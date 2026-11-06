# Panel keys the app ignored + version health + settings_unavailable (Muse, 2026-11-06)

## Done
- **`settings_unavailable` (P0, fail-open):** the server has sent this marker
  since the v1 panel was written, and the app never decoded it — a degraded
  200 would have overwritten the operator's real switches, prices and rails
  with shipped defaults. The app now decodes it and, at all three consumers
  (RemoteConfigWatcher, Home checkForUpdate, VIP loadConfig), keeps the last
  good config and acts on nothing in the degraded body. VipRemoteConfigTest
  pins the marker.
- **Section caps:** `home_sections_max` / `section_cap` are now read by
  `panel_feed.read_section_caps` (clamped to the panel's bounds, 1..12 /
  5..50) and applied in `load_panel_feed` — the server caps the feed, not
  the app. Panel label updated to "panel feed (server applies it)".
- **Free quality cap:** `panel_feed.read_free_quality_cap` serves the
  operator's cap ("480p"/"720p", else shipped "720p"); the watcher mirrors
  it; `VipQualityGate` gained cap-aware overloads — at 480p, 720p rungs,
  prints and labels leave the free ladder/layout, and the locked message
  says so. Detail + player ViewModels collect the cap like they collect
  the gate switch. 2 new gate tests.
- **Version health:** the app's OkHttp client now sends `Brand.userAgent`
  (with the version name) on every request, including the config fetch —
  before this, only the discovery probes sent it. The app decodes the
  `apk_update_version_code` the server already published (AppUpdate
  compares it: a published code at or below this build is silence) and
  `min_version_code` from the latest PUBLISHED panel snapshot (the draft
  does not count). A build below the minimum gets a required update dialog
  — no "Later", no dismiss. 5 new AppUpdate cases.
- **kill_switch:** investigated, no code. The key does not exist anywhere —
  not in the panel, not in the server, not in the app. The kill switch is
  `maintenance_mode`, and the app already honours it (MainActivity shows
  the maintenance screen). Recorded here so the audit's "ZERO hits" line
  is answered, not left open.

## Not done
- No push yet: commit lands after this file; the d541dd4 runs (region +
  disclaimer) are both green, so nothing in flight to cancel. CI judges
  this commit next.
- Panel workspace file (services.py tuning_consumers labels) rides the
  gate with the tabs / Live page / broadcast / disclaimer edits.
- Next one-by-one steps: research-rule screens, backend gaps, design
  polish, final double-verification.
