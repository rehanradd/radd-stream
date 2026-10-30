# 2026-10-28 — Session: kisskh.asia gets its own staging importer, and 100% coverage stops being a slogan (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 — Session: kisskh.asia gets its own staging importer, and 100% coverage stops being a slogan (Qoder)

**Goal:** a fourth Asian-catalog site in its own staging database — `/home/ubuntu/radd-stream-data/kisskh.db`,
Chinese/Korean/Thai dramas with subtitle tracks — stdlib only, in
`Fast_Fetch/importers/import_kisskh.py` (1,562 lines), with an offline suite that actually reaches
100% line coverage. Shipped as `44efa5a` (two files, +2,784), verified and pushed to `master` by the
orchestrator; this entry is the third path and was deliberately held back until the owner scoped it.
`fast_fetch.db` was never opened for writing (md5 `3693bf4e…` before and after; 203 posts, 0 kisskh rows).

**The site is not shaped like the other three, and that changed the design.** kisskh.asia is WordPress
with the "cooldrama" theme and an **open REST API**, so the importer reads JSON instead of scraping
listing pages: `/wp-json/wp/v2/posts?…&_embed` for the catalog (675 posts) and
`/wp-json/cooldrama/v1/player-data?post=<id>` for the media. `_fields` must **not** be combined with
`_embed` — the answer comes back with `_embedded` empty, which is where the taxonomies and the featured
poster live. Term names repeat across term ids (two "Supernatural", two "Thriller"), so terms are
deduped by name. The real catalog is inside `player-data.html`, a compact blob whose grammar was
**ported from the theme's own `player.js`** rather than guessed: `{nextServer}` separates server
groups, `{embed}` forces iframe type, `detectType` returns `jw` when a group holds `|` or a
`.vtt|.srt|.txt|.m3u8|.mp4|.mpd` URL, `;` separates episodes, the episode head line is
`[marker]<video-url>|Lang1,…,Lang11|` followed by comma-terminated track URLs, a leading `*` is a slot
the site published with no file behind it (often a bare host), `$`/`${…}` is scheduled, and invisible
characters (U+200B–D, U+FEFF, NBSP) are scrubbed first. `|` is not a field separator inside `${…}`.
Observed subtitle set is a constant eleven languages (tl, km, en, id, ms, pt, ar, hi, de, fr, es).

**A live finding that cost an ingest, now pinned by a test.** `per_page=100&_embed=1` answers **5.3 MB
in 26 s** on page 1 and page 2 crosses the module's 30 s timeout, so the listing walk stalled with
`page 1 -> HTTP 0` and queued nothing. `PAGE_SIZE` is **20** (200 rows in ~6 s per page) and the
listing fetch uses `LISTING_TIMEOUT = 60`; `get_json`'s 30 s default is untouched for `player-data`.
`test_the_rest_pages_are_walked_until_a_short_page` now asserts both the requested `per_page=20` and
`timeout == 60` on *every* page, so a future widening fails a test instead of an ingest.

**Three defects an independent review found before the commit; all three landed.**
1. **A legacy `sources` table was rejected, not upgraded.** `ensure_schema` created
   `idx_kisskh_sources_status`/`…_playback` before migrating the columns they name. `_SCHEMA` is split
   into `_SCHEMA_TABLES` and `_SCHEMA_INDEXES`, and `_add_missing_columns` runs over `posts`, `releases`
   and `sources` first — with `INTEGER` affinity for the numeric columns, because an `INTEGER` stored
   under `TEXT` affinity compares digits, not times. `RELEASE_COLUMNS`/`SOURCE_COLUMNS` now feed both
   the migration list and the `INSERT`, so the two cannot drift apart.
2. **The single-URL CLI path double-encoded Unicode slugs.** `parse_page` took an already
   percent-encoded path segment and `_fetch_post_by_slug` quoted it again, so `%EC%97%85` became
   `%25EC%2597%2585` and every non-ASCII slug answered "not a catalog entry". The segment is decoded on
   the way in and quoted exactly once on the way out; the bulk path was already correct. Pinned by
   `test_a_percent_encoded_slug_is_encoded_exactly_once` with a Hangul slug end to end.
3. **Subtitle rows claimed a check that never happened.** They were written `status='active'` while
   `resolve_links` skipped `playback_type='subtitle'` even under `--probe`. The skip is deleted — a
   track the subtitle viewer depends on is exactly the row worth asking — and the vocabulary now names
   whether a request was made: `unverified` (never asked), `blocked` (slot published, no file, or a 204/
   403 answer), `js_required` (a page, not an object), and `active|dead|unknown|error` only after a
   probe sets `last_checked`. Cost stated in the docstring and in `--probe`'s help: one HEAD per row,
   so a twelve-episode drama is 12 videos plus 132 tracks, and it stays opt-in because the CDNs rate-limit.

**Two decisions an auditor will ask about, taken on the record.** `year` stays **NULL**: the only year on
the site lives in the page HTML this lean crawl does not fetch, and storing the post's *publish* date as
the work's release year is precisely the defect the pagalmovies audit named (7 rows whose stored year was
the site's SEO title). `release_date` is the publish date; `--with-pages` is the named path that fills
`year` from the site's own meta later, without a rewrite. `is_18_plus` is **keyword-based and errs toward
flagging** (the site publishes no rating), so a title tagged "Erotic Thriller" is stored-but-hidden rather
than displayed on a guess.

**Row shape, and the pilot evidence that it is right.** `sitemap_cache` keeps the resumable queue
contract (`0` queued, `1` indexed, `2` re-check-next-crawl, `-1` parked, 3-strike parking); a blob-less
200 is a drama that has not aired and is **re-queued**, not parked, so a later crawl finds its episodes;
`removed` (401/403/404/410) parks at once; a transport failure keeps the strike budget. Subtitle URLs
are stored twice by owner decision — as `sources` rows (`playback_type='subtitle'`) *and* as a
per-episode map in `posts.raw_meta` — so a merge tool that only understands video rows loses nothing.
Temp-DB pilot (3-page sync, `crawl --limit 3`): **2 posts / 40 releases / 480 sources = 40 stream + 440
subtitle**, exactly eleven tracks on every release, all eleven languages present, **every row
`unverified`**, one drama declined with `last_note='http-error'`, `PRAGMA integrity_check` ok, 0 orphans.
The earlier 12-drama pilot into the real staging DB reached 11 posts / 173 releases / 2,112 sources with
the same 11-tracks-per-episode invariant, 0 duplicate `canonical_key`, 0 brand tokens in any display
string, `year` NULL on all rows and `release_date` on all.

**Full ingest: started here, finished under the orchestrator.** `sync` queued all **675 dramas**
(663 new) and `crawl` reached **posts=119 / releases=2,270 / sources=27,872** (2,898 stream, 24,970
subtitle, 4 iframe; 27,868 `unverified`, 2 `blocked`, 2 `js_required`) with integrity ok, 0 orphans and
0 duplicate keys when I stopped my writer at the owner's instruction. Queue at handover: 554 pending,
119 indexed, 2 parked (`escape` on 3 strikes of `http-error`, `to-my-beloved-thief` `removed`).
**The orchestrator relaunched the remaining crawl in tmux session `kisskh_ingest2`** (2 workers, nice 10)
against `/home/ubuntu/radd-stream-data/kisskh.db` and owns its verification and the push.

**A hard boundary the owner set this session, for every agent after me: do not run `pkill`, `kill`, or
`tmux kill-session` against anything matching `import_kisskh`.** My kill landed on the ingest the
orchestrator had launched, because my command was queued before his ownership message reached me. Two
writers on this database is the one thing that could corrupt it, and a running crawl is not mine to
stop: if a process must die, say so and let the owner decide. Related and worth knowing before
re-running the same command: `sync` commits `sitemap_cache` in **one transaction at the end**, so the
queue looks untouched for minutes while pages are still downloading — an empty `sitemap_cache` is not
evidence that a sync is dead.

**Making 100% coverage actually reachable, and how it is measured.** `test_pagalmovies_import.py` is
*not* 100% coverable and was not copied in that respect: it never calls `main()`, patches only the two
seams (so the retry loop, the `HTTPError` path and the redirect walk never execute), and hides
`_signal_handler` behind `# pragma: no cover`, which `trace` ignores. Here there are exactly two seams
over one injectable primitive each, import-time side effects are callable (`_build_ssl_context`,
`_build_openers`, `_install_signal_handlers`) so both branches are driven, no fallback-import or
`try/except OperationalError` schema retry survives (a `PRAGMA table_info` column check replaced them),
no pragma appears anywhere, and dead defensive branches are **deleted** rather than excused. The
harness is a ~100-line stdlib `sys.settrace` tracker in `/tmp/kisskh_cov.py` that also sets
`threading.settrace` — without it the crawl pool's worker lines are invisible — with the denominator
taken from `code.co_lines()` minus AST docstring spans. Result: **943/943 lines, `UNCOVERED []`**.
The planned `python3 -m trace --count` cross-check **did not work** and is reported as unresolved, not
as a second confirmation: `trace` does not follow threads, and neither the `--module` form nor a runpy
shim could load the suite (`Ran 0 tests`).

**The suite cannot reach the network, and says so.** `socket.socket` is replaced for the whole run by a
stub that raises `AssertionError`, after a hang this session exposed: `test_crawl_from_the_command_line`
called `sync_catalog` unpatched and blocked on a live SSL read for 600 s. Diagnostics that belong to the
next agent: `HTTPError` substitutes an empty `BytesIO` when `fp=None`, so `read()` returns `b''` and
never raises — an unreadable body needs a `BytesIO` subclass whose `read()` throws; and
`build_opener` appends `HTTPErrorProcessor` last, so a custom redirect handler is *not* `handlers[-1]`.
Operator chatter is now captured by a `silenced()` helper and asserted on rather than printed into the
suite's own progress line (`page 1 -> HTTP 500`, `is not a post list`, `is not JSON`, the SIGINT drain
line, `Page is not a catalog entry.`, `parse requires --url`, the sync summary, the crawl totals).
One cosmetic change was reverted on the owner's instruction: the progress line prints before the final
batch flush, so a short run can show `…, 0 sources` and then report the real totals in the summary.
Known and left alone.

**Checks.** `importers/test_kisskh_import.py` **129 OK in ~3.1 s, fully offline, 943/943 lines covered**.
Gate: `importers/test_pagalmovies_import.py` 54 OK, `importers/test_filmiyin_import.py` 38 OK,
`test_database.py` 65 OK, `test_vidout.py` 6 OK, `test_redact` 49 OK, `test_api_v2` 46 OK,
`test_admin_panel` 56 OK, `test_catalog_api` 114 OK, `test_provenance_stamping` 12 OK,
`test_operator_isolation` 22 OK; `import fast_fetch, viewer, merge_catalogs` OK.
`test_media_search` has **one failure that is not mine and that I did not touch**:
`test_the_row_shape_is_the_shape_a_keyword_search_already_returns` — `viewer.api_v1_get_posts` now
returns a `subtitled` key that `media_search.py`'s enriched row does not carry, i.e. the keyword-search
route and the media-search projection have drifted apart in the in-flight API work. Nothing in the
kisskh importer is involved (no shared symbol, no shared table); it needs that owner's call on which
shape is correct.

**Deliberately not done.** No merge into `fast_fetch.db` — staging isolation, per rule 9; the merge is
an operator decision after the crawl finishes. The `.db` stays out of Git. No push by me this session
(the owner pushes). `mp4moviez`, `App/`, and the other untracked workers in this checkout are not mine
to stage. No `active` row exists in `kisskh.db` at handover — the count was 27,868 `unverified`, 2
`blocked`, 2 `js_required` — because every crawl this session ran already used the post-fix vocabulary,
so there is nothing to heal; a `--probe` run is the only way any row should ever acquire `active`.

---

