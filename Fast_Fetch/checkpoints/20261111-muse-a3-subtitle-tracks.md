# 2026-11-11 — Muse [A3-SUBTITLE-TRACKS]: subtitle tracks in the v2 bundle (gap A3 / G-1)

## What was built

Server-side subtitle tracks, end to end. The live catalog already held
125,686 subtitle rows (`download_sources` playback_type='subtitle' — kisskh's
eleven .vtt tracks per episode, hosts res.cloudinary.com + sub.cdnauto.xyz),
but the projection fed them into `cat_links` as cloud_page rows, so the play
ladder carried .vtt files as if they were video, and the bundle's
`tracks.subtitles` was always empty.

- `catalog_v2.py`: new `cat_subtitles` table (release_id, work_id,
  ledger_link_id, lang, label, format, state); the projection diverts
  playback_type='subtitle' rows there instead of `cat_links`. Lang is parsed
  from the filename (`1.en.vtt` → `en`, name fallback via a small map);
  format from the extension (vtt/srt/ass/ssa/ttml, blank when unknown).
  `_reset()` clears it; `project()` reports a `subtitles` counter.
- `catalog_api.py`: every link view now carries `tracks` — audio from the
  release descriptor (one entry per language, layout per-release) and
  subtitles from `cat_subtitles`, addressed by our own
  `/api/v2/subtitle/<handle>` route. The address rides as `subtitle_url`:
  `redact.scrub` drops any key named `url`, so a `url` key would never reach
  the app. English is the default track, else the first.
- `api_v2.py`: `GET /api/v2/subtitle/{handle}` 302s to the stored file
  (no-store, same header block as /resolve). The token parses to a ledger id;
  the row must be a subtitle row; a flagged work, a video handle, or a bad
  handle answers exactly like a missing track. No resolver runs (the stored
  URL IS the file), no quality gate, no `?redirect=0` JSON form — the upstream
  URL never appears in a JSON body. Bucket `play`, arity `(2,)`.
- `redact.py`: `subtitle_url` added to `MINTED_KEYS` (handle noise masking).

## Verification (local, CI way)

- New `Fast_Fetch/test_subtitle_tracks.py` (12 tests: projection, bundle,
  route incl. adult denial) — registered in `backend-ci.yml` (85 suites).
- `test_api_v2.py`: `V2SubtitleRouteTests` (302 + bundle round-trip + video/
  flagged denial) + bucket table + GET-heads set + `ROUTE_TESTS` entry.
- Green locally: subtitle_tracks 12, catalog_v2, catalog_api, bundle_handles,
  redact, api_v2 75, docs_invariants 22, ci_manifest 10 (after commit).
- `API_V2.md`: §5 example, `subtitle_mode` row, §12 route row, §17 Tracks
  checkbox (subtitle half), §18 G-1 marked subtitle-half resolved.

## Still open (not this branch)

- App follow-up: map `tracks` onto `WirePlayCandidate` → `PlaybackRendition`
  and auto-load bundle subtitles in the player (`addExternalSubtitle` path
  exists; the bundle side is what this branch closed). The app model already
  parses `tracks.subtitles[].url` — the server emits `subtitle_url`, so the
  mapping needs the one-field rename on the app side.
- Nginx: `/api/v2/subtitle/{handle}` needs an allow-list entry before the app
  can reach it publicly (noted in API_V2.md §12).
- Live data: the next projection rebuild (rev-8 / parent gate) is what moves
  the 125,686 rows out of `cat_links` into `cat_subtitles` on the live DB —
  no live write was made here.

## State at build time

- Branch `muse/a3-subtitle-tracks-20261111`, rebased onto main `36cc4d33`
  (A1 landed 07:35 PKT). Main + live tree `36cc4d33`; service PID 1700156.
- Disk: 61G free after the 07:47 PKT user-ordered cleanup (was 2.1G) — backend
  gates unblocked again (~7 fit). Panel backend batch no longer disk-blocked.
