# Session — Legal catalog: Archive.org importer (2026-11-09)

Archive-only first, no TMDb key. Branch `session-legal-catalog`, base main
`32f2c19`. The build note is
`~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/legal-catalog-importer-build-20261109.md`;
the proof run (10/10 direct .mp4 play, pool ~8,900 PD films) is
`hidden_files/legal-catalog-proof-20261109.md`. This checkpoint covers only
the code + the small staging batch. The data merge into the live catalog is
a separate parent gate job.

## What changed

`Fast_Fetch/importers/import_archive.py` (new, 1,011 lines, stdlib only):

- Feed walk: `advancedsearch.php?q=collection:feature_films AND NOT
  title:(Jesus)`, downloads desc, pages of 100. Never default order (the
  default sort concentrates Jesus Film translations at the top, 59% of the
  first 150 rows, measured 2026-11-09).
- HARD GATES, in order: `is_dark` → skip; no `licenseurl` → skip;
  `licenseurl` outside the allowlist → skip; no `.mp4` → skip; Range probe
  (follow redirects, expect 206 + video/*) AND ffprobe (video + audio +
  duration > 0) — BOTH must pass, and a missing ffprobe binary fails
  closed (the item is skipped, never imported unproven).
- License gate: deny markers checked FIRST (a BY-NC-SA URL contains both
  "by-nc" and "by-sa"; the NC half decides). ALLOW: PD Mark 1.0, the old
  public-domain dedication (`/licenses/publicdomain/` — Things To Come 1936
  carries exactly that string; a normalizer knowing only `/publicdomain/
  mark/` would have dropped a public-domain film), CC0 1.0, CC BY (any
  version), CC BY-SA (share-alike recorded). DENY: BY-NC, BY-NC-SA, BY-ND,
  sampling, unknown, missing. "Plays" != "importable": Karate Warriors
  1976 plays fine (Range 206 + ffprobe h264 + audio) but is CC BY-NC 4.0
  and is skipped. License forms verified live 2026-11-09 against the six
  known identifiers before the normalizer was written.
- `.mp4` matching is by filename suffix, not `files[].format` (seen live:
  MPEG4, h.264, 512Kb MPEG4, h.264 IA). Preview/trailer/sample files are
  excluded. Largest plain `.mp4` first; `_512kb` is the low-band release;
  cap 3 variants. A `.ia.mp4` over 1 GB is dropped when a plain `.mp4`
  already probes >=720p (Bowery at Midnight: both files are the same
  1.27 GB encode).
- Quality band from **ffprobe height** (>=1080 → 1080p, 720–1079 → 720p,
  <720 → 480p). This DEVIATES from the build note's width rule, on
  measured evidence: Sita Sings the Blues ships a 1280x720 file, which is
  720p by height but reads 1080p under a width rule — and 1080p is a
  VIP-gated band, so the width rule would have answered 402 to free users
  for a free 720p file. The "p" number names the vertical resolution;
  height is the honest signal. Width is the fallback only when no height
  was recorded. After the fix Sita bands 1080p / 720p / 480p (1920x1080,
  1280x720, 848x480) — three distinct bands.
- Content screen: titles word-boundary matched (the repo's adult law: the
  anchors stay — "sex" never fires inside "Sussex", "adult" never inside
  "Adulterated"); identifiers are glued slugs, so they are substring
  matched only on the long act-naming tokens. `naked` is deliberately NOT
  a token (The Naked City / Naked Gun / Naked Lunch are mainstream).
  `nudist` WAS added after the first live batch caught the miss: Diary of
  a Nudist (1961) is a nudist-camp film the first wordlist let through
  unflagged; "nudist" names a person-type and no mainstream word contains
  it. Flagged rows are stored `is_18_plus=1` for manual review, never
  auto-published (xprimehub shape). The merge's own adult derivation and
  the gate-merge human review are the backstops for what the list misses
  (The Naked Witch (1961) is unflagged by design — see the `naked` rule).
- Mapping: one post per identifier, `canonical_key =
  archive_org:<identifier>` (unique per item — no false corroboration with
  another site's title+year key); `source_url` = the details page, never
  the file; one release per probed variant; one `download_sources` row per
  release (`service = "archive_org"`, `final_url` = direct download URL,
  stable, no expiry; `playback_type = "direct"`, `status = "active"`).
  `tmdb_id` stays NULL, never invented. `raw_meta` carries identifier,
  licenseurl, license_kind, share_alike, flag_reason and the full probe
  evidence (Range status + ffprobe width/height/codec/duration) per file.
  Poster is the item's `__ia_thumb.jpg` when present in `files`.
- Year: metadata, then a 4-digit year in the identifier, then in the
  title, else NULL — never invented. Title cleaning strips one trailing
  `(YYYY)` or a trailing digit-free paren group (the cast list Archive
  appends: `The Golfers (Andy Clyde Thelma Hill)`); `(Part 2)` keeps its
  digits and is kept. Translation dedupe by normalized title + known year
  inside one harvest (feed is downloads-sorted, so the most-downloaded —
  usually the English original — wins); yearless items dedupe by
  identifier only.
- `resumable` is NOT set by this importer: the unified `is_resumable`
  flag is set by the link-health probe (`probe_single_source`, 206 →
  resumable), not by the merge. What the importer stores is the probe
  evidence the health probe will corroborate (Range 206 recorded per
  file in `raw_meta`).
- Staging schema is the same posts/releases/sources shape
  `merge_catalogs.py` reads (copied from the themoviebox importer).
  `export_staging` upserts by `canonical_key` and replaces an item's
  releases+sources on re-export, so a harvest re-run is idempotent.
  CLI: `harvest --db --limit --start-page --per-page`, `verify`, `stats`.
  `verify` fails closed: any post without a release, any source without a
  final URL, any post without a licenseurl → exit 1.

`Fast_Fetch/importers/test_archive_import.py` (new, 64 tests, all offline —
fixtures shaped from the 2026-11-09 live probe of the six known
identifiers): license gate (12), content screen (7), title/year (8),
quality band (3, incl. the Sita 1280x720 mislabel case), .mp4 candidates
(5), probes (9), build_record end-to-end (11), export/verify (3), harvest
(3), CLI (2). The module docstring records the measured defect behind
each rule, the themoviebox pattern.

`.github/workflows/backend-ci.yml` (+10): one 🧪 step,
`test_archive_import.py`, after the Session 118 importer block. NOT added
to UNREGISTERED — a new module goes straight into the gate. Gate count
65 → 66.

## Live batch (staging DB `/home/ubuntu/radd-stream-data/archive_org.db`)

Ran from `/home/ubuntu/legal-catalog-run/` (scratch copy of the importer;
never `/opt/radd-stream`). Three runs, same 39 feed rows (downloads page
1), limit 20:

- Run 1: items=39 posts=20 skipped_license=18 skipped_no_mp4=1
  skipped_probe=0 flagged_review=1 errors=0. Staged 20/40/40.
- Run 2 (after the `nudist` token was added): same counts except
  flagged_review=2 — but releases dropped to 39: one variant (Tarzan's
  Revenge main .mp4) failed a probe transiently and the item staged with
  only its `_512kb` release. A variant-level probe failure drops the
  variant silently (only a whole-item failure increments
  `skipped_probe`); the post still stages with its surviving variants.
- Run 3 (after the height-band fix): items=39 posts=20
  skipped_license=18 flagged_review=2 errors=0. Staged **20/40/40** — the
  Tarzan variant came back, confirming the run-2 loss was transient, not
  systematic.

Final verify: **OK** — posts 20, releases 40, sources 40,
flagged_review 2, posts_without_release 0, sources_without_final_url 0,
posts_without_license 0. License kinds: publicdomain 17, cc0 1, pd_mark 2.
Band totals: 1080p 1, 720p 1, 480p 38 — the PD catalog is overwhelmingly
SD, as expected for pre-1960s films. Merge-shape audit (SQL): 0 posts
without a release, 0 releases without a source, 0 null final_url /
service / quality / url — every column `merge_catalogs.
_collect_staging_post` reads is present and non-null.

Titles staged (all recognizable PD classics): Sex Madness (flagged),
Charlie Chaplin Festival, His Girl Friday 1940, Voyage to the Planet of
Prehistoric Women 1967, House on Haunted Hill 1959, Jungle Book 1942,
Reefer Madness 1938, Sita Sings the Blues 2008, The Pied Piper of
Hamelin 1957, Nazi Concentration Camps 1945, Bloody Pit of Horror 1965,
Abraham Lincoln 1930, Dressed To Kill 1946, Diary of a Nudist 1961
(flagged), Three Stooges Episodes, Suddenly 1954, The Naked Witch,
The Stranger 1946, Tarzan's Revenge, McLintock! 1963. Years are NULL
where genuinely unknown (Sex Madness, Chaplin Festival, Three Stooges,
Naked Witch, Tarzan's Revenge) — never invented.

Yield finding: 20 posts from 39 examined rows, but 18/39 (46%) skipped
on license — the downloads-sorted first page is license-poor (many
unlicensed or NC items at the top). The proof's ~35%-usable estimate was
measured on a filtered sample; the raw feed runs leaner. A scale harvest
should expect roughly 1 post per 2 feed rows at the top of the list.

Timing finding: ffprobe on a remote Archive file takes ~10 s (measured:
The Golfers, 9.98 s, 0.1 s CPU — network wait). One TCP connect hung in
SYN-SENT to an Archive storage node during run 1; the 30 s timeout
cleared it and the item was skipped cleanly. At ~10 s per variant, a
serial full-catalog harvest (~9k films) is a multi-day job — the scale-up
needs probe parallelism or a probe budget, not a single serial run.

## Local gate

Runner `run-backend-gate.py` on this worktree: **60/61 PASS**. The one
FAIL is `test_api_v2.py::V2CachingTests.
test_if_none_match_answers_304_with_validators_and_no_body` (200 != 304)
— the KNOWN ETag-304 load flake (AGENTS.md): it fails under concurrent
gate load and passes solo. Solo re-run: **71 tests OK**. My change does
not touch api_v2 or anything it depends on. Importer solos:
`test_dub_collision_census` 13 OK, `test_themoviebox_detail_api` 18 OK,
`test_themoviebox_import` 54 OK, `test_themoviebox_links` 7 OK,
`test_archive_import` **64 OK**. `test_docs_invariants` OK (22 tests).

## Deliberately left out

- The DATA merge into the live catalog (parent gate job: backup + live
  test). Staging only.
- TMDb spine: needs a written commercial agreement first (free key is
  non-commercial only; the app plans ads). `tmdb_id` stays NULL.
- Scale harvest (needs the probe-parallelism decision above).
- Resolver branch for `archive_org`: the download URL 302s to a storage
  node, so the press path MUST follow redirects — a no-follow press is
  not a play verdict here. No resolver change was made in this session.
- `domain_registry.json` entry: Archive.org does not rotate domains, so
  the tracker has nothing to watch; left for the parent to decide.
- The two flagged rows (Sex Madness, Diary of a Nudist) are staged but
  NOT cleared for publishing — the gate merge decides them.
