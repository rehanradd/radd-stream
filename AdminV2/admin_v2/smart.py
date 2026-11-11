"""Smart-methods patterns, applied exactly where the research allows.

- Resolved cache: TTL + jitter, stale-while-revalidate, single-flight.
  NEVER cached: payment, VIP, adult, or price decisions (those reads are
  always fresh in services.py; this module is never called for them).
- Jobs: bounded queue, 1-3 workers, progress, dead-letter after 3 tries.
- Circuits: per-backend, cause recorded. Transport failure does NOT open
  a host circuit and does NOT mark a live link dead.
- Ranking: direct-first, early-exit, skipped candidates audit-noted.
- SQLite: single-writer lock lives in store.WRITE_LOCK; cache/job tables
  are capped by prune functions below.
"""
import hashlib
import json
import random
import threading
import time

JOB_MAX_QUEUED = 100
JOB_MAX_ATTEMPTS = 3
CACHE_MAX_ROWS = 5000
CIRCUIT_THRESHOLD = 3
CIRCUIT_COOLDOWN_S = 300

_single_flight = {}
_single_flight_lock = threading.Lock()


def jittered_ttl(base_s, rng=None):
    """TTL + random 0-20%, so keys created together do not expire together."""
    rng = rng or random
    return int(base_s * (1.0 + rng.random() * 0.20))


def cache_key(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def cache_put(conn, key, backend, value, ttl_s, stale_window_s=3600):
    now = int(time.time())
    ttl = jittered_ttl(ttl_s)
    conn.execute(
        "INSERT OR REPLACE INTO resolved_cache "
        "(cache_key, backend, quality, value_json, expires_at, stale_until, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (key, backend, "full", json.dumps(value), now + ttl,
         now + ttl + stale_window_s, now),
    )
    conn.execute(
        "DELETE FROM resolved_cache WHERE cache_key NOT IN "
        "(SELECT cache_key FROM resolved_cache ORDER BY created_at DESC LIMIT ?)",
        (CACHE_MAX_ROWS,),
    )
    conn.commit()


def cache_get(conn, key):
    """Return (value, quality) where quality is full/stale/None.

    Stale values are served with quality='stale' so the caller can show
    the age; expired-beyond-stale values return None (recompute).
    """
    row = conn.execute(
        "SELECT * FROM resolved_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if not row:
        return None, None
    now = int(time.time())
    if now <= row["expires_at"]:
        return json.loads(row["value_json"]), "full"
    if now <= row["stale_until"]:
        return json.loads(row["value_json"]), "stale"
    return None, None


def single_flight(key, fn):
    """Only one caller computes a key at once; others wait on it."""
    with _single_flight_lock:
        event = _single_flight.get(key)
        if event is None:
            event = threading.Event()
            _single_flight[key] = event
            owner = True
        else:
            owner = False
    if not owner:
        event.wait(timeout=30)
        return None  # caller re-reads the cache after the owner finished
    try:
        return fn()
    finally:
        with _single_flight_lock:
            _single_flight.pop(key, None)
        event.set()


# --- Circuits ---------------------------------------------------------

def record_circuit(conn, backend, ok, cause):
    """cause: 'transport' or 'host'. Transport never opens the circuit."""
    now = int(time.time())
    row = conn.execute(
        "SELECT * FROM circuits WHERE backend = ?", (backend,)
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO circuits (backend, state, fail_count, transport_strikes, updated_at) "
            "VALUES (?, 'closed', 0, 0, ?)", (backend, now),
        )
        row = {"fail_count": 0, "transport_strikes": 0, "state": "closed"}
    if ok:
        conn.execute(
            "UPDATE circuits SET state='closed', fail_count=0, last_cause=?, updated_at=? "
            "WHERE backend = ?", (cause, now, backend),
        )
    elif cause == "transport":
        conn.execute(
            "UPDATE circuits SET transport_strikes=transport_strikes+1, last_cause=?, "
            "updated_at=? WHERE backend = ?", (cause, now, backend),
        )
    else:
        fails = row["fail_count"] + 1
        state = "open" if fails >= CIRCUIT_THRESHOLD else "closed"
        conn.execute(
            "UPDATE circuits SET fail_count=?, state=?, last_fail_at=?, last_cause=?, "
            "opened_at=CASE WHEN ?='open' THEN ? ELSE opened_at END, updated_at=? "
            "WHERE backend = ?",
            (fails, state, now, cause, state, now, now, backend),
        )
    conn.commit()


def circuit_allows(conn, backend):
    row = conn.execute(
        "SELECT * FROM circuits WHERE backend = ?", (backend,)
    ).fetchone()
    if not row or row["state"] != "open":
        return True
    opened = row["opened_at"] or 0
    if int(time.time()) - opened >= CIRCUIT_COOLDOWN_S:
        conn.execute(
            "UPDATE circuits SET state='half_open' WHERE backend = ?", (backend,)
        )
        conn.commit()
        return True  # half-open: exactly one probe is allowed by the caller
    return False


# --- Ranking ----------------------------------------------------------

BACKEND_COST = {
    "direct_resumable": 0, "direct_playable": 1, "cached": 2,
    "simple_bridge": 3, "complex_bridge": 4,
}


def rank_candidates(candidates):
    """Direct-first, then cached, then simple bridge, then complex.

    candidates: list of dicts with keys backend, kind. Returns the same
    list ordered by backend cost, stable within a cost band.
    """
    return sorted(
        candidates,
        key=lambda c: BACKEND_COST.get(c.get("kind", "complex_bridge"), 4),
    )


def early_exit_probe(candidates, probe_fn):
    """Probe in ranked order; stop on the first passing candidate.

    Returns (winner_or_None, skipped_notes). Skipped notes are the
    audit record for candidates that were NOT probed because a direct
    hit already passed — 'not probed' is never reported as 'dead'.
    """
    ordered = rank_candidates(candidates)
    skipped = []
    for i, cand in enumerate(ordered):
        if probe_fn(cand):
            for later in ordered[i + 1:]:
                skipped.append(
                    "skipped: direct/early hit, not probed: %s" % later.get("backend", "?")
                )
            return cand, skipped
    return None, []


# --- Jobs -------------------------------------------------------------

JOB_KINDS = {"fleet_run", "reprobe", "warmup", "export", "domain_recheck", "prune"}


def enqueue_job(conn, kind, payload, idempotency_key, actor_id):
    if kind not in JOB_KINDS:
        raise ValueError("unknown job kind")
    queued = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','running')"
    ).fetchone()["n"]
    if queued >= JOB_MAX_QUEUED:
        raise ValueError("job queue is full")
    now = int(time.time())
    cur = conn.execute(
        "INSERT OR IGNORE INTO jobs (kind, payload_json, status, idempotency_key, "
        "created_by, created_at, updated_at) VALUES (?,?, 'queued', ?, ?, ?, ?)",
        (kind, json.dumps(payload), idempotency_key, actor_id, now, now),
    )
    if cur.rowcount == 0:
        row = conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return dict(row)
    conn.commit()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def run_job_once(conn, job, handler):
    """Run one job; on failure retry up to JOB_MAX_ATTEMPTS, then dead.

    Dead jobs stay in the jobs table with status='dead' (the dead-letter
    queue): never dropped silently, never retried forever.
    """
    job_id = job["id"]
    conn.execute(
        "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?",
        (int(time.time()), job_id),
    )
    conn.commit()
    try:
        result = handler(job)
        conn.execute(
            "UPDATE jobs SET status='done', progress=100, result_json=?, updated_at=? WHERE id=?",
            (json.dumps(result), int(time.time()), job_id),
        )
    except Exception as exc:  # handler failure -> retry or dead-letter
        attempts = job["attempts"] + 1
        status = "dead" if attempts >= JOB_MAX_ATTEMPTS else "queued"
        conn.execute(
            "UPDATE jobs SET status=?, result_json=?, updated_at=? WHERE id=?",
            (status, json.dumps({"error": str(exc)[:200]}), int(time.time()), job_id),
        )
    conn.commit()
