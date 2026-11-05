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
  5. **Trunk's own docs gate fails at trunk tip.**
     `python3 -S Fast_Fetch/test_docs_invariants.py` → `Ran 22 … FAILED (failures=1)`:
     `App/AGENTS.md grew to 16242 B (ceiling 15000)`. It went unseen because `backend-ci.yml` never
     ran on `b99814e` — that commit touches only `.github/workflows/release.yml`, outside the
     `Fast_Fetch/**` + `backend-ci.yml` path filter; the public API for the sha lists only the two
     `Build signed APK + AAB` runs. **So "Backend CI is GREEN" in AGENTS.md certifies `f0c1ca3`, not
     trunk tip — and any landing that touches `Fast_Fetch/**` (task #4 does) would trip this red.**
  6. **Fixed in scratch, two ways.** (a) Rotated `App/AGENTS.md` §10's reference prose **verbatim**
     into new `docs/SPEC_APP_SIGNING_RUNBOOK.md`, leaving the law in place: 16,242 → **13,963 B**.
     (b) Added the measured correction that the prose carried an obsolete claim: signing **works** —
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
