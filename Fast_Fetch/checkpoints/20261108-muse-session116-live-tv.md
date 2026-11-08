# Session 116 — Live TV tab (2026-11-09 ~00:09–00:45 PKT)

**What:** the user-ordered Live TV tab (00:09 PKT 2026-11-09: "add live tv
channels such sports channels some news channels… use the best possible
layout… keep our video player same"). Research first, then build, in the
fresh clone `/tmp/live-tv-work` on branch `session116-live-tv` from
`39bcaf96`. The player is untouched by design — `git diff` shows zero
player files — and Live TV plays through the exact player route a movie
uses, addressed by a signed handle.

## Phase 1 — research

### 1a. App code search: no live TV existed

Greps for "live tv" / "LiveTV" / "live-tv" / "live channel" across the App
found nothing except an unrelated test comment in
`Fast_Fetch/test_api_v2.py:2034`. "channel" hits in the App are payment
channels (JazzCash/EasyPaisa/Raast), audio channels
(`PlayerViewModel.setMaxAudioChannelCount`), or the broadcast comment in
HomeScreen. No Live TV tab, no channel list, no TV streams — build proceeds.

Navigation pattern found (`NavGraph.kt`, `PanelTabs.kt`, `Screen.kt`): the
bottom bar has 4 tabs (Home, Search, My List, Settings) via
`PanelTabs.resolve(tabs, features.search)`; the operator's `tabs` tuning key
is authoritative, Home is always first, Search only when its feature flag is
on, routes stay registered even for hidden tabs. `PanelTabs.DEFAULT` is the
4-tab fallback; `KNOWN = DEFAULT.toSet()`. Tab icons are the stroke set
(`ic_tab_home.xml` etc. — stroke-black, no `?attr/colorControlNormal` tint;
the NavigationBarItem tint recolours them). `Screen.Player` is
`player/{streamId}/{title}` — addressed by the server's OPAQUE STREAM
HANDLE, never by a URL.

Player reuse path confirmed (`PlayerViewModel.startStreamHandle`, ~line
665): it first checks `store.peekDirectUrl(streamId)`, else builds
`streamRedirectUrl(apiProvider.currentBaseUrl(), streamId)` — the player
opens OUR `/api/v1/stream?id=<handle>` URL directly as the ExoPlayer source
and follows the 302. So a signed live-TV handle flows through the exact same
path: navigate to `Screen.Player.createRoute(handle, channelName)`.

### 1b. Online research: iptv-org is the canonical source

- **iptv-org** (github.com/iptv-org): open-source, ~12,854 channels across
  250 countries, public-domain database, playlists by country
  (`iptv/countries/pk.m3u`, `in.m3u`) and by category
  (`categories/news.m3u` ~930 channels, `categories/sports.m3u`). Policy:
  only streams broadcasters themselves publish to the open internet; no
  video stored in the repo; NSFW stopped 2024-01-30. Quality varies; some
  geo-blocked/offline. Same database powers TVAtlas (12,655 channels;
  **Pakistan 121 channels, India 806 channels**).
- **Pakistani sports rights** (wheresthematch.com): official sports
  broadcasters in Pakistan = Geo Super, PTV Sports, TEN Sports, A Sports;
  India = Star Sports, Sony, DD Sports, Amazon Prime Video, FanCode,
  Eurosport India. These are pay channels — their "live" streams on random
  apps are typically pirated rebroadcasts. Official free sports streams are
  scarce; **DD Sports (India, state-owned free-to-air) is the clean
  exception**.
- **Layout consensus** (TIVRA, Forge TV, Tablo): category-first
  (Sports/News/Movies/Kids/…), channel grid with logos, favourites +
  recent, search within channels, EPG time-grid on TV but on mobile a
  category list + channel rows with now/next. TIVRA mobile: five bottom tabs
  incl. "Live" with Live/Guide sub-tab. Tablo's Category View groups
  channels by category instead of channel number.
- **FAST services** (Pluto TV, Tubi, Plex): geo-blocked / login-gated for
  PK; NOT used. **YouTube live** (Geo News, ARY News stream live on
  YouTube): NOT used for v1 — playing YouTube needs server-side HLS
  extraction (yt-dlp, not stdlib) and the app cannot play a YouTube page URL.

### 1c. VM probes: 35 PLAY, 18 DEAD

Playlists fetched from the Oracle VM 00:11 PKT 2026-11-09: `countries/pk.m3u`
105 channels, `countries/in.m3u` 849, `categories/sports.m3u` 502,
`categories/news.m3u` 1056. A 53-channel shortlist was probed with curl
(12 s, follow redirects, require HTTP 200 + `#EXTM3U`) + ffprobe (25 s,
confirm real video). Full probe record:
`~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/live-tv-probes-20261109.txt`
(89 lines).

**Probe-script bug, caught and fixed mid-run:** the first run reported 0
PLAY / 36 PLAYLIST-ONLY because ffprobe csv prints
`codec_name,codec_type,width,height` (`h264,video,1920,1080`) and the script
checked `s.startswith("video")`. Fixed to check field 2, re-probed the 36 —
**35 PLAY, 1 PLAYLIST-ONLY**. Al Jazeera English was confirmed by direct
ffprobe first (h264 up to 1920x1080 + aac, rc=0).

**PLAY (35)** — name (basis, max width): Dunya News (official, 720p),
24 News HD (aggregator, 360p), Such TV (unknown, 1080p), News One
(aggregator, 720p), KTN News (aggregator, 360p), Hum TV (aggregator-cdn,
720p), Bol Entertainment HD (aggregator, 720p), 8XM (aggregator, 360p),
M Sports (unknown, 1080p), PK Sports (aggregator, 720p), Madani Channel
Urdu (official, 720p), Peace TV Urdu (unknown, 1080p), Cartoon Network
Pakistan (aggregator, 720p), Discover Pakistan (channel-cdn, 1080p),
NDTV 24x7 (aggregator, 720p), DD News (public-broadcaster, 360p),
DD News HD (fta-aggregator, 1080p), Aaj Tak HD (official, 1080p),
India Today (official-group, 720p), Zee News (unknown-cdn, 1080p),
Times Now (official-group, 720p), DD Sports (public-broadcaster, 1080p),
Eurosport India (official-cdn, 720p), DD National HD (fta-aggregator,
1080p), DD India (fta-aggregator, 1080p), Al Jazeera English (official,
1080p), Al Jazeera Arabic (official, 1080p), ABC News (official, 720p),
DW English (official-playout, 1080p), France 24 Arabic (official, 1080p),
Euronews English (aggregator, 720p), Africanews English (official, 720p),
CNA Singapore (official-geoblocked, 1080p — plays from the Mumbai VM
despite the playlist's geo-blocked tag), FIFA+ (aggregator, 720p),
FUEL TV (official-fast, 1080p).

**DEAD (18):** 92 News HD (404), ARY News (403 — Tamasha auth wall),
Hum News (400), Samaa TV (000), PTV News (000), 7 News (404), Aaj News
(400), Suno News HD (000), Public News (000), Neo News (000), A-Plus TV
(400), Express Entertainment (000), ARY Musik (403 — signed URL expired),
PTV Sports (000), Ten Sports Pakistan (000), Kids Zone (000),
Fight Network (000), **Republic TV** (master playlist fetches, but its
variant URLs 404 — the session path in the playlist is expired/rotated;
verified by direct ffprobe on a variant URL).

**Known gaps, stated plainly:** NO Pakistani sports channel qualifies for
v1 — PTV Sports / Ten Sports are aggregator-IP restreams and dead from the
VM; Geo Super has no public HLS in iptv-org at all. Geo News is NOT in
iptv-org's PK list (its official stream is YouTube / geo.tv). The big
Pakistani news brands are mostly dead too (92 News 404, ARY 403, Hum/Samaa/
PTV News connection failures — the shared aggregator host 103.250.28.74 is
down from the VM). **Geo caveat:** probes ran from the Mumbai VM (India
IP). A stream geo-blocked in India but open in Pakistan (or vice versa) is
misjudged from here — prefer globally-open streams; Pakistan-side
accessibility is unproven for every channel, and the server-side liveness
probe cannot prove client-side playability for a geo-gated stream (the 302
goes to the user's device, which fetches from Pakistan).

## Phase 2 — design (written before coding)

- **Channel data: server-side registry** (`Fast_Fetch/live_tv_registry.json`,
  modelled on `domain_registry.json` v2.0), served by
  `GET /api/v1/live-tv/channels`, so channel URLs stay out of the app bundle
  and the admin panel can control them later (one registry edit enables /
  disables a channel; the loader re-reads on mtime change, no restart).
  Channel entry: id, name, category, country, language, logo_url,
  stream_url (HLS), source basis, verified_at, enabled, disabled_reason.
- **Seeding rule:** all 35 PLAY channels are seeded; `enabled=true` only
  for broadcaster-published bases (official, official-group,
  official-playout, official-fast, official-cdn, public-broadcaster,
  channel-cdn, official-geoblocked) = **17 enabled**. The 19 verified-playing
  third-party restreams are seeded `enabled=false` with the reason
  "third-party restream, not broadcaster-published — needs owner call", so
  the endpoint hides them until an operator enables them. The endpoint
  serves only enabled channels; the stream route 404s disabled/unknown ids
  identically.
- **Handles:** `redact.py` TV handle pair, version byte 5, tag domain `b"tv"`,
  body = channel id + expiry (24 h TTL, same as a movie handle):
  `mint_live_tv_handle` / `parse_live_tv_handle`. No other handle kind
  parses as a TV handle and vice versa (version byte + tag domain).
- **Stream route:** in `viewer.py` `/api/v1/stream`, the TV-handle check
  runs FIRST (on the public port `parse_token` runs `signed_only`, so a TV
  handle would 400 if it ever reached the movie branch). On success the
  channel is looked up and its playlist is probed (GET, 5 s, require 200 +
  `#EXTM3U` — the same bar the VM probes used); live → 302 to the HLS URL
  with `Cache-Control: no-store`; dead → 404 `no_playable_source`; unknown /
  disabled → 404 `not_found`. The adult check and the quality gate are
  skipped for TV entirely: the registry is curated free-to-air broadcast
  with no adult category and no 1080p/4K premium distinction.
- **Layout chosen: category-first channel grid** — the consensus across
  TIVRA (mobile Live tab), Tablo (Category View) and Forge TV, and the fit
  for OUR app (tabs control + Home structure + brand): a Live TV bottom tab
  opening a screen with horizontal category chips (All + the categories the
  endpoint actually serves) + a logo channel grid (`LazyVerticalGrid`, same
  as BrowseScreen/MyListScreen, same `CatalogGridColumns`) + in-screen search
  by channel name + a LIVE badge on each card; tap a channel → the existing
  Player. NO full EPG time-grid in v1 (no EPG data source is wired; a grid
  of invented times would be a lie), NO favourites in v1 (favourites are a
  posts system, not a channels system).
- **Dead-channel honesty:** a dead channel never fakes a play — the stream
  route 404s before the player ever sees a URL, and the tab shows an honest
  unavailable/empty state, never a fake list. No raw URLs shown in the UI,
  no host names shown — same rule as movies.
- **Deploy note:** nginx's public allow-list does NOT include the
  `/api/v1/live-tv/` prefix — the gate must add it, same as `/api/v2/play`
  was added in live deploy #1, or the channels endpoint answers 403 in
  public and the tab shows its honest unavailable state.

## What was built

Backend (`Fast_Fetch/`, stdlib only):
- `live_tv_registry.json` v1.0 — 35 channels (14 PK, 11 IN, 10 INTL; news
  21, sports 6, entertainment 3, religious 2, music 1, kids 1, travel 1),
  17 enabled. Enabled by country: PK 3 (Dunya News, Madani Channel Urdu,
  Discover Pakistan), IN 6 (DD News, Aaj Tak HD, India Today, Times Now,
  DD Sports, Eurosport India), INTL 8 (Al Jazeera English/Arabic, ABC News,
  DW English, France 24 Arabic, Africanews English, CNA Singapore,
  FUEL TV). Enabled sports: DD Sports, Eurosport India, FUEL TV. Enabled
  categories: news, sports, religious, travel — entertainment / music /
  kids have NO enabled channel in v1 (Hum TV, 8XM, Cartoon Network Pakistan
  are all restreams, held back).
- `live_tv.py` — registry load (mtime-cached, fail-closed validation:
  unique int ids, known categories, https `.m3u8` stream URLs — plain http
  only on loopback for the test fixture — bool enabled, non-empty source),
  `list_channels` (public projection: no `stream_url`, no `source`; signed
  `stream_id` per channel), `list_categories`, `get_channel` (enabled-only),
  `playlist_is_live` (5 s probe, 200 + `#EXTM3U`).
- `redact.py` — `mint_live_tv_handle` / `parse_live_tv_handle` (v5,
  `b"tv"`, id + expiry, 24 h TTL).
- `viewer.py` — `GET /api/v1/live-tv/channels` (optional `?category=`
  filter; response `{"success", "channels", "categories"}`) + the TV branch
  at the top of `/api/v1/stream` (302 / 404 honest-dead / 404 not-found /
  `redirect=0` JSON shape with `mime_type: application/vnd.apple.mpegurl`).
- `test_live_tv.py` (NEW module, registered as a 🧪 step in
  `backend-ci.yml` → 57 steps): 26 tests — registry validation (duplicate
  id, unknown category, plain-http URL, non-playlist URL, empty list,
  missing file), projection (enabled-only, no upstream URL/source leak,
  handle round-trip, category filter, unknown category → []),
  channels endpoint through a real `viewer.make_server` socket server
  (list all, `?category=sports`, body contains no `.m3u8` / `127.0.0.1`),
  stream route through the same server to a loopback fake playlist server
  (live → 302 + `Cache-Control: no-store`, `redirect=0` JSON shape, dead →
  404 `no_playable_source`, disabled/unknown → 404 `not_found`, expired and
  tampered handles → 400), seeded-registry counts (35 / 17, sports = 3,
  enabled sources all official-basis).
- `test_redact.py` — 1 new test: TV handle round-trip + expiry + tamper +
  wrong secret + no confusion with movie / credit / VIP-pass handles
  (test_redact 80 → 81 OK).

App (Kotlin/Compose, player untouched):
- `network/models/LiveTvWire.kt` (NEW) — `LiveTvChannel` (id, name,
  category, country, language, logoUrl, streamId) + `LiveTvChannelsResponse`
  (success, channels, categories). No `streamUrl`/`source` field exists, so
  an upstream address cannot be carried by the wire type.
- `network/RaddStreamApi.kt` — `GET api/v1/live-tv/channels` (optional
  `?category=`).
- `repository/CatalogRepository.kt` — `getLiveTvChannels(category)`.
- `ui/navigation/Screen.kt` — `Screen.LiveTv` (`live_tv`).
- `ui/navigation/PanelTabs.kt` — `DEFAULT` is now the five tabs
  (`home, live_tv, search, my_list, settings`); `KNOWN` follows. Live TV is
  NOT gated by the search flag.
- `ui/navigation/NavGraph.kt` — "Live TV" bottom item with the new
  `ic_tab_live_tv` icon; `composable(Screen.LiveTv.route)` navigates to the
  EXISTING `Screen.Player.createRoute(streamId, title)` — the same call
  Detail/Downloads use. No player file edited.
- `ui/screens/LiveTvScreen.kt` (NEW) — Scaffold + "Live TV" TopAppBar,
  search field, category FilterChips (All + served categories), logo grid
  (`CatalogGridColumns`, `CatalogImage` 16:9, LIVE badge), loading skeleton,
  honest error state with retry, honest empty states. No raw URL, no host
  name anywhere.
- `viewmodel/LiveTvViewModel.kt` (NEW) — one server fetch, then client-side
  category + name filtering (the list is 17 rows; the endpoint's
  `?category=` stays available for a larger list later);
  `friendlyNetworkError` on failure, `CancellationException` rethrown.
- `res/drawable/ic_tab_live_tv.xml` (NEW) — TV-set icon in the brand stroke
  set (strokeWidth 2, stroke-black, no tint attr; parses as XML).
- Tests: `ModelsTest` +2 (rule 7 — full wire decode incl. snake-case names
  and the no-`streamUrl`/`source` field assertion; empty-object defaults);
  `PanelTabsTest` updated (fallback is now the shipped five) +1 (live_tv
  resolves from the operator list, not gated by search).

Pre-push Kotlin checks: full import diff base→HEAD for every edited Kotlin
file — additions only, nothing dropped; @Composable counts unchanged
(NavGraph 1, LiveTvScreen 2 new); `/*` vs `*/` balance clean everywhere —
one real catch fixed before committing: the RaddStreamApi KDoc originally
wrote `` `/api/v1/live-tv/*` ``, whose `/*` would have opened a nested
Kotlin block comment inside the KDoc (33/33 base → 35/34); reworded to "the
`/api/v1/live-tv/` prefix" (34/34) and the same string reworded in the
viewer.py comment. Every new import is used. No local Gradle run by owner
order — Android CI is the verification path for the app half.

## Checks

- `test_live_tv.py`: 26 OK (21.1 s, loopback fixture only, no network).
- `test_redact.py`: 81 OK.
- `live_tv.py` standalone: registry loads (35 / 17), first enabled channel
  probes live in 4.49 s; sports filter = DD Sports / Eurosport India /
  FUEL TV; projection leaks no `stream_url` / `source`.
- Full backend gate on `/tmp/live-tv-work`: **53/53 PASS, FAILED MODULES: 0**
  (364 s; gate reads the module list from `backend-ci.yml`, now 53 with
  `test_live_tv.py` included; 57 🧪 steps) + the 4 importer modules solo
  OK (13 / 7 / 18 / 53) + `test_docs_invariants.py` OK (CONTINUITY count
  113 verified against the checkpoint listing).
- Android CI: NOT run locally (owner order) — parent runs CI after landing.

## What is NOT built yet

- EPG (now/next, time-grid): no EPG data source wired; iptv-org has an EPG
  repo but it is a second integration, not faked here.
- Favourites / recently-watched for channels: favourites are a posts
  system; a channel-scoped one needs a small new store.
- Pakistani sports (PTV Sports, Ten Sports, Geo Super) and Geo News:
  no official public HLS exists in iptv-org; the restreams that do exist
  are dead from the VM. Filling these needs either a broadcaster-published
  stream (none found) or an owner call to seed the verified-playing
  restreams (Hum TV, NDTV 24x7, DD National HD, Zee News, etc. — 18 held
  channels are already in the registry, disabled, one edit from live).
- YouTube-live channels (Geo News, ARY News): needs server-side HLS
  extraction (yt-dlp, not stdlib).
- Pakistan-side playback verification: unproven for every channel
  (probes ran from the Mumbai VM); the in-app failure path is the honest
  one if a geo-gated channel 404s for a PK user.
- Admin-panel control of the registry: the registry is a file the operator
  edits today; no panel UI yet.
- Live deploy: NOT done — this commit only. The gate must add the
  `/api/v1/live-tv/` prefix to the nginx public allow-list, then the parent
  runs the gate (backup + live tree ff + restart + live proofs).

## Live-proof plan (for the parent, after the gate deploy)

1. `GET https://raddstream.duckdns.org/api/v1/live-tv/channels` → 200,
   17 channels, categories `["news", "religious", "travel", "sports"]`,
   no `.m3u8` anywhere in the body.
2. `?category=sports` → exactly DD Sports, Eurosport India, FUEL TV.
3. Press a served `stream_id` at `/api/v1/stream?id=…` (no-follow curl) →
   302 to an HLS playlist; `ffprobe` the Location to confirm real video.
4. Press a disabled channel's handle (mint one from the registry id, e.g.
   Hum TV id 6) → 404 `not_found`.
5. App: Live TV tab shows (5th tab), channels load, tap Al Jazeera English
   → the existing player opens and plays; tap a geo-blocked channel in
   Pakistan → the player's honest unavailable state, never a spin.
