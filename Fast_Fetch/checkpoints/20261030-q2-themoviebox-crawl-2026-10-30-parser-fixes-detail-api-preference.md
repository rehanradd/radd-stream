# [Q2-MOVIEBOX-CRAWL] 2026-10-30 — parser fixes + detail-API preference; crawl gate closed

> Rotated verbatim out of `Fast_Fetch/CONTINUITY.md` by the q3 documentation diet, 2026-10-30.
> Absorbed during the rebase onto trunk `4fe6f65` (trunk moved while this diet was
> open, so this entry was written to the append-here file after the rotation had
> already happened — the rebase moved it here instead of dropping it).
> Source: `git show 4fe6f65:Fast_Fetch/CONTINUITY.md` lines 3528-3627. Not edited, not summarised.

---


---

## [Q2-MOVIEBOX-CRAWL] 2026-10-30 — parser fixes + detail-API preference; crawl gate closed

**Branch:** `q2-themoviebox-crawl`, based on `dc73ac7` (the landed `9b08e51` fix, cherry-picked by q4).

**State at start (measured, read-only, one query):** `themoviebox.db` = **44 posts / 0 releases /
0 sources** — the FAIL shape the owner named. All 44 queued rows carry `raw_json = {}` (no
`subjectId`), so they can only be re-derived from their HTML pages.

**Load gate refused step 1.** `/proc/loadavg` was **7.01** (5-min 6.66, 15-min 5.72), MemAvailable
2.71 GB, swap free 2.54 GB, one vCPU. The brief says stop if load1 > 5.5 mid-run; starting at 7.0
is the same violation at t=0. **No crawl, no re-derive, zero network requests this turn.** The load
source is `/opt/radd-stream/Fast_Fetch/backup_manager.py --dir … --hf` plus five qodercli lanes.

**Done instead (light, offline, no sockets):** the parser fix for every gap the captured answer
proves, with tests, before any crawl — exactly the order the brief asked for.

- `import_themoviebox.py`
  - `_image_list` accepts one image object (the site's `stills` is a dict) and `backdrop_url`
    falls back to the first still, so the only wide image no longer lands nowhere.
  - `_stamp_seasons()` writes `seasons` after the declared renditions land (was `NULL` while 20
    releases each named a season).
  - `_enrich_with_declared_media()` stores `raw_meta.declared_renditions` (per-season/tier
    `epNum` + `source_host`) on the post.
  - New `parse_detail_api(payload, page_url)` for `GET /wefeed-h5api-bff/detail?subjectId=…`
    (measured 200, 39,788 B, **no credential** vs 409,998 B for the same HTML page).
  - New `_apply_detail_evidence()` + `_credits_from_stars()` + `_split_dubs()`: `stars[]` →
    cast / director / writers (character "Director"/"Writer", staffType 2/3, deduped by
    `staffId`); `dubs[].type` 0/1 + `subject.subtitles` split into audio vs subtitles;
    `metadata.keyWords` kept. Applied on both surfaces (HTML only when the page names one work,
    the same gate the tier enrichment already used).
  - Crawl now prefers the API when the queued row carries a `subjectId` (`sync`/`harvest` stamp
    it), falling back to the page for legacy `{}` rows. A non-detail answer fails the row
    (`scraped=2`, retryable) and is never answered with a token.
- `test_themoviebox_detail_api.py` (new, offline): **18 tests green** — every field in the
  declared-vs-stored table, export to in-memory SQLite, the HTML path, and three crawl-surface
  tests that prove `subjectId` rows hit the JSON URL, `{}` rows hit the page, and an auth-shaped
  answer fails without replaying a credential.
- Neighbour `test_themoviebox_links.py`: **7/7 green** (one module, `nice -n 19`, one at a time).
  `test_themoviebox_import.py` was **not** run locally (fleet rule: own module + at most one
  neighbour); it exercises the importer I changed, so CI is its first judge.
- `backend-ci.yml`: new step `🧪 test_themoviebox_detail_api.py` right after the links step.
- `SITES.md` §25: the API-preference rationale and the field-by-field diff table.

**Measured cost this turn:** 0 HTTP requests, 0 hosts touched; one read-only SQLite query (44 rows);
test wall 49 s at load ~7 (CI will be seconds). No writes to `themoviebox.db`, merged_catalog, or
`/opt/radd-stream`. No restart, no tag, no merge.

**NOT verified (network gate closed):** that the live detail API parses end-to-end through
`crawl` (only mocked), the 20-item declared-vs-stored probe, and the 10-title "everything" sample.
They are queued below.

**Queued step 1 — re-derive the 44 rows, run only when load1 < 4 (brief stop line 5.5):**

```bash
nice -n 19 ionice -c3 python3 -S \
  /tmp/q2_moviebox/Fast_Fetch/importers/import_themoviebox.py \
  crawl --limit 44 --workers 1 --delay 1.0 --db /home/ubuntu/radd-stream-data/themoviebox.db
```

Expected: 44 pages × ~410 KB ≈ 18 MB; the edge resets ~2/3 handshakes from this host, so up to
~132 transport attempts at delay 1.0; wall ~5–15 min; RSS < 100 MB; **releases ≈ 880** (44 × 20 on
captured-shaped series), **sources = 0**. The crawl prints counts; if load1 crosses 5.5, Ctrl-C is
safe — rows already `scraped=1`, the rest stay `0`, and the command resumes. Then re-query
`SELECT COUNT(*) FROM posts/releases/sources` and append the numbers here.

**Queued steps 2–4 (after step 1):** `sync --pages 1` stamps `subjectId` on new rows; re-crawl
`--limit 50`, then `500`, then full **only** while load1 < 4, MemAvailable > 3 GiB, swap free >
2 GiB, zero 429s, RSS growth < 50 MB/100 items. The 20-item probe = SQL over
`raw_meta.declared_renditions` vs `COUNT(*) FROM releases` per post + a 10-title dump of declared
tiers/mirrors vs stored releases/sources. **The vault stays a FAIL until some surface publishes a
playable URL; nothing here changes that.**

### [Q2-MOVIEBOX-CRAWL] 2026-10-30 — q4 gate: DiscoveryTests were memory-floor failures, not feed regressions

q4 gated `32d928b` and saw 4 failures in `test_themoviebox_import.py` (DiscoveryTests) on a quiet
box. **Cause measured here: the memory floor, not the feed contract.** `/proc/meminfo` read
`MemAvailable 2,078,168 kB (≈2029 MB)`, below `MIN_MEM_AVAILABLE_MB = 2500`, so `_walk_feed`
returns after logging before its first request — every one of the four failed with `items: 0` and
`api.call_count: 0`. The feed-walk code was not changed by this commit; the tests simply ran on a
box whose lanes were swapped out. `test_the_feed_is_walked_once…` was passing *vacuously* for the
same reason.

Fix: the five DiscoveryTests that walk the feed now patch `mb.memory_ok` to `(True, "ok")`, exactly
as `CrawlTests` already did. **No assertion was changed** — the feed/sitemap/dub/error/metadata
contracts are asserted verbatim as before, and the walked-once test now actually inspects request
bodies instead of an empty list. The memory floor itself is untouched and remains a test of its own
(`test_memory_floor_reads_real_meminfo`).

Also corrected q4's edge note: the ~31% TLS figure was measured under heavy local load. At load 8.2
q4 saw a TLS reset after a 0.99 s TCP connect and a SYN that never connected; at load 1.9 one
request answered in 1.1 s. `SITES.md` §25 and the module docstring now say to attribute a transport
failure to the site only below load 4.

**Gate run on this box (load 1.4–1.8, amber memory — no crawl, no live request):**
`test_themoviebox_import.py` **47/47**, `test_themoviebox_links.py` **7/7**,
`test_themoviebox_detail_api.py` **18/18**, `test_database.py` **133/133**. Rebased onto trunk
`7b01f46`. The 44-row re-derive remains queued: start only when load1 < 4 AND SwapFree > 2048 MB.
