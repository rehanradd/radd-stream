# Previous checkpoint — 2026-10-25 (Layer-1 projector landed on the full fleet catalog)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Previous checkpoint — 2026-10-25 (Layer-1 projector landed on the full fleet catalog)

Every number below was queried or run in this session; where an earlier entry
asserted something different, the measured value is stated and the claim is
corrected rather than repeated.

- **Goal:** finish the approved plan's three phases (provenance stops at the HTTP
  edge, one brand file, one player) and get the 18-site merged catalog projected,
  validated, and ready to serve — with the app actually usable out of the box.
- **Catalog (measured on `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`):**
  130,007 posts · 1,598,614 releases · 3,699,521 `download_sources` · 273,778
  `post_sources`. The fleet merge moved 201,020 staging posts across 18 sites and
  recorded **1,460** conflicted posts in total — the "395" quoted previously is only
  katmoviehd's share (`{katmoviehd 395, multimovies 362, world4ufree 174,
  hindilinks4u 119, 7starhd 85, vegamovies 76, ssrmovies 68, 10xflix 59, bolly4u 56,
  hdhub4u 53, rogmovies 13}` from the merge report JSON).
- **In flight:** `catalog_v2.py` is projecting that ledger into the `cat_*` tables in
  place (116,912 works / 1,303,122 prints / 3,699,521 links — zero link loss), now in
  its `_finalize` stage. Progress is printed every `RADD_PROJECT_PROGRESS=N` works
  because a multi-hour rebuild on this one-CPU box previously printed nothing and
  looked hung.
- **Completed this session (all committed and pushed to `master`):**
  - `bd8891e` — Layer-1 projector items finished: `REVISION_KEYS` version vector,
    `cat_id_map` id-churn journal, season-pack expansion when the ledger names the
    span, `cat_parts` derivation, offset majority vote, repack tiebreak, per-release
    `identity_suspect`, durable review resolutions, entitlement write path. Plus the
    crawler fix that stops marking an unreadable/empty page `scraped = 1` — the exact
    mechanism that lost ~1.7k katmoviehd and ~2.4k hindilinks4u URLs.
  - `ec44aec` — hindilinks4u now shares `fast_fetch.py`'s permanent/transient cause
    vocabulary and retry budget, tolerates a locked database while booking and
    saving, and trips the site-dark fuse instead of manufacturing failures.
  - `b5d286d` — `API_V2.md` reconciled to the as-built code (every ✅ re-checked
    against function and test name), `HANDOFF_apidocs.md` annotations complete, and
    `_parts_for_work`'s stale "cat_parts is never filled" docstring corrected.
  - Android: `Brand.defaultServerUrl` feeds `ServerSettingsRepository.serverUrl` and
    `SetupViewModel`, so a branded build opens on real content instead of the server
    form; the last hardcoded host literal left `SettingsScreen.kt`; `ReleaseParser.kt`
    collapsed into `ReleaseLayoutBuilder.kt` and `QualityLadder.kt` moved to
    `player/`; `design/SCREENS.md` Screen 4 redrawn as one row per quality band with
    no site, hoster or address anywhere.
- **Checks run and exact result:**
  - Backend offline: **36 of 37 modules green, 793 tests** (`test_all_sites.py` is the
    live 18-site audit — its result depends on upstream sites, not this repo, and is
    excluded from the offline gate). Notables: `test_catalog_v2` 88, `test_catalog_api`
    114, `test_database` 57, `test_redact` 47, `test_api_v2` 46,
    `test_hindilinks4u` 24, `test_hindilinks4u_retry` 13.
  - Android: `./gradlew --offline testDebugUnitTest assembleDebug` → **BUILD
    SUCCESSFUL**, 31 suites / **284 tests / 0 failures / 0 errors**,
    `app-debug.apk` 22,483,468 bytes. (The "245/28" in the 2026-10-24 entry and the
    "520+ across 15 CI modules" claim were both wrong; these are the measured counts.)
  - GitHub: `bd8891e` and `b5d286d..ec44aec` pushed to `master` on the explicit clean
    URL `https://github.com/radddao/radd-stream.git` via the askpass flow.
- **Not done / not claimed:**
  - `SubtitleOffsetSheet.kt` and `HeroCarousel.kt` do not exist; Priority 4 items 1–4
    are **not started**, not "in flight". The Trakt/cloud sync engine likewise exists
    only as a roadmap line.
  - The "stale test files archived to `/home/ubuntu/project_trash_bin/`" claim moved
    three untracked items; no tracked source or test file was deleted.
- ⚠️ **STALE — CORRECTED 2026-10-30 by the qoder3 lane.** This blocker read "The live API
      still serves `/home/ubuntu/radd-stream-data/fast_fetch.db` (~201 posts). Swapping
      `RADD_DB_PATH` to the projected catalog is an owner decision and is prepared, not executed."
      **The swap has already happened.** Measured by qoder4 2026-10-30 from
      `/proc/<pid>/environ` of the running unit:
      `RADD_DB_PATH=/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`, unit `active`,
      RSS 58 MB. I confirmed the file it points at myself, read-only: 6,396,899,328 bytes,
      `page_size` 4096, WAL, **150,799** `posts`. Neither of us re-counted the legacy
      `fast_fetch.db` tonight — this bullet says ~201 posts and another lane has written 203 for
      the same file, an unresolved two-row disagreement, which is precisely why neither number
      should be quoted without a fresh count. **Do not follow the instruction that used to sit
      behind this line ("swap `RADD_DB_PATH` and restart `radd-stream.service`"): an agent that
      does restarts a healthy production service for no reason. Restarting `radd-stream.service`
      and cutting the first release tag are the owner's calls only.**
  - No Android device or emulator run: this VM has no KVM, so nothing here proves
    on-device behaviour.
- **Next concrete action:** let `_finalize` finish, validate the projected catalog on
  full data (task #37), re-probe the live edge for provenance/adult leaks (task #39),
  then present the pointer swap (task #38) for approval. Merge
  `multimovies_full_20261022.db` (+79,531 releases / +79,782 links the fleet missed)
  before or immediately after the flip (task #45).
- **Blockers / decisions needed (owner):** revoke the GitHub credential embedded in
  `.git/config remote.origin.url` — until then `origin` must never be used; whether
  the public repo keeps documenting hoster and site names (`Fast_Fetch/AGENTS.md`
  bridge table, `domain_registry.json`, `API_V2.md` examples), which is the same
  content removed from the public API; the exposed public Web IDE on this host.

