# 2026-11-01 ~08:xx — q3 lane, Phase 3 (#35): the FTS5 table `catalog_api` already names has never been created by anything, and I built it

Lane: **qoder3** (backend). Written on trunk `c2528e1` (`main` == `master`, ls-remote-verified by q1),
branch **`q3-fts5-on-c2528e1`**, worktree `/tmp/q3_premerge`. Dispatch: `[MUSE SUPERVISOR 08:03]` —
"GATE CLOSED on c2528e1 … proceed with #35 / Phase 3 FTS5 work in your worktree only, no merge, no tag,
no restart, no production DB write. VM load is 5.07 now, above the 4.0 gate, so no full Gradle build."
Because my head *is* trunk, these commits sit directly on it: no re-branch debt, and
`git merge-base --is-ancestor c2528e1 HEAD` is the FF check I ran before pushing.

## Status

| | |
|---|---|
| Code changed | `Fast_Fetch/migrate_search_indexes.py` (new STEP 3), `Fast_Fetch/test_migrate_search_indexes.py` (new `WorksFts` class) |
| Tests **run** | **none** — `cpu some avg10 ≈ 99` and load 5.07; the freeze bars every test module, including this one. `py_compile` on both files: OK. The hosted Backend CI run on this sha is the first judge, and the `WorksFts` docstring says so in the file itself. |
| Production read | none. No staging scan, no crawl, no merge, no Gradle, no tag, no restart. |
| Landed | nothing — q1's gate. Pushed to my own branch only. |

## The five measured findings

**(a) The FTS branch in the read layer has never executed anywhere in this repo.**
`catalog_api.py:1132` writes `… FROM cat_works_fts WHERE cat_works_fts MATCH :fts`, and
`:1260`/`:1302` turn that on with `_has_table(conn, "cat_works_fts")`. Grep the whole tree for a
`CREATE` of that name: **nothing**. The only hits outside my new step are `docs/FULL_MASTER_FEATURE_INVENTORY.md:228`
citing the branch as though it were shipped, and `catalog_api.py:39`'s own comment — "*If a
`cat_works_fts` FTS5 table is **ever** added*". So `B-V2-03` is a capability the inventory records as
delivered and the schema has never had, and every test ever written against `search()` ran the LIKE path.

**(b) `posts_fts` — step 2 of this same migration — is read by nobody.** Grepping `posts_fts` outside
`migrate_search_indexes.py` and its tests returns **zero** hits. That is deliberate and already
documented in the module, and it is why step 2 is a pure capability you can approve and roll back
without touching a live path. Step 3 is the opposite: it flips a real code path the moment it exists.
That difference is what the rest of this file is about.

**(c) The two indexes cannot be conflated, because their rowid spaces differ.** `posts_fts` is
`content='posts', content_rowid='posts.id'`; `catalog_api` joins `w.id IN (SELECT rowid …)` where `w`
is `cat_works`. Renaming or reusing step 2's table for step 3 would not error — it would silently join
`cat_works.id` against `posts.id` and answer whichever work happens to share a rowid. Separate table,
separate statement.

**(d) `synopsis` is stored, displayed, and searchable by nothing.** `viewer.py:2860` matches
`clean_title`/`title`/`slug` for `q=`; `media_search.py:168` is LIKE-only; `catalog_api.py:1112`'s
haystack is `radd_hay(title, original_title, genres, aliases)`. `synopsis` appears in no WHERE clause
anywhere and is only echoed to the client (`catalog_api.py:1522`). So the plot text — the one column a
user paraphrases when they have forgotten the title — is currently invisible to search. The index I
built carries it, plus `original_title`, `genres`, `languages`, `country`, `industry`, `work_type`.

**(e) MATCH can only narrow, so an index alone cannot widen recall.** `_run_listing` ANDs the title
haystack (`:1117-1119`) and then adds the MATCH clause as an extra AND (`:1129-1133`). A synopsis-only
query therefore still returns zero rows *with* the index present. Making plot search reachable means
treating the index as an **alternative** matcher — which changes result sets, `total_estimate`, and the
cursor fingerprint. That is a ruling, not a side effect of a migration, so I pinned today's semantics
with a tripwire: `test_the_accelerator_cannot_widen_the_corpus_yet` asserts the index answers 8 rowids
while `catalog_api.search(q=PLOT_WORD)["count"] == 0`, and it is designed to fail loudly the day
someone widens the read layer without deciding to.

## Two spec dimensions have no corpus, so I did not build them

The 5-dimension spec asks for dialogue and cast search. **There is no dialogue text in the ledger** —
only `playback_type='subtitle'` file pointers (`audit_staging.py:100/:158/:207`), recorded as a finding
in #33 rather than invented as a column. **There is no cast or actor column** in `cat_works`
(`catalog_v2.py:146-174`). A migration cannot index a string that was never scraped; shipping a
`dialogue MATCH` would be an index over an empty column that reports success. Those two dimensions are
reported as blocked-on-ingestion, not faked.

## Why step 3 has no triggers, and why that is the safe direction

`posts`' three triggers cost **5,308 µs/row against 412 µs/row without** (measured on the copy, step 2's
comment). `cat_works` is not appended to — it is **bulk-written by `catalog_v2.project()`**, a
150k-row projection, so per-row triggers would add roughly 12 minutes to every projection and fire on
rows that are about to be overwritten anyway. The refresh is instead an explicit
`INSERT INTO cat_works_fts(cat_works_fts) VALUES('rebuild')`, run by `apply` and named in `plan`.
The cost of that choice is drift, and the failure mode of drift is the safe one: MATCH is a narrowing
(finding (e)), so a forgotten rebuild **drops** results and cannot add a row that was not projected —
and it cannot leak a flagged work either, because `_adult_clause("w")` sits in the WHERE over
`cat_works` itself (`:1106`), which `test_a_flagged_work_in_the_index_still_cannot_be_listed` pins with
its `include_adult=True` positive control. `verify` catches the drift and says "run the rebuild".

## The two drift probes, and the two checks that do not work

Both come from step 2 and both apply harder here, because `synopsis` is the long column:

- `SELECT COUNT(*) FROM <fts>` reads the **content table**, not the index. Inserting past a dropped
  trigger left it at 21 while the index held 20. So `verify` counts `cat_works_fts_docsize`.
- `INSERT INTO <fts>(<fts>) VALUES('integrity-check')` returned **no error** on that same mismatched
  database. So `verify` samples a token out of actual `synopsis` rows and looks it up, and joins
  `_docsize.id` against `cat_works.id` for orphans.

## Contradiction I am reporting rather than resolving

The spec said to report a doc/spec contradiction instead of choosing. `docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md`
contradicts repo law and its own schema in six measured ways, so it cannot be the authority for this
work; I built to the code and to `redact`'s adult law instead. Every line below is from that file:

1. `:16` — `sqlite3.connect('catalog.db')`. There is no `catalog.db`; paths come from `config.DB_PATH`
   (and repo law: never hardcode, and never point a dev tool at the live file).
2. `:20-26` — `CREATE VIRTUAL TABLE catalog USING fts5(title, duration, aspect_ratio,
   audio_stream_metadata)`: a table named `catalog` that exists nowhere, with four columns of which
   **only `title` does**, in a different table. `cat_works` has no `duration`, no `aspect_ratio`, no
   `audio_stream_metadata`; the closest real columns are `runtime_minutes` and `max_resolution`, and the
   shipped by-media route already uses `duration_s`/`resolution`.
3. `:46-48` — `AND duration BETWEEN :min_duration AND :max_duration` inside a `MATCH` query: in FTS5
   every column is TEXT, so `BETWEEN 120 AND 150` compares **lexically** ('1500' < '200'). It silently
   returns wrong rows rather than failing.
4. `:67-68` — the response body publishes `'streaming_url'` and `'download_url'`. Repo law forbids a
   public surface emitting a source URL at all: they are opaque handles (`work_ref`, `_art_pair`), and
   nginx allow-lists exact routes precisely so a hoster name never leaves the box.
5. Nowhere in the file is there an adult clause — `is_18_plus` does not appear in it — while every real
   query in this repo carries `_adult_clause`. As written, that handler would list a flagged work.
6. `:41` — `re.sub(r'[^a-zA-Z0-9\s]', '', title)` sanitises for a `MATCH`, and punctuation stripping
   does not touch `AND`/`OR`/`NEAR`/`NOT`, which are alphanumeric **query syntax** in FTS5. The real
   layer never does this: `catalog_api.py:1134` quotes each token itself
   (`" ".join(f'"{token}"*')`) so no user string is ever parsed as an expression.
7. `:163` — the Kotlin example calls `http://localhost:8000/api/v1/search/by-media?title=…`;
   the shipped route (`viewer.py:2990`) is `api_v1_search_by_media(query, duration_s, resolution,
   audio_language, limit, full, base_url)` — different parameter name, different host, and no
   `aspect_ratio`/`audio_stream_metadata` at all.

**What I need from Muse:** a ruling on (i) whether the architecture doc gets rewritten to the code or
retired with a pointer, and (ii) finding (e) — whether the read layer should treat `cat_works_fts` as an
alternative matcher and make plot search reachable, which is the only part of this that changes what a
user can find. I built the index and pinned today's semantics; I did not decide that question by
editing a WHERE clause.

## What a reviewer should check first

`plan --with-works-fts` output, then `apply --with-works-fts` **without** `--execute`, then the
`WorksFts` class in `test_migrate_search_indexes.py`. The build refuses (exit 1, naming
`catalog_v2.project()`) against a database with no `cat_works`, and `rollback --with-works-fts` drops
only the index — safe mid-conversation because the cursor fingerprint is computed *without* the MATCH
clause (`catalog_api.py:1129-1133`), so removing the table degrades to the LIKE path without
invalidating one cursor.
