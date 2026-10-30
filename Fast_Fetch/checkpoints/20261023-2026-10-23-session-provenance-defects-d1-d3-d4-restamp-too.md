# 2026-10-23 — Session: Provenance defects D1/D3/D4 + restamp tool (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-23 — Session: Provenance defects D1/D3/D4 + restamp tool (Qoder)

### Accomplishments
- **D3 (hdtvb mis-stamping)**: `import_hdtvb.py` already bound every site value to
  `SITE_KEY = "hdtvb"` (commit `432ed1b`); the remaining `HDHub4u` mentions were
  docstring/banner/argparse labels that still called the site another name. Those now
  read HDTVB, with the genuine mirror relationship kept as prose only. Grep proof and a
  regression test (`test_hdtvb_import.py`) assert no `'hdhub4u'` data literal survives.
- **D1 (desicinemas provenance)**: `import_desicinemas.py` gained `SITE`,
  `LEGAL_MEDIA_TYPES`, `normalize_media_type()`, `slug_from_url()`, `url`/`slug`/
  `source_site` columns, and an additive idempotent migration
  (`_migrate_posts_provenance`) that backfills them from `raw_meta` and clamps the
  illegal `media_type='episode'` onto the four legal types. Verified on a **copy** of the
  live staging DB: 5,223/5,223 rows gained url+slug+site, media_type became
  movie 2,402 / series 2,821 (identical to what merge_catalogs had been coercing), 0 rows lost.
- **D4 (dead `scraped=2` state)**: one vocabulary in
  `import_9xmovies/moviezguru/world4ufree/bolly4u/desicinemas`: the skip path writes -1
  (never 2) and `PENDING_SELECT` + `QUEUED_SCRAPE_STATES = (0, 2)` drain any legacy 2 row.
  Note `import_bolly4u.py:736` was a **fourth** writer the audit missed.
- **New `restamp_provenance.py`**: stdlib, dry-run by default, `--db` required, refuses a
  production-catalog path without `--force-production`, proves origin from the staging DBs
  plus `domain_registry.json` (a known stamp only moves when both agree), takes a
  consistent `.pre-restamp-<UTC>.bak` before writing, and is idempotent.
  Predicted for `merged_catalog.db` (dry run only, nothing written):
  posts 12 hdhub4u→hdtvb + 5,223 unknown→desicinemas; post_sources 3,870 + 5,223;
  releases 79 + 5,285 = **19,692 rows**; `desicinemas.db` staging 2,195 media_type rows;
  `hdtvb.db`/`hdhub4u.db` staging already clean (0 changes).
- **Tests**: `test_database.py` 54 OK (50 before — another agent added 4 mid-session),
  `test_desicinemas.py` 7→11, `test_hdtvb_import.py` 4→8, new `test_provenance_stamping.py` 12,
  `test_9xmovies.py` 5, `test_moviezguru.py` 6, `test_world4ufree_import.py` 6,
  `test_bolly4u_import.py` 7, `test_hdhub4u_import.py` 25, `test_merge_catalogs.py` 5,
  `test_catalog_v2.py` 35, `test_catalog_api.py` 113 — all OK. Nothing committed or pushed;
  no database was written.

### Next agent should
- Review the dry-run numbers, then run `restamp_provenance.py --db merged_catalog.db --apply`
  (backup is automatic) **before** any further merge, and re-run `--sync-sitemaps`/crawler for
  desicinemas so its own migration runs on the live staging DB.

### 2026-10-24 — init_db ordering fixed; redacted edge deployed; backup green
- `_init_db` now creates `idx_posts_slug`/`idx_sitemap_slug` *after* the migration pass and
  adds `slug` to both migration lists. Reproduced on a synthetic pre-`slug` schema (upgrade
  succeeds, rows kept, indexes created, second run idempotent). The remaining failures when the
  *ledger* `init_db` is pointed at a site's own staging DB are a schema-family mismatch, not this
  bug: those DBs use the canonical staging schema (`canonical_key`/`post_url`/`bridge_url`) and
  were never meant to receive the ledger DDL.
- Live service restarted from committed code: `/api/v1/posts` no longer contains `source_site`;
  `/api/v1/posts/{id}` publishes `option_groups`, `play_url` (our redirector) and no upstream URL;
  `redirect=0` returns only `stream_id/kind/mime/size/resumable/expires_in`.
- Nightly backup: `radd-stream-backup_20261024_154000.tar.gz`, 20 databases, 990 MB,
  sha256 `b20f7b0afee4d4f72f4caee9eeba6241b035ee9e6f1225f4bff553801698e5f7`, uploaded to HF.

### 2026-10-26 — Dynamic Gateway Discovery Landed; Qoder Fleet Sync & Roadmap Reconciliation
- **Dynamic Gateway Server Discovery (Blogger Deadman Switch)**:
  - Deployed stealth fallback discovery at `https://rehan-radd.blogspot.com/` with zero search indexing (`noindex, nofollow, noarchive, nosnippet`).
  - Added `network.gateway_discovery_url` to `brand.properties` and `Brand.kt`.
  - Implemented `DynamicServerDiscovery.kt` in `com.raddstream.app.network` to parse stealth meta tags (`radd-primary`, `radd-backup-*`), probe candidate node latency, and failover automatically.
  - Added unit test suite `DynamicServerDiscoveryTest.kt`; verified full Android test suite with **307 passing tests / 0 failures** (`BUILD SUCCESSFUL`).
  - Fresh APK compiled locally on VM and deployed to `/var/www/download/radd-stream.apk` (23MB).
- **Qoder Status & Fleet Audit**:
  - Qoder commit `27fc043` landed on `master` with DataStore preference persistence, `/api/v2/account*` client, dynamic image sizing (`CatalogImage`), and local compilation fixes.
  - 250 backend tests passing green (`test_database`, `test_vidout`, `test_catalog_v2`, `test_release_descriptor`, `test_link_health`, `test_backup_manager`).
  - Full backup snapshot `radd-stream-backup_20261026_124721.tar.gz` (1.72GB) successfully uploaded to Hugging Face dataset.
  - Remaining priority backlog formally re-anchored in `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md`: Priority 6 Admin Monetization Card, Priority 4 Pure Cinema Mode & Hero Carousel, Priority 5 Desi Cine-Finder.

- **Fleet Merge 100% Completed**: All 18 staging databases merged into `/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` with KatMovieHD re-derived (`merge_conflicts` measured at 1,460; 130,007 posts, 1,598,614 releases, 3,699,521 links).
- **Core Engine Shipped**: Offline cache engine, adaptive quality ladder, 200% audio boost, binge preloader, and LAN P2P sharing landed in commits `79b754d` and `7e2be42`.
- **App Architecture Refined**: Replaced 528 lines of redundant `ReleaseParser.kt` with unified `ReleaseLayoutBuilder.kt`.
- **Priority 4 Roadmap Bound to Qoder**: Tasked Qoder via `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md` to deliver:
  1. Subtitle Offset & Online Subtitle Search (`SubtitleOffsetSheet.kt`)
  2. Netflix-Grade Hero Carousel (`HeroCarousel.kt` on `HomeScreen.kt`)
  3. Subtitle & Audio Styling Customizer (font size, yellow/white styling, box background)
  4. Trakt.tv / Cloud Watchlist Sync Engine
  5. Universal Software Audio Codec Fallback (AC3/EAC3/DTS for budget phone audio)
  6. Pure Cinema / Ghost Mode (Sub-Focus Unobstructed Playback: zero pause scrim/icons, active gestures, edge hairline HUD, 3s instant rewind)
  7. 2.0x Long-Press Speed Optimization Engine (Asynchronous MediaCodec + Smart Turbo 1.6x/2.0x scaling to eliminate freeze on 4GB budget phones)
  8. Night-Mode Dialogue Normalizer (Dynamic Range Compression) & Bluetooth Audio-Sync Delay Slider
  9. Priority 5: The "Desi Cine-Finder" (South Asia TikTok/Reels clip & scene identifier: 0 video upload, client-side keyframes, on-device OCR, Lens intent bridge, Share-to-Stream sheet, and SQLite FTS5 natural language plot search)
  10. Priority 6: Sovereign Admin & Monetization Blueprint (`Fast_Fetch/admin_panel.py`: loopback-only
      operator panel, remote config, broadcast alerts, anti-crack HMAC signed payloads, 17/17 operator
      isolation tests passing). The accompanying business-side spec and account-setup guide are
      deliberately **not in this repository** — they name payment rails and an operator location, and
      publishing them here (this tree is mirrored to a public dataset) is the owner's call, not an
      agent's. Ask before writing either into a tracked file.
- **Sanitation**: What actually moved was three untracked items — `load_catalog.py`, a 271 MB stale
  `merged_catalog_stale_prerelease_fix.db` and a leftover build directory — now in
  `/home/ubuntu/project_trash_bin/`. No tracked source or test file was deleted (the only tracked
  removals this cycle are the four Kotlin files task #23 replaced). Spared `Fast_Fetch/multimovies.db`
  after discovering it contains 612k releases (80k more than staging).

