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
- **Current state:** (corrected 2026-10-30 by qoder4; the numbers under this line
  were written against an earlier catalog and three of them are now simply false —
  see the ⚠️ marks. Nothing below was carried forward unverified.)
  1. **Fleet merge complete** — `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`,
     measured tonight **6.40 GB (6,396,899,328 bytes)**, **150,799 `posts`**,
     **15,068 rows flagged `is_18_plus=1`** (stored, filtered from every display
     surface). ⚠️ This line formerly said "all 18 sites … (2.39 GB): 130,007 posts,
     14,078 adult-flagged". Sites merged have since grown (SITES.md §15 records 28
     distinct `source_site` as of 2026-10-29 and a third batch of pagalmovies /
     filmyhit / filmywap landing 31), the file has tripled, and the counts moved.
     The releases/links/post_sources figures below were **not** re-measured tonight.
  2. **Layer-1 projection complete** — `catalog_v2.py` collapsed the posts into
     116,922 works, 1,383,752 releases, and carried **all** 3,456,460 links with
     zero link loss. (Measured against the 130,007-post catalog; the projection is
     being rebuilt against the current file as fleet task #10 — do not treat these
     as current totals.)
  3. **Qoder Commit `27fc043` Landed** — DataStore preferences for all Settings rows,
     sync-account client over `/api/v2/account*`, and local Android compilation on VM
     passed (304 unit tests green, `assembleDebug` passed).
  4. **Dynamic Gateway Server Discovery (Blogger Deadman Switch) Shipped** —
     Live stealth discovery node deployed at `https://rehan-radd.blogspot.com/`.
     Android client engine `DynamicServerDiscovery.kt` integrated and covered by 307
     unit tests. Fresh APK published to `/var/www/download/radd-stream.apk` (23MB).
  5. **Media engine shipped** — commits `79b754d` and `7e2be42`: offline caching,
     200% audio boost ceiling, binge preloading, opt-in LAN sharing, silent
     ladder failover, and `catalog_v2.apply_evidence()` write-back.
  6. **Model layer collapsed** — `viewmodel/ReleaseParser.kt` (528 lines) and the
     duplicate `viewmodel/QualityLadder.kt` are gone; the grammar now lives once
     in `network/models/ReleaseLabelParsing.kt`, layout in
     `viewmodel/ReleaseLayoutBuilder.kt`, the ladder in `player/QualityLadder.kt`.
  7. ⚠️ **Test gates — the former "35/35 offline backend modules green
     (`test_database` 57 …)" line was wrong in both its count and its sizes.**
     The authoritative gate is what `.github/workflows/backend-ci.yml` runs:
     **17 modules, 791 tests, 0 failures**, re-run twice on 2026-10-29/30 at
     `947e17f` and `1aafddb` (locally and on the hosted runner, both green).
     Individual suite sizes measured tonight: `test_database` **133**, `test_vidout` 6,
     `test_catalog_v2` 96, `test_release_descriptor` 24, `test_link_health` 57,
     `test_link_state` 28, `test_evidence_writeback` 12, `test_api_v2` 46,
     `test_usage_stats` 94, `test_operator_isolation` 28. A per-site importer test
     (`test_themoviebox_import.py`, 47) runs at edit time, deliberately outside CI.
  8. **APK endpoint** — `/var/www/download/radd-stream.apk` serves a build from
     2026-10-24, i.e. **before** the model collapse; it is stale, not current.
     `tags: 0`, `releases: 0` — no signed APK has ever been published. The only Release
     run that has ever happened (id 40876596427, `workflow_dispatch`, 2026-10-29 12:50,
     sha `35f9e89`) failed at its very first gate, "🗝️ Verify signing secrets are
     present (fail loudly if not)", and `/actions/secrets` returns an empty list — so
     the four keystore secrets are absent, measured, and nothing can be signed until
     the owner adds them.
- **Blockers / owner decisions:** ⚠️ **the former blocker on this line is false and
  was dangerous.** It said "the live API still serves `fast_fetch.db` (201 posts), so
  the public app today is effectively empty — swapping in the projected catalog is the
  next action and it is a production change", and its "Next step" told the reader to
  *swap `RADD_DB_PATH` and restart `radd-stream.service`*. Measured 2026-10-30 00:35
  from `/proc/<pid>/environ` of the running unit: **`RADD_DB_PATH` is already
  `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`**, the service is
  `active` with 58 MB RSS, and the swap has happened. An agent following the old
  instruction would have restarted a healthy production service for no reason.
  **Never restart `radd-stream.service` — restarts and the first release tag are the
  owner's call.** ⚠️ **The credential line on this bullet was also stale.** It claimed
  the exposed token still sat in `.git/config remote.origin.url`. Measured 2026-10-30:
  `remote.origin.url` is a clean `https://github.com/...` with no userinfo, and neither
  `/opt/radd-stream/.git/config` nor `/home/ubuntu/.gitconfig` matches a token pattern.
  What is *not* fixed is the credential itself — the token kept in `GITHUB_TOKEN` still
  authenticates (it reads `/user` as the owner's own login), so it remains live and
  remains the owner's to revoke. Keep pushing the explicit clean URL; `origin` is now
  safe to use only because the URL is clean, not because the token was withdrawn. The
  at `http://92.4.95.252/` under the owner's own nginx comment "mobile browser access".
- **Next step:** ⚠️ also corrected — the projection swap is done, so the real remaining
  work is the app lane (**Android CI is green on `main`/`master` at `9859b8a`, measured
  2026-10-30 — the old "app lane must land red / 9 failed + 23 lint errors" line is
  retired**; what is left there is a device-verified build, not a green build), bounding
  `/api/data` and rebuilding the v2 projection against the current catalog, the
  canonical re-key reconciliation follow-up, and the monetization knobs. Production
  reads are not free here: `SELECT COUNT(*) FROM posts` costs 0.91 s but
  `… WHERE is_18_plus = 1` costs **26.46 s**, so any admin counter must be a
  pre-computed row, never a scan.

Do not put passwords, API keys, login tokens, or other credentials here.
