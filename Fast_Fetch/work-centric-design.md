# Work-centric API — design note

Branch: `muse/work-centric-api-20261112`. Base: `88019eccc` (main,
rebased 2026-11-12 from `aa37814e`; see §7).
Author: rehanradd <rehanradd@gmail.com>. Date: 2026-11-12.

## 0. What is true today (verified, not re-proved)

- `/api/v1/posts` serves raw `posts` rows. One movie/series = many posts
  (Salaar: 10 posts; the `cat_works` projection already splits it into
  8 work keys — `movie:salaar:ny`, `movie:salaar part 1 ceasefire:2024`,
  `movie:salaar part 1 ceasefire:2023`, `imdb:tt13927994`, … — so the
  projection cannot be the grouping authority; it inherits the same
  title/year/id fragmentation it was meant to cure).
- `cat_works` / `cat_seasons` / `cat_episodes` exist (197,530 / 210,902 /
  207,538 rows live) but no public route reads them.
- `catalog_v2.normalize_title` strips bracketed/paren content and
  punctuation, so an ongoing title like `Show [S01E08 Added]` already
  normalises to the base title. `work_key_for` prefers `imdb:` / `tmdb:`
  keys and falls back to `family:normalized title:year`.
- 189,710 posts (85%) have no `imdb_id` and no `tmdb_id`: id matching
  alone cannot dedup. `merge_catalogs` matches on `canonical_key`
  (title+year); a slightly different title files a new post.
- Season is stored as both `1` and `S01`; episode as both `E01` and `1`.
  Season is NULL on 1,126,132 releases; episode NULL on 213,803 series
  releases (merged packs — the episodes inside a pack are unknowable).
- `posts.language` is messy (`Unknown` 68,950; `Hindi` vs `["Hindi"]` vs
  `hindi`; `Hindi + English`; `Hindi, Urdu`; `Original Audio` …).
  `releases.languages` is NULL/empty on 38% of releases.
- Already present in the code (the brief predates them, so they are NOT
  built again): a `language=` substring filter on `/api/v1/posts`;
  `did_you_mean` via `did_you_mean.suggest_correction` — but only when
  the exact search finds NOTHING; the browse rate bucket is already
  60/min (only `/stats` and auth are 10/min); `sort=trending` is already
  documented in code as "most prints and mirrors, not popularity".
- `redact.CORS_ALLOW_ORIGINS` is an empty frozenset: no browser origin
  can call the API. The first-party client is a native Android app
  (no `Origin` header); the API is public and unauthenticated, so a
  wildcard would only let third-party sites spend our budget from
  visitors' browsers. **Decision: keep CORS closed.** If a web client
  ever ships, allow-list exactly its origin — never `*`.
- Adult-flagged rows are hidden per row by `redact.adult_clause`. Two
  named rows are unflagged DATA (`Pushpa Pelega Nahi MoodX` post 94509,
  `Hot Web Series` post 49986, both `is_18_plus=0`): re-flagging them is
  a data migration (`audit_adult_flags.py --apply`, owner-gated), NOT a
  code change, and is out of scope here. The code change that does
  belong here: the works grouping applies the adult rule at WORK level
  (see §2), on corroboration only, so an unflagged twin can no longer
  surface a corroborated flagged work through the new endpoint — while
  a misflagged twin (Salaar post 9388) does not hide the work.

## 1. New endpoints (additive; `/api/v1/posts` behaviour unchanged)

- `GET /api/v1/works` — list/search. Same params as `/api/v1/posts`
  (`q`, `type`, `page`, `limit`, `industry`, `genre`, `language`,
  `quality`, `sort`, `free_only`, `work_ref`) plus `region` (alias for
  `industry`, see §4). Same envelope (`page`, `limit`, `total`,
  `total_pages`, `results`, `fuzzy`, `moods`, `mood_genres`,
  `did_you_mean`) plus `suggestions` only on the empty-miss path (§5).
- `GET /api/v1/works/<id>` — detail. `<id>` is a post id: the minimum
  SERVABLE member post id of the work (stable, numeric, URL-friendly;
  flagged members are never servable). The response is the SAME shape
  as `/api/v1/posts/<id>` (same fields via the same `redact` views: `id`, `clean_title`, `title`, `year`,
  `content_type`, `imdb_rating`, `genres`, `poster_url`, `work_ref`,
  `release_count`, `source_count`, `releases`, `sources`,
  `option_groups`, `season_artwork`) plus work fields:
  `post_ids` (member post ids), `post_count`,
  `episode_guide` (episode lists with gaps, §3), `is_ongoing`,
  `latest_episode_added_at`. The work's `imdb_id` / `tmdb_id` are its
  best-known member's (the representative's when it carries one, else
  the lowest-id member's): only 1 of Salaar's 9 live posts carries
  ids, and it is not the representative — without this the work would
  answer with no ids at all. (Named `episode_guide`, not `seasons`:
  the representative post's own `seasons` column already occupies
  that key in the detail shape.) The grouping key itself (`work_key`) is
  NEVER emitted: it is a PROVENANCE key in `redact.py`, server-side
  only; the work's public identity is its numeric `id`.
- A work's displayed fields come from its REPRESENTATIVE post:
  (has poster, has rating, fewest clean-title tokens, lowest id) —
  the bare title beats its editioned copies, so the work reads
  `Salaar`, not `Salaar - 1 - Ceasefire`. Deterministic; documented.

## 2. Grouping posts into works (read-time, `Fast_Fetch/works.py`)

Tier 1 key (exact): `imdb:<id>` / `tmdb:<id>` when present, else
`family:normalized-title:year-or-ny`, where the normalized title is
`catalog_v2.normalize_title` plus edition-token stripping (quality /
format / audio / source words such as `web-dl`, `multi`, `audios`,
`hindi`, `nf` — dropped only at token position ≥ 1, so `Hindi Medium`
keeps its first word), 4-digit year tokens dropped, the word `part`
dropped before a number (`Salaar Part 1` ≡ `Salaar 1`), `S01`/`E01`
tokens reduced to their number, and `season` dropped before a number.
Family (`movie` vs `series`) never merges across, and the year is the
clamped year (`_NEWEST_YEAR_SQL` rule: outside 1900..next-year = `ny`).

Tier 2 merge (fuzzy, in Python over the tier-1 groups, union-find):
same family + compatible years (equal, one unknown, or |Δ| ≤ 1) AND
(one normalized title is a token-prefix of the other — `salaar` ⊂
`salaar 1 ceasefire` — OR token Jaccard ≥ 0.6). The tier-2
comparison reads the rows' OWN titles, never the key text: an
id-keyed group (`imdb:tt13927994`) carries no title in its key, and
without this it could never fold with its id-less twins (Salaar: 1
of 9 posts carries an id). This is what folds
`Salaar` / `Salaar Part 1 Ceasefire` (2023 vs 2024) / `Salaar Cease
Fire` into one work. Known gap, accepted for v1: `salaar 1 ceasefire`
vs `salaar cease fire` with NO bare-`Salaar` post to hub them do not
merge (tokenisation difference `ceasefire` vs `cease fire`, Jaccard
0.2). A later pass can add spaceless comparison; it must not guess.

Adult rule at work level: the grouping query fetches flagged posts
TOO (no adult clause in the grouping scan), then a group is dropped
whole only when a flagged member's flag is CORROBORATED — the fold's
gate (`fast_fetch.adult_rule_agrees`: the shared rule re-derives the
flag from the row's own texts). A flagged member that does not
corroborate is excluded from the work but does not hide it: Salaar
carries one such twin live (post 9388, "Salaar Part 1 Ceasefire"
2024 — no adult evidence in its title), and a raw MAX would have
hidden the work on its account, the way an un-gated fold hid 407
mainstream works (measured 2026-10-30). A query matching only
flagged posts answers an empty page, indistinguishable from no
match. A flagged member's releases are never served even when the
work survives. (Data baseline 2026-11-12: Salaar is 10 posts —
2023×6, 2024×2, NULL×1 (id 4220); only 2 of 10 carry a rating,
`imdb_rating` is TEXT with no numeric column, so the representative
pick parses it as a float.)

Performance: grouping is a full scan of the filtered post set
(~135k public rows unfiltered) + a Python union-find. The grouped
work list is cached in-process for 120 s keyed by the exact filter
tuple (the catalog changes only on batched merges, so ≤ 2 min stale
is acceptable for a browse list). The 10 s search deadline still
applies; a grouping that trips it answers 503 like a slow search.
`cat_*` tables are deliberately NOT the grouping authority (they
split Salaar 8 ways, §0); episode lists are derived from `releases`
instead. Re-keying `cat_*` onto work keys is a separate migration.

## 3. Season / episode normalisation (`works.py`)

`parse_season` / `parse_episode` accept `1`, `S01`, `S1`, `Season 1`,
`E01`, `1`, `Episode 1` → int; `format_season(n)` → `S01`,
`format_episode(n)` → `E01`. The episode value `Batch` (10,525
releases, data baseline 2026-11-12) — and `complete` / `pack` /
`all` / `full` — parse to None: they name a pack, never an episode
number, so a season carrying one marks its unnamed episodes
`in_pack`. Works responses normalise every season/episode to that
one format (list items and detail `option_groups` scopes keep their
existing raw values — only the new `episode_guide` and work-detail
release rows are normalised, so `/api/v1/posts` output is
byte-identical).

`episode_guide` in work detail: per season, episodes 1..max with status
`available` (a release names the episode), `missing` (no release
names it and no pack covers the season), or `in_pack` (a season pack
release — episode NULL, season set — may contain it; unknowable, so
never claimed as missing). Movies get `episode_guide: []`.
`is_ongoing`: any member post has `content_type = ongoing_season`, or
a raw member title matches `[S..E.. Added]`.
`latest_episode_added_at`: max `releases.created_at` over the work —
a factual timestamp the client can diff across polls to detect a new
episode (there is no snapshot table to diff against, so no invented
"since last snapshot" state; the timestamp IS the signal). None for a
work with no series member — a film has no episodes to add.

## 4. Filters shared by `/posts` and `/works`

- Language buckets (`works.language_buckets` / `works.language_sql`):
  parse `posts.language` (JSON array, comma list, `+`-joined, plain)
  into canonical tokens with abbreviation expansion (`tel`→telugu,
  `tam`→tamil, `mal`→malayalam, `kan`→kannada, `hin`→hindi,
  `eng`→english, `urd`→urdu, `pun`→punjabi, `ben`→bengali,
  `mar`→marathi, `guj`→gujarati, `rus`→russian, `chi`→chinese,
  `kor`→korean, `tur`→turkish, `jap`→japanese, `spa`→spanish,
  `fre`→french, `ara`→arabic). Buckets: `hindi`, `english`, `urdu`,
  `tamil`, `telugu`, `dual` (≥ 2 known languages), `multi` (≥ 3),
  `unknown` (no known language token), plus every other known
  language as its own bucket. A `language=` value that is a bucket
  uses the bucket predicate; any other value falls back to the
  existing substring LIKE, so facet chips (`original audio`, …) and
  old clients keep working. Baseline-verified: the existing filter
  already returns 7 of 9 Salaar rows for `language=hindi` (dropping
  the 2 Unknown-language rows); the bucket predicate keeps that
  behaviour for single languages and adds `dual`/`multi`/`unknown`.
- Region (`industry` gains three keys; `region=` is an alias):
  `chinese` (industry/country/language mention of China/Chinese/
  Mandarin/Cantonese — 1,385 industry + 1,870 country rows live),
  `korean` (Korea/Korean — 1,133 / 1,139 rows),
  `turkish` (Turkey/Turkish — 588 rows across the three columns).
  Facets grow from 5 to 8 industry keys automatically (same
  `INDUSTRY_FILTER_SQL` drives both), and the facet-count-equals-filter
  invariant is preserved by construction.
- `sort=most_copies` is added as an alias for `sort=trending`;
  `/api/v1/trending` gains `basis: "most_copies"` and
  `label: "Most copies"` in its response. There is no play-count
  column, so no view count is invented; the name now says what it is.

## 5. Search fixes (in `api_v1_get_posts` and `api_v1_get_works`)

- Typo with hits (`salar` → salary anime): when the exact search
  returns rows but no page-1 title contains any query token exactly,
  and a correction exists, set `did_you_mean` to the correction. The
  correction EXCLUDES the served titles' own words
  (`did_you_mean.correct_token(..., exclude=...)`): `salar` is one
  edit from the served `salary` too, and offering that back would be
  no correction at all — the next closest word (`salaar`) is the one
  worth surfacing. The exact results are still served — never
  silently swapped — and the check runs only when `total ≤ 500`
  (the correction pass is an extra title scan). A string prefix is
  not a good match (`salar` prefixes `salary` too). `did_you_mean`
  stays `None` when the exact results are a good match.
- Nonsense query (`asdfghjkl` → 0): when a query misses everything
  (no exact, no fuzzy, no correction, no mood), the response gains
  `suggestions`: the 5 newest public posts (cheap posts-only query),
  so the UI can offer something instead of a bare zero.
- Common words (`the` → 43,577): a single-token query that is a
  stopword (`the`, `a`, `an`, `and`, `or`, `of`, `to`, `in`, `on`,
  `for`, `with`, `by`, `at`, `from`) or ≤ 2 letters matches whole
  words only (`= 'the'`, `LIKE 'the %'`, `LIKE '% the'`,
  `LIKE '% the %'`) on title fields — no more `other`/`together`
  junk, no cast-name leakage. Multi-token queries are unchanged.

## 6. Rate limit — verified, NOT raised

Baseline-verified 2026-11-12: browse 60/min, play 30/min, `/stats`
10/min, auth 10/min. The brief's "10/min" was only ever `/stats`;
the "raise the 10/min" task is moot for browsing. **Decision: keep
60/min.** A CGNAT IPv4 carries ~75 users, but no starvation has been
measured, and the token bucket already absorbs bursts. If CGNAT
starvation is ever observed, doubling the browse bucket is the first
step — documented at `BUCKET_LIMITS` in `redact.py` and pinned by
`test_redact.test_documented_budgets`. Play stays 30/min (expensive:
resolve + redirect), `/stats` 10/min, auth 10/min (KDF cost).

## 7. Rebase onto main 88019eccc (2026-11-12, replacement agent)

Base moved while this branch was uncommitted: main is now `88019eccc`
(App redesign + rework). The rebase kept both sides:

- `did_you_mean.correct_token` gained main's evidence weighting
  (`_candidate_rows`: prints + mirrors weigh an exact-but-obscure
  word against a popular near-miss — `avtar` → `avatar`) AND this
  branch's `exclude=` parameter. The two compose: an excluded
  near-miss is skipped in both the exact-word evidence loop and the
  plain near-miss loop.
- `viewer.api_v1_get_posts` gained main's Audit #38/#17 dedupe
  (`_dedupe_search_page`, `_dedupe_page_rows` via the new
  `title_clean` module) AND this branch's facet clauses, poor-match
  correction and suggestions. Two interactions, both fixed in the
  rebase commit and pinned by `test_works_api.py`:
  1. Main's generic correction block now runs on hits too, so it
     pre-empted the poor-match correction (`salar` → `salary`, the
     served word itself). The poor-match block now OVERRIDES the
     generic correction when the served rows match no query token
     (`salar` → `salaar`); when the rows are a good match (`avtar`
     → old `Avtar` rows) `is_poor_match` is False and the generic
     correction stands.
  2. Main's `_dedupe_page_rows` applied to `sort=trending` only, so
     `sort=most_copies` answered the un-deduped page and the two
     sorts diverged. The dedupe now applies to both names — they are
     the same order, so they must answer the same page.
- `test_redact.py` PublicEdgeHttpTests: 7 timeout errors reproduce
  IDENTICALLY on clean base `88019eccc` (36 tests, 7 errors) — the
  documented load flake (AGENTS.md: local HTTP tests time out under
  load), not a regression from this branch.

## 8. Scale + search speed (user quality bars, 2026-11-12)

- **One swap point for search.** Every works search funnels through
  `viewer._works_search_candidate_ids(conn, query)` — a query string
  in, the post ids it names literally out. The search-performance
  benchmark's winner (FTS5, a title index, whatever it recommends)
  lands THERE and nowhere else: the grouping, the filters, the
  envelope and the tests never see which technique produced the ids.
  The posts route keeps its own literal match; the two share the
  whole-word rule (`works.whole_word_title_clause`) but not the
  candidate query, so a works-side swap cannot change `/posts`.
- **100K users, read path.** The grouped works list is cached
  in-process 120 s per exact filter tuple (`_WORKS_LIST_CACHE`, 32
  entries) — grouping is a full scan of the filtered post set plus a
  Python union-find (WINDOW 10, O(G·10)), paid once per cache miss,
  never per page. Counts are page-only (the posts two-step); the
  trending/most-copies order pays one grouped count query per cache
  miss. The 10 s search deadline still applies via the progress
  handler; a grouping that trips it answers 503 like a slow search.
  Browse never resolves a link: works list/detail mint no handles
  and call no resolver — links resolve lazily, on press, through
  the existing `/api/v1/stream` route (the lazy-first rule; only the
  pressed link is resolved, never a page of them). No code here
  trusts `expires_at` — handles carry their own expiry
  (`redact.mint_token`).
- **Unproven at scale, stated plainly.** No FTS5 table exists yet
  (that is the benchmark agent's recommendation to come); the
  grouping scan's wall time on the live 224k-post catalog is
  unmeasured from this branch — the gate deploy must probe
  `/api/v1/works` (unfiltered + `q=salaar`) for latency before
  calling the route fast. The cache makes the second page cheap;
  the first page after a merge is the cost to watch.

## 9. What is NOT in this change

- No change to `/api/v1/posts` response shape or ordering, except the
  three additive, documented behaviours in §5 (`did_you_mean` on poor
  matches, `suggestions` on empty miss, whole-word matching for
  single-token stopwords) and the additive `language` buckets /
  `industry` keys / `sort=most_copies`.
- No `cat_*` re-key migration; no re-flagging of the two named adult
  rows (owner-gated data migration); no live deploy (coordinator's
  call); no nginx change in this branch — the gate deploy MUST add
  `/api/v1/works` and `/api/v1/works/<id>` to the nginx allow-list
  (`^~ /api/` 403s everything not listed).
- No invented view counts, no snapshot table, no new DB writes.
  Python stdlib only; no `requests` import.
