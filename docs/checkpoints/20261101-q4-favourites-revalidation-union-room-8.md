# 2026-11-01 — q4 App lane: the favourites re-validation union, landed as Room version 8

**Lane:** qoder4 (account4), App. **Branch:** `q4-fav-revalidation-v8-c2528e1`, one commit off trunk
`c2528e1`. **No Gradle ran on this box** — it cannot (no SDK `platforms/`, no `licenses/`), and the
supervisor ordered hosted-CI-only regardless. **No trunk write, no tag, no service action, no
production DB read or write, no credential touched.**

## What this union is

Two preserved halves existed on this repo and neither compiled alone:

| Piece | Where it lived | State |
|---|---|---|
| `AdultPolicy` + `UnavailableWork` + `AdultPolicyTest` + `AdultListingGuardTest` | `q1-rescue-untracked` @ `1c83e1c` (q1's copy of work that was uncommitted in `/opt/radd-stream`) | never built |
| the favourites re-validation itself (DAO, entity fields, repository, My List, schema guard) | `q4-fav-recheck-rescue` @ `583fd54` | **hosted CI `failure`, 35 errors** in `FavoritePost`, `FavoritesRepository`, `MyListScreen` (run `41157938495`) — it references `Post.is18Plus`, `AdultPolicy`, `UnavailableWorkDao`, `MyListUiState.hiddenCount`, none of which were on its parent |

This branch is the union: the two preserved halves, renumbered onto trunk's schema, plus the
callers that make them run. The `583fd54` diff applied to `c2528e1` without a single conflict; every
change below is what the compiler and the schema required on top of it.

## The Room version collision, and why 8 is not cosmetic

Trunk owns **`version = 7`** for `ad_cadence` (`MIGRATION_6_7`). The rescue's `MIGRATION_6_7` was a
*different* 6→7 step — `is18Plus`, `checkedAt`, `unavailable_works`. Landing that as written means a
device already on 7 never re-runs the step, `favorite_posts` keeps missing its two columns, Room's
runtime schema check fails on open, and `DatabaseModule.kt:43` registers
`fallbackToDestructiveMigration()` — so the failure is not a crash, it is **the viewer's saved list
deleted**, which is the exact second bug this feature exists to prevent.

Landing shape, as recorded in the 2026-10-31 entry: `MIGRATION_6_7` (ad_cadence) untouched, new
`MIGRATION_7_8` with the three statements, `version = 8`, registered on the builder. All four are
pinned by `FavoritesSchemaGuardTest`, whose newest-step test was renumbered from 6→7 to 7→8 — the
refusals (`DROP TABLE` / `DELETE FROM` / `RENAME TO` may not appear in that step) came along
unchanged, and the bound stays self-tightening: a future 8→9 becomes the new end of the scan.

## Measured first, and it changed the design: the flag is not a wire field

`GET http://92.4.95.252/api/v1/posts?limit=1` and `GET /api/v1/posts/158`, read 2026-11-01:

```
post_brief keys  : … is_animated … work_ref …            is_18_plus ABSENT
post_detail keys : … is_animated … option_groups …       is_18_plus ABSENT
```

That is not a projection gap, it is the design: the public route answers 404 for a flagged id, so a
row that arrives at all arrived unflagged. Consequences, all of them departures from the rescue:

- **`Post.is18Plus` / `PostDetail.is18Plus` were NOT added.** A field mapped from a key the API
  never returns is permanently null and is exactly the class of phantom `App/AGENTS.md` §6 already
  retired once. `FavoritePost.is18Plus` stays as a *local* column, written only by
  `FavoriteDao.recordAnswer` when a payload genuinely carries a flag, and `toPost()` / `fromPost()`
  do not map it (the three mapping lines in the rescue were dropped). `AdultListingGuardTest` now
  refuses a phantom field instead of requiring one, and its KDoc says what to do if a projection
  ever publishes the key.
- Therefore **`FavoritesRepository.addFavorite` records `flag = null`**, and the half of the rule
  that fires against this server is the **refusal ledger**: an id the public route 404s is hidden by
  `unavailable_works`, not by a flag. `AdultPolicy`'s own KDoc already said this; the union makes
  the code match it instead of leaving a `Post.is18Plus` that could never be true.

## What fires on this branch

- `CatalogRepository.probePost` reports **primitives** (`httpStatus`, `bodyClaimsSuccess`,
  `noAnswer`) and never a verdict, so "refused", "served" and "could not ask" stay distinguishable —
  `getPostDetail` collapses a 404 and a dead socket into one `null`, which is right for a screen and
  fatal for a compliance ledger.
- `FavoritesRepository.recordAnswer` — `LISTED` clears the refusal *and* stamps; `GONE` stamps then
  records; `UNANSWERED` writes nothing, not even the stamp, so an outage leaves the row due instead
  of quiet for a TTL.
- `revalidateSavedRows()` — at most 12 rows per pass, only rows whose answer is ≥ 24 h old or
  missing, never-checked first. Called from `MyListViewModel.init` without awaiting it, so opening
  My List a second time the same day asks nothing and a failed pass costs the viewer nothing they can
  see.
- **Both cached surfaces filter at render**, the one place a `WHERE` clause on the server cannot
  reach: My List (`MyListViewModel`, over the stored rows before any sort or map, with
  `hiddenCount`/`hiddenNotice` — a count, never a title) and Continue watching (`HomeViewModel`,
  keyed on the resume row's own `postId`, `flagOf` a constant null because `watch_history` models no
  flag).
- `Brand.adultFilterEnforced` is **computed**, not returned: `= AdultPolicy.enforcesAdultListing`.
  Nothing in the app read the old literal, so this costs no behaviour and retires a name that reads
  as evidence without being any.

## Two doors this slice deliberately does not open

Recorded here because `AdultListingGuardTest` does not pin them, and an unpinned gap is how
`adultFilterEnforced` stayed a `true` for months:

1. **The detail screen's 404 arm still calls a refusal a connection error.**
   `DetailViewModel`'s `catch (HttpException)` needs `AdultPolicy.serverAnswerFor(...)` →
   `recordAnswer(..., GONE)` in the refused arm only, with the other arm keeping
   `friendlyNetworkError`. Not in this slice: `DetailViewModel` is a mixed live-tree file (another
   lane's deletions ride in it), and the rescue commit says so. Its snapshot is in
   `/tmp/q1_rescue_app_20261031/` for that owner.
2. **The stream door.** `UnavailableWorkEntity.REASON_STREAM` is declared and nothing writes it:
   `recordStreamRefusal` was dropped from `FavoritesRepository` rather than landed uncalled. A
   `/api/v1/stream` refusal about a saved handle belongs in the player/Detail wiring, with the same
   one ledger.

## Verification

Hosted `🔨 CI — Android Build & Test` is the only judge available and the only one used; the verdict
is appended to this entry once read. Local `testDebugUnitTest` is impossible on this host, and the
two Robolectric suites remain excluded on aarch64 (robolectric/robolectric#9166), which is why the
surfaces are guarded as text.
