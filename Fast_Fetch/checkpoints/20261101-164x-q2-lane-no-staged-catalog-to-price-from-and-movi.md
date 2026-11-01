# 2026-11-01 16:4x — q2 lane: the pricing route the ruling assumes does not exist, and MovieBox is not what the records say

Tag: `[Q2-NO-STAGED-CATALOG-TO-PRICE-FROM]` · Tasks #18 #19 #21 #24 · Branch `q2-census-pricing`
· Predecessor: `20261101-161x-q2-lane-the-index-question-the-pricing-tool-refu.md`
· Artifacts: `Fast_Fetch/HEAD_PASS_STAGING_DECISION_20261101.md` §8, `Fast_Fetch/MOVIEBOX_COVERAGE_20261101.md`

## The ruling, and the sweep it needed before it could be followed

*"Keep the guard: do not change `resolve_target` to allow plan-only production reads; price from a
staged or non-production catalog."* The guard is unchanged — I did not touch `price_projection.py` or
`resolve_target`, and §2 of the decision artifact now says so. But the second clause has **no target
on this host**, so I swept for it: all **49** `.db` files in the staging data dir, `mode=ro` +
`query_only`, `sqlite_master` table names only, zero row content, 18 sidecar-bearing vaults skipped
and listed rather than opened.

**26 openable vaults, every one 2/4 Layer-0** (`posts`, `releases`, `sources`, `sitemap_cache` —
missing `download_sources` and `post_sources`); 5 forbidden by name; **18 barred by debris; full
four-table shape among openable non-production files: zero.** The four-table shape is *created by the
merge*, and the merge writes it into exactly the names the guard refuses. So the ruling's route means
either manufacturing a staged ledger — which prices a shape, not this data — or accepting that
**Decision B's measured `VmHWM` is the only instrument left that can size the projection.** That is a
cleaner position than the one I had, and the owner's refusal of the guard change is what produced it.

**#18 sampled, not assumed, then barred again:** load 5.24 / 3.76 / 4.26 with busy CPU **99.7 %** at
16:32. Both clauses failed; the CPU one by 50 points.

## The finding that outranks it: `themoviebox.db` is not 44 posts / 0 releases / 0 sources

The 2026-10-30 crawl checkpoint records that file as empty of releases. Measured now (mtime
**2026-10-31 06:58**): **44 posts, 218 releases, 60 sources**, and referentially clean — **0 orphan
releases, 0 orphan sources**. The old line stays verbatim where it is (absorbed trunk text, true when
written); the correction is the artifact. What that leaves for #21 is *specific*:

- `season_number` non-null in **218/218**, `episode_number` non-null in **0/218** — the releases are
  **season packs** (`Vikings S1-S6 S00 SD`), so Rule §10's "all seasons/episodes" is unmet by parser
  granularity, **not** by a fetch gap. No re-crawl fixes that; `import_themoviebox.py` does.
- **14 of 44 posts have no source at all**; only 60 of 218 releases carry one. Two posts have no
  releases either (`Squid Game` 2021, `The Night Agent` 2023).
- **60/60 sources are `playback_type='direct'`, `service='themoviebox'`, `bridge_url` empty in
  218/218** — the Dooplay embed path landed in `66769c7` and has produced **zero rows in this vault**.
  Three detail fetches answer whether that endpoint is dead or untested, which is #19's first move and
  cheaper than any crawl.
- All 44 posts are `media_type='series'`, and `sitemap_cache` holds exactly 44 `loc` rows — so #24's
  ceiling is a **detail-tier sample with an unmeasured gap above it**, and must not be phrased as
  "the catalog".

## Read class, named because it is the part someone might overrule

§1–§5 of the coverage artifact rest on a **content read of a staging vault** — 299,008 B, `mode=ro`,
counts and `EXISTS` joins over 44/218/60 rows, two `LIMIT 8` label listings, no `raw_meta` value
printed, nothing written. The freeze bars whole-table staging reads as a category; I judged a 299 KB
file to be the census class #20 and #37 already established and said so in the artifact instead of
letting the size of the file excuse the fact of the read. If the owner wants it un-read, the numbers
are re-derivable in one command and nothing else in this segment depends on them.

## Handoffs

- **owner:** the pricing route needs a *manufactured* staged ledger or it needs B's measurement —
  which needs a window under 50 % CPU (the box has read 74.6 / 92.7 / 93.1 / 99.7 % all afternoon).
- **whoever owns `import_themoviebox.py`:** `episode_number` is NULL in every one of 218 releases.
  That is the §10 gap and it is a parser change with a test, not a crawl.
- **#19 when unfrozen:** 3 embed probes → 14 source-less posts → 2 release-less posts → episode
  lists last, host-gated, writes only to `themoviebox.db`.

## 16:5x correction — the embed claim in this file is wrong, and the numbers moved

The line above reading *"60/60 sources are `direct`/`themoviebox` with `bridge_url` empty in 218/218 —
the Dooplay embed path from `66769c7` has produced zero rows in this vault, answerable with 3 detail
fetches"* is a misreading of a schema as a symptom. `import_themoviebox.py` is an **Aoneroom-backed
direct site by construction**: `SERVICE = "themoviebox"`, `MEDIA_HOST_HINTS = ("aoneroom.com",)`, and
the module writes `source_url == final_url` on purpose. All 60 URLs are
`macdn.aoneroom.com/media/vone/<date>/<hash>-{sd,ld}.mp4` (56 `-sd`, 4 `-ld`) — the works' prints.
There is no embed gap, so §4's row 1 is re-aimed at the 14 source-less series instead.

The measurement that replaced it is worse than what I mistook for a gap: **30 of the 218 release rows
are byte-identical twins** (188 distinct `(key,label)`, max 2 copies, 30 of the 42 populated works
affected), and each twin carries its own copy of the same source file — so the 60 sources are really
**30 prints**. The merge cannot catch this: `UNIQUE(release_id, url)` is keyed on `release_id`, so two
sibling releases with one URL are two rows no constraint calls duplicates, and they propagate into
`download_sources` as a doubled rendition count. `merge_catalogs._collapse_identical_releases` now
collapses them where the rows are read, reports `stats["duplicate_releases_dropped"]`, and is covered
by two offline cases including a positive control (same label + quality, different file = two prints,
must survive). **Not executed locally — local test-module runs stay frozen; CI's
`test_merge_catalogs.py` is the judge.** The 30 rows themselves are untouched in the vault, per the
same rule that left the 18 sidecar pairs alone.
