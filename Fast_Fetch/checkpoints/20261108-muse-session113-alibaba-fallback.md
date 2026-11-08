# Session 113 — probe-aware release_id fallback (Ali Baba) — 2026-11-08

Branch `session113-alibaba-fallback` from `e0319c08` (Session 111, the live
tree). Author rehanradd. Builder does not push, deploy, or touch the live DB
or live tree — the parent pushes and gates. All verification ran against
fixture DBs, never the live catalog. The app-bugs session previously called
"Session 113" is now Session 114 — this backend session takes 113 because
it is next in the queue and the self-check already calls the Ali Baba
follow-up the Session 113 candidate.

## 1. THE LIVE PROBLEM — VERIFIED BY THE PARENT 22:3x PKT 2026-11-08

POST /api/v2/play `{"release_id": 1252022}` answered 200 with the NAMED
print cat 130306 (Ali Baba aur 40 Bhoot 720p), playable True, 3 candidates
— but pressing the bundle's OWN stream handles gave 404/404/404. Sibling
720p prints cat 130309 / 130312 / 130315 (legacy 1252025 / 1252028 /
1252031) all press 4/4 302. A playing sibling existed and the route
returned the dead named print instead.

Root cause: Session 110's fallback trigger read the bundle's STATIC
`playable` flag (`api_v2.py`, release branch, `if named_cat_id is not None
and not bundle.get("playable"):`). That flag is classification, not a
press — `catalog_api.play_bundle` counts a copy playable when it is not
dead and its group is streamable-or-resolvable, i.e. when its service is
resolvable. A named print whose copies are from resolvable services but
dead upstream claims playable=True and the walk never runs. The same
static flag gated Session 109's `_play_first_playable`, so a work/episode
walk could stop at a known-dead best print too.

## 2. THE FIX — DONE

Code (`Fast_Fetch/api_v2.py` only; `play_bundle`, coverage rule, adult
scope, quality gate, resolver all untouched):

- NEW `_release_has_unfailed_candidate(conn, release_id)` — does this
  print hold a playable-classified copy the negative cache has NOT
  freshly failed? It reads the print's `cat_links` rows joined to
  `download_sources` on `ledger_link_id` and mirrors
  `_link_view`'s playable rule exactly (ledger id present, group <=
  `_GROUP_RESOLVE`, state not in `tiers.UNPLAYABLE_STATES`), then
  applies the negative-cache freshness rule exactly as
  `fast_fetch.resolve_live_source` states it: a record counts as a
  failure only when `last_failed_at` is within
  `NEGATIVE_CACHE_TTL_SECONDS` (12h) AND
  `COALESCE(failure_resolver_v, 0) >= RESOLVER_VERSION` (Session 107:
  an older-resolver record is stale — a new unwrapper may have landed).
  The check is READ-ONLY: it never clears a stale record (the next real
  press does that) and never writes. Fail-open throughout: no evidence
  of failure means the copy counts, so a print the cache knows nothing
  about behaves exactly as before.
- `route_play` release_id branch: the walk now runs when the named print
  has no playable candidate (Session 110, unchanged) OR when it claims
  playable but holds no unfailed playable copy (Session 113). A sibling
  is accepted only when it too holds an unfailed playable copy. When
  nothing verifies, the NAMED print's bundle stands, so the 409 /
  download-only answer is exactly today's, on the print the caller
  asked for. A bundle that is not ok (unknown/hidden target) never
  walks, as before.
- `_play_first_playable` (Session 109's work/episode walk): the same
  verification gates acceptance — a cache-failed best print no longer
  stops the walk. When nothing verifies, the best print's bundle is
  still returned, exactly as before. This is a deliberate extension
  beyond the release_id branch: it is the same static-flag flaw in the
  same helper, fixed with the same one-line check, and it has its own
  test (f) below.

Deliberate deviation from the brief's literal wording, stated plainly
so the parent can judge it: the brief said "bounded live check". This
session does NOT run a live unwrap+probe inside /play. Reasons: (1)
/play is a routing endpoint measured at 0.016–0.031 s and the app gives
`playV2` a 2 s timeout — a live unwrap+probe per candidate (5 s landing
timeout, up to 3 copies plus 4 siblings) would blow the caller's budget
and turn routing into resolving; (2) the stream route IS the live check,
and its failures are exactly what the negative cache records, so
consulting the cache IS consulting live press evidence; (3) a network
probe is untestable in the offline fixture, while the cache check is
fully testable (see §3). The TTL/version constants are the resolver's
own, read by a lazy `import fast_fetch` inside the helper (the
established pattern — `viewer.py` imports `fast_fetch` inside functions
for the same cycle reason; `api_v2` must not import the resolver at
module level).

Measured cost (scratch `/tmp/session113-timing.py`, one fixture DB,
in-memory SQLite on this box): the helper costs 0.016–0.021 ms per call;
a fallback play runs 2 checks (named + sibling), ~0.04 ms added, against
a full POST /api/v2/play of 13.0 ms in the fixture. The added latency is
negligible against the live route's measured 16–31 ms; the live proof
below should still confirm the route time. Bounded: at most
`_WORK_PRINT_FALLBACK_LIMIT` = 5 small indexed reads per call.

No new failure recording was needed: the evidence is already recorded
by `fast_fetch._record_resolve_failure`, called by the stream route on
every failed press. `route_play` presses nothing, so it has nothing new
to record.

KNOWN LIMITATION (first play): a never-pressed dead print still returns
its bundle on the first play — the cache holds no evidence yet. The
app's handle presses record the failures, and the NEXT /play call falls
back. That is the honest boundary of a cache check, and the follow-up
for ever closing it is a bounded live probe only if the app's play
timeout budget ever allows one.

## 3. TESTS — 6 NEW, NEGATIVE CONTROL RUN

`test_api_v2.py`: 58 → 64 tests. New class
`V2PlayCacheAwareFallbackTests`, new fixture post "Cache Twins" (named
1080p print with TWO playable-classified copies `CT-CDN`/`CT-CDN2`,
sibling 720p print with `CT-SIBLING`; failure records stamped by the new
`_mark_resolve_failure` helper, which writes exactly what
`_record_resolve_failure` writes). (a) named print's copies both
fresh-failed → sibling returned; (b) failure recorded by an older
resolver version → named kept (Session 107 rule pinned); (c) failure
older than the 12h TTL → named kept; (d) one copy failed, one never
pressed → named kept; (e) named AND sibling both fresh-failed → named
returned (honest answer); (f) work_id walks past a cache-failed best
print → sibling returned. Fixture counts updated where pinned:
`test_every_coverage_number_adds_up` (works 8→9, links 15→18, prints
11→13; eleven posts) and the manifest census (works 8→9).

Negative control (only `api_v2.py` stashed, tests + fixture kept): 2/6
fail without the fix — (a) returns the named print, (f) returns the
best print — while (b), (c), (d), (e) pass on the old code, as they
should. Stash popped cleanly afterwards; the fix is what makes the
tests pass, not the fixtures.

## 4. GATE — VERIFIED

Full backend gate (`~/workspace/run-backend-gate.py`, reads the module
list from `backend-ci.yml`): 52/52 modules PASS, FAILED MODULES: 0,
exit 0 (two runs; the first run's console delivery truncated, the
second wrote `/tmp/gate113.log`: `modules: 52`, 52 PASS lines).
`test_api_v2` 64 OK, `test_docs_invariants` 22 OK, `test_catalog_api`
133 OK (in the gate run). The 4 importer modules the gate script's
regex misses, all solo OK: `test_dub_collision_census` 13,
`test_themoviebox_links` 7, `test_themoviebox_detail_api` 18,
`test_themoviebox_import` 53. No new test module, so no `backend-ci.yml`
change and no UNREGISTERED-list change. CONTINUITY count 111 → 112
(110 dated + 2 undated); README pointer added at top.

## 5. LIVE PROOFS OWED (PARENT, AFTER THE GATE DEPLOY — NOT ATTEMPTED HERE)

- POST /api/v2/play `{"release_id": 1252022}` returns sibling 130309
  (or 130312 / 130315), 200, playable True — the fix's live proof. This
  needs the Ali Baba copies' failures to be in the negative cache: the
  parent's 22:3x/22:39 PKT presses recorded them (12h TTL, still fresh
  at deploy time if the gate runs the same night; if the TTL has
  lapsed, press the named print's 3 handles once first — the 404s
  re-record the failures — then re-call /play).
- The named print's own bundle handles still press 404 (unchanged —
  the copies are dead; the fix changes the ROUTE's choice, not the
  copies).
- Sibling handles press 302 (already proven 22:39 PKT: 4/4 each).
- `{"release_id": 500000}` → 624764 unchanged; `{"work_id": 54221}` →
  624764, handles 302; `{"episode_id": 11}` → release 17 unchanged;
  minted presses 302/302/402/302 unchanged.
- Route latency: time the /play call — the added cost should be
  sub-millisecond (two indexed reads); anything near seconds would
  mean the check is not the code written here.

## 6. MERGE NOTE — SESSION 112 SHARES THIS CLONE

Session 112's line (`session112-d25-resolvers` @ `28934275`, incl. its
docs commit with the 111 + 112 checkpoint files and a README entry for
112) is NOT an ancestor of this branch: this branch is from `e0319c08`
(live), so its README/CONTINUITY carry 111 → 113 with no 112 entry.
At merge time the parent should expect a README/CONTINUITY conflict
with the 112 line (both add a top entry and bump the count) and a
possible `fast_fetch.py` `RESOLVER_VERSION` note: this session reads the
resolver's version at call time, so a 112 merge (RESOLVER_VERSION 1→2)
needs no change here — stale v1 records become stale by the same rule.
Zero file overlap with Session 112's code files (this session touches
`api_v2.py` + `test_api_v2.py` only; 112 touches `importers/`,
`fast_fetch.py`, `test_database.py`).
