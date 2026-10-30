# Spec App Screens

> Moved **verbatim** out of `App/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `App/AGENTS.md`
> carried at this sha. Law stayed in `App/AGENTS.md`; this is the reference prose it now links to.
### from `App/AGENTS.md` lines 159-204

See [`design/SCREENS.md`](../design/SCREENS.md) for full wireframes. Verified
against `App/app/src/main/kotlin/com/raddstream/app/ui/`:

**Implemented and navigable** (`NavGraph.kt:105-165`, four-tab bottom nav):

| Screen | Route | Key Components |
|---|---|---|
| Setup | `setup` | Server URL, `/api/v1/stats` connection check |
| Home | `home` | Type filter chips, catalog poster grid, refresh |
| Search | `search` | Debounced title search, type chips, poster grid |
| My List | `my_list` | Room-backed favorites |
| Settings | `settings` | Server config + live server diagnostics |
| Detail | `detail/{postId}` | `getPostDetail`, release/source lists, play action |
| Player | `player/{streamId}/{title}` | Media3 ExoPlayer, `resolveStream`. The argument is the **opaque handle**, never a URL |
| Provider page | `embed/{streamId}/{title}` | `EmbedWebViewScreen` — the provider's own page, visibly, for a link the server calls a page (`ProviderPageLinks`). Same handle-only rule; see §14 Session 25 and `docs/PARITY_BACKEND_BLOCKED.md` §4-G |

The §5 note above supersedes the "app calls only `/api/v1/stats` and
`/api/v1/posts`" statement, and the earlier Phase 1 task lists in §8 and the
Session 2/3 logs, which described a metadata-only MVP that no longer matches
`App/app/src`. Treat those as historical plan, not current state.

> ⚠️ ~~The "Anime" chip on Home and Search is known broken.~~ **Retired 2026-10-28:** the
> server answers `type=anime` and the live catalog returns 5,307 rows for it (§5). The client-side
> half that followed — decode `is_animated` onto `Post` so a tile is typed before its detail page
> opens — shipped in `69b3795`, and App Session 26 carried the same flag into `favorite_posts`, so
> the row on My List is typed from the wire too (`App/docs/PARITY_BACKEND_BLOCKED.md` §4-A closed).

> ✅ **~~`ReleaseDetail` does not match the backend release rows.~~ Retired by code, not by
> hope (re-read `Models.kt` 2026-10-28).** The old note claimed the model asked for
> `season_number`, `episode_number`, `episode_title`, `resolution` and `audio` — five keys the
> response never sends — so all five were permanently `null` and season/episode grouping
> "silently did nothing". That model is gone. `ReleaseDetail` now maps the columns the ledger
> actually writes (`Models.kt:236-253`: `release_title`, `season`, `episode`, `quality`, `codec`,
> `size`, `languages`, `sources[]`), and the four values the UI needs are **derivations** of them
> through one grammar: `seasonNumber`/`episodeNumber`/`resolution`/`sizeBytes` come from
> `printDescriptor` (`:264-286`, i.e. `ReleaseLabelParsing`, the port of
> `Fast_Fetch/release_descriptor.py`), `audio` is simply `languages`. `episode_title` has no
> server counterpart at all, so it does not exist here and `releaseTitle` is the honest label.
> Consequence in the screen: `SeasonChips` (`DetailScreen.kt:387,660`) paints
> `SeasonGroup.number`, which `ReleaseLayoutBuilder.kt:300-330` builds from those same derived
> season numbers — grouping is live, not dead. The provenance columns (`source_site`,
> `origin_url`, `intermediate_url`, `created_at`) are absent from the model on purpose.
> Likewise `StreamResponse.isTemporary` is `Boolean?` (`Models.kt:343-345`) decoded by
> `LenientBooleanAdapter`, which accepts the JSON boolean `/api/v1/stream` sends and the `0/1`
> number the same field arrives as elsewhere.

