# 2026-11-01 09:3x — q2 lane `[Q2-CI-46-NAMEERROR]`

Step `#46 🧪 test_adult_vault_census.py` was the only red step in two hosted runs of my own branch —
41271464775 / job 124744923995 on `1481cf8`, and 41272358454 on `35ad683`. Both said
`Process completed with exit code 1` and nothing else; the annotations endpoint repeats it, and the
zip log needs a token this lane does not have.

## The bug

`test_null_empty_and_unknown_keys_never_become_twins` held a table of 2-tuples and unpacked
`for name, rows in cases`, then asserted against `expected` — a name the edit that introduced the
table had left behind. Three `NameError`s, raised while evaluating the *arguments* of
`assertEqual`, so the census code was never called. Exit 1, no failure detail, one red step.

`d621700` puts `expected` in the table as data: 0 for all three rows. A `NULL`, an empty string and
`unknown` are the shared bucket every titleless payload lands in, not a work, so a flagged row and an
unflagged row that share one of those keys is not an exposure. That is the same law
`audit_adult_flags.py` states for the ledger and `test_adult_twin_probe.py` already pins.

`67a3557` is a second, separate defect found in the same pass: `census_vault(path)` checked
`Path(path).name` against `FORBIDDEN` and then passed the *original* argument to `fingerprint()` and
`open_readonly()`, so a caller holding a plain string got
`AttributeError: 'str' object has no attribute 'name'` — and only *after* walking past the refusal it
was supposed to be. Normalised at the top. My suite passes `Path`, so neither CI run was about this.

## The method error, which is the part worth keeping

I did not run the suite (local test-module runs stay FROZEN), so I re-derived its assertions as
standalone computations against temp fixtures in three sub-second `nice -n 19` snippets. They printed
**FAILS: 0** while CI was red.

What those snippets re-derived was the *semantics*: mixed key → exposure, all-flagged key → hidden,
`NULL`/`''`/`unknown` → not a twin, `COALESCE(flag,0)` → unflagged. Every one of those was correct,
and the census produced the right numbers for them in the snippets. The red case was not a wrong
semantics; it was a *name in the source that was never bound*. A re-transcription that computes the
meaning instead of executing the file cannot see that class of defect — it re-authorises the intent
and silently discards the spelling.

The fix for the method is static analysis, which costs nothing and breaks no freeze: an `ast` walk
that collects each function's bindings (args, stores, `except as`, `global`) against its loads, plus a
pass for `self.test_*` targets that no class defines. Run over
`adult_vault_census.py test_adult_vault_census.py project_readonly.py test_project_readonly.py` it
flagged exactly the one line above and nothing else in those four files. That is what I should have
done *before* pushing, and it is now the standing check for any slice written under a freeze:
compile the file, then resolve every name it loads.

## What this branch owes

Nothing measured. `#37` still has **no census numbers** — `PRICED` holds 19 priced vaults, the plan is
arithmetic, and no real vault has been opened by this command. #18 stays *safe to type, not sized*.

## Do not re-derive

- **CI's step list is more informative than CI's log here.** `/actions/runs/{id}/jobs` gives per-step
  conclusions unauthenticated; the annotations endpoint gives only the generic exit-1 line; the log
  endpoint 404s without a token. Don't burn the shared per-IP quota re-reading the same run.
- **A green standalone replication is not a green suite.** If a slice cannot be executed locally,
  static-check it; do not trust a semantics-only re-derivation to catch a source typo.
- The two commits above are independent fixes; the `NameError` is the only thing that made #46 red, so
  do not go looking for a second cause in the census SQL.
