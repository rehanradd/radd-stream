# 2026-11-02 — q8 supervisor lane `[Q8-AUDIT-DEADLINKS]`: audit critical 10 — dead and expired links can no longer win a band or play

Branch `q8-audit-deadlinks-20261102` from `origin/main` (`723b504`, my gated critical-9 tip),
commit `92ec726`, pushed to the lane ref only. Rules honoured: no trunk push, no tag, no release,
no service restart, no live-DB write, no credential read, no VM Gradle; `/opt/radd-stream`
untouched — every edit in `git worktree` `/tmp/q8_deadlinks`. Duplicate check first, as ordered:
`q7-audit-qualitygate-20261102` is audit critical 5 (720p cap), `q7-audit-stale302` is critical 2;
no branch or commit since 2026-10-31 touches `tiers.py`/`catalog_api.py` (`git log --all --since
2026-10-31 -- Fast_Fetch/tiers.py Fast_Fetch/catalog_api.py` → empty). This lane therefore owns it.

## The defect, measured before written

`score()` penalised a dead copy by only −60 inside a stack of bonuses a dead row can carry
(kind direct 100 + resumable 15 + HTTP 15 + rank_score/4 up to 50 + speed up to 20 + freshness
10 = ~90 after the −60), so a fast dead direct link outranked a slow live resolve and **won the
quality band**. `playable()` read kind only, so that winner was announced playable and served.
The v2 projection said both at once: `_link_view` computed `"playable": state != "dead"`
(expired passed) while `"dead": state not in ("active","unknown","unchecked")` (expired is
dead). The v1 detail route ordered sources by `status = 'active' DESC` — a blanket label every
scraper writes at ingest — with no dead-last and no evidence check, and `/api/m3u` filtered only
`status != 'dead'`, so expired signatures landed in playlists.

## What changed

- `tiers.py` — one shared vocabulary: `DEAD_STATES = (dead, broken, gone)`,
  `EXPIRED_STATES = (expired, unreachable)`, `UNPLAYABLE_STATES` = both.
  `score()`: dead verdicts return **0** (agreeing with `link_health.score_link`, which already
  returns 0 for `ok == False`); an expired copy keeps only its kind weight minus 60 — every
  measured bonus is voided, because speed/range/HTTP describe a fetch that now 403s — but it is
  not zeroed, since a signed URL can be re-resolved (`resolve_live_source` refreshes `expired`
  rows; test_database pins that). `playable()`: any dead-family state answers False **before**
  the projected `playable` boolean is consulted, so a stale view cannot play a dead link.
- `catalog_api.py` — `_link_view()["playable"]` now consults `tiers.UNPLAYABLE_STATES`; the same
  dict can no longer say `playable=True, dead=True`.
- `viewer.py` — `link_view()` gates the v1 surface on ledger `status` too; the detail route's
  source ORDER BY is an evidence ladder — probe-confirmed live (0), unprobed claim: unchecked/
  unverified/unknown (1), expired (2), dead/broken/gone (3, last) — then the old temporary and
  service preferences unchanged; `/api/m3u` uses the same dead-family filter.
- `test_tiers.py` — new `DeadLinkGateTests` (8 cases: score 0 whatever the bonuses, live>dead,
  expired penalised not zeroed, playable refuses dead family, verdict outranks stale boolean,
  unchecked/unknown still play, link_view dead → not playable, dead never wins the band).
  `FailoverTests.test_a_dead_copy_does_not_take_the_second_backup_slot` asserted `[3, 2]` —
  a dead copy as the last silent-failover hop — which was pinning the very bug: `for_release`'s
  backup pool filters by `playable()`, and a failover hop is a served copy. Corrected to `[3]`
  with the reasoning in the comment.

## Verification

All 15 CI gate modules pass locally on this tree (one per invocation, `python3 -S`), plus
operator_isolation, usage_stats, html_escape_guard, admin_panel, merge_catalogs, docs_invariants.
`test_download_endpoint` fails 2 — **identically on a clean `723b504` checkout** (pre-existing
`/admin` auth failures on this VM; that module is not in the CI step list). Hosted CI on the
pushed branch is the gate; verdict reported to the supervisor.
