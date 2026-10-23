# HANDOFF — App UI agent → owners of other files

I built the app's browsing/discovery surface: Home rails, rich Search, the honest
Detail screen, Downloads/keep list, Settings, My List, plus shared components, ViewModels,
navigation, and JVM tests. I only touched files I own:
`ui/screens/**` (except PlayerScreen), `ui/components/**`, `ui/navigation/**`,
`viewmodel/**` (except PlayerViewModel), and `src/test/.../ui|viewmodel/**`.

Everything below is a **request to a file I am not allowed to edit**. Do not assume I
worked around it silently — where a dependency was missing I either hid the feature
(never faked it) or left a loud `// HANDOFF #N` note in code.

Backend ground truth I designed against: `Fast_Fetch/API_V2.md` + `Fast_Fetch/catalog_v2.py`
(the real projection) and `App/AGENTS.md §5/§6` (what v1 actually returns today).

---

## #1 — network/models/Models.kt (network agent) — RELEASE ROW MAPPING IS WRONG
`ReleaseDetail` maps `season_number`, `episode_number`, `episode_title`, `resolution`,
`audio`. None of those keys exist in the v1 `/api/v1/posts/{id}` response (verified
AGENTS.md §6), so all are `null`. My `ReleaseParser` (viewmodel/ReleaseParser.kt) parses
the descriptive text fields that *do* arrive (`quality`, `codec`, `size`, the free-text
columns) as a stopgap so the Detail UI is honest today. To make it precise, map the real
`releases` columns instead:

```kotlin
data class ReleaseDetail(
    val id: Int,
    @SerializedName("post_id") val postId: Int = 0,
    @SerializedName("release_title") val releaseTitle: String? = null, // S07 / "Complete" / batch text
    val season: String? = null,     // free text "S07"/"7"
    val episode: String? = null,    // free text "E03"/"3"/"Batch"
    val quality: String? = null,
    val codec: String? = null,
    val size: String? = null,
    val languages: String? = null,  // e.g. "Hindi|English|Tamil"
    @SerializedName("source_site") val sourceSite: String? = null,
    val sources: List<SourceDetail> = emptyList(),
)
```
If you add `releaseTitle`/`season`/`episode`/`languages`, tell me and I will switch
`ReleaseParser.toPrint()` from text-sniffing to those fields (keeps behavior, adds precision).
I kept the old field names referenced so the current build still compiles.

Also: `StreamResponse.isTemporary: Int?` is declared but `resolve_live_source()` returns a
JSON **boolean** → Gson will fail that field. AGENTS.md §6 item (3) confirms. It needs
`Boolean?`. `SourceDetail.isTemporary`/`isResumable` are likewise int-vs-bool ambiguous;
my `Print` treats `== 1` as true and null as false — fine if they stay `Int?`, wrong if you
switch to `Boolean?`. **Ping me if you change their type** (I parse them in ReleaseParser
and DetailViewModel).

## #2 — repository + network: Home rails that have NO data source today (I hid them)
The owner brief wants continue-watching, trending, "because you watched", and a
genre/language jump-off. The v1 API supports **only** `q`, `type`, `page`, `limit`. So
`HomeViewModel` currently renders only: Recently added (default `id DESC`), Movies, Series,
Seasons. The reserved rails are documented in the `RESERVE_NOTE` const in
`viewmodel/HomeViewModel.kt` and are NOT shown with fake data. I need endpoints (v2 or v1):

- `GET /api/v1/trending?type=&limit=` (or a `play_count`/`popularity` field on posts) → trending rail.
- `GET /api/v1/related?work_id=&limit=` → "because you watched" (API_V2.md §8 `collections/{id}`).
- `GET /api/v1/facets?type|genre|language|year|source_site` → drives the genre/language
  jump-off AND the real Search facet sheet (API_V2.md §8 `browse`).
- (list payload) `Post` needs `genres`, `language`, `quality_max`, `available{stream,download}`
  so Search can filter server-side instead of client-side on one page.

Until those exist, Search's sheet only exposes facets the current payload supports
(type, sort-within-results, year range, source site) — see request #3.

## #3 — Search: server-side sort + facets
`viewmodel/SearchViewModel.kt` sorts year/rating/title **client-side over the accumulated
pages** (first page = `limit 100`, the v1 max). I labelled it "within loaded results" and put
"Sorting applies to the loaded results" in the filter sheet. For a true global sort add
`sort=relevance|newest|title|rating|quality|updated` and facet params to `/api/v1/posts`
(API_V2.md `browse` already specifies these). Then I can drop the client sort and remove the
caveat text. Also want a suggest endpoint (`GET /api/v1/suggest`) for type-ahead + a trending
queries source; I show recent queries but hid trending (`trendingHidden=true`) — no fake list.

## #4 — link health is scrape-time only; do not claim speed
`SourceDetail.status` is written `active` at scrape time and never re-measured (API_V2.md §0.5).
My `LinkHealthChip` intentionally shows only "Working / Dead / Unverified" + ephemeral/resumable
and I removed the old `⚡ Fast Direct` claim. Wire real measured health (v2 `cat_link_evidence`
→ `speed_mbps`, `latency_ms`, `http_status`, `ok`, `state`) onto `SourceDetail` and I will surface
a graded chip (Great/OK/Degraded) — the component is ready for it.

## #5 — data/**: persistence store for Settings (I cannot edit data/)
`viewmodel/SettingsViewModel.kt` now holds real preferences (image quality, mobile-data policy,
keep TTL 3h/6h, default subtitle language, dynamic-color) but only **in-memory for the session**,
because the only DataStore is `ServerSettingsRepository` (server URL). Please add
`data/UserPreferencesRepository.kt` (DataStore Preferences) and I will wire it in:

```kotlin
@Singleton
class UserPreferencesRepository @Inject constructor(@ApplicationContext c: Context) {
    val prefs: Flow<UserPreferences>            // imageQuality, downloadOnMobileData,
                                                 // keepTtl, subtitleLang, dynamicColor
    suspend fun setImageQuality(v: ImageQuality); suspend fun setDownloadOnMobileData(b: Boolean)
    suspend fun setKeepTtl(v: KeepTtl); suspend fun setSubtitleLang(s: String); suspend fun setDynamicColor(b: Boolean)
}
// The enum types live in viewmodel/SettingsViewModel.kt (ImageQuality / KeepTtl / UserPreferences).
```
Also add resume state (for continue-watching, request #2) as a Room entity/DAO next to
`FavoriteDao` (`postId`, `season`, `episode`, `positionMs`, `durationMs`, `updatedAt`), and I will
render the Continue-watching rail. Note favorites persistence already works via
`FavoritesRepository`.

## #6 — player + cache agent contracts (I referenced, did not invent)
- **Player handoff (unchanged, safe):** Detail hands playback to PlayerScreen via the existing
  route `player/{url}/{title}` and `DetailNavigationEvent.PlayStream/OpenExternal`. PlayerScreen's
  signature `PlayerScreen(streamUrl, title, onBackClick)` still holds; I kept NavGraph compatible.
  The richer PlayBundle contract (API_V2.md §5) — rank failover, `expires_at` refresh, `seekable`
  toggling, `pack_warning` + `offset_seconds` for season packs — needs a `PlayerViewModel` I do not
  own. My Detail already parses coverage/packed-season and emits `KeepPrint`; align the Play event
  to carry `releaseId`/`episodeId` when you build `POST /api/v2/play` so I can pass a target instead
  of a raw URL. Right now I resolve a single source URL and hand it over — correct but single-shot.
- **Cache/offline engine:** the Downloads **screen** is mine; the queue **engine** is not.
  `viewmodel/DownloadsViewModel.kt` reads real device storage (StatFs) and shows the honest
  "playable only in this app" + expiry explanation, but the item queue is empty because there is
  no engine yet. Define the interface in `docs/CACHE_SPEC.md` / `HANDOFF_appcache.md` and I will
  bind it. The shape I coded against (`KeptItem`, `KeepState`) is:
  `id, title, printLabel, bytesDownloaded, bytesTotal, state(QUEUED|DOWNLOADING|PAUSED|READY|EXPIRING|FAILED), expiresAtMillis`.
  I need: `Flow<List<KeptItem>> queue()`, `suspend fun keep(url, size, ttlMs)`, `cancel(id)`,
  `retry(id)`, and a `clearAll()` for Settings. Until then Download keeps are shown as a clear
  "not yet wired" state, never fabricated.

## #7 — ui/theme agent: semantic tokens I want (I used colorScheme until they exist)
I referenced ONLY `MaterialTheme.colorScheme.*` (no raw hex) per my constraints. I would like these
as first-class tokens; meanwhile each maps to the nearest M3 role:
- `cam` / `camOn` (currently `errorContainer`/`onErrorContainer`) — bootleg discouragement.
- `hdrAccent` (currently `primaryContainer`) — 4K/HDR print highlight.
- `healthGood`/`healthBad`/`healthUnknown` (currently `primary`/`error`/`outline`).
- `posterScrim` (currently `scrim.copy(alpha)`) — the poster bottom gradient overlay.
- dynamic color: Settings has a `dynamicColor` toggle but `Theme.kt` ignores it. Please honor
  `dynamicColor` (MaterialYou on S12+) reading from the prefs repo (#5); until then the toggle
  is shown but inert (labelled in UI).

## #8 — DI / manifest (di/**, AndroidManifest) — nothing required to compile, FYI only
- Hilt: I inject `DownloadsViewModel(@ApplicationContext Context)` for StatFs — standard, no new
  module needed. No new bindings were required by any of my files.
- Deep links: I added `navDeepLink` patterns `radd://detail/{postId}` and `radd://browse/{type}`
  in NavGraph (AGENTS.md §6 item 4 said the manifest registers `radd://` but NavGraph had none).
  **Please confirm the manifest `data` element scheme/host** so `uriPattern` matches; if the host
  differs from the bare `radd://` I used, tell me and I will adjust the pattern.

## #9 — 18+ policy compliance (for reviewers)
No surface I built renders `is_18_plus` or attempts to bypass the backend filter. Adult rows are
already excluded by `/api/v1/posts` (viewer.py:1891) and `works/{id}` returns 404 for them
(API_V2.md §11), so they simply never reach my ViewModels. About text and empty states describe the
app accurately ("metadata catalog browser and source-link resolver… not a hosting service… does not
display 18+ content") — no misleading claims.

---
### Quick reference: what I created
- `viewmodel/ReleaseParser.kt` (domain + parser, pure)
- `viewmodel/HomeViewModel.kt`, `SearchViewModel.kt`, `DetailViewModel.kt`, `SettingsViewModel.kt`,
  `MyListViewModel.kt`, `BrowseViewModel.kt`, `DownloadsViewModel.kt` (all rewritten/expanded)
- `ui/components/MediaBadges.kt`, `CommonUi.kt`, `PosterCard.kt` (rewritten, backward-compatible API)
- `ui/screens/HomeScreen.kt`, `SearchScreen.kt`, `DetailScreen.kt`, `BrowseScreen.kt`,
  `DownloadsScreen.kt`, `MyListScreen.kt`, `SettingsScreen.kt` (PlayerScreen untouched)
- `ui/navigation/Screen.kt`, `NavGraph.kt` (added Browse + Downloads + deep links)
- tests: `ReleaseParserTest.kt`, `CatalogHelpersTest.kt`
- Did NOT touch SetupScreen/SetupViewModel (already correct) or PlayerScreen/PlayerViewModel.
