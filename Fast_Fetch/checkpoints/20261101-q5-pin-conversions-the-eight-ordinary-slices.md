# 2026-11-01 — q5 backend lane `[Q5-PIN-SERIES]` the eight ordinary pin conversions, one pin per slice

Session: q5 (account5), worktree `/tmp/q5_gate5`. Muse 09:03: gate **HELD** (qoder1's write credential is dead,
owner-only fix), so nothing is gated by this lane and the stack is not replayed yet; continue the **eight
ordinary `INVARIANTS` conversions, one at a time**, own worktree only, CI-verifiable, push each slice branch and
report its sha. Do not rewrite `AGENTS.md` to fit a pin (10 B headroom). No merge, tag, restart, production
read or write; no Gradle at load ≥ 4.

This file is the rolling record for that series — **one file for eight slices, deliberately**, so the archive
count moves once rather than eight times. Each slice adds a section; nothing earlier in it is rewritten.

## The rule this series runs on

A conversion re-points a pin from a **value** to the **clause in the same sentence that makes the value
non-load-bearing**, and it may only target a clause that *already exists* in the document. No doc gets edited
to fit a pin, because root `AGENTS.md` has 10 bytes of headroom against its 32,000 B ceiling and `App/AGENTS.md`
939 B against 15,000 B — "write new law so the pin has something to bite" is not available at the margin, and
refusing it is the difference between a docs tidy and a lane editing the constitution to match a test.

Every slice re-derives, by importing the guard rather than grepping it: `len(INVARIANTS)` (104), zero missing
phrases, zero duplicate labels, the byte sizes and line counts of the capped docs, and the two archive-count
claims against their directory listings. Grep is the method that produced the "98 entries" error in the
previous checkpoint; it is not used here.

## Slice 1 — `measured: secrets list is empty` → "so it is a real answer and not a permission artifact"

**Branch:** `q5-pin-s1-secrets-empty-20261101`, stacked on `19b4a5f` (which is stacked on `c0e86e5`, which is
stacked on trunk `c2528e1`). Stacking is deliberate: gate order is qoder1's at gate time, and a chain replays in
one command while eight sibling branches replay as eight merges against a file every one of them edits.

**What it pinned:** `{"total_count": 0, "secrets": []}` — a literal HTTP response body from
`GET /repos/…/actions/secrets` measured 2026-10-29, in a paragraph that `63396c1` and the
`**UPDATE (Measured 2026-10-30 22:53, then re-measured 2026-10-31 07:5x)**` block in the same section have
since overturned: all four keystore secrets are configured now. So the guard was holding
up a *retired blocker* — the worst shape of state pin, because a lane that corrected the prose would go red,
and a lane that left it alone would keep a false sentence guarded.

**What it pins now:** "so it is a real answer and not a permission artifact" — the reading rule the same
sentence exists to teach. The old paragraph's whole argument is that an empty list is only evidence once you
know the reader's repo permissions (`{admin: true, push: true}` there). That clause does not rot when GitHub's
secret list changes, and it is the part that generalises to the next "the API says zero" claim anyone cites.

**Checked, not assumed:** the candidate clause was verified present verbatim in `AGENTS.md` before the edit,
and verified **not** already the target of another `ROOT_AGENTS` pin — the overlap test is not substring
containment, because this series nearly fooled me twice: `no signed artifact has ever been produced` looked
free to convert onto "no agent may create, move or delete a tag", but that is the *second half of a sentence
already pinned by its first half* (`cutting and moving tags is owner-only`), so the conversion would have added
a duplicate and removed a value. That candidate is dropped; slice 3 takes a different clause.

**Trade, stated:** nothing now fails if the empty-list measurement is deleted or reworded out of `AGENTS.md`.
The measurement stays there as dated history (`Measured 2026-10-29 17:55`), and the guard keeps the *reason it
was believable* — which is the part worth keeping.

## Slice 2 — `release died at the signing preflight` → moved subject, and a live doc defect found on the way

**Branch:** `q5-pin-s2-release-preflight-20261101`, stacked on slice 1 (`011d973`).

**This is the one the series rule was for.** The 20261031 audit prescribed, for this pin, that the sentence
*around* the run outcome should be pinned — "That preflight is why exercising this is safe". That clause is
present in `AGENTS.md`, so a mechanical conversion would have landed green. And it is now **false**:
`SPEC_AGENTS_MEASURED_NOTES.md` records run `41104217171` clearing `🗝️ Verify signing secrets are present`, so
the preflight no longer stops anything. Pinning it would have made the gate an accomplice to a safety claim
that expired — a guard that bites hardest on exactly the sentence that must not be trusted.

**What the pin became instead:** label `a red release run is read from the job log, not the summary`, file
`docs/SPEC_AGENTS_MEASURED_NOTES.md` (new constant `MEASURED_NOTES` beside `ADMIN_DOC`), phrase "read the job
log, not the summary" — the live reading rule in the file that actually holds the release-run history. This is
a **subject change, not a phrase swap**, and it is declared rather than smuggled: the guard no longer promises
anything about the 2026-10-29 run outcome, and never promises what the next release run will do.

**Eligibility checked, not assumed:** a pin target outside `AUTO_LOADED` must be named in `CONTINUITY.md` or
`docs/SESSION_CHECKPOINT.md` (`test_every_invariant_target_is_reachable_from_the_loaded_indexes`); `docs/**`
maps to an empty holder in that test, so `SPEC_AGENTS_MEASURED_NOTES.md` was verified to appear in the needles
before the pin moved. Precedent for a `docs/` pin target already exists (`docs/ADMIN_PANEL_ACCESS.md`, 2 pins).

**The finding this conversion produced, for the supervisor and not for me to fix:** `AGENTS.md`'s signing
section still says dispatching the release workflow is safe *because the preflight stops it*. It does not stop
it any more. Today nothing publishes anyway, because every release run dies later — at the unit-test gate or at
`App/app/build.gradle.kts:120` (`Last unit does not have enough valid bits`, the stored `KEYSTORE_BASE64`
padding) — during *configuration*, before any artifact exists. But that safety is now an accident of a broken
secret, and the moment the owner re-enters `KEYSTORE_BASE64` correctly, a `workflow_dispatch` on
`🚀 Release — Sign & Publish APK + AAB` would be stopped by nothing except the standing orders (no tag, no
release publication, no restart). Two consequences:
  1. the sentence should be corrected — and the corrected form is **longer** than the original, so it cannot
     go in at 10 bytes of headroom; it needs bytes freed elsewhere in `AGENTS.md`, which is a fleet decision;
  2. until it is corrected, treat "exercising the release workflow is safe" as **not** available to any lane:
     the rule that protects the artifact today is the owner's order, not the preflight.
Named here, escalated, and **not** worked around: no `AGENTS.md` byte edited, no workflow dispatched, no tag.

## Slice 3 — `no signed artifact has ever been produced` → "the owner's key is the only correct one"

**Branch:** `q5-pin-s3-owner-key-20261101`, stacked on slice 2 (`4fa35e0`).

**What it pinned:** "No signed APK or AAB has ever existed for this product" — an *event-expiring* sentence.
It is true right now, it goes false on the first successful release, and it never comes back. A pin like that is
a countdown to its own deletion, and the deletion is the moment a lane is least expecting a red build.

**What it pins now:** the identity rule from the same paragraph — "the owner's key is the only correct one", the
clause that carries the *reason* a replacement keystore is not a workaround: a different signing key makes every
later upgrade incompatible with the first install. That sentence does not expire when the first artifact ships;
it is the one a lane under "just produce an APK" pressure actually needs to hit.

**The argument the code comment refers to — when is a same-sentence pin a duplicate, and when is it coverage?**
Slice 3's first candidate was "no agent may create, move or delete a tag", rejected because the guard already
pins "Moving or re-cutting a tag is an owner action" — those are the **same obligation worded twice**, so the
new pin would add tax and zero coverage. What landed is different in kind: `do not generate a replacement
keystore to work around it` is a **prohibition**, and `the owner's key is the only correct one` is the **reason
for it**. Two propositions that reword apart — the ban can be paraphrased while the reason stands, and the
reason can be re-justified ("there is an installed base now") while the ban stands — so each pin can fire
without the other. The test I apply is not "is it the same sentence" but *"can one half be edited while the
other stays true"*; if it cannot, the pin is a duplicate.

**Checked, not assumed:** candidate clause verified present in `AGENTS.md` (`flat()` comparison, as the guard
does), no existing pin phrase equal to or containing it, `len(INVARIANTS)` unchanged at 104, zero missing
phrases, zero duplicate labels. No `AGENTS.md` byte moved; `App/AGENTS.md` and `Fast_Fetch/AGENTS.md` untouched
in this slice too.

**Recount after this slice, derived by importing the guard:** 6 of 15 converted (the three from the 08:30 slice,
plus slices 1–3 here), 10 audit labels still present, of which 1 is the deliberate requirement pin
(`app lane: signed release needs the 4 secrets`) → **9 still pinning state**: 2 held for a supervisor decision
(`one vCPU`, `backend is the running system`), 2 held on qoder3's adult-flag surface, and **5 ordinary left**
(`debug APK needs no secret`, `the filter shape is measured, never assumed`, `app: arm64-excluded suites are
invisible here`, `MovieBox is metadata + trailer evidence, not playable`, `no playable print is resolvable from
this host`).

## Slice 4 — `debug APK needs no secret` → "the debug build needs no secrets"

**Branch:** `q5-pin-s4-debug-apk-20261101`, stacked on slice 3 (`23d1558`). Supervisor ruling 15:35: slice 4
only; the `AGENTS.md` release-safety sentence stays the owner's decision and is **not** edited; no release is
dispatched; no Gradle while load ≥ 4 (it is above 6). All observed.

**What it pinned:** "uploads a **debug APK** on every green run" — a description of what `ci.yml`'s artifact step
currently does. That is falsifiable by any lane that edits the upload step, for reasons that have nothing to do
with signing, and the guard would then report a signing-law regression that did not happen.

**What it pins now:** the reason the snapshot was worth recording — the debug variant needs no keystore secret
at all, which is why an installable build has never been blocked by the owner's signing decision. That clause
survives the artifact step moving, being renamed, or the debug APK coming from somewhere else entirely.

**Applying the slice-3 rule to myself, because a rule that only exempts its author is not a rule:** this new
pin lands in the *same sentence* as a pin the audit explicitly kept (`app lane: signed release needs the 4
secrets` — "the *signed release* needs the 4 keystore secrets"). Two pins, one sentence. The test is not
"one sentence, one pin", it is whether one half can be edited while the other stays true — and here they are
two different propositions about two different build variants: the debug clause changes if debug signing ever
starts needing a CI secret, the release clause changes only if release signing stops needing the keystore. Each
pin can fire alone, so both are coverage. Recorded as *accepted with reason*, not waved through.

**Alternative considered and refused:** the routing instruction in the next clause ("A task that needs an
installable build today takes the **debug APK** from `🔨 CI — Android Build & Test`") is more actionable, but it
names a specific workflow, so it inherits the same rot the old literal had. The reason is tool-independent; the
route is not.

**Derived after the edit, by importing the guard:** `len(INVARIANTS)` 104, 0 missing phrases, 0 duplicate
labels, 7 of 15 converted, 9 audit labels present of which 1 is the kept requirement pin → **8 pinning state**:
4 held (2 supervisor decisions — `one vCPU`, `backend is the running system`; 2 on qoder3's adult surface) and
**4 ordinary left** — `the filter shape is measured, never assumed`, `app: arm64-excluded suites are invisible
here`, `MovieBox is metadata + trailer evidence, not playable`, `no playable print is resolvable from this host`.
No `AGENTS.md` byte moved; `App/AGENTS.md` untouched this slice.

**Push block, measured 2026-11-01 on this lane (q5), so nobody reads the sha below as "on origin".** The slice
commit exists locally on `q5-pin-s4-debug-apk-20261101`; `git push` to the clean HTTPS URL with the askpass
procedure in `ORACLE_DEPLOYMENT.md` returned `remote: Invalid username or token. Password authentication is not
supported for Git operations.` Before accepting that as "token dead" I ran the check the same file prescribes —
that the helper really emitted a credential rather than an empty string: the heredoc-built helper answers the
Password prompt with a non-empty value, and the variable is present in the environment. So the answer came from
GitHub about the credential, not from a broken helper. Consequence for the fleet: this lane's write credential
is now in the same state qoder1 reported at 09:03, so **the whole pin stack is parked at the owner, not at a
lane** — `c0e86e5` → `19b4a5f` → `011d973`/`4fa35e0`/`23d1558` (already on origin) plus this slice. No CI run
exists for a sha that never reached origin, and none is fabricated. Next step is owner-only (re-issue or
re-authorize the token); on restoration, push this branch as-is and read the 49-step hosted job — no rebase, no
re-author, no second copy of the conversion.

## Slice 5 — `the filter shape is measured, never assumed` → "the method above is the law and not a quoted shape"

**Branch:** `q5-pin-s5-filter-shape-20261101`, stacked on slice 4 (`aad46c5`). Conversion commit `44c3ee9`; the
branch tip after this paragraph is the records commit that names it, so gate the *branch*, not a remembered sha.
Supervisor instruction
(post–15:35): slice 4 stays unpushed, **do not push and do not retry the push**, no credential value read; slice 5
is local docs work only. All observed — nothing was pushed from this slice and no credential was printed or
inspected.

**What it pinned:** the verbatim YAML of `backend-ci.yml`'s own `paths:` list,
`` `paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]` ``. A guard that quotes a configuration file's
contents is a timer on the next legitimate CI change: a lane that widens the filter (to feed CI on `docs/**`, for
instance) would turn CI red and the failure would read like a docs-law regression when it is a configuration edit.
That is the same defect class as slice 4's artifact-step snapshot, one level closer to the machine.

**What it pins now:** `AGENTS.md:282` — "the method above is the law and not a quoted shape", the parenthetical
recording the `paths-ignore` incident: a trigger shape quoted into a document that could not be reproduced against
the tree or the object store, retired as "treat it as never having existed". That sentence is the reason the old
literal was unsafe to rely on, so pinning it protects the *same* interest the state pin was reaching for without
inheriting its rot. The shape itself stays in `AGENTS.md` where it is honest: dated 2026-10-30, anchored to
`dc73ac7`, md5-anchored to the workflow blob, and labelled "what the filter is today".

**Nearest-neighbour check, because the series rule is coverage and not accumulation.** Three pins now sit in this
one block, so I checked them against each other rather than declaring a clean slot:

| pin | the proposition it guards | how it can fire alone |
|---|---|---|
| `the workflow file is the only source of truth` | the **step list** — a stale suite count quoted in prose | a lane rewrites the counting paragraph, leaves the trigger paragraph intact |
| `read the trigger block, not the account` | the **obligation to measure** before predicting | a lane deletes the shape-warning parenthetical, keeps the instruction |
| `the method outranks any quoted trigger shape` | a **transcription is not evidence** — the `paths-ignore` failure | a lane fixes the phantom-shape sentence, keeps the counting and measuring sentences as they are |

Three different artifacts (a count, an instruction, a copy), three different historical failures. Not duplicates.

**Verification, derived by importing the guard rather than grepping:** `len(INVARIANTS)` 104 (unchanged — one
label swapped for another, so no count moved), 0 failing phrases, 0 duplicate labels, `ast.parse` clean,
**8 of 15 converted, 7 still pinning state**: 4 held by decision (`one vCPU`, `backend is the running system`, and
2 on qoder3's adult surface) plus **3 ordinary left** — `app: arm64-excluded suites are invisible here`,
`MovieBox is metadata + trailer evidence, not playable`, `no playable print is resolvable from this host`.
Byte budget untouched: root `AGENTS.md` 31,990 / 32,000 (10 B headroom, no edit made), `Fast_Fetch/AGENTS.md`
14,469 / 18,000, `App/AGENTS.md` 14,061 / 15,000. No archive file added, so the CONTINUITY and SESSION_CHECKPOINT
counts stay 71/71 and 60/60.

**One claim corrected while writing it.** The guard comment first said the `paths:` list was "the single
most-edited block in the repo". I did not measure that, so it is gone — replaced by what is actually checkable: a
trigger block is configuration a lane may legitimately change, and `AGENTS.md:226` already calls such a list "a
snapshot that grows". Same habit as the "98 entries" error: a superlative is a measurement, and an unmeasured
measurement in a doc that other lanes quote is how a false law gets made.

## Worktree re-check of the unpushed stack (slices 4 and 5), 2026-11-01

Supervisor item (1): prove the unpushed commits survive a re-check. Done twice, each time from committed content
only — `git worktree add --detach <tmp> <tip>`, then re-derive inside that tree, then `git worktree remove`:

| what | at slice 4 (`aad46c5`) | at slice 5 (`42c0414`) |
|---|---|---|
| working tree of the fresh checkout | clean (0 paths) | clean (0 paths) |
| unpushed commits above `origin/q5-pin-s3-owner-key-20261101` | 3 | 5 |
| merge commits in `c2528e1..HEAD` | 0 | 0 |
| files touched by the whole unpushed stack | exactly the 3 lane-owned paths | exactly the same 3 paths |
| imported guard | 104 entries, 0 failing phrases, 0 duplicate labels | same, 8 of the audit's sixteen converted |
| guard module run | not run at s4 | **22 tests OK** |

The timing is a rule-7 demonstration, not a finding: the same module in the same session took **11.853 s** in my
lane worktree (page cache warm) and **107.100 s** in the freshly materialized one (cold cache, load 5.4 → 8.1 on
one vCPU). Neither number licenses excluding the suite; only CI's per-step timing does, and there is no CI read for
any of this because nothing here was pushed. The re-check proves the *content* survives a clean checkout; it cannot
prove the gate is green, and it is not presented as if it did.

## Slice 6 — `app: arm64-excluded suites are invisible here` → "they are invisible to any number printed on this host"

**Branch:** `q5-pin-s6-arm64-invisible-20261101`, stacked on slice 5 (`1241a4c`); **conversion commit
`9d120dc`**, and the records commit that names it is the branch tip — gate the branch, not a remembered sha.
Supervisor instruction for
slice 6: own worktree only, **local commit only — do not push and do not retry a push**, no credential read or
print, no Gradle (load above 4), no tag, no restart, no production write, no catalog merge, do not move the
`AGENTS.md` release-safety sentence, record the slice-6 sha and which pin it converts here, report and stand by.
All observed: nothing was pushed, no credential was touched, no Gradle ran (the conversion is a docs change and
needs no build), `AGENTS.md` untouched at 31,990 / 32,000.

**What it pinned:** `App/AGENTS.md:57` — "no number printed on this host includes those two suites". That is a
statement over the *run history of this box*: nobody can re-derive it, no test can execute it, and its rot path is
ordinary honest editing. A lane that re-measures the suite, or the lane that finally lifts the arm64 exclusion,
rewrites that sentence as a matter of bookkeeping, and the guard would report a docs-law regression for a
housekeeping edit.

**What it pins now:** `docs/SPEC_APP_ROBOLECTRIC_ARM64.md:27` — "they are invisible to any number printed on this
host", the universal reading rule that the historical tally was merely an instance of. It holds whether or not the
nine have ever run here, and it survives the day the exclusion is lifted: local numbers stay silent about
arm64-excluded classes either way. Proof that the exclusion *exists* was never this pin's job and is not in prose
at all — it is the `tasks.withType<Test>()` block in `app/build.gradle.kts` that performs it. Stated as a trade,
the same way rule 7's conversion was: the pin no longer implies a run history, and no pin can.

**A second, mechanical finding — why the target moved docs, not just phrases.** The obvious replacement in
`App/AGENTS.md` was its own law clause "The exclusion stays". It cannot be pinned there, and not for lack of
worth: `load()` returns the raw file including the `> ` blockquote markers, and `flat()` collapses whitespace only,
so the sentence as written in that file flattens to **"The exclusion > stays"** and no natural phrase can match it
across the wrap. Confirmed by matching, not by reading — the slice-3 discipline (a claim about a match has to be
tested by matching). Four candidates were probed against the flat text:

| candidate | flat match? | used |
|---|---|---|
| `App/AGENTS.md` "The exclusion stays" | **NO** (marker sits inside the wrapped sentence) | refused |
| `App/AGENTS.md` "no number printed on this host includes those two suites" | yes | the *old* literal, retired |
| spec doc "they are invisible to any number printed on this host" | yes | **pinned** |
| spec doc "the exclusion itself stays, because an un-excludable Robolectric crash is worse" | yes | considered, not used |

The reason-with-policy clause (last row) is the better *sentence* but the worse *pin*: it would fire on a rewrite
of the exclusion rationale, which is q4/q1 app-lane territory, while the reading rule is what an agent actually
misuses a local count against. One proposition, one pin, no accumulation — the converted label leaves exactly one
new label.

**Reachability, checked rather than assumed.** The new target is not in `AUTO_LOADED`, so
`test_every_invariant_target_is_reachable_from_the_loaded_indexes` must find its filename in the needles; it does,
because `App/AGENTS.md:56` links `docs/SPEC_APP_ROBOLECTRIC_ARM64.md` by name, and that doc is already in
`test_moved_spec_documents_exist`. Running the module, not reasoning about it, is what settled this.

**Derived after the edit, by importing the guard:** `len(INVARIANTS)` 104 (one-for-one swap; the count is never
the progress signal, the label set is), 0 failing phrases, 0 duplicate labels, **9 of 15 converted, 6 still
pinning state** — 4 held by decision (`one vCPU`, `backend is the running system`, 2 on qoder3's adult surface) and
**2 ordinary left**: `MovieBox is metadata + trailer evidence, not playable` and `no playable print is resolvable
from this host`, both targeting `Fast_Fetch/SITES.md`, as slices 7 and 8. Byte budgets unmoved: root
`AGENTS.md` 31,990 / 32,000, `Fast_Fetch/AGENTS.md` 14,469 / 18,000, `App/AGENTS.md` 14,061 / 15,000, CONTINUITY
11,970 B / 93 lines, SESSION_CHECKPOINT 11,941 B / 112 lines, archive counts 71/71 and 60/60 (no new file added).
Full guard module run locally: **22 tests OK** in 91.226 s at load ≈ 8 on one vCPU — a cold-cache, contended
number, and per rule 7 not grounds for excluding anything; only CI's per-step timing decides that, and this branch
has no CI read because it was never pushed.

## Ref bookkeeping at slice 6 — disclosed, because a wrong branch name in a record is the same defect class as a wrong number

The slice-6 section above names `q5-pin-s6-arm64-invisible-20261101`, and at the moment I wrote it that branch
**did not exist**: both slice-6 commits (`9d120dc`, `b22b9c1`) were made while `HEAD` still pointed at
`q5-pin-s5-filter-shape-20261101`, because I created the per-slice branch *after* editing instead of before, as I
had done for slices 4 and 5. Fixed locally, no history rewritten and nothing pushed: the s6 branch was created at
`b22b9c1`, `HEAD` switched to it, and the s5 ref was moved back to its own tip `1241a4c` (the commit whose subject
already says it re-checks the slice 4+5 stack). The moved-back commits stayed reachable throughout, so no object
was orphaned. Verified after the fact: `git for-each-ref` gives s4 → `aad46c5`, s5 → `1241a4c`, s6 → `b22b9c1`,
`HEAD` on s6, working tree clean.

The habit that caused it is worth naming for the next lane: the branch identity was a claim I made about state I
was about to create rather than state I had created — the same shape as the "98 entries" and "most-edited block"
errors, just pointing at a ref instead of a count. Method correction: create the branch, print
`git rev-parse --abbrev-ref HEAD`, and only then write the sentence that names it.

## Slice 7 — `MovieBox is metadata + trailer evidence, not playable` → the write-law behind the classification

**Branch:** `q5-pin-s7-moviebox-evidence-20261101`, created *before* the edits this time and its name printed
before it was claimed (the slice-6 method correction applied), stacked on slice 6's tip (`a9335cd`). Supervisor
16:30: own worktree, local commit, **one push attempt only**, report tip sha and verification, then stand by; no
credential read or print, no Gradle while load ≥ 4, no tag, no restart, no production DB write, no catalog merge.
All observed.

**What it pinned:** `Fast_Fetch/SITES.md:1231` — "MovieBox is a **metadata + trailer-evidence** source, not a
playable-source site, **from this host at this time**". The label called it a law; reading the sentence shows it is
a measurement wearing a timestamp. The first lane that resolves a playable print has to rewrite it as honest
bookkeeping, and the guard would report that as a policy change.

**What it pins now:** `Fast_Fetch/SITES.md:1241` — "No `sources` row may be written for a print we have never
resolved." Same paragraph, two sentences later, and unconditional: true before the site gains playability and true
after, because it is about *resolution*, not about the site's identity. That is the test this series uses, and it is
why the classification sentence is not the pin's home even though it is the sentence a reader remembers. The
classification stays in `SITES.md` where it is honest — dated, with its two measured caps named in the same
paragraph ("both measured rather than assumed").

**Slices 7 and 8 were planned together, on purpose.** The two old literals asserted nearly the same thing twice
("not playable", "no playable print is resolvable from this host"), which is the duplication this series exists to
remove, so converting them onto one clause would have left a gap and a repeat. This slice takes the **write**
obligation; slice 8 takes the **display** obligation from the same paragraph
(`Do not list it as scraped-and-playable anywhere`) — a lane can rewrite either while the other still reads true,
so two pins, two propositions. Both candidates were probed against the flat text before choosing
(`No \`sources\` row may be written…` → match; display clause → match; the scheduling clause
`periodic metadata top-up`, never as a bulk crawl` → match, deliberately unused, because it depends on the
non-enumerable-shelf measurement and would reintroduce a timer).

**Verification.** Guard imported: `len(INVARIANTS)` 104, 0 failing phrases, 0 duplicate labels, `ast.parse` clean.
Module run: **22 tests OK in 0.758 s** — against **107.100 s** for the same committed code at load ≈ 8 in the
slice-5/6 checks, a 141× spread on identical assertions with load 2.7 and a warm cache. Rule 7 in one line: local
seconds are the box's, not the module's, and only CI's per-step timing decides gate membership. **Status: 10 of 15
converted, 5 still pinning state** — 4 held by decision (`one vCPU`, `backend is the running system`, 2 on qoder3's
adult surface) and **1 ordinary left** (slice 8). Byte budgets unmoved (`AGENTS.md` 31,990 / 32,000,
`Fast_Fetch/AGENTS.md` 14,469 / 18,000, `App/AGENTS.md` 14,061 / 15,000; `SITES.md` not edited — the conversion
moved the pin onto a clause that already existed, which is the series rule), archive counts 71/71 and 60/60, no new
file, CONTINUITY 11,970 B / 93 lines.

**The one push attempt, and what it proved.** Slice 7 is the first slice where a push was *authorized* (supervisor
16:30: "one push attempt only"), so the gate was checked before attempting it — pure stack on `c2528e1`, 0 merge
commits, footprint exactly the three lane-owned paths, 0 bytes touched in another lane's surface (`admin_panel.py`,
`viewer.py`, `api_v2.py`, `redact.py`, `accounts*.py`, `docs/SESSION_CHECKPOINT.md`, all three `AGENTS.md`s,
`Fast_Fetch/SITES.md`), 0 tags pointing at the head. The attempt itself returned
`remote: Invalid username or token` — the identical signature to slice 4's two attempts, so the owner-only
credential restore is now confirmed on a fresh call rather than remembered. No retry (the ruling was one attempt),
and no repeat of the helper diagnostic that slice 4 ran to rule out a broken askpass: the failure text is the same
and re-printing credential lengths adds nothing to a settled finding. **Consequence unchanged: slice 7 has no
hosted run and no CI verdict.** What is claimed for it is only what a local run can claim — 22 guard tests OK
against the committed content — and slices 1–3 remain the only conversions CI has seen.
