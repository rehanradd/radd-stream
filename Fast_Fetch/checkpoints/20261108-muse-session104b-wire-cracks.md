# Session 104b — Wire uploadflix + 1xplayer + MovieBox (crack-methods wiring)

Date: 2026-11-08 (PKT). Branch: `tracking-a-20261107`, base `f84d8c29`
(Session 104, live). Scope: resolver wiring only — the three cracks were
proven by the crack-methods session (08:08 PKT) and re-proven live on the VM
this session before wiring. No production DB writes, no live-tree edits, no
service restart. Fixture DBs only, under /tmp on the VM.

## What was proven before (crack-methods session, VM)

- **uploadflix** (57,845 `dl`-service rows; 52,583 of them
  dl.uploadflix.com): generic XFS doFree. File page carries the download2
  form AND the storage-host dllink anchor on cloud.secure-storage.top:8080;
  Range probe of the anchor -> 206 application/octet-stream, EBML magic
  `1a45dfa3`, a real .mkv. The storage host's cert is self-signed: urllib
  fails it, curl -k / an unverified context works.
- **1xplayer** (31,077 rows): play page (redirects vd.1xplayer.com -> a
  rotating domain, e.g. geoxe446syt.com) carries `p3.file` (starts `~`,
  per-load) + `p3.key` (64 chars, per-load). POST
  /playlist/<file-minus-~>.txt with X-CSRF-TOKEN = p3.key -> 200 mpegurl =
  one signed master URL. Master + variants + segments are signed to the
  requesting IP (~2h expiry, embedded as `:<epoch>:` in the URL) AND gated
  on Referer = the play page (a bare master GET 404s). Segment Range ->
  206 video/mp2t, 0x47 sync at 0/188/376.
- **MovieBox** (themoviebox.xyz + 123moviesfree.club, shared aoneroom
  backend): detail API -> subjectId -> play API
  `/wefeed-h5api-bff/subject/play?subjectId=<id>&se=<se>&ep=<ep>&detailPath=<slug>`.
  The call MUST carry Referer = the `/movies/` player-page URL; the same
  call from `/detail/` returns streams:[] even with cookies. **Correction
  measured this session: no cookies are needed** — /movies/ Referer + NO
  cookies returns the streams; the Referer alone is the discriminator.
  themoviebox gives 360p+480p MP4 free (1080p vipLocked); 123moviesfree
  gives 480p+1080p free. Signed URLs (sign+t) stable per resource
  short-term. NEVER probe with HEAD (429) — GET Range only.

## Code changes

`Fast_Fetch/importers/host_resolvers.py` — three unwrappers + helpers:

- `unwrap_uploadflix(url, fetch=None, verify=True)`: GET the file page
  (cookie jar, follows the dl.uploadflix.com -> 1uploadflix.net redirect).
  If the page already carries the storage-host dllink anchor, take it (the
  live sample does); else drive the forms JD-style — download1
  (method_free set, method_premium dropped, no countdown ever slept) then
  download2 (adblock_detected=0) — and read the anchor off the answer.
  Anchor rule (`_uploadflix_dllink`): a `cloud.secure-storage.top:8080/d/`
  href on a FOREIGN host (never the page host itself), preferring a video
  extension; the href carries spaces in the filename, so the whole quoted
  value is read and URL-quoted before requesting (a naive `[^\s]+` regex
  truncates it and the truncated URL 416s). Probe = Range bytes=0-511 via
  `_unverified_fetch` (unverified-SSL opener, storage host only) through
  `_finish_media`, so the verdict is active only on a real 206 + EBML
  magic. 404 page -> dead; live page with no anchor/form -> unknown.
- `unwrap_1xplayer(url, fetch=None, verify=True)`: GET the play page,
  extract `p3.file`/`p3.key` (the page is ~3.9 KB; the config is one
  `let p3 = {...}` literal). POST /playlist/<file-minus-~>.txt with
  X-CSRF-TOKEN = the key + Referer = the play page. GET the signed master
  with Referer = the play page, take the highest variant (`_m3u8_variants`
  parses RESOLUTION + relative URIs), GET the variant with Referer, Range
  the first .ts segment with Referer (`_ts_segment_ok`: 206 video/mp2t +
  0x47 sync at 0/188, or a video/mp2t content-type). Expiry parsed out of
  the master URL's embedded `:<epoch>:` into `expires_in`; the master URL
  is the final answer and is NEVER cached (is_temporary, re-resolve per
  play). Page 404 -> dead; no p3 config -> unknown.
- `unwrap_moviebox(url, fetch=None, verify=True)`: detail URL (or a
  `?se=&ep=` series URL) -> detail API for the subjectId -> play API with
  Referer = the `/movies/` player-page URL (built from the slug +
  subjectId; se/ep default 0/0, parsed from the detail URL when present).
  No cookie jar (proven unnecessary). `_moviebox_pick_stream` takes the
  highest-resolution FREE MP4 (vipLocked skipped, empty URL skipped, DASH
  never taken — it needs Edge-Cache-Cookie/X-MB-Token). Probe = GET Range
  via `_probe_playlist_or_file` (Referer-carrying, never HEAD). All
  vipLocked / no subjectId -> unknown.
- Pure helpers, unit-tested directly: `_xfs_form_fields`,
  `_uploadflix_dllink`, `_m3u8_variants`, `_ts_segment_ok`,
  `_moviebox_pick_stream`, plus `_cookie_jar_fetch` /
  `_unverified_fetch`.

`Fast_Fetch/fast_fetch.py` — three `elif` dispatch branches after the
vidhide branch, each setting `_unwrap_branch_taken=True`,
`fresh_url`/`fresh_temp=1`/`embed_verdict`/`_gate_from_verdict=True` on
active, i.e. the unwrapper's own verified probe IS the gate evidence (the
Session 103 pattern — a bare re-probe of a proven link can fail):

- uploadflix matches on URL markers (`uploadflix`/`1uploadflix` in the
  URL), NOT on service alone: 52,583 of the 57,845 `dl` rows are
  uploadflix, the other ~5,262 must not be misrouted. Ranked last in the
  chain on purpose, with gofile — a token that rotates on every page load
  is re-unwrapped on every press.
- 1xplayer matches service `1xplayer` or the hostname in the URL.
- moviebox matches services `moviebox`/`themoviebox`/`123moviesfree` or
  either hostname. The branch builds the `/movies/` Referer URL from the
  detail URL + subjectId it does NOT yet know — the unwrapper does the
  detail-API call itself, so the branch passes the detail URL through.

## Tests

- `Fast_Fetch/test_database.py`: 14 new tests (4 uploadflix incl. the
  download1->download2 form flow with posted-field assertions, 3 1xplayer
  incl. the Referer + CSRF-token + expiry assertions, 4 moviebox incl.
  highest-free-MP4 pick, all-vipLocked, no-subjectId, se/ep, 3 dispatch
  tests with the gate probe stubbed FAIL to prove the skip). `_FakeResolvers`
  extended with the three service constants + fake unwrappers — the Session
  103 lesson: an incomplete fake makes a dispatch test silently no-op.
  The uploadflix dispatch test uses service `dl` + a dl.uploadflix.com URL
  to prove the URL-marker match covers the `dl` rows.
  **196 tests OK (1 skipped, pre-existing).**
- `Fast_Fetch/importers/test_host_resolvers.py`: 7 new tests for the pure
  helpers (dllink preference + same-host rejection, form-field parsing,
  variant pick, segment sync bytes, stream pick incl. locked/empty skip).
  **178 tests OK.** (Not registered in backend-ci.yml — same as the Session
  103 unwrapper helpers; the end-to-end chains live in test_database.py,
  which IS gated.)
- Full backend gate (`run-backend-gate.py`): **50 modules, 0 failed.**

## VM proof (fixture DB, one post per host row, real resolver)

Harness `/tmp/vm104b-proof.py` (local copy; scratch code at
/tmp/104b-scratch/Fast_Fetch on the VM). Three runs; the third is the
traced proof run (every unwrapper call + verdict printed):

| run | uploadflix yba4err36sxr | 1xplayer ftt4479696 | 1xplayer ftt6869880 | moviebox 123moviesfree Dhurandhar | moviebox themoviebox Dhurandhar |
|-----|------------------------|---------------------|---------------------|-----------------------------------|----------------------------------|
| 1 | FAIL stale_probe_failed, 3.1s | PASS 7.6s | PASS 7.3s | PASS 4.6s | PASS 3.3s |
| 2 | FAIL stale_probe_failed, 2.5s | PASS 7.4s | PASS 7.2s | FAIL stale_probe_failed, 1.5s | PASS 2.1s |
| 3 (traced) | **PASS 3.0s** | **PASS 7.2s** | **PASS 7.2s** | **PASS 2.1s** | **PASS 2.4s** |

Proof run 3 (the verdict): **5/5 succeeded.**

- uploadflix: active, final URL = the storage-host dllink (206
  application/octet-stream, EBML magic, 365,629,162 bytes), refreshed,
  is_temporary.
- 1xplayer (both samples): active, final URL = a signed master on
  i-arch-400.salov447hev.com, refreshed, is_temporary. The two play pages
  map to the same underlying file (same stream directory, different
  per-load signatures + expiry epochs) — each chain independently fetched
  its own p3 + playlist, so this is the site's mapping, not a harness
  artifact.
- moviebox (both bases): active, final URL = the 1080p signed MP4 on
  bcdnxw.hakunaymatata.com (`?sign=...&t=...`), refreshed, is_temporary.
  Same signed URL from both bases (sign+t stable per resource, as the
  crack research said).

## What the failures in runs 1–2 were (transport flake, not code)

- The traced run shows the mechanism directly: the themoviebox.xyz detail
  API call failed once with **HTTP 0** (a network-level error — no HTTP
  status at all) and the unwrapper returned unknown; the resolver's
  sibling failover then re-resolved the same film through its
  123moviesfree sibling and succeeded. The earlier uploadflix +
  moviebox-123 failures are the same shape: a single network call in the
  chain errored at transport level (HTTP 0), the unwrapper returned
  error/unknown, and a single-copy fixture post has no sibling to fail
  over to. Standalone resolves of the exact same rows minutes later
  succeeded (uploadflix: direct unwrapper call active, traced resolve
  active, minimal-harness replication active in 2.7s).
- Consequence for production: a transient HTTP 0 writes
  failure_class `unwrap_failed` + last_failed_at, i.e. the negative cache
  skips that copy for 12h. In production a post has many copies, so
  sibling failover absorbs it (as the traced moviebox case shows); a
  single-copy post pays the full 12h. **Follow-up (not done here): a
  transport-retry policy — retry once on status 0, and/or do not poison
  the negative cache on a status-0 error.** That is a deliberate resolver
  change, not a wire-up fix, so it is recorded here rather than bolted on.

## Open items / follow-ups

- **MovieBox importer gap (blocks real rows): the live catalog holds 0
  MovieBox rows.** The importer (`import_themoviebox.py`,
  SERVICE="themoviebox") stages films in its own vault with mirror URLs +
  declared releases and empty source lists. For a row to resolve, the
  importer must store the **detail URL as its source_url** (a mirror URL
  carries no slug, so the unwrapper cannot derive a subjectId from it).
  The branch is wired + proven via the fixture harness, like vidmoly in
  Session 103 — but until the importer stores detail URLs, no live row
  will ever reach it.
- **uploadflix storage-host probe flake**: 2 of 3 harness runs failed the
  probe step at transport level (see above). Worth a retry loop if the
  rate holds on live traffic; watch the failure_class counts.
- **gofile app playback still NOT proven** (bare link 302s without the
  Authorization header) — needs a device test; unchanged by this session.
- **1xplayer domain rotation**: play host rotates (vd.1xplayer.com ->
  geoxe446syt.com seen this session); the unwrapper follows the redirect
  and uses the live host for the playlist POST, so no hardcoded domain.
- **themoviebox.xyz detail API** flaked once (HTTP 0) in the traced run
  while 123moviesfree stayed solid — same backend, different front door;
  if the rate holds, prefer the 123moviesfree base for the play API.

## Files changed (uncommitted at checkpoint time)

- `Fast_Fetch/importers/host_resolvers.py` (3 unwrappers + helpers)
- `Fast_Fetch/fast_fetch.py` (3 dispatch branches)
- `Fast_Fetch/test_database.py` (14 tests + `_FakeResolvers` extension)
- `Fast_Fetch/importers/test_host_resolvers.py` (7 helper tests)
- No Kotlin files touched; no API-shape change (no `test_redact` run
  needed beyond the gate).
