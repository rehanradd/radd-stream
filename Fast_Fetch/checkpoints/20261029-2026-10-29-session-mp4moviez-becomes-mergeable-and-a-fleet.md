# 2026-10-29 — Session: mp4moviez becomes mergeable, and a fleet-wide false `active` is retired (Qoder3)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 — Session: mp4moviez becomes mergeable, and a fleet-wide false `active` is retired (Qoder3)

Owner directive: finish what is half-built — filmiyin's 1,841 pending URLs, pagalmovies'
7,535 errored URLs, and the mp4moviez database that `merge_catalogs.py` refuses to read.
Production was explicitly off-limits (`merged_catalog_20261025.db` was 6.3 GB and being
written during this session; it was never opened, nor `fast_fetch.db`). No push.

**filmiyin: the queue is closed.** Pass 2 took all 1,841 pending URLs at `--workers 1`,
`nice -n 15`, `probe=False`: `pages=1841 posts=0 releases=0 sources=0 not-indexable=1841
failed=0`. Queue now `3,899 indexed + 1,841 parked`, zero pending; the database stands at
**3,837 posts / 17,541 releases / 17,541 sources / 21 adult rows**. Every one of those
declines is the same site-side change found in the first pass — the *Download This Movie*
section is now empty, so `harvest_links` yields nothing to store. Pass 3 re-sights the
cohort to label each row with its real reason.

**A stop must not be charged to a page's budget.** `import_filmiyin.crawl_pending`'s `work()`
returned `None` both for "the page declined" and for "we never fetched it because Ctrl-C
landed first", and the loop counted the second as the first: a graceful stop quietly spent
pages' three-read budget. `work()` now returns `(post, reason)`, `reason=None` means
"not attempted", and a test stops a crawl and asserts no row's `error_count` moved.
`parse_page` gained a `diagnostics` dict so a refusal is reported as `http-404`,
`not-a-post-page`, `no-title` or `no-playable-links` instead of one blanket
`not-indexable`, and `_bump_error` merges its note into the row's existing `raw_json`
rather than overwriting the payload the sitemap stored.

**pagalmovies: 400 was our spelling, not a deleted page.** A 127-row verdict sample came
back `removed=120, http-400=7` with zero recoveries — the parked cohort really is gone.
The 7 were not: `…/movie/958/Goal!_the_dream_begins_(2005)…` answers **400** as written and
**200** once `!` goes out as `%21` (measured live, and the site now answers on
`pagalmovies.casa`). `http_get` normalises the path it sends while `loc` keeps the site's
spelling. Re-measured row by row, **6 rows** in that whole database carry a path `_requestable`
rewrites — four with `!` (Goal! twice, Hail Caesar!, Scooby-Doo!), one with `'`
(Good luck, have fun, don't die) and one with `*` (Out of the f**king Attic); five are still
pending, and the `*` row was re-driven with the fix and came back `removed`, which is the
point: correct encoding converts *our* 400 into the *site's* answer, and the site's answer is
still no. None of the 2,694 rows already stored as `%21` need this. The figure written here
earlier, "15 rows sitting on this", did not reproduce and is retired.
`http-error` was split into
`http-<code>` so "genuinely gone" and "unlucky" are countable, a hard 404/410/451 parks on
the first sighting while anything else keeps the three-read cap, and `retry-parked` re-sights
the 7,535 parked rows to answer the owner's 404-versus-retryable question with numbers.

**mp4moviez: the largest unmergeable asset now joins the queue.** `import_mp4moviez.py` is a
converter, not a crawler. Measured plan against the real file: `29,848 legacy pages → 28,066
works, 54,267 releases, 54,267 sources, 344 duplicate pages merged, 16,168 rows skipped for
having no release, 9 takedown notices dropped, 88 adult rows carried, 0 null keys`. It ran on
a **copy** (`/tmp/mp4moviez_copy.db`) and merged through `merge_site_db` into a throwaway
target in 710 s: `posts_merged=28066 releases_merged=54267 sources_merged=54267
posts_conflicted=0`. The real `mp4moviez.db` was deliberately left in legacy form — an
in-flight merge reading it while the converter drops and renames its tables is how a run
loses rows; `convert` is one command whenever the queue is clear. Slug-as-key was tested for
the collision that would make it unsafe: 336 duplicated slugs across 681 rows, only 4
differing on (year, title) — three punctuation variants of the same film and the one takedown
notice, which is dropped. 13,680 posts hold 54,267 releases at exactly one `dl.php` id each,
across 240/360/480/720p.

**14,730 of the 29,848 stored pages are titled, dated, `c<id>`-anchored works with zero
download rows.** Re-fetched five of them: HTTP 200, 11-12 kB of HTML, 39 anchors and
**every one a category link**, no `<h1>`-`<h4>`, no `dl.php` anywhere — the site kept the
URLs and emptied the pages. (Their `data-key` attributes belong to an ad SDK mounted on
`<ins class=… data-cp-host=…>`; it is not a gated download button and no decoder turns a
UUID into a link.) So they convert as catalog entries with metadata and no sources, and
*this site has no recoverable re-drive cohort* — which is the answer to the question, not a
gap in the converter.

**The bug that merge exposed, fleet-wide.** The converter wrote every source as
`status='unverified'` with `final_url NULL`, because following `dl.php` is a play-time
decision this project never made. After the merge probe, all 54,267 unified rows read
**`active`**. `_save_scraped_data` hard-coded the status in its INSERT — one column from the
destination, the staging verdict was discarded — and `merge_catalogs` defaulted to `active`
when a staging table had no status column. Both fixed; a `test_database` case now writes
unverified / `js_required` / absent and asserts each survives. Every row any site merged
through that path was labelled active with no probe behind it, so the backfill question
belongs to the operator, not to a converter that would guess.

**SITES.md now measures instead of advertising.** New *Scraped vs merely documented* table:
`COUNT(*)` per staging database — posts, releases, sources, adult rows, queue
parked/pending, mergeable yes/no, all thirty files. It retires two claims: SITES.md
documented twelve sites while thirty databases exist, and MP4Moviez sat under *Sites To Add
Next* on `mp4moviez.cloud`, a domain nobody scraped, while 29,848 scraped pages waited on a
converter. The new § MP4Moviez says what the converter does and what it refuses to invent.

**Tests.** `test_mp4moviez_import.py` 23 (offline, socket-blocked; includes the rollback
case that breaks the write mid-migration and the `merge_catalogs` read proof), filmiyin
38→47, pagalmovies 53→59, `test_database` 75→76, `test_vidout` 6. All 14 importer suites
green.

**Commits (local, no push):** `58c0070` converter + reason diagnostics + verdict split,
`1e8d3f6` SITES.md measurements + the `%21` fix, `a6ed028` filmiyin `retry-parked` and the
stop-accounting fix, `8c7488e` the `active` status fix.

**Deliberately not done.** No push. `merged_catalog_20261025.db` and `fast_fetch.db` were
never opened; the merge proof wrote only to `/tmp`. No headless browser, so the JS-gated
`dl.php` buttons stay unparsed rather than being worked around. The real `mp4moviez.db` is
still legacy on purpose, and the 14,730 link-less pages are not filled with invented
sources. `AGENTS.md`, `docs/PROJECT_MAP.md` and the untracked `*_task.md` /
`build_mp4moviez.py` / `openrouter_*.py` files in this checkout belong to other accounts and
were left unstaged.

**Queue re-drives, final numbers (same session, later).**

*filmiyin — closed for the second time, now with evidence.* `retry-parked`
requeued all 1,841 parked URLs and re-judged every one: `pages=1841 posts=0
releases=0 sources=0 not-indexable=1841 failed=0`, declined as
`no-playable-links=1841`. The database did not move — 3,837 posts, 17,541
releases, 17,541 sources (every one `js_required`), 21 adult-flagged — and the
queue ends at 3,899 indexed + 1,841 parked + 0 pending. What changed is the
*quality* of the no: pass 2 parked the cohort on a blanket verdict, pass 3
recorded a per-row reason and zero transport failures, so "this title is gone
from the site" is now an observation stored on each row rather than an
inference. Recovery is 0 of 1,841 — the site's catalog has shrunk, and
3,837 is filmiyin's ceiling with the tools we are willing to use.

*pagalmovies — in flight at the time of writing.* The 7,535-row re-drive had
re-judged 1,088 rows, every verdict `removed` (the site's own takedown page),
0 posts recovered, 6,448 still queued at ~62 rows/minute. The final
`declined as:` histogram splits 404/410 from retryable and is what this row
must be reported on; it is deliberately not guessed here.

*The measured table is now reproducible.* All twelve importer modules answer
`stats` (`python3 -S Fast_Fetch/importers/import_<site>.py stats`) and every
`posts` count printed matched the SITES.md row exactly: 5movierulz 442, animahd
232, aryplus 481, desiserials 34, dramacool 544, filmiyin 3,837, kisskh 669,
levidia 147, moviecok 1,738, moviesmela 16,677, mp4moviez 29,848, pagalmovies
6,842. SITES.md now names that command instead of relying on my ad-hoc queries.

*One more retired claim, my own.* The "download buttons moved behind a
`data-key` handler" story was wrong: on five frontier mp4moviez pages the
`data-key` attributes sit on `<ins class=… data-cp-host=…>` ad-SDK elements, the
pages carry 39 anchors that are all category links, no `<h1>`–`<h4>`, and zero
`dl.php` references. The 14,730 link-less work rows are emptied pages, not
gated ones — nothing there is recoverable by crawling, and task #11 is closed
as answered rather than as finished.

