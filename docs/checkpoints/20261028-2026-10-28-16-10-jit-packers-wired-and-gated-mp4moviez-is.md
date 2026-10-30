# 2026-10-28 16:10 — JIT packers wired and gated; mp4moviez is metadata-only

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 16:10 — JIT packers wired and gated; mp4moviez is metadata-only

- `c565e6d` adds the two JIT branches to `resolve_live_source` (mxdrop, pkembed) and puts both
  hosts in `_BRIDGE_HOST_MARKERS`, so a failed unwrap is refused in the v1 envelope instead of
  handing a player an HTML page. The unpackers are imported lazily; a missing module disables
  the branches, it cannot break startup. No production DB write, no restart.
- Master gate at `c565e6d` in a clean worktree: `GATE=GREEN`, all 23 backend modules; the
  touched module is now `test_database.py` **72 tests** (was 65). Remote master verified at
  `c565e6d` by `ls-remote`. Production re-checked after the gate: DB mtime unchanged
  (2026-10-27T01:59), service still the one started 2026-10-27 19:47, `?limit=1` 200 in 0.12 s
  warm (a 19 s sample during the gate was CPU contention, not a regression).
- The JIT branches are inert on production data until a staging catalog with mxdrop/pkembed
  rows is merged; no merge happens under the freeze.
- mp4moviez decided: the WIP importer writes posts/releases only (no `sources` table), and its
  one outbound host `links4mad.online` has no DNS record. Staging keeps 29,848 posts /
  54,267 releases as metadata-only; WIP parks outside the tree, no re-scrape.
- MoviesMela crawl settled: 20,770 pages scraped, 118 retired "watch online" article pages
  (YouTube/cloudy.ec layout, no releases). Resolver freshness re-proved live on a new pool:
  3/3 mxdrop, 3/3 pkembed.

