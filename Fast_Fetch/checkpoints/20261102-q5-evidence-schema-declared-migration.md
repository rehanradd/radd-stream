# 2026-11-02 — q5 lane `[Q5-EVIDENCE-SCHEMA]`: the missing evidence columns become a declared, additive migration — `53396df`, and the push gate is still shut

**Supervisor order (this task):** "Implement ONLY gap 4 from `/tmp/q5-probe-evidence-spec.md` — the
missing evidence columns / `ensure_schema` fix — in your own new branch
`q5-fix-probe-evidence-20261102`, fresh worktree `/tmp/q5_probe_fix` off main `846fb76`. Additive
migration only, offline tests only, no live or production DB write, no play-route edit, no VM
Gradle/APK build (hosted GitHub CI only). Do not touch qoder3 art-route, qoder9 play
stale-redirect, or any other lane work. Report back: branch sha + CI run id + what the migration
adds."

## What was wrong (the measured fact, not the theory)

`link_state.LEDGER_COLUMNS` owns six columns — `checked_at, probe_error, protocol, latency_ms,
speed_mbps, cors_open` (`link_state.py:141-148`). The live ledger carries **none of them** (19
columns, read-only `PRAGMA table_info`, 2026-11-02), so `ensure_schema()` has never run there.
The module absorbed that silently rather than reporting it: `_available_evidence()` builds its
column list from whatever the table happens to carry, and `_pending_where()` then counts a legacy
`last_checked_at` as a verdict. Net effect on the live box: a sweep writes only the legacy fields,
treats already-touched rows as measured, and `status_summary` still prints a coverage number — so
"installed and swept" and "never installed" are indistinguishable from the outside. That is the
silent-degradation defect the spec calls gap 4, and it is the reason gaps 1/3/2 (expiry, cached
answers, the two resumability fields) cannot be closed: their columns do not exist yet.

## What this change adds (`Fast_Fetch/link_state.py`, +84 lines, 0 deletions)

Purely additive — no existing line edited, no existing behaviour changed:

- `CURSOR_TABLES = ("link_state_cursor", "link_state_runs")` — the bookkeeping tables named next to
  the DDL that creates them, so "installed" can mean something testable.
- `schema_status(conn)` — read-only: which evidence columns are present/missing, which cursor
  tables exist, whether `cat_links` is `absent` / `no_link_id` / `linked`, and the two answers an
  operator actually needs: `installed` and `legacy_evidence_only`. It also returns
  `pending_evidence`, the list `_pending_where` judges a row by — **the shrink itself, printed**.
- `schema_plan(conn)` — exactly what the two `ensure_*` calls would add to this file, computed
  before any write.
- CLI `--schema` — prints `schema_status`, **never writes**, with or without `--apply`; in plan
  mode it prints `{"schema", "would_add", "plan"}` on a connection that cannot write.
- CLI `--ensure-schema` — the declared migration step. Without `--apply`: the plan, file untouched.
  With `--apply`: `ensure_schema(conn)` + `ensure_projection_schema(conn)`, printing
  `{"before", "added", "after"}` so the `added` dict is recorded for the audit trail, then returns
  **before** probing or propagating anything.

`__all__` gained the two functions. Nothing else in the module moved, so the sweep, the verdict
collapsing, the projection writes and `/api/v1/stats`' payload shape are byte-for-byte unchanged —
deliberately: a `schema` key inside `status_summary` would have leaked into `stats_payload` and
therefore into the published stats route.

## Tests (`Fast_Fetch/test_link_state.py`, +10, 28 → 38, all green offline)

Covering the spec's own verification list, on `/tmp` fixture copies only:

1. the PRAGMA **name diff** after the migration is exactly the six additions, and every
   pre-existing column keeps its declared type/default (`schema_plan` == `added` == that diff);
2. idempotent end to end — a second `ensure_schema` + `ensure_projection_schema` adds nothing;
3. an **uninstalled** catalog still answers `status_summary` and `stats_payload` (the documented
   read-only behaviour must not regress), and `schema_status` calls it `legacy_evidence_only`;
4. a legacy `cat_links` with no key is reported `no_link_id`, planned, and given `ledger_link_id`;
5. stored row values are identical before/after, and a newly added column is **NULL**, not a
   fabricated verdict;
6. three CLI no-write guarantees, checked by the file's own md5: `--schema`, `--schema --apply`,
   and `--ensure-schema` without `--apply`;
7. `--ensure-schema --apply` installs with `link_health.probe`/`probe_many` patched to explode —
   the migration is a DDL step and provably knocks on nothing.

`python3 -S Fast_Fetch/test_link_state.py` → **38 tests OK, 43.662 s** (this box, load 4.9-9).
`python3 -S Fast_Fetch/test_docs_invariants.py` → **22 tests OK, 10.704 s**.

## Held, named, and pinned — spec verification 4 is NOT implemented

The spec's fourth check wanted: *after install, a row carrying only a legacy `last_checked_at`
stops counting as swept evidence once `checked_at` exists.* As a criticism that is correct — the
legacy tolerance in `_pending_where` is a stopgap, not a verdict. As a change it is
**sweep-semantics**, not an additive migration: every row the old `run_health_check` ever touched
becomes pending again, which on the production ledger is a multi-million-request re-probe of
external hosts. That is (a) outside the order's "additive migration only", (b) a HEAVY READ under
the Fleet Resource Guardrail (load was 8.9-10.3 all session, and rule 2 freezes exactly this), and
(c) an owner/supervisor cost decision, not a lane's. So the current behaviour is pinned by
`test_a_legacy_timestamp_row_is_still_not_re_probed_after_install`, whose docstring says why it is
a stopgap, and `schema_status()["pending_evidence"]` makes the tolerance visible instead of silent.
Flipping it is queued, not taken.

## Quiet-window action (queued, not run)

Applying the migration to the live catalog is the **operator's** declared action, and it is a
write, so it is not run here:

```bash
# expected cost: 6 ALTER TABLEs on a 3M-row table + 2 CREATE TABLEs; metadata-only in SQLite,
# but it holds a write lock briefly against a live service — run in a quiet window.
python3 -S Fast_Fetch/link_state.py --db <named catalog file> --ensure-schema          # plan, writes nothing
python3 -S Fast_Fetch/link_state.py --db <named catalog file> --ensure-schema --apply  # the migration
python3 -S Fast_Fetch/link_state.py --db <named catalog file> --schema                  # verify: installed: true
```

Record the printed `added` dict afterwards. This step is also the prerequisite for gap 1 (expiry
mirror), gap 3 (the two resumability fields) and gap 2 (cache answers) in the spec's own order
**4 → 1 → 3 → 2**.

## Publish state — honest, and the fifth identical refusal

- Branch `q5-fix-probe-evidence-20261102`, commit **`53396df`** (`53396df17facb895a5132b5b82c3ddc4be14077d`)
  on `846fb76`; worktree `/tmp/q5_probe_fix`; tree clean.
- **No CI run id exists for this commit, because the push failed.** One attempt, per standing
  order, with both documented pre-checks satisfied first — `GITHUB_TOKEN` present in the
  environment and the heredoc-built askpass helper emitting a non-empty password (checked with
  `-n`, never printed) — so this is the credential, not the procedure:
  `remote: Invalid username or token. Password authentication is not supported for Git operations.`
  Fifth consecutive lane-identical refusal (`q5_gate5` slices 4/7/8/9 were the first four). No
  retry, no alternative credential, no history rewrite.
- **Next step is qoder1's**, as it was for slices 4-9: land `53396df` (or push this branch ref) so
  `backend-ci.yml` runs — the path filter is fed, since both edited files are under
  `Fast_Fetch/**`, and `test_link_state.py` is one of the `🧪` steps in that workflow. Until then
  the claim is "locally gated, unpublished", not "CI green".
- `Fast_Fetch/CONTINUITY.md` was at **11,817 / 12,000 bytes** before this entry, which is why the
  record is a rotated archive file plus a 163-byte index line rather than a normal session block —
  and why no other prose was added there. If the ceiling is too tight for the next lane's entry,
  that is a rotation decision for the supervisor, not something a lane should work around silently.
