# 2026-10-30 (cont.) — MovieBox: detail-API parser, credits/backdrop/languages fixed, crawl gate refused `[Q2-MOVIEBOX-CRAWL]`

> Rotated verbatim out of `docs/SESSION_CHECKPOINT.md` by the q3 documentation diet, 2026-10-30.
> Absorbed during the rebase onto trunk `4fe6f65` (trunk moved while this diet was
> open, so this entry was written to the append-here file after the rotation had
> already happened — the rebase moved it here instead of dropping it).
> Source: `git show 4fe6f65:docs/SESSION_CHECKPOINT.md` lines 3073-3088. Not edited, not summarised.

---


### 2026-10-30 (cont.) — MovieBox: detail-API parser, credits/backdrop/languages fixed, crawl gate refused `[Q2-MOVIEBOX-CRAWL]`

- **Load was 7.01 (gate 5.5), so step 1 did not run.** Zero network requests this session; one
  read-only SQLite query confirmed `themoviebox.db` = 44 posts / 0 releases / 0 sources (FAIL shape).
- **Parser fixed before any crawl, with tests:** `stills` as a dict → `backdrop_url`; `seasons`
  stamped after declared tiers land (was NULL with 20 releases); `stars[]` → cast/director/writers
  (character/staffType, deduped); `dubs[]` split into audio vs subtitles; `metadata.keyWords` kept;
  per-season `epNum` on `raw_meta.declared_renditions`. New `parse_detail_api()` for the measured
  public `GET /wefeed-h5api-bff/detail` (200, 39.8 KB, no credential); crawl prefers it when the
  row carries a `subjectId`, else HTML, and a non-detail answer fails retryably without a token.
- **`test_themoviebox_detail_api.py` 18/18 green** (offline) and neighbour `test_themoviebox_links`
  7/7; new CI step added. `test_themoviebox_import.py` left to CI (fleet rule: one neighbour).
- **Queued:** the 44-row re-derive (`crawl --limit 44 --workers 1 --delay 1.0`), then 50/500/full
  under the load/RAM/429/RSS gates; 20-item probe and 10-title sample after that. Verdict unchanged:
  posts with zero sources is a FAIL, and the site publishes no playable URL on either surface.
