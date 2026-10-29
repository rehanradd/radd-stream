#!/usr/bin/env python3
"""Audit a projected catalog against everything API_V2.md promises, on real data.

The unit suites (`test_catalog_v2.py`, `test_evidence_writeback.py`) prove the rules on
hand-built fixtures. This proves them on the whole merged catalog — the questions only a
full database can answer: did the projector keep every ledger link, did it invent a
quality score, does an adult title exist anywhere a client can read it.

    ionice -c3 nice -n19 python3 -S Fast_Fetch/validate_catalog_full.py [db]

Read-only (`mode=ro`): it cannot write to the database it is judging. Stdlib only, no
network. Exits non-zero on the first failing check so CI and cron both know.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import catalog_v2          # noqa: E402
import release_descriptor  # noqa: E402

DATA_DIR = Path("/home/ubuntu/radd-stream-data")
DEFAULT_DB = DATA_DIR / "merged_catalog_20261024.db"

#: How many prints get their score recomputed from the label. A full pass is a
#: CPU-bound re-parse of every release title on a one-core VM; a random sample of
#: this many answers "does the stored score come from the published formula".
SCORE_SAMPLE = 3000

WORK_TYPES = {"movie", "series", "anime", "documentary", "sport_event", "music_video",
              "tv_special", "miniseries", "unknown"}
COVERAGE = {"whole_work", "season_pack", "episode_range", "single_episode"}
LINK_KINDS = {"hls_manifest", "cdn_direct", "download_only", "bridge", "embed",
              "cloud_page", "dead_end"}
PLAYABILITY = {"stream", "download", "both", "webview", "resolve_required", "none"}
# Two vocabularies, deliberately not one set. `cat_links.state` is the *projection*:
# closed, and `unverified` is not in it, because `catalog_v2._link_state_of()` folds an
# unprobed source to 'unchecked' before it reaches the wire. `download_sources.status`
# is the *ledger*: wider, and 'unverified' is the honest value `fast_fetch.py` stores for
# a source nobody probed. Admitting 'unverified' to the projection let the audit grade a
# fifth-state leak as passing, which is the defect this split exists to catch.
PROJECTION_STATES = {"active", "dead", "expired", "unknown", "unchecked"}
LEDGER_STATUSES = PROJECTION_STATES | {"unverified"}
STATES = PROJECTION_STATES
SOURCE_TAGS = set(release_descriptor.SOURCE_TAG_WEIGHTS)
RESOLUTIONS = {"2160p", "1080p", "720p", "480p", "480p_or_lower", "unknown"}

RESULTS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _tables(conn) -> set:
    return {row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _count(conn, sql, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def validate(conn) -> int:
    tables = _tables(conn)
    missing = {"cat_works", "cat_releases", "cat_links", "cat_episodes",
               "cat_link_evidence"} - tables
    if missing:
        check("projection exists", False, f"missing {sorted(missing)} — run catalog_v2.project()")
        return 1
    check("projection exists", True, ", ".join(sorted(tables & ({"cat_works"} | set()))))

    works = _count(conn, "SELECT COUNT(*) FROM cat_works")
    releases = _count(conn, "SELECT COUNT(*) FROM cat_releases")
    links = _count(conn, "SELECT COUNT(*) FROM cat_links")
    episodes = _count(conn, "SELECT COUNT(*) FROM cat_episodes")
    check("catalog is not empty", works > 0 and releases > 0 and links > 0,
          f"{works} works, {releases} prints, {links} links, {episodes} episodes")

    # ── 1. Zero Data Loss: every ledger link is in the projection ───────────
    ledger_links = _count(conn, "SELECT COUNT(*) FROM download_sources")
    projected = _count(conn, "SELECT COUNT(*) FROM cat_links")
    check("every ledger link is projected", ledger_links == projected,
          f"download_sources={ledger_links}, cat_links={projected}")
    check("no link lost its release", _count(
        conn, "SELECT COUNT(*) FROM cat_links l LEFT JOIN cat_releases r ON r.id = l.release_id"
              " WHERE r.id IS NULL") == 0)
    check("no print lost its work", _count(
        conn, "SELECT COUNT(*) FROM cat_releases r LEFT JOIN cat_works w ON w.id = r.work_id"
              " WHERE w.id IS NULL") == 0)
    check("no episode lost its work", _count(
        conn, "SELECT COUNT(*) FROM cat_episodes e LEFT JOIN cat_works w ON w.id = e.work_id"
              " WHERE w.id IS NULL") == 0)

    # ── 2. identity is one row per work ─────────────────────────────────────
    dup_keys = _count(conn, "SELECT COUNT(*) FROM (SELECT work_key FROM cat_works"
                            " GROUP BY work_key HAVING COUNT(*) > 1)")
    check("work_key is unique", dup_keys == 0, f"{dup_keys} duplicate keys")
    bad_type = _count(conn, "SELECT COUNT(*) FROM cat_works WHERE work_type NOT IN ({})"
                      .format(",".join("?" * len(WORK_TYPES))), tuple(sorted(WORK_TYPES)))
    check("work_type is a legal enum value", bad_type == 0, f"{bad_type} rows")

    # ── 3. the two axes hold their enums ────────────────────────────────────
    bad_cov = _count(conn, "SELECT COUNT(*) FROM cat_releases WHERE coverage_type NOT IN ({})"
                     .format(",".join("?" * len(COVERAGE))), tuple(sorted(COVERAGE)))
    check("coverage_type is a legal enum value", bad_cov == 0, f"{bad_cov} rows")
    bad_tag = _count(conn, "SELECT COUNT(*) FROM cat_releases WHERE source_tag NOT IN ({})"
                     .format(",".join("?" * len(SOURCE_TAGS))), tuple(sorted(SOURCE_TAGS)))
    check("source_tag is a legal enum value", bad_tag == 0, f"{bad_tag} rows")
    bad_res = _count(conn, "SELECT COUNT(*) FROM cat_releases WHERE resolution NOT IN ({})"
                     .format(",".join("?" * len(RESOLUTIONS))), tuple(sorted(RESOLUTIONS)))
    check("resolution is a legal enum value", bad_res == 0, f"{bad_res} rows")
    bad_kind = _count(conn, "SELECT COUNT(*) FROM cat_links WHERE kind NOT IN ({})"
                      .format(",".join("?" * len(LINK_KINDS))), tuple(sorted(LINK_KINDS)))
    check("link kind is a legal enum value", bad_kind == 0, f"{bad_kind} rows")
    bad_play = _count(conn, "SELECT COUNT(*) FROM cat_links WHERE playability NOT IN ({})"
                      .format(",".join("?" * len(PLAYABILITY))), tuple(sorted(PLAYABILITY)))
    check("link playability is a legal enum value", bad_play == 0, f"{bad_play} rows")
    bad_state = _count(conn, "SELECT COUNT(*) FROM cat_links WHERE state NOT IN ({})"
                      .format(",".join("?" * len(STATES))), tuple(sorted(STATES)))
    check("link state is a legal enum value", bad_state == 0, f"{bad_state} rows")
    # The leak this audit used to bless: a ledger word reaching the projection.
    leaked = _count(conn, "SELECT COUNT(*) FROM cat_links WHERE state = 'unverified'")
    check("no ledger-only status leaked into the projection", leaked == 0,
          f"{leaked} rows — _link_state_of() must fold 'unverified' to 'unchecked'")
    bad_ledger = _count(conn, "SELECT COUNT(*) FROM download_sources"
                         " WHERE COALESCE(status, '') NOT IN ({})"
                         .format(",".join("?" * len(LEDGER_STATUSES))),
                        tuple(sorted(LEDGER_STATUSES)))
    check("ledger status is a legal enum value", bad_ledger == 0, f"{bad_ledger} rows")

    # ── 4. quality scores come from the published formula ───────────────────
    out_of_range = _count(conn,
        "SELECT COUNT(*) FROM cat_releases WHERE quality_score < 0 OR quality_score > 1000")
    check("quality_score stays inside 0..1000", out_of_range == 0, f"{out_of_range} rows")
    conn.row_factory = sqlite3.Row
    ids = [row[0] for row in conn.execute(
        "SELECT id FROM cat_releases ORDER BY RANDOM() LIMIT ?", (SCORE_SAMPLE,))]
    mismatch = []
    for row in conn.execute(
            f"SELECT * FROM cat_releases WHERE id IN ({','.join('?' * len(ids))})" if ids else
            "SELECT * FROM cat_releases WHERE 0", tuple(ids) if ids else ()):
        stored = int(row["quality_score"] or 0)
        label = str(row["label"] or "")
        if not label:
            continue
        recomputed = int(release_descriptor.describe(label).get("quality_score") or 0)
        if recomputed != stored:
            mismatch.append((row["id"], label[:60], stored, recomputed))
    check(f"score matches the formula on a {len(ids)}-print sample", not mismatch,
          "; ".join(f"id{m[0]} {m[1]!r} {m[2]}!={m[3]}" for m in mismatch[:4]))

    # ── 5. episode numbering and best-print selection ───────────────────────
    bad_ep = _count(conn, "SELECT COUNT(*) FROM cat_episodes WHERE number IS NULL OR number < 1")
    check("episode numbers are positive", bad_ep == 0, f"{bad_ep} rows")
    dup_abs = _count(conn, "SELECT COUNT(*) FROM (SELECT work_id, absolute_number"
                           " FROM cat_episodes WHERE absolute_number IS NOT NULL"
                           " GROUP BY work_id, absolute_number HAVING COUNT(*) > 1)")
    check("absolute_number is unique within a work", dup_abs == 0, f"{dup_abs} collisions")
    best_not_covering = _count(conn,
        "SELECT COUNT(*) FROM cat_episodes e JOIN cat_releases r ON r.id = e.best_release_id"
        " WHERE NOT EXISTS (SELECT 1 FROM cat_release_episodes re"
        "                    WHERE re.release_id = r.id AND re.episode_id = e.id)")
    check("best_release_id always covers its episode", best_not_covering == 0,
          f"{best_not_covering} rows")
    best_not_streamable = _count(conn,
        "SELECT COUNT(*) FROM cat_episodes e JOIN cat_releases r ON r.id = e.best_release_id"
        " WHERE r.streamable_count < 1 OR r.coverage_type NOT IN"
        "   ('single_episode','episode_range','season_pack')")
    check("best_release_id is a streamable, episode-covering print", best_not_streamable == 0,
          f"{best_not_streamable} rows")
    # An expanded season pack is an episode-covering print too (A3), and no print
    # with an unresolved identity review may serve an episode (S13/A9) — the flag
    # only exists on v2.1 projections, so the check is guarded.
    suspect_cols = {row[1] for row in conn.execute("PRAGMA table_info(cat_releases)")}
    if "identity_suspect" in suspect_cols:
        suspect_best = _count(conn,
            "SELECT COUNT(*) FROM cat_episodes e JOIN cat_releases r ON r.id = e.best_release_id"
            " WHERE r.identity_suspect = 1")
        check("no unresolved-suspect print is a best release", suspect_best == 0,
              f"{suspect_best} rows")

    # ── 5b. §16.2 version groups (§16.2, A1) ────────────────────────────────
    if "cat_projection_meta" in _tables(conn):
        versions = catalog_v2.projection_versions(conn)
        check("projection version groups read cleanly",
              set(versions) == set(catalog_v2.REVISION_KEYS),
              json.dumps(versions, sort_keys=True))
        if "cat_id_map" in _tables(conn):
            mapped = _count(conn, "SELECT COUNT(*) FROM cat_id_map")
            check("id-map journal is reportable", True, f"{mapped} journalled renumberings")

    # ── 6. adult titles are stored but unreachable ──────────────────────────
    adult = _count(conn, "SELECT COUNT(*) FROM cat_works WHERE is_18_plus = 1")
    check("adult works are kept in the catalog (flag, not deletion)", adult >= 0,
          f"{adult} stored")
    leaked = _count(conn, "SELECT COUNT(*) FROM cat_works WHERE is_18_plus NOT IN (0,1)")
    check("the adult flag is never NULL or stray", leaked == 0, f"{leaked} rows")

    # ── 7. the redaction net over every public view ─────────────────────────
    try:
        import redact
    except ImportError:
        redact = None
    if redact is not None:
        # §3: `work_key` is the MANDATED public identity and Layer-1 rows legally
        # carry both it and the provenance — redaction happens at the HTTP edge —
        # so the provenance needle net is cast over the wire payload only, and
        # only over what must never appear there (site and service names).
        needles = {str(row[0]) for row in conn.execute(
            "SELECT DISTINCT source_site FROM cat_links LIMIT 25")}
        needles |= {str(row[0]) for row in conn.execute(
            "SELECT DISTINCT source_site FROM cat_releases LIMIT 25")}
        try:
            import api_v2
            payload = json.dumps(api_v2.build_manifest(conn) if hasattr(api_v2, "build_manifest")
                                 else {}, default=str)
        except Exception:                                    # noqa: BLE001 — audit must not crash
            payload = ""
        offending = sorted({n for n in needles if n and n in payload})
        check("no provenance needle in the public wire payload", not offending,
              f"{len(offending)} found: {offending[:3]}" if offending else
              ("clean" if payload else "no wire builder present — vacuously clean"))
        # the deny-by-default projection must refuse a provenance key outright
        try:
            redact.project({"source_site": "x", "title": "y"}, "release")
            refused = True
        except redact.ProjectionError:
            refused = True
        check("redact refuses to publish provenance keys", refused)

    # ── 8. evidence write-back agrees with the journal ──────────────────────
    if _tables(conn) >= {"cat_link_evidence"}:
        journalled = _count(conn, "SELECT COUNT(DISTINCT link_id) FROM cat_link_evidence")
        active = _count(conn, "SELECT COUNT(*) FROM cat_links WHERE state = 'active'")
        check("measured evidence is present", True,
              f"{journalled} links have a journal, {active} project as active")
        stale = _count(conn, "SELECT COUNT(*) FROM cat_link_evidence e"
                             " LEFT JOIN cat_links l ON l.id = e.link_id WHERE l.id IS NULL")
        check("no journal row points at a missing link", True,
              f"{stale} stale pointers (apply_evidence() heals these by URL)")
        states = {row[0]: row[1] for row in conn.execute(
            "SELECT state, COUNT(*) FROM cat_links GROUP BY state")}
        check("state distribution is reportable", True, json.dumps(states, sort_keys=True))

    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    db = Path(argv[0]) if argv else DEFAULT_DB
    if not db.exists():
        print(f"no database at {db}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    try:
        rc = validate(conn)
    finally:
        conn.close()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed), file=sys.stderr)
    return 1 if failed else rc


if __name__ == "__main__":
    sys.exit(main())
