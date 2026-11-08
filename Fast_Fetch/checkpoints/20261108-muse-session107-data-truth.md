# Session 107 — data-truth (Phase D) — 2026-11-08

Branch `data-truth-20261108` from `089b2000` (Session 106). Author rehanradd.
Builder does not push, deploy, or touch the live DB or live tree — the parent
pushes and gates. All heavy verification ran against copies on the VM, never
the live catalog. VM copy: `/home/ubuntu/session107/catalog-copy.db` (6.0G,
copied 16:30 PKT 2026-11-08 from `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`).
New code for VM runs: `/home/ubuntu/session107/ff107/Fast_Fetch/` (tar
`ff107.tar.gz`, refreshed after the item-6 edits).

## 1. WRONG-FILM FIX (P0) — DONE

`cat_id_map` is cat→cat, NOT legacy→cat (schema `catalog_v2.py:434`,
`(kind, old_id, new_id, rev)`; `_record_id_map` writes only rows whose id
changed between rebuilds). VM copy proves it: kinds link 3,367,870 / release
1,301,450 / work 66,630; **`ledger_release` rows: 0**. Legacy release 500000
= post 55458, katmoviehd, "Arthur's Whisky" (origin_url
`https://new.katmoviehd.top/arthurs-whisky-2024-full-movie-hindi-dubbed`);
**cat release 500000 = work 39848, "Last Night in Soho (2021)
Hindi-English [480p]", vegamovies** — the wrong film, confirmed live on the
copy. True target: **cat work 54237 = "Arthur's Whisky" (2024), cat release
598344 = "Online Stream (1XPlayer)"** with the same label + origin_url as
legacy 500000 (sibling prints 598345–598348 are the "> Download Link <"
prints). Caution: ledger post 54242 = "Killjoy Terrify Hindi Dubbed", NOT
Arthur's Whisky — ledger and cat id universes collide.

Code: `catalog_v2.py` — `_project_pages` takes new `catalog_rev` kwarg;
after the new/dup if/else where `release_id` is determined, writes
changed-only `INSERT OR REPLACE INTO cat_id_map (kind, old_id, new_id, rev)
VALUES ('ledger_release', ...)` + `counters["ledger_release_mapped"]`;
`project()` passes `catalog_rev` and reports the count in its summary.
`catalog_api.py` — new `translate_legacy_release_id(conn, release_id)`:
`SELECT new_id FROM cat_id_map WHERE kind='ledger_release' AND old_id=?
ORDER BY rev DESC LIMIT 1`, verifies the target exists in `cat_releases`,
falls back to the id as given on no row / missing table / stale target /
non-numeric input; never raises. Hooked at the top of `play_bundle` and at
the `api_v2.py` releases route (`releases/{id}`); `release_detail` itself
stays cat-native (no double-translation).

Tests (7 item-1 tests, all passing, inside classes totalling 17 OK):
`test_catalog_v2.py::RollupAndSafetyTests` —
`test_projector_writes_ledger_release_map_for_renumbered_prints` (dup prints
collapse; map row for the renumbered ledger id; `ledger_release_mapped == 1`)
+ `test_legacy_release_id_plays_the_right_film_not_the_number` (Alpha/Beta
fixture: legacy 3 is Alpha 720p, cat print 3 is Beta 1080p; raw
`release_detail(3)` returns Beta, `play_bundle(3)` returns Alpha 720p);
`test_catalog_api.py::LegacyReleaseTranslationTests` (5 tests: 500000
translates through a hand-written map row to the Dune 1080p print and
`play_bundle(500000)` serves it; unmapped 999999 falls back; stale target
falls back; non-numeric returned unchanged; missing `cat_id_map` table falls
back).

Known collision caveat: map-first would redirect a genuine cat id that also
exists as a legacy id; the app (only live v2-play caller) sends legacy ids,
so map-first + fallback is correct for live traffic; a future explicit
id-universe parameter is the clean fix. Work-id translation (same ledger/cat
split on the works route) is NOT built — follow-up.

Regression caught and fixed in this session (item 6's work): the translator
broke `test_catalog_api.py::PlayBundleTests.test_bundle_for_an_enumerated_episode_uses_the_learned_pack_offset`
— it called `play_bundle` with a cat print id that collides with a mapped
ledger id in the fixture. Verified the test passes on the base commit and
fails with the translator: `play_bundle` is legacy-in by design (its only
production caller is `api_v2.route_play`, which passes the app's legacy id;
cat-native callers use `release_detail`). The test now passes the pack's
ledger release id and asserts the bundle serves the pack print itself
(`bundle["release_id"] == pack["id"]`).

## 2. HTTP-0 RETRY / NO-POISON — DONE

Code (`fast_fetch.py`): `_is_transport_verdict(verdict)`: `failure ==
"transport"` OR `http_status == 0` (NOT `probe_error` — that is
`_stage2_probe`'s own exception marker and the generic failure fixture;
treating it as transport would stop recording real failures). One retry
inside `_stage2_probe` on a transport verdict (after the existing
`blocked`+referer retry) and one retry at the Stage-1 cached probe site
(`_ch_probe`). `_last_failure_verdict` tracked (init None; set at Stage-1
cached probe fail, Stage-2 cached probe fail, after the unwrap chain from
the last branch `verdict` / `stage1_result`, and from the fresh-probe verdict
when rejected). Every `_record_resolve_failure` call guarded: Stage-1
cached probe fail, Stage-2 cached probe fail, voe/vidhide elses, and the
fall-through (skip when `_is_transport_verdict(_last_failure_verdict)`).
`verdict = None` init added before the dispatch chain.

Tests (in `test_database.py`, 201 OK, 1 skipped): Stage-2 probe retries
once on transport then succeeds (real `_stage2_probe`, `probe_media`
side_effect [transport, success], call_count 2); Stage-1 probe retries once
on transport then succeeds (fixture URL must be a pixeldrain **API** URL
`https://pixeldrain.com/api/file/...` — a `/u/` URL IS a bridge URL per
`is_bridge_url`, which sets `needs_refresh=True` and skips Stage-1
entirely); transport twice → no negative-cache row (all three columns
NULL); stale-version row re-probed; current-version row still refuses. Two
existing fixtures updated (raw SQL UPDATEs now stamp
`failure_resolver_v = fast_fetch.RESOLVER_VERSION`):
`test_all_siblings_negative_cached_refuses_fast_with_its_own_reason` and
`test_failover_prefilter_skips_a_recorded_sibling_and_serves_the_live_one`
— both failed before the stamp (NULL version = stale by design) and pass
after. All 7 negative-cache tests pass.

## 3. MOVIEBOX IMPORTER FIX — DONE

Code (`importers/import_themoviebox.py`): new `_detail_source(detail_url)`
— one source per declared release (`service` themoviebox, `playback_type`
"url", `source_url` = `final_url` = detail URL, `status` active,
`is_temporary` 0). `_declared_releases(renditions, title, audio,
detail_url=None)` now attaches that source; series season releases store
`?se=<season>&ep=1` (proven live: se=1&ep=0 and se=0&ep=0 return 0 streams,
se=1&ep=1 returns 2 free streams on "Sistas"); movies take the bare detail
URL. `_enrich_with_declared_media` passes `record["url"]` through.
Docstrings updated (`parse_page`, `harvest_catalog`, `_resource_renditions`,
crawl_pending `metadata_only` comment).

Tests: `importers/test_themoviebox_import.py` 53 OK (updated:
`test_tiers_are_recorded_as_releases_with_detail_url_sources`,
`test_harvest_writes_rows_with_detail_url_sources`,
`test_metadata_only_pages_are_crawled_not_parked` now `with_media` 1 /
`metadata_only` 0; NEW
`test_series_season_release_carries_se_and_ep_one`);
`importers/test_themoviebox_links.py` 7 OK (renamed the rendition test to
assert detail-URL sources; MirrorTests now filter the mirror source among
the 20 detail sources); `importers/test_themoviebox_detail_api.py` 18 OK
(renamed the tier/export tests to assert 20 detail-URL sources; the trailer
test asserts the trailer URL is absent, not that sources are empty).
`test_themoviebox_import.py` registered in `backend-ci.yml` as a 🧪 step
(54→55 steps) and the stale workflow comment above
`test_themoviebox_links.py` fixed.

VM verification (new code, live page): Sistas detail page
`https://themoviebox.xyz/detail/sistas-WvtmA9qQcd1` → 1 record, 26
releases, **26 detail-URL sources** (`?se=N&ep=1`), export totals
`posts_written 1, releases_written 26, sources_written 26` into scratch DB
`mb-scratch2.db`. Note: the first two verify runs printed 0 sources because
the verify script pointed at the live tree's OLD code
(`/opt/radd-stream/Fast_Fetch`) — a stale-script artifact, re-run clean
with the new code; the traced run shows `_declared_releases` called with
the correct detail URL. Also: the real feed's page-1 items carry no
renditions (the `resource` node lives on the detail payload, not the feed
item), so a feed-only harvest yields 0 releases — renditions arrive at
crawl time, which is where the fix pays off.

Known inefficiency (follow-up, not this item): MovieBox detail URLs are NOT
bridge URLs (`is_bridge_url` False), so the resolver pays one wasted
Stage-2 cached probe on the detail page per press before the dispatch
unwraps (the transient `probe_failed` record is cleared by the same press's
success path).

## 4. TEST_REDACT FLAKE — DONE + VERIFIED

`test_redact.py::test_token_round_trip_and_tamper_rejection` — replaced the
probabilistic `assertNotIn(str(number), token)` with structural assertions:
`len(token) == 28` (v2 handle = 21 bytes, base64url without padding),
`assertNotEqual(token, str(number))`, `assertFalse(token.isdigit())`,
round-trip `parse_token` incl. `signed_only=True`. Tamper-rejection
assertions unchanged (forged suffix, wrong secret, `"not-a-token"`, `""`).
Verified: 10/10 consecutive runs of the single test + full `test_redact`
module 80 tests OK (32.5s; re-run in this session: 80 OK, 38.9s).

## 5. NEGATIVE-CACHE INVALIDATION — DONE

Code (`fast_fetch.py`): module constant `RESOLVER_VERSION = 1` (bump when a
new unwrapper lands or an existing unwrapper's coverage materially
changes). New nullable column `failure_resolver_v INTEGER DEFAULT NULL` on
`download_sources`: added to the CREATE TABLE DDL (after `failure_class`)
AND the migration block (same PRAGMA+ALTER pattern).
`_record_resolve_failure` stamps the current version; `_clear_resolve_failure`
clears it (inline success-path clears leave the version stale-but-unreadable
— every success clears `last_failed_at`, which gates the version read).
Hit-site change: a fresh record whose version is NULL (pre-versioning =
version 0) or < current is cleared and re-probed once; a current-version
record still refuses. Pre-filter query gains `failure_resolver_v IS NOT NULL
AND failure_resolver_v >=?` so stale-version siblings are NOT skipped
(fail-open `except Exception` already covers an unmigrated DB).

Tests: `test_stale_resolver_version_row_is_reprobed` +
`test_current_resolver_version_row_still_refuses` (both in
`test_database.py`, 201 OK). Applies uniformly to all failure classes.

## 6. MULTIMOVIES DETAIL MEASURED-PLAYABLE — DONE

Mechanism (verified in code): `_EMBED_SERVICES` (`catalog_v2.py:108`)
includes cracked services, and `classify_link` returned `("embed",
"webview")` for them → `_link_group` (`catalog_api.py:652`) maps
playability `webview` → `_GROUP_WEBVIEW` > `_GROUP_RESOLVE` (1) → v2
`_link_view` (`catalog_api.py:674`) `playable` False. V1 `viewer.link_view`
(`viewer.py:205`) maps `playback_type "iframe"` → kind `"external"` →
playable False.

Code: new `_SERVER_RESOLVABLE_SERVICES` frozenset in `catalog_v2.py` next
to `_EMBED_SERVICES` (13 services, each earned by a resolver branch):
cineverse, vidrift, vidbolt, filmu, iqsmart (Stage-1 backends modiplay,
vidrift, vidbolt, vidly, streamhg), streamtape, stream, streamwish,
mixdrop, voe, vidhide, 1xplayer, uploadflix (Stage-2 `elif` keyed on the
service name, Sessions 103/104b). `classify_link` returns `("embed",
"resolve_required")` for a service in the set, in BOTH embed branches
(file-like and embed-shape); URL-shape embeds (generic `/e/` URLs, unknown
service) stay `webview`. `viewer.link_view`: `playback_type "iframe"` +
service in the set → kind `"resolve"` not `"external"` (service read from
the raw row with the `"service" in row.keys()` guard, so partial test rows
still work; the service name never reaches the response — only the kind
changes, so no new public field and no provenance leak; `redact.py` stays
the only path to the client).

Grounding (VM copy, not guesses): cineverse rows sit on
`rozgarlelo.modiplay.xyz` (70,045) + `cineverse.modiplay.xyz` (5) → Stage-1
modiplay backend; filmu `embed.filmu.in` 69,782 → vidly; iqsmart
`streams.iqsmartgames.com` 26,918 → streamhg; vidbolt `vidbolt.xyz`
69,782; vidrift `embed.vidrift.net` 69,782. Multimovies service census
(probe2): iframe — cineverse 44,508; filmu 44,306; vidbolt 44,306; vidout
44,306; vidrift 44,306; nexus 44,305; gd-mirror 40,830; iqsmart 16,839;
filesforever-mirror 8,939; gdmirror 4,341; screenscape 4,210; nxstream
3,107; vidzee-mirror 3,101; modiplay 2,469; peachify-mirror 1,927;
nhd-stream 1,784.

Deliberately out: vidout (its playlist host vidmmo.com does not resolve on
VM DNS — item 7, unprovable from here); vidoza/doodstream/filemoon (host
down / TCP reset / stdlib-blocked crypto); every other embed service, which
has no server-side unwrapper. `mobilejsr` sits in
`_DOWNLOAD_ONLY_SERVICES` (a download host family) and stays out.
vidhide and uploadflix are NOT in `_EMBED_SERVICES`, so their URLs fall
through to `cloud_page`/`resolve_required` by shape — their set membership
only changes the v1 iframe mapping (pinned by a dedicated test).

Measurement semantics (no new code needed — documented here):
`_link_state_of` (`catalog_v2.py:1365`) already encodes measured vs
unprobed — status active/unverified/"" with NO probe evidence → state
`"unchecked"`, WITH evidence → `"active"`; `_link_view.playable` already
respects `state not in UNPLAYABLE_STATES` and exposes `"measured"` +
`"last_evidence_at"`. Honest reading: playable=True on an unmeasured link
means "resolvable by kind; the press is the probe"; playable=False on a
measured-dead link means "probed dead".

Tests: `test_catalog_v2.py` 103 OK (+4 new: resolvable embeds →
resolve_required across 11 services; file-like URL of a resolvable embed
still needs the resolver; vidhide/uploadflix shape test; vidout stays
webview); `test_tiers.py` 38 OK (+2 new: iframe + resolvable service →
resolve + playable, service key absent from the view; iframe + vidout/vidsrc
→ external + not playable); `test_catalog_api.py` 132 OK (incl. the
pack-offset test updated for the item-1 contract, see §1).

## 7. VIDMMO DNS CHECK (VM) — DONE, DOES NOT RESOLVE

probe2: `getent rc=2`, `socket.getaddrinfo` raises, `curl https 000`,
`curl http 000`. **vidmmo.com does not resolve on VM DNS** (same as
Session 102). Route: vidout/vidmmo links (44,306 multimovies rows) stay
unresolvable from the VM; the vidout branch cannot be proven live. Recorded
honestly; no pass faked. vidout excluded from `_SERVER_RESOLVABLE_SERVICES`
(item 6).

## 8. PROJECTION REBUILD rev 4 — MEASURE ONLY — RUNNING, NOT YET VERIFIED

Launched on the VM copy with the NEW code (items 1 + 6) from a scratch dir:
`python3 -u /home/ubuntu/session107/ff107/Fast_Fetch/catalog_v2.py
/home/ubuntu/session107/catalog-copy.db --rev 4`, VM PID **1198234**
(wrapper bash PID 1198226), started **17:26:05 PKT 2026-11-08**
(12:26:05 UTC), log `/home/ubuntu/session107/rev4-rebuild.log`
(start marker `/home/ubuntu/session107/rev4-rebuild-start.txt`). VM
guardrail at launch: load 0.04, MemAvailable 10394 MB, swap free 4927 MB,
disk 105G free. Expected wall time ~2.7h (rev 3 took 9,770.83s) → finish
~20:10 PKT. Process confirmed alive and working (37% CPU, 3:28 CPU time at
~9 min in); log was 0 bytes at that check (no stage line printed yet).

**Verification is owed by a follow-up once it finishes:** wall time from
the log, post/work counts, rev marker, sample posts now visible to v2,
before/after playability counts from item 6, `ledger_release_mapped` count
+ spot-check 500000→598344 in the new map. Do NOT apply to live — the live
apply is a separate gated step the parent decides.

Rev-3 baseline for comparison (from the copy's `cat_projection_meta`):
`projected_at` 1792942873 = 2026-10-25, build 9,770.83s ≈ 2.7h; posts
130,016 at build vs 150,799 now (+20,783, +16%); works 116,922; releases
1,383,752; links 3,783,959; `links_by_state` all unchecked (3,456,460);
`link_coverage` 0.0; `id_map_rows` 4,735,950.

## 9. SEARCH INSTABILITY (server side) — FINDINGS, NO CODE CHANGE

The endpoint is deterministic — `viewer.api_v1_get_posts`
(`viewer.py:3017`): `WHERE (clean_title LIKE %q% OR title LIKE %q% OR
slug LIKE %q%)` + `redact.adult_clause("p")` + panel hides; `GROUP BY p.id`,
default `ORDER BY p.id DESC`, `LIMIT? OFFSET?`; total via `COUNT(*)` with
the same WHERE; fuzzy fallback only when total == 0. No RANDOM, no cache.

Probe3 (real function, on the copy): **search "Ali Baba" #1 49.415s
(cold), #2 1.095s; totals 17/17, same-ids True** — exactly the 17 the user
first saw. Probe2 SQL count also 17.

Mechanism: cold-cache search takes ~49s, far beyond nginx's 15s read
timeout on `/api/v1/posts` → the app's `SearchViewModel` catch block does
`rawResults = emptyList()` + `resultCount = 0` on ANY search error — so "17
results then 0" is exactly what the user sees when the SECOND search
request FAILS (times out), not when it returns 0 rows. Detail taps: app
passes `post.id` (Int) → `GET /api/v1/posts/{id}` (`viewer.py:4212` → 404
"Post not found" when None); nginx `location /api/v1/posts` is a prefix
location, so `/api/v1/posts/{id}` IS forwarded;
`CatalogRepository.getPostDetail` collapses a 404 and a dead socket into
the same `null`. Device reproduction is a later phase — no device result
claimed here.

## 10. V2/PLAY 70s HANG — MEASURED, CAUSE STILL UNKNOWN, NO CODE CHANGE

`route_play` (`api_v2.py:1713`) does NO resolution — `play_bundle` is pure
SQL, then `apply_prefer` + JSON. Server is `ThreadedHTTPServer`
(`viewer.py:3610`) — threaded, one slow request does not block others.
`get_db` (`fast_fetch.py:1159`): `sqlite3.connect(timeout=30.0)`, WAL,
`busy_timeout = 30000` — WAL readers do not block on writers, so a DB lock
cannot hang a read 70s. Play-path indexes exist
(`idx_cat_links_release`, `idx_cat_releases_work`, `idx_cat_works_title`).

Probe3 measurements: release_detail Mentalist 0.016s, play_bundle
Mentalist 0.020s, release_detail legacy 500000 0.028s, play_bundle legacy
500000 0.031s; EXPLAIN shows indexed plans (`SEARCH cat_links USING INDEX
idx_cat_links_release`, `SEARCH r USING INTEGER PRIMARY KEY`).

Hang cause still unknown; working hypothesis (confirm or kill by
measurement): cold page cache after restart + a concurrent heavy request
(stats took 13.3s live) starving the play request under the GIL — NOT a
code defect; if timings are fast (they are), record it as operational
(pre-warm after restart), not code. The 49s cold search proves the box CAN
stall a request past nginx timeouts under cold cache (play route's nginx
timeout is 60s; the observed hang was 70s with curl timeout). No fix
attempted on an unproven cause.

## 11. PANEL DRIFT FLAG — DONE (panel code, NOT deployed)

Backend half is the panel's own store (the panel lives outside the repo):
`admin-v2/admin_v2/live_stores.py` — `catalog_counts()` gains
`projection_posts` (from `cat_projection_meta.posts`, the projection-time
post count); NEW `LiveStores.projection_drift()` returns rev, age_h,
ledger_posts, projected_posts, drift_posts, drift_pct, link_coverage,
unchecked_links, `stale` + `reasons`. Stale when age > 48h, or more than
1000 posts arrived — or left — since the build, or when no projection
exists at all. Link coverage is reported for context but never sets stale:
0.0 is the steady state (no probe has ever run); flagging it would leave
the alert permanently on. Read-only; a missing meta table yields "no
projection", never an error.
`admin-v2/admin_v2/services.py` — `data_health()` gains `"drift"`.
`admin-v2/admin_v2/server.py` — `_page_data_health` renders a "Projection
drift" warning card first (badge + reasons + ledger/projected/drift
counts, "unknown" when the meta lacks the posts key) when stale, and the
Projection-truth card now shows ledger vs projected posts always.

Tests: panel suite **200 OK** (was 195; +5 new in
`tests/test_live_real.py`: fresh fixture not stale; 100h-old age stale;
1,001 new posts stale with "1,001 posts arrived"; deleted meta stale with
"no projection has ever been built"; page shows the drift alert when stale
+ `data_health` carries the drift dict). Run as `python3 -m unittest
discover -s tests` from the admin-v2 dir (153.9s). **Panel changes are NOT
deployed** — the parent deploys panel changes separately (tar + restart).

## 12. CROSS-KEY ADULT RESIDUAL — DESIGN ONLY (measured, not applied)

`generate_canonical_key` (`fast_fetch.py:587`) is Python regex-based — the
re-key cannot be pure SQL; it needs a Python pass.

Probe3 measurements on the copy (transaction ROLLED BACK, posts count
150,799 after rollback — sanity OK): **blast radius 69,773 rows** (key
would change — matches the 2026-10-29 measurement exactly); **cross-key
residual public rows 3,310 under 2,148 distinct title/year keys** (probe3
method: public rows sharing a (clean_title casefold, year) with a flagged
twin under a DIFFERENT canonical_key — broader than the fold's post-apply
residual of 1,188, which used the fold's key-based method after hiding 480
rows; report both numbers with their methods, do not conflate them);
**re-key UPDATE runtime 0.183s for 69,773 rows** — the UPDATE is cheap;
the projection rebuild (~2.7h) dominates any re-key migration.

Rollback design: journal `(id, canonical_key)` pairs first, update in
batches, re-run `inherit_key_adult`, rebuild projection (cat ids churn —
rev bump), rollback = restore keys from journal + re-project. Do NOT apply
to live, do NOT run `--apply` of anything. No code written for this item.

## Gate

Full backend gate (`~/workspace/run-backend-gate.py`, reads the module list
from `backend-ci.yml`): **51/51 modules PASS, FAILED MODULES: 0** on the
re-run (288s). First run was 50/51: `test_docs_invariants.py` failed
because registering `importers/test_themoviebox_import.py` in the workflow
without removing it from the `UNREGISTERED` debt list in
`test_docs_invariants.py` is itself a tested violation ("now in the gate;
delete from UNREGISTERED") — a real omission, not a flake. Fixed by
deleting that one entry; the module then passed solo twice (22 tests OK
each time) and the full gate re-ran clean.

Note the gate script's count: it reads only `python3 -S
Fast_Fetch/test_*.py` run lines, so it covers 51 modules; the workflow
carries 55 🧪 steps — the 4 extra are the `importers/` modules, which the
script's regex misses (pre-existing gap, not this session's to fix in the
parent's script). All 4 pass solo locally: `test_dub_collision_census` 13
OK, `test_themoviebox_links` 7 OK, `test_themoviebox_detail_api` 18 OK,
`test_themoviebox_import` 53 OK. Key module counts from this session:
`test_database` 201 OK (1 skipped), `test_catalog_v2` 103 OK,
`test_catalog_api` 132 OK, `test_tiers` 38 OK, `test_api_v2` 46 OK,
`test_redact` 80 OK.

Panel suite (admin-v2, separate, NOT in this gate): **200 OK** (see §11).

## Files changed (workspace clone, branch data-truth-20261108)

- `Fast_Fetch/catalog_v2.py` — item 1 (ledger_release map write) + item 6
  (`_SERVER_RESOLVABLE_SERVICES`, `classify_link`).
- `Fast_Fetch/catalog_api.py` — item 1 (`translate_legacy_release_id`,
  `play_bundle` + releases-route hooks).
- `Fast_Fetch/api_v2.py` — item 1 (releases-route hook).
- `Fast_Fetch/fast_fetch.py` — item 2 (transport retry + no-poison) +
  item 5 (`RESOLVER_VERSION`, `failure_resolver_v`).
- `Fast_Fetch/test_database.py` — items 2 + 5 tests + 2 fixture stamps.
- `Fast_Fetch/test_redact.py` — item 4 (structural token assertions).
- `Fast_Fetch/test_catalog_v2.py` — items 1 + 6 tests.
- `Fast_Fetch/test_catalog_api.py` — items 1 + 6 tests (incl. pack-offset
  test moved to the legacy-in contract).
- `Fast_Fetch/test_tiers.py` — item 6 tests (v1 link_view).
- `Fast_Fetch/importers/import_themoviebox.py` — item 3 (detail-URL sources,
  `?se=<season>&ep=1` for series).
- `Fast_Fetch/importers/test_themoviebox_import.py` — item 3 tests.
- `Fast_Fetch/importers/test_themoviebox_links.py` — item 3 tests.
- `Fast_Fetch/importers/test_themoviebox_detail_api.py` — item 3 tests.
- `.github/workflows/backend-ci.yml` — registered
  `importers/test_themoviebox_import.py` (54→55 🧪 steps).
- `Fast_Fetch/checkpoints/20261108-muse-session107-data-truth.md` (this file).
- `Fast_Fetch/checkpoints/README.md` + `Fast_Fetch/CONTINUITY.md` (106 → 107).
- Panel (NOT a git repo; deploy by tar + restart, NOT deployed here):
  `admin-v2/admin_v2/{live_stores,services,server}.py`,
  `admin-v2/tests/test_live_real.py` — item 11.

## NOT done / follow-ups

- Item 8 verification (rev-4 rebuild wall time + counts + 500000→598344
  spot-check + before/after playability) — rebuild running, PID 1198234,
  started 17:26:05 PKT, expected ~20:10 PKT; a follow-up reads
  `/home/ubuntu/session107/rev4-rebuild.log`.
- Item 9 device reproduction ("Ali Baba" search + result taps on the
  emulator) — Phase 5.
- Item 10 hang cause — still unknown; hypothesis only (cold cache + GIL
  starvation). Pre-warm after restart is the operational mitigation.
- Item 1 follow-up: work-id translation (ledger/cat split on the works
  route); explicit id-universe parameter as the clean fix for the map-first
  collision.
- Item 3 follow-up: MovieBox detail URLs are not bridge URLs — one wasted
  Stage-2 cached probe per press.
- Item 6 follow-up: `mobilejsr` is a download family, deliberately out of
  the resolvable set; re-check if its watch path ever becomes server-side.
- Item 11 follow-up: none — the panel half fits and is built; deployment
  is the parent's separate step.
- Item 12: re-key migration is designed + measured only; needs a gated
  decision before any apply.
- Filmyzilla follow-ups (HQ download-ID discovery, FZ80 Turnstile),
  gofile video-folder hunt, doodstream fresh samples, megaup retry window,
  hubdrive live-file hunt — unchanged from the plan, not attempted here.

## Live proofs on copies (no live DB writes)

- Wrong film: copy confirms legacy 500000 = Arthur's Whisky (post 55458)
  vs cat 500000 = Last Night in Soho; true target cat 598344.
- MovieBox: live Sistas page → 26 releases with 26 detail-URL sources.
- Search: "Ali Baba" 49.415s cold / 1.095s warm, 17/17 same ids.
- Play path: 0.016–0.031s, indexed plans.
- Re-key: blast radius 69,773; residual 3,310 rows / 2,148 keys; UPDATE 0.183s (rolled back).
- vidmmo: does not resolve (getent rc=2, curl 000/000).
- Rev-4 rebuild: running on the copy (PID 1198234).
