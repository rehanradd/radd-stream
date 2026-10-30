# Session 2026-10-29 (night) — Filmywap banned, FilmyHit running, one parser fix

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (night) — Filmywap banned, FilmyHit running, one parser fix

**Filmywap is still under a host-wide 429.** A single probe at 02:31 (detail page and
`/api/stream`) returned 429, so the crawl was not forced. The cooldown-aware build ran
once, saw a 500 then a 429 after three pages, and stopped with `paused=rate-limited`
instead of spending the remaining queue. State: 46 posts / 2,069 releases, 1,476 rows
queued at attempt ≤2, 46 scraped. Resume only after the ban lifts (measured > 1 h last
time) and with `--delay 0.5` or slower; the burst that likely triggered it is the ~22
episode API calls per series title.

**FilmyHit is the active crawl slot.** Sitemap re-synced to 16,945 detail URLs in
`filmyhit.db`. The first 112 posts were crawled on the previous build, then the crawl
was restarted on a parser fix: live detail pages repeat each bridge href on the poster
anchor (an `<img>`, no text) before the labeled download button, so the empty text won
the dedupe. `releases_from_page` now keeps the first non-empty label. Verified on freshly
staged rows (`label_text` = "… 254 MB · MP4"). Crawl restarted at 02:44 as PID 871532
(`--workers 1 --delay 0.5`, nice 15): 16,833 pending, ~25 pages/min, ≈11 h. No 429, no
failed rows so far, 142 posts.

**KuttyMovies** remains queued (905 rows, 0 scraped) behind the single crawl slot.

**Commits.** `89b5d56` cooldown, `a744458` SITES §16 note, `b1e16e6` FilmyHit anchor fix —
all pushed to `master` and `main` via the explicit URL. Gate at `89b5d56`: 363 green.

