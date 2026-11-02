# 2026-11-02 — q9 supervisor lane `[Q9-PLAY-STALE]`: the play path stops recalling a copy the ledger already retired

Branch `q9-fix-play-stale-redirect-20261102`, off `origin/main` at `846fb76`. Worktree
`/tmp/q9_play`. Nothing else touched: no trunk push, no tag, no release, no service restart, no
live-tree edit, no production DB write, no VM Gradle/APK build, no credential read.

## The task, as filed

Supervisor: "when re-resolving a saved link fails, the play route still redirects to the stale old
URL, unlike the download route — so a failed unwrap does not reliably produce an honest
`no_playable_source` answer. Make the play path answer honestly on re-resolve failure." Owner order
`/tmp/api-db-logic-first.md` items 1-2 are the same defect from the other side.

## What was already fixed, and what was not

Measured in this tree, not assumed. Line numbers below are the base sha `846fb76`; this lane's own
hunk shifts `fast_fetch.py` by a dozen lines after them. Audit critical 2 (`63a3dd9`, in trunk) made
`/api/v1/stream` refuse the resolver's *flagged* stale answer
(`viewer.py:4052-4061` → 404 `{"success": false, "error": "no_playable_source"}`), and
`test_redact.py::test_a_stale_re_resolve_is_not_a_stream_redirect` pins it. So the fall-through at
`fast_fetch.py:5933-5947` was already honest.

The hole is one branch earlier, in the JIT's refresh trigger
`fast_fetch.py:5642-5644`, before this change:

```python
if src["status"] in ("dead", "expired"):
    needs_refresh = True
```

`download_sources.status` is written from a five-word vocabulary, and
`tiers.UNPLAYABLE_STATES` — the constant lane q8 landed for the ranking surface at `tiers.py:59-64`
— is exactly that list: `dead`, `broken`, `gone`, `expired`, `unreachable`. The resolver named two
of the five. A permanent row retired under any other word therefore skipped the re-resolve entirely
and fell into the cached branch (`success: True, cached: True`, no `stale` flag) and the play route
302-ed a player at it: an address the ledger itself had already demoted, with **no attempt to heal
it and no refusal either**. `viewer.py:956` (`/api/m3u`) and `viewer.py:3107` both already treat
`broken`/`gone`/`unreachable` as not live; the JIT was the last site still reading two words.

## The fix

`resolve_live_source` reads `tiers.UNPLAYABLE_STATES` instead of retyping part of it. One hunk, in
the trigger; the download route, the v2 contract, the projection and the ladder are untouched. The
consequence is the honest answer the task asked for, without a new failure mode invented in the
route: a demoted row is now re-resolved, so it either heals — and the player gets a
`refreshed: True` address that this request produced — or it reaches the existing fall-through and
`/api/v1/stream` answers 404 `no_playable_source` (v1 flags it `stale: True`, and the bridge/v2 path
answers `code: no_playable_source` directly).

Deliberately **not** included: `'unverified'` / NULL / `''`. Those are the blanket "never knocked"
state that `link_state.mark_unverified` writes across the whole unprobed catalog
(`link_state.py:3-30` measures 3,070,247 of 3,070,247 rows as an unprobed `active`). Forcing a
re-resolve of every one of them at play time is owner item 1 — a play-time Range probe — which is a
different change with a different risk profile, not this one. `tiers` does not call them unplayable,
so this lane does not either.

## Tests added (both in the CI-gated module list)

- `test_database.py::test_a_ledger_demoted_link_is_re_resolved_never_recalled` — for each of
  `broken`/`gone`/`unreachable`: a permanent direct-media row is never answered as a stream, the v2
  contract answers `no_playable_source`, and a failed re-resolve does not promote the row back to
  `active`.
- `test_redact.py::test_a_ledger_demoted_link_is_not_a_stream_redirect` — the proof on the route:
  `GET /api/v1/stream?id=<handle>` on the same three rows answers **404 with no `Location` header
  and the body `{"success": false, "error": "no_playable_source"}`**, and the refusal quotes neither
  the host nor the token.

## Verification actually performed

`python3 -S -c` compile of the three edited files (ok), and the predicate itself against the real
`tiers.UNPLAYABLE_STATES` (five words matched; `active`, `unverified`, NULL, `''` not matched).
Hosted Backend CI on the pushed tip is the full judge: run `41381467803` at `abc39dc`, job
`125073004667`, **46/46 steps `success`** in 101 s — including `test_database.py`, `test_redact.py`
and `test_docs_invariants.py`. No Android run exists at this tip because the push touched no `App/**`
path and `ci.yml` filters on them.

Under the light-work order (`load average 11.59`, 1.1 GB available at 08:12) no suite was run; the
**single new route test** was, because it is one test and not a suite —
`python3 -S -m unittest -v test_redact.PublicEdgeHttpTests.test_a_ledger_demoted_link_is_not_a_stream_redirect`
→ `ok`, `Ran 1 test in 3.092s`. Two throwaway probes against the same fixture, one on this tip and
one on a `git archive` export of the base sha, are the before/after:

```
BASE broken|gone|unreachable  resolver success=True stale=None  -> HTTP 302 Location=https://media.example.test/film.mp4?token=old
FIX  broken|gone|unreachable  resolver success=True stale=True  -> HTTP 404 no Location, {"success": false, "error": "no_playable_source"}
```

The base line is the flaw as filed: the row never reached a re-resolve, so nothing flagged it and the
route redirected. The fix line answers through the existing stale-refusal path, and the v1 `success`
flag is what `viewer.py` turns into a refusal rather than a location.

## Follow-up, reported not smuggled in

The echo-laundering path is still open and is a separate item: an unwrap helper that returns the
address it was handed (`unwrap_fastdl` on a non-200, `unwrap_hubcloud` on a failed gpdl hop,
`unwrap_pixeldrain` on input it cannot parse) is accepted by the success branch at
`fast_fetch.py:5836` because that branch only compares against `source_url`, not against the row's
own stored `final_url`. Such an echo is written back as `status='active', last_checked_at=now` and
returned as `refreshed: True` — a failed unwrap reported as a fresh one, and the cached branch then
serves it happily for the next six hours. The bridge guard catches the landing-page shapes; it does
not catch an echo of a media URL. Fixing it means requiring `fresh_url` to differ from the address
the request started with, which changes the download route's answers too, so it is not this branch's
business.
