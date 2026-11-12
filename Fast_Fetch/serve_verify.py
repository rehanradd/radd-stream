#!/usr/bin/env python3
"""Fast_Fetch/serve_verify.py — verified-link serving, strikes, quarantine.

Player Fix v2 (2026-11-12, diagnosis §6.2/§6.3 + research fold-in
`hidden_files/research-fold-in-20261112.md`).

The rule, in one paragraph: the API serves a band's link only when something
recently proved it plays. The proof is a *cached verdict* first — a fresh
banked resolution, or a measured-active verdict inside its TTL — and a live
probe only when the band has no cached verdict at all (never-checked). A
live probe re-resolves the bridge and then knocks on the final file with a
capped 1 KB ranged GET; a 302 from our own redirector is NOT a verification
(the sd band 302s in 0.056 s while its final file 429s). Failures accrue as
strikes in the evidence journal: hide (quarantine) only after 2 consecutive
HARD failures (404/410/DNS) or 3 FLAKY ones (timeout/429/5xx) on separate
days; one success resets the run. Quarantine precedes delete, always;
nothing is ever deleted on expiry alone — an expired signature is
re-resolved, never removed.

What this module does NOT do: it never probes inside a DB transaction (the
caller probes, then writes — WAL, single writer, batched); it never
bulk-deletes; it never trusts ``expires_at`` from the DB (zero rows carry
one); and it never treats a transport failure on OUR side (timeout reaching
the host is flaky evidence, but TLS/DNS-resolution failures of our own
stack are not) as a verdict about the link. Transport causes record
nothing — the poison-cache guard (``batch_is_poisoned``) makes that a
batch rule too: when over half a batch gets no answer at all, our network
is down, not the internet, and nothing is recorded.

Thresholds are operator knobs: ``thresholds()`` reads the panel's
``quarantine_min_failures`` / ``quarantine_min_days`` when a panel is
wired and falls back to the constants below otherwise.

Host priority from measurement (user idea, 20:18 PKT 2026-11-12): which
hosts actually work is measured, then the measured live-rate orders the
serve-time choice — best/most-active hosts first, weak hosts last. The
measurement lives in ``host_health`` (``probes``/``successes`` per host,
counted by every probe outcome, not just the circuit's failure run);
``seed_host_ranking`` loads a ranking produced by a link check (the first
seed is the Salaar 317-link check across 61 hosts); ``host_rank_score``
is what the serve-time tier verification sorts by. The circuit breaker
is seeded from the same measurement: a host measured dead starts with
its circuit open, a host measured weak starts one strike from open.
Unmeasured hosts sort neutral (0.5) — unknown is neither trusted nor
condemned.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone

#: App-facing freshness: a banked resolution counts as a verified answer
#: only this long after it was resolved (diagnosis §6.4.3 — signed URLs
#: expire, and a banked resolution goes stale).
VERIFIED_FRESHNESS_S = 600.0
#: Serve-time verification probes this many candidates per band, in
#: parallel; the first verified answer wins (§6.2, §6.4.1).
VERIFY_CANDIDATES_PER_BAND = 3
#: Total wait for one title's verification round. One slow probe, not the
#: sum — candidates run concurrently, so the detail call is bounded by
#: this, never by 3 bands x 3 candidates in sequence.
VERIFY_TIMEOUT_S = 10.0
#: The final-file probe: total budget, and the capped ranged read
#: (research §2 — Range bytes=0-1023, read at most 1 KB then close, even
#: when the server ignores Range and answers 200 with the whole file).
PROBE_TIMEOUT_S = 5.0
PROBE_SAMPLE_BYTES = 1024

#: Evidence TTL tiers (research §3): a measured verdict is trusted this
#: long before the link is due a re-check. Hot = played recently (24 h);
#: warm = measured alive within a week; cold / never played = 30 d.
#: Failing links re-check after ~20 h with back-off, not on every open.
TTL_HOT_S = 24 * 3600.0
TTL_WARM_S = 7 * 24 * 3600.0
TTL_COLD_S = 30 * 24 * 3600.0
FAILING_RECHECK_S = 20 * 3600.0

#: Strike rule (research §3, sharpens diagnosis §6.3's "3 failures across
#: ≥ 2 days"): hide only after this many consecutive failures of one kind,
#: on separate days; one success resets the run.
STRIKE_HARD_MIN = 2
STRIKE_FLAKY_MIN = 3
STRIKE_MIN_DAYS = 2

#: Host circuit breaker (research §4): after this many consecutive
#: endpoint-answered failures for one host, skip all that host's links
#: with doubling back-off from 2 min, capped at 1 h, until one probe
#: succeeds. One host probe stands in for thousands of file probes.
HOST_CIRCUIT_MIN_FAILURES = 3
HOST_CIRCUIT_BASE_S = 120.0
HOST_CIRCUIT_MAX_S = 3600.0

#: Host priority from measurement (user idea, 20:18 PKT 2026-11-12).
#: A host with this live-rate or worse (and enough probes) is measured
#: weak; a host at zero with enough probes is measured dead. The neutral
#: rank for an unmeasured host — unknown is neither trusted nor condemned.
HOST_WEAK_LIVE_RATE = 0.25
HOST_WEAK_MIN_PROBES = 5
HOST_DEAD_MIN_PROBES = 3
HOST_UNMEASURED_RANK = 0.5

#: Poison-cache guard (research §3): over this fraction of a batch with no
#: answer at all means our network is down — record nothing.
POISON_NO_ANSWER_FRACTION = 0.5

#: Sibling promotion (research §5): a failing sample promotes this many
#: same-movie/same-host siblings to a full check, per failure.
SIBLING_PROMOTION_CAP = 5
SIBLING_PROMOTION_RUN_CAP = 50

#: States the cleanup layer treats as dead for quarantine purposes.
DEAD_STATES = ("dead", "broken", "gone")
QUARANTINED_STATE = "quarantined"

#: Protocols a final URL must answer with to count as playable media.
#: ``html_page`` is a bridge/soft-404 page, ``embed`` is a viewer page —
#: neither plays here, whatever the status code says.
PLAYABLE_PROTOCOLS = ("hls", "dash", "progressive")

#: Failure kinds that never strike: our side failed to reach the endpoint
#: (TLS, reset, connection error). DNS is NOT here — research §3 counts
#: DNS with 404/410 as HARD evidence about the endpoint.
TRANSPORT_REASONS = ("tls", "conn_reset", "conn_error", "transport")
#: Reasons that mean "we got no answer at all" (poison-cache guard).
NO_ANSWER_REASONS = ("timeout", "dns", "transport", "tls", "conn_reset",
                     "conn_error", "resolve_failed", "final_unreachable")

#: Query params that name a real expiry instant (epoch seconds). ``t`` is
#: deliberately NOT here: MovieBox's ``t`` is the SIGNING time, not an
#: expiry — treating it as one would kill every signed link at birth.
EXPIRY_PARAMS = ("expires", "exp", "expiry", "valid_until", "validuntil")

#: Tracking params dropped when normalising a URL for dedupe.
TRACKING_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_term",
                   "utm_content", "fbclid", "gclid", "msclkid", "_ga",
                   "mc_cid", "mc_eid")


# ── pure helpers ─────────────────────────────────────────────────────────

def normalise_url(url: str) -> str:
    """One canonical form for dedupe: fragment stripped, host lower-cased,
    query params sorted, tracking params dropped.

    The same file under several URLs is checked once. A URL that cannot be
    parsed normalises to ``""`` and never dedupes anything else.
    """
    try:
        parts = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    host = parts.netloc.lower()
    params = []
    for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in TRACKING_PARAMS:
            continue
        params.append((key, value))
    params.sort()
    query = urllib.parse.urlencode(params)
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), host, parts.path, query, ""))


def url_expiry_past(url: str, *, now: float | None = None) -> bool:
    """True when the URL carries an explicit expiry instant already past.

    Only ``expires``/``exp``-family params count — never ``t`` (signing
    time). No expiry param, or an unparsable one, means "no verdict".
    """
    moment = time.time() if now is None else float(now)
    try:
        query = dict(urllib.parse.parse_qsl(
            urllib.parse.urlsplit(str(url or "")).query, keep_blank_values=True))
    except ValueError:
        return False
    for key in EXPIRY_PARAMS:
        raw = query.get(key)
        if raw is None:
            continue
        try:
            stamp = float(raw)
        except (TypeError, ValueError):
            continue
        if 1_000_000_000 < stamp < 3_000_000_000 and stamp < moment:
            return True
    return False


def classify_failure(http_status: int = 0, error: str = "") -> str:
    """One probe failure -> ``hard`` | ``flaky`` | ``transport`` | ``no_verdict``.

    Hard (404/410/DNS) is evidence the endpoint is gone; flaky
    (timeout/429/5xx) is evidence this attempt failed; transport is OUR
    side failing (TLS/reset/connect) and is never evidence about the link;
    no_verdict is a refusal to look (blocklisted/invalid URL).
    """
    status = int(http_status or 0)
    err = str(error or "").strip().lower()
    if err in ("blocked_target", "blocklisted", "invalid_url"):
        return "no_verdict"
    if status in (404, 410, 451) or err in ("dns", "dns_error") \
            or err.startswith("dns"):
        return "hard"
    if status == 429 or status >= 500 or err in ("timeout", "redirect_loop") \
            or err.startswith("timeout"):
        return "flaky"
    if status and 400 <= status < 500:
        return "hard"
    if err in TRANSPORT_REASONS or err.startswith("conn_error"):
        return "transport"
    if status or err:
        return "flaky"
    return "no_verdict"


def is_no_answer(result) -> bool:
    """True when a probe got no HTTP answer at all (status 0, not ok)."""
    if isinstance(result, dict):
        return (not result.get("ok")) and int(result.get("http_status") or 0) == 0
    return (not getattr(result, "ok", False)) \
        and int(getattr(result, "http_status", 0) or 0) == 0


def batch_is_poisoned(results) -> bool:
    """Poison-cache guard: over half the batch with no answer means our
    network is down, not the internet — the caller must record nothing."""
    rows = list(results or [])
    if not rows:
        return False
    no_answer = sum(1 for row in rows if is_no_answer(row))
    return no_answer / len(rows) > POISON_NO_ANSWER_FRACTION


def _epoch_of(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            stamp = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        return stamp.replace(tzinfo=timezone.utc).timestamp()
    return None


def is_fresh_verified(link, *, now: float | None = None) -> bool:
    """True when the link carries a ``verified_at`` stamp inside the
    app-facing freshness window (§6.2.5/§6.4.3)."""
    moment = time.time() if now is None else float(now)
    row = link if isinstance(link, dict) else dict(link)
    stamp = _epoch_of(row.get("verified_at"))
    return stamp is not None and 0 <= moment - stamp <= VERIFIED_FRESHNESS_S


def is_known_good(link, *, now: float | None = None) -> bool:
    """True when the link's own cached verdict is good enough to serve
    without a live probe: a fresh ``verified_at`` stamp, or a measured
    active verdict (HTTP 200–399) inside the hot TTL (24 h).

    Anything older, unchecked, or expired is NOT known-good — the caller
    must probe it live (bounded) rather than serve on trust.
    """
    moment = time.time() if now is None else float(now)
    row = link if isinstance(link, dict) else dict(link)
    if is_fresh_verified(row, now=moment):
        return True
    state = str(row.get("status") or row.get("state") or "").lower()
    if state not in ("active", "live", "ok"):
        return False
    http_status = row.get("http_status")
    try:
        http_status = int(http_status) if http_status is not None else 0
    except (TypeError, ValueError):
        return False
    if not 200 <= http_status < 400:
        return False
    checked = _epoch_of(row.get("last_checked_at") or row.get("last_evidence_at"))
    return checked is not None and 0 <= moment - checked <= TTL_HOT_S


def ttl_for(link) -> float:
    """How long this link's verdict is trusted before it is due a
    re-check: failing links ~20 h, measured-alive links 7 d, everything
    else (cold / never played) 30 d."""
    row = link if isinstance(link, dict) else dict(link)
    state = str(row.get("status") or row.get("state") or "").lower()
    if state in DEAD_STATES or state in ("expired", "unreachable"):
        return FAILING_RECHECK_S
    if row.get("http_status") and row.get("last_checked_at"):
        return TTL_WARM_S
    return TTL_COLD_S


def recheck_due(link, *, now: float | None = None) -> bool:
    """Scheduling predicate for the worker/sweep: due when there is no
    evidence at all, or the last evidence is older than the link's TTL.
    Computed, not stored — there is no ``next_check_at`` column; the
    worker query is ``last_evidence_at < now - ttl``."""
    moment = time.time() if now is None else float(now)
    row = link if isinstance(link, dict) else dict(link)
    checked = _epoch_of(row.get("last_checked_at") or row.get("last_evidence_at"))
    if checked is None:
        return True
    return moment - checked > ttl_for(row)


def thresholds() -> dict:
    """Quarantine thresholds, operator knobs first, constants otherwise.

    ``quarantine_min_failures`` is the flaky minimum (hard stays 2 by the
    research rule); ``quarantine_min_days`` is the separate-days minimum.
    A missing/unwired panel answers the constants — never an error.
    """
    out = {"min_hard": STRIKE_HARD_MIN, "min_flaky": STRIKE_FLAKY_MIN,
           "min_days": STRIKE_MIN_DAYS}
    try:
        import panel_feed
        knobs = panel_feed.read_tuning_knobs()
    except Exception:      # noqa: BLE001 — an unwired panel means defaults
        return out
    try:
        out["min_flaky"] = max(1, int(knobs.get("quarantine_min_failures")
                                      or STRIKE_FLAKY_MIN))
        out["min_days"] = max(1, int(knobs.get("quarantine_min_days")
                                     or STRIKE_MIN_DAYS))
    except (TypeError, ValueError):
        pass
    return out


# ── the final-file probe ─────────────────────────────────────────────────

def _result_fields(result) -> dict:
    if isinstance(result, dict):
        return result
    return {"ok": bool(getattr(result, "ok", False)),
            "http_status": int(getattr(result, "http_status", 0) or 0),
            "protocol": str(getattr(result, "protocol", "") or ""),
            "content_type": str(getattr(result, "content_type", "") or ""),
            "size_bytes": int(getattr(result, "size_bytes", 0) or 0),
            "error": str(getattr(result, "error", "") or "")}


def _default_prober(url: str, *, timeout: float):
    import link_health
    return link_health.probe(url, timeout=timeout,
                             sample_bytes=PROBE_SAMPLE_BYTES)


def verify_final_url(url: str, *, prober=None,
                     timeout: float = PROBE_TIMEOUT_S,
                     now: float | None = None) -> tuple[bool, str, dict]:
    """Knock on a resolved final URL and say whether it is playable media.

    Returns ``(verified, reason, fields)``. Verified needs: an explicit
    expiry that has not passed (checked without a probe), HTTP 200–399,
    a media protocol (hls/dash/progressive — ``html_page``/``embed`` is a
    bridge or soft-404 page, never a file), a non-HTML content type, and
    a non-empty body. A 200 with a dead-marker body is what the protocol
    check catches: hosts serve "file removed" pages as ``text/html``.
    """
    moment = time.time() if now is None else float(now)
    if url_expiry_past(url, now=moment):
        return False, "expired_url", {}
    probe = prober or _default_prober
    try:
        result = probe(str(url), timeout=timeout)
    except Exception as exc:      # noqa: BLE001 — a prober fault is "no answer"
        return False, "transport", {"error": type(exc).__name__}
    fields = _result_fields(result)
    status = int(fields.get("http_status") or 0)
    error = str(fields.get("error") or "")
    if not fields.get("ok"):
        if status:
            return False, "http_%d" % status, fields
        if error:
            return False, error, fields
        return False, "final_unreachable", fields
    if not 200 <= status < 400:
        return False, "http_%d" % status, fields
    protocol = str(fields.get("protocol") or "")
    if protocol not in PLAYABLE_PROTOCOLS:
        # A 200 that is a page, not media: soft-404 / bridge / webview.
        return False, "webview", fields
    content_type = str(fields.get("content_type") or "").lower()
    if content_type.startswith("text/html"):
        return False, "webview", fields
    if int(fields.get("size_bytes") or 0) == 0:
        # Free header signal (research §4): Content-Length 0 on a video
        # URL is dead without reading a body.
        return False, "empty_file", fields
    return True, "ok", fields


# ── host circuit breaker ─────────────────────────────────────────────────

_HOST_HEALTH_DDL = """
CREATE TABLE IF NOT EXISTS host_health (
    host TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    opened_until REAL NOT NULL DEFAULT 0,
    backoff_s REAL NOT NULL DEFAULT 120,
    probes INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    measured_at REAL NOT NULL DEFAULT 0
)
"""


def _ensure_host_health(conn) -> bool:
    try:
        conn.execute(_HOST_HEALTH_DDL)
        have = {row[1] for row in conn.execute(
            "PRAGMA table_info(host_health)").fetchall()}
        for column in ("probes", "successes"):
            if column not in have:
                conn.execute(
                    "ALTER TABLE host_health ADD COLUMN %s"
                    " INTEGER NOT NULL DEFAULT 0" % column)
        if "measured_at" not in have:
            conn.execute("ALTER TABLE host_health ADD COLUMN measured_at"
                         " REAL NOT NULL DEFAULT 0")
        return True
    except sqlite3.Error:
        return False


def _host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(str(url or "")).netloc.lower()
    except ValueError:
        return ""


def circuit_open(conn, host: str, *, now: float | None = None) -> bool:
    """True while the circuit for *host* is open (skip all its links)."""
    if conn is None or not host:
        return False
    moment = time.time() if now is None else float(now)
    if not _ensure_host_health(conn):
        return False
    try:
        row = conn.execute("SELECT opened_until FROM host_health WHERE host = ?",
                           (str(host),)).fetchone()
    except sqlite3.Error:
        return False
    if row is None:
        return False
    try:
        return float(row[0]) > moment
    except (TypeError, ValueError):
        return False


def record_host_failure(conn, host: str, *, now: float | None = None) -> None:
    """Count one endpoint-answered failure for *host*; open the circuit
    at the threshold with doubling back-off (2 min → 1 h cap).

    Every failure is also a measurement: ``probes`` counts it, so the
    host's live-rate (see ``host_live_rate``) is earned by the same
    outcomes that drive the circuit.
    """
    if conn is None or not host:
        return
    moment = time.time() if now is None else float(now)
    if not _ensure_host_health(conn):
        return
    try:
        row = conn.execute("SELECT consecutive_failures, backoff_s FROM host_health"
                           " WHERE host = ?", (str(host),)).fetchone()
        failures = int(row[0]) + 1 if row is not None else 1
        backoff = float(row[1]) if row is not None and row[1] else HOST_CIRCUIT_BASE_S
        opened_until = 0.0
        if failures >= HOST_CIRCUIT_MIN_FAILURES:
            opened_until = moment + backoff
            backoff = min(backoff * 2, HOST_CIRCUIT_MAX_S)
        conn.execute(
            "INSERT INTO host_health (host, consecutive_failures, opened_until,"
            " backoff_s, probes, successes, measured_at)"
            " VALUES (?, ?, ?, ?, 1, 0, ?)"
            " ON CONFLICT(host) DO UPDATE SET consecutive_failures = ?,"
            " opened_until = ?, backoff_s = ?,"
            " probes = host_health.probes + 1, measured_at = ?",
            (str(host), failures, opened_until, backoff, moment,
             failures, opened_until, backoff, moment))
    except sqlite3.Error:
        pass


def record_host_success(conn, host: str, *, now: float | None = None) -> None:
    """One success closes the circuit: failures reset to zero.

    Also a measurement: ``probes`` and ``successes`` both count it.
    """
    if conn is None or not host:
        return
    moment = time.time() if now is None else float(now)
    if not _ensure_host_health(conn):
        return
    try:
        conn.execute(
            "INSERT INTO host_health (host, consecutive_failures, opened_until,"
            " backoff_s, probes, successes, measured_at)"
            " VALUES (?, 0, 0, ?, 1, 1, ?)"
            " ON CONFLICT(host) DO UPDATE SET"
            " consecutive_failures = 0, opened_until = 0, backoff_s = ?,"
            " probes = host_health.probes + 1,"
            " successes = host_health.successes + 1, measured_at = ?",
            (str(host), HOST_CIRCUIT_BASE_S, moment,
             HOST_CIRCUIT_BASE_S, moment))
    except sqlite3.Error:
        pass


def host_live_rate(conn, host: str):
    """The host's measured live-rate (successes / probes), or None when
    the host has never been measured. The measurement is the probe
    outcomes the circuit already records — no second source of truth."""
    if conn is None or not host:
        return None
    if not _ensure_host_health(conn):
        return None
    try:
        row = conn.execute("SELECT probes, successes FROM host_health"
                           " WHERE host = ?", (str(host),)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        probes, successes = int(row[0]), int(row[1])
    except (TypeError, ValueError):
        return None
    if probes <= 0:
        return None
    return successes / probes


def host_rank_score(conn, host: str) -> float:
    """Sort key for serve-time choice: the measured live-rate, or the
    neutral 0.5 for an unmeasured host. Best/most-active first, weak
    last, unknown in the middle."""
    rate = host_live_rate(conn, host)
    return float(rate) if rate is not None else HOST_UNMEASURED_RANK


def seed_host_ranking(conn, ranking, *, now: float | None = None) -> dict:
    """Load a measured per-host ranking into ``host_health`` — the
    seeding entry point for a link check's results.

    ``ranking`` is an iterable of dicts with ``host`` plus ``probes`` and
    ``successes``, or ``live_rate`` and ``probes`` (successes are derived).
    The circuit is seeded from the same measurement: a host measured dead
    (live-rate 0, enough probes) starts with its circuit OPEN; a host
    measured weak (live-rate under ``HOST_WEAK_LIVE_RATE``, enough probes)
    starts one strike from open; anything else starts clean. Seeding
    supersedes the cold state — a host measured good is not held to an
    old failure run. Returns ``{hosts_seeded, circuits_opened}``.
    """
    moment = time.time() if now is None else float(now)
    seeded = 0
    opened = 0
    if conn is None or not _ensure_host_health(conn):
        return {"hosts_seeded": 0, "circuits_opened": 0}
    for entry in ranking or ():
        try:
            host = str((entry or {}).get("host") or "").strip().lower()
            probes = int((entry or {}).get("probes") or 0)
            successes = (entry or {}).get("successes")
            if successes is None:
                rate = (entry or {}).get("live_rate")
                successes = round(float(rate) * probes) if rate is not None else 0
            successes = int(successes)
        except (TypeError, ValueError, AttributeError):
            continue
        if not host or probes <= 0:
            continue
        successes = max(0, min(probes, successes))
        rate = successes / probes
        failures = 0
        opened_until = 0.0
        backoff = HOST_CIRCUIT_BASE_S
        if rate == 0.0 and probes >= HOST_DEAD_MIN_PROBES:
            failures = HOST_CIRCUIT_MIN_FAILURES
            opened_until = moment + backoff
            backoff = min(backoff * 2, HOST_CIRCUIT_MAX_S)
            opened += 1
        elif rate < HOST_WEAK_LIVE_RATE and probes >= HOST_WEAK_MIN_PROBES:
            failures = HOST_CIRCUIT_MIN_FAILURES - 1
        try:
            conn.execute(
                "INSERT INTO host_health (host, consecutive_failures,"
                " opened_until, backoff_s, probes, successes, measured_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(host) DO UPDATE SET consecutive_failures = ?,"
                " opened_until = ?, backoff_s = ?, probes = ?,"
                " successes = ?, measured_at = ?",
                (host, failures, opened_until, backoff, probes, successes,
                 moment, failures, opened_until, backoff, probes, successes,
                 moment))
            seeded += 1
        except sqlite3.Error:
            continue
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return {"hosts_seeded": seeded, "circuits_opened": opened}


# ── measured rankings from link-check CSVs ────────────────────────────────

CHECK_VERDICT_ALIVE = "alive"
CHECK_VERDICT_DEAD = "dead"
#: A page_alive row whose error carries this prefix answered 200 HTML
#: saying the file is gone — a soft-404, which the probe recipe counts
#: as DEAD (see the research fold-in), not as an unproven page.
CHECK_SOFT404_PREFIX = "soft404-marker:"


def _check_csv_host(row, bridges):
    """The host key for one check row: the bridge domain when the sources
    join is available, else the probed URL's domain."""
    source_id = str(row.get("source_id") or "").strip()
    if bridges is not None and source_id in bridges:
        return bridges[source_id]
    return _host_of(row.get("url_probed"))


def ranking_from_probe_csvs(check_path, sources_path=None):
    """Aggregate a link-check CSV into a seedable per-host ranking.

    Reads the check CSV (columns: source_id, host_or_site, quality_band,
    url_probed, http_code, content_type, verdict, elapsed_ms, error) and,
    when ``sources_path`` is given, joins each row to its bridge domain
    via the sources CSV (source_id -> source_url); ``sources_path`` may
    be one path or a sequence of paths (the multi-title check reuses
    Salaar's 317 rows, whose sources live in a second file). The host
    key is ALWAYS the bridge domain — that is the key the serve-time
    ranking and the circuit breaker look up (``_source_host`` reads
    ``download_sources.source_url``), and a label (fastdl, hubcloud)
    spans several bridge domains while one bridge domain serves several
    labels, so label keys would never match a runtime lookup. Without
    the sources join the probed URL's domain is the fallback key (the
    file host — weaker, because a shared CDN blurs bridges — documented,
    not hidden).

    Only endpoint-answered verdicts count: alive is a success, dead is a
    failure, and a page_alive row carrying a soft-404 marker is a
    failure too (the page answered that the file is gone). Unknown,
    page_alive without a marker, and expired are NOT counted — no answer
    is not a failure (poison-cache rule) and an expired signature is a
    re-sign, not death. Hosts with no answered probe are omitted: there
    is nothing measured to seed. Returns a list of dicts — host, probes
    (alive + dead), successes (alive), alive, dead, unknown, page_alive,
    n — sorted by live-rate desc, then probes desc, so the best-measured
    hosts come first. The ranking is DATA, not a code order: the next
    check (multi-title, ordered 2026-11-12) re-seeds it, and the owner
    decides the final priority order.
    """
    bridges = None
    if sources_path is not None:
        if isinstance(sources_path, (str, os.PathLike)):
            sources_path = [sources_path]
        bridges = {}
        for path in sources_path:
            with open(path, newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    source_id = str(row.get("source_id") or "").strip()
                    domain = _host_of(row.get("source_url"))
                    if source_id and domain:
                        bridges[source_id] = domain
    counts: dict = {}
    with open(check_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            host = _check_csv_host(row, bridges)
            if not host:
                continue
            verdict = str(row.get("verdict") or "").strip().lower()
            error = str(row.get("error") or "")
            bucket = counts.setdefault(
                host, {"host": host, "probes": 0, "successes": 0,
                       "alive": 0, "dead": 0, "unknown": 0,
                       "expired": 0, "page_alive": 0, "n": 0})
            bucket["n"] += 1
            if verdict == CHECK_VERDICT_ALIVE:
                bucket["alive"] += 1
                bucket["successes"] += 1
                bucket["probes"] += 1
            elif verdict == CHECK_VERDICT_DEAD:
                bucket["dead"] += 1
                bucket["probes"] += 1
            elif verdict == "page_alive" \
                    and error.startswith(CHECK_SOFT404_PREFIX):
                bucket["dead"] += 1
                bucket["probes"] += 1
            elif verdict == "page_alive":
                bucket["page_alive"] += 1
            elif verdict == "expired":
                # A dead signature, not a dead link: re-resolve at serve
                # time, never counted for or against the host.
                bucket["expired"] += 1
            else:
                bucket["unknown"] += 1
    ranked = [bucket for bucket in counts.values() if bucket["probes"] > 0]
    ranked.sort(key=lambda bucket: (-(bucket["successes"] / bucket["probes"]),
                                    -bucket["probes"], bucket["host"]))
    return ranked


def seed_from_probe_csvs(conn, check_path, sources_path=None, *, now=None):
    """Seed ``host_health`` from a link check's CSVs, in one call.

    Aggregates with ``ranking_from_probe_csvs`` and loads it via
    ``seed_host_ranking``. Returns the ranking plus the seed outcome:
    ``{ranking, hosts_seeded, circuits_opened}``.
    """
    ranking = ranking_from_probe_csvs(check_path, sources_path)
    outcome = seed_host_ranking(conn, ranking, now=now)
    return {"ranking": ranking,
            "hosts_seeded": outcome["hosts_seeded"],
            "circuits_opened": outcome["circuits_opened"]}


# ── failure evidence ─────────────────────────────────────────────────────

def _fail_cause_for(reason: str, http_status: int = 0):
    """Map a verification reason onto the resolver's ``fail_cause``
    vocabulary for the failure circuit: an HTTP status int, ``not_media``
    for a page that answered, or None (ambiguous/transport — never strikes)."""
    if http_status:
        return int(http_status)
    if reason in ("webview", "not_media"):
        return "not_media"
    return None


def record_probe_failure(conn, source_id: int, reason: str, *,
                         http_status: int = 0, final_url: str = "",
                         now: float | None = None) -> dict:
    """Write one endpoint-answered failure to every place that must see it.

    Transport reasons record NOTHING (our side failed, not the link).
    A hard/flaky failure: (1) the resolved-cache circuit (only on an
    affirmative endpoint verdict), (2) the 12 h negative cache — hard
    failures only, so a transient 429/5xx never blocks a later press,
    (3) the ``cat_link_evidence`` journal, folded via
    ``catalog_v2.apply_evidence`` (state + ``last_evidence_at`` + reason),
    and (4) the host circuit breaker. Best-effort throughout: a missing
    table or an unreadable DB is "no evidence recorded", never an error.
    Never called from inside a probe — the caller probes first, then
    records, so no probe ever runs inside a DB transaction.
    """
    moment = time.time() if now is None else float(now)
    kind = classify_failure(http_status, reason)
    if kind in ("transport", "no_verdict"):
        return {"recorded": False, "kind": kind}
    recorded: dict = {"recorded": True, "kind": kind, "journal": False,
                      "negative_cache": False, "host": False}
    host = _host_of(final_url)
    # 1. Resolved-cache circuit — affirmative endpoint verdicts only.
    try:
        import resolved_cache
        cause = _fail_cause_for(reason, http_status)
        if cause is not None:
            resolved_cache.note_failure_from_probe(
                conn, int(source_id), {"fail_cause": cause})
    except Exception:      # noqa: BLE001 — evidence is best-effort
        pass
    # 2. Negative cache — hard failures only, on THIS connection.
    # Never via fast_fetch._record_resolve_failure (it opens its own
    # connection to the same file): this function is called while the
    # caller holds uncommitted writes on `conn`, and a second connection
    # would block on that write lock until busy_timeout (30 s) and then
    # fail silently — the write would never land.
    if kind == "hard":
        try:
            import fast_fetch
            fast_fetch._record_resolve_failure_on(
                conn, int(source_id), "probe_failed", now=moment)
            recorded["negative_cache"] = True
        except Exception:      # noqa: BLE001 — see above
            pass
    # 3. Evidence journal + fold (state=dead etc. is _blend_link's call).
    # The journal row is the durable fact; the fold is derived. If the
    # fold faults, the row is still committed — a failed fold must not
    # eat the evidence.
    try:
        import catalog_v2
        if catalog_v2._has_table(conn, "cat_links") \
                and catalog_v2._has_table(conn, "cat_link_evidence"):
            row = conn.execute("SELECT id FROM cat_links WHERE ledger_link_id = ?",
                               (int(source_id),)).fetchone()
            if row is not None:
                try:
                    catalog_v2.apply_evidence(conn, [{
                        "link_id": int(row[0]), "probed_at": moment, "ok": False,
                        "protocol": "", "http_status": int(http_status or 0),
                        "content_type": "", "size_bytes": 0, "latency_ms": 0,
                        "speed_mbps": 0.0, "accepts_ranges": False,
                        "error": str(reason), "url": str(final_url or ""),
                    }])
                except Exception:      # noqa: BLE001 — fold fault: keep the row
                    try:
                        conn.commit()
                    except Exception:      # noqa: BLE001 — best-effort
                        pass
                recorded["journal"] = True
    except Exception:      # noqa: BLE001 — see above
        pass
    # 4. Host circuit breaker.
    if host:
        try:
            record_host_failure(conn, host, now=moment)
            recorded["host"] = True
        except Exception:      # noqa: BLE001 — see above
            pass
    return recorded


# ── the candidate check ──────────────────────────────────────────────────

def verify_candidate(source_id: int, *, resolver=None, prober=None,
                     conn=None, now: float | None = None,
                     record_evidence: bool = True,
                     live: bool = True) -> dict:
    """Verify one link (a ``download_sources`` id) is playable right now.

    Order: (1) a fresh banked resolution — no network; (2) the host
    circuit — a host already known down is not re-probed; (3) live
    re-resolve + final-file probe. A 403 from the final file is an expired
    signature, NOT death: re-resolve/re-sign ONCE, and only if the fresh
    signature also fails does failure evidence accrue. A verified success
    is banked for the next press. With ``record_evidence=False`` failures
    are returned with their evidence payload but not written — the caller
    (serve-time batch) applies the poison-cache guard first and records
    afterwards.

    ``live=False`` is the detail fast path: steps (1)–(2) are the whole
    verdict, and a link with neither a fresh banked resolution nor a
    known-down host answers ``unchecked`` — no network is touched, so
    the caller never waits on a probe. The live pass runs in the
    background and banks its verdicts for the next call.
    """
    moment = time.time() if now is None else float(now)
    source_id = int(source_id)
    result: dict = {"verified": False, "reason": "unchecked",
                    "final_url": "", "verified_at": None, "evidence": None}

    def _fail(reason: str, *, http_status: int = 0, final_url: str = ""):
        result.update({"verified": False, "reason": reason,
                       "final_url": final_url})
        kind = classify_failure(http_status, reason)
        if kind in ("hard", "flaky"):
            result["evidence"] = {"source_id": source_id, "reason": reason,
                                  "http_status": int(http_status or 0),
                                  "final_url": final_url}
            if record_evidence and conn is not None:
                record_probe_failure(conn, source_id, reason,
                                     http_status=http_status,
                                     final_url=final_url, now=moment)
        return result

    # 1. Fresh banked resolution — the verified answer, no network.
    if conn is not None:
        try:
            import resolved_cache
            hit = resolved_cache.lookup_cache(conn, source_id, want="watch")
        except Exception:      # noqa: BLE001 — a cache fault is "not banked"
            hit = None
        if hit:
            resolved_at = _epoch_of(hit.get("resolved_at"))
            if resolved_at is not None \
                    and 0 <= moment - resolved_at <= VERIFIED_FRESHNESS_S:
                result.update({"verified": True, "reason": "banked",
                               "final_url": str(hit.get("url") or ""),
                               "verified_at": resolved_at})
                return result
    # 2. Host circuit — checked against the bridge host we already know.
    bridge_host = ""
    if conn is not None:
        try:
            row = conn.execute("SELECT source_url FROM download_sources"
                               " WHERE id = ?", (source_id,)).fetchone()
            bridge_host = _host_of(row[0]) if row is not None else ""
        except sqlite3.Error:
            bridge_host = ""
        if bridge_host and circuit_open(conn, bridge_host, now=moment):
            result.update({"verified": False, "reason": "host_circuit_open"})
            return result
    if not live:
        # Cached-only call (the detail fast path): steps (1)–(2) are
        # the whole verdict — a fresh banked resolution or a known-down
        # host — and a link with neither is "unchecked", not failed.
        # No network is touched, so the caller never waits on a probe.
        return result
    # 3. Live re-resolve, then probe the final file.
    if resolver is None:
        import viewer as _viewer
        resolver = _viewer._resolve_coalesced
    try:
        res = resolver(source_id)
    except Exception:      # noqa: BLE001 — a resolver fault is transport
        return _fail("transport")
    if not isinstance(res, dict) or not res.get("success") \
            or not res.get("url"):
        cause = res.get("fail_cause") if isinstance(res, dict) else None
        if isinstance(cause, int):
            return _fail("http_%d" % cause, http_status=cause)
        if cause == "not_media":
            return _fail("webview")
        if isinstance(cause, str) and cause:
            return _fail("transport")
        return _fail("resolve_failed")
    final_url = str(res["url"])
    verified, reason, fields = verify_final_url(
        final_url, prober=prober, timeout=PROBE_TIMEOUT_S, now=moment)
    if verified:
        if conn is not None:
            try:
                import resolved_cache
                banked = dict(res)
                banked["url"] = final_url
                resolved_cache.record_resolved_cache(conn, source_id, banked)
            except Exception:      # noqa: BLE001 — banking is best-effort
                pass
            record_host_success(conn, _host_of(final_url))
        result.update({"verified": True, "reason": "ok",
                       "final_url": final_url, "verified_at": moment})
        return result
    if reason == "http_403":
        # Expired signature, not death: re-resolve/re-sign ONCE. Only if
        # the fresh signature also fails does evidence accrue.
        try:
            res2 = resolver(source_id)
        except Exception:      # noqa: BLE001 — transport on the re-sign
            return _fail("transport")
        if isinstance(res2, dict) and res2.get("success") and res2.get("url"):
            final_url2 = str(res2["url"])
            verified2, reason2, _fields2 = verify_final_url(
                final_url2, prober=prober, timeout=PROBE_TIMEOUT_S, now=moment)
            if verified2:
                if conn is not None:
                    try:
                        import resolved_cache
                        banked = dict(res2)
                        banked["url"] = final_url2
                        resolved_cache.record_resolved_cache(
                            conn, source_id, banked)
                    except Exception:  # noqa: BLE001 — banking is best-effort
                        pass
                    record_host_success(conn, _host_of(final_url2))
                result.update({"verified": True, "reason": "ok",
                               "final_url": final_url2, "verified_at": moment})
                return result
            status2 = int(_fields2.get("http_status") or 0)
            return _fail(reason2, http_status=status2, final_url=final_url2)
        return _fail("resolve_failed")
    status = int(fields.get("http_status") or 0)
    return _fail(reason, http_status=status, final_url=final_url)


# ── strikes, quarantine, delete ──────────────────────────────────────────

def strike_state(conn, cat_link_id: int) -> dict:
    """The trailing failure run for one projected link, from its journal.

    Walks the journal newest-first: consecutive ``ok=0`` rows are the run;
    the first ``ok=1`` resets it (one success resets ``fail_count`` +
    ``first_failed``). Each failure is classified hard/flaky from its own
    HTTP status + error. Returns counts, the run's first/last probe times,
    and how many distinct days it spans (the "separate runs" rule).
    """
    out = {"hard": 0, "flaky": 0, "failures": 0, "first_failed_at": None,
           "last_failed_at": None, "days": 0}
    try:
        rows = conn.execute(
            "SELECT probed_at, ok, http_status, error FROM cat_link_evidence"
            " WHERE link_id = ? ORDER BY probed_at DESC, id DESC",
            (int(cat_link_id),)).fetchall()
    except sqlite3.Error:
        return out
    days: set = set()
    for row in rows:
        ok = row[1]
        try:
            ok = int(ok or 0)
        except (TypeError, ValueError):
            ok = 0
        if ok:
            break
        try:
            probed_at = float(row[0])
        except (TypeError, ValueError):
            continue
        kind = classify_failure(int(row[2] or 0), str(row[3] or ""))
        if kind == "hard":
            out["hard"] += 1
        elif kind == "flaky":
            out["flaky"] += 1
        else:
            # Transport / no-verdict rows are not strikes and do not break
            # the run either: they say nothing about the link.
            continue
        out["failures"] += 1
        days.add(datetime.fromtimestamp(probed_at, tz=timezone.utc).date())
        if out["last_failed_at"] is None:
            out["last_failed_at"] = probed_at
        out["first_failed_at"] = probed_at
    out["days"] = len(days)
    return out


def should_quarantine(strikes: dict, *, min_hard: int = STRIKE_HARD_MIN,
                      min_flaky: int = STRIKE_FLAKY_MIN,
                      min_days: int = STRIKE_MIN_DAYS) -> bool:
    """The strike rule: 2 consecutive HARD or 3 FLAKY failures, on
    separate days. A single bad afternoon never quarantines anything."""
    if int(strikes.get("days") or 0) < int(min_days):
        return False
    return int(strikes.get("hard") or 0) >= int(min_hard) \
        or int(strikes.get("flaky") or 0) >= int(min_flaky)


def quarantine_and_delete_dead_links(conn, *, min_failures: int | None = None,
                                     min_days: int | None = None,
                                     delete: bool = False,
                                     now: float | None = None) -> dict:
    """Quarantine, then (only when asked) delete, per-link, on evidence.

    Phase 1 — quarantine: a link whose folded state is dead/broken/gone
    AND whose journal shows a qualifying strike run is set to
    ``quarantined`` — excluded from ``tiers.score`` entirely (score 0 is
    not enough; exclusion is). Phase 2 — delete (``delete=True`` only):
    a link that is ALREADY quarantined and still qualifies is deleted
    from ``cat_links`` and from ``download_sources`` (via
    ``ledger_link_id``). A link that was never quarantined is never
    deleted, however dead it looks. Expired links are never candidates:
    an expired signature is re-resolved, not removed — "dead" here means
    the bridge no longer yields a playable file after re-resolution.
    No bulk delete ever: every row acted on earned it in its own journal.
    """
    moment = time.time() if now is None else float(now)
    out = {"candidates": 0, "newly_quarantined": 0, "deleted": 0}
    try:
        import catalog_v2
        if not catalog_v2._has_table(conn, "cat_links") \
                or not catalog_v2._has_table(conn, "cat_link_evidence"):
            return out
    except Exception:      # noqa: BLE001 — no projection, no cleanup
        return out
    knobs = thresholds()
    min_flaky = int(min_failures) if min_failures is not None \
        else int(knobs["min_flaky"])
    min_days = int(min_days) if min_days is not None else int(knobs["min_days"])
    try:
        rows = conn.execute(
            "SELECT id, ledger_link_id, state FROM cat_links"
            " WHERE state IN ('dead', 'broken', 'gone', 'quarantined')"
            ).fetchall()
    except sqlite3.Error:
        return out
    has_ledger = True
    try:
        conn.execute("SELECT id FROM download_sources LIMIT 1")
    except sqlite3.Error:
        has_ledger = False
    for row in rows:
        link_id = int(row[0])
        state = str(row[2] or "")
        out["candidates"] += 1
        strikes = strike_state(conn, link_id)
        if state == QUARANTINED_STATE:
            if delete and should_quarantine(
                    strikes, min_flaky=min_flaky, min_days=min_days):
                try:
                    conn.execute("DELETE FROM cat_links WHERE id = ?",
                                 (link_id,))
                    if has_ledger and row[1] is not None:
                        conn.execute("DELETE FROM download_sources WHERE id = ?",
                                     (int(row[1]),))
                    out["deleted"] += 1
                except sqlite3.Error:
                    pass
            continue
        if should_quarantine(strikes, min_flaky=min_flaky, min_days=min_days):
            try:
                conn.execute("UPDATE cat_links SET state = ? WHERE id = ?",
                             (QUARANTINED_STATE, link_id))
                out["newly_quarantined"] += 1
            except sqlite3.Error:
                pass
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return out
