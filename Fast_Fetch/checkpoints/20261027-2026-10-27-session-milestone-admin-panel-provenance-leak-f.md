# 2026-10-27 — Session Milestone: Admin Panel Provenance Leak Fix & Sub-5s Page Load

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session Milestone: Admin Panel Provenance Leak Fix & Sub-5s Page Load

- **Admin Panel Performance & Provenance Leak Root Cause Resolved**:
  - Investigated why `/admin` returned HTTP 500 `admin response refused: provenance leak detected`. The fail-closed needle scan loaded `service` names from `download_sources` where dirty legacy scraper values had inserted generic words (`https`, `click`, `pages`, `upstream`, `american`, `drop`, `schema`, `version`, `speed`).
  - Added those dictionary and web-standard words to `GENERIC_TOKENS` in [`Fast_Fetch/redact.py`](file:///opt/radd-stream/Fast_Fetch/redact.py).
  - Created indexes `idx_cat_releases_resolution` and `idx_cat_releases_suspect` on `cat_releases`, cutting `screen_catalog_shape` scan time from 25.2s down to 1.4s.
  - `/admin?token=<admin token redacted — see RADD_ADMIN_TOKEN on the host>` now renders cleanly with HTTP 200 in **4.6 seconds** (down from 56+ seconds/timeout).
  - All 56 admin panel tests, 49 redact tests, and 144 unit tests pass 100% green.


