# SPEC: clip-search schema — what FTS5 can be built on, and what has no corpus behind it

Status: **design, as dispatched** (`DESI CINE-FINDER`, qoder3's half). Code that follows this file is
`Fast_Fetch/media_search.py` (opt-in matcher), `Fast_Fetch/viewer.py` (`/api/v1/search/by-media`) and
`Fast_Fetch/migrate_search_indexes.py` (step 3). Written at trunk `c2528e1`, branch
`q3-cinefinder-route-on-c2528e1`. Supervisor rulings this file implements, verbatim from
`[MUSE SUPERVISOR 09:02]`: route shape = *extend the already-allow-listed `/api/v1/search/by-media`,
NO new route*; step-4 trigger-cost measurement = *on a COPY only, and only when the freeze/load lift is
announced*; `MATCH` = *an OPT-IN alternative matcher only, adult clause preserved, default LIKE
semantics unchanged*.

`docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` is **not** the source of record for anything here. It was
reported as contradicting repo law and this schema in seven measured ways and the ruling was "recorded,
not resolved now — do not rewrite the architecture doc to force a fit". Where that doc and this one
disagree, this one states what the code does.

## 1. The question, and the honest answer to it

The feature asks for search by *clip frames, screenshot, plot text, actor name and genre in one request*.
Three of those five have a corpus in this database. Two do not, and no schema change can fix that:

| Dimension | Data behind it today | Where |
|---|---|---|
| Title / on-screen text → catalog title | **yes** | `posts.title`, `posts.clean_title` (`fast_fetch.py:952-953`), `cat_works.title`, `original_title` |
| Plot text | **yes** | `posts.synopsis` (`fast_fetch.py:961`), `cat_works.synopsis` (`catalog_v2.py:155`) |
| Genre / facet | **yes** | `posts.genres`, `cat_works.genres`, `languages`, `country`, `industry`, `work_type` |
| **Dialogue / subtitle line** | **NO** | see §2 — the ledger holds file pointers, not text |
| **Actor / cast name** | **NO** | no cast or actor column exists in any table in `Fast_Fetch` (measured by grep across the DDL of `fast_fetch.py:948-1016` and `catalog_v2.py:146-174`) |

**Verdict, stated plainly because the spec asked for it:** the clip-search feature is **buildable today
for title, plot and genre, and not buildable for dialogue** — and the sentence in the brief, *"dialogue
text goes to SQLite FTS5 plot/subtitle search"*, has **no data behind the word "subtitle"**. It is not a
matter of adding a column or running a migration: the text was never captured by any parser in this repo.
Selling a dialogue search on this ledger would return an empty list for every query and report success,
which is the worst shape this feature can ship in. The two paths from here are both owner decisions, not
mine: **(a)** ingest subtitle text (a scraper-side change, per site, with its own storage cost and its own
adult-flag question), or **(b)** scope the feature to title + plot + genre and let the on-device Google
Lens bridge the spec already names stay the fallback for "what show is this line from". I recommend **(b)
now, (a) as a named backlog item**: (b) ships something true, and (a) is a content-acquisition decision
about a corpus nobody has estimated.

## 2. The finding, as evidence rather than as a claim

The only thing in the ledger with the word "subtitle" in it is a **row classification on a source link**:

- `download_sources.playback_type TEXT DEFAULT 'url'` (`fast_fetch.py:999`), whose value set is written at
  `fast_fetch.py:3606-3620` — `iframe|hls|mp4|video|direct`, plus subtitle file pointers.
- `Fast_Fetch/audit_staging.py:100` counts them (`subtitle_source_rows`), `:157-159` groups
  `playback_type` and reads `report["playback_types"].get("subtitle", 0)`, `:207`/`:230` census
  `posts_with_subtitles`, and `:155-162` says out loud that *"sources has no playback_type; subtitle
  coverage is unmeasurable"* when the column is absent.

So the audit tool measures **how many posts point at a subtitle file**. It is the closest thing in the
repo to subtitle coverage, and it is a pointer count. Grepping the whole of `Fast_Fetch` for a transcript,
`.srt`/`.ass` body, or any dialogue-text column returns nothing media-related: the only `transcript` hits
are `export_chat.py` and `auto_chat_sync.py`, which read *this agent's* chat logs.

**A file pointer is not a corpus.** An FTS index over a URL string would match the *filename*
(`Movie.2024.1080p…eng.srt`) — which is title and year and resolution, already searchable — and would
silently rank a work highly because its subtitle file is named after it. That is a fake capability, so it
is not built.

## 3. Schema — the two indexes, and why they are not one

Rowid spaces differ, so a table cannot serve both layers. `content_rowid` names which space the rowids
are in; reusing one index for the other id space would join silently and answer wrong.

### 3a. `cat_works_fts` — v2 layer, **shipped as step 3**, inert until a ruling changes the read layer

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS cat_works_fts USING fts5(
    title, original_title, synopsis, genres, languages, country, industry, work_type,
    content='cat_works', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2', prefix='2 3');
```

`catalog_api.py:1132` has queried this name since it was written and **nothing ever created it**, so
`_has_table` (`:1260`, `:1302`) was always False and v2 search always ran the LIKE path it documents as
the fallback. Step 3 (`migrate_search_indexes.py`, `--with-works-fts`) builds it. No triggers: `cat_works`
is bulk-written by `catalog_v2.project()`, and the refresh is an explicit
`INSERT INTO cat_works_fts(cat_works_fts) VALUES('rebuild')`. `prefix='2 3'` exists because the read layer
asks for `"tok"*` per token (`catalog_api.py:1134`).

### 3b. `posts_text_fts` — v1 layer, **specified here and NOT built**

A v1 route answers from `posts`, and every v1 projection helper (`_art_pair`, `_work_ref`,
`_subtitled_posts`) takes a post row. So the route's index is on `posts`, not on the projection:

```sql
-- PROPOSED. Not applied by any script; see the measurement gate in §5.
CREATE VIRTUAL TABLE IF NOT EXISTS posts_text_fts USING fts5(
    clean_title, title, synopsis, genres,
    content='posts', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2', prefix='2 3');
INSERT INTO posts_text_fts(posts_text_fts) VALUES('rebuild');
```

The name is the one `media_search.py` looks for (`PLOT_INDEX_TABLE`). When the table is absent — which is
everywhere, today — the opt-in says so and the old path runs. Naming the table before building it is
deliberate: the *consumer* is shipped and inert, the *write path* is not shipped at all.

## 4. The route, per ruling (1): one existing endpoint, opt-in, additive

`GET /api/v1/search/by-media?q=&duration_s=&resolution=&language=&limit=&plot=` — `plot` is new,
defaults **off**, and off means *the SQL text is today's SQL text, character for character*. With
`plot=1`:

```sql
WHERE {redact.adult_clause('p')}
  AND ( p.clean_title LIKE ? ESCAPE '\' OR p.title LIKE ? ESCAPE '\'
        OR p.id IN (SELECT rowid FROM posts_text_fts WHERE posts_text_fts MATCH ?) )
ORDER BY p.id DESC LIMIT ?
```

Three properties, each of which is a test and not a sentence:

1. **The adult clause is outside the disjunction.** Indexing a flagged row's synopsis cannot list it,
   because `redact.adult_clause('p')` (`redact.py:1077`) is ANDed over `posts` itself. An FTS index can
   only ever *add candidates the WHERE already permits*; it is not the safety layer and is not trusted as
   one. Tested with a positive control (`include`-style), because a scan that matches nothing also hides
   everything.
2. **No user text is ever parsed as query syntax.** The MATCH argument is built by us as one
   quoted phrase by `_fts_phrase` (`media_search.py`), which folds a double quote to a space, so
   `AND`, `OR`, `NEAR`, `NOT` arrive as text. This is the specific flaw reported in the
   architecture doc (its `re.sub(r'[^a-zA-Z0-9\s]', '', title)` strips punctuation and leaves the
   operators, which are alphanumeric). `catalog_api.py:1134` already does the quoting-to-a-prefix
   per token; this module quotes the whole phrase because a clip query is a phrase, not a boolean
   expression. Measured on this box with sqlite3 3.45.1 against a three-row external-content
   index, because the claim is cheap to check and expensive to get wrong:

   | MATCH argument | Result |
   |---|---|
   | `'AND marigold'` | `fts5: syntax error near "AND"` — an unquoted operator is not data |
   | `'"AND marigold"'` | no rows, no error — the phrase is parsed as three tokens |
   | `'"marigold"'` | the two seeded rows, and only them |
   | `'"mari"*'` | the same rows — the `prefix='2 3'` index serves a token prefix |
   | `'""'` | no rows, no error |

   The last row is why an empty phrase is rejected before the statement is built rather than
   after: an empty question is not a match, and an answer must not claim a matcher that never
   ran. `_fts_phrase` returns `None` for it and `matcher` stays `title_like`.
3. **The work is still one bounded statement, and that is all this section claims.** The
   candidate query remains a single `SELECT … FROM posts p … ORDER BY p.id DESC LIMIT window`
   with no join anywhere near it — the shape that replaced the 45-second `q=love`
   (`media_search.py:23-44`). What is *not* known is whether SQLite keeps the rowid-reverse
   walk once a third disjunct sits in the WHERE: an `OR` whose terms cannot all be
   index-satisfied can push the planner onto a sort, and no `EXPLAIN QUERY PLAN` has been taken
   with the disjunct present, because the freeze bars running the suite that would take it. §5
   carries that as the first task at the lift, and if the plan comes back with a
   `USE TEMP B-TREE`, the disjunct ships as a second bounded statement unioned in Python instead
   of being folded into this one. `test_the_opt_in_buys_one_statement_and_no_join` asserts the
   structural half — one scan, no join, `LIMIT` still present, six statements — and names the
   half it cannot assert in its own docstring.

**The response contract for q4.** One additive key, `matcher`, carrying `title_like` /
`title_like+plot_fts` / `plot_unavailable`; `query.plot` echoes what was asked; and a `hint`
string appears *only* on the `plot_unavailable` answer. `title_like` is the only value a
non-migrated catalog can produce and receiving it is not an error. A client must be able to tell
"the plot search found nothing" from "the plot search did not run": those need different words on
a screen and only one of them is a fact about the film. Both fields are optional on the wire —
absence means the request never reached a candidate scan (no title, or a title under
`MIN_QUERY_CHARS`), and those two answers are exactly what they are today.

## 5. Ranking, and the gate that step 4 must pass before it ships

**Ranking** stays in Python over the capped window, as it is today: title strength (2 exact / 1 prefix /
0 contains), then evidence agreement (`matched − mismatched`, the three-way honesty in
`media_search.py:10-15`), then print count, then `id DESC` as the total order. A plot-only hit therefore
ranks at title-strength 0 and cannot outrank a title match — which is the behaviour a viewer expects from
"found it by what happens in it" and the reason `bm25()` is *not* used on this route. `bm25()` belongs to
the v2 layer if `_run_listing` is ever widened, where the corpus is works rather than prints. That choice
is a user-visible ranking decision and is listed as a ruling, not made here.

**Step 4's gate.** `posts` is written incrementally by every scrape, so a `posts` index needs triggers to
stay in step — and step 2 measured that tax at **5,308 µs/row against 412 µs/row without** (`posts_fts`,
two short title columns). `synopsis` is the long column, so §3b's table costs *more* than a number already
considered large, charged to the ingest path. Ruling (2) is therefore enforced in code review as well as
in prose: **step 4 does not ship until the trigger cost is measured on a copy after the supervisor
announces the lift**, and the measured figure goes into `migrate_search_indexes.py` next to step 2's, not
into a comment here. Until then the route's `plot=1` answers `plot_unavailable`, which is a true sentence
about the database rather than a 500 and rather than an unindexed `OR synopsis LIKE '%…%'` scan that would
be a new way to take the box down.

**Coverage of the corpus that does exist is also unmeasured** and deliberately so: `COUNT(*) … WHERE
synopsis IS NOT NULL` over `posts` is a whole-table read, forbidden under the hold and by the merge freeze
(#34). At the lift, the number to take on a copy is synopsis coverage by site — a plot search over 150 799
posts whose synopsis column is 20 % filled answers differently from one that is 90 % filled, and the app's
copy should not promise plot search before that is known.

**In order, at the lift, all of it on a copy:** (1) `EXPLAIN QUERY PLAN` for the three-disjunct candidate
statement — the plan question §4 could not answer; (2) synopsis coverage by site; (3) the
`posts_text_fts` trigger cost against step 2's 5,308 µs/row figure; (4) then, and only then, a step 4 in
`migrate_search_indexes.py` that builds §3b with whatever sync choice (1)–(3) support.
