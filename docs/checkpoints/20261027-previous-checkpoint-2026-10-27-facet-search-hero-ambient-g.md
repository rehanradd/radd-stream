# Previous checkpoint — 2026-10-27 (Facet search, hero ambient glow, broadcast update dialog)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

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

