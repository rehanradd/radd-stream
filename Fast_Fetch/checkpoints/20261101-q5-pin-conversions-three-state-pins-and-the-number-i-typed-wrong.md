# 2026-11-01 — q5 backend lane `[Q5-PIN-CONVERSIONS]` three state pins converted, and the entry count I typed wrong

Session: q5 (account5), worktree `/tmp/q5_gate5`, branch `q5-pin-conversions-3-20261101`.
Machine state as reported by the supervisor at 08:30: **load 6.8, above the 4.0 gate → LIGHT ONLY, hosted CI
only**. Nothing heavy started: no Gradle, no crawl, no merge, no production read, no test module run locally.

## 0. The assignment

Muse, 08:30: the `INVARIANTS` pin conversions are sliceable on supervisor word — **one small slice, at most 3
conversions**, or the smallest coherent slice if 3 would split a unit; worktree/branch only; push to a **new**
q5 branch; do not re-push `q5-verdict-keys-on-c2528e1` (`c0e86e5`); gate nothing; `.exists()` probes and
production reads stay frozen.

**Actual count: 3 conversions.** I checked the split question against the tree rather than assuming it: the
16 audit items are *individually* convertible (each is one label pinning one literal), so three of them does
not cut a unit in half — with one exception I handled by taking **both** pins of the rule-7 unit, which is
the pair that shares a single sentence in `AGENTS.md`. Taking one of the two would have been the split.

## 1. What a "conversion" is here, and the precedent that made it mechanical

`test_docs_invariants.py` asserts `flat(phrase) in flat(file)` for each of the 104 `INVARIANTS` entries. A
**state pin** puts a *measured value* in that literal, so the guard fires red when a lane makes the doc
*more accurate* — re-measure `266.312 s`, edit `AGENTS.md`, CI goes red. A **law pin** puts the interpretive
clause in that literal, so the value can move and the guard still bites on the sentence that matters.

The file already contained the pattern to copy, and I used it rather than inventing one:
`("the panel guide separates the running tree from the repository", ADMIN_DOC, "Read that table as the state
of the *running tree*, not of the repository.")`. That pins *how to read a table*, not *what the table says*.

## 2. The three conversions (guard-only edits; zero `AGENTS.md` bytes moved)

| old label → literal | new label → literal |
|---|---|
| `rule 7 carries its measurement` → `266.312 s` | `rule 7 says the local number is a symptom` → "the local number is a symptom of the guardrail, not a property of the code" |
| `rule 7 names the hosted verdict` → `1 s on the hosted runner` | `rule 7 gives CI the timing authority` → "only CI's per-step timing decides whether a suite belongs in the gate" |
| `nginx allow-lists the public routes` → the `/api/v1/posts`, `/api/v1/stream`, `/api/v1/stats` enumeration | `nginx allow-lists rather than block-lists at the edge` → "allow-lists only the public routes" |

**Why these three first.** The nginx pin had the most to say and the least to guard: its literal is the first
**three items of a seven-item enumeration** in the Key Links row (`/api/v1/posts`, `/api/v1/stream`,
`/api/v1/stats`, `/api/v1/download`, `/api/v1/search/by-media`, `/api/v1/app/remote-config`,
`/api/v2/account*`). Checked against `git show c2528e1:AGENTS.md` before I wrote this: **it matched**, so the
honest description is not "a broken pin" — it is a pin that red-fires on any reorder or reword of a list the
doc has visibly grown once, while claiming to guard the allow-list and in fact describing only its head. The
rule-7 pair pins two stopwatch readings, one of them taken at load 6.9 on a box whose top five consumers are
the lanes themselves.

**Why no doc edit was needed, and why that matters:** all three replacement clauses are already present
verbatim in `AGENTS.md`, verified before committing. `AGENTS.md` is at **31,990 B against a 32,000 B
ceiling** (`ByteBudgetTests.CEILINGS`), i.e. **10 bytes of headroom**, so "rewrite the sentence so the pin
fits" was not a cheap option for anyone — it would have needed bytes freed first. A conversion that only
moves the guard's pointer can land under that ceiling; a conversion that needs new law in the file cannot, and
that distinction is what decides the order of the remaining slices.

**The trade, stated rather than hidden behind the word "converted":** the tax is gone, and so is the guard's
accidental insistence that someone re-measures those numbers. Nothing now fails if `266.312 s` sits stale in
`AGENTS.md` forever. Rule 7's own sentence ("only CI's per-step timing decides") is what still asks for it,
plus `docs/CAPACITY_MEASURED.md`. That is the correct place for the pressure — but it is softer than a red CI.

## 3. The number I got wrong, and the method that would not have gotten it wrong

The previous version of `docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md` said the block had **"98 entries total"** and
labelled it "measured on the sha". **It was 104 and always was** — `len(INVARIANTS)` at `c2528e1` is 104, and
`grep -c '^    ("'` on the same file agrees. So this was not a tree that moved under a correct measurement; it
was a wrong number wearing the word "measured". The corrected paragraph is in the money doc, with the reason:
a line-grep and a hand-count both fail on a list whose entries wrap across lines — the same failure mode as
`grep 'run: python3 -S'` undercounting the CI suites, which `AGENTS.md` already warns about and which I quoted
twice today while doing the identical thing.

**The method now written into the doc:** ask the module (`len(INVARIANTS)` from importing the file), not the
text of the file.

**A second one, caught before it landed.** The first draft of §2 called the nginx pin "a live timer" whose
enumeration the doc had "already grown past", implying the pin had silently stopped matching. It had not: the
literal is the first three items of a seven-item list and `flat()` still finds it in `git show
c2528e1:AGENTS.md`. I checked that against the sha instead of against my impression, and §2 now says the
accurate, less flattering thing — the pin matched, which is *worse* than being broken, because it reported
"the allow-list is guarded" while describing only the head of it. Same lesson as the 98, one rung sharper: a
claim about a *match* has to be tested by matching, not by reading the list and eyeballing whether it changed.

## 4. Verification done locally, and what was deliberately not done

Imported `test_docs_invariants.py` and ran its own comparison over **all 104 entries**: **0 missing phrases, 0
duplicate labels** (`test_invariant_labels_are_unique_so_no_check_is_silent`'s property). That is a read-level
operation on the module, not the suite — **`test_docs_invariants.py` was not run locally**, because the freeze
says no test modules and load is 6.8.

Also checked: this slice adds **one new checkpoint file** — this one — so the archive count moves 69 → 70 and
the dated count 67 → 68, and both are edited in this commit: `CONTINUITY.md` line 10 (a length-neutral
`69`→`70`, `67`→`68`, which is why the file still fits its 12,000 B cap at 11,970 B / 93 lines) and an index
bullet in `Fast_Fetch/checkpoints/README.md`. `test_docs_invariants.py::test_the_index_counts_are_the_directory_listings`
compares the `(\d+) session files` figure against the directory listing, so writing the file and leaving the
count is a red CI step — and this lane has already been burned once by a count that moved under a clean merge,
which is why the count is re-derived from the listing rather than incremented from memory.

**Cited by function name, not line range, on purpose.** The previous draft of this file said
`test_docs_invariants.py:478-487`; adding nine lines to that same file in this commit moved the function to
485-499, so the citation went stale inside the commit that wrote it. That is the fourth instance today of a
tree-derived number rotting under its own sentence (the session count, the CI step count, the "98 entries",
this one), and the fix is the same each time: name the function, the run id, or the sha — never the coordinate.

`docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md` is not under a byte ceiling (`CEILINGS` covers the root,
`Fast_Fetch/` and `App/` `AGENTS.md`; the 12,000 B / 120-line cap covers `CONTINUITY.md` and
`docs/SESSION_CHECKPOINT.md`, and this slice leaves `docs/SESSION_CHECKPOINT.md` at 11,941 B / 112 lines
untouched).

## 5. Status of the remaining twelve, and the two that are not mine

3 of 15 converted; **12 open**, of which 2 are *tolerable* (`measured: secrets list is empty`,
`release died at the signing preflight` — the prose they quote was reframed as history by `63396c1`/`b48d15f`).

**Two of the twelve need a supervisor decision, not a docs tidy:** `one vCPU` (`**This host has ONE vCPU**
(`nproc` = 1)`) and `backend is the running system` pin host hardware and deployment status, and every clause
around them in `AGENTS.md` is *also* a status claim. Converting them means writing new law into a file with 10
bytes of headroom, which means freeing bytes first, which is a fleet-wide doc decision. I am not making that by
editing a capped file at the margin.

**Two more belong to another lane's surface:** `the named hole: 442 keys / 455 rows` and `residual measure
under the correct identity` (`2,600 / 3,486 / 69,773`) quote `AGENTS.md`'s adult section and its evidence file,
which q3 is actively editing. Stepping on it unasked is how two lanes landed the same contradiction last week.

**Eight remain as ordinary next slices**, none needing a capped-file rewrite to be decided: `debug APK needs
no secret`, `no signed artifact has ever been produced`, `the filter shape is measured, never assumed`,
`MovieBox is metadata + trailer evidence, not playable`, `no playable print is resolvable from this host`,
`app: arm64-excluded suites are invisible here`, and the two signing-history pins if the supervisor wants them
converted rather than tolerated.

## 6. CI

A lane cannot know its own run id at commit time: the run is created by the push. Read it from the anonymous
API after pushing — `GET /repos/rehanradd/radd-stream/actions/runs?per_page=…`, filter on `head_sha`, then
`/actions/runs/<id>/jobs` for step conclusions — which is also how the supervisor verifies it without taking my
word. The suite that matters for this change is `🧪 test_docs_invariants.py` — **step 33 of 49 on run
`41268935119`**, the last green read of the parent sha, and the step number is anchored to that run rather than
stated bare, because I have already published one stale step count today. If any of the three new literals is
wrong, that step is where it shows, and the failure message names the label and the file.

**Not done, by rule:** no gate to trunk by this lane, no tag, no release, no service restart, no production DB
write, no credential read or print, no local Gradle, no local test module, no force-push, no `git add -A`, no
re-push of `q5-verdict-keys-on-c2528e1`. `.exists()` probes (8 sites) and the five production-read money items
stay frozen pending the fleet decision.
