# Previous checkpoint — 2026-10-27 (the deployment was the missing half)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Previous checkpoint — 2026-10-27 (the deployment was the missing half)

- **Goal:** after the VIP/entitlement/gate code landed, make it real on the box: ship the
  operator switch, prove the public edge leaks nothing, and stop the app being unable to reach
  the endpoints it was written against.
- **Deployed and verified on Oracle (this host):**
  1. `radd-stream.service` restarted twice — the running process predated the payment ledger, so
     `/api/v1/app/remote-config` was still serving three flags. It now carries
     `feature_flags.quality_gate = false`, which is the decision: the 1080p/4K charge exists and
     is off until the operator flips `/admin`.
  2. **nginx was the blocker nobody had written down.** The installed config proxied only
     `/api/v1/posts`, `/api/v1/stats`, `/api/v1/stream`, with `location ^~ /api/ { return 403; }`
     catching everything else — so every v2 route, including all of `/api/v2/account*` and
     `remote-config`, answered 403 from outside. Added `= /api/v1/app/remote-config` (GET/HEAD)
     and `^~ /api/v2/account` (GET/HEAD/POST/PUT/DELETE); previous file kept at
     `/etc/nginx/radd-stream.pre-v2.bak`, `nginx -t` before reload. Probed from the public
     address after reload: `remote-config` 200, `account/entitlement` 401 (its own problem body),
     `account/payment` POST 401 without a key, `/api/v2/health` and `/api/admin` still 403.
  3. **Edge sweep, run for real.** A 31 MB snapshot (`/tmp/edge_snapshot.db`: 270 posts, 15 per
     site, 18 sites, plus the releases/sources/cat_* rows those posts join to — the live 6.2 GB
     catalog was never opened for writing) through `sweep_public_edge.py`. It passed, and its
     hand-review list was the finding: public JSON carried `"Ozark S01E01 ModiPlay"`,
     `"480P [GDFlix] 1.89 GB"`, `NXStream`, `ScreenScape` in `release_title`, because
     `scrub_text()` only deletes tokens in `BASE_NEEDLES` and those four were not in it.
- **Fixed here:** the four tokens added to `Fast_Fetch/redact.py`, each after the check the file
  requires — zero rows of `posts` contain the token in `clean_title` or `title`. `"Nexus"` was
  left alone deliberately (it titles real films; the residual report exists so a human decides),
  same for `"Short"` and `"Torrent"`. After the restart the served JSON for the two posts that
  leaked them contains none of the four.
- **Checks run and exact result:** `:app:compileDebugKotlin :app:testDebugUnitTest` → BUILD
  SUCCESSFUL, **452 tests / 55 suites / 0 failures**, all 55 result XMLs newer than the run and
  `OVERLAP=NO` (an idle VM, so this is clean evidence). Backend: `test_redact.py` 49 OK,
  `test_database.py` 64 OK, `test_vidout.py` 6 OK, `test_admin_panel.py` 56 OK,
  `setup_check.py` all pass, `sweep_public_edge.py` exit 0 twice (before and after the fix).
- **What is NOT verified:** still no device or emulator. Every app claim here is compile plus
  unit test. The keep-chip change (a tapped keep now plays its own bytes through the loopback
  proxy instead of re-resolving upstream) is the one a phone has to confirm.
- **Next action:** the debug APK on `/var/www/download/radd-stream.apk` is being rebuilt from
  this tree; after it, task 3 (`/api/v1/search/by-media`) and the VIP shortener waterfall are
  the remaining decided-but-unbuilt items.

