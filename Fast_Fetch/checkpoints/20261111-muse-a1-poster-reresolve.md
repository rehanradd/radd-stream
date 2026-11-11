# 2026-11-11 — Muse [A1-POSTER-RERESOLVE]: `--poster-url` scope for backfill_tmdb.py

Gap A1 (artifact-gap-review-20261111): 13,234 posts share the Masterplan poster
`https://image.tmdb.org/t/p/original/7ULXMNvmZSi13zN3EZjz8wbER9B.jpg`
(Fall post 7648 among them). Verified read-only against the live catalog:
13,234 rows, ids 30–72,696, written 2026-10-24 19:51–20:23 (one ~32-min bad
import window); zero affected rows with id > 140,000, so the bug is
historical, not an ongoing scraper fault — a re-resolve will stick.
Affected sites: vegamovies 8,503, hdhub4u 1,603, katmoviehd 911,
hindilinks4u 852, 7starhd 783, hdtvb 400, rareanimes 139, desicinemas 38,
toonworld4all 5. Only 2,087 carry a tmdb_id (all distinct), 4,121 an
imdb_id; Fall 7648 has neither. Stored tmdb_ids are trustworthy: Cinemeta
cross-check on Tom and Jerry (tt1361336) returns moviedb_id 587807, exactly
the stored value. `post_artwork` is empty (0 rows).

Fix (code only — the live data run is parent-gated): `backfill_tmdb.py` gains
`--poster-url <url>`, which scopes a `--force` run to the rows carrying that
exact poster_url. Without the filter, `--force` re-reads the whole catalog;
with it, only the wrong-poster rows are candidates. `--poster-url` without
`--force` is rejected (parser error) so the run cannot silently do nothing.
The re-resolve still uses the script's existing guards (stored tmdb_id, then
IMDb `/find`, then title search with the year guard — a miss stays a miss).

Tests: `test_backfill_tmdb.py` gains `PosterUrlScopeTests` (3 tests: the
filter rewrites only the wrong-poster row end-to-end, the SQL binds the
poster before the id cursor, `--poster-url` without `--force` exits 2).
The suite is now registered in `backend-ci.yml` (84 suites, was 83) and
removed from `UNREGISTERED` in `test_docs_invariants.py` plus the workflow
header's EXCLUDED list. Tests: backfill_tmdb 38, docs_invariants 22,
ci_manifest 10 — all OK solo. Branch `muse/a1-poster-reresolve-20261111`.

NOT done here: the live re-resolve itself. Next step (parent gate):
`--poster-url <masterplan-url> --force --dry-run` on a staging copy of the
live catalog, review the match rate, then the gated live run with backup.
