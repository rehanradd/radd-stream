# PARITY — WHAT THIS APP CANNOT SHIP YET, AND WHO OWNS EACH BLOCKER

> Checklist item #21. Every row is a competitive feature (Netflix / Prime Video / YouTube /
> Temu-grade expectations for a 2026 streaming client) that the Android app **does not have**,
> sorted by what actually stops it: a server contract that does not exist, a deployment that
> refuses the request, a route that answers too slowly for a phone, or a promise only a device
> can make.
>
> **Every claim here was measured, not remembered.** Each row names a file:line in this repo or
> a live measurement taken on **2026-10-28** against `http://92.4.95.252` (public) and
> `http://127.0.0.1:8080` (the running service, loopback). §6 is the exact read-only recipe, so
> anyone can re-run it in ten minutes instead of trusting this prose — which is how three of the
> "known blockers" below turned out to be already unblocked.
>
> **The rule for the rest of the app:** a feature in §3 stays unwired until its blocker clears.
> It never ships as a stub, never fabricates the missing data client-side, and never degrades to
> a guess. Where the blocker is app-side (§4) that is not an excuse — it is the honest backlog,
> and each row there names the file to change.

---

## 1. What the phone can actually reach today

The live surface is an **allow-list at the reverse proxy**, not the set of routes `viewer.py`
implements. `/etc/nginx/sites-enabled/` (this host) ends with:

```nginx
# Protect administrative internal API endpoints
location ^~ /api/ {
    return 403;
}
```

and above it sit the exact/prefix exceptions that are proxied to `127.0.0.1:8080`:

| Publicly reachable | Verb scope |
|---|---|
| `/api/v1/posts` (prefix — list **and** `/posts/{id}`) | GET/HEAD |
| `/api/v1/stats` (`=`) | GET/HEAD |
| `/api/v1/stream` | GET/HEAD |
| `/api/v1/app/remote-config` (`=`) | GET/HEAD |
| `/api/v1/download` (`=`) | GET/HEAD |
| `/api/v1/search/by-media` (`=`) | GET/HEAD |
| `/api/v2/account*` (`^~`) | GET/HEAD/POST/PUT/DELETE |
| `/download/` (static APK) | — |

Measured: `GET https://…/api/v2/manifest`, `/api/v2/stats`, `/api/v2/search`, `/api/v2/works/x`
**from the public host all return an nginx `403 Forbidden` HTML page** — the JSON problem body
the v2 contract promises is never reached, because nginx answers first. `GET /api/v2/account/entitlement`
with no bearer returns a correct `401` problem+json, proving the exception works and the deny is
route-shape, not auth.

**Consequence:** the app's entire reachable contract is the six v1 API reads above plus
`/api/v2/account*`. `App/AGENTS.md` §5 lists four calls; the reachable set is bigger than what
the app uses, and that gap is §4 here, not a server gap.

There is no TLS. `curl -m 8 https://92.4.95.252/` produced no bytes and timed out (exit 124 on a
connect that never completed); the host serves plain HTTP only. That single fact is behind two
parity rows (§3 LAST-MILE and CASTING) and it is an owner/deployment decision, not an app bug.

### 1a. Two fields the list row gained since the docs were written

`GET /api/v1/posts?type=anime&limit=1` measured 2026-10-28 returns
`total: 5307` and a row whose keys are:

```
backdrop_urls, clean_title, content_type, country, genres, id, imdb_id, imdb_rating,
industry, is_animated, language, poster_url, release_count, seasons, source_count, title,
tmdb_id, work_ref, year
```

- **`is_animated` is on the list row.** `viewer.py:2513` answers `type=anime` from
  `(p.is_animated = 1 OR lower(p.industry) LIKE '%anime%')`, and `viewer.py:2539` offers the same
  predicate as an `industry=anime` facet. The Anime chip is therefore **not** backend-blocked.
- **`work_ref` is on the list row.** That is the handle the sync account accepts
  (`SyncAccountRepository.pushFavorite(workRef)` refuses anything else), so server-named
  favourites and cross-device resume are reachable from a browse tile today.
- **`subtitled` is absent** — the key exists in this working tree
  (`viewer.py:2450 _subtitled_posts`, applied at `:2612`/`:2620`) but `radd-stream.service`
  started 2026-10-27 19:47, before that edit landed. The app's Subtitled chip is correctly dark
  until someone restarts the service. This is a **deploy**, not code.

---

## 2. The four blocker classes

| Class | Meaning | Who moves it |
|---|---|---|
| **DEPLOY** | The code exists in this tree; the running process or the proxy does not expose it. | Owner: `systemctl restart radd-stream.service`, an nginx `location` block. |
| **SLOW** | The route answers, but far outside a phone's patience, so it cannot be a user-facing call. | Backend work (measured below); the app waits. |
| **NO FIELD** | The data does not exist anywhere in the ledger — no column, no scraper, no ingestion path. Nobody can guess it. | Backend schema + ingestion; a product decision first. |
| **DEVICE-ONLY** | The truth lives on the phone and the server has no way to verify it, so it cannot be honoured by any other party. | Product decision (server-side grant) or accept the local-only scope. |

### 2a. Measured v2 latency (loopback, 2026-10-28, 1 vCPU, un-warmed then re-tried)

| Route | Result |
|---|---|
| `GET /api/v2/suggest?q=ra` | **200 in 6.97 s** — the only v2 read usable from a UI |
| `GET /api/v2/manifest` | **200 in 52.8 s**, then 80.4 s, then 33.1 s |
| `GET /api/v2/browse?limit=1` | **0 bytes at 120 s** (curl exit 28), again 0 bytes at 60 s |
| `GET /api/v2/search?q=ray` | **0 bytes at 120 s** |
| `GET /api/v2/stats` | **0 bytes at 120 s** |
| `GET /api/v2/works/zz`, `/api/v2/nope`, `/api/v2/links/zz/resolve` | correct `404` problem+json in 0.4–0.7 s |

### 2b. Measured v1 latency on the same box, same day — including the four routes the app actually calls

| Route | Result |
|---|---|
| `GET /api/v1/stats` | **200 in 0.004 s** (the 120 s `_STATS_CACHE`, `viewer.py:2821-2823`, is doing its job) |
| `GET /api/v1/posts?limit=20` | **200 in 0.209 s** |
| `GET /api/v1/posts?type=anime&limit=20` | **200 in 0.330 s** — the anime filter is not a slow path |
| `GET /api/v1/app/remote-config` | **200 in 0.014 s** |
| `GET /api/v1/posts/100858`, `/108678` (small works) | **200 in 0.02–0.03 s**, 4–5 KB |
| `GET /api/v1/posts/40582` (Naruto: ~1,000 releases) | **200 in 10.38 s, 3,454,126 bytes** |
| `GET /api/v1/search/by-media?q=naruto&limit=3` | **200 in 82.4 s** (§4-D) |
| `GET /api/v1/search/by-media?q=naruto&duration_s=1400` | **0 bytes at 45 s** (curl exit 28) |

**Why the last two rows decide a client feature, and the sixth row decides not to change one.**
The app's OkHttp client is built with `connectTimeout(10, SECONDS)` and `readTimeout(15, SECONDS)`
(`ApiProvider.kt:51-52`). So by-media can never be wired: every call would surface as a
`SocketTimeoutException` and `friendlyNetworkError` would answer "The server took too long to
answer. Try again." — a control that fails 100 % of the time. The 3.4 MB / 10.4 s detail page, by
contrast, **is inside** the budget, so no timeout is touched here: the margin is recorded because
the largest work in the catalog is not necessarily the one this probe happened to pick, and a
future work with more releases would cross 15 s on this box. Raising the read timeout to chase one
measurement would be guessing; the honest response to a 40 % margin is to note it and let the
detail route be tuned, not the client to be papered over.

### 2c. Two honest notes on the v2 table, restated so the next reader does not repeat the mistake

First, these are **loopback** numbers — the public path adds the proxy and the network, so a
phone does strictly worse. Second, the projection **is** built on this host:
`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` carries the full `cat_*` set
(`cat_works` 116,922 rows, `cat_releases` 1,383,752, `cat_links` 3,783,959,
`projected_at` set, build took 9,770 s). So the blocker is **not** the one the docs say it is:
`api_v2.py:659 has_catalog()` would answer `503 unavailable`, and the routes instead disappear
into multi-minute full read-model queries that never write a response within any client timeout.
A request that neither answers nor fails is the worst thing a phone can be pointed at, and the
app must never send one.

---

## 3. Parity rows — the features we do not have

Capability names on the left are what the leading 2026 clients offer. "Fallback" is what this
app honestly shows instead; it is never presented as the feature.

| # | Capability competitors ship | Class | Blocker, with evidence | The app's fallback today |
|---|---|---|---|---|
| 1 | **Server-ranked play bundle** — one call returns "play this, in this order" | SLOW | `api_v2.py:1663` `POST /api/v2/play` sits behind the same read model; nginx 403s it publicly. `EndpointGaps.PLAY` (G-7) | `getPostDetail` → client `PrintDescriptor` + `LinkClassification` ranking |
| 2 | **Resolver round-trip for gated links** | SLOW/DEPLOY | `/api/v2/links/{id}/resolve` 403 publicly; `EndpointGaps.RESOLVE` | `GET /api/v1/stream?id=…&redirect=0`, reachable and used |
| 3 | **Dead-link reporting → self-healing catalog** | DEPLOY+SLOW | `POST /api/v2/links/{id}/report` is 403'd publicly. The v1 heal route is **operator-only by design** (`/api/heal` is in `OPERATOR_ONLY_ROUTES`, `viewer.py:58`, so the public port answers 404) and it re-resolves a whole post rather than recording what a viewer saw — there is no public channel that accepts a per-link verdict. (Session 6's note that `/api/heal` "never writes a response" is retired: `viewer.py:3104-3113` now sends JSON.) `EndpointGaps.REPORT` | Nothing. The app cannot tell the server a link died; `v1Fallback = null` is accurate |
| 4 | **Season-pack episode offsets** ("episode 7 starts at byte 1.2 GB") | DEPLOY+SLOW | `/api/v2/episodes/{id}/offset` 403 publicly. The projection *does* have `cat_offsets`, so the data is closer than the docs admit — what is missing is a reachable, fast route. `EndpointGaps.OFFSET` | Numbered episodes play as their own files; an in-file packed successor relies on the player seeking inside one file |
| 5 | **Delta sync ("what changed since 04:00")** | DEPLOY+SLOW | `/api/v2/sync?since=` 403 publicly; no `/api/v1/sync` exists. `EndpointGaps.SYNC` | Re-fetch `/api/v1/posts?page=n`; the account's favourites/progress lists are pulled whole |
| 6 | **Stable work identity across re-projection** | DEPLOY | `/api/v2/works/{work_key}` 403 publicly, and it is the slow family. `EndpointGaps.MANIFEST` | `/api/v1/posts/{numericId}` — a row id that survives as long as this database does |
| 7 | **Server-authoritative print fields** (codec / HDR / quality_score / coverage) | SLOW | `cat_releases` carries them (`API_V2.md` §8 marks them ✅ in Layer 1) but no v1 route sends them and the v2 route is unreachable. `EndpointGaps.PRINT_FIELDS` (G-4) | `ReleaseLabelParsing` — a client-side port of the server's own label grammar, so the app and server agree by construction, not by luck |
| 8 | **Measured link quality, TTL, resumability** | SLOW | `cat_links`/`cat_link_evidence` exist in Layer 1; nothing on the v1 wire. `EndpointGaps.LINK_FIELDS` (G-5) | `LinkClassification` prior; real TTL only from `/api/v1/stream` |
| 9 | **Subtitles as selectable tracks** (real `.srt`/`.vtt` URLs) | NO FIELD for the asset, SLOW for the metadata | The *fact* is already projected: `cat_releases.subtitle_mode` / `subtitle_languages` (`catalog_v2.py:258-259`) and the v2 print payload emits `"subtitles": {"mode", "languages"}` (`catalog_api.py:885-888`). What does not exist anywhere is a subtitle **file**: no URL column, no importer, no track list — `grep -rn "subtitle_url" Fast_Fetch/*.py` → zero hits — and `catalog_api` can only ever say "external / hardcoded / none". `EndpointGaps.SUBTITLES` (G-1) | The `ESub`/`Subtitled` badge is descriptive only, and the `subtitled` boolean this tree derives for the v1 list (`viewer.py:2450`, undeployed — §1a) is an existence test, not a track. The player's offset sheet nudges a system overlay; all parsing the app has is client-side (`SubtitleParsersTest`, 15 cases) |
| 10 | **Trailer playback / preview on the detail page** | NO FIELD | No `trailer` column in the ledger, no YouTube-id ingestion; the only `trailer` string in the backend is a *rejected* nav label in `import_7starhd.py:360`. Nothing downstream can invent it | Poster + backdrop hero only |
| 11 | **Certification and parental guidance** (PG-13 / 18A / content advisories) | NO FIELD | `grep -rn "certification\|parental\|content_advis" Fast_Fetch/*.py` → zero hits. IMDb/TMDB would be the source; no importer fetches it | The 18+ policy is all-or-nothing: flagged works are stored and **never** shown (`redact.adult_clause`, filtered in every public query) |
| 12 | **Editorial / featured rail** (a curated hero, not "whatever is newest") | NO FIELD | `grep -n "featured" Fast_Fetch/*.py` hits only WordPress *image* fields inside importers; there is no `featured`/`editorial`/`pinned` column and no admin control for one | `HeroCarousel` deliberately reuses rail 1 and says so in its own header (Session 8) |
| 13 | **A real "Trending" with a visible rank** (#1…#10 this week) | NO FIELD | There is no play-count column anywhere. The v1 `sort=trending` ranks by `release_count + source_count` — an availability proxy, honest but not popularity. `/api/v2/play`, the only route that could count plays, is unreachable | `SearchViewModel`'s sort names it "Most available"-flavoured and the default sort is NOT trending (checklist #6). No `#N` badge: the rank parameter `PosterCard` once had was deleted in #20 because no caller and no server field existed |
| 14 | **Personalised recommendations / because-you-watched** | NO FIELD | Requires a server-side event stream. The app never tells the server what was watched *and played* (row 3 and `/api/v2/play` are both blocked); account `progress` rows exist but no route turns them into suggestions | Room-backed local favourites and Continue Watching only |
| 15 | **Ad-supported free tier with real ad breaks** | NO FIELD + OWNER | `AdSlotPolicy` is the single placement authority and refuses mid-roll by design; there is no ad SDK, no creative source, and `monetag_rewarded_zone_id` / `adsterra_native_banner_id` arrive through remote config as *ids only*. Shipping an SDK is an owner/product/legal decision (a play-store listing changes with it) | The policy seam plus the VIP removal path. `AdSlotPolicyTest` (7+2) pins that nothing can interrupt a running title |
| 16 | **Rent / buy / flatrate offers with prices per title** | NO FIELD | `cat_entitlements` exists in Layer 1 but the ledger has no per-title offer, price, window or `delivery channel` data to project; `/api/v1/app/remote-config` publishes exactly two membership prices (`vip_monthly_pkr` 200, `vip_yearly_pkr` 1500 — `admin_panel.py:929-930`). `EndpointGaps.ENTITLEMENT` (G-6) | `Entitlement.freeDefault` for every work, and one real membership route |
| 17 | **Chromecast / Lean-back Android TV** | NO FIELD for TLS + DEPLOY for discovery | Casting hands a *URL* to another device, which must be able to fetch it: the host is plain HTTP with no certificate (§1) and a Google Play release build may not permit cleartext. Phase 3 in `App/AGENTS.md` §8 correctly still says ⏳ | Handset playback through `ExoPlayer` with the redirector's resolved URL |
| 18 | **Rewarded-ad VIP that works everywhere** | DEVICE-ONLY | `RewardedVipPass` stores a deadline in this device's DataStore. The server's bypass is a *signed capability*: `viewer.py:389 request_is_vip()` accepts a bearer sync key or `?vip=`/`?vip_token=` parsed by `redact.parse_vip_pass`, and `mint_vip_pass` HMACs the expiry with a server secret. The doc string is explicit that a caller-typed `vip=1` is deliberately not trusted. A local boolean therefore moves nothing — and that is the correct security answer | The pass silences ads on the device that earned it, and the card says so in the copy |
| 19 | **Cross-device resume without signing in** | DEVICE-ONLY (by design) | `SyncAccountRepository` refuses to send anything but a minted `workRef`; progress is keyed to a bearer key. There is no anonymous device roster server-side | Room + DataStore progress on this device; a signed-in viewer gets the account rows (and `work_ref` now makes that nameable from a list tile — §4) |
| 20 | **Stats a viewer can believe** ("116,922 titles") | NO FIELD (scope leak) | `/api/v1/stats` now prefers `cat_projection_meta` (`viewer.py:2826-2833`): `works=116922`, and the projection is **not** adult-scoped — `SELECT COUNT(*) FROM cat_works WHERE is_18_plus=1` → 13,342. The fallback `COUNT` queries *are* filtered (`:2838-2845`). **Re-measured 2026-10-29 and the arrow is gone:** the same `stats.posts` `116922` now sits *under* a browsable `total` of `131559` (and `134815` after the owner's later merges — root `docs/SESSION_CHECKPOINT.md` 04:50, where `posts=149818` minus `is_18_plus=15003` equals `134815` exactly). So this row does **not** get to say which number is bigger. Two further facts the App lane cannot settle and deliberately leaves open: `App/AGENTS.md` §5 records the preferred branch as reading keys named `works_safe / releases_safe / links_safe`, while this row's own SQL says the stamped `116922` is the *whole* `cat_works` count including 13,342 flagged — either the `_safe` keys are not what their name promises, or the stamp predates the flagging. Re-deriving it means reading `Fast_Fetch/viewer.py` and the projection metadata table, which is the backend lane. What survives either answer is the rule, not the direction | **App-side mitigation shipped (App Session 27), arrow retired (Session 30):** `viewmodel/CatalogScale` is the single wording owner for these three numbers — Settings paints `Works stored / Releases stored / Links stored` plus a "stored totals, not a browsable count" note that says what the tally *can* contain, and both connection notices come from `connectionNotice(posts)`, which never says "available" and never compares sizes. Pinned by `tooling/StatsHonestyTest` (6 cases, two of them rewritten), which now fails on a directional word in either sign. **What is still missing is the server's own browsable count**: no field answers "titles this viewer may list", and a client cannot subtract rows it is refused. `/api/v1/posts?limit=1` does answer an adult-scoped `total`, so a surface that wants a real browsable figure must ask that route rather than reskin this one — one extra request per screen, and it is not the endpoint this row is about |
| 21 | **Third-party embed playback *inside our own player*** — i.e. a provider page whose video is lifted out of it and handed to ExoPlayer, with the page itself never shown | **WON'T DO (owner decision, 2026-10-28)** | This is not a missing field or a slow route: it is a refusal. The technique is a hidden `WebView` + `shouldInterceptRequest` sniffing for `.m3u8` / `video/mp4` and then killing the page, and it exists solely to defeat the conditions the provider put on its own player. Root `AGENTS.md` ("Not a DRM circumventer", "Do not disguise its purpose or frame work to bypass another service's safety rules") and `DISCLAIMER.md` §2 rule it out, so no client code of that shape is written, reviewed or merged. `tooling/ProviderPageScreenTest` pins the four API calls that would make it possible to *never appear* in `EmbedWebViewScreen.kt`. Separately, the premise was also fictional here: there is no `needs-js` resolver value in this backend, and `sources.playback_type` is a `TEXT` column (`fast_fetch.py:644`) whose importers only ever write `url|iframe|hls|mp4|video|direct` (`fast_fetch.py:3257-3271`) — the served word for an iframe row is `kind=external` / `playable=false` (`viewer.py:176 link_view()`) | The provider's **own page, visibly**, in their player, under their conditions, opened through our redirector (see §4-G). A page is never offered as a kept file and never given to Media3 |

---

## 4. Not blocked — app-side work that is reachable today

These are **not** parity excuses; they are the backlog the measurements above just unlocked. Each
row is one call site plus one test, and none needs a server change.

| # | Capability | What is already reachable | What the app still must do |
|---|---|---|---|
| A | ~~The Anime entry actually filters~~ **DONE — `69b3795`, gated at `daeb3d2`** | `GET /api/v1/posts?type=anime` → `total 5307` (measured). `HomeScreen.kt:237` sends `type=anime`, `SearchScreen`'s `typeChips` gained the same entry, and `viewer.py:2513`/`:2539` both answer it | Shipped: `Post.isAnimated` decodes the INTEGER 0/1 column through `LenientBooleanAdapter`, `V1CatalogMapper.animatedFromList` reads it, and one label owner (`WorkTypeLabel.of`) paints "Anime" on the tile, the hero and the detail header; a flagged series also groups into its own rail (`typeGroupKey`). Pinned by `AnimeWireTest` (14). The remainder this row carried is **closed by App Session 26**: Room version 6 adds nullable `isAnimated` and `subtitled` to `favorite_posts` through real `MIGRATION_5_6` DDL, `fromPost` keeps both and `toPost()` gives them back, so a saved anime tile says "Anime" and a saved subtitled work keeps its chip. NULL on an older row means "this build never asked", never "not animated"; the column/entity parity is pinned by `FavoritesSchemaGuardTest` (6), which is the offline substitute for the Room runtime check this no-device box cannot run. **One asymmetry stays honest:** `fromPostDetail` cannot carry `subtitled` because the detail route sends no such key (it is a per-page existence test the list route appends), so a work saved from its detail page shows no Subtitled chip until it is re-saved from a grid |
| B | ~~Server-named favourites from any tile~~ **DONE — verified in code, not assumed** | `work_ref` on the list row (measured); `api/v2/account/favorites` + `/progress` reachable through nginx | Shipped: `FavoritePost.workRef` is the stored column, `fromPost`/`fromPostDetail` both carry the server's handle onto the row, `syncable` is `!workRef.isNullOrBlank()`, and `SyncAccountRepository.pushFavorite`/`removeRemoteFavorite`/`pushProgress` refuse anything else with `SyncAck.NOT_NAMABLE` (`:220-231`, `:257`) — a title, a row id or a work key is never sent. The only rows that stay on the device are the ones saved by a build that never received a handle, which is the honest answer, not a gap |
| C | ~~A paid VIP actually skipping the shortener~~ **CLOSED 2026-10-29 — the owner retired link shorteners from the project; nothing is left to bypass** | The 2026-10-28 measurement is what made this cheap to close, so it stays on the record: live `GET /api/v1/app/remote-config` answered `link_shorteners: [{shrinkme, configured: false}, {droplink, configured: false}]`, and the app never touched `/api/v1/download` at all — `ApiProvider.streamRedirectUrl` (`:91-98`) was and is the only byte-path builder in `App/app/src`, and every consumer (`CacheSeeds.kt`, `DeviceDownloadsRepository.kt`, `PlayerViewModel.kt`) uses `/api/v1/stream?id=<handle>`, which has no shortener in its code path. **Correcting the directive as received:** there was never a `wrapWithShortener` in this app — a read-only `grep -rni "wrapWithShortener" app/src` returns nothing, and `DetailViewModel.kt` carries no shortener reference of any kind. The client-side shortener surface was exactly one wire field, `VipRemoteConfig.linkShorteners`, which **nothing ever read** outside its own test | **Done, client-side.** `VipRemoteLinkShortener` and the `link_shorteners` field are deleted from `VipRemoteConfig.kt`; `VipRemoteConfigTest` keeps a case proving a body that still *publishes* the retired key decodes unchanged, so a server that has not been cleaned up cannot break pricing on a phone. **What is NOT mine to do:** the producing side — `viewer.shorten_download_url()`, `admin_panel.shortener_targets()` and the `link_shorteners` row remote-config still publishes — lives in `Fast_Fetch/*.py`, which is the backend lane and off-limits to App agents. Until that is cleaned, the retired behaviour is a server-side no-op, not a deleted feature; the owner should open a backend task so `/admin` stops advertising a mechanism the project has dropped. The `vip-pass` route (§4 of Session 24) stays as it was recorded: reachable, unused, and now with even less reason to be wired |
| D | **"Which work is this file?" identification** — **MEASURED 2026-10-28: SKIP THE WIRING, the route is unreachable in practice from a phone** | `GET /api/v1/search/by-media` is proxied, rate-limited and *correct*: loopback `?q=naruto&limit=3` answers `200` with the honest three-way report (`matched_on` / `mismatched_on` / `unknown_on`, plus `runtime_minutes`, `resolutions`, `is_animated`, `work_ref`) — the same row shape as a `q=` search, so a client could render it with no new model. **But it answered in 82.4 s**, and `?q=naruto&duration_s=1400` did not answer within 45 s at all (`curl` exit 28). The app's OkHttp client is configured with `readTimeout(15, SECONDS)` (`ApiProvider.kt:52`), so every call would die as a `SocketTimeoutException` and `friendlyNetworkError` would say "The server took too long to answer. Try again." — a button that fails 100 % of the time is worse than no button | **Not app work.** The route needs the same tuning the v2 reads need (task §2's SLOW class: `browse`/`search`/`stats` hung past 120 s, `manifest` 33–80 s); this is one more member of that family, and its cost is concentrated in the per-candidate `_subtitled_posts` / enrichment pass over a `LIKE '%title%'` set. Whoever tunes Layer 2 makes this row real; then the wiring is one Retrofit method plus one Detail-screen diagnostic row, and the row shape is already proven above. **Recorded, deliberately not implemented** |
| E | **The Subtitled chip lighting up** | `viewer._subtitled_posts` in this tree; `Post.subtitled: Boolean?` already tolerates its absence | A **deploy** (restart `radd-stream.service`), which the owner does — the app needs no change and currently renders nothing, correctly. **Owner decision 2026-10-28: no restart now.** The live API stays frozen until the owner says otherwise, so this ships with the next planned deploy and belongs in that release note ("tiles now badge a work whose prints claim subtitles; a server that has not shipped the key shows no badge"), not in a client workaround |
| F | ~~Season/episode grouping~~ **DONE — the keys were retired in code long before this doc caught up; `App/AGENTS.md` §6 corrected at `cf10f03`** | `releases[].season` / `episode` / `release_title` are on the detail wire and are exactly what `ReleaseDetail` maps (`Models.kt:236-253`); `seasonNumber`/`episodeNumber`/`resolution`/`sizeBytes` are derivations through `printDescriptor` (`:264-286`), `audio` is `languages`, and `episode_title` does not exist because no server column backs it | Nothing left. `SeasonChips` paints `SeasonGroup.number`, which `ReleaseLayoutBuilder.kt:300-330` builds from those derived numbers, so grouping is live. `StreamResponse.isTemporary` is `Boolean?` (`:343-345`) on `LenientBooleanAdapter`. The stale §6 warning that claimed all five keys were phantom is what this row was really about, and it is now retired in the guide itself |
| G | ~~A page link that fails quietly or is "kept" as if it were a film~~ **DONE — shipped app-side in this tree** | `link_view()` serves `kind="external"` with `playable=false` on v1; the Layer-1 projection serves the same fact as `kind="embed", playability="webview", rank_score=280` (`GoldenVectors.LinkGoldenVectors`, 8 rows). Both edges already answer on the deployed host — no server change, no restart | Shipped: `network/models/ProviderPageLinks` is the one rule for both spellings; `LinkClassification` maps them to `LinkKind.EMBED` / `Playability.WEBVIEW` and its derived `rankScore` lands on the server's 280; `RankedLink.keepable` excludes pages (before this, `keep` handed DownloadManager an HTML page and the Downloads row claimed a film), and it excludes them by the **served word**, not by the actionable verdict: a page that is currently `dead` is still not a file, so `isPageLink` (kind/playability only) is what `keepable`, `keepPrint` and `QualityOption.downloadOnly` read, while `isProviderPage` — which additionally needs a handle, a redirector and a live status — is what decides whether an "Open" offer exists. `DetailViewModel` routes a page to `Screen.Embed` **before** any failover or resume staging; `ui/screens/EmbedWebViewScreen.kt` shows the provider's page in the foreground through `<server>/api/v1/stream?id=<handle>`, with page-history back navigation, HTML5 fullscreen honoured, non-web schemes refused, media-permission requests denied, a "Try again" on failure and an "Open in browser" that hands over **our** redirector only. **Two remainders, both honest:** (1) no device or emulator has run this screen, so it is compile- and unit-verified only; (2) the host is plain HTTP (§1) and cleartext is permitted in the debug build only, so a signed release build cannot open a provider page (or a stream) from `92.4.95.252` until the deployment has TLS — the same blocker row 17 names, not a new one |

---

## 5. Claims elsewhere that these measurements retire

Recorded here so the next reader does not re-litigate them, and because several live in files this
checklist does not own. **Proposed, not edited** — `Fast_Fetch/*.py` and `Fast_Fetch/*.md` are
backend-owned and the standing instruction for app sessions is to propose rather than edit.

| Where | Says | Measured truth (2026-10-28) |
|---|---|---|
| `App/AGENTS.md` §5 | "🚨 There is no `?type=anime`… returns `{total: 0}`" | `total: 5307`. `viewer.py:2513` answers it from the flag/industry |
| `App/AGENTS.md` §6 note | "The Anime chip is known broken today" | The chip's *request* works; what is missing is §4-A's client-side typing. (`SearchScreen`'s chips no longer offer Anime at all — `typeChips` there is All/Movies/Series/Seasons; the anime path in search is the `industry` facet.) |
| `App/AGENTS.md` §5 stats warning | stats "count every post including 18+" | Still true, different mechanism: it reads `cat_projection_meta.works` (116,922, adult included), while the fallback `COUNT` queries are filtered |
| `network/models/Models.kt:57-63`, `V1CatalogMapper.kt:47-52` | the list "does not select `is_animated`", "`?type=anime` returns zero rows" | Both false on the deployed server; the list row carries the key |
| `network/models/Models.kt:104-113` (`Post.workRef`) | "Today's v1 projection sends no such key" | It sends `work_ref` on both list and detail rows |
| `network/models/EndpointGaps.kt` header | v2 is unusable "because every v2 route requires the `cat_*` projection, and the database the public service runs on has none" | The live database has the whole projection. The real blockers are nginx's `return 403` and §2a's multi-minute read models |
| `Fast_Fetch/API_V2.md:28-32` | "the live database has no `cat_*` tables yet, so every v2 route currently answers `503 unavailable`" | `cat_*` exists and is populated; the routes hang instead of answering 503, which is a *worse* client outcome than the documented one |

---

## 6. Re-verify this document in ten minutes

Read-only. Nothing here writes to a database, restarts a service, or touches a credential.

```bash
# 1. What the proxy allows (expect 403 HTML on the v2 catalog routes, 401 json on account)
for p in api/v1/stats api/v1/posts?limit=1 "api/v1/posts/1" api/v1/app/remote-config \
         api/v1/download api/v1/search/by-media api/v2/manifest api/v2/browse api/v2/stats \
         api/v2/account/entitlement; do
  printf '%-32s %s\n' "$p" "$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "http://92.4.95.252/$p")"
done

# 2. The anime filter, and which keys a list row really carries
curl -sS -m 20 'http://92.4.95.252/api/v1/posts?type=anime&limit=1' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["total"], sorted(d["results"][0]))'

# 3. No TLS
curl -sS -m 8 -o /dev/null https://92.4.95.252/ ; echo "rc=$?"     # expect a connect failure

# 4. The projection state and the adult leak, from the database the SERVICE uses
pgrep -af "fast_fetch.py serve"                                  # note the PID
ls -l /proc/<PID>/fd | grep -o '/[^ ]*\.db.*' | sort -u          # the real RADD_DB_PATH
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect('file:/home/ubuntu/radd-stream-data/merged_catalog_20261025.db?mode=ro', uri=True)
print([r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'cat_%'")][:6])
print('cat_works', c.execute('SELECT COUNT(*) FROM cat_works').fetchone()[0],
      'adult', c.execute('SELECT COUNT(*) FROM cat_works WHERE is_18_plus=1').fetchone()[0])
EOF

# 5. v2 latency — loopback, and long enough to be honest. Expect suggest ~7 s, manifest ~1 min,
#    browse/search/stats to exceed any client timeout. Four routes is up to ~9 minutes of this
#    one-vCPU host: run it once, not in a loop.
for p in "suggest?q=a" "manifest" "browse" "stats"; do
  printf '%-14s ' "$p"; curl -sS -m 130 -o /dev/null -w '%{http_code} %{time_total}s\n' \
    "http://127.0.0.1:8080/api/v2/$p" || echo "no answer"
done
```

If a row in §3 moves class, edit **this file** and the table in §5 in the same commit — a parity
doc that lags the server is worse than no doc.

---

## 7. What this document deliberately does not claim

- It is not a plan. §4 rows are candidates for the next checklist item; the master orders them.
- It does not authorise any `.py` edit, any service restart, or any nginx change from an app
  session. §5 and §6 are how those get asked for.
- It makes no device claim. Every number above is a server-side measurement or a source read;
  nothing in §3 has been confirmed on a handset, because this host has none.
- It does not soften the adult policy: 18+ rows are stored and never displayed, and row 11's
  "no certification field" is not an invitation to expose flagged works behind a rating label.
