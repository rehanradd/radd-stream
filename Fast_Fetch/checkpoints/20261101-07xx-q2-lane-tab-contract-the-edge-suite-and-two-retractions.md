# 2026-11-01 07:xx — q2 lane `[Q2-TABCONTRACT-RETRACTIONS]`: the tab contract lands, the edge suite is its own CI step, and two of my own prose claims are withdrawn

**Lane:** q2 (`/tmp/q2_admin_auth`, branch `q2-admin-auth-upgrade`).
**Base:** merged trunk `c2ae2bf` (both refs) → head after this session `f50d74b` + the commits on top.
**Machine state obeyed:** LIGHT ONLY (q1's published rule: two sustained sub-4 windows + `cpu some
avg10 < 50%` + hard floors). **No test module was executed in this session**, no crawl, no merge, no
Gradle, no production read. Everything in the two new suites is judged by the hosted runner, which
costs zero seconds of this VM.

---

## 1. #30, the half that is actually bounded: the tab strip's contract

`DASHBOARD_HTML`'s two main tabs were inline `onclick="switchMainTab('db')"` handlers that toggled one
CSS class. The strip therefore claimed nothing and mislabelled nothing — which is not the same as being
safe: the increment here *adds* a claim (`role="tablist"`, `aria-selected`, arrow keys), and a claim the
code does not keep is worse than no claim, because it changes what a screen-reader user expects the page
to answer. So markup and behaviour landed together and the guard landed with them:

- Markup: `role="tablist"` + accessible name; `role="tab"` with `aria-selected` and `aria-controls` per
  button, `tabindex="-1"` on the unselected one; `role="tabpanel"` + `aria-labelledby` on both sections.
- Selection now routes through the page's delegated `ACTIONS` map as `switch-tab` (`viewer.py:1551`), the
  route every other button already takes. The map's lookup is `Object.prototype.hasOwnProperty`
  (`viewer.py:1556`), so an unknown `data-action` is a no-op rather than a prototype property.
- `switchMainTab` (`viewer.py:1586`) moves `aria-selected` and `tabIndex` **with** the paint instead of
  only toggling `.active`; a `keydown` listener (`viewer.py:1564`) answers `ArrowRight` / `ArrowLeft` and
  focuses the tab it selects.
- **No new sink.** The markup is literals only — no `${}` anywhere in the tab strip — so this touches
  neither the escape contract nor `Fast_Fetch/INTERPOLATION_SINK_INVENTORY.md`.

`test_html_escape_guard.py` gains `TabSurfaceTests` (5 cases): panel named by `aria-controls` exists on
the same page; the paint moves the ARIA state; the tablist answers the keys it announces; every action
the markup asks for has a handler in the map; and a positive control proving the detector has something
to look at (`tab_buttons` returns 2 on the real page and `[]` on the pre-fix spelling).

**One defect in my own new test, caught before commit and worth recording:** I first asserted that
`switch-tab` appears in `action_handlers_defined(...)`'s `used` set. `used` is a scan of the *script*,
and the tab buttons are static markup above it, so the assertion could only ever fail — and had I
"fixed" it by widening the scan, the check would have been about the wrong surface. The claim the
browser can actually break is *markup's action ∈ map's declared*, which is what it asserts now. Verified
statically against the shipped source (`viewer_page`/`page_script`/`tab_buttons`/`function_body`/
`event_listener`/`action_handlers_defined` loaded by `importlib`, definitions only): 2 tabs, both
`data-action="switch-tab"`, `switch-tab` in `declared`, `aria-selected` and `tabIndex` both in
`switchMainTab`'s body, both arrow keys and `switchMainTab` in the `keydown` handler, pre-fix control
still matching nothing.

**Deliberately not attempted** inside #30: badges, tooltips, and **account lookup**. Account lookup would
be a new data path over `Fast_Fetch/user_state.db` — q3's surface, holding unsalted `sha256:` key digests
per q1's 05:25 bounded read (`user_accounts=0`, `key_hash non-null=0`) — i.e. a prospective-credential
exposure that needs a scope ruling, not a dashboard widget.

## 2. #33: no skip was written, and none will be

The edge suite (`Fast_Fetch/test_public_edge_scenarios.py`, 22 cases A–H over real HTTP, registered as its
own `🧪` step in `b0add6b`) contains **zero** skips — re-checked this session:
`grep -rn "skipTest|@unittest.skip|skipIf"` over both new modules → no matches. Case B does not skip the
adult-reconciliation question; it asserts the mechanism with the repair call that is on trunk
(`fast_fetch.reconcile_key_adult`, returns the flipped-row count, asserted `== 1` on the fixture) and then
asserts the repaired twin answers **404**. That is a real assertion, which is the form q1 ruled.

What a unit test genuinely cannot assert is the *production-scale* `keys_both > 0`. That number lives in
the census, not in a suite: `keys_both = 0` in 24 of 25 staging vaults, `mp4moviez.db` has no
`canonical_key` column to compare on, so the 442 that root `AGENTS.md` carries is a **merged-catalog**
property and is not measurable from a vault — and the merged catalog is a production read, which is
frozen. Reconciling it against the ledger is `merge_catalogs.py` work (q3's lane), not a `WHERE` clause
and not something I can turn green here.

## 3. Two of my own claims, withdrawn — with the artifacts that kill them

I have been calling other lanes on confident prose; the same rule applies to me, so both claims are
retracted rather than restated with hedging.

**(a) "trunk's own gate is already red on `test_tiers.py:269`" — withdrawn, and it was never true of
trunk.** From the tree I would have run in, `git -C /tmp/q2_admin_auth rev-parse HEAD` =
`b0add6b…32682`; `git status --porcelain Fast_Fetch/test_tiers.py` = empty (unmodified); `grep -c coins
Fast_Fetch/test_tiers.py` = **0** in the working copy **and** 0 in `HEAD:Fast_Fetch/test_tiers.py`; line
269 is the fixture line q1 quoted (`"final_url": "https://cdn.example/a"`), not an `assertEqual`. No
failure block, no test-method name exists in this lane's transcript for that line on any ref I hold. The
only `coins`-named suite on this box is `Fast_Fetch/test_coins_engine.py`, which **landed on trunk at
`c2ae2bf` and is registered** (`backend-ci.yml:412-413`). So the most likely mechanism is mine and it is
exactly the failure mode I have criticised: a red associated with another lane's coins work — q1 scanned
120 worktrees and found the same zero I find in mine — got asserted as a property of trunk without ever
being pinned to a tree, a ref, or an output. Without those three it was not a measurement. Consequence:
the premise for the skip is gone, and the skip was never needed (see §2).

**(b) "trunk is 9 files past the documentation diet cap because of my own ingest" — withdrawn; the real
number is one file, 10 bytes.** The diet guard's caps are byte and line budgets, not file counts:
`ByteBudgetTests.CEILINGS` at `Fast_Fetch/test_docs_invariants.py:343` =
`{AGENTS.md: 32_000, Fast_Fetch/AGENTS.md: 18_000, App/AGENTS.md: 15_000}`, and
`test_session_logs_are_indexes_not_archives` at `:350-355` = 12_000 B and 120 lines for
`Fast_Fetch/CONTINUITY.md` and `docs/SESSION_CHECKPOINT.md`. `RotatedHistoryTests` only sets *floors*
(`≥ 10` files per rotated dir at `:364`, `≥ 20` `SPEC_*.md` at `:374`) — there is no file-count cap in the
diet guard at all, so "9 files past the cap" describes a check that does not exist.

Measured at trunk `c2ae2bf` (`git cat-file -s`), same numbers in my merged tree:

| file | size | cap | headroom |
|---|---|---|---|
| `AGENTS.md` | **31,990 B** | 32,000 B (`:343`) | **10 B** |
| `Fast_Fetch/AGENTS.md` | 14,469 B | 18,000 B | 3,531 B |
| `App/AGENTS.md` | 14,061 B | 15,000 B | 939 B |
| `Fast_Fetch/CONTINUITY.md` | 10,765 B | 12,000 B / 120 lines | 1,235 B |
| `docs/SESSION_CHECKPOINT.md` | 10,355 B | 12,000 B / 120 lines | 1,645 B |

The unwelcome part survives the wrong wording: **root `AGENTS.md` is 10 bytes from its ceiling**, and the
file is the one every lane is told to append measured notes to — the next sentence of prose is a red CI
step. That is a real finding and it is not mine to fix unilaterally: whose file it is, whether the ceiling
moves, and which paragraph leaves if it does is a ruling for the supervisor and the owner, so I am
reporting it and changing nothing. My own ingest in this session touched only `Fast_Fetch/CONTINUITY.md`
(one integer) and `Fast_Fetch/checkpoints/README.md` (one index line), both far under their caps.

## 4. Trunk movement, and the run-id citation I got wrong

`c2ae2bf` is not fast-forwardable from `653915c`, and force-pushing is not available to me, so I merged
trunk rather than re-branching: `f50d74b Merge commit 'c2ae2bf'`, with
`git merge-base --is-ancestor c2ae2bf HEAD` → **true** (trunk can FF onto this branch). The single
conflict was `Fast_Fetch/checkpoints/README.md`, where both lanes had prepended a newest-first entry;
resolved by keeping **both** entries verbatim in timestamp order via a deterministic marker filter — no
side was retyped, so no side was silently edited.

**Citation corrected:** the two numbers I quoted as green trunk runs (15890335555 / 15890335545) are not
run ids from `/actions/runs`; they came from a pane and I asserted them as identifiers. The trunk runs at
`c2ae2bf` are **41263022437 (main)** and **41263024947 (master)**, both `completed success`, attempt 1,
read from `/actions/runs?branch=`. Same rule I asked q5 for: an artifact and its scope, or say where the
number came from.

## 5. Census accepted over my own dispatch — recorded as q1's correction to q1

`81/186`, `186/1704`, `322/1563` (flag column `is_adult`, 25 vaults, `mode=ro`, merged catalog excluded
with a reason) supersede the dispatched `43 / 88 / 91`, which has no artifact on either side: q3 already
showed it was a pre-fold single-source count from a vault that is not on disk. My retraction over the
`91 − 43 = 48` reading stands for the same reason: those are different generations and `mp4moviez.db` has
no key to compare them on, so the subtraction is arithmetic, not a measurement.

## 6. Environment facts this session depended on

- `DBPATH_ACK /tmp/q2_admin_auth/Fast_Fetch/fast_fetch.db` — measured, not asserted: `env | grep -c
  RADD_DB_PATH` = **0** in the shell that ran everything here, and `python3 -S -c 'import config;
  print(config.DB_PATH)'` from the worktree resolves to **`/tmp/q2_admin_auth/Fast_Fetch/fast_fetch.db`**,
  a path that **does not exist** (`ls` → No such file or directory), which is the proof that nothing in
  this session created or wrote a catalog. No `bash -i` wrapper, no `export RADD_DB_PATH`, no `~/.bashrc`
  edit, no production symlink touched.
- `/tmp/tmpjbp1_4w9` — **untouched.** No delete, no large write. It is the backup-`hf` failure evidence
  (last good off-box snapshot Oct 31 05:13) and the owner's call.
- Freeze obedience: the only local executions were `ast.parse` on two files and static regex scans of
  repo text (`importlib` definitions-only load of the guard, `git cat-file -s`, `ls`, `grep`). No test
  module ran. If that counts as more than LIGHT, say so and I will move the checks to the runner.

## 7. What the next session must not re-derive

1. Read the hosted verdict on **`b0add6b`** (edge suite's first-ever execution) and on this session's
   pushed sha. Report the step's `Ran N tests` line. If a case is red, fix the code or name the defect
   with its owner and measurement — never soften an adult assertion, never add a skip.
2. #30's remaining halves (badges, tooltips, account lookup) need a scope ruling first for the
   `user_state.db` path; do not open it as a dashboard feature.
3. #37: the 19 unfunded staging vaults (4.3 GB, 73–366 CPU-minutes by the measured per-file rates) —
   check `sqlite_master` for a `canonical_key` index before launching; that single `PRAGMA` is what makes
   the rest cheaper or pointless.
4. Root `AGENTS.md` at 31,990 / 32,000 B: **any** append to it needs a paragraph removed in the same
   commit. Decide the ceiling or the eviction before someone discovers it as a CI failure.

## 8. The base moved twice more inside this session, and what that cost — recorded so the next lane
##    does not read §4's shas as the gated head

`f50d74b` (merge of `c2ae2bf`) and `37f5082` were the head I pushed and CI-judged *first*; the verdicts
below are theirs and they are real: **run 41262497585 at `b0add6b`** → step 37
`🧪 test_public_edge_scenarios.py` **success** on its first-ever execution, step 41 `🧪 test_accounts.py`
**failure**, and **run 41264880812 at `37f5082`** → `completed success` with steps 37/41/42/44 all green.
`test_accounts.py` is byte-identical at `4b025bf`, `c2ae2bf` and my head (`git rev-parse
<ref>:Fast_Fetch/test_accounts.py` = `7d189b0c…` in all three) and its lockout tests inject `now=` rather
than reading the clock, so the `b0add6b` red is **not reproducible on identical inputs** and I could not
read its log: the annotations API returns only `Process completed with exit code 1` (annotation
`start_line 102`, no test name), and `/actions/runs/{id}/logs` needs a token this lane does not have. It
is q3's module, it went green twice on the same content, and I am reporting it as a runner-side unknown
rather than a cause.

Then trunk moved to `c2ae2bf` → `c2528e1` (q3's premerge-plan docs) with the instruction to re-branch.
**A re-branch is not something I can do to the existing ref:** `q2-admin-auth-upgrade` already carries the
merge of `c2ae2bf`, and rewriting it onto `c2528e1` would be a force-push, which is barred. So the replay
went onto a **new ref, `q2-admin-auth-c2528e1`**, by `git cherry-pick -x` of exactly my five non-merge
commits (`--right-only --cherry-pick` proved none of them were already in trunk), leaving
`q2-admin-auth-upgrade` at `37f5082` as history — **gate on the new ref, and do not land the old one**;
deleting the stale ref is the owner's call, not mine.

What that cost, honestly: two `checkpoints/README.md` conflicts and one `CONTINUITY.md` conflict, all the
same shape (two lanes prepending a newest-first line, plus the archive integer). One of my resolutions was
**wrong and I caught it before pushing**: my first sorter treated the picked side and the base side
backwards and its timestamp regex could not match the index's `05:xx` spelling (`\d{2}:\d{2}` does not
match `xx`), so it silently sorted my entry above q3's newer one and put `06:xx` after `05:xx`. Fixed by
swapping the two adjacent entries back and re-checking for duplicates (`none`), and the integer was taken
from the listing the guard counts, not from arithmetic — as §7 of this file already said to do. Static
re-check of the final tree: `CONTINUITY` claims 70 / listing holds 70, `docs/SESSION_CHECKPOINT.md` 60/60,
newest checkpoint indexed, `steps == runs` at 42 with no duplicate, no undeclared module and no stale debt
row, no conflict markers in any changed path, and both tab-strip detectors still matching the real page.

**Second near-cap file, found by the same measurement, and it is not mine either:**
`docs/SESSION_CHECKPOINT.md` is now **11,941 B of a 12,000 B cap** and **112 of 120 lines** (cap at
`Fast_Fetch/test_docs_invariants.py:352-355`) after trunk's own `c2528e1` append added 24 lines to it.
So the diet guard has *two* files within one screenful of failing — root `AGENTS.md` at 10 B of headroom
and this at 59 B and 8 lines — and both will be hit by ordinary appends rather than by misuse. Reported,
not edited: `docs/SESSION_CHECKPOINT.md` is q3's file and root `AGENTS.md` is nobody's to trim silently.
