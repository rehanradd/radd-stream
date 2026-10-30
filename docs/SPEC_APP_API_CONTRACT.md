# moved verbatim out of `App/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

## 5. REST API Contract (Verified Against viewer.py)

⚠️ **Reality (verified against viewer.py 2026-10-22, re-measured against the live server
2026-10-28):** this section previously described a metadata-only MVP that called two endpoints,
and it listed `anime` as a valid `type` value. Both were wrong **then**; the `anime` half has
since been fixed server-side and §5 now says so. The app in `App/app/src` today calls
**four** endpoints. `App/docs/PARITY_BACKEND_BLOCKED.md` §1 is the measured list of everything
the deployed host will actually answer, and its §5 is the table of claims in this file that a
later measurement retired — read that file before trusting any line number here.

The backend is `Fast_Fetch/viewer.py`. The app currently consumes:

| Call site | Endpoint |
|---|---|
| `SetupViewModel` / `SettingsViewModel` → `CatalogRepository.testConnection()` / `getStats()` | `GET /api/v1/stats` |
| `HomeViewModel` / `SearchViewModel` → `CatalogRepository.getPosts()` | `GET /api/v1/posts` |
| `DetailViewModel.kt:69` → `CatalogRepository.getPostDetail()` | `GET /api/v1/posts/{id}` |
| `DetailViewModel.kt:130` → `CatalogRepository.resolveStream()` | `GET /api/v1/stream?id=…&redirect=0` |

`GET /api/v1/rules` is **not** called by the app. `App/.github/workflows/` and
the deferred roadmap items are separate concerns; see §6 and §8.

> ⚠️ **The four claims this paragraph used to make are now false on the current code —
> re-measured 2026-10-28.** It used to say there is **no authentication, no API key, no bearer
> token, and no rate limiting** anywhere in `viewer.py`, that `send_json()` answers every
> request with `Access-Control-Allow-Origin: *`, and that the server defaults to binding
> `0.0.0.0`. All three have since changed, so the paragraph is replaced by what the file
> actually does:
>
> - **The four catalog reads stay open, and the account surface does not.** `viewer.py:381
>   _bearer_token()` / `:389 request_is_vip()` read `Authorization: Bearer …`, and every
>   `api/v2/account*` route requires the sync key (that is why Session 13's payment call had
>   to be signed in). A plain `vip=1` is never honoured — only a server-minted pass.
> - **There is a limiter.** `viewer.py:2957 _bucket_for()` assigns each request a token bucket
>   (`account`, the `api_v2.ROUTE_BUCKETS` map, `play` for `/api/v1/stream|download|art` and
>   `/api/m3u`, `reports` for `/api/v1/stats`, `browse` otherwise), and `redact.py:1163` puts
>   the IETF `RateLimit-Limit/Remaining/Reset` triple on the answer. A phone that polls too
>   hard gets throttled, so "retry forever" is not a free strategy.
> - **CORS is an allow-list that is currently empty.** `send_json()` (`viewer.py:2939`) calls
>   `redact.cors_headers_for(origin)`, which returns the two headers only for an origin in
>   `redact.CORS_ALLOW_ORIGINS` — a `frozenset()` today (`redact.py:1278`), so no browser
>   origin is granted and a refused one gets **no header at all**. Nothing sends `*` any more.
>   This costs the Android client nothing (OkHttp is not a browser and ignores CORS), but it
>   means a web dashboard cannot read this API until an operator adds its origin.
> - **The default bind is loopback.** `start_server()` is `host="127.0.0.1"`
>   (`viewer.py:3491`) and `fast_fetch.py:5857` defaults `--host` to `127.0.0.1` with the help
>   text "nginx is the public gate". The old `0.0.0.0` default is gone.
>
> What did **not** change: the deployed host is plain HTTP with no TLS, the four catalog reads
> answer anyone who can reach nginx, and nothing behind them is private — a sync key protects a
> viewer's own bookmarks and resume rows, not the catalog. Never treat the catalog as a private
> surface, and never treat the account routes as unauthenticated.

### `GET /api/v1/posts`
**Query params** (route dispatch viewer.py:3159-3191 → `api_v1_get_posts()` viewer.py:2507):

| Name | Behaviour |
|---|---|
| `q` | `LIKE '%q%'` against `clean_title`, `title`, or `slug`. Omit for no search. |
| `type` | Exact-equality match on `posts.content_type` — **plus one special case**: `type=anime` is answered from the flag the data actually carries, `(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')` (viewer.py:2530). The plain values are only `movie`, `series`, `complete_season`, `ongoing_season` — the four `classify_media()` ever writes. |
| `industry` / `genre` / `quality` / `sort` | Facet filters added 2026-10-27 (App Session 12's multi-filter pass): fixed SQL clauses per known value, `quality` as an `EXISTS` over the prints, `sort=trending` as `release_count + source_count`. An unknown value is ignored, not guessed at. |
| `page` | 1-based, default `1`. |
| `limit` | Default `20`, clamped to `1..100`. |

> ✅ **`?type=anime` works on the deployed server (measured 2026-10-28):**
> `GET http://92.4.95.252/api/v1/posts?type=anime&limit=1` returns `total: 5307`, and the row
> carries `is_animated: 1`. **The client now reads that flag** (`Post.isAnimated`,
> `Models.kt:77`, decoded by `LenientBooleanAdapter` because the column is INTEGER 0/1), so a
> tile inside an anime-filtered list is typed ANIME from the wire the moment it decodes:
> `V1CatalogMapper.animatedFromList` returns the field instead of `null`, and the one label
> owner `WorkTypeLabel.of(contentType, isAnimated)` paints "Anime" on the tile, the hero badge
> and the detail header. Search's own rail and chips gained the same entry
> (`typeChips` = All/Movies/Series/**Anime**/Seasons), and a flagged series now groups into its
> own "Anime" rail instead of the Series one (`typeGroupKey`).
> `App/docs/PARITY_BACKEND_BLOCKED.md` §4-A is closed by `69b3795`.
>
> (The old 🚨 note here — "there is no `?type=anime`", "`HomeScreen.kt:48` / `SearchScreen.kt:49`
> map the chip to an empty grid" — described the 2026-10-22 server and is retired. `HomeScreen`
> offers the Anime entry at `HomeScreen.kt:237`; the `industry` facet is the second door to the
> same predicate, which `viewer.py:2555` also answers. The last open piece was the Room
> consequence — `FavoritePost` stored no `is_animated` column, so a favourite saved from the grid
> came back labelled "Series" — and **App Session 26 closed it**: database version 6 adds nullable
> `isAnimated` and `subtitled` to `favorite_posts` with real `MIGRATION_5_6` DDL, and
> `FavoritePost.toPost()` hands both back to the tile, so My List paints the same words the grid
> painted. A row saved by an older build gets NULL, which means "this build never asked", not
> "not animated".)

**Response** — `api_v1_get_posts()` selects these columns per result
(viewer.py:2612-2617: `id, clean_title, title, year, content_type, seasons, poster_url,
backdrop_urls, imdb_rating, imdb_id, tmdb_id, genres, is_animated, industry, country,
language, release_count, source_count`), then `redact.project(row, "post_brief")` trims it,
`_art_pair()` (viewer.py:415) rewrites the two art fields through the redirector, and the loop
appends `work_ref` (viewer.py:2635) and `subtitled` (viewer.py:2636). The example below is a
real row sampled from
`Fast_Fetch/multimovies.db` on 2026-10-22 (poster URL elided); the totals are that
staging database's counts, **not** the unified catalog's:

```json
{
  "page": 1,
  "limit": 20,
  "total": 10512,
  "total_pages": 526,
  "results": [
    {
      "id": 10512,
      "clean_title": "Sorcerer Heavenly Master · Dark Hades",
      "title": "Sorcerer Heavenly Master · Dark Hades",
      "year": null,
      "content_type": "movie",
      "seasons": null,
      "poster_url": "https://...",
      "imdb_rating": null,
      "imdb_id": "tt35786199",
      "tmdb_id": 1673401,
      "genres": "Action, Adventure, Drama, Fantasy",
      "source_site": "multimovies",
      "industry": "Hollywood",
      "country": "USA",
      "language": "English",
      "release_count": 8,
      "source_count": 8
    }
  ]
}
```

`slug` is **not** in the list payload — it is only on the detail response, and only when the
caller asked for the un-redacted `full` view (viewer.py:2610 adds `source_site, url, slug` for
that path and nothing else). `year`,
`imdb_rating`, and `seasons` are nullable; `year` and `tmdb_id` arrive as JSON
**numbers** when present. Results are ordered `p.id DESC` (newest first), and rows
with `is_18_plus = 1` are excluded by the SQL `WHERE` (viewer.py:2515, one
`redact.adult_clause("p")` that every branch of the route inherits).

> **Added 2026-10-28 (Session 19):** the list payload now carries one more key,
> `subtitled` — a JSON **boolean** the server computes per work by
> `viewer._subtitled_posts()` (viewer.py:2466, applied at :2628/:2636). It answers
> "does at least one print of this work claim subtitles", using the same
> `release_descriptor` grammar the detail screen uses, so it is an existence test over
> the ledger's own labels and never a per-release promise. The sampled row above
> predates the key. `Post.subtitled` is `Boolean?`: a server that has not been
> restarted sends nothing, and the app renders no badge rather than an assumed one.

### `GET /api/v1/posts/{id}`
Returns `{"success": true, "data": {...}}`, where `data` is the raw `posts` row
plus `source_pages[]` and `releases[]`, each release carrying `sources[]`.
Releases are ordered **`id ASC`** only (viewer.py:2696) — no quality sorting and no
season/episode grouping; group them client-side. The tier ordering applies only
to `sources` inside a release (viewer.py:2702-2712: `status = 'active' DESC`, then
`is_temporary ASC`, then a fixed `CASE service` preference — a query, never a field on the
wire). An unknown id or an
adult-flagged post returns `404 {"success": false, "error": "Post not found"}`.

### `GET /api/v1/stream`
`redirect=1` (default) → bare `302` with `Location`. `redirect=0` → JSON with
`success`, `id`, `url`, `cached`, `refreshed`, `service`, `is_temporary`,
`is_resumable`, `source_name`, `mime_type` — `is_temporary` and `is_resumable` are
JSON **booleans**, which `StreamResponse` must not model as integers. Failure →
`404 {"success": false, "error": ...}`.

### `GET /api/v1/stats`
Field names are snake_case exactly as below — the answer is built at viewer.py:2902-2909 and
cached for 120 s (`_STATS_CACHE`, viewer.py:2831; the 120 s check at :2851), so a figure a phone sees can lag the
ledger by two minutes by design. **The values
are illustrative only** — they were read live from the `multimovies.db` staging
catalog on 2026-10-22, the old `131 / 1031 / 2017` figures were a 2026-10-13
milestone snapshot, and the unified catalog grows with every scraper run. Call the
endpoint on the server you are pointed at to get real numbers.

```json
{
  "posts": 10512,
  "releases": 612180,
  "sources": 675000,
  "active_sources": 675000,
  "resumable_sources": 0,
  "temporary_sources": 0
}
```

> ⚠️ **`/api/v1/stats` answers a different population than `/api/v1/posts` — re-measured
> 2026-10-29, and the direction flipped.** The route prefers the Layer-1 projection's own stamped
> tally (`viewer.py:2854-2869` reads `cat_projection_meta`, keys `works_safe / releases_safe /
> links_safe / …`, all-or-nothing) and otherwise counts `cat_works`/`posts` with
> `redact.adult_clause` (`:2877-2897`). The list route counts the live `posts` table
> (`viewer.py:2605`, adult-scoped). Those are two snapshots of two tables, and after the owner's
> 2026-10-28/29 merges they no longer agree in either direction: measured today `stats.posts` is
> `116922` while `/api/v1/posts?limit=1` answers `total: 131559` — the browsable catalog is now the
> **larger** number, where on 2026-10-28 the adult-flagged projection made it the smaller one.
> `sources` and `active_sources` both answered `3783959` with `resumable_sources: 0`, which is the
> projection calling every stamped link live. **The rule therefore is not "stats is bigger" — it is
> that no UI may present any stats field as a browsable count at all**, in either direction.
>
> Consequence for the shipped wording: `CatalogScale.connectionNotice` and `SCOPE_NOTE` used to
> assert the smaller-than direction (`"… the catalog you can browse here is smaller"`, `"they
> include works this app must not show"`), and today's measurement does not support an arrow in
> either direction. **Retired by App Session 30:** the notice now reads "This server stores $posts
> works — its own total, not the count you can browse here", the scope note says what a stored tally
> *can* contain rather than what it *is*, and `StatsHonestyTest` fails on a directional word in
> either sign (`smaller`, `larger`, `bigger`, `fewer`, `above`, `below`) for both a full server and an
> empty one — because a test that only banned the word "Title" went green while a sentence like the
> one above was wrong.
>
> **The client half of that rule is `viewmodel/CatalogScale.kt`** (App Session 27): the only
> wording allowed for these three numbers. Settings paints
> `Works stored / Releases stored / Links stored` over that owner and Setup/Settings connection
> notices come from `CatalogScale.connectionNotice(posts)`. `tooling/StatsHonestyTest` fails if a
> screen calls a stored total a title or a stream, and — because a refusal is green on an empty file — it also
> fails if the numbers stop being rendered. A surface that genuinely wants a browsable count must
> ask the list route for its adult-scoped `total` (`/api/v1/posts?limit=1` answers it), never
> reskin this one.

---

