# 2026-10-27 — Session: remote controls, honest bridge unwrapping, offline playback (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: remote controls, honest bridge unwrapping, offline playback (Qoder)

### Completed
- **`admin_panel.py`**: `app_remote_config` gained `maintenance_mode`, `apk_update_url` and
  `feature_downloads` / `feature_pure_cinema` / `feature_chromecast`. Existing single-row
  tables are migrated in place (`ALTER TABLE ... ADD COLUMN`) so an older deployment keeps
  its payment ids. Flags accept only honest booleans (`0/1`, `on/off`, `true/false`,
  `yes/no`); the update address must be an `http(s)` URL with a host, no credentials, no
  controls/whitespace, and must survive `redact.scrub_text`. `remote_config()` publishes
  booleans plus the scrubbed address to `/api/v1/app/remote-config` (viewer already mounts
  it); shortener tokens stay server-side as `configured: true|false`.
- **`fast_fetch.py`**: `is_direct_media_url()` / `is_bridge_url()` classify byte endpoints
  versus HTML landing pages. A cached bridge `final_url` now forces a refresh; a re-resolve
  that still returns a bridge fails closed (`no_playable_source` /
  `bridge_unresolved`) instead of handing ExoPlayer a landing page. Fixed the FastDL branch,
  which called `unwrap_hubcloud`; added `unwrap_gdflix()` for GDFlix `file/<id>` pages
  (embedded Google CDN or Drive id → `drive.usercontent.google.com`), and gamerxyt
  `?link=` decoding.
- **`PlaybackService.kt`**: media reads go through `DefaultDataSource.Factory(this,
  httpFactory)` instead of a raw `DefaultHttpDataSource.Factory`, so a downloaded
  `content://` (MediaStore) or `file://` URI opens locally with no network; http(s) still
  goes through the branded agent and cross-protocol redirects.
- **Tests**: five resolver/classification tests in `test_database.py`, four remote-control
  tests in `test_admin_panel.py`. `test_admin_panel` now restores `redact`'s process-global
  needle set per test, because `viewer._ensure_schema()` leaves the last fixture database's
  hostnames behind and made an admin body fail its own leak scan in the combined run.
  `viewer.fetch_database_payload` counts site attribution from both `cat_work_sites` and
  legacy `releases.source_site`, so an older ledger's site is not dropped from the totals.
- **Resolver refresh inputs**: `resolve_live_source` now unwraps whichever stored address
  names the hoster (`source_url` is often the site's own page; the hoster id lives in a
  cached `final_url`). Without this, refreshing a cached PixelDrain `/u/` link discarded a
  resolvable bridge. The `test_redact` fixture's cached HubCloud URL was a `/drive/`
  landing page and now points at the real `pixel.` byte server.

### Checks
- `python3 -S -m unittest test_database.py test_vidout.py test_admin_panel.py` → **112
  tests, OK** (the exact requested command).
- Combined regression run `test_database + test_vidout + test_admin_panel + test_redact +
  test_operator_isolation` → **182 tests, OK**.
- `./gradlew --offline :app:compileDebugKotlin` → BUILD SUCCESSFUL.

### Not done
- No device/emulator run, so airplane-mode playback and the remote-config card are verified
  by compilation and unit tests only. Nothing committed (no commit requested).

