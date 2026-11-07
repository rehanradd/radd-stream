# 2026-11-07 — Muse [MUSE-C-FILE-MERGES]: live-deploy prep, (c)-file merges

Branch `live-only-20261107` (from main `5a3788dd`). Step 3 of the D1.1 deploy order:
merge the 38 live-only-vs-main conflicts one file at a time, after the keepers
(`c97dbc9f`) and the Stage-2 port (`96207b4f`, Backend CI 42374683145 SUCCESS;
Android green after the guard-test drop, run 42375137577 on `bedd89ad`).

Method: live (c) files pulled read-only from `/opt/radd-stream` via tar-over-ssh
into `~/workspace/live-only-staging/c-files/` (37 files; `fast_fetch.py` excluded,
already ported). Each file resolved by diffing live vs branch (branch = main +
keepers + Stage-2). Nothing in `/opt/radd-stream` was edited.

## Edited (6 files)

1. `App/.../data/cache/OfflineCacheEngine.kt` — main's short RETENTION KDoc
   paragraph replaced with live's longer two-classes version (auto-preview ages
   out vs keep promoted to USER_KEEP, `ttlSeconds = null` convention).
   D1.1 resolution: take main's code; keep live's retention comment.
2. `App/.../repository/FavoritesRepository.kt` — live-only
   `recordStreamRefusal(postId)` ported verbatim, after `recordAnswer`.
   Symbols verified present in branch: `FavoritePost.is18Plus`,
   `UnavailableWorkEntity.REASON_STREAM`, `favoriteDao.findById`,
   `favoriteDao.recordAnswer`, `unavailableDao.record`.
3. `App/.../viewmodel/PlayerViewModel.kt` — live's probe logic ported: imports
   `FavoritesRepository` + `retrofit2.HttpException`, constructor param
   `private val favoritesRepository: FavoritesRepository`, `probeHandle()`,
   `prefetchNextEpisodeHead` body replaced (probe; on
   `AdultPolicy.ServerAnswer.GONE`: `recordStreamRefusal(postId)` + emit
   `PlayerEvent.Message(NEXT_UNAVAILABLE)`), top-level `HandleProbe` data class
   + `NEXT_UNAVAILABLE` const appended. Verified first: `AdultPolicy.serverAnswerFor`
   exists, `StreamResponse.streamId` computed val, `SyncScope.postId`,
   `currentSyncScope()`, `catalogRepository.resolveStream` returns
   `StreamResponse`, NO test constructs PlayerViewModel directly. NOT ported:
   `store.reportPlayhead` (main deliberately removed it — PlaybackService owns
   the playhead feed), `requestAdBreak` (superseded by AdCadenceGovernor).
   Main's `directPlaybackBundle` is the direct-URL path, not a duplicate.
4. `Fast_Fetch/viewer.py` — three ports: (a) `_public_base` honors
   `X-Forwarded-Proto`; (b) `download_filename(stream_id, mime_type,
   url_hint=None)` with deferred `from current_hosts import
   download_extension_for` fallback, and `download_descriptor` now passes
   `res.get("url")`; (c) DashboardHandler Stage-2 call sites: stream route
   `resolve_live_source(int(source_id), want="watch")`, download route
   `resolve_live_source(int(source_id), v2=True, want="download")`, each with
   live's Stage-2 comment. `python3 -c "import viewer"` OK. NOT ported: live's
   hardcoded stats fallbacks in `fetch_database_payload` (stale numbers, main
   counts real), live's `link["playable"] = kind in ("direct","resolve")`
   (main's audit-critical-10 version also excludes UNPLAYABLE ledger states —
   stricter, wins), live's old dashboard HTML/queries (main rewrote them).
   The 9 D1.1 overlap functions exist in BOTH; sampled bodies byte-identical.
5. `ORACLE_DEPLOYMENT.md` — added the row `| Primary Production Domain (HTTPS)
   | https://raddstream.duckdns.org/ (Let's Encrypt SSL) |` after the Oracle
   public IP row. Main's other content (askpass printf warning, /api/v1/art
   allow-list correction + nginx block) is newer and kept.
6. `App/.../player/UniversalSourceTest.kt` — ONE live-only case ported into
   main's rewritten suite: `"application/x-mpegURL "` (trailing space) added
   to the `hlsAliases` list, pinning the trim. Live's other 10
   `manifestMimeType` tests are fully subsumed by main's stricter suite
   (live's `contains("mpegurl")` rule would wrongly pass
   `"video/vnd.mpegurl"` and `"application/x-mpegurls"`; main's exact-set
   rule rejects them and its test pins that). No production change.

## Verified no change (take main's as-is)

- Backend: `redact.py`, `test_merge_catalogs.py`, `catalog_v2.py`.
  **`redact.py` security finding: live's `stream_secret()` still returns the
  constant fallback `"radd-stream-dev-secret-unconfigured"`; main's version
  FAILS CLOSED — audit critical 4 retired the constant, and main's
  `test_redact.py` asserts the constant appears nowhere. Main wins outright.**
  Live's `sources_by_state` is already in main; the other 17 live-only diff
  lines are position-shifted duplicates present in main.
  `test_merge_catalogs.py`: ZERO live-only lines; live's 4-line tweak is fully
  covered by main's +134-line MergeTimeAdultReconciliationTests.
  `catalog_v2.py`: the live-vs-branch diff is only 40 lines, ALL main's DASH
  fix (live folded `.mpd` into `_HLS_MARKERS` — the bug; main splits
  `_DASH_MARKERS`, adds `dash_manifest` kind + `"dash"` protocol +
  `_PROBE_PROTOCOL_WORDS` sniff override). The D1.1 "real conflict" does not
  exist in the live-vs-branch diff.
- App: `AppDatabase.kt` (live MIGRATION_6_7 DDL byte-identical to main
  MIGRATION_7_8; main's v8 numbering wins), `FavoritesSchemaGuardTest.kt`
  (main pins v8/7→8 + ladder-coverage test), `Brand.kt` + `PlayBundle.kt`
  (logic identical, comment prose only), `DatabaseModule.kt` (main adds
  AdCadenceDao provider + MIGRATION_2_3/7_8), `CacheRepository.kt` (main's
  keep/preview/mayEvictForAdmission strictly fuller), `CatalogRepository.kt`
  (`probePost` byte-identical; main adds playV2/submitContact/suggest/
  V2PlayResult), `PlaybackMediaItemFactory.kt` (main's alias-set matching with
  `substringBefore(';')` normalization is newer/better than live's
  `contains("mpegurl")`), `PlaybackService.kt` (live's `instantStartLoadControl`
  duplicates main's `loadControl()`; the 500 ms value survives as
  `PlayerBuffering.BUFFER_FOR_PLAYBACK_MS`), `HomeViewModel.kt` (all counts
  present; live-only lines are older wording), `MyListViewModel.kt` (main's
  one-tap remove + Undo supersedes live's `armedRemoval` confirm),
  `MyListScreen.kt` (live's armed-removal AlertDialog superseded by Session 65
  UX), `FavoritePost.kt` (live's `fromPost`/`fromPostDetail` mapping lines copy
  `post.is18Plus`/`detail.is18Plus` which main's models deliberately lack).
- **Models.kt policy fork — DECIDED for main:** live MODELS the wire flag
  (`is18Plus` on Post and PostDetail) and builds on it (V1CatalogMapper
  `browseItems` filter `it.is18Plus != true`, DetailViewModel
  `recordAnswer(postId, detail.is18Plus, LISTED)` + hide). Main DELIBERATELY
  does NOT model `is_18_plus` anywhere (Models.kt KDoc point 4, App/AGENTS.md,
  API_V2.md §13): the server never sends the flag on public routes, and the
  real protection is server 404 + `AdultPolicy` + `UnavailableWork` ledger.
  Consequently NO CHANGE to `Models.kt`, `V1CatalogMapper.kt`,
  `DetailViewModel.kt` (main records LISTED with `flag = null` in
  FavoritesRepository — the repository layer, not the ViewModel).
  `AdultListingGuardTest.kt`: take main's (224 lines); live's two unique tests
  assert the fork (mapper filter, `TITLE_NOT_AVAILABLE`) and must NOT be
  ported. `UniversalSourceTest.kt`: see edit 6 above.
- Docs: `Fast_Fetch/SITES.md` (diff is all main additions), `ANTIGRAVITY_HANDOFF.md`
  (main's qoder4-corrected numbers supersede live's stale ones),
  `docs/PROJECT_MAP.md` (main newer/corrected throughout),
  `Fast_Fetch/AGENTS.md` (live's inline architecture tree + §3 reference were
  rotated by main into `docs/SPEC_FAST_FETCH_ARCHITECTURE.md` /
  `docs/SPEC_FAST_FETCH_SITES.md`), `Fast_Fetch/CONTINUITY.md` (see note
  below), `docs/SESSION_CHECKPOINT.md` (live's entries rotated into
  `docs/checkpoints/`), root `AGENTS.md` (live-only lines are the old repo-map
  tree, moved to `docs/SPEC_REPO_MAP.md`; take main's structure),
  `App/AGENTS.md` (live's §12 pointer + §14 index survive verbatim at the head
  of `App/docs/SESSION_HISTORY.md`, moved by the 2026-10-30 documentation
  diet; take main's), `App/docs/PLAYER_AND_CACHE_DIRECTIVE.md` (main adds the
  5-line streak note; live adds nothing), `docs/MONETIZATION_AND_FLEET_PLAN.md`
  (main adds the 2026-10-29 Play Billing/Wise/Raast + shortener-flag
  corrections; live adds nothing).
- `Fast_Fetch/importers/import_themoviebox.py`: take main's 2,446-line rewrite.
  Main has NO `_looks_like_sitemap`/`_sitemap_entries` because `/sitemap.xml`
  is a hard 404 on the site (documented in main's module docstring) — live's
  helpers parse sitemap XML that never arrives. Dead code; NOT ported.

## Two findings recorded here, not fixed in this commit

1. **Live CONTINUITY entry with no main checkpoint.** Live's 2026-11-02 entry
   "Production Reality Audit, HTTPS Domain (raddstream.duckdns.org), and
   Release Status Reconciliation" has no matching checkpoint file in main and
   no occurrence of "Production Reality Audit" anywhere in the branch. Its
   substance is already recorded in main: the domain + SSL live
   (ORACLE_DEPLOYMENT.md, this commit's row), v1.0.4 signed + published
   (root AGENTS.md, run 41323174024), the docs truth pass (main's docs).
   NOT re-added to `Fast_Fetch/CONTINUITY.md`: the file is at 98 lines /
   11,998 bytes against the ≤120 lines / ≤12 KB guard — the 15-line entry
   would breach the byte ceiling. The full entry text survives in the live
   tree's CONTINUITY.md (backed up before any deploy overwrites it).
2. **Main's `App/docs/SESSION_HISTORY.md` lost Sessions 78–93 in the Option C
   merge.** Main `5a3788dd` carries only the four `## Session` headers 74–77;
   the panel branch `28741d9d` carries 14 (through Session 93). The merge took
   main's side of the file. The panel branch still has them; the fix belongs
   on main, not on this branch. This commit's App log entry is numbered
   Session 94, continuing the project's session count.

## Checks

- Full backend gate (`run-backend-gate.py`, working tree incl. the viewer.py
  edits), 2026-11-07 ~18:16 PKT: **49/49 modules PASS, 0 failed** (incl.
  test_database 138, test_redact 76, test_api_v2 46, test_docs_invariants 22).
  The gate does not judge the Kotlin edits — Android CI does.
- Pre-push Kotlin checks on the 4 edited Kotlin files vs `bedd89ad`: import
  diff = ONLY `+FavoritesRepository` + `+retrofit2.HttpException` in
  PlayerViewModel, zero dropped; @Composable counts unchanged (0/0);
  `/*` vs `*/` balanced in all four (7/7, 7/7, 93/93, 4/4); no `\"` escape
  artifacts (the one hit is pre-existing in the application-scan test's
  string literal); both new imports used.
- `python3 -c "import viewer"` OK from `Fast_Fetch/` after the edits.
- `test_docs_invariants.py` 22 OK locally after the CONTINUITY count bump
  95 → 96 (this file is the 96th).
