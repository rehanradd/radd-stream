# 2026-10-27 — Session: filmiy.in gets its own staging importer (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: filmiy.in gets its own staging importer (Qoder)

- **New module, no dispatcher edits.** `Fast_Fetch/importers/import_filmiyin.py` (~800 lines,
  stdlib only) scrapes `https://filmiy.in` into `/home/ubuntu/radd-stream-data/filmiyin.db`
  and nothing else. `fast_fetch.py`, `viewer.py` and the production catalog were not touched —
  strict staging isolation, and no merge without the operator's word.
- **The task spec's recon was wrong and the code follows the site, not the spec.** It claimed a
  "protection layer: none" and supplied a sample post with 0 embeds and two download mirrors.
  In reality every page sits behind a Cloudflare JS challenge and the site's only mirrors are
  `new1.filesdl.co/cloud/<Laravel-encrypted token>`. Those are stored verbatim as
  `js_required` — the §4.12 greenmotors.cc precedent — never dropped, `is_temporary=0`.
- **Four bugs the first sample run exposed:**
  1. related-post cards were harvested as this title's downloads (24 releases where 3 exist) →
     same-host links are navigation, excluded in `harvest_links`;
  2. releasing per `canonical_key` silently deleted the earlier page's prints when one title is
     published on a season page and an episode-pack page → added `releases.origin_url` and
     replace per page, with a regression test;
  3. title-derived keys stranded rows every time the cleaner improved (12 posts became 33 after
     an edit) → `build_canonical_key` derives from the URL slug, right-trimming packaging tokens
     but keeping numeric titles (`3-idiots`, `jailer-2`) by only eating a number after
     `episode/ep/part/extras/unseen/bonus/add`;
  4. `imagecloud_*` thumbnails from the shelf became this title's backdrops → screenshots are
     scoped to `/uploads/posts/` and must match the slug.
- **18+ flagging is deliberately narrower here.** UnCut appears on every title, so it is not a
  signal; bare `sex` is not either (`Gail Daughtry and the Celebrity Sex Pass` is a real film and
  its title is preserved whole). Ambiguous words — `bold`, `lust`, `sensual` — count only in the
  site's own labels, never in a synopsis, because a false positive hides a mainstream series from
  every display surface: `Dil Padosi` was flagged by "a bold, glamorous couple" and now is not,
  while `Mocktail (18+)` still is.
- **Provenance stops at this edge.** `scrub_brand()` on display strings, tracker hosts excluded,
  same-site links dropped, and a leak sweep over the staging rows returns NONE.
- **Scale:** `sync` queues 5,740 URLs; a 150-page sample crawl produced 147 posts / 716 releases
  / 716 sources across 480p·720p·1080p·2160p, idempotent on re-crawl.
- **Not done, on purpose:** `fast_fetch.py` dispatcher integration (DEFAULT_DOMAINS,
  `normalize_url`, a `sync_sitemaps()` block, `SITE_CHOICES`) and the remaining 5,590 queued pages.

**Checks:** `importers/test_filmiyin_import.py` 38 OK (all offline, `http_get` patched),
`test_database.py` 64 OK, `test_vidout.py` 6 OK, `python -c "import fast_fetch"` OK.

---

