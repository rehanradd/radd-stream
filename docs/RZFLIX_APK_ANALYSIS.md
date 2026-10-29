# RzFlix APK — static analysis, and what radd-stream should take from it

Lane: `q5-rzflix-fzmovies` (`/tmp/q5_rzflix_lane`). Date: 2026-10-30.
Method: **static only**. The APK was downloaded to `/tmp/q5_rzflix/` (never to
`/opt/radd-stream`, never into the repo), read with `zipfile` + byte-level
`strings` + a hand-rolled binary-AXML string-pool parser, all under `python3 -S`
with zero pip installs. Nothing in the APK was installed, executed, or loaded
into anything that runs code; no dex was handed to a runtime, no instrumentation,
no proxy. Six outbound requests were made in total for this task, each with its
host printed and a short `-m` timeout (4 for the analysis, 2 for fzmovies).

Every URL below is an **untrusted pointer to somebody else's service**. They are
recorded, not used. Two of them were probed once, for the question the owner
asked; the rest were never touched.

> **Secrets.** The config file at `api.ringzstudio.com/apis/r.txt` carries live
> credential material under the keys `appTkn`, `secKey` and `useSecKey`. Those
> values are **not reproduced in this document** and were never sent anywhere:
> replaying a token extracted from someone else's app against their API is
> reaching a protected service with stolen credentials, which is not what this
> task is. The fetched copy stays in the lane's `/tmp/q5_rzflix/` scratch
> directory and is not committed.

---

## 1. What the artifact is

| Fact | Measured value |
|---|---|
| Source | `https://archive.org/download/rz-flix-updated_202604/RzFlix_Updated.apk` |
| Size | 119,744,040 bytes |
| SHA-256 | `e2b4ea954a34456691a06a11fe11fbe386c6f7cd3641d68ca47e403435546b46` |
| Package | `com.rflix.rflix` (recovered from the binary `AndroidManifest.xml` string pool: 280 UTF-16 strings) |
| Framework | **Flutter**, not native/Kotlin. App logic is AOT-compiled into `lib/<abi>/libapp.so`, not into the dex files. |
| ABIs shipped | `arm64-v8a`, `armeabi-v7a`, `x86_64` in one fat APK (`libmpv.so` is 12.4 MB of the total per ABI) — consistent with sideloading, not Play delivery |
| Zip layout | 2,137 entries: 4 `.dex`, 15 `lib/`, 35 `assets/`, 96 `META-INF/` |
| Own code size | 88 Dart modules `package:rflix/*` recovered from the AOT image |
| Largest own-code file | `lib/arm64-v8a/libapp.so` (10,879,580 bytes) |
| URLs recovered | 165 unique literals across `libapp.so` + dex. **3 are product endpoints; the rest are SDK/library/document strings.** |

The Kotlin/Java side is only the Flutter shell plus SDK registrations
(Firebase, OneSignal, TradPlus, Vungle, Unity, mBridge, Honeygain). Everything
interesting is in `libapp.so` and in the runtime config, which is why the dex
files alone would have told us nothing.

One trap for a future reader: `assets/builddatas.json` in this APK is **not**
their config. It is a 450-byte mBridge ad-SDK artifact listing three
`IPlayTempleView` methods with numeric keys. The real config is the fetched
`r.txt` described in §2.

---

## 2. Base URLs and API path patterns

The app boots from **one** URL, hardcoded, and reads everything else from it:

```
https://api.ringzstudio.com/apis/r.txt          ← config bootstrap (a JSON array)
```

`r.txt` is 9,440 bytes, fetched once with `curl -m 15`, and is an **array of 3
profiles** (`id` 0, 1, 2 — `"Rflix 26"`, `"Rflix 26"`, `"Rflix 26 Hpan"`) sharing
one 81-key schema. Multiple white-label builds are served from one config file
and one backend; the app selects its profile by `id`.

From that file, the catalog host and every API path are **data, not code**:

| Role | Value in the measured config |
|---|---|
| Catalog / data API host | `dataapi.yomoviesapk.com` (in `link1` **and** `link2` — two failover slots, pointed at the same host) |
| Movies master list | `/mm.json` (`allData`) |
| Latest | `/public/movies/latest.json` (`latest`, `mbanner`) |
| New additions rail | `/public/movies/JustAdded.json` |
| Industry rails | `/public/movies/{Bollywood,Hollywood,South}.json` |
| Language rails | `/public/movies/{Punjabi,Gujarati,Bengali,Marathi}.json` |
| Adult rail | `/public/movies/Adult.json` |
| Web series | `/ss.json` (`sbanner`, `webseries`) |
| DesiHub (adult-adjacent rail) | `/desihub.json` |
| Anime | `/lstanime.json` |
| Taxonomy | `/cn.json` (categories), `/g.json` (genres), `/lng.json` (languages) |
| Live TV | `/live.json` |
| Play/embed wrapper | `https://rzflix.com/?s=rstudios` — **`?s=<server>` selects the embed provider** |
| APK self-update channel | `https://apk.ringzapidata.in/RzFlix.apk` |
| Unmet-search logging | `https://ereviewwala.com/Apps/log_unmet_search.php` |
| Custom ad image / target | `https://pub-8520…d6a.r2.dev/…` (Cloudflare R2) → `https://t.me/ringzstudio` |
| Second R2 bucket, support e-mail, cross-promo | `pub-0ee7…eed1.r2.dev`, `mailto:ringzstudio@proton.me`, `bit.ly/songsmodapk` |

**Path pattern, stated plainly:** there is no versioned API, no pagination
parameter, no query-string catalog endpoint. Each rail is a **pre-generated flat
JSON file** on a static host, and the client is told which file to read by the
config. `mainapi.yomoviesapk.com/r` also appears as a literal in the AOT image —
the second host of the same family, whose role is not determinable statically.

Live TV is not from their server at all. `M3uParser`/`M3uChannel` classes
consume **public GitHub raw playlists** baked into the binary:

```
https://raw.githubusercontent.com/drmlive/sliv-live-events/refs/heads/main/sonyliv.m3u
https://raw.githubusercontent.com/abusaeeidx/IPTV-Scraper-Zilla/refs/heads/main/Yupptv.m3u
https://raw.githubusercontent.com/abusaeeidx/CricHd-playlists-Auto-Update-permanent/refs/heads/main/ALL.m3u
```

---

## 3. Authentication — what is observable, and what is not

Measured, from `r.txt`: three credential-shaped keys — `appTkn`, `secKey`,
`useSecKey` — delivered in the same plaintext config file as the feature flags.
Their values are redacted here and were never replayed.

What static analysis **cannot** show is the wire form. Searched through the whole
AOT image and the dex strings:

* no `Authorization` literal, no `Bearer ` literal,
* no URL template containing `?tk=`, `&key=`, `&token=`, `&s=` or `&pt=`,
* `appTkn` and `secKey` appear only as the config field names,
* `apis/` appears (the config path), `/public/movies/` does **not** — consistent
  with those paths being assembled from config at runtime rather than baked in.

So the honest answer is: **the client holds a shared app token and a secondary
key from its config file, and how it presents them is not statically observable**
— a runtime string concatenation leaves no literal to find. It is *not* device
authentication: there is no signing, no nonce, no challenge. One token for every
installation, shipped in a file that is trivially public — which is precisely
why the two probes below bounced and why replaying it would be the wrong act.

**Probes made (2 requests, hosts printed, `-m 15`, no credentials sent):**

| Request | Result |
|---|---|
| `dataapi.yomoviesapk.com/public/movies/latest.json` | **403 — Cloudflare Access.** The feed is gated at the edge, not merely obscure. |
| `api.ringzstudio.com/…/latest.json`, `/mm.json` | Hostinger "This Page Does Not Exist" 404s — the config's own host/path pairing is not live for anonymous callers. |

After those two, probing stopped. The payload schema in §5 is therefore
**statically inferred from the app's own model classes, not observed on the
wire**, and is labelled as such.

---

## 4. Playable-link resolution

Three playback engines, in this order of preference, all visible in `libapp.so`
and the Flutter asset list:

1. **`media_kit` / mpv** (`lib/*/libmpv.so`, `modern_media_kit_player.dart`) for
   direct files and adaptive streams. Supporting evidence: `HlsManifest`,
   `HlsMasterPlaylist`, `HlsMediaPlaylist`, `HlsPlaylistParser`,
   `hlsManifestUrlD`, `hlsSegmentFormat`, `hlsVideoSegmentFormat`,
   `AdaptationSet`, `adaptiveFormats`, `mp4a`, `webm`, plus
   `assets/…/media_kit/assets/web/hls1.4.10.js`. `addLicense` and the
   Widevine `AcquireLicense` URI show a DRM code path is *linked in*, not that
   they use it.
2. **`flutter_inappwebview`** (`WebViewOptions`, `WebHelper`,
   `addJavaScriptHandler`, `webViewAssetLoader`) for embed pages — i.e. the
   `rzflix.com/?s=<server>` wrapper, which is itself an HTML page that resolves
   to a player.
3. **YouTube** as a *content source*, not just trailers:
   `omni_video_player/assets/youtube_player.html`, `playerVars`,
   `playerResponse`, `youtubei/v1/player?prettyPrint=false`, `noembed.com/embed`,
   `i3.ytimg.com/vi/`, `developers.google.com/youtube/iframe_api_reference`.

Subtitle support: `SubtitleTrack`, `subtitle_id`, `SUBTITLES`, `WEBVTT`,
`languageMap`, `imgVertical` — caption tracks are first-class, keyed per server.

**Resolution model, as inferred:** the item's JSON carries a per-quality,
per-server structure (`Quality`, `qualityUrls`, `serverDialog`,
`EpisodeListFromServer`), the app filters the servers by the config's
`serverNFlagMvs`/`FlagSrs` and `480pSNFlag`/`1080pFlag`/`4kFlag` switches, shows
a server picker, and hands the chosen URL either to mpv (direct/HLS) or to the
WebView (embed). **Which of the two is decided per server, by the operator's
config, without an app release.** No signature, no expiry, no per-user token in
the link itself is observable.

---

## 5. Catalog model (inferred from the app's own classes)

Class names recovered from the AOT image describe the shape:
`MovieResponse`, `MoviesListBloc`, `CategoryResponse`, `WebSeriesResponse`,
`WebseriesListBloc`, `PlayerResponse`, `WatchPageInitialData`, `M3uChannel`,
`EpisodeListFromServer`, `DownloadItem`, `WatchlistItem`,
`continue_watch_entry`, `movie`/`movieName`/`seriesTitle`/`posterUrl`/`img_url`/
`imageUrl`/`quality`/`qualityLabel`/`genre`/`season`/`episode`/`year`.

| Aspect | What the structure says |
|---|---|
| Unit | One flat "movie" record per rail file; rails are **materialised lists, not queries**. The same work appears in every rail file it belongs to. |
| Identity | No stable id in the config; `id` exists on the *config profile*, not on the work. Rail files are the identity: `/public/movies/Hollywood.json`. |
| Two media types | Movies (`/mm.json`, `separateMvs=TRUE`) and web series (`/ss.json`, `separateSrs=TRUE`) are **separate catalogs with separate flag namespaces** (`…FlagMvs` vs `…FlagSrs`). |
| Hierarchy | Series carry `season` + `episode` + `EpisodeListFromServer` — episodes are resolved **per server**, not once per episode. |
| Taxonomy | Separate small files: `/cn.json` categories, `/g.json` genres, `/lng.json` languages — so facets are their own endpoints rather than query parameters. |
| Rail semantics | `latest`, `JustAdded`, `nowPlaying` (`get_now_playing_bloc`), industry, language, adult, anime, desihub, live. |
| Local state | SQLite on device: `DatabaseHelper.dart`, `continue_watching_dao.dart`, watchlist, downloads. |

Compare our own model (`Fast_Fetch/API_V2.md`): we have a real `canonical_key`,
a `releases`/`download_sources` ledger, and a queryable SQLite catalog. Theirs is
a **denormalised CDN-of-JSON front end over an unseen store** — weaker identity,
far cheaper to serve. Both are valid; they optimise for different failure modes.

---

## 6. Quality tiers

Tiers are `480p`, `1080p`, `4K` as first-class config switches, and the tier is
**multiplied by the server**: `480pS1Flag` … `480pS4Flag` turn 480p on or off
*per server*, while `1080pFlag` and `4kFlag` are global, and
`e1080pFlagSrs`/`e4kFlagSrs` repeat the pair for series. `serverDialog` is the
UI that results. `qualityLabel`/`qualityUrls` on the record complete it.

So the tier model is: `(server × quality × media-type) → enabled`, all twelve-ish
combinations operator-editable at runtime. Our equivalents exist but are code,
not knobs: `Fast_Fetch/tiers.py` picks one winner per quality band, and
`redact`/`link_state` decide playability. That gap is the single most reusable
idea in this file.

---

## 7. The operator surface: 81 keys, 35 of them booleans

`r.txt` is a remote-config file of exactly the kind our
`admin_panel.remote_config()` produces, and it is worth reading as a competitor's
answer to the same question. Grouped by what it controls:

| Group | Keys |
|---|---|
| Ad cadence | `playerStartingAd`, `timerAdsFlag`, `afterHowMuchAdShown` (180), `playerAdsTimer` (35), `splashAds`, `categoryAds`, `srsAllAds`, `adsInLiveFlag`, `nativeAds`, `cwAds`, `customAds`, `customAdImg`, `customAdurl` |
| Source/quality gating | `server1FlagMvs`–`server4FlagMvs`, `server1FlagSrs`–`server4FlagSrs`, `tapeFlagMvs`, `480pS1Flag`–`480pS4Flag`, `1080pFlag`, `4kFlag`, `e1080pFlagSrs`, `e4kFlagSrs`, `decodeFlag` |
| Passive income | `hgEnableFlag`, `hgButtonFlag`, `hgButtonFlagNew`, `extraTermsHG`, `batteryPopUp`, `cstSDKEnable`, `permissionFlag` |
| Rail enablement | `liveFlag`, `searchNew`, `separateMvs`, `separateSrs`, `tab` (52), `otherAppLink`, `otherAppText` |
| Version enforcement | `version` (1.3.0), `closeVersion` (1.0.0) — with `closeApp.dart` behind it |
| Remote copy / push | `notification`, `homeNotification` (Hindi operator text, shown verbatim to users), `telgramUrl`, `supportemail` |
| Search telemetry | `searchLog`, `searchLogFlag` |
| Delivery | `apkUrl`, `link1`, `link2`, `name`, `id` |

Ad networks actually linked into the binary: **TradPlus** mediation (including
its China endpoints and its *test* endpoints, shipped in the same image),
**Vungle**, **Unity Ads**, **mBridge**, OMID/OMSDK verification scripts,
**Firebase Remote Config + Crashlytics + In-App Messaging**, **OneSignal**, and
**Honeygain**. The `playerAdsTimer`/`afterHowMuchAdShown` pair is a
time-based interstitial cadence, exactly the pillar `engagement.py` now models.

---

## 8. Ideas worth taking — they do X, we do Y, adopt Z because…

Each line names where it would land in our tree. Nothing here is implemented;
this is the pick-list.

1. **They do remote per-server enable flags; we do embed-server availability in
   code; adopt `sources_enabled`/`servers_enabled` as an operator list in
   `MONETIZATION_FIELDS` published through `remote_config()`, because a dead
   upstream is the one outage an operator can fix fastest and today we can only
   fix it by editing a parser.**
2. **They do per-quality-per-server switches (`480pS1..S4`, `1080p`, `4k`); we do
   `tiers.py` one-winner-per-band in SQL; adopt a `tier_enabled` list in the
   public config, because it lets the operator throttle bandwidth on the single
   vCPU by turning off 4K for an hour without a deploy.**
3. **They do a remote `closeVersion` floor with a `closeApp` screen; we do no
   version gate at all; adopt `min_app_version` + `close_app_below_version` in
   `/api/v1/app/remote-config`, because a client we cannot push to is a client we
   cannot recall — and the Android app is distributed outside Play.**
4. **They do `apkUrl` + in-app `downloadAndInstallApk` behind `REQUEST_INSTALL_PACKAGES`;
   we do a debug APK from CI and nothing else; adopt a self-update *prompt* that
   points at our own `/download/` edge (not silent install), because sideloaded
   apps die quietly when users never revisit the page — and stop short of the
   silent-install permission, which is the part that would cost us trust.**
5. **They do `searchLog` + `log_unmet_search.php` gated by `searchLogFlag`; we do
   nothing with a zero-result search; adopt a counters-only `unmet_query` record
   in `usage_stats.py` (query text, not user identity) and read it as the scrape
   backlog queue, because it converts the site's biggest failure into a work list
   for exactly the importer lane this task created.**
6. **They do two failover host slots (`link1`/`link2`) even though the operator
   pointed both at the same host; we do one base URL per site; adopt a
   `mirror_hosts` list per importer in the config, because `SITES.md` already
   documents `.gallery → .yt → .one → .vip` domain chains that we currently heal
   by hand-editing an importer.**
7. **They do whole rails as static JSON files regenerated upstream; we answer
   every browse from SQLite at 8080; adopt a nightly `--export-rails` that
   materialises `/api/v2` projections to JSON under the nginx-served static tree,
   because on one vCPU a file read is free and a `SELECT` is not — this is a
   latency idea, not a data-model change.**
8. **They do `notification`/`homeNotification` as operator-typed text; we have no
   broadcast channel; adopt `banner_text` + `banner_enabled` in
   `remote_config()` (already a `_TEXT` kind), because an operator who can warn
   users before an outage gets the same effect as monitoring for a fraction of
   the code.**
9. **They resolve subtitles per server (`subtitle_id`, `languageMap`, WEBVTT);
   we store none; adopt a `subtitle_url` on `download_sources`, because dubbed
   content is half our catalog and captioned playback is the difference between
   a Media3 player and a toy.**
10. **They do `serverDialog` with episodes resolved per server; we resolve one
    server per episode; adopt "list every server that has this episode" in the
    v2 projection, because a dead embed server currently takes the episode down
    with it instead of falling to the next row.**
11. **They do three playback engines with mpv for HLS; we do Media3/ExoPlayer in
    the Android app; adopt nothing — our choice is better for battery and Play
    policy — but *do* copy their `hlsSegmentFormat` discipline: declare the
    segment format per source instead of sniffing at playback time.**
12. **They do a custom self-serve ad slot (`customAdImg` + `customAdurl` on
    Cloudflare R2); we have no first-party inventory; adopt
    `house_ad_image_url` + `house_ad_target_url` as two `_URL` fields, because it
    monetises without a third-party SDK, costs nothing per impression, and can be
    switched off by one flag — the cheapest possible ad pillar.**
13. **They ship Honeygain (`hgEnableFlag`), reselling the user's bandwidth; we do
    nothing like it; adopt *nothing*, and record why: routing third-party traffic
    through a customer's IP for pennies is the kind of thing that ends a
    project's credibility, and the `batteryPopUp` dance they need to sell it is
    the tell.**
14. **They do live TV by consuming public GitHub M3U repos; we already serve
    `/api/m3u` for a single post; adopt an optional `m3u` export per rail
    (playlist = the catalog, at the edge), because it costs one projection and
    makes the whole catalog usable by any off-the-shelf player.**
15. **They ship adult rails that are *displayed* to end users
    (`/public/movies/Adult.json`, `get_Adult_bloc.dart`, `AdultSeriesAll`,
    `nowPlayingDesiHub`); we store 18+ rows and show them to nobody; adopt
    nothing — this is the one place where being stricter is a feature, and the
    AGENTS.md invariant (`redact.adult_clause`, loopback-only operator panel) is
    the reason our catalog can be served from a public edge at all.**
16. **They gate a failure screen behind a digest check (`shaVerificationFailedScreen`
    appears next to `downloadApk`/`downloadAndInstallApk`, and `crypto` is linked
    in); we sign with Gradle and publish no digest anywhere; adopt a published
    `apk_sha256` in the remote config, because a sideloaded build with no stated
    digest is indistinguishable from a tampered one. *Caveat, stated rather than
    assumed:* the binary proves the screen exists, not what it verifies.**
17. **They do Firebase Remote Config *and* their own `r.txt`, i.e. two control
    planes; we have exactly one (`admin_panel` → `remote_config()`); adopt
    nothing, and consider it evidence that ours is the right architecture — their
    own duplicated failover host in §2 shows the cost of running two.**

---

## 9. Where RzFlix gets its links — the direct answer

**Upstream catalog: `dataapi.yomoviesapk.com`** (the `yomoviesapk.com` family,
plus `mainapi.yomoviesapk.com/r` as a second literal), driven by
`api.ringzstudio.com/apis/r.txt`, with playback wrapped through
**`rzflix.com/?s=<server>`** and live TV pulled from public GitHub M3U repos.

**Is it already one of our sites? No.** Checked against
`Fast_Fetch/SITES.md` and `Fast_Fetch/importers/`: the yomovies family is not
listed (we have `moviesmela`, a different site) and neither is `rzflix.com`. Two
things follow:

* `dataapi.yomoviesapk.com` is **not scrapable by us as configured** — it 403s at
  Cloudflare Access for an anonymous caller. An importer would be a credential
  replay, which is out of scope and out of bounds. It is a feed to *subscribe to*
  only with its owner's permission, which we do not have.
* `rzflix.com/?s=<server>` is the actual public HTML surface — the same class of
  target as the embed wrappers `host_resolvers.py` already unwraps for us. That
  is where any future work would sit, and it needs its own measurement before any
  import code is written.

**The transferable finding is the architecture, not the endpoint:** a flat
JSON-per-rail catalog behind a config file that also carries the kill switch, the
server flags and the ad cadence. That is buildable inside our existing stack
(§8 items 1–7, 12) without touching anyone's service.

---

## 10. Design brief for a new importer: `fzmovies.host`

Written as the brief for the next gate; the code that implements it is
`Fast_Fetch/importers/import_fzmovies.py` with
`Fast_Fetch/importers/test_import_fzmovies.py` (69 offline tests). Two requests
only: the homepage (19,751 B) and one item page (50,978 B), hosts printed,
`-m 15`.

**Site class.** Not WordPress, no REST layer, no sitemap claimed. A flat PHP
catalog where every surface is a query string on a bare filename — the same
shape class as `pagalmovies`/`mp4moviez`, so the house "listing rails → item
pages" importer contract applies rather than the WP-family one.

**Entry points (rails), each measured on the homepage:**

```
movieslist.php?catID=<1|2|3>&by=<latest|date|rating|downloads|alpha>
    catID 1 = Bollywood Movies, 2 = Hollywood Movies, 3 = Hollywood Dubbed
hotmovies.php?catID=2 · genre.php?catID=2 · alpha.php?catID=1|2
imdb250.php · oscars.php · filmfare.php
```
Availability is uneven and was recorded, not assumed: `hotmovies.php` and
`genre.php` appear for catID=2 only; `by=downloads` for catID 1 and 2 only; the
dubbed rail spells its A–Z index `movieslist.php?catID=3&by=alpha`, not
`alpha.php?catID=3`. Facet rails exist too (`year.php?catID=&year=`,
`starcast.php`, `director.php`, `movietags.php`, `movieseries.php`,
`userlists.php`, `moviequotes.php`, `advancedsearch.php`) and are cheap crawl
seeds later. **Unknown: total item count and whether any rail paginates** — no
listing page was fetched, so the importer claims neither.

**Item page shape.**
`movie-<Title>--hmp4.htm` with `%20` on a listing page and *literal spaces*
inside the item page, plus a second naming class on the dubbed rail —
`movie--Dubbed--The Tiger Rising [Hindi].htm` — which has no `--hmp4` tail and no
year. `movie-…--subtitle.htm` is the same shape and is **not** a work. `<title>`
is `The Break-Up 2006 (2006)`; there is no `og:*` block and no JSON-LD, but the
page is a complete `itemtype='http://schema.org/Movie'` microdata tree: `name`,
`description`, `image`, `genre`, `tag`, `sameAs` (the IMDb URL, hence the `tt…`
id), nested `actor`/`director` Person blocks, `datePublished`/`dateModified`, and
`url` per release. Plain text around it carries `Runtime:`,
`IMDb Rating: 5.8 … /10 (148862 votes)` and `Downloads: 41621.5`.

**Link/embed shape — the part that needs care.** A release row is one anchor:

```
href    = download1.php?downloadoptionskey=3-10504-6de26004dc76…   (no token)
onclick = window.location.href="download1.php?…&pt=jRGarGzOo2"     (visitor token)
text    = "The Break-Up 2006 BluRay 480p.mp4"                      (label metadata)
next    = <dcounter> (284 MB) { 34466 hits }</dcounter>            (size, popularity)
siblings= mediainfo.php?downloadoptionskey=<same key> · ss.php?downloadoptionskey=<same key>
```
Four consequences, all implemented: match `href` only from the attribute list (a
naive `href=` search finds the JavaScript copy and stores visitor state as the
link); keep the options key and drop `pt=` (the stored URL must not expire with
the page view, and must not carry someone's session material); read size and
hits from the **following** `<dcounter>`, not from the label; treat
`mediainfo.php`/`ss.php` as derivable evidence pages, never fetched.
`download1.php` is a **same-site redirector to an unknown final URL** — so every
row is `playback_type='redirect'`, `status='unverified'`, `is_temporary=1`, and
the module deliberately has no `--resolve-links`. Nothing routes a viewer through
a link shortener; that family is retired project-wide.

**Adult signal.** No adult section observed on the site; `is_18_plus` is
keyword-derived from title and link text with `looks_adult()` erring toward
flagging, per the AGENTS.md law (stored, never displayed; `redact.adult_clause`
does the hiding). Two known limits recorded in the importer: the site's own
`sex`-adjacent titles and the uncut/rated distinction mean keyword-only flagging
will over-flag some rows, and the correct fix is per-site authority, not another
`WHERE` clause.

**Staging + gate contract.** Writes only to a per-site staging DB (`fzmovies.db`,
default `/home/ubuntu/radd-stream-data/fzmovies.db`), never to
`merged_catalog_20261025.db` or `fast_fetch.db`; merging stays a separate
operator decision (`merge_catalogs.py`, reads `post_canonical_key`). Idempotent
by `canonical_key`. First 429 pauses the whole run. And the owner's fleet rule is
implemented as code, not prose: `crawl_blocked(loadavg, mem_available_mb,
other_crawlers, limit)` refuses on load ≥ 4.0, MemAvailable ≤ 4000 MB, any other
importer running, or a missing `--limit`.

**Crawl status: deferred.** Measured at decision time and again at write time:
1-min load **6.31–10.7** against the 4.0 ceiling, MemAvailable **4,145–5,532 MB**,
no other importer process. The load condition alone closes the gate, so
`sync` was never run, `import_fzmovies.py gate` exits 3 with
`crawl deferred, gate conditions not met`, and **zero fzmovies item pages beyond
the two measured fixtures are in the database — there is no staging DB yet.**

**Queued heavy action (for a quiet window, do not run at load > 4):**
```
python3 -S Fast_Fetch/importers/import_fzmovies.py sync --limit 200 --delay 1.5 \
  --db /home/ubuntu/radd-stream-data/fzmovies.db --rails hollywood bollywood dubbed
```
Expected cost: ~202 HTTP requests over ≥ 5 minutes at 1.5 s delay, one PHP page
parse each (10–60 KB, no DB scans), peak RSS well under 100 MB, and a staging
database of roughly 200 rows plus their releases. Number wanted from it: how many
item pages each rail actually yields, and whether any rail paginates — the two
facts this brief cannot claim.

---

## 11. What this analysis did **not** establish

* The wire format of `appTkn`/`secKey`, and therefore the real request shape of
  the yomovies data API. Statically invisible; not attempted.
* The JSON field names of a live rail file. §5 is inferred from class names.
* Whether `download1.php` still resolves, what it redirects to, or whether those
  keys expire. Never followed.
* Any count on fzmovies: item total, rail pagination, per-language depth.
* Whether RzFlix's own upstream is *itself* scraping fzmovies or an unrelated
  provider — no evidence either way in the binary.
* Any dynamic behaviour: no emulator, no device, no Frida, no proxy, no request
  from the app.
