# 2026-11-01 08:5x — q2 lane `[Q2-CENSUS-COMMAND]`: #37 stops being a table and becomes a command, and the first thing the command does is fail my own plan

**Lane:** q2 (`/tmp/q2_admin_auth`). **Branch:** `q2-census-pricing`, on top of `b4d20fa` (the corrected
pricing pass, hosted-green at run 41269611861: 47 steps, 42 `🧪`, none non-green).
**Ruled on:** the supervisor's 08:38 — *"do NOT create the `is_18_plus` index (it would re-baseline the
C2/C4 guards)"*. That ruling is now written into the tool as `FORBIDDEN` + the size+mtime check, not
just into this prose, because prose is what let the last 25 vaults drift.

---

## 1. The defect, found by writing down the plan as data

The 08xx pass priced **19** vaults. Its tier table named **18**. `rogmovies.db` appeared in §2's pricing
table (157,319,168 B, 1,509 ms of schema — the slowest schema pass of the 19) and in no tier row.

What saved the published costs from being wrong is a coincidence worth naming: whoever summed the tier
bytes (me, an hour earlier) had already put rogmovies' bytes inside tier C's `3.42 G`, so
`A + B + C = 4,605,050,880 B` still equaled the corpus, and the missing name was invisible to any
reader who checked the totals. The membership line and the cost line disagreed, and nothing in the tree
could tell.

So the correction is one word in the C row and **no number in that file changes** — I am not "fixing" a
cost figure that was right, and the earlier 885 M → 884 M correction I made stands. The erratum sits on
the tier table itself (`20261101-08xx-...-vault-pricing-no-cheap-count-and-the-plan-that-follows.md`
§4) with this explanation, and `test_adult_vault_census.py` recomputes it on every push:

| published figure | what the test now derives from `PRICED` |
|---|---|
| tier A / B / C bytes | 300,912,640 / 883,949,568 / 3,420,188,672 |
| corpus | 4,605,050,880 B = the tiers summed exactly once |
| A / B / C CPU-minutes | 4.5→5, 25.1→25 · 13.3→13, 73.7→74 · 51.3→51, 285.0→285 |
| cumulative A+B / all | 18–99 / 69–384 |
| `world4ufree` + `9xmovies` | 1,388,961,792 B = 30.2% of the census |
| the two generational pairs | 561,262,592 B = 12.2% — counted once, not twice |

Every range reproduces from `bytes × (0.9, 5.0) s/MB`, the measured spread. That is the whole point: a
tier edited without the doc, a size typo, or a 20th vault added to the data dir without a tier now
breaks a step instead of quietly making the plan wrong.

**And the test caught a second one before it shipped — mine, in this very file.** Typing `PRICED` from
the 08xx table I put `ssrmovies.db` (284,966,912 B) in tier **B**, because it sorted next to
`toonworld4all` and I grouped by size instead of copying the published membership. Tier B would have
become 1,168,916,480 B and the corpus check would still have passed — the same blind spot as the
rogmovies defect, one layer down. Caught it by running `--list`, which printed the tier rows and made
the disagreement visible; `test_tier_byte_totals_are_the_published_ones` would have caught it in CI at
the cost of one red step. `ssrmovies` is now C, and the three tier name lists in the code are
set-identical to the three in the table (A 4, B 6, C 8 published + rogmovies = 19).

Two lessons, both cheap and both already written: **a size sort is not a tier**, and a plan that lives
in prose will be re-typed wrong by whoever trusts it. The `--list` output above is the first thing the
next lane should read rather than the table.

## 2. The command

`Fast_Fetch/adult_vault_census.py` (new, stdlib only). `--list` prints the plan and opens nothing — a
window can be *spent* counting, not re-deciding the order, which is what happened three times to this
task already.

    python3 -S Fast_Fetch/adult_vault_census.py --list
    python3 -S Fast_Fetch/adult_vault_census.py --tier A --budget 1800     # 4 sites, one admitted window
    python3 -S Fast_Fetch/adult_vault_census.py --tier ABC --budget 21600  # the whole remainder

Per vault it reports `rows`, `flagged`, `keys_both`, `rows_on_exposed_keys`,
`flagged_rows_on_exposed_keys`, seconds, and `size_delta_vs_pricing` — the last because a staging vault
is written by scrapers between pricing and census, and the number that decided the projected cost was
the size. The delta is *reported*, not refused: staleness is the operator's call, not the tool's guess.

Four properties, each with a test behind it rather than a promise in front of it:

* **`mode=ro` at the connection level.** `test_the_connection_itself_refuses_an_update` asserts
  `sqlite3.OperationalError` on an `UPDATE` through `open_readonly`, so the freeze's "no production DB
  write" is enforced by SQLite rather than by my intentions.
* **It re-stats and byte-hashes its own input.** `assert_untouched` fails the run if the vault's
  `(st_size, st_mtime_ns)` moved while it was counted, or if a `-wal`/`-shm`/`-journal` appeared beside
  it — the second is the tell that another process holds the file writable, which is exactly the
  situation q3's C2 guard is built to notice. A read-only open cannot create those files, so their
  appearance means the census is not the only writer, and the census stops.
* **A budget it cannot overrun quietly.** If the remaining budget cannot cover the *cheapest* thing
  left, the walk stops, names every uncounted vault as `over budget`, and returns `complete: false`.
  `test_a_budget_that_cannot_cover_the_first_vault_reports_incomplete` pins that an empty run never
  reads as a finished one — the failure mode where a partial census gets quoted as "the census found
  0 collisions" is how an invariant looks satisfied.
* **Named refusals.** `merged_catalog_20261025.db`, `fast_fetch.db`, `user_state.db`, `resolvers.db`
  are not census targets, a mistyped `--only` raises instead of censusing nothing, and a plan that
  matches no tier raises rather than claiming completeness.

The collision rules are **inherited, not invented**: `keys_both` excludes `NULL`, `''` and `unknown`
(the shared bucket every titleless payload lands in, per `audit_adult_flags.py`) and reads a `NULL`
flag as unflagged through `COALESCE(flag,0)`, the way `audit_adult_flags.py` and
`test_adult_twin_probe.py` already read it. A key carrying only flagged rows is correctly hidden and is
not an exposure; that distinction is asserted, because conflating the two is how 455 mainstream works
got hidden once already.

## 3. What I did not run, and why the branch is still worth gating

`test_adult_vault_census.py` is registered in `backend-ci.yml` **without a local verdict** — the same
exception q5 recorded for `test_config_data_dir.py`. The supervisor refroze local suites at load1 5.05
and 08:38 said "hosted CI only"; the box at the start of this segment read load 5.05 / 4.73 / 4.56 with
`cpu some avg10=99.50`, so *nothing* ran locally except `ast.parse` on both new files and the static doc
verifier. This run is the suite's first execution.

> **Cost of what did run:** `--list` twice and the arithmetic check — wall 2.157 s /
user **0.042 s**, `nice -n 19`, one process, no `posts` table read and no path opened (the plan is
`dict` arithmetic, and `test_the_list_command_needs_no_directory_at_all` proves it by running it against
a directory that does not exist). Plus `ast.parse` on both new files and the markdown-only doc mirror.
Nothing else was executed locally.

It also imports no `config`: `config.py` asks a directory for `Path.exists()`, `exists()` re-raises
EACCES, and a worker that cannot stat `/home/ubuntu` ends a step before its first assertion (q5 measured
it at `eb4c0ee`). The census resolves `config.DATA_DIR` inside `main()` only, so the plan is testable on
a machine that cannot see the data dir at all — which is the same property that makes `--list` free to
run in a LIGHT window.

## 4. Census result: none. Stated before anyone reads the table above as one.

`flagged` and `keys_both` for the last 19 vaults are **still unknown**. This file produced the
instrument, not the measurement. #37 stays pending and needs an admitted HEAVY window: tier A is 5–25
CPU-minutes, tier C alone is 51–285.

And the honest note on the instrument: nothing here has been executed against a real vault. The queries
are the ones `EXPLAIN QUERY PLAN` described in the 08xx pass, and the fixtures are synthetic. The first
time the SQL runs against `9xmovies.db` is the census itself, in a window, with a budget. If it fails
there, that is the tool's first real test — not a reason to have trusted its numbers already.

## 5. Do not re-derive

* The tier order and its costs: §4 of the 08xx pass + `PRICED`. Do not re-price to "check" it; the test
  recomputes it on every push.
* Whether an index helps: it does not, and creating one on a merge input is barred by the supervisor's
  08:38 ruling. `FORBIDDEN` encodes the target half of that; the size+mtime check encodes the
  consequence half.
* Which vaults are already counted: 25 in the 05xx pass (`COUNTED` there), 19 here, 4 excluded —
  `PRICED` + `FORBIDDEN` is the whole ledger, and `unpriced_on_disk` reports anything new.
* `keys_both` semantics: `test_adult_twin_probe.py` and `audit_adult_flags.py` own them; this suite only
  re-pins them for the staging vaults.
* `q2-admin-auth-c2528e1@f294bee` is with qoder1 for gating. Re-measured this segment: still
  `f294bee32ccc82806a91c21f4a46d32e3a77a49a`, untouched. Do not re-push or re-gate it.
