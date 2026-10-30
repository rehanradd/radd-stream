# 2026-10-27 — Session: a file on the phone can now be asked about (Qoder, orchestrator)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: a file on the phone can now be asked about (Qoder, orchestrator)

**Milestone commits:** see `docs/SESSION_CHECKPOINT.md` (this session: the by-media endpoint,
the APK republish, and the sweep growing a new route to cover).

- **The question this answers** is the one `?q=` cannot: a viewer holding a 1 437-second,
  1920x1080, Hindi file wants to know which work it is. `Fast_Fetch/media_search.py` treats
  the media facts as **evidence** and reports every hint three ways — `matched_on`,
  `mismatched_on`, `unknown_on`. Collapsing the third into the first would rank a work above
  another purely because our row for it is emptier, and the live catalog really does answer
  `runtime_minutes: null` for most works, so "unknown" is the common case, not a corner.
- **Why the sketch was not built.** `docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` asks for an
  FTS5 `catalog` table and several columns the ledger does not have. Writing the sketch would
  have produced a module that cannot run; this is the design that fits the schema that exists.
- **The bridge is `cat_work_sites.post_id`.** `posts.canonical_key` never matches
  `cat_works.work_key` — one is a slug, the other an `imdb:` id — and a join between them
  returns **zero rows**, which is the silent wrong answer this whole module is built to avoid.
  Two tests pin it: one asserts the projector really writes the runtime/rung this reads, the
  other asserts the *wrong* join matches nothing.
- **A title is required, as a 400.** 130 016 works, several thousand of them ~120-minute 480p
  films. Duration and resolution alone do not discriminate; ranking all 130k to answer "here
  are 10 of possibly 10 000" is a lie and a self-inflicted denial of service on one vCPU.
- **Three bugs the fixture found, none of which a diff would have shown:**
  1. the rung ladder was walked bottom-up, so `1920x1080` came back **480p**;
  2. `audio_languages` is a `cat_releases` column, not a `cat_works` one (the query raised
     `no such column` the first time it ran);
  3. the projector takes the rung from the release row's `quality` and only falls back to the
     label — my fixture contradicted itself, so it had been testing the fallback.
- **Deployment.** nginx: `= /api/v1/search/by-media` before the `^~ /api/` deny, GET/HEAD only,
  `burst=20`, 30 s read timeout, backup at `/etc/nginx/radd-stream.pre-bymedia.bak`. Public GET
  answers the three-way report, POST → 403, `/api/v2/health` still 403 and `/admin` still 401.
  Live cost: **0.37 s** for a five-candidate title.
- **APK.** `:app:assembleDebug` `GRADLE_EXIT=0` / `OVERLAP=NO` / `apksigner` clean on v1+v2,
  published over `/var/www/download/radd-stream.apk` (22 738 552 bytes, md5 `9ace0279…`,
  byte-identical to the artifact). The superseded build was **moved out of the web root**, not
  deleted — a stale APK anyone can install is worse than a backup nobody can.

**Checks:** `test_media_search.py` **21 OK** (new); `test_database` 64, `test_redact` 49,
`test_api_v2` 46, `test_admin_panel` 56, `test_catalog_api` 114, `test_provenance_stamping` 12,
`test_operator_isolation` 22 — **364 OK**, one module per invocation, `--` no live catalog was
written to anything. `sweep_public_edge.py --db /tmp/edge_snapshot.db --posts 20` → **OK**, and
it now walks the new route (sample titles, three hidden-adult probes, the no-title 400, the
garbage-duration 200).

- **A claim this file carries that is not true of the tree (not mine, and now written
  down).** `git show HEAD:Fast_Fetch/CONTINUITY.md` ends with a filmiyin session log asserting
  `importers/test_filmiyin_import.py` 38 OK — but `Fast_Fetch/importers/` is **untracked**, so
  the prose landed in `04126e7` without the code it describes. That commit staged `CONTINUITY.md`
  while another account had appended to it in the same checkout. Consequence for whoever picks
  this up: the filmiyin importer is **not in the repository**, its 38 tests do not run from a
  fresh clone, and the log above it should be re-verified before being trusted. Nothing here
  stages or reviews that work — it is recorded so the next agent does not inherit it as fact.

**Not done, on purpose:** the Kotlin half of M-SRCH-01 (permissions, `DeviceMediaScanner`, the
screen, the Room mapping). There is still no device and no emulator on this box, and a
`MediaStore` query that has never run against a real phone is exactly the kind of "implemented"
this file has repeatedly had to walk back.

