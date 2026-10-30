# Session 2026-10-30 (q2 lane) — `[Q2-MB-CRAWL-20261030]`: the first real MovieBox crawl, bounded, honest numbers

Branch `q2-mb-crawl-20261030` off `55da3ea` (the mint verdict). Worktree `/tmp/q2_moviebox`,
vault `/home/ubuntu/radd-stream-data/themoviebox.db` (staging only — no merge, no
`/opt/radd-stream`, no `fast_fetch.db`).

## Gate held throughout

| | load1 | MemAvailable | SwapFree |
|---|---|---|---|
| before harvest | 2.85 | 6.2 GB | 3.45 GB |
| before crawl | 3.62 | 6.2 GB | 3.45 GB |
| after crawl | 3.47 | — | — |

Gate was load1 < 4, MemAvailable > 3 GiB, SwapFree > 2 GiB; the stop line (5.5) was never
approached. `nice -n 19`, single worker, 3 s floor between requests.

## What ran, and what it said

`harvest --pages 2 --limit 40` — 100 feed items, **88 duplicates, 12 non-works, 0 new**:

```
[✓] [themoviebox] harvest items=100 posts=0 duplicates=88 skipped_type=12
{"duplicates":88,"items":100,"posts":0,"queued":0,"skipped_type":12,
 "stop_reason":null,"stopped_for_memory":false}   rc=0
```

The popular feed's first two pages are the same set of works shuffled: everything on them is
already queued. **No new works exist to be added at this bound** — that is the honest answer,
not a failure. Deeper pages are where new works are, and each costs a request.

`crawl --limit 12 --workers 1 --delay 3` — 12 rows, 158 releases, 0 sources, 0 failures, 35 s:

```
[✓] [themoviebox] pages=12 posts=12 releases=158 sources=0 metadata_only=12
                  with_media=0 failed_rows=0 parked=0 in 35s
{"api_pages":0,"failed":0,"failed_rows":0,"metadata_only":12,"pages":12,"parked":0,
 "paused_rate_limit":false,"posts":12,"releases":158,"skipped_after_stop":0,"sources":0,
 "stop_reason":null,"stopped_for_memory":false,"with_media":0}   rc=0
```

## Stats BEFORE and AFTER

```
BEFORE  works 44  crawled  0  queued 44  releases   0  sources 0  series 44  movies 0
AFTER   works 44  crawled 12  queued 32  releases 158  sources 0  series 44  movies 0
```

`metadata_only_posts` 44 both times; `trailer_evidence_posts` 41 both times.

The 12 re-crawled rows are genuinely series (`subjectType: 2`), so `series: 44, movies: 0`
describes the popularity feed's composition, not a parser defect. Example — *All American
S1-S8*: `seasons [1..8]`, 24 releases (3 tiers × 8 seasons), per-season `episodes` 16/13/…,
`available_resolutions [1080,720,480,360]`, and **`play_url: null` on every release** — the
declared tiers, with no URL invented for them.

## Finding for the next pass (not fixed here)

`api_pages: 0`: these rows were queued by the pre-detail-API `sync`, so `sitemap_cache.raw_json`
is `{}` and the crawl used HTML pages (~410 KB) instead of the JSON detail answer (~39 KB).
The pages *do* carry `subjectId` and the re-crawl now stores it in `posts.raw_meta`, but it is
not written back to `sitemap_cache`, so the next pass will still choose HTML. A one-line
stamp-on-crawl would hand the remaining 32 rows the 10× cheaper surface; it needs its own test,
so it is proposed rather than slipped into this branch.

Also visible on these HTML-sourced rows: `audio_languages` still merges dubs and subtitles into
one list (the detail-API path splits them; the HTML path keeps the older merge), which is another
reason the stamp belongs in the plan.

## What was NOT done

No merge into any catalog, no re-derive, no `viewer.py`, no service restart, no new works added
(none were available at this bound), no source URL written for a site that has no public play
grant. Peak RSS was not instrumented; the crawl is single-worker, 35 s, and RSS growth was
visibly absent but that is an observation, not a measurement.
