# [Q5-CI-AND-DOC-TRUTH] 2026-10-30 — the CI inventory is closed in both directions, and the docs stop asserting retired facts

**Lane:** q5 (`/tmp/q5_ci`, branch `q5-ci-20261030`, based on trunk `6a441ec`). Lane scope: test
modules, `.github/workflows`, docs. No `Fast_Fetch/*.py` implementation file and no App Kotlin
touched — qoder3 owns those.

## Task 1 — CI inventory integrity (measured, then closed)

Enumerated every `test_*.py` under `Fast_Fetch/` and `Fast_Fetch/importers/`: **83 modules**. The
workflow had **32** `name: 🧪` steps. No step named a file that does not exist (checked each of the
32 against the tree). The gap was the other direction: **21 real `unittest` modules (1,235 test
methods) never ran in CI**. Of those, 18 are per-site importer suites that the workflow header
deliberately excludes (their fixtures track each site's layout). Three are **not** per-site importers
and were covered by no stated policy, so they were simply never wired:

| module | tests | verified locally |
|---|---|---|
| `Fast_Fetch/importers/test_stream_resolvers.py` | 45 | **45/45 OK** (41.096 s) |
| `Fast_Fetch/importers/test_convert_mp4moviez.py` | 15 | **15/15 OK** (81.828 s) |
| `Fast_Fetch/importers/test_host_resolvers.py` | 171 | **NOT RUN — load hold** (see below) |

All three are offline by construction (`test_host_resolvers.py` replaces `socket.socket` with a
raiser; the other two use fixtures/in-memory SQLite). They are steps in `backend-ci.yml` now.

**The closure is a guard, not four steps.** New `Fast_Fetch/test_ci_inventory.py` (also a CI step)
asserts, offline: every real `test_*.py` is either a 🧪 step or an `EXCLUDED` entry with a stated
reason; every step names a file that exists and runs the file it names; no suite runs twice; an
exclusion that has rotted (file gone) is a failure. The 18 per-site importers are the only entries
in `EXCLUDED`.

**Coordination with qoder3:** `test_adult_key_reconcile.py` was left out of every edit to
`backend-ci.yml`; my four steps are appended at the end of the step list so their insert collides as
little as possible with qoder3's.

## Task 2 — docs truth pass (each claim re-measured; file:line cited)

| claim | verdict |
|---|---|
| `test_database.py` is **133** (root `AGENTS.md:224`) | **TRUE** — `def test_` and an AST walk both give 133; `20261030-session-…-q2-mb-stopflag` records 133 OK. No edit. |
| "GitHub has zero keystore secrets" | **STALE** — `63396c1` (trunk) records all four configured 2026-10-30. The section carried the live sentence "CI cannot produce a signed release… until the owner adds all four" next to the CURRENT update. Rewritten as HISTORICAL → CURRENT, one answer. |
| "15 CI test modules/suites" (`docs/MONETIZATION_AND_FLEET_PLAN.md:57,58`) | **STALE** — 32 on trunk. Both cells now point at the workflow instead of a remembered number. |
| README `:170-171` "no rate limiting / wildcard CORS / binds 0.0.0.0" | **ALREADY CORRECTED** — `README.md:169-172` quotes that claim only to retire it; `:174-183` states the measured code (`CORS_ALLOW_ORIGINS` empty at `redact.py:1309`; `_public_gate` at `viewer.py:3379`; `start_server` default `host="127.0.0.1"` at `viewer.py:3929`). No edit. |
| adult 442-keys / 455-twins | **CONSISTENT** — root `AGENTS.md:81,97` labels it the pre-reconciliation slug-keyed count and gives the residual 2,600 / 3,486 / 69,773, matching `CONTINUITY.md:25-27`. No edit. |
| adult-law line citations | **ALL DRIFTED** — fixed: `adult_clause` 1073→`redact.py:1077`; `api_v1_get_posts` 2534→`viewer.py:2779`; bails 709/2710→`886`/`2955`; `link_is_adult` 1079→`1083`; `DASHBOARD_HTML` 739→`916`; `fetch_database_payload` 494→`556`; badge 1681→`1918`. |
| `save_scraped_data` re-derive at `fast_fetch.py:4426` | **TRUE**. |

**The reported contradiction, now stated one way.** `redact.link_is_adult` (`redact.py:1083`) ends
`return bool(row and row[0])`, so an **unknown** link id answers **False** — while its own docstring
and root `AGENTS.md` both said "True, so a typo cannot play". Measured effect: the resolver's 404
`no_playable_source` is what stops a typo; the gate is fail-open. `AGENTS.md` now says exactly that,
names the characterization test (`test_operator_adult_projection.py::test_an_unrecognized_link_id_reaches_the_resolver_today`),
and states that qoder3's fail-closed flip takes the docstring **and that test** with it. The code is
unchanged here (qoder3 owns it). Pins in `Fast_Fetch/test_docs_invariants.py` updated in this commit
for the two sentences that changed; the historical 10-29 secret measurement and preflight sentences
were kept word-for-word so their pins still hold.

## Not verified / not run

- **`test_host_resolvers.py` (171 tests) never ran.** Supervisor hold at load 12.5 arrived after
  `test_convert_mp4moviez.py` finished. Exact queued command, under `nice -n 19`:
  `python3 -S Fast_Fetch/importers/test_host_resolvers.py` (offline); cost unknown, its two sibling
  suites took 41 s and 82 s at load 6.7–8.7. Its own docstring says the fixtures are captured host
  HTML with `socket.socket` replaced by a raiser. **If it is red, drop its step — do not drop the
  other two or the guard.**
- `test_ci_inventory.py` itself was **not executed** (written during the hold). It is static: reads
  the workflow and two directory listings; it was reviewed by hand against the tree (83 modules, 36
  steps after this change, 18 exclusions, no overlap).
- `test_docs_invariants.py` was **not executed** after the pin edits (same hold). Each new pinned
  phrase was checked with `grep -F` against the edited files; `docs/SESSION_CHECKPOINT.md` count
  updated 54→55 / 52→53 dated to match the new archive file.
- No CI run observed. No tag, no Gradle, no service restart, no production catalog read.
