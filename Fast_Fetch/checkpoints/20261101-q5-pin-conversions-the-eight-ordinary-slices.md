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

**Branch:** `q5-pin-s5-filter-shape-20261101`, stacked on slice 4 (`aad46c5`). Supervisor instruction
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
