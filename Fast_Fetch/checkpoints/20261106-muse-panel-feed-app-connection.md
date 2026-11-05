# 2026-11-06 — Muse [MUSE-PANEL-FEED]: the admin panel feed reaches the app

The panel has owned three things the phone never read — the home sections it
builds, the broadcasts it publishes, and the works it hides — and the app has
built its own rails from `/api/v1/posts` since the beginning. This session
connects them, on the user's order ("connect the app to the admin panel",
00:02 PKT), coded by Muse directly, no qoder lane.

## Server (Fast_Fetch)

- New `Fast_Fetch/panel_feed.py` (stdlib only): reads the panel database
  read-only (`mode=ro`, env `RADD_ADMIN_V2_DB` via `config.PANEL_DB_PATH`;
  unset means the feature is off, never an error) and resolves sections
  (`latest` / `trending` / `category` / `curated` from `slider_cards`),
  broadcasts (published, in-window, `target='all'` only — narrower targets
  stay unpublished to the app rather than leaking to the wrong audience),
  and hides (`content_visibility`: global `work` + per-section
  `section_work`, unexpired, unrestored). A missing database or table
  answers empty, never an exception.
- Adult rule is the public one (`redact.adult_clause`): only a set flag
  hides a row. Adult-only sections are not served to the app at all.
- `viewer.py`: the panel feed rides the existing
  `/api/v1/app/remote-config` body as three additive keys (`sections`,
  `broadcasts`, `hidden_work_ids`) — no new route, no nginx change. Section
  items are projected through the same `post_brief` + art-pair + `work_ref`
  + `subtitled` shape the posts route serves, so the app decodes them as
  `Post` with no second fetch. `api_v1_get_posts` also excludes hidden work
  ids at serve time, so an old app obeys a hide too.
- Two bugs the new tests caught before anything shipped: `_active_hides`
  selected only `scope, scope_id`, so an expired hide read `expires_at` as
  NULL and hid forever; and `scrub_text` removes site tokens but does not
  strip HTML, so broadcast copy now goes through a tag-stripping plain-text
  step before scrubbing.
- New suite `Fast_Fetch/test_panel_feed.py`, 15 tests, registered in
  `backend-ci.yml` (the `WorkflowSuiteCoverageTests` guard demanded it).
  Local: 15/15 OK; `test_docs_invariants` 22/22 OK; `test_redact` 74/74 OK
  (one transient 6-error run that did not reproduce on two reruns);
  `test_catalog_api` 127/127 OK; `test_database` 134/134 OK (1 skipped).

## App

- `VipRemoteConfig` gains `sections: List<PanelSection>`,
  `broadcasts: List<PanelBroadcast>`, `hiddenWorkIds: List<Int>` — all
  default empty, so a deployment with no panel wired decodes unchanged.
- `HomeViewModel.mergePanelFeed` (pure, tested): panel sections first in
  panel order, built-in rails after them minus any key a panel section owns,
  hidden rows dropped from both, empty panel sections render nothing, a
  dismissed broadcast never returns this session. Panel rails are
  `panelManaged`: never loaded, retried, or refreshed through the posts
  route — the next remote-config fetch rebuilds them. The hero rides the
  first visible rail, so the operator's top section drives it.
- `HomeScreen` renders broadcasts as a dismissible banner above the
  catalog, severity-coloured (info / warning / urgent), even when the
  catalog failed to load — that is exactly when the operator has something
  to say.
- Tests: 2 new cases in `VipRemoteConfigTest` (full feed decodes; absent
  feed is three empty lists) and a new `PanelFeedMergeTest` (7 cases).
  No local Gradle run — the owner order is GitHub Actions only; CI judges.

## Not done, deliberately

- Live deploy is not part of this branch: it needs the gate path (backup +
  live test) and the `RADD_ADMIN_V2_DB` env var on the `radd-stream`
  service, which is a service-unit change at deploy time. Nothing here
  restarts anything.
- The theme block, tabs control, contact form, and the panel "Live control"
  page are the next one-by-one steps, in that order — see
  `~/workspace/goals/radd-stream-on-oracle-vm/files/app-admin-control-ideas-20261106.md`.
- The VM cool-down order (user, 00:09 PKT): if Oracle VM load is high, some
  qoder tmux sessions may be closed to cool it down — parked/idle first,
  never the crown or a lane mid-task. Load at 00:09 was 3.19: not high,
  nothing closed.
