# Session 108 — play id-universe fix — 2026-11-08

Branch `session108-play-id-universe` from `3cae54bb` (Session 107). Author rehanradd.
Builder does not push, deploy, or touch the live DB or live tree — the parent
pushes and gates. All verification ran against fixture DBs, never the live catalog.

## 1. THE LIVE BUG — VERIFIED BY THE PARENT 19:27 PKT 2026-11-08

After the Session 107 gate + rev-4 apply went live (live rev 4, works 129,457,
legacy 500000 → cat 624764 → Arthur's Whisky, verified live):

- `POST /api/v2/play {"work_id": 54221}` (Arthur's Whisky, a CAT work id)
  returned release 763887 / work 68520 Desperate Lies — WRONG film.
- `POST /api/v2/play {"work_id": 54205}` returned release 763808 / work
  68514 (Savoring Paris, per the supervisor) — also wrong.
- `POST /api/v2/play {"release_id": 500000}` (legacy id) correctly returned
  cat release 624764 / Arthur's Whisky — the Session 107 fix works on the
  release_id path.

Root cause (the Session 107 checkpoint's "explicit id-universe parameter"
follow-up, now built): `catalog_api.play_bundle` always ran
`translate_legacy_release_id` (map-first). But `api_v2.route_play`'s
episode_id branch resolves `best_release_id` from cat_episodes (a CAT id)
and its work_id branch resolves the best cat release (a CAT id), then both
feed that CAT id into play_bundle, which redirects it via a ledger_release
row. The Session 107 docstring assumed only legacy-id callers reach
play_bundle; the route's own branches are cat-id callers. A second live
case from the same evening: work 116859 (The Chalk Line) resolves to cat
release 1430243, which the rev-4 map redirects to 1381940, a different
title.

## 2. THE FIX — DONE

Code (`catalog_api.py`, `api_v2.py`):

- `catalog_api.play_bundle` takes a new explicit id-universe parameter
  `legacy_release_id: bool = True`. When False, it SKIPS
  `translate_legacy_release_id` entirely and uses the id as-is. Default
  True preserves the app's contract: a bare `release_id` in the body is
  a legacy id. `release_detail` is untouched (stays cat-native) and the
  translator's fallback behaviour for genuine legacy ids is untouched.
- `api_v2.route_play` sets `legacy_release_id = release_id is not None`:
  a `release_id` in the body is legacy (translated); an id derived from
  the episode_id/work_id lookup below is already a cat id (not
  translated). The flag is passed through to `play_bundle`.
- The OTHER translate hook — the `api_v2` releases route (`GET
  /api/v2/releases/{id}`, Session 107) — audited and fixed the same way:
  the translation is REMOVED, so the route is cat-native. Evidence: v2
  speaks cat ids on every other detail route (works/episodes/seasons
  take them untranslated); `release_detail` is cat-native by design; the
  app never calls this route at all (no caller in `App/`, its detail
  comes from v1 `/api/v1/posts/{id}`); the operator panel never calls it
  either. The Session 107 rationale ("the app sends legacy releases.id")
  does not hold for this route — it was applied by analogy with
  play_bundle, whose legacy-in contract comes from the app's actual
  /play calls. A future cat-id caller would have hit the same
  redirection; a hypothetical legacy-id caller has no route left that
  needs one (v1 detail already serves legacy ids).
- Caller audit (complete): `grep` for `play_bundle` /
  `translate_legacy_release_id` over `Fast_Fetch/*.py` +
  `Fast_Fetch/importers/*.py` finds exactly three non-test call sites:
  `play_bundle` itself (guarded), `route_play` (flagged), the releases
  route (translation removed). No other caller exists — `viewer.py`,
  `fast_fetch.py` and every importer never call either function.
  `release_detail` callers all pass cat ids already.

Tests (5 new, all passing — see §3): `test_catalog_api.py` gains
`test_cat_native_id_is_not_redirected_when_flagged` in
`LegacyReleaseTranslationTests` (default legacy-in still redirects; the
flagged cat-native call stays itself); `test_api_v2.py` gains the
`V2PlayTranslationTests` wire class (4 tests): work_id returns the
work's own print, episode_id returns the episode's own print, a legacy
release_id still translates, and the releases route serves the cat
print (not the mapped target). Fixture note: `public_episode_id` is the
first Campus Beats episode and Campus Beats has exactly one release, so
its `best_release_id` is that release; `public_work_id` is Dune Protocol
(one release), so the work_id branch resolves `public_release_id`.

## 3. TESTS — 5 NEW, NEGATIVE CONTROL RUN

- `test_catalog_api.py`: 133 OK (was 132, +1 new).
- `test_api_v2.py`: 50 OK (was 46, +4 new).
- Negative control (source files stashed, tests kept): the new catalog
  test FAILED (error — the flag kwarg does not exist on the old
  signature) and `V2PlayTranslationTests` FAILED 3/4 (work_id,
  episode_id and releases-route tests fail; the legacy release_id test
  passes on the old code, as it should — that path was already correct).
  Stash popped cleanly afterwards; the fix is what makes the tests pass,
  not the fixtures.

## 4. GATE

Full backend gate (`~/workspace/run-backend-gate.py`, reads the module list
from `backend-ci.yml`): 51/51 modules PASS, FAILED MODULES: 0.
The 4 importer modules the gate script's regex misses, all solo OK:
`test_dub_collision_census` 13 OK, `test_themoviebox_links` 7 OK,
`test_themoviebox_detail_api` 18 OK, `test_themoviebox_import` 53 OK.
Key module counts: `test_catalog_api` 133 OK, `test_api_v2` 50 OK.

## Files changed (workspace clone, branch session108-play-id-universe)

- `Fast_Fetch/catalog_api.py` — `play_bundle` gains `legacy_release_id`
  (default True); translator docstring caveat resolved to the Session 108
  finding (a cat-id caller arrived inside the server itself).
- `Fast_Fetch/api_v2.py` — `route_play` derives and passes the flag;
  releases route translation removed (cat-native).
- `Fast_Fetch/test_catalog_api.py` — 1 new test
  (`test_cat_native_id_is_not_redirected_when_flagged`).
- `Fast_Fetch/test_api_v2.py` — new `V2PlayTranslationTests` (4 tests).
- `Fast_Fetch/checkpoints/20261108-muse-session108-play-id-universe.md` (this file).
- `Fast_Fetch/checkpoints/README.md` + `Fast_Fetch/CONTINUITY.md` (107 → 108).

## NOT done / follow-ups

- Live proofs owed (parent, after gate deploy): `POST /api/v2/play
  {"work_id": 54221}` must return Arthur's Whisky (cat release 624764),
  `{"work_id": 54205}` its own work, an episode_id play its own print,
  and `GET /api/v2/releases/{cat-id}` the cat print — all against the
  live rev-4 catalog. Do NOT claim live until the parent deploys it.
- Session 107 follow-up still open: work-id translation (whether any
  caller ever sends a legacy *work* id to the v2 works route — the route
  itself is cat-native and untranslated; no evidence either way yet).
- Session 107 item 12 (cross-key adult re-key) still design-only; needs a
  gated decision before any apply.
- Filmyzilla follow-ups (HQ download-ID discovery, FZ80 Turnstile),
  gofile video-folder hunt, doodstream fresh samples, megaup retry window,
  hubdrive live-file hunt — unchanged from the plan, not attempted here.

## Note on the working tree at session start

The parent had already drafted this exact fix in the working tree when
the session began (uncommitted changes to the same 4 files, labelled
"Session 107b"); the tree was reverted to clean 3cae54bb before the
branch was created, so the fix was implemented fresh here per the task
spec, under the Session 108 name. The design matches the draft; the
releases-route fix (translation removed, not kept) and the 4th wire test
are this session's additions.
