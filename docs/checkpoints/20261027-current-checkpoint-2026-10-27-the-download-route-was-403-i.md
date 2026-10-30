# Current checkpoint — 2026-10-27 (the download route was 403; it is open, and the client half was declined on purpose)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Current checkpoint — 2026-10-27 (the download route was 403; it is open, and the client half was declined on purpose)

- **Goal:** finish the server half of M-MON-04 / P-B-02 / P-B-03, the monetization items
  the inventory listed as P0 and that needed no phone.
- **The finding that reframed the task.** `/api/v1/download` — the *only* route in
  `viewer.py` that runs `shorten_download_url` (one call site, line 3207) — was answered
  **403 by nginx**. So the entire waterfall was dead from any client, and no amount of
  app-side work would have touched it. Opening it was the actual blocker.
- **Shipped.** `GET /api/v2/account/vip-pass` in `Fast_Fetch/accounts_api.py`: 401 without a
  key, `402 licence_required` for a free account, `200 {pass, expires_at, membership_until}`
  for a member. `VIP_PASS_TTL_SECONDS = 6 h`, and the window is `min(now + TTL, vip_until)` —
  ten minutes of membership cannot buy six hours of capability. `redact.mint_vip_pass` had
  existed with **no caller** before this.
- **nginx.** `= /api/v1/download` added (GET/HEAD only, `burst=20`, 30 s read timeout) and both
  capability-carrying routes now log under a new `radd_capability` format — the standard format
  minus `$args`, because `$args` is where `?vip=` lives. Proved with `SECRETSENTINEL`
  strings: zero matches in `/var/log/nginx/access.log` for a capability that was definitely
  served, while other routes still log args.
- **Tests.** `test_accounts_api.py` 38 OK (the vip-pass cases are a `VipPass` subclass of a new
  `EdgeFixture` mixin — subclassing `Edge` directly had silently re-run all 29 inherited cases,
  67 → 38). `test_download_endpoint.py` 18, `test_database` 64, `test_vidout` 6,
  `test_payments`, `test_catalog_v2`, `test_media_search` 21, `test_admin_panel`, `test_redact`
  49 — all OK, one module per invocation. Edge sweep with `--probe`, covering the new
  `download` descriptor scan: **OK, 0 flags**.
- **The catch, and why no Kotlin was written.** The inventory's build text for M-MON-04 says
  "switch `DeviceDownloadsRepository` to `/api/v1/download` and attach `Authorization: Bearer`".
  Two reasons that is not a task: (1) `/api/v1/stream` was never monetized, so an in-app VIP was
  never walking through a shortener — the bypass it asks for buys nothing; (2) *a shortened link
  is a landing page, not the file* (`test_download_endpoint.py`'s own words). Pointing OkHttp's
  byte pipe at it writes an interstitial into `Movies/RaddStream/*.mp4` and destroys
  pause/resume. **Asked and answered on 2026-10-27: keep the byte pipe.** Free-tier shortener
  revenue is accepted at zero, VIP purchases are the monetization, and **no Kotlin was written**.
  M-MON-04 is closed, P-B-02 is closed *won't-fix*, and both say why — so the next agent re-poses it
  against a recorded decision instead of rediscovering it from `viewer.py:3207`.
- **Live verification:** `download?id=bad` → the server's own 400; `account/vip-pass` → 401
  problem body publicly; POST `download` → 403; `/api/data`, `/api/v2/health` → 403 unchanged.
- **Two repo-level facts found while verifying this push, both now in `docs/PROJECT_MAP.md`.**
  (a) **Resolved by the owner:** GitHub's default branch was `main` (= `3271a1d`) while 25 commits of
  shipped work sat on `master`, `master..main` = 0. `master:main` was pushed as a **pure
  fast-forward — no force, no history rewrite, nothing on `main` discarded**; both heads are now
  `095c3c7`. `AGENTS.md`'s "push verified milestones to `main`" is operative from here, and `master`
  keeps pointing at the same commit rather than being deleted.
  (b) **Verified, not discovered:** CI has never run on this repository, and the cause is the
  account-level Actions switch that root `AGENTS.md` already records. `actions/runs`,
  `backend-ci.yml/runs` and `check-runs` for `47d90a1` all report zero, and today's push that landed
  on the *default* branch produced no run either; `/actions/permissions` says enabled/`all` because
  that is the **repository** setting, which sits under the account one. Zero tags and zero GitHub
  Releases match it — the signed-APK flow has never executed, and the only published APK is the debug
  build task 5 placed in `/var/www/download/` by hand. **"CI green" is therefore unmet-by-default,
  not passed**, so the offline suites are the gate; that is what this session relied on.
- **Next:** task 10 (`M-SRCH-01`'s client half) and the outstanding device passes are all that is left
  of the decided work. Both need a phone or an emulator, and this box has neither.

