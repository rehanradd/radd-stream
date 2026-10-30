# Session 2026-10-29 (late) — rate-limit cooldown and an honest failure count

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (late) — rate-limit cooldown and an honest failure count

The Filmywap crawl collapsed from ≈2.3 titles/min to nothing after 41 posts. The ledger
said why: 1,476 rows at `http-429` and 1 parked row (`http-500`) out of 1,518 pages
attempted. A single fresh probe afterwards returned `HTTP/2 429` for a detail page *and*
for `/sitemap.xml`, with no `Retry-After`: the host was rate-limiting the whole VM, not
one URL. The old loop still logged that as `dead=1477` even though every 429 row was
`scraped=2`, attempt 1 — retryable, not dead.

**Cooldown, all three importers.** `RATE_LIMIT_STATUS = 429` plus a module-level
`threading.Event` (`_RATE_LIMITED`), cleared at crawl start. The first 429 sets the event
and is recorded as `kind="rate-limited"` on that row (a real request did happen); every
later queued row's `work()` returns without a request or an attempt. The loop breaks, and
totals now report `failed_rows`, `parked` and `paused_rate_limit`, printed as
`paused=rate-limited`. Nothing is silently marked dead.

**Tests.** `dead_ids` assertions moved to `failed_rows`/`parked` (park only for
404/410/rest-empty), and each module gained a two-row 429 test that asserts one request,
one row at `scraped=2`, and the other untouched at 0/0.

**Gate — 363 tests, all green:** `test_database.py` 76, `test_vidout.py` 6,
`importers/test_host_resolvers.py` 171, `import_filmywap` 34, `import_filmyhit` 31,
`import_kuttymovies` 45.

**Crawl state.** Filmywap stopped at 41 posts / 1,208 releases; 1,477 rows remain queued
at attempt 1 and will be picked up by the cooldown-aware build once the host's 429 lifts.
FilmyHit and KuttyMovies are still uncrawled, waiting for the single crawl slot.

**Push disclosure.** Commit `11742e0` was pushed to `master` and `main` via the explicit
`https://github.com/rehanradd/radd-stream.git` URL. Because the local branch was three
commits ahead of the remote (which sat at `fdf226f`), that push also carried qoder1's
already-committed local work (`926cec9`, `9eee9a7`, `1a6657e`) — docs-only app-session
edits. No force, no history rewrite, nothing lost; recorded here so the owner knows what
moved.

