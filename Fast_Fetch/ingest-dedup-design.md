# Ingest dedup — design note (2026-11-12, branch muse/ingest-dedup-20261112)

## What is broken (measured, not assumed)

Live catalog, read-only probe 2026-11-12 ~07:00 PKT
(`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`, `mode=ro`):
- `Salaar`: 10 posts, 10 distinct `canonical_key`s.
- `One Piece`: 65 rows matching `clean_title LIKE '%One Piece%'`
  (incl. a slug-keyed legacy row `one-piece-001-812-seasons-01-19-ultimate-batch-english-jap`).
- `ongoing_season`: 363 posts; `complete_season`: 2,148 posts.
- 189,710 posts (85%) carry no `imdb_id` and no `tmdb_id` (per brief) — ID
  matching alone cannot dedup.

## Where identity lives today (read first)

- `fast_fetch.generate_canonical_key(title, year)` — the key builder.
  Strips `[...]`/`(...)` segments, then a token list (`480p`, `s\d+`, `season\s*\d+`,
  `complete`, …), then slugifies. `ledger_canonical_key(clean_title, year, supplied)`
  is what a *new* ledger row is filed under; the `_s<N>` supplied-key exception
  keeps `mobland_s1` / `mobland_s2` apart (genuine seasons stay apart).
- `fast_fetch._find_existing_post` — match order: page URL → IMDb/TMDB id →
  exact `canonical_key` (single candidate only; >1 raises). No fuzzy step.
- `fast_fetch._save_scraped_data` — adopts the stored row's key on match,
  guarded by `guard_canonical_key`; releases are inserted verbatim.
- `merge_catalogs.merge_site_db` — collapses rows with the SAME `canonical_key`
  onto one anchor URL (same-media-type guard + `_has_episode_evidence` escape);
  identity conflicts raise out of `save_scraped_data` and land in `merge_conflicts`.
- `catalog_v2.project` — groups posts into works by
  `work_key_for(clean_title, year, …)` → `normalize_title` (strips brackets only);
  seasons/episodes are already ints in `cat_*` (`release_descriptor._detect_index`
  + `_hint_int`), so the projection does NOT split '1' vs 'S01' — the split lives
  in the ledger (`releases.season`/`episode` TEXT) and in the work key.

## The actual hole (proven in-process, not guessed)

`generate_canonical_key` on the volatile variants:

| title | key |
|---|---|
| `One Piece [S01E08 Added]` | `one-piece_2023` |
| `One Piece [S01E09 Added]` | `one-piece_2023` (same — bracket strip works) |
| `One Piece S01E08` | `one-piece-s01e08_2023` |
| `One Piece S01E09` | `one-piece-s01e09_2023` (DIFFERENT — duplicate post) |
| `One Piece S01 E08 Added` | `one-piece-e08-added_2023` |
| `One Piece Season 1 Episode 8` | `one-piece-episode-8_2023` |
| `Campus Beats S07EP(01-06)` | `campus-beats-s07ep_2026` |
| `Campus Beats S07 Complete` | `campus-beats_2026` (different — would split if keys were derived) |

So the bracketed form was already safe; the **unbracketed** episode marker is the
hole. A re-scrape that writes the count unbracketed creates a new post per episode.

## (a) Stable key — strip the volatile episode suffix before keying

New helper in `fast_fetch.py`, applied inside `generate_canonical_key`
(after the bracket strip, before the token strip), so `ledger_canonical_key`,
`_title_token_sets` and every caller inherit it:

- `\bs\d{1,2}\s*e\d{1,4}\b` — S01E08, S1E8, S01 E08
- `\bs\d{1,2}\s*eps?\b` — S07EP (the `(01-06)` half is already bracket-stripped)
- `\bep(?:isode)?s?\s*\(?\d{1,3}\s*(?:[-–]\s*\d{1,3})?\)?` — EP(01-06), Episode 8, E08
- `\bseason\s*\d{1,3}\s*(?:episode|ep)\s*\d{1,4}\b` — Season 1 Episode 8
  (bare `Season 2` was already stripped by the existing token rule)
- `\badded\b` — the scraper's volatile word (per brief; a real work is never
  titled "Added …")

Deliberately NOT stripped: `Part N` / `Chapter N` (Salaar Part 1 vs Part 2 are
different films — `test_catalog_v2` already pins that), bare years, bare `Episode`
with no digits, and the `_s<N>` supplied-key exception in `ledger_canonical_key`
(season identity is real identity, episode-count is not).

`catalog_v2.normalize_title` gets the same strip (mirrored regex, cross-referenced
in a comment — `catalog_v2` must not import the 8,800-line `fast_fetch`), so two
ledger rows of one ongoing season project to ONE `cat_work` even before the
ledger itself is re-keyed. Stored `clean_title`/`title` are NOT rewritten:
only the derived key changes; re-keying stored rows is the already-planned,
separately-reviewed migration.

## (b) Fuzzy fallback in `save_scraped_data` — same work, different key spelling

New `fast_fetch._find_fuzzy_title_year_match(conn, …)`, called from
`_find_existing_post` ONLY after the exact-key step finds nothing:

- Requires an incoming year (no year → no fuzzy match, a new post as today).
- Candidate pool: `posts WHERE year = ?`, filtered in Python by
  `_post_type_matches` (same media family), no `_identity_values_conflict`,
  and **normalized-base equality**: both the derived base
  (`generate_canonical_key(clean_title)`, volatile-stripped by (a)) and the
  stored key's base (trailing year removed, separators unified, volatile
  suffix stripped the same way) must be equal. This is what catches the
  legacy slug-keyed rows (`puli-2015` vs derived `puli_2015`) and
  pre-fix keys (`one-piece-s01e08_2023`).
- Exactly 1 candidate → attach (return it). 0 → new post, as today.
  >1 → `ValueError("Fuzzy title+year match is ambiguous …")` — the merge
  path already catches that into `merge_conflicts` and continues; a direct
  `save_scraped_data` caller sees the same refusal shape as today's
  "matches multiple records" error. **No silent merge, ever.**
- The adult flag is part of the match: a candidate whose `is_18_plus`
  disagrees with the incoming row is NOT a candidate. A flagged page
  attaching to an unflagged twin would hide that twin via `MAX` +
  `inherit_key_adult` without the evidence `reconcile_adult_on_merge`
  demands (only a flag `is_adult_title()` can reproduce folds — the
  407-work boundary; the disputed `Nenokkadine` case is the proof). Such
  twins stay twins for the fold to decide, exactly as before. This is why
  the three `MergeTimeAdultReconciliationTests` still pass unchanged.
- What this deliberately does NOT do: merge subtitle variants
  (`salaar_2023` vs `salaar-part-1-ceasefire_2023` — different normalized
  bases, still separate posts). That is a different-work judgment no
  title+year rule can make safely; it stays a duplicate until a human or a
  stronger (cast/TMDb) signal decides it. A wrong merge is worse than a duplicate.
- Cost: one `WHERE year = ?` scan per genuinely-new ingest (no year index
  exists). Ingest/merge runs offline; correctness first, and the scan only
  fires when URL, ID and exact-key matching all missed.

## (c) Season/episode — one format at ingest

New `fast_fetch.normalize_season(value)` → `"S01"` / `None`, and
`normalize_episode(value)` → `"E01"` / `None`:

- Normalizes only a SINGLE number with an optional prefix:
  `1`/`S01`/`Season 2` → `S01`/`S02`; `1`/`E01`/`Episode 3`/`ep 3` → `E01`/`E03`.
  `S00` → `S00` (specials stay addressable).
- The literal pack label `Batch` → NULL (both columns). Baseline 2026-11-12:
  `Batch` is the ONLY non-numeric episode value in the live catalog
  (10,525 releases, 0.5%); seasons carry no such value. A pack print names no
  single episode, so NULL is the honest value — the pack-ness still shows in
  the release title / `is_pack`. No other unparseable value is NULLed.
- Passes everything else through UNCHANGED: ranges (`01-06`, `E01-E06`),
  multi-values, and non-numeric labels (`Specials`, `Complete`).
  Collapsing a range to its first episode would invent an episode that does
  not exist; dropping a label would destroy data.
- Enforced in `_save_scraped_data` (every release row, insert path — the one
  funnel all scrapers and merges go through) and mirrored in
  `merge_catalogs._collect_staging_post` / `_collect_unified_post` so the
  collector output is already canonical.
- `catalog_v2.py`: no schema change — `cat_seasons.number` /
  `cat_episodes.number` are already INTEGER, and `_hint_int` /
  `release_descriptor._detect_index` already collapse '1' vs 'S01'. The
  catalog_v2 change is the `normalize_title` strip from (a), plus tests
  proving one `cat_season` from mixed-spelling releases.

## Tests (all in existing CI-listed modules — no manifest change needed)

- `test_database.py` (`DatabaseSaveTests`): ongoing-season re-scrape attaches
  (S01E08 → S01E09, unbracketed); fuzzy attach to a legacy slug-keyed row;
  ambiguous fuzzy raises and leaves 2 posts; different year does not fuzzy-merge;
  season/episode stored as S01/E01 from mixed spellings; ranges/labels pass through.
- `test_merge_catalogs.py`: staging re-scrape of an ongoing season merges to 1 post;
  ambiguous fuzzy at merge time is recorded in `merge_conflicts` and the merge continues.
- `test_catalog_v2.py`: two ledger rows of one ongoing season (different episode-count
  clean_titles) project to 1 `cat_work`; releases with season '1' and 'S01' land in
  1 `cat_season`.

## Not done by this change (stated so the coordinator can scope it)

- No re-key migration for the 224k stored rows (Salaar's 10 keys, etc. stay
  until that separately-reviewed migration runs). This change only stops NEW
  duplicates at ingest; the fuzzy fallback attaches NEW scrapes to ONE legacy
  row when it is unambiguous.
- No subtitle-variant merging (`Salaar` vs `Salaar Part 1 Ceasefire`).
- No live deploy (coordinator's call via the gate).
