# Session checkpoint

Update this file after each independently verified milestone so work can resume across accounts, tools, and usage limits.

## Overnight fleet contract — 2026-10-28 (owner approved full autonomy, live API frozen)

- **Fleet, verified:** qoder1 (`~/.qoder`) = App region/settings + snapshot work; qoder2
  (`~/.qoder_account2`, me) = fleet orchestrator; qoder3 (`~/.qoder_account3`) = kisskh
  importer; `agy` (Antigravity) = roadmap/supervision; `vm_monitor` = pane tail. No Gemini
  CLI process exists on this host.
- **Rules enforced:** one Gradle build at a time (prefer `/tmp/qbuild.sh`; qoder1 ran one
  direct build at 00:24, no other build was started); at most two crawlers, both `nice`d;
  live API (`merged_catalog_20261025.db`, 115,938 posts) is frozen; staging DBs only; no
  secrets echoed; no `git add -A`, no force-push.
- **Site roster, verified live by probe:** 21 existing importers + kisskh (building) +
  dramacool.li + 5movierulz.green + moviecok.xyz + levidia.ch = 26 catalogs; plus four
  resolver adapters (vidsrc.sh, superembed.stream, vidlink.pro, 2embed.cc) = 30 integrations.
  Dead replacements ruled out: desiserials (.org parked, .com redirect), moviesflix (parked),
  isaimini (/lander), animepahe (challenge), asianc (timeout), apnetv (403), dramacool.ch
  (reset), kissasian.vip (for sale).
- **mp4moviez:** 29,848 posts stored; remaining 3,119 URLs are 2,565 adult pages + 442
  category listings + 112 Unicode-titled posts, and the site moved those pages to JS-gated
  `data-key` download buttons. The old `dl.php` parser cannot see links; a resolver upgrade
  is the follow-up, not a crawl outage.
- **Subtitle rule:** every `.vtt/.srt/.ass` track becomes its own `sources` row with
  `playback_type='subtitle'`, and the full track map is kept in `raw_meta`. Tracks are never
  dropped or deduplicated by language.
- **Subtitle audit result (verified by query):** the legacy pipeline stored **zero** subtitle
  rows — 17,541 filmiyin sources, 2,229+ dramacool sources and every sampled legacy range
  carry no `playback_type='subtitle'` row and no `.vtt` URL. Subtitle capture begins with the
  new importers; kisskh is the first catalog expected to yield real tracks.
- **Progress at 00:50:** commits `e6b5dd7` (5movierulz, moviecok, dramacool, resolvers),
  `ecb6a84` (levidia), `7069e2f` (filmiy.in importer that built the existing 3,837-post
  staging DB — it had been untracked, 38 tests) are local and **pushed**; GitHub master is
  `7069e2f`. qoder1's `3fb1a6c`, `a0ecbce`, `1a7b475` verified green and included.
- **Progress at 01:20:** dramacool finished (544 posts / 9,675 sources); 5movierulz finished
  (601 pages, 442 unique works / 6,491 sources); moviecok is crawling (753+ posts); levidia
  next. `Fast_Fetch/audit_staging.py` is committed and pushed (`9fa263f`): 27 catalogs,
  292,462 posts, 2.48M releases, 1.98M sources, 0 measurable subtitle rows, 17,373 adult-flagged
  posts, plus schema-drift warnings for every legacy DB. qoder1's App snapshot work landed as
  `6c923f7` after lint suppression was removed; 481 tests, 0 failures, `OVERLAP=NO`. GitHub
  master is `6c923f7`.
- **kisskh, ready for pilot:** suite is 129 tests OK in 9.6 s with no live socket; all three
  review findings fixed (missing-column migration for `sources`, single-quote slug path,
  subtitle rows stored `unverified`). Player-data was probed independently: eleven live
  `text/vtt` tracks per title (tl, km, en, id, ms, pt, ar, hi, de, fr, es), a sampled track
  returning HTTP 200.
- **Milestone closed at 02:00 — 30 integrations, verified.** 26 catalogs (21 legacy site
  parsers plus dramacool, 5movierulz, moviecok, levidia, kisskh) and 4 resolver adapters
  (vidsrc, vidlink, 2embed live; superembed documented-blocked) = 30. kisskh shipped as
  `44efa5a` (2 files, 2,784 lines, 129 tests) plus continuity `a311012`; GitHub master is
  `a311012`. Final kisskh staging: **669 works, 11,550 releases, 12,999 stream + 763 iframe +
  126,984 subtitle sources**, eleven languages at 11,533 rows each (ar, de, en, es, fr, hi,
  id, km, ms, pt, tl) from res.cloudinary.com and sub.cdnauto.xyz, every subtitle row honestly
  `unverified`, 10 adult-flagged works stored and never displayed, episode maps in `raw_meta`
  for all 669. Other new catalogs: dramacool 544/9,675; 5movierulz 442/6,491; moviecok
  1,738/7,452; levidia 147/2,976; filmiyin 3,837/17,541. The legacy 21 still carry no
  subtitle data (audit-proven), so kisskh is the first subtitled catalog.
- **Live-site constraint learned:** kisskh's REST listing at `per_page=100&_embed=1` returns
  5.3 MB and crosses a 30 s timeout; `per_page=20` with a 60 s listing timeout works. Do not
  combine `_fields` with `_embed` on that host — `_embedded` comes back empty.
- **Open items:** mp4moviez parser upgrade for JS-gated `data-key` downloads; the untracked
  `import_mp4moviez.py`/`test_mp4moviez_import.py` are unverified OpenRouter drafts (their test
  imports a module that does not exist) — do not commit them as-is. Eight new candidate
  domains probed today were all NXDOMAIN, so the roster stays at 26 catalogs.

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

## Previous checkpoint — 2026-10-27 (the by-media endpoint, and the APK that was still stale)

- **Goal:** close the two decided-but-unbuilt items that did not need a phone: the
  identify-a-file search (`/api/v1/search/by-media`) and the debug APK the public
  `download/` link was still serving from an older tree.
- **APK republish (task 5, now closed).** `:app:assembleDebug` from `04126e7` finished
  `GRADLE_EXIT=0`, `OVERLAP=NO`, `apksigner verify` clean on v1+v2 (Android Debug cert).
  Published over `/var/www/download/radd-stream.apk`: public 200, 22 738 552 bytes,
  md5 `9ace0279…`, byte-identical to the built artifact. The superseded build was
  **moved out of the web root** to `/home/ubuntu/radd-stream-data/radd-stream.apk.pre-04126e7`
  rather than deleted — it had been publicly fetchable at a stable URL, and a stale APK
  anyone can install is a worse state than a backup nobody can.
- **New endpoint.** `Fast_Fetch/media_search.py` + the `/api/v1/search/by-media` route in
  `viewer.py`, tested by `Fast_Fetch/test_media_search.py` (21 tests). The design decisions,
  because they are not guessable from the code:
  1. **Hints are evidence, not keywords, and are reported three ways** — `matched_on` /
     `mismatched_on` / `unknown_on`. A runtime the ledger does not hold is `unknown`, never a
     silent agreement; the live catalog answers `runtime_minutes: null` for most works, so this
     is the common case, not a corner.
  2. **A title is required; no title is a 400.** 130 016 works, thousands of them ~120-minute
     480p films — duration plus rung cannot discriminate, and ranking all of them to say
     "here are 10 of possibly 10 000" would be a lie at 1 vCPU.
  3. **The v1↔v2 join is `cat_work_sites.post_id`.** `posts.canonical_key` ↔ `cat_works.work_key`
     matches **zero rows** (a slug against an `imdb:` id); a test now pins both facts, so the
     bridge cannot silently rot back into an empty answer.
  4. `docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` was **not** implemented as sketched: it asks
     for an FTS5 `catalog` table and columns the ledger does not have. This is the design that
     fits the real schema.
- **Verified:** `test_database` 64, `test_media_search` 21, `test_redact` 49, `test_api_v2` 46,
  `test_admin_panel` 56, `test_catalog_api` 114, `test_provenance_stamping` 12,
  `test_operator_isolation` 22 — 364 tests, all OK, one module per invocation.
- **Edge sweep now covers the new route** (`sample_titles` probes, three hidden-adult probes,
  the no-title 400, the garbage-duration 200). Run on `/tmp/edge_snapshot.db`: **OK — no site,
  no hoster, no upstream host across 48 sampled posts and every route**; hosts named inside
  public bodies were only `image.tmdb.org` and `m.media-amazon.com`.
- **Deployed:** service restarted (8 polls to 200 — it takes ~70 s to boot, do not trust a fast
  000), `= /api/v1/search/by-media` added to nginx before the `^~ /api/` deny (GET/HEAD only,
  `burst=20`, 30 s read timeout), `nginx -t` ok, reloaded. Backup of the old config:
  `/etc/nginx/radd-stream.pre-bymedia.bak`. Public checks: GET answers 200 with the three-way
  report, POST → 403, and `/api/v2/health` 403 / `/admin` 401 / `/api/data` 403 unchanged.
  Live query cost measured: **0.37 s** for a five-candidate title.
- **What is NOT verified:** still no device and no emulator, so the *client* half of
  M-SRCH-01 (permissions, `DeviceMediaScanner`, the screen, the Room mapping) is deliberately
  not started rather than half-written; nginx's rate shedding was not re-proved here (the 26
  request loop stayed inside the burst), and the app's own per-path limiter is the backstop.
- **Repo hygiene, found while staging this session's work:** commit `04126e7` — a docs commit
  of mine — swept in another account's `Fast_Fetch/CONTINUITY.md` entry asserting
  `importers/test_filmiyin_import.py` 38 OK, while `Fast_Fetch/importers/` is still **untracked**.
  The filmiyin importer is therefore not in the repository and its tests do not run from a fresh
  clone. A correction is now written into `CONTINUITY.md` itself; the untracked
  `importers/`, `dispatch_worker.py`, `openrouter_*.py`, `prompt_worker*.txt`, `android_tasks.md`
  and `filmiyin_task.md` are deliberately **not** staged by this session — reviewing someone
  else's unfinished work is not a side effect of committing my own.
- **Next action:** task 4's remaining half — the VIP shortener waterfall in the app
  (`cat_shortened_links` exists and is empty; `link_shorteners` already reaches
  `VipRemoteConfig`) — then the M-SRCH-01 client pass, which needs a phone.

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

## Previous checkpoint — 2026-10-27 (VIP claim is a real server round-trip)

- **Goal:** close the last fake in the monetization path — the app stored a transaction ID
  locally and claimed it had been kept, while `Fast_Fetch/payments.py` already served a real
  ledger. Wire the client to it, read the entitlement back, and gate something honest on it.
- **Done here (app):**
  1. **Real payment call.** `POST api/v2/account/payment` with the bearer sync key and body
     `{"plan","method","tid"}` (`RaddStreamApi.submitVipTid`, `SyncAccountRepository.submitPayment`).
     Named for the screen's verb; the doc on it records that **`/api/v1/vip/submit-tid` does not
     exist** and that `phone` is not collected, so nobody re-invents either.
  2. **Entitlement read-back.** `GET api/v2/account/entitlement` → `{vip, vip_until, pending}`,
     refreshed at launch, on every "Sync now", and on a 6-hour clock from the Application;
     throttled to 60 s, keeps the last good answer on a transient failure, clears on sign-out.
     The type is `AccountEntitlement`, because `CatalogV2.kt:216` already owns `Entitlement`.
  3. **No local VIP minting.** `VipViewModel` prices plans/channels in the server's own spelling,
     posts when signed in, keeps the draft on the device when not, and re-files a kept draft
     once an account exists. Refusal text is ours (`VipSubmission.outcome`), never the server's
     `detail`.
  4. **Honest gating.** Entitlement or a rewarded pass silences `AdSlotPolicy` and the
     `DetailScreen` sponsor card. **No quality/resolution gate was invented** — remote config
     publishes no such flag.
  5. **Three false UI claims corrected** ("this server has no payment collection endpoint",
     the reference is "not sent anywhere automatically", and the privacy footnote).
  6. **Drift pinned by `VipWireContractTest`**, which reads `payments.py` and `redact.py` off
     disk and pins plan names, plan days, fallback prices, channel names and both projection
     field sets, plus that `tid` appears in neither projection.
- **Also landed in the same tree (worker session, task P-A-05):** `RemoteConfigWatcher` polls
  `/api/v1/app/remote-config` every 5 min and `MainActivity` shows a full-screen
  `MaintenanceScreen`; `VipRemoteConfig` now decodes `feature_flags`, `ads`,
  `link_shorteners`. Reviewed and sound: the flags the server does *not* send (`sharing`,
  `search`) default to `true`, so an absent key cannot switch a real feature off.
- **Checks run and exact result:** `:app:compileDebugKotlin :app:testDebugUnitTest` →
  BUILD SUCCESSFUL, 410 tests / 50 suites / 0 failures (all 50 result XMLs newer than the
  run). Backend unchanged this round; `python3 -S Fast_Fetch/test_database.py` was 64 OK and
  `test_vidout.py` 6 OK at the last backend milestone.
- **Operational finding — this is the one to remember:** concurrent Gradle invocations in
  `App/` on this 1-vCPU host corrupt each other's kapt output (`BUILD FAILED`, zero compile
  errors, `Unable to delete directory .../generated/source/kapt`). Builds now go through a
  queue that waits for other agents and holds an exclusive lock, and `App/AGENTS.md` §1a
  replaces the stale "never run gradlew locally" rule with the real constraint. A file-reading
  drift test can also fail purely from a source file being written mid-test — re-run before
  believing it.
- **Known limitations:** no device or emulator, so the posted claim, the operator approval and
  the entitlement countdown are compile/unit-verified only. `PosterCardProvenanceTest` still
  self-skips (no aarch64 Robolectric runtime; needs an x86_64 runner, and Actions is disabled
  at the account level). The new maintenance overlay has no escape hatch to Settings — tracked
  as a follow-up.
- **Next concrete action:** commit this milestone once a build runs with no overlapping agent
  build; then the keep-chip (`DownloadsScreen` "In-app keeps" still plays through the network
  handle instead of the bytes already on the device).

## Previous checkpoint — 2026-10-27 (Facet search, hero ambient glow, broadcast update dialog)

- **Goal:** the requested "2026 Luxury UI & Multi-Filter Search" pass — real multi-facet
  search, a subtle glow under the hero banner, and a one-tap APK update notice driven by
  `apk_update_url` from remote config.
- **Done here:**
  1. **Server facets (no dead UI).** `/api/v1/posts` gained `industry`, `genre`, `quality`
     and `sort`. Industry/anime reuse the columns the ledger actually writes
     (`p.industry`, `p.country`, `p.language`, `p.is_animated`); genre is a `lower(genres)`
     LIKE over the free-text column; quality is an `EXISTS` test over `releases.quality`
     (4K also matches 2160/UHD). Sort answers `trending` (coverage: release+source counts),
     `newest`, `rating` (null last), `title`. All compose with `q`/`type`/paging.
  2. **App search UI.** `SearchViewModel` owns the facet enums + `hasSearchIntent`
     (a blank query is still a search when a facet is chosen, so `loadMore` still pages);
     `SearchScreen` has one horizontally scrolling rail (Type · Industry · Genre · Quality ·
     Sort) plus the same facets as `FlowRow`s in the filter sheet, and a loading state.
  3. **Hero glow.** `HeroAmbientGlow` paints two radial blooms behind the banner from the
     theme's primary/secondary/tertiary, cross-fading per page (snap under reduced motion).
     The hero card is inset 14dp with a 24dp corner so the light spills around it; the
     skeleton matches the inset, so nothing jumps.
  4. **Update dialog.** `VipRemoteConfig` now decodes `apk_update_url` and
     `maintenance_mode`. `HomeViewModel.checkForUpdate()` folds the URL into a pure
     `AppUpdate.from(...)`; Home shows a branded `AlertDialog` that opens the link with
     `ACTION_VIEW` and only closes once the browser actually launched. A failed config
     fetch stays silent; `Later` suppresses that URL for the session.
  5. Added `copy.update_title` / `copy.update_message` / `copy.update_now` to
     `/brand.properties`.
- **Checks run and exact result:** `python3 -S Fast_Fetch/test_database.py` → 64 tests OK;
  `python3 -S Fast_Fetch/test_vidout.py` → 6 tests OK. Android
  `./gradlew --offline :app:compileDebugKotlin` → BUILD SUCCESSFUL;
  `testDebugUnitTest` → 381 tests / 47 suites / 0 failures (new `AppUpdateTest` 3,
  `VipRemoteConfigTest` now 6, `BrandDriftTest` 9 still green).
- **Known limitations:** no device/emulator pass, so glow smoothness and the dialog on a
  real phone are compile/unit-verified only. Remote config carries no version code, so the
  notice says "a new build is available" and cannot compare versions. `maintenance_mode`
  is decoded but no screen consumes it yet.
- **GitHub branch/commit/push result:** not committed (no commit requested).
- **Oracle deployment result:** not deployed.
- **Next concrete action:** device pass on the facet rail/glow/dialog; decide whether
  `maintenance_mode` should gate Home; consider documenting the four new query params in
  `Fast_Fetch/ANDROID_INTEGRATION.md`.

## Previous checkpoint — 2026-10-27 (Remote Controls, Direct Stream Unwrapping, Offline Playback, OpenRouter Deep Audit)

- **Goal:** Remote app management from Admin Panel, unwrap HTML bridge redirects (HubCloud/FastDL/GDFLix/PixelDrain), offline media playback, and OpenRouter pure-code architectural audit.
- **Done here:**
  1. **Remote Controls Live in Admin Panel & Remote Config**:
     - Added `maintenance_mode`, `apk_update_url`, and feature flags (`feature_downloads`, `feature_pure_cinema`, `feature_chromecast`) to `Fast_Fetch/admin_panel.py`.
     - Mounted on `/api/v1/app/remote-config` alongside Pakistani payment rails (JazzCash, EasyPaisa, Raast), ad zones (Monetag, Adsterra), and link shorteners.
  2. **Direct Media Resolution (Zero HTML Bridges)**:
     - `Fast_Fetch/fast_fetch.py` classifies `is_direct_media_url()` vs. `is_bridge_url()`.
     - Automatically unwraps HubCloud, FastDL, and GDFLix (Google CDN/Drive) to direct media endpoints (`.mp4`, `.mkv`, PixelDrain direct API `https://pixeldrain.com/api/file/{id}`).
     - Fails closed as `no_playable_source` / `bridge_unresolved` if an upstream fails to unwrap, never serving an HTML landing page to ExoPlayer.
  3. **Offline Playback Support**:
     - `App/.../player/PlaybackService.kt` switched to `DefaultDataSource.Factory`, supporting `content://` and `file://` URIs so downloaded media plays offline without network access.
  4. **OpenRouter Deep Pure-Code Audit**:
     - Created `Fast_Fetch/openrouter_oracle.py` (stdlib only) and completed pure-code architectural review saved to `docs/OPENROUTER_PURE_CODE_AUDIT.md`.
  5. **Explorer Dashboard Resolved**:
     - Replaced 3.7M unindexed full-scan queries in `viewer.py` with instant stats from `cat_projection_meta` and `cat_work_sites` with `LIMIT 50` pagination (loads in 0.67s).
     - Fixed code-server proxy paths in `DASHBOARD_HTML` so all API requests route properly.
- **Verified:**
  - Backend test suites: 182 tests across 5 suites passing (100% OK).
  - Android build: `./gradlew --offline assembleDebug` → **BUILD SUCCESSFUL in 1m 16s**.
  - Fresh APK published to `/var/www/download/radd-stream.apk` (23MB).
  - VM health: Load average 1.38, RAM used 4.3GB / 11GB (7.3GB available free RAM), swap 0B.
- **Previous entry below is the 2026-10-26 checkpoint.**

## Previous checkpoint — 2026-10-26 (TMDB artwork backfill, 1-tap phone sync, 356 Android tests green)

- **Goal:** Distinct season/episode artwork backfill, Pakistani phone sign-in (`03XXXXXXXXX`), Sovereign Admin Monetization, and verified debug APK.
- **Done here:**
  1. `Fast_Fetch/backfill_tmdb.py` (new, stdlib only): Queries TMDB for missing poster/backdrops, populating `post_artwork` with distinct season posters and episode stills without duplicating series posters.
  2. `DetailViewModel` & `ReleaseLayoutBuilder`: TV seasons display distinct season posters and episode stills with the main poster as fallback.
  3. `sync/`: 1-Tap Account Sync supporting quick sign-in using Pakistani mobile numbers (`03XXXXXXXXX` → SHA-256 16-char sync key) or 16-character keys.
  4. Sovereign Admin Monetization API mounted at `POST /admin/action/save-monetization` and public `GET /api/v1/app/remote-config`.
  5. `VipUpgradeScreen.kt` & `VipViewModel.kt`: Live PKR pricing (200/1500), 1-tap copy for JazzCash Till ID/Account, EasyPaisa, Raast, and TID transaction submission.
  6. Autonomous 6-hour crawler timer (`radd-autocrawl.timer`) active and healthy.
- **Verified:**
  - Backend suites: `test_database` (58), `test_vidout` (6), `test_backfill_tmdb` (23), `test_redact` (49), `test_accounts` (61), `test_accounts_api` (29), `test_catalog_v2` (91), `test_admin_panel` (39) — ALL PASSING.
  - Android tests: `./gradlew --offline testDebugUnitTest assembleDebug` → **BUILD SUCCESSFUL, 356 tests / 42 classes / 0 failures**.
  - Debug APK deployed to `/var/www/download/radd-stream.apk` (23MB).
- **Previous entry below is the earlier 2026-10-26 UI checkpoint.**

## Previous checkpoint — 2026-10-26 (Android hero, ghost mode, fallback art, stubs gone)

- **Goal:** the four owner asks — HeroCarousel, `ViewMode.PURE_CINEMA`, a branded
  image fallback, and deleting the retired push-script stubs — verified by a real build.
- **Done here:** `ui/components/HeroCarousel.kt` (400dp pager + Watch Now, fed from
  the first visible Home rail, wide art from the list row's `backdrop_urls`), cinema
  ghost mode in `PlayerScreen.kt`/`PlayerUiState.kt`/`PlayerGestures.kt` (edge-hairline
  HUD, no pause scrim, no center button, two-finger 3s rewind persisted like the other
  gesture prefs), `CatalogImage.kt` failure card, and the five root stubs
  (`push.py`, `github_push.py`, `emergency_push.py`, `push_github.py`, `safe_push.sh`)
  deleted after confirming each was a `Disabled:`-and-exit-2 no-op.
- **Crash fixed:** `WireText.splitOnAny`'s unqualified `listOf(source)` resolved to the
  object's own `listOf` member, so any non-JSON text column recursed into
  `StackOverflowError`. New `WireTextTest` covers the CSV/`+`/`/`/bare-URL shapes that
  had no test at all before.
- **Verified:** `./gradlew --offline testDebugUnitTest assembleDebug` → BUILD
  SUCCESSFUL, 320 tests / 0 failures, debug APK produced on this ARM64 host.
- **Not done:** nothing committed (not requested); no device run, so the Compose
  rendering and the two-finger gesture are unverified on hardware. Other workstreams'
  uncommitted edits (`viewer.py`, `redact.py`, `DynamicServerDiscovery.kt`, several
  docs) are still in the tree — review them separately before staging anything.
- **Previous entry below is the 2026-10-25 fleet-catalog checkpoint; its measured
  numbers still stand.**

## Previous checkpoint — 2026-10-25 (Layer-1 projector landed on the full fleet catalog)

Every number below was queried or run in this session; where an earlier entry
asserted something different, the measured value is stated and the claim is
corrected rather than repeated.

- **Goal:** finish the approved plan's three phases (provenance stops at the HTTP
  edge, one brand file, one player) and get the 18-site merged catalog projected,
  validated, and ready to serve — with the app actually usable out of the box.
- **Catalog (measured on `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`):**
  130,007 posts · 1,598,614 releases · 3,699,521 `download_sources` · 273,778
  `post_sources`. The fleet merge moved 201,020 staging posts across 18 sites and
  recorded **1,460** conflicted posts in total — the "395" quoted previously is only
  katmoviehd's share (`{katmoviehd 395, multimovies 362, world4ufree 174,
  hindilinks4u 119, 7starhd 85, vegamovies 76, ssrmovies 68, 10xflix 59, bolly4u 56,
  hdhub4u 53, rogmovies 13}` from the merge report JSON).
- **In flight:** `catalog_v2.py` is projecting that ledger into the `cat_*` tables in
  place (116,912 works / 1,303,122 prints / 3,699,521 links — zero link loss), now in
  its `_finalize` stage. Progress is printed every `RADD_PROJECT_PROGRESS=N` works
  because a multi-hour rebuild on this one-CPU box previously printed nothing and
  looked hung.
- **Completed this session (all committed and pushed to `master`):**
  - `bd8891e` — Layer-1 projector items finished: `REVISION_KEYS` version vector,
    `cat_id_map` id-churn journal, season-pack expansion when the ledger names the
    span, `cat_parts` derivation, offset majority vote, repack tiebreak, per-release
    `identity_suspect`, durable review resolutions, entitlement write path. Plus the
    crawler fix that stops marking an unreadable/empty page `scraped = 1` — the exact
    mechanism that lost ~1.7k katmoviehd and ~2.4k hindilinks4u URLs.
  - `ec44aec` — hindilinks4u now shares `fast_fetch.py`'s permanent/transient cause
    vocabulary and retry budget, tolerates a locked database while booking and
    saving, and trips the site-dark fuse instead of manufacturing failures.
  - `b5d286d` — `API_V2.md` reconciled to the as-built code (every ✅ re-checked
    against function and test name), `HANDOFF_apidocs.md` annotations complete, and
    `_parts_for_work`'s stale "cat_parts is never filled" docstring corrected.
  - Android: `Brand.defaultServerUrl` feeds `ServerSettingsRepository.serverUrl` and
    `SetupViewModel`, so a branded build opens on real content instead of the server
    form; the last hardcoded host literal left `SettingsScreen.kt`; `ReleaseParser.kt`
    collapsed into `ReleaseLayoutBuilder.kt` and `QualityLadder.kt` moved to
    `player/`; `design/SCREENS.md` Screen 4 redrawn as one row per quality band with
    no site, hoster or address anywhere.
- **Checks run and exact result:**
  - Backend offline: **36 of 37 modules green, 793 tests** (`test_all_sites.py` is the
    live 18-site audit — its result depends on upstream sites, not this repo, and is
    excluded from the offline gate). Notables: `test_catalog_v2` 88, `test_catalog_api`
    114, `test_database` 57, `test_redact` 47, `test_api_v2` 46,
    `test_hindilinks4u` 24, `test_hindilinks4u_retry` 13.
  - Android: `./gradlew --offline testDebugUnitTest assembleDebug` → **BUILD
    SUCCESSFUL**, 31 suites / **284 tests / 0 failures / 0 errors**,
    `app-debug.apk` 22,483,468 bytes. (The "245/28" in the 2026-10-24 entry and the
    "520+ across 15 CI modules" claim were both wrong; these are the measured counts.)
  - GitHub: `bd8891e` and `b5d286d..ec44aec` pushed to `master` on the explicit clean
    URL `https://github.com/radddao/radd-stream.git` via the askpass flow.
- **Not done / not claimed:**
  - `SubtitleOffsetSheet.kt` and `HeroCarousel.kt` do not exist; Priority 4 items 1–4
    are **not started**, not "in flight". The Trakt/cloud sync engine likewise exists
    only as a roadmap line.
  - The "stale test files archived to `/home/ubuntu/project_trash_bin/`" claim moved
    three untracked items; no tracked source or test file was deleted.
  - The live API still serves `/home/ubuntu/radd-stream-data/fast_fetch.db` (~201
    posts). Swapping `RADD_DB_PATH` to the projected catalog is an owner decision and
    is prepared, not executed.
  - No Android device or emulator run: this VM has no KVM, so nothing here proves
    on-device behaviour.
- **Next concrete action:** let `_finalize` finish, validate the projected catalog on
  full data (task #37), re-probe the live edge for provenance/adult leaks (task #39),
  then present the pointer swap (task #38) for approval. Merge
  `multimovies_full_20261022.db` (+79,531 releases / +79,782 links the fleet missed)
  before or immediately after the flip (task #45).
- **Blockers / decisions needed (owner):** revoke the GitHub credential embedded in
  `.git/config remote.origin.url` — until then `origin` must never be used; whether
  the public repo keeps documenting hoster and site names (`Fast_Fetch/AGENTS.md`
  bridge table, `domain_registry.json`, `API_V2.md` examples), which is the same
  content removed from the public API; the exposed public Web IDE on this host.

## Previous checkpoint — 2026-10-22 (Docs truth-audit vs viewer.py)

- **Goal:** Remove documentation that asserted API behaviour the code does not
  implement, so future agents and app developers stop building against endpoints
  and filters that cannot work.
- **Method:** every claim re-read against `Fast_Fetch/viewer.py`
  (`do_GET()` 2039-2190, `api_v1_get_posts()` 1886, `api_v1_get_post_detail()`
  1930, `api_v1_rules()` 1968, `generate_m3u_playlist()` 185, stats 2156-2174)
  and `Fast_Fetch/fast_fetch.py` (`classify_media()` 1613-1622,
  `resolve_live_source()` ~4540-4600), plus `PRAGMA table_info` on a staging
  database and one live `api_v1_get_posts()` call. No `.py` or `.kt` file was
  modified; nothing was committed or pushed; no crawler was run.
- **Verified defects corrected in docs:**
  1. **`?type=anime` never matched.** `viewer.py:1898` filters with
     `p.content_type = ?` (exact equality); `classify_media()` only ever writes
     `movie` / `series` / `complete_season` / `ongoing_season`. A live call with
     `content_type='anime'` returned `total: 0` while unfiltered returned
     `10512`. Corrected in `Fast_Fetch/ANDROID_INTEGRATION.md`, `App/AGENTS.md`,
     `App/README.md`, `App/docs/PLAN.md`, `App/design/SCREENS.md`, `README.md`,
     `docs/PROJECT_MAP.md`. **The Kotlin is still broken** —
     `HomeScreen.kt:48` and `SearchScreen.kt:49` still send `type=anime`; fixing
     it needs either a removed chip or a new backend `animated` filter parameter.
  2. **`/api/v1/posts/{id}` does not order releases by tier or group by
     season/episode.** `viewer.py:1942` is `ORDER BY id ASC`. The tier `CASE`
     (viewer.py:1946-1961) applies only to `sources` inside a release:
     `status='active'` first, `is_temporary ASC`, then `pixeldrain`,
     `vegadrive`, `hubcloud_10g`, `fsl_r2`, `fastdl`, `google_cdn`, everything
     else `99`. Documented that the `CASE` matches only those literal strings,
     while real rows commonly carry host-derived names (`fastdl-beer`,
     `vcloud-beer`, `hubcloud-ist`) that all fall through to `99`.
  3. **`/api/v1/sync` does not exist** (no such route, no `do_POST` at all).
     `App/docs/PLAN.md` §3.4 now marks it explicitly as a proposal.
  4. **`api_v1_get_posts()` example omitted real keys.** Corrected to the exact
     `SELECT` list (viewer.py:1905-1909): `id, clean_title, title, year,
     content_type, seasons, poster_url, imdb_rating, imdb_id, tmdb_id, genres,
     source_site, industry, country, language, release_count, source_count`.
     Note `slug` is **not** returned by the list route (contrary to the audit
     brief) — it only appears on the detail response.
  5. **`App/AGENTS.md` self-contradiction resolved.** It claimed the app calls
     only `/api/v1/stats` and `/api/v1/posts` and that Detail/Player/MyList/
     Settings are "not navigable". `RaddStreamApi.kt` declares four endpoints and
     `CatalogRepository.kt:38,46` + `DetailViewModel.kt:69,130` + `NavGraph.kt:139-165`
     actually use detail and stream resolution. §5/§6/§8/§0/§4/§11 rewritten to
     the verified state, with historical Phase 1 lists labelled as plan.
  6. **`/api/heal` hangs.** viewer.py:2100-2108 builds `resp_payload` and never
     calls `send_json()`; `protocol_version = "HTTP/1.1"`, so clients wait for a
     response that never arrives, and a missing/non-numeric `id` raises before any
     response. Documented as broken/unusable in `ANDROID_INTEGRATION.md`,
     `App/docs/PLAN.md`, `README.md`, `docs/PROJECT_MAP.md`. **The Python was not
     changed**, per task scope.
  7. **No auth, no keys, no rate limiting, no HTTPS.** Verified by grepping
     `viewer.py` for `Authorization` / `api_key` / `rate_limit` / `Bearer` — zero
     hits. `send_json()` emits `Access-Control-Allow-Origin: *` (viewer.py:2037)
     and `start_server()` defaults to `0.0.0.0` (viewer.py:2211). Removed the
     "auth token injection" bullet from `App/docs/TECH_STACK.md`, the `token`
     profile field from `App/docs/PLAN.md` §3.3, and added explicit public-surface
     warnings wherever docs implied privacy.
  8. **Stale numbers relabelled.** The `131 / 1031 / 2017` figures were a
     2026-10-13 snapshot; `/api/v1/stats` field *names* kept exactly as the code
     returns them and values labelled illustrative. `docs/PROJECT_MAP.md` no
     longer implies the suite is only `test_database.py` + `test_vidout.py` — 26
     `Fast_Fetch/test_*.py` modules exist today.
- **NEW contradictions found beyond the eight briefed:**
  - `Models.kt:68-84` `ReleaseDetail` maps `season_number`, `episode_number`,
    `episode_title`, `resolution`, `audio` — **none of those keys exist** in the
    `releases` payload (`PRAGMA table_info`: `release_title, season, episode,
    quality, codec, size, languages, intermediate_url, origin_url, ...`).
    `DetailScreen.kt:206-220,426-428` builds its entire season/episode grouping on
    those always-null fields, so series grouping silently does nothing.
  - `StreamResponse.isTemporary: Int?` cannot receive the JSON **boolean**
    `resolve_live_source()` returns (`is_temporary` is wrapped in `bool(...)`), so
    Gson rejects that field on `redirect=0` responses.
  - `AndroidManifest.xml:43-48` registers a `radd://` intent filter but
    `NavGraph.kt` declares no `navDeepLink` entries — deep links cold-start to the
    default destination and route nowhere.
  - `/api/v1/stats` has **no** `is_18_plus` filter (viewer.py:2157-2162), so its
    `posts` count exceeds what `/api/v1/posts` can ever show. Docs now say so.
  - `App/design/SCREENS.md` Screen 2 draws a hero banner and per-type `LazyRow`
    sections; `HomeScreen.kt` implements a single `LazyVerticalGrid` only.
  - `PLAN.md` §2.3/§2.2 (downloads, continue-watching) genuinely unbuilt, but
    §3.1 external-player hand-off **is** built (`DetailScreen.kt:529-539`) — the
    roadmap has now been split accordingly.
- **Checks run:** read-only `api_v1_get_posts()` / `api_v1_get_post_detail()`
  calls against `Fast_Fetch/multimovies.db` via `RADD_DB_PATH` (no writes);
  `PRAGMA table_info` on `posts` / `releases` / `download_sources`; content_type
  distribution query (`movie` 7753, `series` 2759, `anime` 0); grep sweeps for
  `anime` / `auth` / `sync` / `heal` across all twelve permitted docs. No test
  suite was executed in this session and no server was started.
- **Files changed (Markdown only, nothing committed or pushed):** `README.md`,
  `Fast_Fetch/ANDROID_INTEGRATION.md`, `Fast_Fetch/DATABASE_SCHEMA.md`,
  `App/AGENTS.md`, `App/README.md`, `App/docs/PLAN.md`, `App/docs/TECH_STACK.md`,
  `App/design/SCREENS.md`, `docs/PROJECT_MAP.md`, `docs/SESSION_CHECKPOINT.md`.
  `Fast_Fetch/DATABASE_SCHEMA.md` already documented `content_type` correctly
  (lines 50 and 148 list the four real values), so the only edit there is the new
  warning that its canonical `download_sources.service` vocabulary is not the tier
  ranking and does not match the host-derived values real rows carry. `Fast_Fetch/SITES.md` was checked — its
  "anime" mentions are third-party site genre labels and its `/api/...` references
  are the *sites'* WordPress and KatDrive endpoints, not this project's API, so it
  was left untouched. `docs/AI_HANDOFF_PROMPT.md` contains no API claims.
- **Next action:** fix the three Kotlin/backend defects above (anime chip,
  `ReleaseDetail` field names, `StreamResponse.isTemporary` type) or add an
  `animated` query parameter to `api_v1_get_posts()`; then add the missing
  `send_json(resp_payload)` to the `/api/heal` branch at viewer.py:2108. Re-run
  `python -S Fast_Fetch/test_database.py` and the full `test_*.py` set after any
  code change.

## Previous checkpoint — 2026-10-21 (Milestone 7)

- **Goal:** Rule change per owner directive — scrapers no longer skip adult content; 100% of each site's catalog is stored with full metadata/links behind an `is_18_plus` flag column in every staging database; every presentation surface (REST API, dashboard, M3U, stream resolver, Android app) filters `is_18_plus=1`.
- **Completed:**
  1. Rules rewritten in root `AGENTS.md` and `Fast_Fetch/AGENTS.md` (store flagged, never display).
  2. `fast_fetch.is_adult_title()` shared helper added (fixed latent `\b18\+\b` regex bug); `resolve_live_source()` blocks 18+ source ids.
  3. Flag-not-skip conversion in 5 scrapers; `is_18_plus` inserted (MAX-merged) in all 10 custom-schema scrapers; CREATE + ALTER migrations in each.
  4. All 16 staging DBs now carry `posts.is_18_plus`; 795 previously skipped adult posts re-queued; 36,848 failed posts reset to pending fleet-wide.
  5. `viewer.py` API/dashboard/M3U filters exclude flagged rows.
- **Checks run:** 21/21 offline test modules; import checks; helper smoke tests; synthetic adult-save verified.
- **Fleet:** 15 scrapers relaunched at full speed (sync-then-crawl, workers=4, delay=0.2); KatMovieHD heal still running from earlier.
- **Next action:** Monitor fleet to completion, verify per-site `is_18_plus=1` counts, snapshot databases to Hugging Face.

## Previous checkpoint — 2026-10-21 (Milestone 6)


- **Goal:** Resume the token-limited Milestone 5 session directly on the Oracle VM, finish and verify the in-progress Domain Resolver & Auto-Discovery Engine, and record crawler fleet completion.
- **Completed:**
  1. **Crawler fleet victory confirmed** — all four Milestone 5 crawlers finished cleanly: KatMovieHD (39,277 scraped / 7,938 failed, 130,113 sources), Bolly4U (28,280 scraped, 21,875 sources), World4uFree (13,837 scraped, 85,654 sources), MoviezGuru (3,372 scraped, 8,850+ sources).
  2. **Domain Resolver & Auto-Discovery Engine landed** (`Fast_Fetch/domain_resolver.py` + `domain_registry.json`): registry-driven live domain tracking, redirect-following `probe_site()`, mirror auto-failover across 16 sites, integrated into all 15 `import_*.py` scrapers; FilmyZilla migrated to `thefilmyzilla.in`, HDHub4u to `new8.hdhub4u.cl`, Bolly4U to `bolly4uv.com`, 10xflix to `10xflix.hair`, 7StarHD to `7starhd.dentist`, SSMMovies to `ssrmovies.surf`, MultiMovies to `m1.multimovies.courses`, Vegamovies to `new1.vegamovies.lease`, KatMovieHD to `new.katmoviehd.top`.
  3. **Quality Gate:** all 21 offline test modules pass; all modified importers import cleanly; live `probe_site()` smoke test 200 OK for filmyzilla and hdhub4u.
  4. `auto_chat_sync.py` (PID 210724) confirmed continuously persisting chat to `Fast_Fetch/CHAT_HISTORY.md`.
- **Next action:** Retry-failed posts on katmoviehd/bolly4u/world4ufree (heal pass), snapshot databases to Hugging Face, expand remaining scrapers (`import_9xmovies.py`, `import_10xflix.py`, `import_hdhub4u.py`) for cast/director/synopsis extraction.

## Previous checkpoint — 2026-10-20 (Milestone 5)

- **Goal:** Overhaul KatMovieHD crawler (`import_katmoviehd.py`) with modern multi-host support (BBUpload, GoFile, 1XPlayer, SuperDuperLoad), enrich DesiCinemas with cast/director metadata, and audit database fleet.
- **Architectural Breakthroughs & Deployments:**
  1. **KatMovieHD Root Cause Resolved & Overhauled (`Fast_Fetch/import_katmoviehd.py`)**:
     - Diagnosed why 47,215 titles failed (`scraped = -1`): site migrated from legacy `kmhd.*` links to `bbupload.to`, `gofile.io`, and `1xplayer.com`.
     - Reverse-engineered `download.bbupload.to/ajax.php?action=getdownload&data=<ID>` with `X-Requested-With` header: yields direct `https://superduperload.site/get/...` stream URLs, exact filenames, and exact file sizes in bytes with zero Cloudflare Turnstile blocks.
     - Added direct GoFile cloud storage unwrapping and 1XPlayer (`vd.1xplayer.com/play/...`) streaming embeds.
     - Added rich metadata extraction: `director`, `cast_names`, `genres`, `languages`, `synopsis`, and Amazon/TMDB posters.
     - Auto-migrated `katmoviehd.db` `posts` table with `director`, `cast_names`, and `languages` columns.
     - Re-queued 47,215 failed posts in `/home/ubuntu/radd-stream-data/katmoviehd.db` (`scraped = 0`).
     - Added unit tests in `Fast_Fetch/test_katmoviehd.py` (5/5 passing).
     - Launched background crawler writing to `/home/ubuntu/radd-stream-data/katmoviehd.db` (PID 302661).
  2. **DesiCinemas Metadata Enrichment (`Fast_Fetch/import_desicinemas.py`)**:
     - Completed full catalog ingestion (5,270 titles, 5,270 releases, 4,325 streaming sources) into `desicinemas.db`.
     - Added extraction for `director`, `cast_names`, `genres`, `languages`, and `synopsis`.
     - Unit tests in `Fast_Fetch/test_desicinemas.py` (7/7 passing).
  3. **Database Fleet Audit**:
     - Audited all 17 SQLite staging databases: **129,697 posts**, **1,121,719 releases**, and **2,945,395 direct sources/download links** (~3.1 GB).
  4. **Active Crawler Fleet Status**:
     - `bolly4u.db` (PID 161377): >26,300 processed, >35,500 releases, 21,875 sources (12,677 Google CDN).
     - `world4ufree.db` (PID 249172): >10,500 processed, >55,700 releases, >63,500 sources.
     - `moviezguru.db` (PID 277265): >600 processed, >1,290 releases, >1,670 sources.
     - `katmoviehd.db` (PID 302661): re-crawling 47,215 titles with BBUpload, GoFile, and 1XPlayer streams.
     - `auto_chat_sync.py` (PID 210724): continuous real-time chat persistence.
  5. **Quality Gate**: 65/65 offline unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6], `test_desicinemas.py` [7], `test_katmoviehd.py` [5]).
- **Next action:** Expand remaining scrapers (`import_9xmovies.py`, `import_10xflix.py`, `import_hdhub4u.py`) for cast/director/synopsis extraction, snapshot databases to Hugging Face, and analyze FilmyZilla expansion.

## Previous checkpoint — 2026-10-20 (Milestone 4)

- **Goal:** Complete 9xmovies ingestion, conquer DesiCinemas scraper (`desicinemas.pk`) with Dean Edwards packed HLS unwrapper, and expand concurrent crawler fleet.
- **Architectural Breakthroughs & Deployments:**
  1. **9xmovies Ingestion Finished**:
     - Completed crawling `https://9xmovie.bayern` yielding **323,565 streams** across 29,663 releases and 11,560 posts stored in `/home/ubuntu/radd-stream-data/9xmovies.db`.
  2. **DesiCinemas Conquered (`Fast_Fetch/import_desicinemas.py`)**:
     - Automated sitemap ingestion across 7 Yoast XML sitemaps (5,299 URLs queued).
     - Reverse-engineered DooPlay `trembed` router: unwraps VidSrc Me, Netu/Waaw, OK.ru, WatchX, RPMPlay, Short.ink.
     - Built pure Python stdlib Dean Edwards JS unpacker (`unpack_dean_edwards`) resolving `peytonepre.com` packed players directly to `.m3u8` master HLS playlist streams.
     - Unit test suite `Fast_Fetch/test_desicinemas.py` (7/7 passing).
     - Background crawler launched in staging isolation `/home/ubuntu/radd-stream-data/desicinemas.db` (PID 286778).
  3. **Master-Disciple Dual-Tier Workflow Verified**: Delegated title cleaning and test stubs to local offline Qwen (`/usr/local/bin/disciple`) saving cloud tokens, followed by divine review and hardening.
  4. **Active Crawler Fleet Status**:
     - `9xmovies.db`: 323,565 streams (100% finished).
     - `moviezguru.db` (PID 277265): actively unwrapping 10Gbps Google CDN streams.
     - `world4ufree.db` (PID 249172): >8,200 posts, >46,600 sources.
     - `bolly4u.db` (PID 161377): >24,400 posts, >21,800 sources.
     - `desicinemas.db` (PID 286778): 5,299 catalog titles, actively resolving HLS and player embeds.
  5. **Quality Gate**: 60/60 offline unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6], `test_desicinemas.py` [7]).
- **Next action:** Monitor active crawlers, prepare Hugging Face backup snapshot, and identify next site.

## Previous checkpoint — 2026-10-20 (Milestone 3)

- **Goal:** Launch MoviezGuru crawler (`import_moviezguru.py`), maintain concurrent crawler fleet on Oracle VM, and track staging database ingestion metrics.
- **Architectural Breakthroughs & Deployments:**
  1. **MoviezGuru Conquered (`Fast_Fetch/import_moviezguru.py`)**:
     - WP REST API ingestion for `https://moviezguru.guru` (3,391 titles).
     - Reverse-engineered `mzgserver.shop/file/<ID>` bridge unwrapping: resolves through `/dl/<MD5>` directly to high-throughput 10Gbps Google CDN streams (`drive.usercontent.google.com`).
     - Added comprehensive unit tests in `Fast_Fetch/test_moviezguru.py` (6/6 passing).
     - Background crawler launched in staging isolation `/home/ubuntu/radd-stream-data/moviezguru.db` (PID 277265).
  2. **Active Crawler Fleet Expansion**:
     - `bolly4u.db` (PID 161377): >24,000 titles, >21,000 sources (12,677 10Gbps Google CDN).
     - `world4ufree.db` (PID 249172): >7,600 titles, >40,000 sources (multi-domain parser active).
     - `9xmovies.db` (PID 261855): >11,000 titles, >247,000 sources resolved, 0 failures.
     - `moviezguru.db` (PID 277265): 3,391 titles synced, actively unwrapping Google CDN streams.
     - `auto_chat_sync.py` (PID 210724): continuous real-time chat persistence.
  3. **Quality Gate**: 53/53 unit tests passing (`test_database.py` [36], `test_vidout.py` [6], `test_9xmovies.py` [5], `test_moviezguru.py` [6]).
- **Next action:** Analyze and conquer DesiCinemas (`desicinemas.pk`) or next target site.

## Previous checkpoint — 2026-10-20 (Milestone 2)

- **Goal:** Repair World4uFree multi-domain parser gap, conquer 9xmovies scraper (`9xmovie.bayern`), demonstrate Master-Disciple local AI law via Ollama Qwen 1.5B, and run concurrent crawler cluster.
- **Architectural Breakthroughs & Deployments:**
  1. **Master-Disciple AI Delegation**: Used local offline Qwen (`/usr/local/bin/disciple`) to draft function signatures, title cleaning, regex patterns, and test suites, preserving cloud tokens. Reviewed and tested before integration.
  2. **World4uFree Parser Repair & Re-crawl**: Diagnosed why 16,758 posts failed (parser only matched `w4links.space` and ignored 68,000+ `fastilinks.beauty`, 7,000+ `wlinksi.site`, and 3,200+ `cloud.mail.ru` links). Added multi-domain link extraction and fallback gateway preservation (Zero Data Loss). Reset 16,758 posts and resumed crawler in background (PID 249172).
  3. **9xmovies Conquered (`Fast_Fetch/import_9xmovies.py`)**: Built full WP REST API crawler for `https://9xmovie.bayern` (20,347 posts). Reverse-engineered `linksddr.com/view/<TOKEN>` session-cookie CSRF unwrapping yielding direct 10Gbps Google CDN, HubCloud, HubDrive, FilePress, GoFile, Streamtape, 1Fichier, and MegaUp streams. Dedicated staging DB `/home/ubuntu/radd-stream-data/9xmovies.db`. Launched background crawler (PID 250953).
  4. **Active Crawler Cluster on Oracle VM**:
     - `import_bolly4u.py` (PID 161377): 20,880+ titles, 30,000+ releases.
     - `import_world4ufree.py` (PID 249172): re-crawling 16,758 posts with multi-domain parser.
     - `import_9xmovies.py` (PID 250953): syncing 20,347 posts & crawling unwrapped streams.
     - `auto_chat_sync.py` (PID 210724): real-time chat persistence active.
  5. **Unit Test Quality Gate**: 47/47 offline unit tests pass (36 `test_database` + 6 `test_vidout` + 5 `test_9xmovies`).
- **Next action:** Monitor active crawlers, proceed to analyze and conquer next streaming site or address `katmoviehd` content extraction.

- **Goal:** Implement local Master-Disciple AI workflow via Ollama `qwen2.5-coder:1.5b` (`disciple.py`), repair and resume `10xflix` background crawler, deploy real-time auto chat sync daemon, and maintain strict staging database isolation.
- **Architectural Breakthroughs & Deployments:**
  1. **Master-Disciple Dual-Tier Local AI**: Implemented `Fast_Fetch/disciple.py` and `/usr/local/bin/disciple` connected to local Ollama on Oracle VM. Local Qwen drafts boilerplate, unit tests, and regex at 0 cloud token cost; Antigravity reviews and verifies.
  2. **10xflix Float Parser Fix & Resilience**: Fixed malformed size string bug (`'3.73.GB'`) in `parse_size_string` in `import_10xflix.py`. Wrapped `process_item` and worker results in exception guards to prevent worker aborts. Added unit tests in `test_10xflix_import.py`.
  3. **10xflix Crawler Resumed**: Restarted `import_10xflix.py` inside persistent detached session `tmux: crawler-10xflix` (PID 198100, 5 workers, 0.3s delay, past 6,620+ titles with 0 errors).
  4. **Real-Time Background Chat Persistence Daemon**: Created and launched `Fast_Fetch/auto_chat_sync.py` inside persistent session `tmux: chat-sync`. Continuously polls Antigravity transcript logs and appends every user/model turn directly to `Fast_Fetch/CHAT_HISTORY.md` in real-time.
  5. **Active Concurrent Crawler Cluster**: 4 crawlers concurrently operating on Oracle VM (`10xflix.db`, `world4ufree.db`, `bolly4u.db`, `katmoviehd.db`). Strict staging DB isolation maintained with zero merges into `fast_fetch.db`.
- **Verification:** 142/142 unit tests passed across 14 modules.
- **Next action:** Continue monitoring 4 background crawlers, proceed with next scraper conquest or API enhancements.

### 2026-10-17 — MultiMovies scraper resume and chat export

### 2026-10-16 — Android App MVP & CI pipeline implementation
- **Goal:** Implement full Android app flow (navigation, details, player, local favorites, settings) and establish root GitHub Actions CI.
- **Completed:**
  1. Created root `.github/workflows/ci.yml` and `.github/workflows/release.yml`.
  2. Created Unix launcher `App/gradlew` with executable permissions.
  3. Implemented Bottom Navigation Bar in `NavGraph.kt` (Home, Search, My List, Settings).
  4. Implemented `DetailScreen.kt` and `DetailViewModel.kt` supporting movies, series season filters, source resolution, and external player launch.
  5. Implemented `PlayerScreen.kt` with Media3 / ExoPlayer full-screen playback.
  6. Implemented Room local database (`FavoritePost`, `FavoriteDao`, `AppDatabase`, `DatabaseModule`, `FavoritesRepository`).
  7. Implemented `MyListScreen.kt` and `MyListViewModel.kt`.
  8. Implemented `SettingsScreen.kt` and `SettingsViewModel.kt` with live server stats.
  9. Extended `Models.kt`, `RaddStreamApi.kt`, `CatalogRepository.kt`, `PosterCard.kt`, and `ModelsTest.kt`.
- **Checks run:**
  - `python -S Fast_Fetch/test_database.py`: 36/36 passed.
  - `python -S Fast_Fetch/test_vidout.py`: 6/6 passed.
  - Live Oracle API tests: `/api/v1/posts`, `/api/v1/posts/203` (details), `/api/v1/stream?id=1` (streams), `/api/v1/stats` all return 200 HTTP OK; administrative routes remain 403 Forbidden.
- **GitHub Status:** Pushed directly to `main` (commit `e0e116e`). Rule updated per owner instruction to permit direct pushes of verified milestones to `main`.
- **Note on GitHub Actions:** GitHub API returns `Actions has been disabled for this user`. The repository has actions enabled, but user account `radddao` needs Actions re-enabled in account billing/settings.
- **Oracle Status:** Live server Nginx updated to proxy `/api/v1/posts` and `/api/v1/stream` to the local backend. Detail and playback endpoints are verified live.

### 2026-10-16 — Android APK Compilation & Server Deployment
- **Goal:** Compile native `app-debug.apk` directly on Oracle server and serve it publicly for download.
- **Completed:**
  1. Solved Google AAPT2 ARM64 binary incompatibility on Oracle by installing `qemu-user-static` and extracting AMD64 dynamic libraries (`libc6`, `libstdc++6`, `zlib1g`).
  2. Executed full Gradle build (`./gradlew assembleDebug`) compiling all Compose UI screens, Room DB, ExoPlayer, and D8/R8 bytecode packaging.
  3. Successfully compiled 21.5 MB `app-debug.apk` with exit code 0.
  4. Deployed APK to `/var/www/download/radd-stream.apk`.
  5. Verified public download endpoint: `http://92.4.95.252/download/radd-stream.apk` returns HTTP 200 OK with `Content-Disposition: attachment`.
- **Checks run:**
  - `python -S Fast_Fetch/test_database.py`: 36/36 passed.
  - `python -S Fast_Fetch/test_vidout.py`: 6/6 passed.
  - `curl -I http://92.4.95.252/download/radd-stream.apk`: HTTP/1.1 200 OK, Content-Length: 21510182.
- **Download Link:** `http://92.4.95.252/download/radd-stream.apk`

### 2026-10-21 — HDHub4u link-topology recovery + two new sites (HindiLinks4u, ToonWorld4All)

- **Goal:** Heal the last failing scrapers, add the three owner-requested sites, and make the
  adult `is_18_plus` flag reliable on every write path.
- **Completed:**
  1. **HDHub4u** (`import_hdhub4u.py`): bridge regexes now also match `linkrit.` and `hubcloud.`
     hosts (old greenmotors links are gone), hubcloud `/drive/<id>` links are unwrapped via
     `fast_fetch.unwrap_hubcloud_drive()`, unresolvable linkrit bridges are stored as bridge
     sources instead of being dropped, and `normalize_hdhub4u_loc()` repoints stale
     `new2/new3.hdhub4u.free` sitemap rows at the live `new8.hdhub4u.cl` host while status
     updates still key on the original stored `loc`.
  2. **FilmyZilla**: verified the redesign pipeline end to end on `thefilmyzilla.in`
     (post → `/server/<slug>.html` → `/download/<id>/server_N` → `fzcdn.store/file/<base64>`);
     remaining `-1` rows are 620 posts absent from the new site plus ~2,842 stub posts whose
     pages carry quality text but no download links at all. Statuses recorded, nothing discarded.
  3. **New site HindiLinks4u** (`import_hindilinks4u.py`, `www.hindilinks4u.zip`): the `.pink`
     domain is behind a Cloudflare JS challenge and was NOT bypassed; the plain-HTML `.zip`
     mirror serves the same catalog (32,271 titles queued). Rewrote `clean_hl4u_title()` to stop
     mid-word truncation ("Bigg Boss" → "Bigg Bo") and dangling-paren leaks ("MobLand (2025").
  4. **New site ToonWorld4All** (`import_toonworld4all.py`, Hindi anime): WP REST API discovery +
     `archive.toonworld4all.me/episode/…` `window.__PROPS__` payloads; one release per encode with
     per-quality mirrors, `/redirect/<hex>` unwrapped to `hubcloud.ist` final URLs via the new
     `--resolve` flag, season-scoped canonical keys (`…_sNN`), legacy `tw4all.workers.dev` tokens
     decoded. Fixed a bug where every release shared one cumulative source list (inflating source
     counts ~2x and mixing qualities) and added a stream-only release fallback.
  5. **Adult flag safety net**: `fast_fetch.save_scraped_data()` now derives `is_18_plus` from
     `is_adult_title()` for every importer that leaves it unset (vegamovies, rogmovies, hdtvb,
     7starhd, ssrmovies all wrote a literal 0). `import_multimovies.py` no longer skips restricted
     titles — it ingests them flagged. Extended `ADULT_TITLE_PATTERNS` with studio names
     (RealityKings, Tushy, Vixen, Blacked, Wankz, Lustery, Moodyz, iuliian, Uncut, Naughty).
  6. Back-flagged every existing staging row: 10xflix 2,665 · 9xmovies 2,726 · katmoviehd 974 ·
     hdhub4u 817 · bolly4u 972 · 7starhd 2,296 · world4ufree 425 · filmyzilla 423 · ssrmovies 924 ·
     hdtvb 1,161 · rogmovies 879 · vegamovies 445 · hindilinks4u 165 · moviezguru 97 ·
     desicinemas 7 · rareanimes 7 · multimovies 30 · toonworld4all 1.
  7. Registered `hindilinks4u` and `toonworld4all` in `domain_registry.json`; documented both in
     `Fast_Fetch/SITES.md` (sections 11 and 12).
  8. **Merge tool handles both staging families** (`merge_catalogs.py`): detects
     `sources` vs `download_sources` schemas, maps staging release columns onto the unified
     shape, tolerates per-site column drift, and deduplicates repeated `canonical_key` rows onto
     one catalog record while keeping the displaced page URL in `post_sources`. Verified by
     merging 300 posts from each of 7 databases and 30 from each of the other 11 — zero errors.
- **Files changed:** `Fast_Fetch/fast_fetch.py`, `Fast_Fetch/import_hdhub4u.py`,
  `Fast_Fetch/import_multimovies.py`, `Fast_Fetch/merge_catalogs.py`,
  `Fast_Fetch/import_hindilinks4u.py` (new), `Fast_Fetch/import_toonworld4all.py` (new),
  `Fast_Fetch/domain_registry.json`, `Fast_Fetch/test_hindilinks4u.py` (new, 8 tests),
  `Fast_Fetch/test_toonworld4all.py` (new, 12 tests), `Fast_Fetch/test_merge_catalogs.py`
  (3 tests), `Fast_Fetch/SITES.md`, `Fast_Fetch/CONTINUITY.md`, `docs/SESSION_CHECKPOINT.md`,
  crawler `*_status.json` snapshots.
- **Checks run and exact result:** `test_database.py` 36/36 OK · `test_vidout.py` 6/6 OK ·
  `test_hdhub4u_import.py` 25/25 OK · `test_multimovies_import.py` 9/9 OK ·
  `test_filmyzilla_import.py` 8/8 OK · `test_hindilinks4u.py` 8/8 OK · `test_toonworld4all.py`
  12/12 OK · `test_merge_catalogs.py` 3/3 OK (new staging-family + dedup cases) · every
  pre-existing offline test module re-run OK (23 modules, 160 tests, no network).
- **Known failures or checks not run:** `test_all_sites.py` live audit not re-run this session;
  Android app not built (no app-side change needed); no merge into `fast_fetch.db` yet.
- **GitHub branch/commit/push result:** committed to `master` and pushed (see commit below).
- **Oracle deployment result:** not deployed — code is live-source only; staging DBs remain on
  `/home/ubuntu/radd-stream-data/`.
- **Next concrete action:** let the three running crawlers finish (HDHub4u ~4.4h, HindiLinks4u ~2.3h,
  ToonWorld4All ~2.4h), then run `python3 Fast_Fetch/import_toonworld4all.py --resolve-bridges`
  to back-fill Toon CDN URLs and merge every staging DB into `fast_fetch.db` with
  `python3 Fast_Fetch/merge_catalogs.py <site>.db --target-db /home/ubuntu/radd-stream-data/fast_fetch.db`
  (the merge tool now handles both staging schema families), re-verify the API/dashboard/M3U
  18+ filters against the merged totals, and snapshot the merged DB.
- **Blockers / decisions needed:** Shemaroo (owner chose "skip"); owner still needs to revoke the
  GitHub credential that was exposed in an earlier session (value never recorded here).

## Template for future checkpoints

### YYYY-MM-DD — short milestone name

- **Goal:**
- **Completed:**
- **Files changed:**
- **Checks run and exact result:**
- **Known failures or checks not run:**
- **GitHub branch/commit/push result:**
- **Oracle deployment result (or why not deployed):**
- **Next concrete action:**
- **Blockers / decisions needed:**

### 2026-10-23 — Master Architect Directive & Senior Mentor Guidance to Qoder
- **Goal:** Ratify the 20-year architectural vision, multi-VM cluster strategy ($0 cost), infinite site expansion protocol, and mentor guidance for Qoder agent (`qwen2.5-coder:1.5b`).
- **Completed:**
  1. Authored and published `docs/MASTER_ARCHITECT_DIRECTIVE.md` defining the 20-year blueprint (Zero-bandwidth 302 engine, 100% Python stdlib, multi-VM Oracle cluster, Hugging Face sync, SQLite FTS5, Netflix UI + MX Player parity).
  2. Authored and published `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md` providing senior mentorship to Qoder with 7 smart methods (Multi-CDN silent failover ladder, Smart binge pre-caching, MX Player Pro gesture engine, Adaptive quality switcher, Offline P2P WiFi sharing, Sleep timer with fade-out, Dual audio track matcher).
  3. Verified completion of ToonWorld4All bridge resolution: 225,833 / 226,438 links resolved (99.7% completion).
  4. Audited and confirmed Qoder's Task 28 execution (One winner per quality tier + silent failover, `tiers.py`, `redact.py`).
  5. Verified 118+ backend unit tests passing cleanly across `test_database` (50/50), `test_vidout` (6/6), `test_tiers` (16/16), and `test_redact` (46/46).
  6. Authored and published `docs/SITE_SCOUT_SPEC.md` documenting the automated scraper reverse-engineering and synthesis engine for rapid site onboarding.
- **Next concrete action:** Let Qoder finish Task 28 quality tier collapse, verify offline Gradle build `:app:compileDebugKotlin`, stage & commit verified Android app tree, and execute staging merge once approved.

### 2026-10-24 — Nightly safety pass + backend/app milestone landed
- **Goal:** run the nightly test gate, back up every database, land reviewed work, stop the live API leaking provenance, and establish the VM-centric build workflow.
- **Completed:** 
  1. Backend milestone `b1d6077` (redaction at the v1 edge, honest `resolve_live_source` v2 contract, `init_db` index-after-migration fix, unmounted `api_v2.py`, site scout, link state, importer resilience) and app milestone `79b754d` (offline cache engine, quality ladder + in-player switch, audio boost/track matching/binge preload, LAN share, `Brand.load` at startup). Live `radd-stream.service` restarted from the committed code; `/api/v1/posts` and `/api/v1/posts/{id}` now carry no `source_site`, no hoster name and no upstream URL, and `play_url` is our own `/api/v1/stream?id=<opaque>`.
  2. Fleet Merge actively running: `merge_fleet.py` merging 18 staging databases into `merged_catalog_20261024.db` (8 sites complete, 60k+ posts merged so far).
  3. VM-Centric Mandate: codified in `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md` directing all development, UI polish, testing, and APK packaging to this VM.
  4. Packaging & Downloads: `app-debug.apk` (22.5 MB) and `radd-stream-android-bundle.zip` (586 KB) live on `/var/www/download/`.
- **Files changed:** `Fast_Fetch/*.py` (31 files), `App/app/src/**` (51 files), `.gitignore`, `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md`.
- **Checks run and exact result:** test_database 54, test_redact 47, test_catalog_api 114, test_tiers 23, test_link_state 28, test_site_scout 25, test_provenance_stamping 12, test_hindilinks4u 24, test_katmoviehd_import 14, test_desicinemas 11, test_hdtvb_import 8 — all OK; `:app:assembleDebug` green; `:app:testDebugUnitTest` 245 tests / 28 suites / 0 failures.
- **Next concrete action:** Complete 18-site fleet merge into `merged_catalog_20261024.db`, finish wiring Compose gesture HUD overlays and Quality ladder bottom sheet in `PlayerScreen.kt`, and copy updated APK to download directory after each milestone.

### 2026-10-26 — Artwork backfill + one-tap phone/16-character sync

- **Goal:** distinct season posters/episode stills per work and a one-tap optional account.
- **Completed:** `Fast_Fetch/backfill_tmdb.py` (stdlib, env-only TMDB credential, resumable,
  missing-art-only unless `--force`); `post_artwork` table + `season_artwork` on
  `/api/v1/posts/{id}` with public-host filtering; `ReleaseLayoutBuilder`/`DetailViewModel`
  consume the published art and keep the pool only as fallback; `accounts.py` mints
  16-character/96-bit keys and accepts the app's phone-derived key; the account card signs
  in on one tap with `03XXXXXXXXX` or a 16-char key and syncs immediately.
- **Checks run and exact result:** backend — database 58, vidout 6, backfill_tmdb 23,
  redact 49, accounts 61, accounts_api 29, catalog_v2 91, provenance_stamping 12, all OK.
  Android — `testDebugUnitTest` 356 tests / 42 classes / 0 failures (cache disabled);
  `assembleDebug` green, `app-debug.apk` produced.
- **Known failures or checks not run:** no TMDB credential was read and no live backfill was
  performed; no device/emulator run for the account card or season grid.
- **GitHub branch/commit/push result:** not committed (no commit requested).
- **Oracle deployment result:** not deployed (unverified WIP plus unrelated uncommitted work).
- **Next concrete action:** run `backfill_tmdb.py --dry-run` with an operator-supplied
  `TMDB_BEARER_TOKEN`, then a real pass against the production catalog; manually exercise
  phone sign-in and a series detail screen on a device.
- **Blockers / decisions needed:** the owner must accept that a phone-derived key has only
  phone-space entropy (stated in the UI) or make the random 16-character key the only door.

### 2026-10-27 — Remote controls, direct-media resolution, offline playback

- **Goal:** operator toggles for maintenance/update banner/feature flags, resolvers that
  never hand a bridge page to the player, and downloaded files that play with no network.
- **Completed:** `app_remote_config` extended in place and published by
  `/api/v1/app/remote-config`; `is_bridge_url`/`is_direct_media_url` guards plus
  `unwrap_gdflix` and the FastDL branch fix in `fast_fetch.py`; `PlaybackService` reads
  local `content://`/`file://` URIs through `DefaultDataSource`.
- **Checks run and exact result:** `python3 -S -m unittest test_database.py
  test_vidout.py test_admin_panel.py` → 112 tests OK; the five affected suites together
  (`+ test_redact + test_operator_isolation`) → 182 tests OK; `:app:compileDebugKotlin`
  → BUILD SUCCESSFUL.
- **Known failures or checks not run:** no device/emulator, so airplane-mode playback is
  not physically observed.
- **GitHub branch/commit/push result:** not committed (no commit requested).
- **Oracle deployment result:** not deployed.
- **Next concrete action:** on a device, download a title, enable airplane mode, play it
  from Downloads; then flip the three feature flags and confirm the app honours them.

### 2026-10-27 — Luxury polish, binge pre-cache, sponsor-slot guard, keyless ratings

- **Goal:** finish the overnight polish pass: shimmer placeholders, release-tier audio/HDR
  badges, 85% binge pre-resolution, a structural guarantee that no sponsor break can appear
  mid-title, and a live Cinemeta pass to fill missing genres/IMDb scores.
- **Completed:**
  1. `ShimmerBox` (moving highlight band, reduced-motion aware) now backs `SkeletonBox` and
     every `CatalogImage` loading slot, so `PosterCard`, rails and `HeroSkeleton` all load
     with one animation instead of blank boxes.
  2. `MediaBadges` gained HDR / source / dual-audio / subtitle badges; `DetailScreen` shows
     them in a `FlowRow` on both the per-episode best print and every release card.
  3. `PlayerViewModel` now carries the episode scope onto route-launched bundles
     (`SyncScope.postId/workType` + `PlaybackBundle.withStagedTarget`) and, at 85%, resolves
     the successor's ladder/handle through the redirector. END/manual-next opens the
     prepared handle directly and stores its failover/ladder, with an on-demand lookup
     fallback.
  4. `AdSlotPolicy` + `AdSlotPolicyTest` make placement structural: `PRE_ROLL` only while
     paused at the start, `BETWEEN_EPISODES` only at a real END with a successor, and
     `NONE` for every running title. `PlayerUiState.adBreak`, `requestAdBreak()` and a guarded
     `SponsorBreakDialog` are wired; nothing raises a break automatically because the app
     ships no ad SDK or creative.
  5. `backfill_tmdb.py` now writes `posts.imdb_rating` from Cinemeta `imdbRating`, treats
     junk labels (`"."`, `"N/A"`, `"0"`) as missing, and includes the column in candidate
     selection. One keyless live pass on `/home/ubuntu/radd-stream-data/fast_fetch.db`:
     missing genres 18 → 13, unusable ratings 93 → 27 (110 processed, 108 matched).
  6. Repaired a pre-existing indentation break in `Fast_Fetch/viewer.py` where the stats
     cache helper had been spliced into `do_GET`'s branch chain; helpers now sit at module
     scope.
- **Checks run and exact result:** requested backend command (database + vidout +
  admin_panel + download_endpoint) → 135 tests OK; with `test_backfill_tmdb` → 170 tests OK.
  Android `assembleDebug` → BUILD SUCCESSFUL; `testDebugUnitTest` → 371 tests / 45 suites /
  0 failures (includes `AdSlotPolicyTest` 7 and `BingePreloaderTest` 8).
- **Data change:** production catalog enriched in place; pre-run copy at
  `/home/ubuntu/radd-stream-data/fast_fetch.db.bak-prebackfill-20261027`.
- **Known limitations:** no device/emulator pass; no ad creative or VIP entitlement exists,
  so the sponsor overlay is a guarded seam rather than an active ad; 26 rows still have no
  rating because Cinemeta has no score for those (mostly 2025–26 titles).
- **GitHub branch/commit/push result:** not committed (no commit requested).
- **Oracle deployment result:** not deployed.
- **Next concrete action:** device pass on shimmer, badges, next-episode hand-off and the
  three-player timing invariant; run the backfill against staging DBs that carry an
  `imdb_rating` column; wire a real creative/entitlement before enabling breaks.

## 2026-10-28 — Overnight master run (app polish + new-site pipeline)

- **Master/orchestrator:** qoder2 on `/opt/radd-stream`; workers qoder1 (Android) and qoder3
  (backend discovery/importers). Live API frozen; staging DBs only; one crawler and one
  Gradle build at a time.
- **Android (verified by the master, pushed to master):** `824ebd2` media-controller manifest,
  `2966f4f` inline/empty failure states (Browse/Search/Detail), `fcdbb0e` honest player start
  state (`StartPhase`), `0141180` continue-watching resume position, `90ae074` home-rail
  failure state (includes 0141180). Gate for 90ae074: `/tmp/qbuild.sh :app:testDebugUnitTest
  --rerun` → `GRADLE_EXIT=0`, `OVERLAP=NO`, 63 suites / 516 tests / 0 failures, one fresh XML
  batch. qoder1's Hilt incremental cache poisoned once; a full `--no-build-cache` rerun after
  deleting `app/build/generated/hilt` restored a green build.
- **New-site discovery:** `/tmp/new_site_candidates_20261028.json` (126 domains checked,
  30 candidates). Independent master probe found the build list is mostly iframe-only:
  MoviesMela (pkembed/mxdrop), HindiDubbedPK (rpmplay), Moviehax (filemoon), TamilGun
  (YouTube), HindiAnimeZone (Turnstile), Bollyflix (CF-gated fastdl), Dotmovies (mobilejsr).
  The Android app has no WebView path (`PlaybackRecovery`/`LinkClassification`), so iframe
  rows are catalog-only and must be stored as `playback_type='iframe'`.
- **Two hosts are genuinely resolvable with stdlib** (verified by the master, Range
  `bytes=0-511`, no Referer, HTTP 206 `video/mp4`, `ftypisom`):
  - `mxdrop.to` — Dean-Edwards identity packer, `MDCore.wurl` signed MP4. 5/5 posts.
  - `pkembed.site` — Dean-Edwards base-36 packer, `<source src="https://stoplus.vkcdn5.com/…">`.
    6/6 posts. `e=43200` is a duration, `s` the start epoch (`expires_in=(s+e)-now`).
  Both are short-lived: the embed URL is the durable id, the MP4 must be unpacked JIT and
  never persisted; a site Referer returns 403. MoviesMela (819/820 mxdrop, 814/820 pkembed)
  therefore has two independent playable sources per title.
- **rpmplay lead:** its SPA bundle exposes `/api/v1/info`, `/api/v1/video`, `/api/v1/player`,
  `capacityToken`, and returns hex-encoded encrypted blobs (application/octet-stream) —
  still a bounded spike for qoder3; a NEEDS-JS verdict is an acceptable result.
- **Data:** `import_moviesmela.py` passes 153/153 offline tests (master-verified);
  `host_resolvers.py` + tests pass 66/66. Both still uncommitted by qoder3 at 05:20.
- **Staging inventory:** 25 per-site DBs carry sources; largest are 9xmovies (337,595),
  world4ufree (254,340), hdhub4u (250,925), 10xflix (228,397), katmoviehd (163,972),
  hindilinks4u (145,196), kisskh (140,746). Older importers did not store embeds, so the new
  resolvers do not retro-unlock those rows.
- **Next:** qoder3 → commit MoviesMela + host_resolvers, add `unwrap_pkembed`, then the
  rpmplay/filemoon verdicts; qoder1 → #12 feature flags, #13 audio-boost cap, #14 subtitle
  style persistence.
