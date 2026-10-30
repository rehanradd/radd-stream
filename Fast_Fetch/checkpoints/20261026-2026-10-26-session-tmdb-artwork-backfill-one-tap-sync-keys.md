# 2026-10-26 — Session: TMDB artwork backfill + one-tap sync keys (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-26 — Session: TMDB artwork backfill + one-tap sync keys (Qoder)

### Completed
- **`Fast_Fetch/backfill_tmdb.py`** (new, stdlib only): fills missing `posts.poster_url`
  and `posts.backdrop_urls` from TMDB via a stored `tmdb_id`, an IMDb `/find`, or a
  conservative cleaned-title search; refills `tmdb_id`/`imdb_id` when they were absent.
  Updates only missing root art unless `--force`. Credentials come from
  `TMDB_BEARER_TOKEN` / `TMDB_API_KEY` in the environment only — never a CLI argument or a
  log line. Resumable (`--after-id`), rate-paced, retries 429/5xx without logging the URL
  or key, and it never writes to a staging database unless `--db`/`--site` names one.
- **`post_artwork` table** (`fast_fetch.py`): one row per (post, kind, season, episode) so
  a work keeps one poster and each season keeps its own. Season posters and episode stills
  are fetched from TMDB; a season with no poster never inherits the root poster.
- **`viewer.py`**: `GET /api/v1/posts/{id}` now adds `season_artwork` as
  `{kind, season, episode, url}`. Only URLs on `redact.PUBLIC_IMAGE_HOSTS` are emitted;
  anything else is dropped rather than minted into an unresolvable handle.
- **`redact.py`**: added `public_image_value()` so the season rows use the same
  public-host rule as work art.
- **`accounts.py`**: minted keys are now 16 characters / 96 bits
  (`secrets.token_urlsafe(12)`); `MIN_SYNC_KEY_CHARS` is 16 so the app's phone-derived key
  is admitted. The module docstring, limiter notes and `_hash_key` docstring state plainly
  that a phone-derived key inherits the phone space's low entropy and is a convenience,
  not a secret; the server never receives the number and cannot distinguish the two.
- **`DATABASE_SCHEMA.md` / `API_V2.md`**: documented `post_artwork`, its index, and the new
  key length + phone-derived-key caveat.

### Checks
- `test_database` 58 OK, `test_vidout` 6 OK, `test_backfill_tmdb` 23 OK,
  `test_redact` 49 OK, `test_accounts` 61 OK, `test_accounts_api` 29 OK,
  `test_catalog_v2` 91 OK, `test_provenance_stamping` 12 OK.

### Not done
- No TMDB run was performed here (no credential was read); the script is verified by its
  offline tests. Nothing committed — the tree already carries unrelated workstreams.

