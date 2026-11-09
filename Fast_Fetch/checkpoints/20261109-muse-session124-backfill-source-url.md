# Session 124 — backfill_cast.py reads `source_url` (mp4moviez)

2026-11-09 ~11:44–11:55 PKT, self-check run (radd-self-check-5m). Follow-up to the
Session 123 gate-deploy cast backfill, which filled 43,775 posts across 22 sites
but crashed on `mp4moviez.db` with `sqlite3.OperationalError: no such column: url`
— its posts table names the page column `source_url`, not `post_url`/`url`, so its
29,848 cast rows (biggest single source) were never filled.

## Fix (`Fast_Fetch/backfill_cast.py`, `cast_rows`)

- URL column is now the first present of `post_url`, `url`, `source_url`
  (was: `post_url` if present else `url`, unconditionally — the crash).
- A staging table with cast but none of the three URL columns now raises a
  `ValueError` naming the columns it looked for, instead of crashing on a
  missing `url` or silently skipping the database.

## Tests (`Fast_Fetch/test_backfill_cast.py`, 4 → 6)

- `test_source_url_column_is_read`: a `source_url`-only staging DB with no
  `site` column fills its catalog post (site defaults to the db stem
  `mp4moviez`); `stats["sites"]["mp4moviez"]["filled"] == 1`.
- `test_no_url_column_raises`: no URL column at all → `ValueError`.

## Verification

- `python3 -S Fast_Fetch/test_backfill_cast.py`: **6/6 OK**.
- Negative control: both new tests fail on the pre-fix code with exactly the
  reported error (`no such column: url`), pass with the fix.
- Full backend gate + CI: see the push note below (branch
  `session124-backfill-source-url`).

## Not done (parent gate)

- Merge to main + gate-deploy, then re-apply the backfill for mp4moviez only
  (`--site mp4moviez --apply`) — the re-apply writes the live catalog, so it
  goes through the gate with backup first. The 11:30 run's lock lesson applies:
  report mode also takes the write lock, so run it clear of the service's
  maintenance tick.
- mp4moviez_staging.db / mp4moviez_staging2.db matched 0 catalog posts in the
  11:30 run — separate data question, not this fix.
