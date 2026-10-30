# Previous checkpoint — 2026-10-21 (Milestone 7)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Previous checkpoint — 2026-10-21 (Milestone 7)

- **Goal:** Rule change per owner directive — scrapers no longer skip adult content; 100% of each site's catalog is stored with full metadata/links behind an `is_18_plus` flag column in every staging database; every presentation surface (REST API, dashboard, M3U, stream resolver, Android app) filters `is_18_plus=1`.
- **Completed:**
  1. Rules rewritten in root `AGENTS.md` and `Fast_Fetch/AGENTS.md` (store flagged, never display).
  2. `fast_fetch.is_adult_title()` shared helper added (fixed latent `\b18\+\b` regex bug); `resolve_live_source()` blocks 18+ source ids.
  3. Flag-not-skip conversion in 5 scrapers; `is_18_plus` inserted (MAX-merged) in all 10 custom-schema scrapers; CREATE + ALTER migrations in each.
  4. All 16 staging DBs now carry `posts.is_18_plus`; 795 previously skipped adult posts re-queued; 36,848 failed posts reset to pending fleet-wide.
  5. `viewer.py` API/dashboard/M3U filters exclude flagged rows.
- **Checks run:** 21/21 offline test modules; import checks; helper smoke tests; synthetic adult-save verified.
- **Fleet:** 15 scrapers relaunched at full speed (sync-then-crawl, workers=4, delay=0.2); KatMovieHD heal still running from earlier.
- **Next action:** Monitor fleet to completion, verify per-site `is_18_plus=1` counts, snapshot databases to Hugging Face.

