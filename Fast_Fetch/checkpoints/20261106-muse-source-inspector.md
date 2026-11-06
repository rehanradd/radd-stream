# 2026-11-06 — Muse [MUSE-SOURCE-INSPECTOR]: honest source rows on Detail — quality + audio + stream shape + tier

## The gap (measured before writing code)

The Detail quality switch already showed the band, the size and "Plays here /
Download only" — but not the other three facts the media-browser plan's Phase 3
promises: the print's audio languages, whether the copy is a manifest stream or
a direct file, and which tier the rung requires. All three were missing for a
reason, not an oversight: the ladder wire (`ladder_link` projection) carries no
audio and no protocol, and the gate REMOVES premium rungs for free viewers
(`VipQualityGate.gate` filters them out; `VipSourcesCard` explains where they
went), so a per-row "VIP" badge cannot be read off the ladder as served.

## What the server now publishes (both measured, never guessed)

- `tiers.for_release` adds `"audio_languages"` to the tier dict, parsed from the
  print's stored `releases.languages` column (`_split_languages`: split on `|`
  and `,`, trim, drop blanks, dedupe). Empty column → `[]`, and the row shows no
  audio line. `tiers.merge` keeps the winning print's list (`dict(tier)` carries
  it; the promoted tier is the print whose link won). The v2 play bundle calls
  the same `for_release` with a dict that has no `languages` key, so its tiers
  carry `[]` — safe, no shape change there beyond the additive key.
- `redact.py`: `"mime_type"` joins the `ladder_link` allowlist. It is the
  probe-measured Content-Type of the winner copy (the healer persists it at
  `fast_fetch.py:5444`), and it names a format, never a hoster. Grounded live
  before building: post 73983 (Street Fighter) — `releases.languages` populated
  ("English"); 3 of its 11 sources carry `application/vnd.apple.mpegurl`, 8
  carry NULL mime. So the category shows exactly when a probe measured it.
- New tests: 4 `AudioLanguageTests` in `test_tiers.py` (pipe list, comma +
  dedupe, empty → `[]`, merge keeps the winner's); 1 projection test in
  `test_redact.py` (`ladder_link` keeps `mime_type`, still drops provenance).
  `test_tiers` + `test_redact`: 110 tests OK locally.

## What the app shows (Session 71)

- Wire: `LadderTier.audioLanguages` (`audio_languages`, default `[]`),
  `LadderLink.mimeType` (`mime_type`, default null).
- NEW pure `streamCategoryFor(mimeType, playUrl)` in `player/QualityLadder.kt`
  (+ `StreamCategory(kind, container)` with its `label`): an HLS mime outranks
  everything → "Instant Stream · M3U8"; DASH → "Instant Stream · DASH"; a video
  file mime names its container → "Direct File · MP4 / MKV / WebM / …"; anything
  else (HTML, audio, no measurement) → null, and the row claims no category.
  Reuses `LinkClassification.isHls/isDash`, the same precedence
  `ManifestProtocolTest` pins for playback.
- `QualityOption` gains `audioLanguages` + `streamCategory` (both defaulted),
  wired in `LadderTier.toOptionOrNull`.
- NEW `DetailViewModel.tierLabelFor(option)`: "VIP" when the operator's gate
  reserves the rung's band/label under the free cap, else "Standard". A property
  of the stream and the operator's policy, never of the viewer — a VIP viewer
  reads "VIP" on the 1080p row they can play; a free viewer never sees that row
  (the gate removed it, `VipSourcesCard` says where it went); gate off → every
  rung is Standard.
- `QualityRungCard` rows now show a facts line under the size line — audio
  (`audioBadgeText`, e.g. "Hindi + English audio"), stream category, and
  "Resumable" when the rung's `resumable` is true — each only when measured,
  joined with " · "; plus a small `TierPill` ("VIP" in primary container,
  "Standard" quiet) beside the title. Threaded via `RungActions.tierLabel`
  (`viewModel::tierLabelFor`) through both call sites (work + episode).
- New tests: `QualityLadderTest` +3 (category mapping incl. unmeasured → null;
  rung carries audio + category; bare rung shows neither) and NEW
  `LadderWireTest` (2 Gson cases incl. missing fields read as absent).
  One test-header repair during the edit: the new-test insert ate the
  `the screen counts a scope…` test's `@Test` + `fun` header — restored, and
  the file now holds 11 @Test, all followed by a `fun`, braces balanced.

## Checks

- @Composable counts: QualityRungCard 2 → 3 (exactly the new TierPill),
  DetailScreen 15 = 15, DetailViewModel 0 = 0; no strings.xml / PlayerScreen.kt
  changes; every new import used. **Not done:** push (this commit, then CI
  judges — nothing is in flight). Device checks owner-only: a title with a
  probed HLS copy shows "Instant Stream · M3U8" on its rung; a 1080p rung for a
  VIP viewer wears the VIP pill and a free viewer sees the VIP card instead;
  a rung with no stored languages shows no audio line.
