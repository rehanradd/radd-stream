# 2026-11-06 — Muse [MUSE-SEARCH-MYLIST]: Search + My List research rules

## Search — typo tolerance (server)

Exact LIKE-substring search answers first and always. Only when it finds
nothing does the server take a second chance: NEW `Fast_Fetch/search_fuzzy.py`
— a 3-gram candidate pass over `clean_title` (one scan, 200 rows), then a true
edit-distance check in Python (`edit_distance_le1`, single-row DP with early
exit). Every query token must land within one edit of some title token.
"Avngers" finds "Avengers Endgame"; two edits away stays silent. Tokens
shorter than four letters never enter the fuzzy pass (one edit in a
three-letter token can destroy every shared gram). The adult clause applies
to the candidate pass too, and the operator's hides still apply in the final
query — the candidate ids only ever replace the LIKE clause (always index 1,
always the first three params) in `api_v1_get_posts`. The response carries
`"fuzzy": true` when the fallback ran.

## Search — "Included in my plan" (server + app)

New `free_only=1` filter on `/api/v1/posts`: a work counts when it has at
least one print the free gate lets through — 1080p/2160p/4K/UHD/Full-HD are
premium, 720p joins them under a 480p operator cap (read from
`panel_feed.read_free_quality_cap()`), and a print with no quality label
counts as free, the same as the client treats an unknown band. The app's
chip sits in the filter rail and the filter sheet, and only a free viewer
sees it: for a VIP viewer everything is included, so the chip would only
narrow their catalog for nothing.

## Search — suggestions while typing (app)

The existing `/api/v2/suggest` endpoint is wired in: two characters minimum,
same 300ms debounce as the search, at most five title chips under the field.
A tap searches for that title — it never opens a page, because a suggestion
names a work (cat_works id), not a post. A blocked route or an old server
just leaves the list empty; the search never fails for it. **Gate item:**
`/api/v2/suggest` needs the nginx allow-list before it answers in
production, like `/api/v2/play` and `POST /api/v1/contact` before it.

## My List (app)

Remove is one tap now, not a held tile plus a confirm dialog: a small × on
the poster's corner (new optional `PosterCard.onRemove`) removes the row at
once, and the snackbar offers Undo for as long as it is on screen. The old
arm-and-confirm state machine (`MyListRemoval`) is deleted, with its test.
Sort gains "Unwatched first" (pure `sortMyList`): titles with no finished
watch row come first, then recently-added inside each half — finished means
the rail's own 10-second end-guard via `watchedTitles`, so a half-watched
title still counts as unwatched. The empty state shows three "Popular right
now" titles — the server's own trending order (most prints and mirrors
first), loaded once and only when the visible list is empty; no server means
no titles, the text-only empty state stands.

## Tests

- NEW `Fast_Fetch/test_search_fuzzy.py` (8 tests, registered in
  backend-ci.yml): edit distance, tokenize, match rules, typo finds the
  title, exact stays exact, adult never served, free-only keeps only works
  with a free print. 8 OK locally.
- `test_panel_feed.py` 29 OK, `test_database.py` 135 OK (skipped=1) locally.
- App: NEW `MyListSortTest` (2 cases) + NEW `SuggestWireTest` (3 cases:
  suggest decode, empty body, fuzzy posts page).

## Also in this push

Fixes the Session 64 CI failure (Android run 42153914025 on 9e0e7fb):
`compileDebugKotlin` — Session 64's new top-level `PendingKeep` is public
and exposes its `internal` parameter type `KeepTarget`. Fixed by making
`PendingKeep` `internal` (only the Detail screen reads it, same module).
