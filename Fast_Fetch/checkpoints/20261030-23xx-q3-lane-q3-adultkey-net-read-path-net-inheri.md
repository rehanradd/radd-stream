# 2026-10-30 23:2x→ — q3 lane, Q3-ADULTKEY-NET: read-path net inherited, takeover patch reviewed, HELD at load 12.5

Token `Q3-ADULTKEY-NET`. Brief: `/tmp/Q3_ADULTKEY_NET.md` from qoder1, amended mid-session by the
supervisor collision notice (qoder4 holds uncommitted fold-engine work in `/tmp/q4_adultkey`, exported
as `/tmp/q4_adultkey_wip.patch` + `/tmp/q4_test_adult_corroborated_fold.py`). This file is the handoff
artifact for whoever continues, and it is written under a **hard execution hold**: load average hit
12.5 on the 1-vCPU box, so nothing below was run — no python, no sqlite, no test module. Everything
marked *measured* came from the briefs or from another lane; everything marked *not run* is exactly
that.

## Where the branch is

`q3-adultkey-net`, worktree `/tmp/q3_adultkey`, base `origin/master` = `6a441ec`. Never touched
`/opt/radd-stream` (live, 60 dirty files from other lanes) and never touched `/tmp/q4_adultkey` or
`/tmp/q1_adultkey`.

Applied:

- `/tmp/q1_adultkey_wip.patch` — `redact.py` and `fast_fetch.py` hunks **clean** (`git apply
  --exclude=Fast_Fetch/viewer.py`; the viewer hunk was pre-declared stale because viewer moved on
  trunk). That is: `adult_justified_keys(canonical_key PK, evidence, rows_justified, decided_at)`,
  `ensure_adult_key_table` called from `fast_fetch._init_db`, `key_is_adult` (probe → create-and-
  reprobe → **deny** on second failure), `row_is_adult`, `adult_clause(alias, keyed=False)` with the
  uncorrelated `NOT IN (SELECT canonical_key FROM adult_justified_keys)` anti-join, and `art_is_adult`
  / `link_is_adult` consulting the key table.
- **Decision (c) landed, and it is named here on purpose:** `link_is_adult` now returns **True** for an
  unknown or dangling link id. Trunk `024f554` documented `False` and declined to change it; this task
  requires the flip, and it is also what `redact.link_is_adult`'s own docstring and root `AGENTS.md`
  have claimed for weeks. q4's patch contains the *same* flip in the same function, so the two lanes
  agree — mine is a superset (it adds the key consultation), and q4's hunk should be merged as a
  comment, not re-applied.
- The one-line viewer hunk by hand at `fetch_database_payload` (`viewer.py:762`), with a note that the
  panel feed was the row-half only.

Deliverable 4, emitters — converted, each after re-grepping the site rather than trusting the brief's
base-`072158f` line numbers:

| site | what it is | now |
|---|---|---|
| `viewer.py:762` | `/api/data` panel feed | `keyed=True` |
| `viewer.py:2796` | `api_v1_get_posts` — **the leak** | `keyed=True` |
| `viewer.py:3182` | `_ledger_link_breakdown` live link counts | `keyed=True` |
| `viewer.py:3204` | `_counted_stats` posts fallback | `keyed=True` |
| `viewer.py:3208` | `_counted_stats` releases join | `keyed=True` |
| `viewer.py:3200` | `_counted_stats` `cat_works` branch | **left `keyed=False`** — the projection's identity is `work_key`, and `project()` already rolls the flag up with `any()` |
| `media_search.py:168` | `/api/v1/search/by-media` fallback scan | `keyed=True` |
| `viewer.py:891` | `generate_m3u_playlist` per-post bail | `redact.row_is_adult(conn, post)` |
| `viewer.py:2960` | `api_v1_get_post_detail` per-post bail | `redact.row_is_adult(conn, post)` |
| `catalog_api.py:292`, `catalog_v2.py:2214`, `api_v2.py:274` | v2 read layer, alias `w` | **left unkeyed** per the brief |
| `audit_adult_flags.py:313`, `backfill_adult_key.py:69` | `public_total` verification arithmetic | **left unkeyed deliberately**: a fold changes row flags, and `flipped == before - after` only holds against the row-level total. Keying these would make the verification number move for a reason the pass did not write. |

**The single layer every public listing route provably passes through** (the brief asks for it):
`redact.adult_clause`, at every emitter above — there is no second filter. Proved by reading the call
graph, and the census test (deliverable 5g) is what makes that claim enforced rather than asserted.
The v2/app surface reaches the same law through `catalog_v2.project()`'s `any()` roll-up into
`cat_works.is_18_plus`, which is why the `cat_works` sites must stay unkeyed.

## The one open hazard I closed before stopping

`keyed=True` is raw SQL, so it 500s on a ledger without `adult_justified_keys`. Every converted route
in `viewer.py` begins with `_ensure_schema()` — verified at `:612` (panel feed), `:2788` (posts list),
`:2942` (by-media), `:2961` (post detail), and `:3795`/`:3802` *before* `_get_cached_stats(conn)` at
`:3804` — and `_ensure_schema()` calls `fast_fetch.init_db()`, which now runs
`redact.ensure_adult_key_table(conn)`. `row_is_adult`/`key_is_adult` self-heal on their own. So no
public route can reach the anti-join before the table exists. **Not verified by execution** — read off
the file. Residual: any caller outside `viewer.py` that reaches `media_search.search_by_media` with a
connection it built itself would need the same guarantee; I did not enumerate those callers.

## What I reviewed but did NOT apply — q4's fold engine

`/tmp/q4_adultkey_wip.patch` read in full (372 lines) plus its 498-line suite. It is good work and I am
not going to re-implement it. My review findings, in the order I will fix them:

1. **`--undo` honours only one of the two identities `--corroborate` folded across.** The fold groups
   on `canonical_key` *and* `(clean_title, year)`; the undo's "still justified" probe tests
   `canonical_key` siblings only. So a cross-key fold — the `puli-2015` / `puli__2015` shape the suite
   itself celebrates — is silently **re-exposed** by `--undo` while its corroborating adult source is
   still flagged. Their `test_two_siblings_hidden_by_one_fold_do_not_justify_each_other` **pins the
   unsafe direction** (`unflagged: 2, kept: 0`), and it does so while a live flagged source row
   (`boss-src`, post 1) shares the work identity. I disagree with that expectation: the journal
   exclusion is the right termination argument and it survives my change, because a *source* row is
   never journaled (only flipped rows are). Fix: build the "flagged and not journaled" key set and
   work-identity set once in Python, then justify a journaled row from either. That also removes the
   `id NOT IN (…3,490 placeholders…)` per row, which is one 3.5k-parameter statement per journaled
   row on a 1-core box. (Verified locally that this host's SQLite is 3.45.1 with
   `MAX_VARIABLE_NUMBER=250000`, so it is a cost bug, not a limit bug.)
2. **`--corroborate --apply` writes the production ledger with no `--owner-go` and no file preimage.**
   The standing write contract (`audit_adult_flags.py`, and this brief's deliverable 3) requires
   preimage + `fdatasync` + directory fsync + re-read before the first UPDATE, and an owner's words
   for a production write. A fold *hides*, and hiding is what cost 407 mainstream works on 2026-10-29,
   so the gate is not ceremony. The in-database `adult_fold_journal` is a good undo record but it dies
   with the copy of the file it is in. Fix: `--owner-go` (+ `--prod` for the live catalog) and reuse
   `audit_adult_flags.write_preimage`/`default_preimage_dir` rather than forking a third contract.
   This changes two of their CLI tests (`--corroborate --apply` gains `--owner-go`), and adds a refusal
   test.
3. **Their headline number is a claim I have to re-measure before I repeat it**: 10,816 of 15,068
   stored flags not reproducible by `is_adult_title`, and 3,490 rows the naive cross-key fold would
   have hidden. `--audit` is read-only and is the measurement; queued below, not run.
4. Cosmetic: `undo_corroborated_adult_fold` counts a journaled row whose post no longer exists as
   `kept`, which reads as "a flag was kept" when it means "there was nothing to restore". Left alone —
   it is not worth breaking their `out == {"unflagged": …, "kept": …}` equality tests for a label.

## The ONE-TABLE decision (deliverable: choose and say so)

The read path consults **`adult_justified_keys`**, and `adult_fold_journal` stays what its author built
it to be. They are not two copies of one concept; they are the two halves the fold needs:

- `adult_justified_keys` is a **scope**: one row per ledger key, and it is what makes the net
  *load-bearing for rows that do not exist yet*. That is deliverable 2 and the brief's case (f): a new
  unflagged twin inserted under an already-justified key must be hidden with no re-migration, because
  `fast_fetch.inherit_key_adult` only reconciles when the row being written is the flagged one.
- `adult_fold_journal` is a **record**: one row per *flipped post*, and it is what makes `--undo`
  possible at all. A per-post-id table cannot do the scope's job — a row written tomorrow has no
  journal entry, so an anti-join on `post_id` hides exactly what `is_18_plus` already hides and the net
  is decorative. That is the decisive argument, and it is why I am not collapsing the two.

What I *am* collapsing is the evidence scheme, which was the real risk: `adult_justified_keys` will be
populated **only** from q4's `fast_fetch.adult_rule_agrees` + `work_identity` +
`ADULT_FOLD_FIELDS` — the same two identities, the same precision gate, no second rule, and no raw
key-level `MAX(is_18_plus)` anywhere (forbidden; it caused the 407-work false-hide). One grouping, two
outputs: refactor `corroborated_adult_exposures` so a shared private helper feeds both the row list the
fold flips and the key set the read path consults. Their suite indexes the exposure dicts by key and
never asserts an exact shape, so adding `kind`/`identity` fields is additive and safe.

## Remaining plan, in order, for whoever picks this up

1. `git apply /tmp/q4_adultkey_wip.patch` (its `redact.py` hunk will conflict — merge the comment
   only; the fail-closed flip is already in). Copy `/tmp/q4_test_adult_corroborated_fold.py` to
   `Fast_Fetch/test_adult_corroborated_fold.py`.
2. Fix review findings 1 and 2 above; update their two tests, add the refusal and the cross-key-undo
   tests.
3. New `Fast_Fetch/adult_key_net.py`: reads only, `--dry-run` by default; prints justified-key count,
   rows newly hidden, ~20 title samples, and separately the **version-word-only count it refused to
   flip**; idempotent (second run reports 0/0); writes `adult_justified_keys` only under
   `--apply --owner-go` (+ `--prod` for the live catalog) with the preimage contract; opens
   `file:…?mode=ro` otherwise. It is the *only* writer of that table.
4. New `Fast_Fetch/test_adult_key_net.py` covering brief cases (a)–(g), including the load-bearing
   new-unflagged-twin case and the source-census guard with positive controls (a scan that matches
   nothing must fail). Allow-list names, with a reason each: the three v2 sites, the `cat_works` stats
   branch, and the two `public_total` verification sites.
5. Append **two** `🧪` steps to `.github/workflows/backend-ci.yml` (trunk is at **32**):
   `test_adult_corroborated_fold.py` and `test_adult_key_net.py`. Never renumber; `grep -c 'name: 🧪'`
   is the only count to quote.
6. Read-only production scope count — see the queue.
7. Deliverable 7: the dub-collision finding. `canonical_key = generate_canonical_key(clean_title,
   year)` and q4's `work_identity = (clean_title, year)` are the **same** identity, so a dubbed print
   of a film shares an identity with its non-adult twin by construction — themoviebox demonstrably
   files separate works under one title+year. Under q4's precision gate a dub can only be hidden if
   *its own* text reproduces the flag, which is the right answer, but the residual count of
   title+year groups that mix an adult print with a genuinely different work still has to be reported,
   with examples, and I will not widen or narrow the migration to make it disappear.
8. Honest gaps to keep stating: `test_redact.py:243` pins the exact unkeyed clause string, so
   `keyed` defaulting to `False` is not a choice I can reverse; ~11 other-lane suites hand-create a
   `posts` table with no key table; production latency of the keyed clause on `/api/v1/search/by-media`
   is unmeasured (that route was deliberately shaped to `SCAN p … ORDER BY p.id DESC LIMIT ?`), and the
   plan check is queued, not run.

## 🕒 Queued heavy commands (load 12.5 at 23:2x — NOTHING here has run)

One worker at a time, only when `cat /proc/loadavg` 1-min is under 4, always `nice -n 19`, serially:

1. `python3 -S Fast_Fetch/test_redact.py` — expected ~18 s here (measured 17.57 s on this box earlier
   tonight at load 1.3–1.5, 61 tests). This is the suite that has opinions about the `link_is_adult`
   flip and about `test_redact.py:243`'s pinned clause string.
2. `python3 -S Fast_Fetch/test_database.py` — ~25 s (measured 25.26 s, 133 tests, load 1.4).
3. `python3 -S Fast_Fetch/test_adult_corroborated_fold.py` — **never run anywhere by anyone**; q4's
   author was in a refusal loop before finishing, so its 44 cases are unexecuted. Expected a few
   seconds offline; two of them will fail until findings 1 and 2 are fixed, and I expect to change
   their expectations rather than the rule they encode.
4. `nice -n 19 python3 -S Fast_Fetch/backfill_adult_key.py /home/ubuntu/radd-stream-data/merged_catalog_20261025.db --audit`
   — **the number I must re-measure before repeating it** (10,816 / 15,068). Read-only (`mode=ro`).
   Cost estimate: no index on `is_18_plus`, so it is one full ledger pass; the same box measured
   `COUNT(*) FROM posts WHERE is_18_plus = 1` at **26.46 s** against 0.91 s for the bare `COUNT(*)` on
   the 6.4 GB file, and the sibling pass `corroborated_adult_exposures` measured **16.3 s** for
   150,799 rows including the regex. So budget ≈ 30–45 s wall, one statement, one pass, only at load
   under 4.
5. `EXPLAIN QUERY PLAN` for the keyed by-media statement, then one bounded query at `LIMIT 20` —
   read-only, cheap, but it is a production query and so it is queued, not run.

## Handoff line

Nothing here is merged, nothing is deployed, the live tree was never written, and `adult_justified_keys`
is created **empty** by `_init_db`, which means this branch as it stands behaves exactly like trunk on
every route: the net exists, the emitters consult it, and nobody has populated it yet. That is the
intended interim state — the population step is an owner-gated production write, and the production
apply stays behind `--owner-go`.
