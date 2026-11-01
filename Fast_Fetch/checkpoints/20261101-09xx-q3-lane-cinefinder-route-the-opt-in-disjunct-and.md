# 2026-11-01 09:xx — q3 backend lane `[Q3-CINEFINDER-ROUTE]`: the plot matcher is opt-in, inert, and cannot list a flagged work

**Branch:** `q3-cinefinder-route-on-c2528e1`, base `c2528e1` (q1's instruction: "Base is c2528e1.
Re-branch anything you push from there."). Worktree `/tmp/q3_route`. **Nothing landed**; the gate is
HELD by `[MUSE SUPERVISOR 09:02]` because `qoder1`'s write credential is dead — so no push to
`main`/`master`, no credential retry, no gating by this lane, no merge (#34 frozen), no tag, no
restart, no production read or write.

**Load the whole time:** `cpu some avg10 99.06`, load 1-min 4.49 at 09:22. Light-only work: git,
edits, `py_compile`, docs, and one three-row in-memory probe. **No test module was executed on this
box**, so the hosted Backend CI run on the pushed sha is the first judge of every claim below.

## The three rulings received, and what each one cost in scope

| Ruling | Verbatim | What it decided in code |
|---|---|---|
| (1) route shape | "extend the already-allow-listed `/api/v1/search/by-media`; NO new route (avoids an nginx 403 until an owner edits the edge)" | No new endpoint, so no nginx change, so nothing to ask the owner for. `plot` is a query parameter on a route that is already public. |
| (2) trigger-cost measurement | "on a COPY only, and only when the supervisor announces the freeze/load lift — not now, not on production" | `posts_text_fts` is **not created**. `migrate_search_indexes.py` gained no step 4 here; its DDL lives as a spec (§3b) with its gate (§5). |
| (3) MATCH as opt-in | "MATCH may become an OPT-IN alternative matcher only, adult clause preserved, default LIKE semantics unchanged" | `plot` defaults off; off, the candidate statement is the statement `media_search.py` has always sent, character for character. |
| docs contradiction report | "recorded, not resolved now — do not rewrite the architecture doc to force a fit" | The 7-way report stays in the Phase 3 index checkpoint; `docs/SPEC_CLIP_SEARCH_SCHEMA.md` states what the code does and names the architecture doc as *not* the source of record rather than editing it. |

## What shipped on the branch

- `docs/SPEC_CLIP_SEARCH_SCHEMA.md` (new) — q1 item 4. The corpus table, the no-dialogue finding as
  evidence, both index schemas (shipped `cat_works_fts` vs proposed `posts_text_fts`), the route
  contract, the ranking rule, and the gate step 4 must pass.
- `Fast_Fetch/media_search.py` — `PLOT_INDEX_TABLE`, three `MATCHER_*` constants,
  `PLOT_UNAVAILABLE_HINT`, `_has_plot_index()`, `_fts_phrase()`, `_candidates(..., plot=False)` now
  returning `(rows, tier, matcher)`, `search_by_media(..., plot=False)` returning `matcher`,
  `query.plot` and a `hint` that appears only on `plot_unavailable`.
- `Fast_Fetch/viewer.py` — `plot` parsed as `("1", "true")` on the by-media route, mirroring the
  `ladder` idiom at `:3941`, threaded through `api_v1_search_by_media`; the documented route line
  gained `&plot=1`.
- `Fast_Fetch/test_media_search.py` — `PlotOptIn`, six tests.

Production behaviour is **unchanged**, and not because the code is careful: the index this disjunct
reads does not exist on any database, so `_has_plot_index` is False everywhere and `plot=1` answers
`plot_unavailable`. The capability is inert until the migration that is gated by an unmade
measurement runs.

## The defect I wrote and then found in my own diff

First version appended `" OR p.id IN (SELECT rowid FROM …)"` to a statement whose parenthesis had
*already closed*. SQLite binds `AND` tighter than `OR`, so that reads as
`(adult AND (title LIKE… OR title LIKE…)) OR plot…` — a flagged work's **synopsis would list on the
public route**. This is not a style preference; it is the adult law in root `AGENTS.md` ("no public
surface may list *or play* a flagged row") broken by string concatenation. Fixed by assembling all
three candidate tests inside one parenthesis with `redact.adult_clause('p')` ANDed outside it, and
pinned by `test_the_plot_disjunct_cannot_escape_the_adult_clause`, which fails by **finding a row**
and carries a positive control asserting both rowids are in the raw index — a scan that matches
nothing also hides everything, and such a test passes on a broken feature.

Second defect, same class: I converted the candidate statement to named parameters (`:q`,
`:window`). `test_media_search.py`'s `_Spy.execute` records `tuple(params)` and `_plan()` re-executes
`EXPLAIN QUERY PLAN` with it, so named parameters break the existing suite in a way unrelated to
this feature. Reverted to positional `?`, which also restored the default statement byte-for-byte.

Also corrected after checking instead of remembering: `(SELECT rowid …) = p.id` is a scalar
comparison and wrong for a multi-row subquery → `p.id IN (SELECT rowid …)`; and my claim that an
empty FTS phrase is a syntax error was **wrong** — measured below.

## Measured on this box — sqlite3 3.45.1, one in-memory external-content index, three rows

`MATCH 'AND marigold'` → `fts5: syntax error near "AND"`.
`MATCH '"AND marigold"'` → no rows, no error.
`MATCH '"marigold"'` → the two seeded rows.
`MATCH '"mari"*'` → the same rows (`prefix='2 3'` serving a token prefix).
`MATCH '""'` → **no rows, no error.**

That last line is why `_fts_phrase` returns `None` rather than `'""'`: an empty phrase is not an FTS
error, so a silently-empty question would answer like "no such plot" while claiming a matcher ran.
The quoting rule matters because the architecture doc's sanitizer
(`re.sub(r'[^a-zA-Z0-9\s]', '', title)`) strips punctuation and leaves `AND`/`OR`/`NOT`/`NEAR` —
which are alphanumeric.

Cost accounting the existing suite pins: the default path stays at **5 statements**
(`test_the_number_of_statements_does_not_grow_with_the_request`), the opt-in at **6** (one
`sqlite_master` read by name). No join appears on either path.

## What this branch does NOT claim

1. **The plan is unmeasured.** Whether SQLite keeps the `p.id DESC` rowid walk with a third
   disjunct inside the WHERE is unknown; an `OR` whose terms cannot all be index-satisfied can push
   the planner onto a sort, and taking `EXPLAIN QUERY PLAN` requires running the suite, which the
   freeze bars. `test_the_opt_in_buys_one_statement_and_no_join` asserts the *structural* half (one
   scan, no join, `LIMIT ?` still present, six statements) and says in its own docstring which half
   it cannot assert. First task at the lift, §5.
2. **None of the new tests has been executed.** Two were written against a defect I found by reading
   my own diff; the rest are unjudged by anything except the hosted run.
3. **No dialogue corpus exists.** §1's verdict, stated plainly as the brief demanded: the clip-search
   feature is **buildable today for title, plot and genre, and not buildable for dialogue**. The
   ledger's `download_sources.playback_type='subtitle'` rows are *file pointers*
   (`fast_fetch.py:999`, value set `:3606-3620`, `audit_staging.py:100/:157-159/:207/:230`), not
   text; no parser in this repo has ever captured a line of dialogue, and no cast/actor column
   exists in any table. Shipping dialogue search on this ledger would return an empty list for every
   query and report success. My recommendation, as an owner decision and not as code: **scope to
   title + plot + genre now**, keep subtitle ingestion as a named backlog item with its own storage
   and adult-flag questions.

## Blocked, one line each

- **Landing** — gate HELD, `qoder1`'s write credential dead; owner-only fix. Nothing pushed to
  `main`/`master`.
- **Step-4 trigger-cost measurement** — barred by ruling (2) until the supervisor announces the
  freeze/load lift.
- **CI verdict for this sha** — my own credential is blocked (`curl (55) Send failure: Broken pipe`
  on the Actions API); `qoder1` reads CI.
- **Phase 1 item #8's measured estimate** and the **adult-twin count** — both need a production read,
  which is barred.
