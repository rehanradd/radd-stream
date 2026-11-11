# Session 2026-11-12 — self-check `[LIVE-TV-503]`: six empty logo_urls killed the whole Live TV tab

## What happened
- The user's phone recording (app-design-audit-20261112.md) showed Live TV 503 twice.
- Reproduced locally on the Oracle VM: `GET /api/v1/live-tv/channels` → 503
  `{"success": false, "error": "live_tv_unavailable"}`.
- Root cause: `live_tv.validate_registry()` fails closed on the FIRST bad entry, so one
  bad channel kills the whole list. All six test channels added 2026-11-11 19:57 PKT
  (ids 36–41) had `logo_url: ""`. First failure: `channel 36 must have an https logo_url`.
  The tab has been dead since those channels were added (~30 h).
- Fix: gave each of the six a verified https logo (all curl-checked 200 + image/*):
  36 reuses the ABC News logo (id 28, same brand); 40 reuses the Al Jazeera logo
  (ids 26/27, same brand); 37 Bloomberg TV, 38 Rakuten Viki, 41 Class CNBC from
  Wikimedia Commons; 39 Now 70s from the Wikipedia infobox file (`NOW_70s.png`).
- Drift found while fixing: the repo registry (35 channels) was stale — the panel
  dropped the 18 restreams on the live file 2026-11-11 20:12 PKT and that never went
  to git. This branch syncs the repo file to the live 23-channel file first, then
  fixes the logos, so a gate deploy cannot resurrect the dropped restreams.
- Test update: `test_seeded_registry_loads_and_counts` pinned 35 channels / 17
  enabled; updated to 23 / 23 with a comment citing the 2026-11-11 drop.
- Tests (local, CI way): `test_live_tv.py` 26 OK, `test_panel_feed.py` 48 OK,
  `test_redact.py` 82 OK.
- NOT deployed: live tree + service restart go through the gate (parent). The 503
  persists until the gate lands this branch.
