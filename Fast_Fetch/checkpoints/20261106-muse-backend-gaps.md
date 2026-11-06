# 2026-11-06 — Muse [MUSE-BACKEND-GAPS]: stream deep link + share URI, WorkManager sweep, by-media sort, watchlist pull

## Stream deep link + share with a URI (app)

NEW `ui/navigation/DeepLinks.kt`: the one owner of deep-link URIs (detail,
stream, browse) — build and parse with the same route codec (`Screen.kt`'s
encoder/decoder went `private` → `internal` for it). The NavGraph's Player
destination now answers `radd://stream/<handle>/<title>` with the same args
the in-app route carries. Sharing a title from Detail sends the template
words PLUS the title's own deep link. NEW `DeepLinksTest` (6 cases).

## WorkManager sweep (app)

The sweep already ran in-process every 5 minutes while the app is alive
(`CacheEngineRunner`); nothing ran it while the app is closed. NEW
`data/cache/CacheSweepWorker.kt` (`@HiltWorker`, the same `CacheSweeper`,
never retries), `work-runtime-ktx` 2.9.0 + `hilt-work` in the catalog and
the app build, the Application implements `Configuration.Provider` with the
Hilt worker factory, and a unique daily periodic work (`KEEP`) is enqueued
at launch. The manifest removes WorkManager's default startup initializer,
or the Hilt worker could never construct.

## By-media sort (server)

`/api/v1/search/by-media` takes `sort=best|newest|most_copies|title`.
Best is the old key; newest orders by year, most_copies by print count,
title alphabetically. Unknown falls back to best, never a refusal, and the
answer echoes the sort it used. The sort orders the capped window only.
4 new tests in `test_media_search.py` (44 OK).

## Watchlist pull materialization (server + app)

The push side of sync existed; the pull side only counted what it could not
name. Server: `GET /api/v1/posts` takes `work_ref` — a minted handle,
unminted with the server's own secret, resolved by NEW
`viewer._resolve_work_ref` (imdb/tmdb id columns; title-family keys by a
per-connection UDF over the same `normalize_title` the key was derived
from, family checked in Python). A forged handle, a handle for a missing
work, and a flagged work's handle all answer an empty page (total 0),
never an error; the operator's hides still apply on top. NEW
`Fast_Fetch/test_work_ref.py` (5 tests, registered in backend-ci.yml).
App: `FavoritePlan` carries `unknownRefs` (blank refs excluded);
`syncNow` resolves up to 50 per pass, saves the post locally, clears any
stale refusal against it, and reports `favoritesPulled` (the account card's
sentence says so; `favoritesUnknownHere` is only what is still unresolved).
NEW `SyncContractTest` cases (2).

## Deliberately not built

`/api/v1/trending` and `/api/v1/suggest` as v1 routes: the app already
reaches both — trending through `sort=trending` on the posts list and
suggestions through the wired `/api/v2/suggest`. A v1 alias would be a
route no caller calls.

## Also in this push

Fixes the Session 65 CI failure (Android run 42155195902 on c65cf05;
Backend run 42155195867 was SUCCESS): `compileDebugKotlin` — the
six-flow `combine(...)` in MyListViewModel does not resolve to a typed
overload (the compiler falls back to the vararg form, whose array the
six-parameter lambda cannot take). Fixed by combining as two triples
(3 + 3) and destructuring the pair.

## Tests

- test_media_search.py 44 OK, test_work_ref.py 5 OK, test_search_fuzzy.py
  OK, test_panel_feed.py OK, test_redact.py OK, test_database.py OK
  (skipped=1) locally.
- App: new DeepLinksTest (6) + SyncContractTest additions (2).
