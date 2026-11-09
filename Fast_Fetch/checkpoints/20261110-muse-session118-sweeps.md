# Session 118 sweeps — MovieNestBD letters, HarPal /programs index, MoviesDrive beyond 10 (2026-11-10)

**Scope:** the fuller Phase E sweeps for the three Session 118 first-batch
importers. No live-DB writes, no merge, no deploy — staging DBs only; the
data merge is a separate parent gate job. Branch `session-118-sweeps`,
base main `399f747`.

## 1. Pre-sweep probes (Oracle VM, 2026-11-10 ~00:30–00:36 PKT)

- **MovieNestBD** `/api/v1/search?q=a&page=1`: 200, count **16,353**
  (was 16,341 on 2026-11-09), 909 pages, `has_next` true, 18 rows/page.
  API alive and unchanged. Full sweep = 36 letters a-z0-9, paginated to
  `has_next=false`; the sync dedupes by `loc` (ON CONFLICT), so letter
  overlap costs pages, not duplicate titles.
- **HarPal Geo** homepage: 200, 321 KB, **11 programs** via the real
  extractor (Session 118's "31" was the raw `/program/` href count incl.
  episode links — corrected in the importer docstring). NEW surface:
  `/programs` is a **30-page index** (`/programs`, `/programs/2`, …;
  `?page=N` returns page 1 again): page 1 = 24 programs, ~18 new per
  page through page 29, page 30 adds 0 (dedup-stop fired); **509
  programs total**, not 11. The pager's link window only shows up to
  page 12 — the loop, not the pager, finds the end.
- **MoviesDrive** `new1.moviesdrive.cyou` wp-json: **302 → new2**
  (`https://new2.moviesdrive.cyou/wp-json/wp/v2/posts`, query string
  dropped by the redirect). Followed: 200, `X-WP-Total: 9658`,
  `X-WP-TotalPages: 966` (at the redirect's default per_page=10).
  A stale base breaks paging — the redirect drops `?page=`/`?per_page=`,
  so every page request would return the same default 10 posts.

## 2. Fixes in this branch

- `domain_registry.json`: moviesdrive `active_base_url` new1 → **new2**,
  new2 prepended to `known_mirrors`, `rotation_history` records the
  2026-11-10 rotation, `last_verified`/`last_checked`/`updated_at`
  2026-11-09T19:35:00Z.
- `import_moviesdrive.py`: `DEFAULT_BASE_URL` → new2 + docstring rotation
  note. `test_moviesdrive_import.py`: registry assertion → new2.
- `import_harpalgeo.py`: `sync_programs_to_db` now walks the homepage
  AND `/programs` pages 1..N with a dedup-stop (first page adding no new
  program, or non-200; cap `PROGRAMS_INDEX_MAX_PAGES = 50`). The
  homepage-only sync was missing ~98% of the catalog (11 of 509).
  `test_harpalgeo_import.py`: +1 test (homepage + /programs union,
  dedup-stop at `/programs/2`, 3 fetches) — 10 → **11 OK**.

## 3. Staging counts BEFORE the sweeps (VM, 00:30 PKT)

| site | posts | releases | sources | sitemap scraped | pending |
|---|---|---|---|---|---|
| movienestbd | 20 | 20 | 54 | 20 | 16 |
| harpalgeo | 5 | 42 | 42 | 5 | 6 |
| moviesdrive | 10 | 49 | 457 | 10 | 9,638 |

MoviesDrive's sync had already walked the full wp-json list (9,648 posts
then; 9,658 now) — the sweep is the detail scrape of the 9,638 pending.
MovieNestBD's 16 pending are letter-"a" leftovers (sync capped at
`--limit 20` in the first batch). HarPal's re-sync (new /programs walk)
discovered **509 programs total, 504 pending** — the /programs index,
not the homepage, is the real catalog.

## 4. Launch (detached on the VM, from the branch worktree)

Worktree `/tmp/sweeps118-work` (VM clone `/tmp/muse-panel-push`,
branch `session-118-sweeps`). All three run detached with `nohup`, logs
in `/tmp/sweeps118-*.log`; state lives in `sitemap_cache`, so a reboot
or a killed run resumes where it stopped.

- MovieNestBD (longest): `--sync-search --delay 0.3` (all letters) then
  scrape pending `--workers 3 --delay 0.4`.
- HarPal: `--sync-programs` (homepage + /programs) then scrape pending
  `--workers 2 --delay 0.5`.
- MoviesDrive: `--sync-posts` (re-sync picks up the +10 new posts) then
  scrape pending `--workers 4 --delay 0.4`.

Rates are modest on purpose (small sites, one page at a time on the
syncs). Load at launch ~0.2; the parent's gate deploy (live tree
399f747, service+panel restart) was in flight at the same time — the
sweeps touch neither the live tree nor the service.

Launched 00:38–00:39 PKT: MovieNestBD chain PID 1408837, HarPal
1410253, MoviesDrive 1410254. First HarPal/MoviesDrive launch failed
instantly: `cd DIR && nohup ... &` backgrounds the `cd` too, so those
two chains ran in /home/ubuntu (`can't open file`); relaunched with
absolute script paths + `</dev/null`. MovieNestBD was unaffected
(sync running, PID 1408841). HarPal sync finished in ~20 s: 509
programs, dedup-stop at page 30. MoviesDrive sync walking 97 wp-json
pages on new2 (page 20/97 at +20 s).

## 5. Tests (this tree, CI way, before push)

- `test_harpalgeo_import.py` **11 OK** (was 10, +1 new)
- `test_moviesdrive_import.py` **10 OK**
- `test_movienestbd_import.py` **9 OK**
- `test_domain_resolver.py` **39 OK**
- Registry JSON parses. Importer md5s on the live tree match this
  branch (verified before the gate deploy ff'd the live tree to
  399f747 — the triple merge did not touch these three importers).

## 6. What remains (parent-gated, NOT this session)

- Sweep completion + final staging counts per site (logs above).
- Data merge via `merge_catalogs.py` (parent gate) + rev-7 projection
  rebuild — the mp4moviez merge is ahead of these in the same queue.
- jiofiles unwrap is still a separate crack task (MovieNestBD rows are
  catalog + bridge, not proven playable).
- HarPal reality-show / movie "programs" (Pakistan's Got Talent,
  Maula Jutt, Deemak, …) have no episode structure — the importer
  yields None for them (marked scraped=-1); that is by design, not a
  failure.

## 7. MoviesDrive sitemap dedupe — rotation orphans old locs (00:44–00:46 PKT)

After the new2 re-sync, `sitemap_cache` held **19,306 rows for 9,658
posts** (9,648 new1 + 9,658 new2): the sync upserts on `loc`, so the
rotated domain created a twin row per post. Worse, `save_post_record`
marks `data["url"]` (the WP post's current link = new2) scraped, so
processing a new1 row marked its new2 twin while the new1 row stayed
pending — the run would have processed every post twice (~4 h instead
of ~2) and left 9,638 new1 rows pending forever.

Fix: stopped the chain (SIGTERM, graceful), deleted the 9,648 new1
rows sharing a slug with a new2 row (0 new1 rows left), found 2
scraped new2 rows with no post and unmarked them for re-processing,
relaunched on the deduped 9,406 pending (chain PID 1412064, 1.6
posts/sec, 0 failed). No duplicate posts resulted: `posts.url` is
UNIQUE and the save path updates on identity match — 0 dup urls / 0
dup canonical_keys measured. Lesson: after a domain rotation, dedupe
`sitemap_cache` by slug before scraping; the mark-by-`data["url"]`
pattern assumes loc == post link and breaks on rotation (shared
pattern, not changed in this session — the dedupe is the fix).

## 8. Progress at 00:47 PKT (sweeps still running detached)

| site | posts | releases | sources | sitemap scraped | pending |
|---|---|---|---|---|---|
| movienestbd | 20 | 20 | 54 | 20 | 7,900 |
| harpalgeo | 172 | 1,221 | 1,221 | 172 | 337 |
| moviesdrive | 301 | 1,547 | 9,010 | 303 | 9,355 |

- HarPal 160/504 programs, 0.48/sec, 0 failed — ~12 min to finish.
- MoviesDrive 50/9,406 posts, 1.59/sec, 0 failed — ~1.6 h to finish.
- MovieNestBD sync is the slow one: the search API takes ~1.1 s/page
  (measured), letter "a" alone is 909 pages (~17 min); the 36-letter
  sync will take 2–4 h, then the detail scrape (~7.5 titles/sec at
  3 workers). The sync prints only when a letter finishes, so an empty
  log is normal mid-letter. Load 1.48 with the mp4moviez merge and the
  MovieBox gapfill running alongside — the sweeps are network-bound
  and stay out of their way.
