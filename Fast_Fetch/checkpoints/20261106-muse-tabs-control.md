# Tabs control — panel orders the bottom bar (Muse, 2026-11-06)

## Done
- **Panel source (admin-v2 workspace, NOT this repo — gate deploy owed):**
  `store.py` `TUNING_DEFAULTS` gains `"tabs": "home,search,my_list,settings"`
  and `TUNING_TEXT_COLUMNS` gains `"tabs"`. The panel's `_seed` auto-adds the
  column and NULL-only-seeds the default on its next restart, the same way
  the theme keys landed. `services.py` `put_tuning` validates the value
  (comma list of home/search/my_list/settings, at least one named, anything
  else refused out loud) and `tuning_consumers` labels it
  "remote-config (app reads it)". No tuning UI template exists — tuning is
  API-driven (GET/PUT `/admin/api/v2/tuning`), so no template change was
  needed. Panel tests: 126 OK locally with the additions.
- **Server (this branch):** `panel_feed.read_tabs()` reads the `tabs` TEXT
  column from `tuning_settings` id=1, read-only, same tolerant pattern as
  `read_theme`: missing DB/table/row/column answers the default four;
  unknown ids drop, duplicates collapse, empty/unreadable answers the
  defaults. `viewer.py` merges `payload["tabs"]` into the remote-config
  body next to `theme` — no new route, the public allow-list does not change.
  Tests: 3 new `test_panel_feed.py` cases (operator order deduped,
  defaults when nothing set, unknown ids dropped + empty falls back);
  `python3 -S test_panel_feed.py` 21 OK locally.
- **App (this branch):** `VipRemoteConfig.tabs` (empty = older deployment,
  the app keeps its own four). NEW pure `ui/navigation/PanelTabs.resolve`
  + 7 tests: the operator's list is authoritative (order stands, a tab it
  did not list does not show), Home is always pinned first, Search drops
  out when its feature flag is off, empty/all-unknown falls back to the
  shipped four, case/space forgiven, duplicates collapse.
  `ServerSettingsRepository` mirrors the list in DataStore (`panel_tabs`
  key, comma-joined) via `saveTabs`/`panelTabs`; `RemoteConfigWatcher`
  saves it on the same successful poll as the theme; `MainActivity`
  collects it and passes it to `RaddStreamNavGraph`, whose bottom bar is
  now driven by the resolved list. Routes stay registered even for a
  hidden tab, so a back stack holding that screen still resolves.
  `VipRemoteConfigTest` panel-feed decode case extended with tabs.

## Not done
- No push yet: CI run 42143779496 (step 19 + language defaults) is still in
  progress on this branch, and a push would cancel it. This commit lands
  after that run finishes.
- No local Gradle run — owner order is GitHub Actions only; CI judges.
- Panel workspace changes are NOT in this repo: they must be posted to the
  VM panel workspace and the panel server restarted (correct six env vars,
  exact PID) before tabs control works end-to-end. The live panel DB has no
  `tabs` column yet; `read_tabs` defaults cover it until then.
- No live deploy of this branch (gate path + `RADD_ADMIN_V2_DB` env).
- Next one-by-one steps: contact form, Live control page, per-region
  sections + disclaimer versioning, P0 bug fixes, remaining ideas sweep,
  research-rule screens.
