# Session 2026-11-12 — Player Fix v2 server (`muse/playerfix-v2-server-20261112`, base `c07aac07`)

Backend builder, server side only. Diagnosis §6.2/§6.3/§6.4 + research fold-in + host-priority-from-measurement.

## What was built

- **Serve-time verification** (§6.2, cached-first per the fold-in): new `Fast_Fetch/serve_verify.py` + `viewer._verify_option_tiers`. A band serves only a live-verified link — a fresh banked resolution (≤600 s) or a bounded parallel probe of its top 3 candidates under one shared 10 s deadline; a 302 from the redirector alone never verifies (the sd band proved why). Unverified bands hide entirely; served links carry `verified_at`. Gating stays: 2160p/1080p for a free user stay gated (402), verified the same way. `POST /api/v2/play` prefers a verified sibling print over a 409 on the named print.
- **Warm-all-bands** (§6.4.2): `_preresolve_for_detail` warms every band's top candidate in parallel the moment the detail request arrives; `?warm=1` still reports it.
- **Dead-link cleanup** (§6.3): every endpoint-answered failure writes evidence (journal + `catalog_v2.apply_evidence` fold + negative cache + host circuit). Strikes: 2 hard (404/410/DNS) or 3 flaky (timeout/429/5xx) failures across ≥2 days → quarantine (excluded from `tiers.score`); a second pass deletes only already-quarantined links. Never on expiry alone — a 403 re-signs once; only a fresh signature failing counts. Sweep gained counters (`newly_marked_dead`, `quarantined`, `deleted`), oldest-first sampling, sibling promotion, and a poison-cache guard (>50% no-answer records nothing).
- **Host circuit breaker + measured priority**: `host_health` table (probes/successes/measured_at, migrates old tables); 3 consecutive failures opens a circuit with doubling back-off (2 min → 1 h). Serve-time candidate order is host-rank first, then score. `seed_host_ranking` loads a measured ranking; `ranking_from_probe_csvs` builds one from link-check CSVs, keyed by **bridge domain** (the runtime lookup key — labels span several bridge domains, so label keys would never match). Expired tokens count separately, never for/against a host; soft-404 page_alive rows count dead; unknown/page_alive never count.
- **Prefetch cap** (§6.1): `warmup_count` default 50 → 200. New panel knobs `quarantine_min_failures` (3) / `quarantine_min_days` (2).

## Two bugs the new tests caught

1. `_verify_option_tiers`' first parameter was named `tiers`, shadowing the `tiers` module — `tiers.BACKUP_LIMIT` raised `AttributeError`. Renamed to `tier_rows`.
2. `record_probe_failure` opened a second connection to the same DB (via `fast_fetch._record_resolve_failure` → `get_db()`) while the caller held uncommitted writes on the first — the writer blocked 30 s on the write lock, then failed silently, so double-403 evidence never landed (and the suite took 30 s). Fixed by `fast_fetch._record_resolve_failure_on` (same-connection write; the old function now delegates to it).

## Tests

New `Fast_Fetch/test_serve_verify.py` (51 tests, registered in `.github/workflows/backend-ci.yml` after `test_search_fuzzy.py`). Solo green: serve_verify (51), home_rails (41), panel_feed (98), tiers (43), redact (96), resolved_cache (84), link_sweep (21), api_v2 (76), ci_manifest (10), docs_invariants (22), prefetch_worker (12), link_state (33), evidence_writeback (15), database (227). Full gate run once: everything green except `test_docs_invariants` — my first CONTINUITY.md entry pushed the file to 13,728 B over its 12,000 B budget (base was already 11,997 B); fixed by rotating this log here and keeping CONTINUITY.md an index. Gate re-run after the rotation: see the branch's CI runs.

## Host seeding (deploy-time, NOT done — the code is not live yet)

- Seed JSON: `hidden_files/host-ranking-seed-20261112.json` (41 hosts, from the FINAL 2,717-link check: pass 1 + browser-UA second pass; 298 answered probes, 31 alive). Top: download.bbupload.to 7/7 (the superduperload bridge — new #1), fastdl.beer 6/6, vcloud.beer 11/27. 22 circuits open (mobilejsr.com, 1fichier.com, archive.toonworld4all.me, …). fastdl/google_cdn links are Google temp tokens (245 expired) — re-resolve at serve time, never serve stored.
- Apply at deploy time: `hidden_files/seed-host-ranking-20261112.py --db <live catalog>` (one small transaction; never during a gate backup or sweep). Merged final check CSV: `hidden_files/host-priority-final-check-20261112.csv` (pass-2 verdict wins; totals match the final ranking MD exactly).
- The final ranking MD holds the tier order; the OWNER decides whether to set it in the API. This seed only orders probes and opens circuits from measurement — it sets no priority.

## NOT verified / owed

- **§0 acceptance table** (per-band first-link cold presses from the VM): NOT run — needs the code live. Deploy is the coordinator's call; this branch only pushes code to GitHub. Self-check workers must never deploy.
- App side (player/cache engine) is a separate lane; the Samsung retest fault is there, not in this server work.
