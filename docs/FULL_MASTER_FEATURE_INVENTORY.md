# FULL MASTER FEATURE INVENTORY

**Project:** `radd-stream` (Python/stdlib backend + Kotlin/Compose/Media3 Android client)
**Compiled:** 2026-10-27 · **Amended:** 2026-10-27 after a call-site (not just symbol) audit — see §18.1
· **Re-measured 2026-10-29 21:40.** Four figures in this file were wrong against the code as it stands
today and are corrected in place, each row marked with its old value: B-SEC-08 called the sync-key
digest "PBKDF2-style" when `accounts.py:593-624` stores **one unsalted SHA-256, prefix-tagged** (and
the app derives that key from a phone number — see `docs/IDENTITY_AND_TRIAL_ABUSE.md`); the admin
setting count is 17, not 15; and the Android test file/annotation counts are 81/637, not 47/381.
The shortener row was also restated, because "server ✅" is true of the code and false of the policy.
Everything else in this appendix is still a 2026-10-27 measurement and should be re-checked before
being quoted.
**Mandate:** exhaustive archaeology of every feature, mechanism, earning trick, UI requirement and
search capability ever specified for this project, cross-referenced against the code that exists
today, with build specifications for everything still missing.

**Sources read for this inventory**

| Source | Role |
|---|---|
| `Fast_Fetch/CHAT_HISTORY.md` (101,915 lines / 5.2 MB) | full conversational archive, 2026-10 onwards |
| `Fast_Fetch/DAO.md` | eternal mission, multi-source redundancy, local-AI law |
| `docs/MASTER_ARCHITECT_DIRECTIVE.md` | 302 handoff, staging isolation, redaction, federation, FTS5, Netflix/MX parity |
| `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md` | features A–I, Desi Cine-Finder, player requirements |
| `docs/MASTER_ADMIN_MONETIZATION_SPEC.md` | admin tables, payments, ads, shorteners, VIP matrix |
| `App/docs/PLAN.md` | phased app roadmap |
| `docs/PAKISTAN_OPERATOR_GUIDE.md` | Lahore operator context, rails, approval flow, growth |
| `docs/QODER_MASTER_EXECUTION_PROMPT.md` | Tasks 1–8 execution contract |
| `docs/ARENA_ROUND_1_PROPOSALS.md` | AI-generated growth/monetization proposals |
| `docs/OPENROUTER_PURE_CODE_AUDIT.md` | external audit recommendations |
| `docs/SITE_SCOUT_SPEC.md` | scraper-synthesis engine design |
| `App/docs/PLAYER_SPEC.md`, `App/docs/CACHE_SPEC.md` | player parity + offline cache contracts |
| `docs/PROJECT_MAP.md`, `docs/SESSION_CHECKPOINT.md` | cross-agent state |
| `Fast_Fetch/API_V2.md`, `ANDROID_INTEGRATION.md`, `DATABASE_SCHEMA.md` | wire/data contracts |
| `brand.properties` | single-file brand + feature flags + limits |
| Code: `Fast_Fetch/**`, `App/app/src/main/**`, `App/app/src/test/**` | ground truth |

---

## 0. How to read this document

### Status legend

| Status | Meaning |
|---|---|
| ✅ **FULL** | Implemented end-to-end in code, covered by offline/JVM tests, no known wiring gap. |
| 🧪 **FULL–DEVICE-UNVERIFIED** | Implemented and compiled; behaviour requires a real Android device/emulator (no KVM here). |
| 🟡 **PARTIAL** | A working slice exists, but a named piece is absent or disconnected. |
| 🧩 **LOGIC-ONLY** | Pure decision logic + tests exist; nothing calls it in the shipped flow. |
| 🏗 **DESIGN** | Spec/proposal only; no implementation. |
| ❌ **MISSING** | No code, no spec, or spec explicitly deferred. |

### Verification tiers used in the evidence column

- **T1** — code read + offline/JVM test exists (strongest available without a device).
- **T2** — code read + compiled by CI/`assembleDebug` at some recorded point; no device run.
- **T3** — code read, no test and no runtime harness.
- **T4** — documentation/spec only.
- **D** — **deployment dependency**: the code exists but the live host/route/data is not configured to
  make it reachable.

### Honesty rules applied

1. "Built" never means "verified on a phone". No Android device or emulator (no KVM) was available.
2. "Verified" backend means the module and its offline tests exist; the full suite was *not re-run*
   during this audit. Latest recorded run in `docs/SESSION_CHECKPOINT.md` is green.
3. Any claim that a feature works in production must survive §24 (deployment truth). Several
   fully-built capabilities are unreachable through the documented nginx allowlist.
4. No credential values appear in this file. Where a security issue exists, the risk is described
   without reproducing the value.

### Repository state at compile time

- `HEAD = 27fc043` ("feat(app): make every preference real, add the sync-account client, verify the
  build here"), branch `master`, **working tree dirty with 105 modified/untracked paths** from prior
  sessions. This document adds one path and touches no code.
- Android sources: 132 Kotlin files / 29,981 lines.
- Android tests: 47 test files, 46 with `@Test`, **381 JVM tests**.
- Backend tests: **44 `test_*.py` modules, 1,039 `def test_` functions**.
- Backend importers: **18** site modules.
- Last recorded build: `assembleDebug` green, debug APK 23,128,096 bytes (2026-10-27 01:58). This
  audit did not rebuild.

---

## 1. Executive result

| Domain | Fully built | Partial | Missing / design |
|---|---:|---:|---:|
| Catalog ingestion & merging | 9 | 2 | 3 |
| REST v1 + streaming | 13 | 2 | 1 |
| Provenance / security / adult rules | 9 | 1 | 2 |
| API v2 projection surface | 7 (code) | 3 | 2 |
| Accounts / sync | 6 | 3 | 2 |
| Admin / remote control | 6 | 2 | 3 |
| Monetization / payments / ads | 4 | 3 | 8 |
| Ops / backups / scheduling | 6 | 2 | 3 |
| Android shell / navigation / branding | 10 | 3 | 5 |
| Player (MX parity) | 23 | 10 | 10 |
| Subtitles / audio | 9 | 2 | 4 |
| Offline cache | 9 | 6 | 1 |
| Downloads | 6 | 1 | 3 |
| LAN / P2P sharing | 3 | 2 | 4 |
| Search & discovery | 3 | 2 | 8 |
| Local media / reverse search / fingerprint | 0 | 0 | 4 |
| Growth / federation / AI tooling | 3 | 2 | 6 |

**Headline findings**

1. The backend is far more complete than its own `PROJECT_MAP.md` says: `/api/v1/download`,
   `/api/v1/art`, `/api/v1/app/remote-config`, the two-port split, the shortener waterfall, accounts,
   admin, v2 routes, link health and backups all exist.
2. The documented **nginx allowlist blocked the very routes the app needs** (`/api/v1/posts/{id}`,
   `/api/v1/stream`, `/api/v1/download`, `/api/v1/app/remote-config`). That is no longer true on the
   live host: all four answer on the public port as of 2026-10-27, and `/api/v1/posts/{id}` is served
   by the `/api/v1/posts` prefix location. `/api/v1/art` is still denied — and that one is immaterial,
   because `poster_url`/`backdrop_urls` in a projected row are upstream CDN addresses (TMDB,
   Amazon) and no Kotlin source references `/api/v1/art` at all. The reference block in
   `ORACLE_DEPLOYMENT.md` ("Reference deployment configuration": `location = /api/v1/posts`,
   `location = /api/v1/stats`, everything else under `/api/` denied, and line 455 saying so outright)
   is what the caveat was about, and it is now superseded by
   `/etc/nginx/sites-enabled/radd-stream` on the live host.
3. Three of the brief's named capabilities — **click-to-search from a user device**, **local device
   media scanning**, and **audio-fingerprint matching** — have **zero origin** in any directive or
   chat message. They are not half-built; they were never specified. **Reverse search** does exist as
   a detailed proposal (Clip & Scene Finder), never implemented.
4. "Audio track matcher" in the code is a **language-track selector** (`AudioTrackMatcher.kt`), not
   acoustic fingerprinting. The archive explicitly rejected Shazam-style audio recognition for movie
   identification.
5. Monetization is mostly **UI + configuration**, not a transaction system. That was the honest state
   and it has moved: a payment ledger, an operator approval write and the `vip_until` mutation it
   implies now exist (§M-MON-01, `Fast_Fetch/payments.py`), and `/api/v1/download` now has a route
   that can mint the capability a redirect can carry (§P-B-03). What still does not exist is an **ad
   SDK**, and the app's download path still bypasses the shortener route entirely — **now by choice**:
   the owner kept the resumable byte pipe on 2026-10-27, for the reason in §M-MON-04, so free-tier
   shortener revenue is a stated zero rather than an oversight.
6. A second, deeper wiring pass (recorded in §18.1) moved **eleven capabilities out of "fully built"**.
   They compile and are unit-tested, but the shipped flow never calls them: playhead reporting for the
   ahead-cache, stay-forever keeps, local playback of kept files, binge byte prefetch, cross-file next
   episode, ad breaks, the LAN share URL, and the loopback 206 proxy. The distinction between "logic
   exists" and "feature runs" is the single most important caveat in this document.

---

# PART I — 100% FULLY BUILT & VERIFIED

## 2. Backend: catalog ingestion, merging and enrichment

| ID | Capability | Spec origin | Implementation evidence | Proof |
|---|---|---|---|---|
| B-CAT-01 | 18 per-site importers into isolated staging DBs | DAO.md; AGENTS rule 9; `merge_catalogs` docs | `Fast_Fetch/import_{10xflix,7starhd,9xmovies,bolly4u,desicinemas,filmyzilla,hdhub4u,hdtvb,hindilinks4u,katmoviehd,moviezguru,multimovies,rareanimes,rogmovies,ssrmovies,toonworld4all,vegamovies,world4ufree}.py` | T1 — per-site `test_import_*` suites, 18 modules present |
| B-CAT-02 | Staging→unified merge with conflict recording | ARCHITECT §staging | `merge_catalogs.py:244` (`merge_site_db`), `:229` (conflict table) | T1 — `test_merge_catalogs.py` |
| B-CAT-03 | Fleet-wide merge runner | same | `merge_fleet.py:36` | T3 |
| B-CAT-04 | Sitemap delta sync per site/all | ARCHITECT; `SITES.md` | `fast_fetch.py sync --site …`; `sitemap_cache` table | T1 — `test_sitemap_sync.py` class suites |
| B-CAT-05 | Title cleaning / year extraction / media classification | ARCHITECT; MENTOR §2 | `fast_fetch.py:1613-1622` (`classify_media`); title helpers | T1 |
| B-CAT-06 | Release-label parsing (resolution/codec/HDR/audio/size/scope) | ARCHITECT; `API_V2.md` §5 | `release_descriptor.py:222-369`; `tiers.py:103-330` | T1 — `test_release_descriptor.py`, `test_tiers.py` |
| B-CAT-07 | Link classification (cdn/hls/embed/bridge/download-only/dead) | `API_V2.md` §5 | `release_descriptor.py` classification; mirrored in app `LinkKindClassifier.kt` | T1 |
| B-CAT-08 | TMDB + Cinemeta artwork metadata backfill | MENTOR §2 "TMDB art first"; AUDIT §2 | `backfill_tmdb.py:182-405` (Cinemeta fallback `:221-266`, season posters `:377`) | T1 — `test_backfill_tmdb.py` |
| B-CAT-09 | Animated/anime flag backfill | MENTOR §Priority 5 (anime) | `backfill_animated_flag.py`; `posts.is_animated`, `posts.industry` | T1 — `test_backfill_animated_flag.py` |
| B-CAT-10 | Site Scout: recon, DOM archaeology, poster heuristics, link graph, blueprint + AI scaffold | `SITE_SCOUT_SPEC.md` §1–4 | `site_scout.py:204` (`SiteScout`), `:656` (`PageDigest`), `:819-847` (image scoring), `:916-1040` (scaffold prompt, disciple draft, stdlib/compile gates) | T1 — `test_site_scout.py` |
| B-CAT-11 | Domain-rotation resolver + registry | ARCHITECT multi-domain | `domain_resolver.py:24-127` | T1 — `test_domain_resolver.py` |

**Posture:** 11 items fully built. The staging-isolation rule is enforced by structure and by the
per-site test suite; no importer writes to the unified DB directly.

---

## 3. Backend: REST v1, streaming and resolver

| ID | Capability | Spec origin | Implementation evidence | Proof |
|---|---|---|---|---|
| B-API-01 | Paginated catalog list with server-side facets | ARCHITECT; app Search contract | `viewer.py:2448-2530` (`api_v1_get_posts`); params `q/type/page/limit/full/industry/genre/quality/sort` | T1 — `test_viewer_api.py` |
| B-API-02 | Anime filter fixed server-side | bug report in archive | `viewer.py:2470-2471` (`is_animated=1 OR industry LIKE '%anime%'`) | T1 |
| B-API-03 | Post detail with releases/sources | ARCHITECT | `viewer.py:3054`; detail builder | T1 |
| B-API-04 | **302 redirector streaming (zero video bandwidth)** | ARCHITECT §"302 handoff"; DAO zero-bandwidth | `viewer.py:3069-3128` (`/api/v1/stream`, `send_response(302)` at `:3091`) | T1 — `test_stream_redirect.py` |
| B-API-05 | JIT link resolution / bridge unwrapping server-side | DAO auto-healing | `fast_fetch.resolve_live_source`; selectors in `viewer.py:2685-2760` | T1 |
| B-API-06 | Direct-media-only guard (never "download" HTML) | MENTOR "direct .mp4/.mkv only" | `viewer.py:3138-3146` comment + resolver existence checks; `link_health` sniffing | T1 |
| B-API-07 | Signed opaque link handles | ARCHITECT provenance; `API_V2.md` §16 | `redact.py:818` (`mint_token`), `:826` (`parse_token`), `:856` (`mint_vip_pass`) | T1 — `test_redact.py` |
| B-API-08 | `/api/v1/download` with free-tier shortener waterfall + VIP bypass | MONETIZATION §shorteners/AUDIT §1 | `viewer.py:3129-3202`; `shorten_download_url` `:352`; `request_is_vip` `:388` | T1 — `test_download_endpoint.py` |
| B-API-09 | `/api/v1/art` poster/backdrop serving | ARCHITECT art; brand 400dp hero | `viewer.py:3203`, `_art_pair` `:413` | T1 |
| B-API-10 | `/api/v1/rules` operator-only unwrapping recipes | API_V2 §manual | `viewer.py:2685-2760`; operator-only set `:57-66` | T1 |
| B-API-11 | `/api/v1/app/remote-config` public, token-masked | MONETIZATION §2 | `viewer.py:3209-3223`; `admin_panel.remote_config` `:1208` | T1 — `test_admin_panel.py` |
| B-API-12 | `/api/health-check` + `/api/heal` | DAO auto-healing | `viewer.py:3016`, `:3028` (now writes JSON; the old "never writes a body" bug is fixed) | T1 — `test_link_health.py` |
| B-API-13 | Link health probe: range/HEAD/redirect chain, media sniff, score, EWMA evidence | DAO auto-healing; MENTOR link health | `link_health.py:474` (`probe`), `:694` (`score_link`), `:789` (history merge), `:1014` (`probe_many`); `link_state.py:210-262` | T1 — `test_link_health.py`, `test_link_state.py` |
| B-API-14 | M3U export | ARCHITECT | `viewer.py:3006` | T1 |
| B-API-15 | Adult suppression at every read surface | root AGENTS adult rule | `viewer.py:665,2592,2764-2778`; `api_v2.py:1161`; `catalog_api.py:1420,1746,1801,1875` | T1 — `test_redact.py`, `test_api_v2.py` |
| B-API-16 | Operator/public port split (8081 internal vs 8080 public) | ARCHITECT redaction; `PROJECT_MAP` | `viewer.py:57-73` (`OPERATOR_ONLY_ROUTES`), `start_server` defaults | T1 — `test_viewer_ports.py` (if present) / `test_redact.py` |

**Note on `PROJECT_MAP.md`:** its "verified REST surface" table is stale. It omits `/api/v1/download`,
`/api/v1/art`, `/api/v1/app/remote-config`; its claims that `/api/heal` hangs and `?type=anime`
returns zero rows are no longer true (see §24).

---

## 4. Backend: provenance, security and adult rules

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| B-SEC-01 | Deny-by-default view projection (`VIEWS`) | API_V2 §16.9 | `redact.py:189`, `:645` (`project`) | T1 |
| B-SEC-02 | Provenance text scrubbing (site/hoster/upstream URLs) | ARCHITECT | `redact.py:500` (`scrub_text`), `:473`, `:437` | T1 |
| B-SEC-03 | Brand-shaped token detection + public-edge sweep | ARCHITECT | `redact.py:266`; `sweep_public_edge.py:9-148` | T1 |
| B-SEC-04 | CORS allow-list shared by v1/v2 | API_V2 §16.7 | `redact.cors_headers_for`; `viewer.py:75` | T1 |
| B-SEC-05 | Work/link handle minting for public responses | ARCHITECT | `redact.py:818-886`; `_art_pair` `viewer.py:413` | T1 |
| B-SEC-06 | Adult link suppression by id | root AGENTS | `redact.link_is_adult`; `viewer.py:3076` | T1 |
| B-SEC-07 | VIP capability parsing (bearer account or signed pass) | MONETIZATION | `viewer.py:388-410`; `redact.py:870` (`parse_vip_pass`) | T1 |
| B-SEC-08 | Sync key hashing + attempt throttling | accounts spec | `accounts.py:593-624` (**one unsalted SHA-256, prefix-tagged `sha256:`** — not PBKDF2/bcrypt; `AttemptTracker` `accounts.py:658` is consulted on the *failure* path only, per-IP bucket `account (30, 60.0)` `redact.py:1108`) | T1 — `test_accounts.py`; **open defect: the app derives the key from the phone number, see `docs/IDENTITY_AND_TRIAL_ABUSE.md`** |
| B-SEC-09 | Admin token gate on loopback-only panel | MONETIZATION §admin | `admin_panel.py:19-43,1753-1830` | T1 |

**Two security caveats (do not reproduce values):**
- The admin token is supplied as a **static literal in the systemd unit** rather than read from a
  root-owned file; anyone with unit access has the token. Rotate and load from
  `/etc/radd-stream/admin.env` (0600).
- `auto_crawl_cron.sh` now sources Hugging Face credentials from `/etc/radd-stream/hf.env` or
  `~/.hf_env`; the hardcoded-token finding in `docs/WATCHDOG_AUDIT.md` is fixed in the tree. Verify
  the deployed copy, not just the repo.

---

## 5. Backend: API v2 implementation (code complete, data-dependent)

`api_v2.py` mounts under `/api/v2/` and implements the route set below. The **code** is built and
tested; end-to-end usability depends on the `cat_*` projection existing in the live DB (see §23).

| ID | Route | Evidence | Proof |
|---|---|---|---|
| B-V2-01 | `GET /api/v2/manifest` | `api_v2.py:669-795`; `fast_fetch.py project` builds projection | T1 |
| B-V2-02 | `GET /api/v2/browse` | `api_v2.py` browse route + `catalog_api` | T1 |
| B-V2-03 | `GET /api/v2/search` with FTS5 + LIKE fallback | `catalog_api.py:1098-1260` (`cat_works_fts MATCH`, `:1133`) | T1 |
| B-V2-04 | `GET /api/v2/suggest` | `api_v2.py:1447` | T1 |
| B-V2-05 | `GET /api/v2/works/{key}`, `/episodes/{id}`, `/releases/{id}` | `catalog_api.py:1740-1801` | T1 |
| B-V2-06 | `POST /api/v2/play` — ranked PlayBundle | `api_v2.py:1714`; `tiers.merge` | T1 — `test_api_v2.py` |
| B-V2-07 | `POST /api/v2/links/{id}/report` — dead-link evidence | `api_v2.py:1240-1288`, `:1672` | T1 |
| B-V2-08 | `POST /api/v2/episodes/{id}/offset` — learned pack offsets | `api_v2.py:1823-1840` | T1 |
| B-V2-09 | `GET /api/v2/sync` — revision-keyed delta | `api_v2.py:925-1100` | T1 |
| B-V2-10 | `GET /api/v2/stats` (adult-scoped, unlike v1) | `api_v2.py:797-900` | T1 |
| B-V2-11 | Per-route rate buckets / arity table | `api_v2.py:170-236`, `ROUTE_BUCKETS` | T1 |

**Known code-level gaps inside v2:** none that block the contract; the projection data does.

---

## 6. Backend: accounts and sync

| ID | Capability | Evidence | Proof |
|---|---|---|---|
| B-ACC-01 | Create account, key returned exactly once | `accounts_api.py:303-371`; `accounts.py:546` | T1 — `test_accounts_api.py` |
| B-ACC-02 | Read account / revoke key | `accounts_api.py:267-295` | T1 |
| B-ACC-03 | Favorites add/remove/list (handles only) | `accounts_api.py:267-371`; `accounts.py:419` | T1 |
| B-ACC-04 | Progress put/remove/list with `client_updated_at` conflict rule | `accounts.py:428`; `accounts_api.py` progress routes | T1 |
| B-ACC-05 | Per-account row cap, weak-key refusal, 429 retry | `accounts.py:270-312`, `:619-742` | T1 |
| B-ACC-06 | Work-ref validation against catalog | `accounts.py:259` (`UnknownWork`) | T1 |

**Important:** `user_accounts.vip_until` exists (`accounts.py:416`) and `vip_status()` reads it
(`:822`), but **nothing in the codebase ever writes it**. VIP entitlement can never become true
without the payment/approval work in §18.

---

## 7. Backend: admin panel and remote control

| ID | Capability | Evidence | Proof |
|---|---|---|---|
| B-ADM-01 | Loopback-only `/admin` page + JSON screens | `admin_panel.py:19-105,1753` | T1 |
| B-ADM-02 | Fleet status screen (`/admin/api/fleet`) | `admin_panel.py:150` | T1 |
| B-ADM-03 | Monetization settings row (single row, id=1) | `admin_panel.py:880-1040` | T1 |
| B-ADM-04 | Save payment/ad/shortener/feature settings | `admin_panel.py:882,1165-1208` | T1 |
| B-ADM-05 | Queue one bounded scraper run | `admin_panel.py:151,1827` | T1 |
| B-ADM-06 | Link-evidence write (`POST /admin/api/links/{id}/evidence`) | `admin_panel.py:1819-1830` | T1 |
| B-ADM-07 | Remote-config masking of shortener tokens | `admin_panel.py:1208-1275` | T1 |

**Settings fields that exist** (`admin_panel.py:903-919`): JazzCash till/mobile, Easypaisa, Raast,
VIP monthly/yearly, Monetag rewarded zone id, Adsterra banner id, ShrinkMe token, Droplink token,
maintenance mode, APK update URL, and flags `downloads`, `pure_cinema`, `chromecast`.

---

## 8. Backend: operations, backups and background pipeline

| ID | Capability | Evidence | Proof |
|---|---|---|---|
| B-OPS-01 | 6-hour autonomous pipeline (sync → merge → backup) | `auto_crawl_cron.sh` steps 1–3; `radd-autocrawl.timer` | T3 |
| B-OPS-02 | Concurrency lock + yields to manual crawlers | `auto_crawl_cron.sh` header | T3 |
| B-OPS-03 | SQLite safe backup (`VACUUM INTO`/verification) with counts + SHA-256 | `backup_manager.py:37-115` | T1 — `test_backup_manager.py` |
| B-OPS-04 | Backup upload: GitHub Releases | `backup_manager.py:172` | T3 |
| B-OPS-05 | Backup upload: Telegram | `backup_manager.py:237` | T3 |
| B-OPS-06 | Backup upload: Cloudflare R2 (AWS SigV4) | `backup_manager.py:297-376` | T1 |
| B-OPS-07 | Backup upload: Hugging Face dataset repo | `backup_manager.py:384-488` | T1 |
| B-OPS-08 | Code snapshot alongside data | `backup_manager.py:488` | T3 |
| B-OPS-09 | Public-edge provenance sweep CLI | `sweep_public_edge.py` | T1 — `test_sweep_public_edge.py` |
| B-OPS-10 | Arena model tournament (OpenRouter) | `arena_tournament.py:18-62`; key from env/file | T3 |

**Not in the pipeline:** `fast_fetch.py project` (the `cat_*` rebuild) is **not** called by
`auto_crawl_cron.sh`. The cron merges the ledger but never refreshes the v2 projection — a core
reason v2 routes answer "unavailable". This is a one-line fix (§22, P0-3).

---

## 9. Android: shell, navigation, branding, settings

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| A-UI-01 | Single-activity Compose app with 11 routes, start destination from stored server URL | PLAN | `ui/navigation/Screen.kt:9-74`; `NavGraph.kt:109-222`; `MainActivity.kt:75-86` | T2 |
| A-UI-02 | Bottom bar Home/Search/My List/Settings | PLAN | `NavGraph.kt:58-70` | T2 |
| A-UI-03 | Deep links `browse/{type}` and `detail/{id}` | PLAN phase 3; QODER Task 1? | `NavGraph.kt:137,190`; manifest `${brandScheme}` + `autoVerify` | T2 |
| A-UI-04 | Single-file re-skin (`brand.properties` → BuildConfig/resources/assets) | ARCHITECT brand | `App/app/build.gradle.kts:140-266`; `Brand.kt`; `BrandDriftTest` | T1 — `BrandDriftTest` (9) |
| A-UI-05 | Dark "Undertow" + light "Daybreak" themes, optional dynamic colour gated by brand | ARCHITECT; MENTOR | `ui/theme/*`; `MainActivity.kt:123-124` | T2 |
| A-UI-06 | Setup screen: server URL, test, save, prefilled default | PLAN phase 1 | `SetupScreen.kt:106-113`; `SetupViewModel.kt:31` | T2 |
| A-UI-07 | Home hero carousel (6 items), rails, skeletons, refresh | MENTOR §2; ARCHITECT Netflix UI | `HomeScreen.kt:65,119-149`; `HeroCarousel.kt` | T2 / T1 — `HeroCarouselTest` |
| A-UI-08 | Continue-watching row merged from local history + synced progress | MENTOR; PLAN "continue watching" now built | `HomeScreen.kt:129-140`; `HomeViewModel.kt:121-140` | T2 |
| A-UI-09 | Force-update dialog from `apk_update_url` | MONETIZATION remote control | `HomeViewModel.kt:65-77,156-167`; `HomeScreen.kt:156-163` | T2 — `AppUpdateTest` |
| A-UI-10 | Detail page: hero art, synopsis, print summary, seasons, episodes, pack banner, quality ladder, play/download/external/share/favorite | MENTOR §2; PLAYER_SPEC §3 | `DetailScreen.kt:277-985`; `DetailViewModel.kt` | T2 |
| A-UI-11 | Sponsor "Go VIP" card (first-party, no SDK) | MONETIZATION §6 | `DetailScreen.kt:506-551` | T2 |
| A-UI-12 | My List with recent/title sort, long-press remove | PLAN | `MyListScreen.kt:75-96` | T2 |
| A-UI-13 | Settings: server, stats, offline, VIP, LAN share, account, playback/display, storage, about | MENTOR; PLAN | `SettingsScreen.kt:100-463` | T2 |
| A-UI-14 | Every persisted preference has a consumer (image quality, mobile-data posters, TTL, subtitle/audio language, boost, dynamic colour) | QODER Task "make every preference real" | `ServerSettingsRepository.kt:260-275`; `SettingsViewModel.kt`; consumers listed in §6 of the audit | T1 — settings/pref tests |
| A-UI-15 | Downloads screen: storage card, device downloads, in-app keeps, expiry, retry/cancel | CACHE_SPEC §8 | `DownloadsScreen.kt:56-425`; `DownloadsViewModel.kt` | T2 |
| A-UI-16 | VIP screen: plans, PKR prices from server, four payment handles with Copy, TID form, pending card, rewarded pass card | MONETIZATION §3; OPERATOR guide | `VipUpgradeScreen.kt:74-651`; `VipViewModel.kt` | T2 — `VipTidTest`, `RewardedVipPassTest` |

---

## 10. Android: player (MX Player parity)

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| A-PLR-01 | Media3 `MediaSessionService` with notification/lock-screen/headset buttons, background audio | PLAYER_SPEC §2.2–2.3 | `PlaybackService.kt:1-524` | T2 |
| A-PLR-02 | Double-tap ±10 s with ripple + label | PLAYER_SPEC §2.1 (MX) | `PlayerGestures.kt:93-103`; `PlayerScreen.kt:770` | T1 — `PlayerGesturesTest` (15) |
| A-PLR-03 | Double-tap centre play/pause (toggleable) | MX skin option | `GestureSettings.doubleTapCenterPlays` | T1 |
| A-PLR-04 | Vertical swipe left = brightness, right = volume (window-local, no permission) | MX | `PlayerGestures.kt:52-54`; PlayerScreen HUD | T2 |
| A-PLR-05 | Horizontal scrub with live time preview + chapter ticks (no thumbnails) | MX; PLAYER_SPEC honest limit | `PlayerGestures.kt:55`; `PlayerScreen.kt` scrub HUD | T2 |
| A-PLR-06 | Long-press 2× boost, release restores | MX | `PlayerGestures.kt:104`; `PlayerViewModel.kt:763-770` | T1 |
| A-PLR-08 | Pinch / resize modes FIT→ZOOM→FILL→FIXED_WIDTH | MX | `PlayerScreen.kt` aspect cycle; `PlayerViewModel.kt:1152-1160` | T2 |
| A-PLR-09 | Lock: all gestures/controls except unlock | MX | `PlayerScreen.kt:1093,1174`; `PlayerUiState.locked` | T2 |
| A-PLR-10 | Orientation cycle SENSOR↔LANDSCAPE↔PORTRAIT↔LOCKED | MX | `PlayerViewModel.kt:1160-1174` | T2 |
| A-PLR-11 | Speed 0.25–4× pitch-preserved | MX; PLAYER_SPEC | `PlayerViewModel.kt:755`; `SpeedSheet` "pitch preserved" | T2 |
| A-PLR-12 | Frame step ±1/frameRate (approx) | PLAYER_SPEC §2.3 | `PlayerViewModel.kt:749`; `stepFrame` | T1 |
| A-PLR-13 | Sleep timer: presets, end-of-video, fade-out | MX Tools; archive feature 6 | `SleepTimer.kt:10-89`; `PlayerScreen.kt:929-948,1733-1753`; `PlayerViewModel.kt:812` | T1 — `SleepTimerTest` (9) |
| A-PLR-14 | Audio-only mode (video track disabled, artwork surface) | PLAYER_SPEC | `PlayerScreen.kt:553-569`; `PlayerViewModel.kt:1179` | T2 |
| A-PLR-16 | Screen-off playback | MX | `PlaybackService.kt` `setWakeMode(C.WAKE_MODE_LOCAL)`; WAKE_LOCK | T2 |
| A-PLR-17 | Quality ladder built per scope (work/season/episode), Auto option | ARCHITECT; MENTOR "Play Best Quality" | `QualityLadder.kt`; `DetailViewModel.kt:176-203`; `PlayerViewModel.kt:949` | T1 — `QualityLadderTest` (8) |
| A-PLR-18 | Silent same-band failover + retry-once → next rank → give-up with reason log | API_V2 §5; PLAYER_SPEC §3.2 | `PlaybackService.kt:66+` (`FailoverStateMachine`); `network/models/PlaybackRecovery.kt:112-236`; UI `PlayerScreen.kt:1974-1998` | T1 — `SilentFailoverTest` (5) |
| A-PLR-19 | Adaptive quality from measured throughput | archive feature 4 | `AdaptiveQuality.kt:33-214`; `PlayerPolicyBridge.kt:174+`; `PlaybackService` stats | T1 — `AdaptiveQualityTest` (10) |
| A-PLR-21 | Pack offsets: local > server > calibration UI; report learned offset | PLAYER_SPEC §3.3; API_V2 §8 | `EpisodeOffsets.kt`; `PlayerScreen.kt:1556-1580`; `PlayerViewModel.kt:569-594,1464` | T1 — `EpisodeOffsets` tests |
| A-PLR-23 | Resume prompt + "play from" mm:ss dialog | MX | `PlayerScreen.kt:1494-1607`; `PlayerViewModel.kt:621-640` | T2 |
| A-PLR-25 | External player hand-off on give-up | BRAND `features.external_player_fallback` | `PlayerViewModel.kt:1596+`; `PlayerScreen.kt:1412` | T2 |
| A-PLR-27 | Gesture settings model (skip, boost, zones, cinema) | MX; archive pure-cinema | `PlayerGestures.kt:22-38` | T1 |
| A-PLR-28 | Pure cinema / ghost mode (hide UI; two-finger rewind) | MENTOR §PURE_CINEMA; archive | `PlayerScreen.kt:361,425,987,1088`; `GestureSettings.pureCinema` | T2 |
| A-PLR-29 | Subtitle delay for **native/embedded** cues (renderer wrapper) | PLAYER_SPEC said impossible in 1.3.1 | `player/subtitles/SubtitleOffsetPipeline.kt:34-154`; `PlaybackService.kt` `buildTextRenderers` override | T1 — `SubtitleOffsetPipelineTest` (6) |

**Correction to `PLAYER_SPEC.md`:** it states native subtitle delay is impossible on Media3 1.3.1.
The tree contains a working decoder/renderer wrapper that shifts cue times by the live offset. It is
built and unit-tested; only device verification is outstanding. `PLAYER_SPEC.md` §2.3 needs updating.

**Moved by the deep-wiring pass (§18.1):** A-PLR-07 (two-finger speed) was never implemented; A-PLR-15
(PiP), A-PLR-20 (binge preload), A-PLR-22 (cross-file next episode), A-PLR-24 (keep) and A-PLR-26
(ad break) exist only as unwired logic. They are now P-A-20, P-A-21, P-A-17, P-A-22, P-A-23 and
P-A-24 in §18.

---

## 11. Android: subtitles and audio

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| A-SUB-01 | Embedded subtitle track selection + Off | PLAYER_SPEC §2.3 | `PlayerViewModel.kt:269-286`; `SubtitleSettingsSheet` | T2 |
| A-SUB-02 | External subtitle picker via SAF (SRT/VTT/ASS/SSA/TTML) | PLAYER_SPEC; MENTOR subtitle styling | `PlayerScreen.kt:1766-1780` (`OpenDocument`); `addExternalSubtitle` | T2 |
| A-SUB-03 | Custom SRT/WebVTT parser + Compose overlay | MENTOR subtitle styling | `player/subtitle/SubtitleParsers.kt:1-143`; `SubtitleOverlay` | T1 |
| A-SUB-04 | Live subtitle offset ±, persisted per session | MENTOR feature A | `SubtitleOffsetSheet.kt:1-228`; `PlayerViewModel.kt:1104-1123` | T1 — `SubtitleOffsetTest` (8) |
| A-SUB-05 | Subtitle size / bottom padding / native styling | MENTOR subtitle styling | `PlayerScreen.kt:531-545` (`SubtitleView` styling) | T2 |
| A-SUB-06 | Preferred subtitle language | MENTOR; settings | `ServerSettingsRepository`; `SubtitleTrackPolicy` | T1 — `SubtitleTrackPolicyTest` (6) |
| A-SUB-07 | Audio language auto-match (Hindi/Urdu/English/etc.) | archive feature 6; MENTOR | `AudioTrackMatcher.kt:31-205`; `PlayerPolicyBridge.kt:45-109` | T1 — `AudioTrackMatcherTest` (23) |
| A-SUB-08 | Audio-only/stereo track cap | PLAYER_SPEC §2.3 | track policy in `PlayerPolicyBridge`; UI "stereo" | T1/T2 |
| A-SUB-09 | Audio boost with honest ceiling (gain multiplication, no fake EQ) | archive; MENTOR | `AudioBoost.kt:25-114`; `PlayerViewModel.kt:790-817` | T1 — `AudioBoostTest` (11) |

---

## 12. Android: offline cache (the signature feature)

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| A-CACHE-01 | Byte-interval ledger, canonical merge, gaps/prefix | CACHE_SPEC §2 | `IntervalLedger.kt`; `ByteInterval.kt` | T1 — `IntervalLedgerTest` (17) |
| A-CACHE-02 | Source identity independent of rotating signed URL | CACHE_SPEC §3 | `SourceIdentity.kt`; `ResumeToken.kt` | T1 — `SourceIdentityTest` (7), `ResumeTokenTest` (7) |
| A-CACHE-03 | Resumable state machine + exponential backoff w/ jitter | CACHE_SPEC §4 | `CacheStateMachine.kt` | T1 — `CacheStateMachineTest` (15) |
| A-CACHE-05 | HLS segment ahead-buffer + rewritten local.m3u8 | CACHE_SPEC §5 | `HlsAheadBuffer.kt`; `HlsPlaylist.kt` | T1 — `HlsPlaylistTest` (6) |
| A-CACHE-06 | No-range fallback / ephemeral re-resolve / unknown size | CACHE_SPEC §5 | `AheadFetcher` modes; `CacheCoordinator` | T1 — `OfflineCacheWiringTest` (7) |
| A-CACHE-08 | TTL 3h/6h, user-kept lives forever, running-task defer, orphan grace | CACHE_SPEC §8 | `TtlPolicy.kt`; `CacheSweeper.kt` | T1 — `TtlPolicyTest` (10), `CacheSweeperTest` (5) |
| A-CACHE-09 | Eviction planner: per-file cap, hard ceiling, OS floor, usefulness ordering | CACHE_SPEC §9 | `EvictionPlanner.kt`; `StorageGate.kt` | T1 — `EvictionPlannerTest` (10) |
| A-CACHE-10 | Scheduler: 2 concurrent, user beats preview, network gates, data budget | CACHE_SPEC §10 | `SchedulerPolicy.kt`; `CacheCoordinator.kt` | T1 — `SchedulerPolicyTest` (10) |
| A-CACHE-13 | Keep TTL preference honoured by Downloads row + sweeper | CACHE_SPEC §8 | `KeepTtlHolder.kt`; `ServerSettingsRepository` | T1 |

**Deviation from spec:** `CACHE_SPEC.md` says TTL/eviction run under `WorkManager`. WorkManager is
**not a Gradle dependency**; sweeping runs only while the process is alive (5-minute coroutine loop).
Files therefore do **not** age out while the app is killed. See §15 (A-DL-04) and §22.

**Moved by the deep-wiring pass (§18.1):** A-CACHE-04 (ahead fetcher), A-CACHE-07 (zero-waste
handoff), A-CACHE-11 (loopback 206 proxy) and A-CACHE-12 (engine/playhead pump) are now P-A-25…P-A-28.
The ledger, policy, scheduler and eviction engines are real; the *live feed* into them is not.

---

## 13. Android: downloads

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| A-DL-01 | Own foreground `Service`, not platform `DownloadManager`, so pause/resume exist | archive; QODER Task 3 | `DownloadService.kt:40-52,76-135` | T2 |
| A-DL-02 | HTTP Range resume from last byte; total from `Content-Range` | CACHE_SPEC/archive feature 4 | `DownloadService.kt:170-177,288` | T2 |
| A-DL-03 | Public `Movies/RaddStream/` via MediaStore (API 29+) / legacy path | QODER Task 3 | `DownloadService.kt:231-288`; manifest `WRITE_EXTERNAL_STORAGE maxSdk 28` | T2 |
| A-DL-04 | Notification with progress + Pause/Resume/Cancel | QODER Task 3 | `DownloadService.kt:299-434` | T2 |
| A-DL-05 | Device download list + Play (content URI) + delete | QODER Task 3 | `DeviceDownloadsRepository.kt:87-229`; `DownloadsScreen.kt:234-315` | T2 |
| A-DL-06 | Completion opens locally in airplane mode (DefaultDataSource handles content/file) | archive offline playback | `PlaybackService.kt:81-90`; `PlayerViewModel.startLocalUri` | T2 |

---

## 14. Android: LAN share (P2P slice)

| ID | Capability | Spec origin | Evidence | Proof |
|---|---|---|---|---|
| A-P2P-01 | Opt-in LAN HTTP server on 8990 with token-path lookup | archive feature 2 | `LanShareServer.kt:53-232`; `LanShareRunner.kt` | T1/T2 — `LanShareProtocolTest` (14) |
| A-P2P-02 | Range/HEAD/416 semantics, traversal-proof token parsing | archive P2P | `LanShareProtocol.kt:64-212` | T1 — `LanShareProtocolTest` |
| A-P2P-03 | Only complete, non-temporary, app-private cache files are shareable; no provenance on the wire | ARCHITECT §16.9 | `ShareCatalog.kt:1-103` | T1 — `ShareCatalogTest` (6) |

**Moved by the deep-wiring pass (§18.1):** A-P2P-04 (live address/count) is now P-A-09. The server
works and is tested; the UI never renders `LanShareProtocol.shareUrl`, so a user has no address to
type into a second device.

---

## 15. Android: sync account

| ID | Capability | Evidence | Proof |
|---|---|---|---|
| A-SYNC-01 | Optional account card; create random key / paste existing key / sign out (revoke) | `SettingsScreen.kt:195-323`; `SyncAccountRepository.kt:88-175` | T2 |
| A-SYNC-02 | Phone-number quick sign-in deriving a deterministic key | `SyncContract.kt:211-224` | T1 — `SyncContractTest` (8) |
| A-SYNC-03 | Favorites push (add/remove) | `SyncAccountRepository.kt:192-205`; `FavoritesRepository` | T2 |
| A-SYNC-04 | Progress push throttled, conflict-aware | `SyncAccountRepository.kt:221-263`; `PlayerViewModel.kt:663-689` | T2 |
| A-SYNC-05 | Resume position pulled from account | `SyncAccountRepository.kt:322-327`; `PlayerViewModel.kt:470-475` | T2 |
| A-SYNC-06 | Key never logged or added to unrelated requests; bearer only on account calls | `RaddStreamApi.kt:28-46` | T1 |

---

## 16. Android: build, branding, CI verified

| ID | Capability | Evidence | Proof |
|---|---|---|---|
| A-BLD-01 | Brand file drives name, colours, strings, scheme, deep-link host, limits | `brand.properties`; build script; `BrandDriftTest` | T1 |
| A-BLD-02 | Release cleartext policy: loopback-only unless one host explicitly allowed | `build.gradle.kts:74-105,245-266` | T1 |
| A-BLD-03 | Debug/release signing from four repo secrets; minify + proguard | `build.gradle.kts:110-181` | T2 |
| A-BLD-04 | Root CI builds debug APK + runs 381 tests + lint | `.github/workflows/ci.yml:50-132` | T2 |
| A-BLD-05 | Tag release pipeline: secret gate, versionCode arithmetic, tests, signed APK/AAB, signature verify, SHA-256, GitHub Release | `.github/workflows/release.yml:33-174` | T2 |
| A-BLD-06 | Backend CI runs stdlib-only suites | `.github/workflows/backend-ci.yml:76-122` | T2 |

---

# PART II — PARTIALLY BUILT

Each entry below is a capability whose parts exist but whose user-visible flow is incomplete. Rows
marked "(was …)" were reclassified by the call-site audit in §18.1. The consequence is stated in user
terms, not as a code TODO.

## 17. Backend partials

| ID | Feature | What exists | What is missing | Consequence |
|---|---|---|---|---|
| P-B-01 | API v2 live availability | All routes implemented and tested | The live catalog has no/stale `cat_*` projection; `project` is not in the 6-hour pipeline | `/api/v2/*` answers `unavailable`, so server-ranked play, FTS search, sync and offsets are unreachable |
| P-B-02 | Shortener monetization | Weighted rotation, cache, fallback, `/api/v1/download`; nginx no longer denies it (public since 2026-10-27) | Client half **declined 2026-10-27**: a shortened target is a landing page a human taps, not the file, so the byte pipe cannot follow it — see M-MON-04 | Free-tier downloads earn **zero** shortener revenue, **by the owner's decision** |
| P-B-03 | VIP bypass | `request_is_vip` accepts account `vip_until` or signed pass; `GET /api/v2/account/vip-pass` mints one (200 / 401 / 402, capped at the membership); admin approval sets `vip_until` | No app sends the bearer or `?vip=` on downloads — and no app needs to yet, because `/api/v1/stream` was never monetized, so nothing was bypassing | The bypass is reachable and tested; the *reason* to use it arrives with P-B-02 |
| P-B-04 | Admin panel | Screens + three writes + token gate | Token is a static systemd literal; no audit log; no CSRF/rotation | Weak operational security for the one write surface |
| P-B-05 | Domain rotation | Probe + registry + active base URL | Not invoked by importers/cron on 403/404; no scheduled probe | Site migrations still require a manual registry edit |
| P-B-06 | Site Scout | Stages 1–4 incl. disciple scaffold | No `bridge_tracer.py`; no automated promotion of a scaffold into CI; manual review required | Adding a site stays human-in-the-loop |
| P-B-07 | Arena tournament | OpenRouter query + tournament | Needs an API key; no scheduled winner promotion | Model comparison is a manual exercise |
| P-B-08 | Backups | Four upload targets + code snapshot | HF/R2/Telegram credentials are host-local and unverified here; no restore drill in CI | Backups exist but recovery is untested |
| P-B-09 | Link health on the live catalog | Probe/score/report + admin evidence | Cron does not schedule `link_health`; live `cat_links` were observed `unchecked` with link_coverage 0.0 | Ranked play and client reports have no measured health to use |
| P-B-10 | Public edge | Two-port split + sweep tool | Documented nginx allowlist omits five routes the app needs (see §24) | Playback/detail/download/art/remote-config 403 behind the documented proxy |

## 18. Android partials

| ID | Feature | What exists | What is missing | Consequence |
|---|---|---|---|---|
| P-A-01 | Search recents | In-memory list, 8 chips | Persistence (DataStore/Room) | Recents vanish on process death |
| P-A-02 | Search suggestions/trending | `trendingHidden` flag + debounce infrastructure | `/api/v2/suggest` call, trending UI | No suggestions while typing |
| P-A-03 | Watchlist sync pull | Push works; favorites count pulled | Pull never materializes server rows into Room (`favoritePlan` count-only) | Signing in on a new phone shows an empty My List |
| P-A-04 | Account `verify()` | Implemented | Never called | A revoked key is only discovered on the next real sync |
| P-A-05 | Remote config | Prices, handles, APK URL consumed | `maintenance_mode`, `ads`, `link_shorteners`, three feature flags not parsed | No maintenance screen, no ads, no shortener awareness, no flags |
| P-A-06 | VIP upgrade | Plans, handles, TID form, local pending | No POST, no approval status, no entitlement read, no gating | A paying user cannot become VIP in the app |
| P-A-07 | Rewarded VIP | Device-local 4-hour pass; honest "no ad player yet" text | Ad SDK and server-signed pass | Button grants VIP for free |
| P-A-08 | Ads | `AdSlotPolicy` + sponsor dialog/break UI | Any ad network, any creative, any preload | No ad revenue; policy is a guard, not a fill |
| P-A-09 | LAN share | Server/protocol/catalog + Settings toggle + live peer/count | QR, peer discovery, share sheet, receiver flow, Downloads entry; **`LanShareProtocol.shareUrl` has no caller outside tests**, so no per-file address is ever displayed | Users cannot practically discover or use it; the server is effectively invisible |
| P-A-10 | Auto server discovery | Full Blogger gateway implementation + tests | Never injected or called; Setup has no "find server" | An IP change requires manual re-entry |
| P-A-11 | Device downloads | Range resume, pause, notification | Midnight scheduling, SD-card destination, queue concurrency control; no Wi-Fi-only/metered policy (`mobileDataAllowed` gates *images* only); queue is strictly serial; **zero download tests** | Archive features 1/3 missing; one download at a time; can burn mobile data; regressions unguarded |
| P-A-12 | Offline TTL while app dead | Coroutine sweep at 5 min | WorkManager (not a dependency) | Expired previews stay until next app launch |
| P-A-13 | Deep links | browse + detail | player, downloads, vip, setup; no `onNewIntent` for warm start | Shared links only cover two destinations |
| P-A-14 | Inbound sharing | Outbound `ACTION_SEND` text share | `ACTION_SEND` receiver / share-target activity | "Share to Radd" cannot identify a clip |
| P-A-15 | Player failover narration | Reason log + prints sheet | Report POST to `/api/v2/links/{id}/report` | Dead links never feed the server's health |
| P-A-16 | Pack offset reporting | Local learning + report object | POST to `/api/v2/episodes/{id}/offset` | Learned offsets never help other users |
| P-A-17 | Binge preload (was A-PLR-20) | `BingePreloader` at 85% + `PlayerViewModel.tickBingePreload`; emits a *resolve* for the next head | Actual byte prefetch/adoption. `PlayerViewModel.kt:1019-1030` only calls `resolveStream(handle)` (the source comment admits the head-pull entry point does not exist) | The "next episode ready" message is true about the link, false about warm bytes |
| P-A-18 | Anime chip | Server supports `type=anime`; Browse forwards it | Stale comment in `Models.kt` claiming it returns zero | Works in code; documentation contradicts it |
| P-A-19 | Device search / local library / reverse search / fingerprint | Nothing | Everything | See §19 |
| P-A-20 | Two-finger vertical speed (was A-PLR-07) | Nothing. `GestureMapper` has only `onTwoFingerTap` → pure-cinema rewind (`PlayerGestures.kt:114`) | The two-finger **vertical drag → speed** mapping and its settings row | MX-parity claim is inaccurate; no such gesture exists |
| P-A-21 | Picture-in-Picture (was A-PLR-15) | Manual PiP button; manifest `supportsPictureInPicture`; `PlayerScreen.kt:2106` builds empty `PictureInPictureParams` | Aspect ratio, auto-enter on home, seamless resize, source-rect hint | PiP works only from the button and uses the default video rect |
| P-A-22 | Cross-file next episode (was A-PLR-22) | In-file END detection and `NextEpisodeAction` event; prepared successor; `openNextEpisode` | `NavGraph.kt:215-219` constructs `PlayerScreen` **without** `onPlayNextEpisode`, so the default no-op at `PlayerScreen.kt:178` swallows the event | Finishing one file cannot advance to the next episode in the app |
| P-A-23 | Keep chip (was A-PLR-24) | Chip, saved/remaining accounting, honest blocked states, `keepCurrent()` enqueue | Enqueue hardcodes `origin = AUTO_PREVIEW` (`CacheRepository.kt:113`); `CacheCoordinator.keepNow` (`:222`) has **zero callers**; `OfflineCacheEngine.playableUri` (`:113`) has **zero callers** | A "kept" file expires on the preview TTL and, when played, still streams from the network |
| P-A-24 | Sponsor break (was A-PLR-26) | `AdSlotPolicy` + break dialog/UI + `requestAdBreak()` (`PlayerViewModel.kt:861`) | `requestAdBreak()` has **zero callers**; no ad SDK or fill | `adSlot` is always `NONE`; no break is ever requested |
| P-A-25 | Ahead-of-playback fetcher (was A-CACHE-04) | `AheadFetcher` (1 MiB chunks, 40 MiB window, 256 MiB/pass), `RangeByteFetcher`, scheduler, ledger | `PlayerSessionStore.reportPlayhead` (`:70`) has **zero callers**, so the `playhead` SharedFlow never emits | The engine ticks on schedule but never learns the position; nothing is buffered ahead |
| P-A-26 | Zero-waste preview→keep handoff (was A-CACHE-07) | `HandoffAccounting` + tests | Adoption of already-fetched preview bytes lives only inside the unused `keepNow`; the served flow re-enqueues from zero | Watch-then-keep downloads the file twice |
| P-A-27 | Loopback HTTP 206 proxy (was A-CACHE-11) | `LocalMediaProxy.kt:1-162` complete | **Zero references** outside its own file; `CacheContract.playableUri` (`:112`) has no caller | Partial/complete files cannot be served locally; "offline" playback is a network stream |
| P-A-28 | Cache engine playhead pump (was A-CACHE-12) | Engine starts at app launch (`RaddStreamApplication.kt:40`); tick 3 s; sweep 15 s then 5 min; collector at `CacheEngineRunner.kt:57` | The collected `playhead` flow is never written (root cause shared with P-A-25) | Sweeps and TTL run; ahead-of-playback caching does not |
| P-A-29 | Subtitle format coverage | SRT/VTT custom parser + overlay; ASS/SSA/TTML handed to Media3; native-cue delay wrapper | No unit tests for `SubtitleParsers`; external subtitle text over 4,000,000 chars returns `null` with no size-specific message (`PlayerViewModel.kt:1366-1372,1627`) | Parser regressions are unguarded and very large subtitle files fail without an explanation |

### 18.1 Deep-wiring verification (code-level)

A second pass traced *call sites*, not just existence. Every capability below compiles and has tests,
yet the shipped flow never invokes it. Line references are from the tree at commit `27fc043`.

| Root cause | Exact evidence | Capabilities affected |
|---|---|---|
| Playhead flow has no writer | `PlayerSessionStore.kt:63-73`: `_playhead` is a `MutableSharedFlow`; `reportPlayhead()` is the only emitter and has **0 callers** in `main`/`test`/`androidTest` | P-A-25, P-A-28, zero-waste handoff, any "preview" behaviour |
| Every keep is a preview | `CacheRepository.kt:113`: `origin = CacheOrigin.AUTO_PREVIEW.name` on the keep path; `TtlPolicy.kt:90` only spares `USER_KEEP` | P-A-23, TTL promise, Downloads "kept" label |
| Promotion path unused | `CacheCoordinator.kt:222-236` `keepNow()` and `CacheTaskDao.kt:122` promotion query have **0 callers** | Keep-forever, zero-waste adoption |
| Local-file playback unused | `OfflineCacheEngine.kt:113-117` `playableUri()` + `CacheContract.kt:112`; `LocalMediaProxy` referenced nowhere | Offline playback of in-app keeps; any 206 path |
| Prefetch resolves but fetches nothing | `PlayerViewModel.kt:1019-1030`: `prefetchNextEpisodeHead` calls `resolveStream` only; its own KDoc says the head-pull entry point does not exist | Binge preload |
| Next-episode callback omitted | `NavGraph.kt:215-219` builds `PlayerScreen(...)` without `onPlayNextEpisode`; default is `{ _, _, _, _ -> }` (`PlayerScreen.kt:178`) | Cross-file advance |
| Ad request never made | `PlayerViewModel.kt:861` `requestAdBreak()` has **0 callers**; `AdSlotPolicy` only classifies | Pre-roll / between-episode breaks |
| Share URL never rendered | `LanShareProtocol.kt:178` `shareUrl()` only referenced by `LanShareProtocolTest.kt:157-164` | LAN share UX |
| PiP params are empty | `PlayerScreen.kt:2106`: `PictureInPictureParams.Builder().build()` | PiP aspect/auto-enter |
| No metered-data gate on transfers | Only `ServerSettingsRepository.mobileDataAllowed` → `ImageSizing`/`CatalogImage`; `DownloadService` has no connectivity check | Data-saver promise |
| No background scheduler | WorkManager absent from `App/app/build.gradle.kts`; sweep is an in-process coroutine | TTL/eviction while app is dead |

**What this does not mean.** The underlying engines are not fake: the byte ledger, state machine,
TTL/eviction policy, scheduler policy, failover machine, subtitle wrapper and LAN HTTP server all have
passing unit tests. The gap is the *last mile* between a tested component and the screen the viewer
touches. Closing it is mostly small, local wiring — which is why these sit at the top of §25.

---

# PART III — PLANNED / MISSING (with exact build specifications)

Each item below is absent. The specification is written so an implementer can start without
re-reading the archive. Priority is in §25.

## 19. Discovery and search capabilities

### M-SRCH-01 — Click-to-search from a user device (never specified before this brief)
**Goal:** tap a video/poster on the user's phone and find the same title in the catalog.
**Origin:** no occurrence in directives or chat archive. This inventory is the first spec.
**Build:**
1. Add permissions: `READ_MEDIA_VIDEO` (API 33+), `READ_EXTERNAL_STORAGE` (`maxSdkVersion=32`).
2. `data/local/DeviceMediaScanner.kt`: query `MediaStore.Video.Media.EXTERNAL_CONTENT_URI` for
   `_ID, DISPLAY_NAME, DURATION, SIZE, DATE_ADDED, RELATIVE_PATH, MIME_TYPE`; map to
   `LocalVideo(id, uri, name, durationMs, sizeBytes, folder)`.
3. `ui/screens/LocalLibraryScreen.kt` + route `library`; grid grouped by folder; empty state explains
   the permission.
4. On click: bottom sheet with **Play here** (`player_local/{uri}/{title}`) and **Find in catalog**.
5. `LocalTitleMatcher.kt` (pure, JVM-tested): strip extension, quality tokens (`480p|720p|1080p|4K`),
   codec (`x264|x265|HEVC`), group tags (`ESub`, `HDHub`, `Vega`), year extraction; produce
   `cleanTitle` + `year`.
6. Call `GET /api/v1/posts?q=<cleanTitle>`; rank candidates by normalized-title equality, then year
   distance, then token overlap. Show top 5 with poster + "This is the one?" confirmation.
7. Store the mapping in Room (`local_video_match`) so the next tap opens Detail directly.
**Tests:** title cleaner (30 cases incl. `Movie.Name.2019.1080p.WEB-DL.x264-ESub.mkv`), matcher
scoring, scanner cursor mapping.
**Acceptance:** tapping any of 20 sample filenames yields the correct work for ≥16; no file bytes
leave the device.

> **Status 2026-10-27 — the server half is BUILT and DEPLOYED, the phone half is not.**
> `GET /api/v1/search/by-media` (`Fast_Fetch/media_search.py`, routed in `viewer.py`, public as a
> rate-limited GET-only nginx location) takes the facts a `MediaStore` row already carries —
> `DISPLAY_NAME`, `DURATION`, and the print's rung — and answers which work they belong to. It does
> the part steps 5–6 of this spec never could: the media facts are **evidence, not keywords**, and
> every hint comes back as `matched_on`, `mismatched_on` or `unknown_on`, because a ledger that has
> no runtime for a work must not be credited with agreeing about one. A title is required and its
> absence is a `400`, not a top-ten list: 130 016 works, several thousand of them ~120-minute 480p
> films, and duration plus rung cannot discriminate among them.
> **What remains is steps 1–4 and 7** (permissions, `DeviceMediaScanner`, the screen, the Room
> mapping), and it is deliberately not started: none of it can be verified on this box — there is
> still no device and no emulator here, and a half-written `MediaStore` query that has never run
> against a real phone is exactly the kind of "implemented" that this file has repeatedly had to
> walk back. Verified: 21 tests in `Fast_Fetch/test_media_search.py`, and the new route is inside
> the `sweep_public_edge.py` route set (adult rows absent, no provenance, no upstream host).
> Measured on the live catalog: 0.37 s for a five-candidate query.

### M-SRCH-02 — Local device media scanning / library
**Goal:** browse and play media already on the phone, without a server.
**Origin:** never specified; adjacent to archive feature 3 (SD card) only for downloads.
**Build:** reuse `DeviceMediaScanner` (M-SRCH-01); add filters (video/audio), sort by date/name/size,
folder navigation, thumbnails via Coil `videoFrameMillis`; playback via `player_local`; optional
"hide from library" set. No catalog call required.
**Acceptance:** library opens in <500 ms for 1,000 rows; playback works in airplane mode.

### M-SRCH-03 — Reverse search / Clip & Scene Finder
**Origin:** archive 2026-10-25, lines ~81598–81983; `SENIOR_MENTOR_DIRECTIVE_QODER.md` Priority 5
("Desi Cine-Finder"); `docs/SITE_SCOUT_SPEC.md` mentions OCR reconnaissance only.
**Goal:** user supplies a 5–20 s clip or screenshot; app identifies the movie and offers Play.
**Architecture (zero server video load):**
1. `ClipIdentifyScreen` — pick clip via `ACTION_OPEN_DOCUMENT` (video/*) or share target.
2. `FrameExtractor.kt`: `MediaMetadataRetriever` with `OPTION_CLOSEST_SYNC` at 25/50/75%; JPEG in
   memory; cap 3 frames.
3. **Track A (text):** on-device ML Kit `text-recognition` (new dependency). Extract dialogue;
   normalize to ≤10 words; query `GET /api/v1/posts?q=` (or `/api/v2/search` when projected).
4. **Track B (visual):** invoke Google Lens via intent on one frame; fall back to a user-confirmed
   manual title entry. **Do not upload the clip to our server.**
5. Rank: exact FTS hit > fuzzy title > visual result; display poster, year, "Watch now".
6. Privacy copy: "Recognition happens on your phone; only the recognized text is sent to your
   catalog server."
7. Feature flag `features.clip_finder` in `brand.properties` (default false until tested).
**Tests:** frame timestamps, OCR text normalizer, ranker, intent failure paths.
**Acceptance:** 10 known clips identify correctly for ≥6; zero video bytes uploaded; no server CPU
spike.
**Costs:** ML Kit adds ~few MB; Lens intent requires Google app.

### M-SRCH-04 — Audio fingerprint / audio-track identification
**Origin:** archive explicitly evaluated and **rejected Shazam-style recognition for movie ID**
(line ~82137: "It identifies the background song, NOT the movie"). No fingerprint directive exists.
The code's `AudioTrackMatcher` is a language selector, not acoustic matching.
**Honest recommendation:** do not build movie ID by audio fingerprint. Build song ID only if a music
feature is wanted.
**If built for songs:** `AudioRecord` 10 s PCM → ACRCloud/AudD REST (`fingerprint` endpoint) →
map artist/title to catalog soundtracks if such data exists (it does not today). Requires a paid API
key and a server-side relay to hide the key; store results locally.
**If used as a secondary signal for clips:** extract audio fingerprint locally and compare against a
local index of movie audio — not feasible at catalog scale.
**Acceptance (song mode):** 10 sample songs, ≥8 correct, key never shipped in APK.

### M-SRCH-05 — FTS5 / natural-language / vibe search in the app
**Origin:** ARCHITECT FTS5; MENTOR Priority 5; archive lines ~69079.
**Build:** keep v1 as fallback. When `GET /api/v2/manifest` succeeds, `SearchViewModel` calls
`/api/v2/search` (FTS5) and `/api/v2/suggest`; add chips for mood/theme only if the projection has
those tags; add "Trending" from `/api/v2/browse?sort=trending`. Feature-detect with one manifest call
at startup; cache the answer for the session.
**Acceptance:** typing 2 chars shows suggestions <300 ms; v1 fallback identical results if v2 is down.

### M-SRCH-06 — Recommendations ("Because you watched")
**Origin:** `HomeViewModel` KDoc lists it as a planned row; MENTOR Netflix UI.
**Build:** derive top 2 genres/industries from `WatchHistory` + favorites; call
`/api/v1/posts?genre=&industry=`; de-duplicate against Continue Watching; one rail, 12 items. No ML.
**Acceptance:** cold start shows nothing; after 3 watched titles a relevant rail appears.

### M-SRCH-07 — Cast / trailer / reviews on Detail
**Origin:** AUDIT §2 metadata; MENTOR hero/metadata; archive.
**Build:** add `cast`, `director`, `trailer_url` columns to v1 detail (TMDB backfill already fetches
details); Detail shows a horizontally scrolling cast row (name + character, no photos unless TMDB
provides) and a trailer button that opens YouTube via `ACTION_VIEW`. Reviews stay out (no source).
**Acceptance:** works when fields are null (hide section), never fabricates.

### M-SRCH-08 — Watchlist materialization
Covered as P-A-03; build in §22 P0-5.

---

## 20. Offline growth features (from the Pakistan/India/Bangladesh feature set)

### M-DL-01 — "Night-Owl" scheduled downloads
**Origin:** archive 2026-10-23, feature 1 (lines ~71400).
**Goal:** queue downloads to run in the carrier's free window (e.g. 01:00–06:00).
**Build:**
1. Add `androidx.work:work-runtime-ktx`.
2. `data/downloads/NightDownloadScheduler.kt`: compute next window start; enqueue a unique
   `OneTimeWorkRequest` with `setInitialDelay`; `NightDownloadWorker` (CoroutineWorker) starts
   queued downloads, checks `LocalTime` every minute, pauses at window end, reschedules next day.
3. Persist `night_window_start/end` + `night_only` per download row.
4. UI: switch in the download sheet ("Download tonight") + a banner in Downloads.
5. Constraint: `NetworkType.CONNECTED` (mobile allowed); battery not low optional.
**Tests:** window math across midnight/timezones; worker stops at boundary.
**Acceptance:** a queued item does not start before 01:00 and stops by 06:00, surviving reboot.

### M-DL-02 — MicroSD card destination selector
**Origin:** archive feature 3.
**Build:** `StorageDestination` model; inspect `context.getExternalFilesDirs(null)` (second entry =
removable); Settings row "Download location" with free space; write via app-specific external dir
(no permission) or SAF tree for public `Movies/` on the card; migrate in-progress rows safely.
**Acceptance:** with a card inserted, new downloads land there and play offline; removing the card
marks rows unavailable rather than crashing.

### M-DL-03 — Data-saver streaming cap + sizes
**Origin:** archive feature 5.
**Build:** per-rung `sizeBytes` already exists in `QualityLadder`; add a "Data saver" toggle that,
on `NetworkClass.MOBILE`, caps auto selection at 720p (480p if `saveMore`), and shows sizes on every
rung; Detail "best print" respects the cap. Add a session data meter (bytes from Media3 stats).
**Acceptance:** mobile + saver never opens a >720p rung automatically; user can override per title.

### M-DL-04 — Download queue concurrency + Wi-Fi-only toggle
**Build:** `DownloadService` currently pumps one id at a time. Add `maxConcurrent` (1–3) and a
`wifiOnly` preference; use a work queue with priority (user tap > binge preload). Show queued state.
**Acceptance:** three downloads progress within the cap; metered network pauses them.

### M-DL-05 — Offline TTL enforcement while app is dead
Covered as P-A-12. Add WorkManager periodic worker (15 min minimum) that calls `CacheSweeper`;
keep the in-process loop as a fast path. Acceptance: a 3-hour preview is gone after 3 h + 15 min
even if the app was never opened.

### M-DL-06 — LAN share UX, QR and receiver
**Origin:** archive feature 2; current server is only half the feature.
**Build:**
1. Downloads screen: "Share" on each kept item and "Share all" -> `ShareSheet` showing URL + QR
   (`com.google.zxing:core` or a pure-Kotlin QR generator), copy button, "Stop sharing".
2. Optional `NsdManager` advertisement `_raddshare._tcp` for peers that support discovery.
3. Receiver: `LanShareReceiverScreen` with QR scanner (`zxing-android-embedded`) or "Open URL";
   download with Range to `media_cache`, then play via `LocalMediaProxy`. This turns the feature into
   true device-to-device transfer, not just streaming.
4. Security: per-session token, 4-hour expiry, stop when screen off optional, never serve a file that
   is not complete.
**Acceptance:** two phones on one hotspot, 1 GB file, no internet; receiver plays after transfer.

---

## 21. Growth, monetization and payments

### M-MON-01 — Payment ledger + approval + entitlement
**Status: BUILT (server + app + deployed), device pass outstanding.** The ledger, the two routes, the admin
approval screen and the client round-trip all exist and are tested; what is still owed is a phone
in a hand (see the acceptance line below). Steps 1–7 are done as written. Step 8's quality clause
is now satisfied the honest way: remote config *does* publish a quality field
(`feature_flags.quality_gate`), it defaults off, and the client gates on it rather than on a guess —
see M-MON-05 for what is still server-side.
**Deployment fact that was blocking all of this:** the installed nginx swallowed every v2 route
behind `location ^~ /api/ { return 403; }`, so `/api/v2/account*` and
`/api/v1/app/remote-config` were unreachable from any viewer's phone. Both are exposed now; the
runbook records the exact blocks and the backup path.
**Origin:** `MASTER_ADMIN_MONETIZATION_SPEC.md` §2–3 (tables `app_users`, `payment_transactions`,
admin pending list, 1-click approve); `PAKISTAN_OPERATOR_GUIDE.md`.
**Current state (was: UI + settings only, TID stays on the phone, `vip_until` never written):**
the TID is filed to the server, `pending` comes back, and `vip_until` is written only by an
operator approval.
**Build (server):**
1. Add tables in the accounts DB:
   `payment_transactions(id, account_id, plan, amount_pkr, method, tid, status, submitted_at, reviewed_at, reviewer_note)`;
   index on `status, submitted_at`.
2. `POST /api/v2/account/payment` (bearer): validate plan/TID shape, insert `pending`, rate-limit
   1 per 5 min, return `payment_id`.
3. `GET /api/v2/account/entitlement` (bearer): `{vip: bool, vip_until, pending: bool}` derived from
   `user_accounts.vip_until`.
4. Admin screen `/admin/payments`: list pending with account hint, TID, amount, plan; two actions
   `approve` / `reject`. Approve sets `vip_until = max(now, vip_until) + days(plan)` in one
   transaction and writes an audit row.
5. Optional `POST /admin/api/payments/{id}/approve` with the same token gate; CSRF token on the HTML
   form; never log TIDs in access logs.
**Build (app):**
6. `VipViewModel.submitTransaction()` calls the endpoint; remove local-only persistence except as an
   offline draft.
7. Poll entitlement on app start and every 6 h; show "Pending verification" and "VIP until …".
8. Gate what the spec says VIP gets: no sponsor card, direct (unshortened) downloads, quality above
   720p if soft gating is enabled. Read the gate from remote config.
**Acceptance:** end-to-end: user submits TID → operator approves → app shows VIP without reinstall;
reject path explains why; no double-credit on retry.

### M-MON-02 — Server-signed rewarded VIP pass
**Origin:** MONETIZATION rewarded flow; app already has a local pass.
**Build:** `POST /api/v2/account/reward` with a server-verifiable proof (ad network callback S2S or
admin-issued code) → `redact.mint_vip_pass(expires_at)`; app stores the token and sends `?vip=<pass>`
on downloads; duration 4 h default, max 24 h. Until an ad network exists, keep the current honest
"activates directly" text rather than pretending.
**Acceptance:** a pass works on `/api/v1/download`, expires server-side, cannot be reused after
expiry, and is bound to one account.

### M-MON-03 — Ad SDK integration (Monetag rewarded + Adsterra native)
**Origin:** MONETIZATION §6; AUDIT §3; admin fields already exist.
**Build:**
1. Parse `ads` + `featureFlags` from `/api/v1/app/remote-config` into `VipRemoteConfig`.
2. Add the Monetag rewarded SDK (or a mediated wrapper) and Adsterra native banner view.
3. Wire rewarded completion → `grantRewardedVip` **and** server pass (M-MON-02).
4. Native banner: only where a sponsor card is allowed (Detail, maybe Home) — never over playback.
5. `AdSlotPolicy` stays the only gate for video breaks; preload the next break; never mid-roll.
6. Add a privacy/consent gate and a "remove ads" path (VIP).
**Acceptance:** with IDs configured, a free user sees a pre-roll seam and a native card; VIP sees
neither; no ad request on a metered network if data saver is on (configurable).

### M-MON-04 — Shortener-aware client downloads
**Status: CLOSED 2026-10-27. Server half BUILT and DEPLOYED; the client half was declined by the
owner, for the reason written down below rather than discovered later in a bug report.**

What shipped (2026-10-27): `/api/v1/download` answers on the public port (nginx denied it before, so
the whole waterfall was unreachable from any client), `GET /api/v2/account/vip-pass` mints the
capability a URL can carry, and both routes log under `radd_capability`, a format with no `$args`, so
a `?vip=` never reaches an access log.

Why the original build text does not work. It says: switch `DeviceDownloadsRepository` from
`/api/v1/stream` to `/api/v1/download` and attach the bearer. Two things are wrong with that.

1. **The bearer it asks for buys nothing.** `DownloadService` pipes bytes itself with OkHttp, so an
   `Authorization` header would reach our route fine — but `/api/v1/stream`, the route it uses today,
   has **never** run the shortener: `shorten_download_url` has exactly one call site in `viewer.py`
   (line 3207, the download route). A VIP in-app was therefore never being walked through a shortener,
   so there is no bypass waiting to be attached. Attaching a pass here monetizes nothing and breaks
   nothing; it is a no-op dressed as a milestone.
2. **A free download cannot be monetized and kept resumable.** `test_download_endpoint.py` states it
   in its own comment: *"A shortened target is a landing page, not the file."* Point the byte pipe at
   `/api/v1/download?redirect=1` for a signed-out viewer and OkHttp faithfully follows the shortener to
   an interstitial and writes HTML into `Movies/RaddStream/` under a `.mp4` name. That is not a slower
   download; it is a broken one, and it loses the pause/resume the app exists to provide.

So the acceptance line ("a free signed-out download goes through the configured shortener") is
reachable only by **handing the free download to something a human operates** — the shortener URL to a
browser, the way `openInExternalPlayer()` already hands a stream URL to an external player. That
trades the app's download promise for revenue on the free tier.

**Decided by the owner on 2026-10-27: keep the byte pipe.** Free downloads keep streaming from
`/api/v1/stream` with an honest pause that keeps its bytes, and **free-tier shortener revenue is
accepted at zero** — VIP purchases are the monetization. No client change follows from this feature,
and the server work above is what makes the *paid* path correct. **P-B-02 is closed as won't-fix,
not left unfinished:** the waterfall stays configured, exercised and reachable, and it now serves the
browser hand-off and any future surface with a human at the end of it.

**Acceptance:** ~~a free signed-out download goes through the configured shortener~~ *(declined —
see the decision above)*; a VIP account gets the direct URL — **met**, by both proofs (`?vip=` pass and
bearer header) and asserted in `test_download_endpoint.py`; a shortener outage still downloads —
**met** (falls back to the direct URL; monetization can never break a download).

### M-MON-05 — Quality gating matrix (free vs VIP)
**Status: HALF BUILT, and off by default.** The client rule exists (`VipQualityGate`) and the
operator can now turn it on (`feature_quality_gate` in `/admin`, published as
`feature_flags.quality_gate`). With the switch off, which is what a deployment ships with, nothing
is restricted — a catalog that was never priced should not go dark on its own. Still outstanding:
the server-side `max_quality` on the PlayBundle and the resolver refusing to mint a handle above
the cap, which is what turns a client-side courtesy into an actual entitlement.
**Origin:** MONETIZATION "non-strict quality gating"; AUDIT §3.
**Build:** server-side entitlement field in the PlayBundle (`max_quality`), client honours it in the
ladder (shows locked rungs with "VIP"), and the server refuses to mint handles above the cap. Keep it
"soft": never break playback of a lower rung.
**Acceptance:** free user sees 720p playable, 1080p/4K locked with an upgrade path; VIP sees all.

### M-MON-06 — Maintenance mode UI
**Status: BUILT.** `RemoteConfigWatcher` polls `/api/v1/app/remote-config` every 5 min and persists
the switch; `MainActivity` replaces the nav graph with `MaintenanceScreen` while it is on. The spec's
"all navigation blocked **except Settings**" is honoured by the only part of Settings a viewer
actually needs under a wrongly-flagged server: the notice carries "Use a different server", which
routes to `Screen.Setup` (the address field) and stays available until the flag clears. Full
Settings remains behind the overlay — the escape is to another server, not to the rest of the app.
**Build:** `HomeViewModel` observes `maintenanceMode`; show a full-screen "We'll be back" with retry
and a link to Telegram; all navigation blocked except Settings. Admin already has the switch.
**Acceptance:** toggling the admin flag changes the app within one refresh, no reinstall.

### M-MON-07 — Telegram funnel, announcements, referral
**Origin:** OPERATOR guide Step 5; MONETIZATION remote control.
**Build:** add `announcement_text`, `telegram_url`, `referral_code` to `app_remote_config` and
remote-config; Home banner + Settings link; deep link `radd://join?ref=`; server counts referrals.
**Acceptance:** operator can post a one-line announcement without an app release; taps are attributed.

### M-MON-08 — USDT → JazzCash arbitrage / payout rails
**Origin:** MONETIZATION §5; OPERATOR guide accounts.
**Nature:** operational, not code. The only code requirement is that payout references are recorded
in the payment ledger (M-MON-01). Document the Binance P2P procedure in the operator guide; do not
build an exchange integration.

---

## 22. Platform and player depth

### M-PLAT-01 — Chromecast / Google Cast
**Origin:** admin flag `feature_chromecast`; PLAYER_SPEC mentions cast as out of scope.
**Build:** add `androidx.mediarouter` + `com.google.android.gms:play-services-cast-framework`;
`OptionsProvider` with receiver app id from brand; `MediaRouteButton` in PlayerTopBar and Detail;
`CastPlayer`/`RemoteMediaClient` for the PlayBundle URL (server 302 works); remote config flag gates
the button. Requires a Cast developer app id.
**Acceptance:** phone discovers TV, playback starts at the current position, no local player echo.

### M-PLAT-02 — Android TV / leanback
**Build:** add leanback `uses-feature`, TV banner, `LEANBACK_LAUNCHER` intent filter; D-pad focus
order on rails; a TV-specific player overlay (no touch gestures); test on an emulator image. Brand
file gets a TV banner color/shape.
**Acceptance:** installs on a TV, D-pad navigates every screen, playback controls reachable.

### M-PLAT-03 — Inbound share target (`ACTION_SEND`)
**Build:** add an intent filter for `text/plain` and `video/*` to MainActivity (or a dedicated
`ShareReceiverActivity`); `onNewIntent` handles warm starts; text containing a URL → Detail/stream
resolution; a video → M-SRCH-03; a title string → Search prefilled.
**Acceptance:** "Share to Radd" from YouTube/TikTok opens the right flow; no crash on unknown type.

### M-PLAT-04 — Deep links for player, downloads, VIP
**Build:** add `navDeepLink` patterns: `player/{handle}`, `downloads`, `vip`; validate handles as
opaque tokens; `onNewIntent` in MainActivity navigates when the app is already running.
**Acceptance:** every shared link opens the correct screen cold and warm.

### M-PLAT-05 — A-B repeat
**Origin:** PLAYER_SPEC §2.3 "future"; MX feature reel.
**Build:** player state `repeatA/B`; set from current position; ticker seeks to A when position ≥ B;
UI in overflow "Repeat A-B"; clear on stop. Unit-test the loop predicate.
**Acceptance:** loops exactly between markers, survives speed changes, clears on new item.

### M-PLAT-06 — Audio delay, downmix, equalizer
**Origin:** PLAYER_SPEC honest limits; MENTOR "night dialogue normalizer".
**Build:**
- **Equalizer:** `android.media.audiofx.Equalizer` + `LoudnessEnhancer` attached to the player's
  audio session (API 16+); presets + custom bands; bypass with AudioBoost honesty. This is the only
  path to the "night dialogue" boost; keep the existing gain multiplier as fallback.
- **Audio delay:** requires an `AudioSink`/renderer wrapper analogous to the subtitle wrapper;
  implement only if a real user need appears. Estimated 2–3 weeks and risky.
- **5.1→stereo downmix:** needs a custom `AudioSink` or FFmpeg extension; `setMaxAudioChannelCount(2)`
  only restricts selection. Document as No until extension build exists.
**Acceptance:** equalizer changes are audible and reversible; no clipping at max boost.

### M-PLAT-07 — Software decoders (FFmpeg extension)
**Origin:** PLAYER_SPEC §2.4.
**Build:** add a CI job that checks out media3 source at 1.3.1, builds `decoder_ffmpeg` with the NDK
for arm64-v8a/armeabi-v7a, publishes the AAR to a Maven repo or vendors the `.so`; set
`DefaultRenderersFactory.setExtensionRendererMode(PREFER)` behind a setting. Decide APK-size budget.
**Acceptance:** a DTS/TrueHD sample plays with audio; H.264 still uses hardware by default.

### M-PLAT-08 — Native subtitle timing for other formats / forced flags
**Build:** the wrapper already covers cue shift; add forced/SDH/3D flags to the track list from
`Format.selectionFlags`/label parsing; add "subtitle search online" (M-PLAT-09).
**Acceptance:** forced tracks labelled; offset applies to every text format.

### M-PLAT-09 — Online subtitle search
**Origin:** MENTOR feature A; archive 80002–80008 (OpenSubtitles).
**Build:** server proxy to OpenSubtitles (API key in env, never APK) `GET /api/v1/subtitles/search?
title=&year=&imdb=`; app downloads `.srt` via the proxy, stores in `filesDir/subs`, feeds
`addExternalSubtitle`. Cache per work. Respect provider rate limits.
**Acceptance:** searching a known title returns ≥3 languages; playback loads the chosen file.

### M-PLAT-10 — Trakt
**Origin:** MENTOR feature A; archive 68677.
**Build:** OAuth device-code flow; store tokens encrypted; scrobble start/pause/stop at 80%+;
two-way watchlist sync. Requires a Trakt client id/secret and a server-side redirect. Optional.
**Acceptance:** watching an episode marks it on Trakt; importing Trakt history fills Continue Watching.

### M-PLAT-11 — Widgets and QR server setup
**Build:** Glance widget for Continue Watching (one row) + "Open Downloads"; setup QR: a
`radd://setup?url=` deep link encoded as QR, and a scanner in Setup. Depends on M-PLAT-04.
**Acceptance:** widget updates after playback; scanning a QR fills the server URL.

### M-PLAT-12 — Push notifications for new releases
**Origin:** not explicit in directives (adjacent to Telegram funnel). Mark as optional.
**Build:** FCM topic per language/industry; server sends on new work; tap opens Detail. Needs a
Firebase project; do not add if the Telegram funnel is preferred.

---

## 23. Infrastructure, federation and AI tooling

### M-INF-01 — Build the v2 projection in the live pipeline (P0)
**Origin:** ARCHITECT v2; `API_V2.md` §17.
**Build:** add `python3 Fast_Fetch/fast_fetch.py project --db <catalog>` to `auto_crawl_cron.sh`
between merge and backup; verify `cat_projection_meta` revision changes; fail the pipeline (not
silently continue) if projection fails; add a `/api/v2/manifest` health probe to `setup_check.py`.
**Acceptance:** after one cycle, `/api/v2/manifest` returns counts and `/api/v2/search` answers.

### M-INF-02 — Correct the public nginx allowlist (P0)
**Build:** allow exactly the app's routes: `/api/v1/posts`, `/api/v1/posts/`, `/api/v1/stream`,
`/api/v1/download`, `/api/v1/art`, `/api/v1/stats`, `/api/v1/app/remote-config`, `/api/v2/`,
`/client`, `/`; keep `/api/data`, `/api/fetch`, `/api/heal`, `/api/health-check`, `/api/m3u`,
`/api/v1/rules`, `/admin` denied. Keep GET-only on metadata; allow GET+HEAD on stream/download/art;
do not cache stream redirects. Add `proxy_read_timeout` > resolver time.
**Acceptance:** from a phone on mobile data: list, detail, play, download, art, remote-config all
work; operator routes return 403; `/admin` 404.

### M-INF-03 — TLS
**Build:** obtain a certificate (Let's Encrypt) for the host or put Cloudflare in front; enable
`network.release_cleartext_for_default_host=false` and ship the HTTPS URL; redirect 80→443. Needed
before any release build (brand file currently documents this).
**Acceptance:** release build reaches the API without cleartext exceptions.

### M-INF-04 — Scheduler for link health and domain rotation
**Build:** add a second systemd timer (or cron step) that calls `link_health` on a bounded sample and
`domain_resolver.probe_all_sites()` every N hours; write results to `cat_links`/registry; alert via
log. Projection then reflects measured health.
**Acceptance:** `cat_links` states change after a cycle; a dead host is skipped in play ranking.

### M-INF-05 — Multi-VM / Cloudflare federation
**Origin:** ARCHITECT 20-year blueprint; archive 70057–70162.
**Nature:** design. Build order: (1) snapshot replication to HF/R2 already exists; (2) a read-only
replica VM serves the same API from a downloaded snapshot; (3) Cloudflare Worker health-routes
between replicas; (4) DNS failover; (5) only then consider write federation (single leader, signed
catalog revisions). P2P catalog gossip (Nostr/Stremio-like) remains a design note.
**Acceptance:** killing the primary leaves the app working through a replica within 60 s.

### M-INF-06 — Site Scout bridge tracer + auto-promotion
**Build:** `Fast_Fetch/bridge_tracer.py` following 1–2 hops with hoster classification; emit a
`bridge_graph` section into the blueprint; add a `--promote` mode that writes a scaffold only after
`check_stdlib_compliance` + `compile_check` + a dry-run on 3 posts; require human review before
enabling the importer in cron.
**Acceptance:** a new site can be scouted and a scaffold produced in <60 s, with no network calls
from generated code beyond the site.

### M-INF-07 — Local AI guardrails
**Origin:** DAO Master-Disciple law.
**Build:** every generated file runs through `site_scout.check_stdlib_compliance` and
`compile_check`; add a test that greps for `requests|httpx|bs4|lxml` in generated code; log prompts
without secrets. This exists in `site_scout.py`; extend it to any future generator.
**Acceptance:** a generated importer that imports a third-party package is rejected in CI.

---

## 24. Deployment truth — what is built but unreachable

This section exists because "implemented" and "usable" diverged in production.

| # | Finding | Evidence | Impact |
|---|---|---|---|
| D-1 | Documented nginx allows only `/client`, `/api/v1/posts`, `/api/v1/stats`, `/api/v2/`; everything else `/api/` → 403 | `ORACLE_DEPLOYMENT.md:367-425` | No detail, stream, download, art, remote-config. **App is catalog-only.** |
| D-2 | `/api/v1/posts/{id}` is not in the allowlist | same | Detail screen cannot load |
| D-3 | `/api/v1/stream` and `/api/v1/download` are not allowed | same | No playback, no download |
| D-4 | `/api/v1/art` is not allowed | same | Posters/backdrops 403 unless they are absolute CDN URLs |
| D-5 | `/api/v1/app/remote-config` is not allowed | same | VIP screen shows "could not load payment details" and defaults |
| D-6 | `/api/v2/` is allowed but the projection is not built by cron | `auto_crawl_cron.sh` steps | v2 answers "unavailable" |
| D-7 | `cat_links` were observed `unchecked`, link_coverage 0.0 | prior live audit | Ranked play has no health signal |
| D-8 | No TLS; release cleartext forbidden by default | `brand.properties` `release_cleartext_for_default_host=false` | Release build cannot reach the HTTP host |
| D-9 | `vip_until` never written; no pass minted | `accounts.py:822`; no callers | VIP entitlement impossible |
| D-10 | App downloads use `/api/v1/stream`, not `/download` | `DownloadService.kt:49` comment; `DeviceDownloadsRepository` | Shortener revenue path unused |
| D-11 | WorkManager absent; sweeps stop with the process | `CacheSweeper.kt:5-6`; Gradle deps | TTL not enforced while app dead |
| D-12 | `DynamicServerDiscovery` orphan | no injection sites outside test | IP changes break installs |
| D-13 | Favorites pull never materializes rows | `SyncAccountRepository.favoritePlan` | New-device restore is empty |
| D-14 | `maintenance_mode`, `ads`, `shorteners`, flags unparsed | `VipRemoteConfig.kt:20-67` | Operator switches do nothing in app |
| D-15 | `PROJECT_MAP.md` says `/api/heal` hangs and anime returns zero | code now writes and filters | Stale documentation misleads agents |
| D-16 | `PLAYER_SPEC.md` says native subtitle delay impossible | wrapper implemented | Understates the player |
| D-17 | `Models.kt` says `type=anime` matches no row | `viewer.py:2470` handles it | Comment contradicts server |
| D-18 | Working tree dirty (105 paths); HEAD not deployed | `git status` | Repo state ≠ host state |
| D-19 | Admin token stored as static systemd literal | unit file | Token exposure risk |
| D-20 | HF token fixed in tree via env file | `auto_crawl_cron.sh` header | Verify deployed copy |

---

## 25. Prioritized build queue

**P0 — make what exists usable (days, not weeks)**
1. **M-INF-02** ~~nginx allowlist for detail/stream/download/art/remote-config~~ **done on the live
   host** — detail, stream, download and remote-config answer publicly; `art` stays denied and the app
   does not reference it (caveat 2 above). Without it the app is a catalog list.
2. **M-INF-01** add `project` to the 6-hour pipeline; verify `/api/v2/manifest`.
3. ~~**M-MON-04** point downloads at `/api/v1/download` (unlocks shortener + VIP bypass).~~
   **CLOSED 2026-10-27** — server half shipped (route reachable, `vip-pass` mintable, capability
   logged without `$args`); the client half was **declined by the owner**, because a shortener
   interstitial cannot be piped as bytes. Read that section before re-proposing it.
4. **M-MON-01** payment ledger + approval + entitlement (the only path to real VIP revenue).
5. **M-PLAT-03 / M-PLAT-04** inbound share + full deep links (cheap distribution wins).
6. **M-SRCH-01 / M-SRCH-02** local library + click-to-search (brief requirement, self-contained).
7. **M-DL-05** WorkManager sweep (keeps storage promises honest).

**P0.5 — wire what already exists (hours each, §18.1)**

| Item | Change | Unlocks |
|---|---|---|
| W-1 | Call `PlayerSessionStore.reportPlayhead(url, position, duration)` from the playback ticker | Ahead-cache, P-A-25/28 |
| W-2 | Make keep enqueue set `origin = USER_KEEP` (or call `keepNow`) and route playback through `playableUri`/`LocalMediaProxy` | Real keep-forever + offline playback, P-A-23/26/27 |
| W-3 | Pass `onPlayNextEpisode` from `NavGraph` and navigate on `PlayerEvent` | Cross-file next episode, P-A-22 |
| W-4 | Call `requestAdBreak()` at the defined seams, or delete the dead UI until a fill exists | Honest ad behaviour, P-A-24 |
| W-5 | Render `LanShareProtocol.shareUrl` + peer count in Settings/Downloads | Usable LAN share, P-A-09 |
| W-6 | Either implement two-finger vertical speed or remove the MX-parity claim | Accurate feature list, P-A-20 |
| W-7 | Add metered-connection gate to `DownloadService` and honour `mobileDataAllowed` for transfers | Data-saver promise, P-A-11 |

**P1 — close the promises already made to users**
8. **M-DL-01** Night-Owl downloads.
9. **M-DL-06** LAN share QR/receiver (the feature is 70% built).
10. **M-MON-06 / M-MON-07** maintenance UI + announcements/Telegram.
11. **M-SRCH-05** v2 search/suggest in app (after projection).
12. **M-SRCH-08** watchlist materialization.
13. **M-INF-04** link-health/domain timers.
14. **M-DL-02 / M-DL-03** SD card + data saver.
15. **M-SRCH-03** Clip & Scene Finder (highest virality, medium effort).

**P2 — platform depth and revenue expansion**
16. **M-MON-03** ad SDKs (after entitlement exists).
17. **M-MON-02** server-signed rewarded pass.
18. **M-MON-05** quality gating.
19. **M-PLAT-01** Chromecast.
20. **M-PLAT-09** online subtitles.
21. **M-SRCH-06 / M-SRCH-07** recommendations + cast/trailer.
22. **M-PLAT-05** A-B repeat, **M-PLAT-06** equalizer.
23. **M-PLAT-02** Android TV.

**P3 — long horizon**
24. **M-PLAT-07** FFmpeg decoders.
25. **M-PLAT-10** Trakt.
26. **M-INF-05** federation.
27. **M-SRCH-04** audio fingerprint (song-only, if ever).
28. **M-PLAT-11 / M-PLAT-12** widgets/QR, push.

---

## 26. Brief-named capabilities: origin audit

The brief explicitly named four capabilities. Their true origin is:

| Named capability | Found in directives? | Found in archive? | Code? | Verdict |
|---|---|---|---|---|
| Video click search from user device | No | No | No | **Never specified before this inventory** |
| Local device media scanning | No | No (MediaStore only used to *write* downloads) | Write-only MediaStore in `DownloadService` | **Never specified as a library feature** |
| Reverse search | Yes — MENTOR Priority 5 Desi Cine-Finder | Yes — Clip & Scene Finder architecture, lines ~81598–81983 | No | **Specified, never built** |
| Audio track matcher | Yes — dual-audio auto-select | Yes — archive feature 6 and 71166 | Yes — `AudioTrackMatcher.kt` (language selection) | **Built, but it is not acoustic fingerprinting** |
| P2P offline sharing | Yes — DAO/ARCHITECT notes | Yes — archive feature 2 | Partial — LAN HTTP server, no UX/transfer | **Half built** |
| Sleep timer | Yes — MX changelog reference | Yes — archive feature 6 | Yes — with fade | **Built** |

**Recommendation:** treat "click-to-search", "local media scan" and "reverse search" as one coherent
feature family (Part III §19) rather than three disconnected additions; they share the same scanner,
title cleaner and matcher.

---

## 27. Feature-to-source trace (highlights)

| Feature | First/primary source | Implementation |
|---|---|---|
| 302 zero-bandwidth streaming | `MASTER_ARCHITECT_DIRECTIVE.md` | `viewer.py:3069` |
| Provenance redaction / signed handles | ARCHITECT; `API_V2.md` §16 | `redact.py` |
| Per-site staging DBs | root `AGENTS.md` rule 9 | 18 importers + `merge_catalogs` |
| Staging → unified merge | `merge_catalogs.py` docs | `merge_catalogs.py:244` |
| 18-site fleet | `SITES.md`; archive | importers |
| Site Scout | `SITE_SCOUT_SPEC.md` | `site_scout.py` |
| FTS5 | ARCHITECT; archive 69079 | `catalog_api.py:1133` (v2) |
| Netflix UI / hero rails | ARCHITECT; MENTOR §2 | `HomeScreen`, `HeroCarousel` |
| MX gestures | `PLAYER_SPEC.md` §2.1 | `PlayerGestures.kt` |
| Pure cinema | MENTOR §PURE_CINEMA; archive 83 | `PlayerScreen.kt:361` |
| Sleep timer + fade | MX; archive 71163 | `SleepTimer.kt` |
| Subtitle offset | MENTOR feature A | `SubtitleOffsetPipeline.kt` |
| Audio language auto-select | archive 71166 | `AudioTrackMatcher.kt` |
| Audio boost | MENTOR; archive | `AudioBoost.kt` |
| Binge preloader | MENTOR; archive | `BingePreloader.kt` (resolve-only, P-A-17) |
| Quality ladder / best quality | MENTOR "Play Best Quality" | `QualityLadder.kt` |
| Silent failover | `API_V2.md` §5; PLAYER_SPEC | `PlaybackRecovery.kt` |
| Pack offsets | PLAYER_SPEC §3.3; API_V2 §8 | `EpisodeOffsets.kt` |
| Stream→download zero waste | Owner idea; `CACHE_SPEC.md` | `HandoffAccounting.kt` (policy only, P-A-26) |
| Ahead-of-playback cache | `CACHE_SPEC.md` | `AheadFetcher.kt` (engine only, P-A-25) |
| TTL 3/6 h | `CACHE_SPEC.md` | `TtlPolicy.kt` |
| LAN P2P share | archive feature 2 | `LanShareServer.kt` (no URL UI, P-A-09) |
| Night-Owl downloads | archive feature 1 | ❌ missing |
| SD-card priority | archive feature 3 | ❌ missing |
| Data meter / saver | archive feature 5 | 🟡 sizes only |
| Shortener waterfall | MONETIZATION §shorteners | server code present but **retired by the owner's standing directive**; app never calls the route. Measured on the live catalog 2026-10-29 21:40: `app_remote_config` = 1 row, both shortener token columns **empty**, `cat_shortened_links` = **0 rows**. **The retirement is enforced in the pushed code (`admin_panel.py:1327-1346` refuses every target unless `feature_link_shorteners=1`), NOT in what is deployed** — `/opt/radd-stream/Fast_Fetch/admin_panel.py` (mtime 10-27 17:25) contains no occurrence of that flag, and the live `app_remote_config` table has 18 columns, i.e. the flag column is absent. On production today the directive holds only because the token columns happen to be empty |
| Rewarded VIP | MONETIZATION | local pass only |
| Payments JazzCash/Easypaisa/Raast | OPERATOR guide | handles ✅, ledger ❌ |
| Telegram funnel | OPERATOR guide Step 5 | ❌ |
| USDT arbitrage | MONETIZATION §5 | operational only |
| Force update | MONETIZATION remote control | ✅ |
| Maintenance mode | MONETIZATION remote control | server ✅, app ❌ |
| Chromecast | admin flag | ❌ |
| Trakt | MENTOR feature A | ❌ |
| Online subtitles | MENTOR feature A | ❌ |
| Clip & Scene Finder | archive 2026-10-25 | ❌ |
| Multi-VM federation | ARCHITECT blueprint | ❌ design |
| Local AI disciple | DAO law | ✅ `site_scout` + `disciple.py` |

---

## Appendix A — Endpoint inventory (current code)

| Method | Path | Port | Purpose | App uses |
|---|---|---|---|---|
| GET | `/api/v1/posts` | both | list + facets | yes |
| GET | `/api/v1/posts/{id}` | both | detail | yes |
| GET | `/api/v1/stream` | both | 302 play / metadata | yes |
| GET | `/api/v1/download` | both | 302 download + shortener | **no (gap)** |
| GET | `/api/v1/art` | both | artwork | yes (as URL) |
| GET | `/api/v1/stats` | both | counts | yes |
| GET | `/api/v1/app/remote-config` | both | prices/handles/ads/flags | partially |
| GET | `/api/v1/rules` | operator | unwrapping recipes | no |
| GET | `/api/data`, `/api/sitemap`, `/api/fetch`, `/api/m3u` | operator | dashboard | no |
| GET | `/api/health-check`, `/api/heal` | operator | link diagnosis | no |
| GET | `/client`, `/mobile`, `/` | both | PWA/dashboard | no |
| GET | `/api/v2/manifest|browse|search|suggest|works|episodes|releases|sync|stats` | both | v2 read surface | no |
| POST | `/api/v2/play` | both | ranked bundle | no |
| POST | `/api/v2/links/{id}/report` | both | health report | no |
| POST | `/api/v2/episodes/{id}/offset` | both | learned offset | no |
| POST | `/api/v2/account` | both | mint key | yes |
| GET/DELETE | `/api/v2/account` | both | read/revoke | yes |
| GET/POST | `/api/v2/account/favorites[/remove]` | both | watchlist | push only |
| GET/POST | `/api/v2/account/progress[/remove]` | both | resume | yes |
| GET/POST | `/admin/*` | loopback only | operator | no |

---

## Appendix B — Test and artifact counts

| Item | Count | Notes |
|---|---|---|
| Backend test modules | 44 | stdlib-only |
| Backend `def test_` | 1,039 | static count, not re-run here |
| Backend importers | 18 | per-site |
| Android Kotlin files | 132 | `app/src/main` |
| Android test files | **81** (80 with `@Test`) | re-counted 2026-10-29 under `App/app/src/test`; the row previously said 47/46 |
| Android JVM tests | **637** `@Test` annotations | static count of the same tree, CI runs them; the row previously said 381 |
| Android routes | 11 | all wired |
| Cache test suites | 12 | ledger, TTL, eviction, scheduler, handoff, HLS, wiring |
| Player test suites | 13 | gestures, audio, sleep, failover, ladder, ads, subtitles |
| Admin settings fields | **17** | re-counted 2026-10-29 from `admin_panel.MONETIZATION_FIELDS` (`:924-953`); the row previously said 15. Payments handles (4), VIP prices (2), ad/shortener ids+tokens (4), `feature_link_shorteners`, `maintenance_mode`, `apk_update_url`, three feature flags, `feature_quality_gate`. **Nothing in it covers the owner's engagement pillars** — no ad-cadence caps (1 pre-roll/25 min, 1 native card/12 posters, 1 app-open/4 h), no coin-wallet balance or ledger, no 7-day streak, no PKR micro-pass ladder (₨20/₨50/₨250). That is gap M-MON, not a doc error |

---

## Appendix C — What each directive contributed

| Directive | Distinctive requirements |
|---|---|
| `DAO.md` | zero-cost, zero-bandwidth, immortal resilience; multi-source redundancy; auto-healing; stdlib only; adult flag; local AI disciple |
| `MASTER_ARCHITECT_DIRECTIVE.md` | 302 handoff; staging isolation; provenance redaction; multi-VM/Cloudflare/HF; FTS5; Netflix UI; MX parity; codecs |
| `SENIOR_MENTOR_DIRECTIVE_QODER.md` | real DB swap; direct media only; TMDB art; title sanitization; 400dp hero; PURE_CINEMA; Play Best Quality; features A–I; Desi Cine-Finder; admin/monetization |
| `MASTER_ADMIN_MONETIZATION_SPEC.md` | admin tables; HMAC anti-crack; payment ledger; free/VIP matrix; shortener waterfall; 24h pass; quality gating; USDT arbitrage; pre-cached ads |
| `App/docs/PLAN.md` | phase roadmap; originally deferred continue-watching, downloads, deep links, cast, multi-server, TV, admin, anime — several now built |
| `PAKISTAN_OPERATOR_GUIDE.md` | Lahore context; PKR 200/1500; JazzCash/Easypaisa/Raast; manual TID approval; Telegram funnel; remote control |
| `SITE_SCOUT_SPEC.md` | four-stage scraper synthesis; CMS fingerprint; DOM archaeology; redirect graph; AI codegen |
| `PLAYER_SPEC.md` | verified Media3 1.3.1 capability matrix; honest "No" list (audio delay, thumbnails, downmix, SW codecs) |
| `CACHE_SPEC.md` | byte ledger; range resume; HLS ahead buffer; 3/6h TTL; eviction; loopback 206; zero-waste handoff |

---

## 28. Final statement

Nothing in this document is a promise that a feature works on a phone. It is a map of what the
repository contains, what the archive asked for, and exactly where the two differ.

The single most valuable next action is not a new feature: it is **making the already-built app
reachable** by correcting the public allowlist and building the v2 projection (P0-1, P0-2). The second
is **closing the last-mile wiring gaps in §18.1**, because a tested cache engine that never receives a
playhead, a keep that expires, and a share server with no address are, to the viewer, missing features.
After that, the brief's named search capabilities (local scan, click-to-search, reverse search) are the
highest-leverage additions because they are the only part of the product that no competitor in this
catalog space has.

Status summary: the repository is broad and its low-level engines are unusually well tested; its
weaknesses are integration seams, deployment configuration, and monetization transactions — not
missing algorithmic work.
