# 2026-10-28 17:05 — anime reads its flag, the comment guard reads Kotlin, and the JIT keeps its lifetime

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 17:05 — anime reads its flag, the comment guard reads Kotlin, and the JIT keeps its lifetime

- **§4-A closed on the client.** `Post` now decodes `is_animated` (the JSON number `1`/`0`, read by
  the existing `LenientBooleanAdapter`), `WorkTypeLabel.of` is the single owner of the type word a
  tile, banner or detail header paints, `V1CatalogMapper.animatedFromList` answers the wire flag
  instead of a hardcoded `null`, and Search gained a real Anime chip plus an `anime` group key fed
  by `WorkType.fromContentType`. An absent key stays `null` — unknown is never "not animated", and
  a flagged *movie* stays a movie because the server's own `work_type_for` only promotes the
  series family.
- **The comment guard now reads Kotlin, not the common case.** `CommentBalanceTest.scan` closed a
  raw string at the first `"""` of a run; Kotlin closes at the **last** three, so a legitimate
  `"""…""""` leaked one quote into a phantom string and desynchronised the rest of the file. It is
  that false positive — not the anime code — that failed qoder1's 16:05 build. The scanner counts
  the run now, with two controls: such a string is not flagged, and a nested opener after it still
  is.
- **Task #21 closed.** `818b435` keeps the whole packer verdict in the JIT row: a signed
  `expires_in` is recorded with `observed_via="signed_params"` when the CDN declares no window,
  and the byte endpoint's `mime_type`, `file_size_bytes`, `http_status` and `is_resumable` are
  persisted. Three new tests pin the cached answer, the expired-window refresh and the rule that
  host headers beat the signed number.
- **Gates.** App: `/tmp/qbuild.sh -Dorg.gradle.jvmargs='-Xmx1536m' :app:compileDebugKotlin
  :app:testDebugUnitTest` → `GRADLE_EXIT=0`, `OVERLAP=NO`, **588 tests / 74 suites / 0 failures /
  0 errors / 0 skipped**, all 74 XMLs from that one run. Backend in the merged tree:
  `test_database.py` 75 OK, `test_vidout.py` 6 OK, `importers/test_host_resolvers.py` 141 OK.
- **Shared-worktree hazard, recorded:** switching this worktree to `app/anime-20261028` meant
  qoder3's commit `818b435` landed on that branch rather than master. It was reviewed and gated
  before the fast-forward, so nothing unverified rode along — but branch switches on this host
  move every agent's HEAD, not just the switcher's.
- Production untouched: no restart, no write to `fast_fetch.db`; `merged_catalog` not touched.

