# Previous checkpoint — 2026-10-26 (Android hero, ghost mode, fallback art, stubs gone)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

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

