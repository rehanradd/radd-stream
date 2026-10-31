# 2026-10-31 — the guard's remembered constants: a derived/remembered audit, and the gate that now checks itself

Branch `q5-guard-derived`, from trunk `babb06f`. Guard run at the end: **22 tests OK**
(`nice -n 19 python3 -S Fast_Fetch/test_docs_invariants.py`, 3.2 s). One `.py` touched:
`Fast_Fetch/test_docs_invariants.py`. Everything else is markdown.

## 1. The rule this audit applies

A guard may **remember a rule**; it may not remember a **fact**. A remembered fact is a literal that
someone has to keep editing as the tree moves — and when nobody does, the guard pins a lie. This
file has already done that once (`currently absent`, fixed at `cc5f393`), and the `all 32 steps now`
claim went false in the very commit that made it false, in `CONTINUITY.md`, with nothing looking.

## 2. Every assertion in the guard, by class

**Derived — computed from the tree or the workflow at run time (good):**

| test | what it derives |
|---|---|
| `InvariantPhrasesTests.test_each_target_file_exists_and_is_non_empty` | file existence + a 1 KB floor |
| `test_invariant_labels_are_unique_so_no_check_is_silent` | the label list itself |
| `test_every_invariant_target_is_reachable_from_the_loaded_indexes` | link text in the five indexes |
| `RotatedHistoryTests.test_rotated_log_directories_exist_with_content` | directory + ≥10 files |
| `test_app_session_history_moved_and_exists`, `test_moved_spec_documents_exist` | named-file existence (a *required* set, i.e. law) |
| `test_no_history_line_was_deleted_only_moved` | the listing's newest file vs the index |
| `LinkIntegrityTests.*` | every relative link target |
| `AbsorbedTrunkEditTests.test_absorbed_files_are_named_by_the_index` | index text vs archive names |
| `test_the_index_counts_are_the_directory_listings` | `N session files` / `N files cover` vs `glob` — the model |
| `test_trunk_added_no_line_that_is_now_nowhere` | two immutable shas (`4fe6f65`, `dc73ac7`) |
| `ConflictMarkerTests`, `OpenItemsIndexTests` | file contents, positions |
| **new** `WorkflowSuiteCoverageTests.*` | the workflow's steps and the `test_*.py` files |

**Remembered, but a bound or a decision — must be edited on purpose, not a fact (keep):**
`ByteBudgetTests.CEILINGS` (32/18/15 KB), the 12 KB / 120-line session ceilings, `≥10` archives,
`≥20` SPECs, the 4,000-char index position. A ceiling cannot go stale the way a count does: it is a
policy whose whole purpose is to require a deliberate edit.

**Remembered, and it encodes a fact about today — the defect class (16 pins, all in `INVARIANTS`):**

| pin label | the literal | why it is state |
|---|---|---|
| `measured: secrets list is empty` | `{"total_count": 0, "secrets": []}` | false since 2026-10-30 (secrets configured; preflight cleared at run `41104217171`) |
| `release died at the signing preflight` | `it died at the … preflight` | a 2026-10-29 run outcome; the preflight now passes |
| `debug APK needs no secret` | `uploads a **debug APK** on every green run` | workflow behaviour snapshot |
| `no signed artifact has ever been produced` | `No signed APK or AAB has ever existed…` | event-expiring; true until the first release, false forever after |
| `one vCPU` | `**This host has ONE vCPU** (`nproc` = 1)` | host property, not law |
| `rule 7 carries its measurement` | `266.312 s` | one sample, re-measured routinely |
| `rule 7 names the hosted verdict` | `1 s on the hosted runner` | same |
| `the filter shape is measured, never assumed` | `` `paths: ["Fast_Fetch/**", …]` `` | the file itself says the shape is not the rule |
| `nginx allow-lists the public routes` | enumerated route list | the list has already grown |
| `backend is the running system` | `**already deployed there and is the running system**` | deployment status |
| `the named hole: 442 keys / 455 rows` | `442 keys held both…` | pre-reconciliation measurement |
| `residual measure under the correct identity` | `2,600 … 3,486 … 69,773` | dated measurement |
| `MovieBox is metadata + trailer evidence…` | `**metadata + trailer-evidence** source, not a` | site capability status |
| `no playable print is resolvable from this host` | same | status the fleet is trying to change |
| `app: arm64-excluded suites are invisible here` | `no number printed on this host includes those two suites` | toolchain state |
| `app lane: signed release needs the 4 secrets` | `the *signed release* needs the 4 keystore secrets` | **a requirement — keep as law** |

Every one of the first fifteen should pin the sentence around it instead: *do not re-quote it as a
live blocker*; *the debug build needs no secrets*; *read the workflow's own trigger block*;
*nginx allow-lists only the public routes*; *do not copy untested or WIP code onto it*; *that is
fixed here, not by adding another `WHERE` clause* (already pinned); *the vault stays a FAIL until
some surface publishes a playable URL* (already pinned). None was re-pinned here — the guard is the
supervisor's surface, and the previous audit enumerated them.

## 3. The gate now checks itself

New class `WorkflowSuiteCoverageTests`. It reads `.github/workflows/backend-ci.yml`, extracts every
`- name: 🧪 …` step and every `(time) python3 -S …test_*.py` run command, and compares them to the
`test_*.py` files that exist under `Fast_Fetch/` and `Fast_Fetch/importers/`:

1. **step name == run command** — a renamed module or a step whose name drifted from its command fails;
2. **no module runs twice**;
3. **every step runs a module that exists** — a deleted or renamed file fails with the file named;
4. **every module is registered, or recorded as debt** — `in_gate | UNREGISTERED == on_disk`.

Measured at `babb06f`: **35** suite steps, **35** run commands, **0** missing, **86** modules on
disk, so **51** are outside the gate. Strict set equality (`in_gate == on_disk`) is therefore *false
today* and cannot be landed as a passing test. What is landable, and what survives the next merge,
is the equality *modulo a declared debt set*: `UNREGISTERED` is a ratchet of 51 names, grouped in
the code with the reason each is out. It is recalled, but it is a **decision ledger, not a count**:
when a module appears, the test fails and the author must register it or write down why not; when
one is registered, the test fails until it is removed from the ledger; when one is deleted or
renamed, it fails too. The debt shrinks towards plain equality; it cannot silently grow.
`test_accounts.py`, `test_accounts_api.py` and `test_payments.py` — the money and keys — are in it,
which is the known defect the fleet keeps re-measuring.

**Non-vacuity, probed** (`/tmp/q5_cov_probe.py`): a step pointing at a deleted module, a name/run
mismatch, a duplicated suite, a brand-new unregistered module, and a deleted module still listed as
debt all fail with their own message; the unmodified tree passes.

## 4. What was deliberately not done

- No `INVARIANTS` pin was edited (supervisor's surface; items listed above with the law to pin).
- Strict equality was not faked by registering 51 suites: several are live/network audits, that is a
  fleet scheduling decision, not a docs-guard edit.
- No count was added to `backend-ci.yml`; the step list is the fact, and it is now derived.
