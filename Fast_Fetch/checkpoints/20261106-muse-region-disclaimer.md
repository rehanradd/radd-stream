# Per-region broadcasts + disclaimer (Muse, 2026-11-06)

## Done
- **Panel (admin-v2 workspace, uncommitted there — gate deploy owed):**
  broadcasts gained `target_detail` (TEXT; `_seed` adds the column to an
  existing database the way tuning columns are added). `create/update_
  broadcast` validate the target and its detail as one rule: region needs
  one of pakistan/india/asia/international, version needs one exact version
  name, all/free/vip take no detail; update validates the MERGED row, so
  changing the target without its detail is refused, not half-saved. The
  broadcasts form has a Target detail field. Tuning gained
  `disclaimer_text` (TEXT, ≤4000) + `disclaimer_version` (0..9999), both
  labelled "remote-config (app reads it)". 5 new panel tests (35 OK in
  test_unit.py).
- **Server (this branch):** `panel_feed.active_broadcasts` serves every
  live published broadcast with its target + detail (was: all-target only);
  a target the app has no rule for, or a region/version row with no detail,
  is dropped, never served half-targeted. NEW `read_disclaimer()` (same
  tolerant pattern as `read_theme`: missing DB/table/column → empty).
  `viewer.py` merges `payload["disclaimer"]` next to theme/tabs. 4 new
  `test_panel_feed.py` cases + fixture now mirrors the real schema; 25 OK.
- **App (this branch):** `PanelBroadcast` gains target/targetDetail,
  `VipRemoteConfig` gains `disclaimer` (PanelDisclaimer). NEW pure
  `ui/navigation/BroadcastTargeting.visible` (7 tests): all always; free/vip
  only on a KNOWN tier (null entitlement hides both); region maps the panel
  country to the viewer card — pakistan/india share the Desi card, so a
  Pakistan broadcast reaches Indian Desi viewers too, and the panel form
  says so; version matches exactly. `mergePanelFeed` filters through it
  (region + tier read in `checkForUpdate`; merge-level test added).
  Disclaimer: `RemoteConfigWatcher` saves it on the same poll as tabs;
  DataStore keys + `disclaimerSeenVersion` (-1 = never shown);
  `MainActivity` shows `DisclaimerDialog` once per version (cannot be
  dismissed without "I understand"); Settings has a Disclaimer card +
  the same dialog for re-reading. No text is ever invented: empty text
  means nothing published, and nothing shows.

## Not done
- The operator has not written the disclaimer text yet (his words, via the
  panel tuning API; the draft policy doc is
  `~/workspace/radd-stream-disclaimer-removal-policy.md`). Until he does,
  the app shows no disclaimer anywhere — by design.
- No push yet: commit lands after this file, then CI judges. Panel
  workspace files (broadcasts target_detail, disclaimer tuning keys) go
  to the VM panel + restart through the gate, with the tabs edits already
  waiting there.
- Next one-by-one steps: panel keys the app ignores, research-rule
  screens, backend gaps, design polish, final double-verification.
