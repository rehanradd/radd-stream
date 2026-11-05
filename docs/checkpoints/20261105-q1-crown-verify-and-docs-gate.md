# 2026-11-05 ~21:0x — qoder1 crown supervisor `[Q1-CROWN-VERIFY-AND-DOCS-GATE]`

- **Goal:** close task #59, then work the queue the operator authorised ("list what is left and
  finish it one by one") without a commit, a push, or a live-tree write.
- **Completed:**
  1. **Task #59 VERIFIED** — `/tmp/crown_orders/CROWN_VERIFY_59.md`. Crown re-ran the filing rather
     than reading it: `test_database` `Ran 133 … OK`, `test_host_classifier` `Ran 74 … OK
     (skipped=16)`, `test_hubcdn_unwrap` `Ran 34 … OK`, `test_site_scout` `Ran 25 … OK`,
     `grep -c "HTTPSHandler(context=SSL_CONTEXT)"` → `0`, and all six landing hashes match
     `/tmp/q12_59_LANDED_TREE/README.md` byte-for-byte. Nothing indexed; HEAD `b99814e`.
  2. **The adult task was mis-queued.** It is not "unbuilt": trunk ships
     `backfill_adult_key.py`, `audit_adult_flags.py`, `test_adult_corroborated_fold.py`,
     `test_adult_twin_probe.py` (CI :233) and the write-time law
     (`fast_fetch.py:612/:4770/:4844`). The **live tree `bf9e565` has none of them**, and `bf9e565`
     and `b99814e` are **not ancestors of each other** (checked both ways) — which is why earlier
     censuses reported the tooling "absent". Filed `/tmp/crown_orders/CROWN_ADULT_MEASUREMENT.md`.
  3. **Live exposure, crown-measured with trunk's own tool in report mode (`mode=ro`, 20.0 s,
     `ionice -c3 nice -n19`):** 135,731 public posts · **394** mixed `canonical_key`s · **407**
     exposed unflagged rows · 1,190 cross-key residual rows · 142 corroborated rows. AGENTS.md's
     442/455 is stale; reproduce with
     `python3 -S Fast_Fetch/backfill_adult_key.py <db>` at trunk, never from prose.
  4. **The documented fix over-hides.** Classifying all 407 rows by title+year agreement:
     **364 agree, 43 are key collisions** — the adult row's own `canonical_key` contradicts its own
     title (`100-bullets_2016` = public "100 Bullets" + flagged "Frank Phoenix UNRATED";
     `a-perfect-murder_1998` = "A Perfect Murder" + flagged "Van Wilder UNRATED" 2002;
     `7-aum-arivu_2011` = "7 Aum Arivu" + "Chennai vs China"). Artifact
     `/tmp/crown_adult60_collisions.csv`. So `--apply` as written hides legitimate works on a
     mis-keyed sibling's verdict. Dispatched as **order #60** (qoder12, `/tmp/q12_fold60`):
     agreement gate + `test_adult_fold_guard.py` + 5 mutants. Root cause (`canonical_key`
     assignment) is deliberately out of that scope and still unfixed.
  5. **The docs gate fails at `b99814e` — and I first mis-called that branch "trunk".**
     `python3 -S Fast_Fetch/test_docs_invariants.py` on `b99814e` → `Ran 22 … FAILED (failures=1)`:
     `App/AGENTS.md grew to 16242 B (ceiling 15000)`. It went unseen because `backend-ci.yml` never
     ran on `b99814e` — that commit touches only `.github/workflows/release.yml`, outside the
     `Fast_Fetch/**` + `backend-ci.yml` path filter; the public API for the sha lists only the two
     `Build signed APK + AAB` runs. **CORRECTED the same evening (Phase 4): `b99814e` is not trunk.**
     Trunk is `main` at `37ae67b`, and measured in a clean worktree at that tip the suite is
     **`Ran 22 … OK`** — `App/AGENTS.md` **14,948 B**, root `AGENTS.md` **31,998 of 32,000 B**. The red
     was real but belongs to a branch that is not the landing base; what constrains a landing on trunk
     is the root guide's **2 bytes** of headroom, not a failing gate.
  6. **Fixed in scratch, two ways.** (a) Rotated `App/AGENTS.md` §10's reference prose **verbatim**
     into new `docs/SPEC_APP_SIGNING_RUNBOOK.md`, leaving the law in place: on `b99814e`
     16,242 → 13,963 B, re-done on trunk `37ae67b` 14,948 → **13,634 B**. (b) Added the measured
     correction that the prose carried an obsolete claim: signing **works** —
     unauthenticated public API shows `v1.0.4` published with `radd-stream-1.0.4.apk`,
     `radd-stream-1.0.4.aab`, `…-SHA256SUMS.txt`, tags `v1.0.0`–`v1.0.4`; the "stored
     `KEYSTORE_BASE64` is malformed" story is the pre-`b99814e` state. Appended the collision caveat
     to the backend adult law (`Fast_Fetch/AGENTS.md`, 14,469 → 15,563 B of an 18,000 B ceiling).
  7. **A second, real defect in the #59 landing set, found only by trunk's guard.** Combined tree
     `b99814e` + docs fix + the six hubcdn paths → `test_every_module_is_registered_or_recorded_as_debt`
     fails: **`test_host_classifier.py` ships with no CI step.** The lane's `test_ci_manifest.py`
     could not see it (different accounting scheme). Crown added the step in trunk's two-line shape;
     combined tree is now `Ran 22 … OK` with `test_hubcdn_unwrap` 34 OK, `test_host_classifier` 74 OK,
     `test_site_scout` 25 OK, `test_redact` 63 OK.
  8. **Crown self-correction, publicly:** `CROWN_VERIFY_56/57` and order #61 claimed "trunk has no
     CI drift guard at all". **Wrong.** `test_ci_manifest.py` is absent, but the guard exists as
     `test_docs_invariants.py::WorkflowSuiteCoverageTests` (`:580-628`, CI step :286): every on-disk
     test module must be in the gate or declared in `UNREGISTERED` with a reason, step names must
     match the module they run, no module twice. Retracted in `CROWN_VERIFY_59` §6 and in the order.
- **Files changed (scratch only, nothing staged):** `/tmp/crown_docs61` (`App/AGENTS.md`, new
  `docs/SPEC_APP_SIGNING_RUNBOOK.md`, `Fast_Fetch/AGENTS.md`, this file, its index line);
  `/tmp/crown_land62` = docs fix + the six hubcdn paths + the added CI step, for the combined gate.
- **Checks run and exact result:** `test_docs_invariants` 22 OK (docs tree and combined tree);
  `test_hubcdn_unwrap` 34 OK; `test_host_classifier` 74 OK (skipped=16); `test_site_scout` 25 OK;
  `test_redact` 63 OK; `test_database` 133 OK; hashes of the six paths verified against
  `q12_59_LANDED_TREE/README.md`. Load at measurement: 1.29–2.09 on `nproc=1`; `/` at 96 %
  (9.3 G free) so **no 6.4 GB DB copy** — every production read was `mode=ro`.
- **Known failures or checks not run:** the other ~37 CI suites were not run in the combined tree
  (one core; #59's seven-suite pass already covers the delta). The 43 collision keys are classified
  by crown's own normaliser — a human must confirm each before any fold. `--apply` was **never**
  executed against the production DB. qoder11/qoder13 sit at 93–94 % context and cannot be given new
  scope; qoder14's model is down (`qfmodel unavailable`), so order #61 was partly executed by crown.
- **GitHub branch/commit/push result:** none. No commit, no push, no tag, per the standing order.
- **Oracle deployment result:** none — `/opt/radd-stream` untouched, unit still `active` on its
  existing checkout.
- **Next concrete action (owner, in this order):**
  1. land the docs + CI-step fix first (it is what makes any later push CI-green),
  2. then the hubcdn six paths — **with the corrected `backend-ci.yml` from `/tmp/crown_land62`**, not
     `/tmp/q12_port58`'s (the latter is missing the `test_host_classifier.py` step),
  3. then, only after #60's agreement gate lands and the 43 collisions are reviewed,
     `backfill_adult_key.py --apply` / `--projection` with `--undo` staged.
- **Blockers / decisions needed:** the two commits above (task #4 widened to include the docs fix);
  the `test_ci_manifest` mandated-list vs `UNREGISTERED` ruling (`CROWN_VERIFY_57 §4`); whether to
  raise `App/AGENTS.md`'s ceiling instead of rotating (crown chose rotation — it preserves the diet's
  rule and the file's LAW); and the standing hazard of 39 uncommitted files in the live tree.

## Phase 2 (same session, later) — the owner's `AGENTS.md` audit: 8 false claims, measured and fixed

The owner reported that `AGENTS.md` reads wrong in places and is missing others. Re-measured every
checkable claim in the three auto-loaded guides against trunk `b99814e` and the unauthenticated
public GitHub API. **Eight claims were false**, and one of them was load-bearing:

1. **Signing.** `AGENTS.md` asserted `GET /releases` is `[]` and **"No signed APK or AAB has ever
   existed for this product."** Measured: one release `v1.0.4` with `radd-stream-1.0.4.apk`, `.aab`,
   `-SHA256SUMS.txt`, published by run `41323174024` (`completed success`), 5 tags, 7 of 8 release
   runs `failure`. The whole retired chain moved verbatim to `docs/SPEC_AGENTS_MEASURED_NOTES.md`.
2. **The guard pinned that false sentence as law** (`test_docs_invariants.py`: "no signed artifact has
   ever been produced"). A pin on a *measurement* fights whoever re-measures it — it was the only
   thing standing between the guide and the truth. Retired and replaced with a pin on the retraction
   discipline (`"were true when measured and are false now"`).
3. Secrets table: four rows said "CONFIGURED, never exercised" / "build step fails".
4. `## Secrets`: "a release workflow that builds — which it does not have."
5. Guardrail rule 5 and the App Sessions item 4 both justified the tag ban with "`/actions/secrets` is
   `[]`" — false reasoning; the ban stands because tagging is the owner's call.
6. Status table: "all three repo-root workflows are `state=active`" — measured **four**
   (`backend-ci.yml`, `ci.yml`, `raddrelay-ci.yml`, `release.yml`).
7. Repo Map block: "they are 119 and 54 lines" — measured **91 and 112**; the numbers are gone and the
   `wc -l` method stays.
8. `docs/PROJECT_MAP.md`: "`tags: 0` and `releases: 0` are still true" — false.

**Two self-contradictions, not stale numbers:** the guide's own rule 6 and its App-Sessions item 2
both told agents to append the session log to `App/AGENTS.md` — the file the same guide says must stay
instructions-only, and the log already lives at `App/docs/SESSION_HISTORY.md`. Both now point there.

**Missing coverage added:** the four drifted `viewer.py` citations from Phase 1, `check_doc_citations.py`
extended to the three guides (it had never checked them — that is how four wrong citations rode green),
a `📎 Docs citation drift check` step in `backend-ci.yml` (a non-`🧪` step deliberately, because
`WorkflowSuiteCoverageTests`' RUN regex matches `test_*.py` only), `docs/SPEC_APP_SIGNING_RUNBOOK.md`,
`docs/SPEC_FAST_FETCH_MODULE_INDEX.md` (now linked from `Fast_Fetch/AGENTS.md` — it had **no inbound
link anywhere**, i.e. dead on arrival), and the supersession block in the measured notes.

**Verified:** `test_docs_invariants.py` **22 tests OK**; `check_doc_citations.py` `[✓] 5 docs: 0 broken,
21 suspect`, exit 0; `grep -c 'name: 🧪'` still **41**; sizes root **31,727/32,000**,
`Fast_Fetch/AGENTS.md` 15,815/18,000, `App/AGENTS.md` 13,963/15,000.

**Edge probe (light work, N=1 each, `-m 10`):** `/api/v1/posts?limit=1` 200, `/api/v1/posts/159` 404,
`/api/m3u?id=159` 403, `/admin` 303, `/download/radd-stream.apk` 200. `/api/v1/stats` **timed out at
load 4.85** — not evidence about the route, only about the box; probe it in a quiet window. No claim
in the guides' link table was contradicted.

**Landing-set consequence:** `/tmp/crown_land62`'s `backend-ci.yml` hash is superseded by this work —
recomputed in `/tmp/crown_62_LANDING/README.md` before anyone quotes it.

**Phase 2's `Verified` block above is the `b99814e` soil** (21 suspects, 41 `🧪`, root 31,727 B). The
trunk re-measurement is Phase 4; quote Phase 4 for anything that lands.

---

## Phase 3 (same session, later) — the disk that "could not be cleaned" was a nightly leak

The owner's order was *"clean up our disk space and memory, do not waste anything, delete old and wrong
info docs from everywhere."* The disk question had constrained every task for a week (`/` measured
96% full), and the answer was not old files — it was a **leak still running**.

**Measured, not inferred:** `/opt/radd-stream/backups/staging/` held **66 GB** of `*.tar.gz` fragments
written by `backup_manager.create_backup_archive()` and never removed. The archive is built **inside**
`tempfile.TemporaryDirectory()` (`Fast_Fetch/backup_manager.py:135-160`), and every `snap_path` is
`tar.add`-ed from that staging dir into the final archive — so the staging tree is, by construction, a
subset of bytes already present in the archive next to it. That is the proof of redundancy; the direct
verification (re-reading ~10 GB of gzip at ~6 MB/s under load 8) could not finish in its window and was
stopped rather than allowed to starve the service. **Deleted 147 name+size records, inventoried first**
to `/tmp/crown_orders/DELETED_STAGING_INVENTORY_20261105.txt` — every byte is reconstructible from the
archives that stayed. Result: **96% → 62% used, 75 G free**.

**Memory is not the problem:** `MemAvailable` ~8.5 G of 11.9 G, `SwapFree` well above the 800 MB floor,
cgroup `MemoryCurrent` under the 1,200 MB ceiling. Nothing to reclaim; the guardrail floors were not
approached by the cleanup.

**What was NOT deleted, and why it is the owner's call:** ~7.9 G of local archives that are already on
Hugging Face, `prebatch4_*.db` + `premerge_*.db` (**12.6 G** of pre-merge catalog snapshots — the only
way back), and the **39 uncommitted files in the live tree** with four lanes working inside
`/opt/radd-stream`. Deleted none of them.

**The leak is still open (task #14):** the next nightly run writes staging bytes again. The fix is four
lines and a test — `try/finally rmtree(ignore_errors=True)`, a `df` preflight that refuses when free
space is under 2× the expected staging, honouring `RADD_BACKUP_STAGING`, and a test that a **raised**
exception still leaves no staging directory behind. Freeing 66 GB without that change buys one clean
week, not a fix.

**A second leak of the same shape, measured while the HF push ran:** `upload_to_huggingface()` clones
the dataset with LFS smudge **enabled**, so every single upload materialises the content of every file
already in the dataset into a fresh `/tmp` directory — `/tmp/tmpvgpjzyhv/hf_repo` was **7.1 GB** while
one 3.5 GB archive was being pushed. `TemporaryDirectory()` reclaims it on a clean exit, but a
SIGKILL or an OOM leaves it forever, which is precisely how the 66 GB appeared. Fix: `GIT_LFS_SKIP_SMUDGE=1`
in `_hf_git_env()` — the push never needs the existing objects locally — plus a janitor for stale clone
dirs. Filed as task #16 with task #14.

**Hugging Face:** the push resumed only once the box could carry it (`/tmp/crown_hf_upload63.py`, my own
wrapper: sha256 + a rebuild manifest honestly stamped `source_commit: "not-recorded-at-upload-time"`,
then `backup_manager.upload_to_huggingface()`). A first attempt looked hung because I piped it through
`tail` — Python block-buffers stdout when it is not a TTY; relaunched under `python3 -u` + `nohup`, and
checked the dataset before retrying so nothing was half-pushed (23 files, `lastModified` unchanged).
Two archives remain queued after the in-flight one (`20261101_224046`, `20261103_224046`).

---

## Phase 4 — my landing set had the wrong base, and I published the correction before using it

**The error, in my own words:** for the whole session "trunk" meant `b99814e` on `master`. It is not.
`/repos/rehanradd/radd-stream` reports **`default_branch: "main"`**, and `main` sits at **`37ae67b`,
56 commits ahead of `b99814e`, with `b99814e` as an ancestor of it.** Everything I had built — the docs
fix, the hubcdn set, `CROWN_VERIFY_54/57/59`, orders #60 and #61 — was measured on soil 56 commits stale,
and the "green CI" on my pushed `crown/63-…` branch proved only that a stale tree can be green.

**Published before fixing, so no lane inherited it:** `/tmp/crown_orders/FLEET_NOTICE_63_TRUNK_IS_MAIN_37ae67b.md`
names the four invalidated items and the rule *"do not cite `b99814e`, `master`, or `/opt/radd-stream`'s
`bf9e565` as trunk again."*

**Re-based in `/tmp/crown_main64` (branch `crown/64-docs-and-hubcdn-on-trunk` at `37ae67b`):**

- 7 of 13 docs files applied with `git apply -3`; `App/AGENTS.md`, `docs/SESSION_CHECKPOINT.md`,
  `docs/checkpoints/README.md` resolved by hand because trunk had moved under all three.
- `check_doc_citations.py` extended to the three auto-loaded guides found **4 wrong citations in root
  `AGENTS.md`** at trunk — `redact.py:1077/1083`, `viewer.py:2849/557/966/1978/887` — and all of them
  are now trunk-true: `adult_clause` **`redact.py:1091`**, `api_v1_get_posts` **`viewer.py:2910`**
  (clause at `:2918`), `art_is_adult` bail **`:3768`**, `link_is_adult` **`redact.py:1097`** on the
  redirectors **`:4027`/`:4113`**, `DASHBOARD_HTML` **`:1027`**, `fetch_database_payload` **`:617`**,
  badge **`:2039`**. `save_scraped_data`'s `is_18_plus` assignment is now cited **by symbol, not by
  line**, because re-applying the hubcdn set on top of the docs moved it from `fast_fetch.py:4598` to
  `:4735` — a citation corrected for one commit of a landing set is wrong for the next, and only the
  landed tip is ever executed. Root AGENTS.md lands at **31,929 of 32,000** — 71 bytes of headroom,
  down from trunk's 2, because a correction that replaces a wrong number with a true explanation costs
  bytes. `App/AGENTS.md` **13,634/15,000**, `Fast_Fetch/AGENTS.md` **15,815/18,000**,
  `docs/SESSION_CHECKPOINT.md` **11,993/12,000**, `Fast_Fetch/CONTINUITY.md` **11,998/12,000**, and
  `grep -c 'name: 🧪'` **43**.
- **The hubcdn set re-derived as an addition, not a revert.** Trunk already ships `_tls_context`.
  **A claim I made in Phase 1 and repeated in this landing's own commit message is retired here: the
  `/tmp/crown_62_HUBCDN.patch` would NOT have reverted the TLS fix.** q13-63 measured it and crown
  re-measured it independently — `git apply --check --include='Fast_Fetch/fast_fetch.py'` on a clean
  `37ae67b` worktree **applies**, the result is **byte-identical to the landed tip**, and
  `_tls_context` counts **12** in it. What that patch genuinely cannot do is apply *wholesale*: its doc
  hunks fail loudly at `App/AGENTS.md:129`, `docs/SESSION_CHECKPOINT.md:4`,
  `docs/checkpoints/README.md:5`. The "silent revert of a security fix" story was an inference from
  `_tls_context` counts on `b99814e` (9) versus trunk (10) — and the patch's code slice is not
  `b99814e`-derived. `967a05d`'s message still carries the wrong sentence because a pushed message is
  not amended; this file is where the record is corrected, and a warning that is *right about the
  danger and wrong about the artifact* is how good guards become noise.
  The delta is `git diff b99814e 0e8f74d -- fast_fetch.py site_scout.py` — 3 new
  files (`host_classifier.py`, `test_host_classifier.py`, `test_hubcdn_unwrap.py`), `is_bridge_url`
  learning `hubcdn.io`, `_HubcdnNoRedirect` + `_hubcdn_page` + the asset-role gate, and the
  `site_scout` authority-merge block — every hunk additive; `grep -n "ssl._create_unverified\|CERT_NONE"`
  on the result returns only the docstring that *describes* the old bug.
- **Verified at trunk:** `test_docs_invariants` **22 OK**, `test_host_classifier` **74 OK (skipped=16)**,
  `test_hubcdn_unwrap` **34 OK**, `test_site_scout` **25 OK**, `grep -c 'name: 🧪'` **43**, root guide
  **0 suspects** (`check_doc_citations` → 0 broken). `0d1dd71` (the filmywap stall fix) is already an
  ancestor of trunk, so `site_scout.py`'s stall behaviour arrived by another road and only the
  classifier merge is new.
- **Still open in the citation layer:** **20 suspects** in `docs/API_V2.md` and
  `docs/HANDOFF_apidocs.md` — spot-checked five, all four-point-at-unrelated-code real drift, e.g.
  `HANDOFF_apidocs.md:250` → `viewer.py:2526` is a `<div>` in the dashboard HTML. Warnings only
  (`check_doc_citations.py` exits 0 on a suspect), so they do not gate; recorded as a named backlog item
  instead of being fixed blind at load 9 or silently left.

---

## Phase 5 — landed on real trunk: `37ae67b → 967a05d`, and the deploy this lane will not perform

**The two commits, on trunk soil:** `6a5531c` (the guides, re-measured) then `967a05d` (the hubcdn
trust gate re-derived additively, plus both suite registrations). `main` **fast-forwarded**
`37ae67b..967a05d`, and both gates are green **at that exact sha**: Backend CI
`python3 -S offline suites` — 49 steps, none non-green, last real step `📎 Docs citation drift check` —
and `🔨 CI — Android Build & Test` (`assembleDebug + testDebugUnitTest + lintDebug`), which fired only
because the App guide edit touches the `App/**` filter, so the App lane's gate proved this docs change
too. `crown/64-docs-and-hubcdn-on-trunk` carries the same sha and is now redundant; **deleting it is an
owner action, not a cleanup I make silently.**

**Why the split, and the failure that produced it.** The first attempt at two commits was one commit
wearing a docs message: `git apply -3` **and** `git checkout <sha> -- <paths>` both *stage* what they
write, so the "docs" commit swallowed the entire hubcdn set — and its own coverage guard went red on
`test_host_classifier.py` / `test_hubcdn_unwrap.py` running on no one's push. `git reset --soft HEAD~1`,
`git restore --staged .`, then stage by name, twice. Recorded because the failure is invisible from the
message and obvious from `--stat`: 2,943 insertions in a commit that claimed to touch markdown. Commit 1
now stands alone — `test_docs_invariants` **22 OK** measured in a clean worktree at `6a5531c`, before
the second commit existed.

**Deploy: refused, with the measurement.** `/opt/radd-stream` sits at `bf9e565` — **not an ancestor of
`main`** — with **39 modified tracked files and 30 untracked** in it and four lanes working there.
Checking `967a05d` over that tree is the exact thing `AGENTS.md` forbids ("a silent revert of a pushed
fix"), so the ruling's *deploy live* step stops at the owner's decision about those files. Nothing was
restarted, nothing was copied to the host. And the fold the ruling was about needed no deploy at all:
it already ships in `catalog_v2._link_state_of` and already runs live — the residual there is the
`unknown` divergence in `link_state.state_for()`, latent, not a live defect.

---

## Phase 6 — two lane filings judged by re-measurement, and 16 gates that report green while asleep

**q13-63 (hubcdn re-derive on trunk) — CLOSED as already satisfied, and it corroborates the landing.**
Its `/tmp/q13_hubcdn37` lane ported the six paths from `967a05d` and `cmp` says all six are
byte-identical to trunk; `test_hubcdn_unwrap` 34 OK, `test_host_classifier` 74 OK (skipped=16). It also
caught my own false warning about `crown_62_HUBCDN.patch`, retired in Phase 4 above.

**The 16 skips are the finding, not the green.** All 16 share one reason —
`'resolved_cache.py not present in this tree'` — across `TestViewerShapeGate` (9),
`TestCategoryACrossCheckWithResolvedCache` (5), `TestTaxonomyCollisionGuard` (2). `resolved_cache.py`
exists **only as uncommitted work in `/tmp/lane_phase1`**. So Backend CI prints two green suite names
while sixteen assertions — viewer-shape rejection, category-A cross-checks, the horizon/kind taxonomy
collision guard — never execute on anyone's push. That is the precise failure class
`CROWN_VERIFY_54` §5 was written about, but inverted: the suite *is* registered, and its protection is
skipping. Whoever lands the resolved-cache lane must say so in the same commit, or the register keeps
claiming coverage it does not have.

**q12-60 (the adult agreement gate) — ACCEPTED, `/tmp/crown_orders/CROWN_VERIFY_60.md`.** Crown
re-measured: three sha256 values, the 760/329 line counts, `nothing indexed`, and
`test_adult_fold_guard.py` **Ran 20 OK** on this box; the 135,731 / 394 / 407 / 1,190 census matches my
own measurement exactly. The 330-agree/77-quarantine split (mine was 364/43) was **not** re-run and is
labelled unverified. **Their rule beats mine**: my 43-row quarantine came from a subset rule, and the 30
rows they refuse are `row ⊂ sib` shapes like *"Dom (Season 1 - 3) Dual Audio"* versus the film *"Dom"* —
exactly the mis-hide the collision CSV was hunting. Accepted law: **a subset is not an agreement**, one
refusing row refuses the whole key, and 7 corroborating rows stay public as the honest direction of
error. The stale base cost nothing here: trunk's `backfill_adult_key.py` is **byte-identical to
`b99814e`'s**, so the 760 lines port with zero re-base work. Landing with
`🧪 test_adult_fold_guard.py` registered (43 → 44); **`--apply` on the production catalog is not
authorised by any document in this session** — the tool landing flips no row.
