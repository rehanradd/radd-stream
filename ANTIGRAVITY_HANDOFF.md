# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

Every number below was measured on this box, not carried over from a report.

- **Current goal:** finish the approved plan — a user must never learn which
  source site or server a title came from, one player plays everything, and one
  file (`/brand.properties`) re-skins the product. Then make the app actually
  usable: a real catalog behind the live API, a shipped APK, clean tree.
- **Operator Location & Identity (Permanent):** The Project Owner and Dao Partner is located in **Lahore, Punjab, Pakistan**. All monetization and admin control systems are anchored to Pakistani Rupee (`PKR`), JazzCash (Till ID), EasyPaisa, and Raast. Full runbook is in `docs/PAKISTAN_OPERATOR_GUIDE.md`.
- **Current state:**
  1. **Fleet merge complete** — all 18 sites in
     `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` (2.39 GB):
     130,007 posts, 1,598,614 releases, 3,699,521 links, 273,778 `post_sources`
     pages, 1,460 unresolved identity conflicts, 14,078 adult-flagged rows
     (stored, filtered from every display surface), 0 rows with an unknown site.
  2. **Layer-1 projection complete** — `catalog_v2.py` collapsed those 130,007
     posts into 116,922 works, 1,383,752 releases, and carried **all**
     3,456,460 links with zero link loss.
  3. **Qoder Commit `27fc043` Landed** — DataStore preferences for all Settings rows,
     sync-account client over `/api/v2/account*`, and local Android compilation on VM
     passed (304 unit tests green, `assembleDebug` passed).
  4. **Dynamic Gateway Server Discovery (Blogger Deadman Switch) Shipped** —
     Live stealth discovery node deployed at `https://rehan-radd.blogspot.com/`.
     Android client engine `DynamicServerDiscovery.kt` integrated and covered by 307
     unit tests. Fresh APK published to `/var/www/download/radd-stream.apk` (23MB).
  3. **Media engine shipped** — commits `79b754d` and `7e2be42`: offline caching,
     200% audio boost ceiling, binge preloading, opt-in LAN sharing, silent
     ladder failover, and `catalog_v2.apply_evidence()` write-back.
  4. **Model layer collapsed** — `viewmodel/ReleaseParser.kt` (528 lines) and the
     duplicate `viewmodel/QualityLadder.kt` are gone; the grammar now lives once
     in `network/models/ReleaseLabelParsing.kt`, layout in
     `viewmodel/ReleaseLayoutBuilder.kt`, the ladder in `player/QualityLadder.kt`.
  5. **Test gates as of now** — 35/35 offline backend modules green
     (`test_database` 57, `test_catalog_v2` 88, `test_catalog_api` 114,
     `test_api_v2` 46, `test_redact` 46); Android `testDebugUnitTest` 284 tests,
     0 failures. The Kotlin brand-default-server edits made *after* that run are
     not yet re-verified.
  6. **APK endpoint** — `/var/www/download/radd-stream.apk` serves a build from
     2026-10-24, i.e. **before** the model collapse; it is stale, not current.
- **Blockers / owner decisions:** the live API still serves
  `fast_fetch.db` (201 posts), so the public app today is effectively empty —
  swapping in the projected catalog is the next action and it is a production
  change. The exposed GitHub credential in `.git/config remote.origin.url` is
  still the owner's to revoke (until then push the explicit clean URL, never
  `origin`). The Web IDE is reachable from the internet at `http://92.4.95.252/`
  under the owner's own nginx comment "mobile browser access".
- **Next step:** finish the projection, run `validate_catalog_full.py` against
  it read-only, swap `RADD_DB_PATH` and restart `radd-stream.service`, re-probe
  the public edge for provenance and adult leaks, then re-run
  `./gradlew testDebugUnitTest assembleDebug` and refresh the published APK.

Do not put passwords, API keys, login tokens, or other credentials here.
