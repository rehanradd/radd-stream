# 2026-10-28 — Overnight master run (app polish + new-site pipeline)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 — Overnight master run (app polish + new-site pipeline)

- **Master/orchestrator:** qoder2 on `/opt/radd-stream`; workers qoder1 (Android) and qoder3
  (backend discovery/importers). Live API frozen; staging DBs only; one crawler and one
  Gradle build at a time.
- **Android (verified by the master, pushed to master):** `824ebd2` media-controller manifest,
  `2966f4f` inline/empty failure states (Browse/Search/Detail), `fcdbb0e` honest player start
  state (`StartPhase`), `0141180` continue-watching resume position, `90ae074` home-rail
  failure state (includes 0141180). Gate for 90ae074: `/tmp/qbuild.sh :app:testDebugUnitTest
  --rerun` → `GRADLE_EXIT=0`, `OVERLAP=NO`, 63 suites / 516 tests / 0 failures, one fresh XML
  batch. qoder1's Hilt incremental cache poisoned once; a full `--no-build-cache` rerun after
  deleting `app/build/generated/hilt` restored a green build.
- **New-site discovery:** `/tmp/new_site_candidates_20261028.json` (126 domains checked,
  30 candidates). Independent master probe found the build list is mostly iframe-only:
  MoviesMela (pkembed/mxdrop), HindiDubbedPK (rpmplay), Moviehax (filemoon), TamilGun
  (YouTube), HindiAnimeZone (Turnstile), Bollyflix (CF-gated fastdl), Dotmovies (mobilejsr).
  The Android app has no WebView path (`PlaybackRecovery`/`LinkClassification`), so iframe
  rows are catalog-only and must be stored as `playback_type='iframe'`.
- **Two hosts are genuinely resolvable with stdlib** (verified by the master, Range
  `bytes=0-511`, no Referer, HTTP 206 `video/mp4`, `ftypisom`):
  - `mxdrop.to` — Dean-Edwards identity packer, `MDCore.wurl` signed MP4. 5/5 posts.
  - `pkembed.site` — Dean-Edwards base-36 packer, `<source src="https://stoplus.vkcdn5.com/…">`.
    6/6 posts. `e=43200` is a duration, `s` the start epoch (`expires_in=(s+e)-now`).
  Both are short-lived: the embed URL is the durable id, the MP4 must be unpacked JIT and
  never persisted; a site Referer returns 403. MoviesMela (819/820 mxdrop, 814/820 pkembed)
  therefore has two independent playable sources per title.
- **rpmplay lead:** its SPA bundle exposes `/api/v1/info`, `/api/v1/video`, `/api/v1/player`,
  `capacityToken`, and returns hex-encoded encrypted blobs (application/octet-stream) —
  still a bounded spike for qoder3; a NEEDS-JS verdict is an acceptable result.
- **Data:** `import_moviesmela.py` passes 168 offline tests (master-verified); `host_resolvers.py`
  passes 67. Both pushed (`1ec1627`, `85b398c`). The first full staging sync queued 10,460 pages
  before stopping early; the importer measured 20,888 posts over 1,045 REST pages, and `e97d833`
  now flushes queue rows per batch so a re-sync resumes durably. pkembed support landed in
  `8dd9c70` and was live-verified by the master on `crawlers-2026` (206, 201,886,684 bytes,
  `_l`/`_n` renditions, 12 h window). A by-media row now carries `subtitled` like a `q=` row
  (`7162e3e`), and rpmplay/filemoon are recorded as NEEDS-JS with the evidence (`5a9341e`).
- **Android since the last entry:** `3976a0b` feature board, `67bfe69` subtitle look persisted,
  `d598f18` audio-boost ceiling, `01f4a8c` TalkBack names + 48 dp targets, `1f7b41d` 53 player
  font literals on `brandSp` (with a drift test that bans raw `sp`), `3037c1b` player paints as
  design tokens. All pushed; the last gate was 69 XMLs at one instant, 554 tests, 0 failures.
- **Staging inventory:** 25 per-site DBs carry sources; largest are 9xmovies (337,595),
  world4ufree (254,340), hdhub4u (250,925), 10xflix (228,397), katmoviehd (163,972),
  hindilinks4u (145,196), kisskh (140,746). Older importers did not store embeds, so the new
  resolvers do not retro-unlock those rows.
- **Next:** qoder3 → finish the MoviesMela sync and crawl (no full `--probe`), bounded resolver
  sample, then the next build target; qoder1 → #18 chrome strings, #19 dead code, #20
  grid/region polish, #21 backend-blocked parity doc. JIT wiring of `unwrap_mxdrop` /
  `unwrap_pkembed` into `resolve_live_source` is drafted but deliberately not deployed; it needs
  a planned service restart, and the live API stays frozen until then.

---

