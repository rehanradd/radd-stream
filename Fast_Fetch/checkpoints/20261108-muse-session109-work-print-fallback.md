# Session 109 — work print fallback — 2026-11-08

Branch `session109-work-print-fallback` from `00e75af0` (Session 108). Author rehanradd.
Builder does not push, deploy, or touch the live DB or live tree — the parent
pushes and gates. All verification ran against fixture DBs, never the live catalog.

## 1. THE LIVE PROBLEM — VERIFIED BY THE PARENT 20:1x PKT 2026-11-08

After the Session 108 gate went live (live tree `00e75af0`, service restarted):

- `POST /api/v2/play {"work_id": 54221}` (Arthur's Whisky) no longer returns
  the wrong film (Session 108 fixed the id-universe redirect), but it answers
  409 no_playable_source. Reason: `api_v2.route_play`'s work_id branch picked
  ONE release — `ORDER BY r.quality_score DESC, r.id ASC LIMIT 1` — which is
  release 624765 (score 300, whose only candidate is one dead superduperload
  link), and never tried sibling release 624764 (score 110, 5x 1xplayer links,
  PROVEN playable via the legacy release_id path). Same 409 pattern for
  work_id 54205 (best print dead, sibling plays).
- The user asked to play the WORK, not one print. A dead best print must not
  hide a playable sibling print.

## 2. THE FIX — DONE

Code (`api_v2.py` only; `play_bundle` untouched):

- `route_play`'s work_id branch now fetches the work's releases in the same
  order (`quality_score DESC, id ASC`) with `LIMIT _WORK_PRINT_FALLBACK_LIMIT`
  instead of `LIMIT 1`, and walks them with the new `_play_first_playable`
  helper: build each candidate bundle with `legacy_release_id=False` (these
  are cat ids — Session 108) and return the FIRST bundle whose `"playable"`
  is true. The first tried print is exactly the print the old code picked
  alone, so the walk only ADDS tries — it never changes the first choice.
- If NO print of the work has a playable candidate, the walk returns the
  BEST print's bundle, so the caller's download-only/409 answer is exactly
  today's (S11 download_only 200 when the best print has download options,
  else the same 409 shape with the best print's `tried` list). Nothing is
  fabricated; a dead print is never returned as playable.
- The episode_id path walks too — it has the same failure shape, and the
  check the task asked for came back YES: `cat_release_episodes` is
  many-to-many (PK `(release_id, episode_id)`), and the projector's own
  `best_release_id` query picks ONE print out of a multi-row candidate set
  (`ORDER BY ... LIMIT 1`). The sibling query mirrors the projector's
  filters and ordering exactly (`coverage_type IN (...)`, `streamable_count
  > 0`, `identity_suspect = 0`, `quality_score DESC, print_version DESC,
  id DESC`), so the walk's first print IS the projector's best. One
  structural nuance found while building the fixture: a dead NON-streamable
  print can never be an episode's best (the projector filters
  `streamable_count > 0`, which counts playability class, not liveness), so
  the episode fallback only ever triggers for prints whose streamable links
  are recorded dead — the Twin Beats fixture uses a dead google_cdn link
  (playability `stream`, state `dead`) for exactly that reason.
- The direct `release_id` path is UNCHANGED: one bundle, one print, no
  sibling switch. The 404 (named target) / 400 (unnamed) answers are
  unchanged — they now trigger on "no release id AND no candidate prints".
- The cap: `_WORK_PRINT_FALLBACK_LIMIT = 5`. The live case needs 2; 5 leaves
  headroom for works whose top prints share one dead host family, while
  bounding the walk. Cost per tried print is one bundle build — a few
  indexed SQL reads; `catalog_api` contains no HTTP client, so the walk
  performs ZERO network probes and cannot blow the play-path probe budgets.
  A series work can hold hundreds of prints; the walk never scans past 5.
- Response shape identical: the returned bundle is a real `play_bundle`
  output, so its `target` names the print actually returned, and the
  `prefer`/`device` handling applies to it exactly as before.

Tests (4 new, all passing — see §3): `test_api_v2.py` gains
`V2PlayWorkPrintFallbackTests` (work fallback, episode fallback, all-dead
→ 409, release_id for the dead print still 409s). The fixture gains two
works in `build_corpus`: "Twin Prints" (movie: 1080p best with one dead
pixeldrain link, score 580; 720p sibling with a probed google_cdn link,
score 460) and "Twin Beats" (series: 1080p best covering EP 01–02 with a
dead-but-streamable google_cdn link, score 400; 720p sibling, score 300).
Two pinned corpus counts were updated for the bigger fixture:
`test_every_coverage_number_adds_up` (works 5→7, prints 5→9, links 9→13)
and `test_manifest_publishes_the_contract_it_keeps` (works 5→7); every
other count assertion in the module is computed from the DB, not pinned.

## 3. TESTS — 4 NEW, NEGATIVE CONTROL RUN

- `test_api_v2.py`: 54 OK (was 50, +4 new).
- Negative control (only `api_v2.py` stashed, tests + fixture kept): the
  two fallback tests FAILED on the old code (both answer 409 — the exact
  live shape: "1 ranks tried; every candidate returned a transport or
  HTTP failure", tried = the one dead link), while the all-dead 409 and
  the release_id 409 tests PASSED on the old code, as they should — those
  two paths are unchanged. Stash popped cleanly afterwards; the fix is
  what makes the fallback tests pass, not the fixtures.
- Fixture verified directly before the tests were written (scratch probe):
  Twin Prints releases score 580/460 with states dead/active; Twin Beats
  best_release_id is the dead 1080p print (streamable_count 1) with the
  live 720p sibling; public counts 7 works / 9 prints / 13 links.

## 4. GATE — VERIFIED

Full backend gate (`~/workspace/run-backend-gate.py`, reads the module list
from `backend-ci.yml`): 51/51 modules PASS, FAILED MODULES: 0, exit 0.
The 4 importer modules the gate script's regex misses, all solo OK:
`test_dub_collision_census` 13 OK, `test_themoviebox_links` 7 OK,
`test_themoviebox_detail_api` 18 OK, `test_themoviebox_import` 53 OK.
Key module counts: `test_api_v2` 54 OK.

## Files changed (workspace clone, branch session109-work-print-fallback)

- `Fast_Fetch/api_v2.py` — `route_play` walks candidate prints
  (`_WORK_PRINT_FALLBACK_LIMIT = 5`, `_episode_sibling_prints`,
  `_play_first_playable`); release_id path untouched.
- `Fast_Fetch/test_api_v2.py` — new `V2PlayWorkPrintFallbackTests` (4 tests);
  fixture gains Twin Prints + Twin Beats; two pinned corpus counts updated.
- `Fast_Fetch/checkpoints/20261108-muse-session109-work-print-fallback.md` (this file).
- `Fast_Fetch/checkpoints/README.md` + `Fast_Fetch/CONTINUITY.md` (108 → 109).

## NOT done / follow-ups

- Live proofs owed (parent, after gate deploy): `POST /api/v2/play
  {"work_id": 54221}` must return 200 with the SIBLING print 624764 (not
  409, not 624765), `{"work_id": 54205}` its own work's playable print, an
  episode_id play its own episode's playable print, and `{"release_id":
  500000}` must still return 624764 Arthur's Whisky (5 handles) — all
  against the live rev-4 catalog. Do NOT claim live until the parent
  deploys it.
- The all-dead 409 names the BEST print's `tried` candidates only — the
  walk itself is invisible in the response (the client asked for the work,
  not a print). Deliberate: same shape as today.
- Session 107 item 12 (cross-key adult re-key) still design-only; needs a
  gated decision before any apply.
- Filmyzilla follow-ups (HQ download-ID discovery, FZ80 Turnstile),
  gofile video-folder hunt, doodstream fresh samples, megaup retry window,
  hubdrive live-file hunt — unchanged from the plan, not attempted here.
