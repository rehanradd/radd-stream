# 2026-10-31 — state-shaped claims: the second audit, and the step count that cannot be remembered

Branch `q5-state-shape-audit`, from trunk `40bb84f` (`origin/main`). The class: a claim about the
world as it stands today, pinned or indexed where only a rule should sit. Last time the instance was
`currently absent` (the guard refused the truthful correction); this time it is `all 32 steps now`
(CONTINUITY line 38) — true when written, false the moment a suite was added, and tested by nothing.

Method: grep the five auto-loaded docs (root `AGENTS.md`, `Fast_Fetch/AGENTS.md`, `App/AGENTS.md`,
`Fast_Fetch/CONTINUITY.md`, `docs/SESSION_CHECKPOINT.md`) and both checkpoint indexes for
`N steps/suites`, `N tests`, `currently absent`, `not yet built`, `running as we speak`, and every
`file:line` cite; verify each against the tree, not against a memory of it. A throwaway probe
(`/tmp/q5_state_guard_probe.py`, not committed) implements the proposed guard checks and was run.
Docs guard baseline on this tree: **18 tests OK**.

## A. Protected by a test — safe today

- `58 session files` (CONTINUITY:10) and `59 files cover` (SESSION_CHECKPOINT:7): recomputed from the
  directory listing on every run (`test_the_index_counts_are_the_directory_listings`).
- Byte ceilings, `≤120 lines`, the newest archive being named by its README, conflict markers, and
  link resolution — bounded or computed, not remembered.
- The adult-law sentences, including the eight code cites' *laws*. The **line numbers are not
  pinned** (see C).
- Carried over from the last audit and still state-shaped: the secrets-list JSON, the signing-preflight
  outcome, the debug-APK upload step, `No signed APK or AAB has ever existed`, `266.312 s`,
  `1 s on the hosted runner`, the one-vCPU line, the literal `paths:` filter, the nginx allow-list,
  `442 keys / 455 rows`, and `2,600 / 3,486 / 69,773`. Each is already reported with a law-shaped
  replacement; none was changed here.

## B. Unprotected and stale today (measured on `40bb84f`)

| # | where | quote | today |
|---|---|---|---|
| 1 | `CONTINUITY.md:38` | `all 32 steps now` | **35** `🧪` suites, **37** named steps. q1's `8137b16` retires it to `all its steps`; that commit is not on trunk yet. |
| 2 | `CONTINUITY.md:45` | `83 tests, CI 33` | the onboarding suite is **suite #34 / all-step #36** |
| 3 | `SESSION_CHECKPOINT.md:32` | `83 offline tests, CI step 33` | same suite, same drift |
| 4 | `Fast_Fetch/checkpoints/README.md:11` | `83 tests, CI step 33` | same |
| 5 | `SESSION_CHECKPOINT.md:48` | `complete index (all 54)`; `newest 14 are listed here` | **59** archives; **15** bullets listed |
| 6 | `docs/checkpoints/README.md:13` | `that file is at 54 lines / 5.4 KB` | **71 lines / 7.4 KB** |
| 7 | `AGENTS.md:16` | `they are 119 and 54 lines` | **99 and 71** lines |
| 8 | `Fast_Fetch/AGENTS.md:40` | `https://github.com/radddao/radd-stream` | the repo is `rehanradd/radd-stream` |
| 9 | `Fast_Fetch/AGENTS.md:41` | `fast_fetch.py (3,907 lines)` | **6,745** lines |
| 10 | `AGENTS.md:202, 244, 324` | `/actions/secrets` is `[]`, so a release run cannot succeed today | all four secrets were configured 2026-10-30 and the preflight cleared at run `41104217171` 18:08:05Z — the release now gets past it and dies later, at the base64 decode. The law (no agent tags) stands; the **reason** is false. |
| 11 | `AGENTS.md:322-323` | `tags: [] and releases: [] are measured empty` | tag `v1.0.0` exists on the remote → `6a441ec77` (one `git ls-remote`). Contradicts `AGENTS.md:146` in the same file. (A local clone tag points elsewhere; that is clone drift, not doc evidence.) |
| 12 | `SESSION_CHECKPOINT.md:24` | `85 commits behind with 22 dirty backend files` | `bf9e565` is **157** commits behind `origin/main` today |
| 13 | 14 linked reference files | `(N lines)` labels | every one is off, mostly by +3 from the diet header: 221→224, 79→82, 19→22, 95→98, 19→22, 37→40, 25→28, 214→217, 74→77, 1686→1689, 294→303, 120→125; `SESSION_HISTORY.md` is advertised twice as 19 and 235, actually **741** |
| 14 | `App/AGENTS.md:11, 35` | `Device/CI verification … still pending`; `The Android ci.yml job is red` | the device half is still true; the CI half could not be re-measured from here (no credential) and the tree's own entries claim hosted App greens. Re-measure before deleting — do not assert either way. |

## C. Unprotected but true today (verified line-by-line)

- The nine root-`AGENTS.md` code cites — `fast_fetch.py:4598`, `redact.py:1077`/`:1083`,
  `viewer.py:557`/`:887`/`:917`/`:1919`/`:2780`/`:2956` — plus `release.yml:53` and
  `App/app/build.gradle.kts:120`: **11/11 land on the code they name** on `40bb84f`.
- `26 🧪 steps … measured 2026-10-30 at 56e743b` — anchored to an immutable sha, so it cannot rot.
  This is the model for any size claim that has to be written down at all.
- `test_accounts.py` and `test_payments.py` are absent from `backend-ci.yml` — verified absent.
- `the 429-parking and per-run cap are unbuilt` (CONTINUITY:30) — there is no parking path in
  `link_health.py`; still true.
- 105 `file:line` cites inside `docs/checkpoints/**` and `Fast_Fetch/checkpoints/**` are historical
  and append-only; they are conservation records, not current claims, and must not be re-pinned.

## D. The mechanical form (proposed; probe run, not committed)

**1. The workflow declares its own size; the guard recomputes.** Add one machine-readable line under
the header of `backend-ci.yml`:

```yaml
# test-suites: 35   # must equal `grep -c 'name: 🧪' .github/workflows/backend-ci.yml`
```

```python
class WorkflowSuiteCountTests(unittest.TestCase):
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "backend-ci.yml"

    def test_the_workflow_declares_the_suite_count_it_contains(self):
        text = load(self.WORKFLOW)
        declared = re.search(r"^#\s*test-suites:\s*(\d+)\b", text, re.M)
        self.assertTrue(declared, "backend-ci.yml lost its `# test-suites: N` declaration")
        counted = len(re.findall(r"^\s*- name: 🧪", text, re.M))
        self.assertEqual(int(declared.group(1)), counted,
                         "backend-ci.yml declares %s suites, contains %d"
                         % (declared.group(1), counted))
```

Probe on trunk: `declared=None, counted=35` — the declaration is exactly the missing half. Adding a
suite now means editing the file that grows, in the same edit; a forgotten bump is red.

**2. No loading doc may remember that number.** The same class as `all 32 steps now`:

```python
    def test_no_loading_doc_remembers_the_gate_size(self):
        shapes = [re.compile(r"\ball \d+ steps?\b"), re.compile(r"\bCI (?:step )?\d+\b")]
        offenders = []
        for path in AUTO_LOADED + [CONTINUITY, CHECKPOINT, FF_CKPT / "README.md", DOC_CKPT / "README.md"]:
            for n, line in enumerate(load(path).splitlines(), 1):
                if any(s.search(line) for s in shapes):
                    offenders.append("%s:%d %s" % (path.relative_to(REPO_ROOT), n, line.strip()[:80]))
        self.assertFalse(offenders, "say 'all its steps', not a number:\n" + "\n".join(offenders))
```

Probe: exactly four hits today — B1–B4 — and zero false positives; the sha-anchored 26-step sentence
is untouched by design. Say **all its steps**; the number lives only in the workflow declaration.

**3. Citations become tested claims.** A table of `(doc, cite, needle)` and a ±4-line window:

```python
    def test_every_code_citation_points_at_the_code_it_names(self):
        for doc, cite, needle in CITES:
            rel, n = cite.rsplit(":", 1)
            src = load(REPO_ROOT / rel).splitlines()
            window = " ".join(src[max(0, int(n) - 4):int(n) + 2])
            self.assertIn(needle, window, "%s: %s no longer lands on %r" % (doc.name, cite, needle))
```

Probe: 11/11 pass as written; shifting each `viewer.py` cite by one line fails 6 of them — the check
is non-vacuous. This is what turns "a later edit moved the line" from a silent rot into a CI failure;
today nothing checks a single one of these numbers.

**4. Counts that restate a listing are recomputed, never remembered.** The existing count test covers
the two headline claims; extend the same shape to `all N` / `newest N` in `SESSION_CHECKPOINT.md` and
to the `(N lines)` labels (probe: 2 + 14 mismatches, all listed in B5/B6/B13). Where the number adds
nothing — `(N lines)` on a living file — delete the label; where it is an index promise, compute it.

## E. What this branch did not do

- No doc claim from B was edited here. Two candidates are in flight over the same lines
  (`q1-edge-scenarios-20261031` owns B1; `ae8f86d` is in the hosted gate). The edits are enumerated
  above so the lane that lands the guard can apply them in one pass and watch it go green.
- The previous audit's class-A pins are unchanged; the guard is the supervisor's surface.
- Push is blocked on this box (`GITHUB_TOKEN` is 401 on `/user`); the commit is local.
