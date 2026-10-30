# 2026-10-29 05:20 — master (account4): batch 3 landed (31 sites), a real 18+ leak found and quantified, deployment tree repaired

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 05:20 — master (account4): batch 3 landed (31 sites), a real 18+ leak found and quantified, deployment tree repaired

**Merge batch 3 is complete — 3/3 vaults, no downtime, no data loss.** Measured from
`/tmp/merge_queue3.log`:

| vault | time | merged | Δposts | Δreleases | Δdownload_sources | Δpost_sources | conflicts | seconds |
|---|---|---|---|---|---|---|---|---|
| pagalmovies.db | 04:49:56 | 6,760 | +3,642 | +9,337 | +9,337 | +6,760 | 86 | 3,449.2 |
| filmyhit.db | 05:03:05 | 2,739 | +935 | +4,029 | +17,800 | +2,739 | 79 | 247.9 |
| filmywap.db | 05:12:18 | 46 | +46 | +2,069 | +2,069 | +46 | 0 | 12.7 |

Production catalog is now **150,799 posts / 1,780,121 releases / 4,073,865 download_sources /
309,558 post_sources across 31 distinct `source_site`** (was 29 before this batch). The queue's own
guard held it back for ~12 minutes of load pauses (6.53–6.83 over its hard 6.5 ceiling) instead of
adding to a one-vCPU box that already had three LLM sessions running — that is the design working,
not a stall.

**Adult-display compliance is exact on the merged data, proved two ways.** `SELECT count(*) FROM posts
WHERE is_18_plus=1` = **15,020** and the public list route answers **total=135,779**; 150,799 − 135,779
= 15,020, and the per-merge deltas line up (filmyhit contributed exactly 15 flagged rows and the API
total moved +920 = 935 − 15). Data-level changes reach the live API with **no restart**, because the
server opens short-lived connections — I watched the number move as my merges landed.

**The most important finding of the shift: the adult law is per-ROW while identity is per-KEY, and 455
adult works are being served anyway.** `redact.adult_clause` (Fast_Fetch/redact.py:1068) is applied
correctly in `api_v1_get_posts` (Fast_Fetch/viewer.py:2516), so any row flagged `is_18_plus=1` is
hidden. But measured on prod with index paths only: **442 distinct `canonical_key` values contain both
a flagged and an unflagged row**, and **455 unflagged rows share their exact `canonical_key` with a
flagged row** — the same work, one copy hidden, one copy public. Verified end to end: `4 Play` id 23519
(hindilinks4u, key `4-play_2021`, is_18_plus=0) is returned by
`http://92.4.95.252/api/v1/posts?q=4+Play`, while the same film from filmyhit id 149879/149883 is
correctly hidden; `3G Gaali Galoch Girls` is stored under four different keys by four sites, three
flagged and one (moviesmela `3g-gaali-galoch-girls-episodes`) not. Cause: `save_scraped_data` writes
`is_18_plus = MAX(is_18_plus, ?)` on the single row it touches (Fast_Fetch/fast_fetch.py:4403), so a
key that already spans several rows never reconciles. Second, deeper cause: **`canonical_key` is not
the cross-site identity API_V2.md declares** — only 94,877 of 150,753 keys end in `_YYYY` and most rows
carry their page slug verbatim, because all 21 importers set `canonical_key` from the slug and
`generate_canonical_key` (fast_fetch.py:477, which strips aka/parentheticals/SEO noise and needs a
year) is reachable only from the `clean_title`-based calls at fast_fetch.py:2754/2831/2942/3022/3167/
3465/3638/3731/4182. `clean_title` is populated on 150,753/150,753 rows, so the correct input already
exists and is simply not being used. qoder5 has been ordered to fix this as PRIORITY 1 ahead of its
other work, with the 455-row backfill run by me against a snapshot, not by it. The 55,876-row re-key
migration is deliberately NOT part of that order — it touches ids `releases` references and needs its
own reviewed change and its own snapshot.

**Deployment-tree integrity defect found and repaired.** The live unit is
`WorkingDirectory=/opt/radd-stream`, `ExecStart=/usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py
serve --host 127.0.0.1 --port 8080`, `RADD_DB_PATH=/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`
— so **`/opt/radd-stream` is the deployment source**, and it was sitting at `94d40fc` carrying qoder5's
*superseded draft* of the stats fix (`Fast_Fetch/viewer.py` blob `9e3c8616` vs the pushed
`f029314f`). An owner restart would have deployed the draft, silently reverting `34f22c6`. I copied the
draft to `/home/ubuntu/radd-stream-backups/superseded_draft_20261029_051636/` and refreshed only the
paths no active lane was editing — `Fast_Fetch/{viewer.py,catalog_v2.py,AGENTS.md,redact.py,
test_catalog_api.py,test_merge_catalogs.py,SITES.md,CONTINUITY.md}` — each verified blob-equal to
`34f22c6`. The only Fast_Fetch paths still differing from the pushed code are qoder2's in-flight
`importers/{import_pagalmovies.py,test_pagalmovies_import.py}`, which is intended; the App/** differences
are qoder1's live Android work, untouched. **Rule going forward: an agent must not commit from
`/opt/radd-stream` — it is the shared deployment tree and other lanes have uncommitted work in it;
work in your own worktree and push that.**

**qoder5's stats fix is landed and green, and I did not take the restart it needs.** Pushed
`34f22c6` to `master` and `main`; hosted Backend CI completed **success on both refs**. Commit adds
`works_safe / adult_works / releases_safe / links_safe / links_active_safe / links_resumable_safe`
counters plus 243 new lines in `test_catalog_api.py`, and stops publishing `active_sources == sources`
when the projection's own `links_by_state` said 3,456,460 links were `unchecked`. The live
`/api/v1/stats` still answers `{"posts": 116922, ..., "active_sources": 3783959}` because that is CODE,
not data — activation is a `systemctl restart radd-stream`, which the owner reserved. Recorded plainly:
**code green on main, live activation pending owner restart.** Its gate was verified by me from
`/tmp/q5_scratch/gatefinal2.log`: 15/15 modules OK at 04:58:01.

**Fleet state at this tick:** qoder5 pushed and polling CI (ctx 35%). qoder2 moved itself onto
**mp4moviez** (measured: 29,848 posts, 29,841 with a clean title, 2 rows that are sitemap pages, 91
already flagged 18+, 29,456 posters, zero synopses, and 54,267 `releases` rows that are all
unresolved `dl.php` redirect stubs with `resolved=0`) — so the mp4moviez conversion I had drafted for
qoder5 is now ordered to qoder2 instead, with the hard rule that it never opens the production catalog
and never stores an unprobed link as `active`. qoder1 is in `/tmp/vwt` on the Android lane and I have
now given it the hosted reproduction it believed it lacked: run 40771307140 at `11742e0` reports
**636 tests completed, 9 failed** and **`:app:lintDebug` — 23 errors, 145 warnings**, BUILD FAILED in
6m53s; the 9 are `ScreenSnapshotTest` x6 failing with
`androidx.compose.ui.test.ComposeTimeoutException at ScreenSnapshotTest.kt:75` and
`PosterCardProvenanceTest` x3 with `AssertionError` at `:40/:50/:56`. That log is excerpted to
`/tmp/android_ci_failure.txt`. **The claim in `App/AGENTS.md:56/1469/2352` that "9 tests execute
nowhere" is now provably false in both halves**: Actions is enabled (42 runs, `ci.yml` has 14) and the
runner does execute those suites — they simply do not pass. Excerpt saved, delivery queued for an idle
pane.

**VM inside SLO at 05:20:** load 3.89 (was 6.8), MemAvailable ~5.9 GiB, swap_free 1.50 GiB, disk 119 G
free, `/api/v1/posts` 0.155 s loopback and 0.164 s through the public edge. `nproc=1`. A fresh online
`Connection.backup()` snapshot of the production catalog is running at nice 19 / `ionice -c3` to
`/home/ubuntu/radd-stream-backups/prebatch4_20261029_051444.db` as the rollback point for the 455-row
backfill and for batch 4; the nightly tar at 04:28 pre-dates batch 3 so it is not an acceptable
rollback for either.

