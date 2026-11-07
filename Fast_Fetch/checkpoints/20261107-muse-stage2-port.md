# 2026-11-07 — Muse [MUSE-STAGE2-PORT]: live-deploy prep, Stage-2 port

Branch `live-only-20261107` from main `5a3788dd` (D1.1 order steps 1–2).
Keepers commit `c97dbc9f` (10 files +1695/−1): `.gitignore` credential
block, `UNIVERSAL_AI_PROMPT.md` domain line, `Fast_Fetch/current_hosts.py`
(855 lines), `InstantStartGuardTest.kt` (233 lines), four OpenRouter
tooling files, two scraper-spec reference files.

Stage-2 port: live `fast_fetch.py` hunks A–I applied verbatim onto main's
file — strict-gate helpers (`_stage2_hint` / `_stage2_probe` /
`_stage2_accept`, `_STAGE2_REFERER_RETRY`), `want` + `_failover` params,
Stage-1 + Stage-2 cached probes, Stage-1 dispatch, fresh-verdict probe,
4-branch measured block, Stage-1 sibling + Stage-2 general failover,
stale probe. Diff +370/−22, and the +/- lines are byte-identical to the
live diff; markers 14x `stage2` + 2x `STAGE2`; import OK on Python 3.12.3
(CI is ubuntu-24.04 system python 3.12, same minor as the VM).

Tests: 3 new in `test_database.py` — strict gate refuses an unprobed
cached page (both contracts), strict gate serves a probed cached address
(`stage2_probed`), Stage-1 dispatch serves a proven-backend copy. The
resolver now probes over the network, so the offline suites stub the
network boundary: `_stage2_probe` → passing file verdict and
`current_hosts.classify_backend` → `"unknown"` by default
(`DatabaseSaveTests.setUp`, `PublicEdgeHttpTests.setUp`, the safe-link
test, the resolver test). The stale/demoted fixtures in `test_redact.py`
isolate their row (siblings deleted) because Stage-2 failover would
otherwise rescue the row from its healthy sibling — the route-refusal
assertions themselves are unchanged.

Results: `test_database.py` 138 OK, `test_redact.py` 76 OK. Full backend gate run 2026-11-07 ~17:57 PKT (`run-backend-gate.py`, 49 modules): 49/49 PASS, 0 failed — `test_api_v2.py` 46 OK in 92.2s, `test_docs_invariants.py` 22 OK. CI verdict to be filled in after the push.
