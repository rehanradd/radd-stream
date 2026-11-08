# Session 110 — coverage-aware release print fallback — 2026-11-08

Branch `session110-release-print-fallback` from `3916e6ab` (Session 109).
Author rehanradd. Builder does not push, deploy, or touch the live DB or
live tree — the parent pushes and gates. All verification ran against
fixture DBs, never the live catalog.

## 1. THE LIVE PROBLEM — VERIFIED BY THE PARENT 20:14–20:19 PKT 2026-11-08

Device test session 1 (APK 279, Appetize): Play FAILED on Ali Baba aur 40
Bhoot 720p — the player showed "Nothing playable", every option failed.
Parent proved server-side the cause is DEAD LINKS, not an app bug: the
chosen 720p print (cat release 130306, legacy 1252022) has 3 copies
(mixdrop 376248, vupload 376250, streamtape 376251), all 404 on
minted-handle press; the app correctly tried the bundle and reported
honestly. The gap it exposes: the app plays by release_id
(`DetailViewModel.playV2(print.releaseId)`), and Session 109's fallback
only walks work_id/episode_id targets — a bare `release_id` "names one
print and is never switched to a sibling", so a dead named print hides a
playable sibling print of the same work. Session 110 closes that gap,
with a hard constraint Session 109 did not need: the fallback must never
cross episode ranges (a user who asked for S1E3 must never get S1E4 or a
whole-season pack).

## 2. THE FIX — DONE

Code (`api_v2.py` only; `play_bundle` untouched):

- `route_play`'s bare-`release_id` branch now builds the named print's
  bundle FIRST (legacy translation applies to the NAMED print only) and
  returns it unchanged when it plays — the walk never changes the first
  choice. Only when the named bundle is `ok` but not playable does the
  route walk same-coverage siblings, best first, capped at the same
  `_WORK_PRINT_FALLBACK_LIMIT = 5` total tries including the named print.
  Every sibling id is a cat id resolved by the route itself, so
  `legacy_release_id=False` (Session 108 lesson).
- When nothing plays, the NAMED print's bundle is returned — not the best
  sibling's — so the 409 / download-only answer is exactly today's, on
  the print the caller asked for. A bundle that is not ok (unknown or
  hidden target) never walks: the walk cannot run without the named
  print's coverage, and a 404 must not become an oracle for hidden rows.
- The coverage rule (new `_same_coverage_sibling_prints`, documented in
  its docstring), defined from `cat_releases.coverage_type` +
  `cat_release_episodes` rows:
  - whole_work -> another whole_work print of the same work, same season
    number (0 for a movie, the stamped season for a series print).
  - season_pack -> another season_pack of the same work, same season.
  - single_episode / episode_range -> another print of the same
    coverage_type whose materialised episode set is EXACTLY the named
    print's set — same episodes, no more, no fewer (two NOT EXISTS, so
    a print with no rows can never match).
  - parts -> another parts print of the same work, same part number and
    season.
  - Fail closed: an unstamped season_pack, a range with no materialised
    rows, a parts print with no part number, or an unknown
    coverage_type yields NO siblings. The data model expressed "same
    range" cleanly — no guessing was needed.
- Adult scope: the sibling read applies `adult_scope('w')` for public
  callers exactly like Session 109; operator bypass unchanged. The flag
  is a property of the work, so a flagged work's named bundle is already
  not-ok and the walk never runs for it — the scope on the sibling read
  is the second lock, not the first. Streamable/identity filters and the
  projector ordering (quality_score DESC, print_version DESC, id DESC)
  mirror Session 109. Zero network probes: each tried print is one
  bundle build of indexed reads.

Tests (5 new, all passing — see §3): `test_api_v2.py` gains
`V2PlayReleasePrintFallbackTests`: (a) dead named + playable
same-coverage sibling -> sibling bundle; (b) playable sibling covering
a DIFFERENT episode range exists, named dead -> still 409 on the named
print (tried list holds only the dead print's link); (c) named playable
-> named bundle, no walk; (d) adult-flagged sibling never returned to a
public caller (404), operator bypass walks to it (200); (e) legacy
release_id still translates for the named print, work_id/episode_id
paths unchanged. Session 109's `test_release_id_for_the_dead_print_still_409s`
is SUPERSEDED by (a) and moved/rewritten into the new class; the Session
109 class docstring's "never switched to a sibling" sentence is corrected.
`_twin_prints` moved to the fixture base so both classes share it.
Fixture gains "Range Prints" (series: EP 01-02 dead 1080p, EP 03-04
playable 720p) and "Adult Twins" (flagged movie: dead 1080p, playable
720p). Three pinned corpus counts updated for the bigger fixture:
`test_every_coverage_number_adds_up` (works 7->8, prints 9->11, links
13->15; totals 19 links, 4 hidden), `test_manifest_publishes_the_contract_it_keeps`
(works 7->8), `test_an_unprobed_link_is_unchecked_never_active`
(excludes the new hidden AT-CDN from the public-active census).

## 3. TESTS — 5 NEW, NEGATIVE CONTROL RUN

- `test_api_v2.py`: 58 OK (was 54, -1 superseded Session 109 test +5 new).
- Negative control (only `api_v2.py` stashed, tests + fixture kept): 2/5
  fail without the fix — (a) and (d-operator) answer 409 on the old code,
  the exact live shape — while (b), (c) and (e) pass on the old code, as
  they should. Stash popped cleanly afterwards; the fix is what makes the
  fallback tests pass, not the fixtures.

## 4. GATE — VERIFIED

Full backend gate (`~/workspace/run-backend-gate.py`, reads the module list
from `backend-ci.yml`): 51/51 modules PASS, FAILED MODULES: 0, exit 0.
The 4 importer modules the gate script's regex misses, all solo OK:
`test_dub_collision_census` 13 OK, `test_themoviebox_links` 7 OK,
`test_themoviebox_detail_api` 18 OK, `test_themoviebox_import` 53 OK.
`test_docs_invariants.py` 22 OK from `Fast_Fetch/` as well as in the gate.
Key module counts: `test_api_v2` 58 OK. Suite count by the law's method:
`grep -c 'name: 🧪' .github/workflows/backend-ci.yml` = 55 (51 script
modules + 4 importer modules), all green.

## Files changed (workspace clone, branch session110-release-print-fallback)

- `Fast_Fetch/api_v2.py` — `route_play` release_id branch walks
  same-coverage siblings (`_same_coverage_sibling_prints`,
  `_WORK_PRINT_FALLBACK_LIMIT = 5` total tries); work/episode paths
  untouched.
- `Fast_Fetch/test_api_v2.py` — new `V2PlayReleasePrintFallbackTests` (5
  tests); fixture gains Range Prints + Adult Twins; three pinned corpus
  counts updated; Session 109's release_id 409 test superseded.
- `Fast_Fetch/checkpoints/20261108-muse-session110-release-print-fallback.md` (this file).
- `Fast_Fetch/checkpoints/README.md` + `Fast_Fetch/CONTINUITY.md` (109 -> 110).

## NOT done / follow-ups

- Live proofs owed (parent, after gate deploy): `POST /api/v2/play
  {"release_id": <legacy 1252022>}` (Ali Baba aur 40 Bhoot 720p) must
  return 200 with a same-work sibling print's bundle when one plays, and
  the existing release_id plays (Chalk Line 1080p 402, Mentalist 720p
  302) must not change. Do NOT claim live until the parent deploys it.
- Session 109's follow-up stands: the walk is invisible in the response
  (the client asked for a print, not a walk). Deliberate: same shape as
  today.
- The coverage rule trusts the projector's materialised rows; a print
  whose `cat_release_episodes` rows are missing fails closed (no
  siblings) rather than falling back on label parsing — if such a print
  is ever found live, that is a projector bug to fix, not a fallback
  rule to loosen.
