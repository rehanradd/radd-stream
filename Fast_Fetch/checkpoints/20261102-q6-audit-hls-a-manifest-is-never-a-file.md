# 2026-11-02 — q6 supervisor lane `[Q6-AUDIT-HLS]`: audit critical 1 — a manifest is never a file

Branch `q6-audit-hls-20261102` off trunk `9074134`, worktree `/tmp/q6_hls`. Owner command
(Muse/Billo): first-check for duplicates — no origin branch names hls/dash/protocol/manifest,
the four playback/player lanes (`q4-*`, `q1-m3u-400`) carry zero `dash` references, task list
empty; the fix did not exist anywhere.

**The bug, both halves.** `playUrl` is always our own `/api/v1/stream?id=<handle>` redirector,
so it names no medium and Media3's extension inference reads nothing. The projection
(`catalog_v2._protocol_of`) returned `progressive` for any stream/download/both playability with
no `dash` word at all — and `.mpd` sat inside `_HLS_MARKERS`, so the one DASH shape the URL
layer could see was recorded as `hls`: the wrong reader, a different failure of the same family.
The probe half was already there and already unused: `link_health._sniff` names `#EXTM3U` and
MPEG-DASH off the first bytes and journals the verdict in `cat_link_evidence.protocol`, but
`_blend_link` — the write-back that folds measured facts onto `cat_links` — copied
`http_status`/`content_type`/`size_bytes` and never touched `protocol`. A `.mp4`-named endpoint
serving a manifest stayed `progressive` forever. On the client, `LinkClassification.isHls()`
counted `.mpd` as HLS, `protocolOf` had no dash branch mirroring the projection, and a served
`progressive` was never re-checked against the measured `mime_type` before the MediaItem was
built.

**The fix (small, per command).**
* `Fast_Fetch/catalog_v2.py` — `.mpd` split out of `_HLS_MARKERS` into `_DASH_MARKERS`;
  `classify_link` returns the new kind `dash_manifest`; `_protocol_of` answers `dash` for it;
  `_blend_link` now records the newest probe's protocol when it names a medium
  (`_PROBE_PROTOCOL_WORDS = hls|dash|progressive`) — `embed`/`html_page`/`unusable` deliberately
  do not rewrite the column, because "not media" is a kind fact the projection's own kind owns.
* `Fast_Fetch/api_v2.py`, `validate_catalog_full.py` — `dash_manifest` added to the published
  kind vocabularies.
* `App/.../network/models/` — `LinkKind.DASH_MANIFEST`; `isDash()` beside `isHls()` with
  `.mpd` removed from the HLS rule; `classify()` files a dash manifest and, when the protocol
  is `progressive`/unknown, checks the measured content type before it reaches the player
  (audit's client half, no live HEAD: the stored probe MIME is the redirect=0 answer's own
  source); `V1CatalogMapper.resolvedRendition` gains the dash branch the mime re-derivation
  always lacked. `PlaybackMediaItemFactory.manifestMimeType` already normalised aliases and
  needed no change — with the protocol crossing correctly it now fires on the protocol word.
* Tests: `test_catalog_v2.py` pins kind+protocol for both manifests; `test_evidence_writeback.py`
  pins probe-over-guess for hls, dash, and the non-media refusals; new `ManifestProtocolTest.kt`
  pins the client law. Hosted Android CI judges Kotlin — no VM Gradle per command.

**Verdict:** the full `backend-ci.yml` module list — all 41 modules, one invocation each,
exit-code gated — ran green on this tree on the VM before the push (including the two touched
suites and `test_docs_invariants.py` after the continuity edits). Kotlin was not built locally
(no VM Gradle per command); the hosted Android CI at the pushed sha is the judge. Hosted run
ids and per-step verdicts are reported to the supervisor from the branch push.
