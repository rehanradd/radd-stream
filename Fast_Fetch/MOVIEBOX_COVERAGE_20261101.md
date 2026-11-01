# MovieBox Coverage — what the vault actually holds (2026-11-01 16:4x)

Task **#21**'s probe half, plus the numbers **#19**'s bounded re-crawl and **#24**'s honest discovery
ceiling have to be written against. Everything here is measured, not carried over from a checkpoint.

**Read class, stated so it can be overruled:** `/home/ubuntu/radd-stream-data/themoviebox.db`,
**299,008 B**, `mode=ro` + `PRAGMA query_only=ON`, no sidecars beside it. `COUNT(*)`, `EXISTS` joins,
`GROUP BY` over 44 + 218 + 60 rows, and two `LIMIT 8` label listings. No `raw_meta` value was printed
and nothing was written. It is a content read of a staging vault, which the freeze bars as a
*category* while permitting it as a *size question* — I judged 299 KB to be the census class #20 and
#37 already established, and I am naming the judgement instead of burying it.

## 1. The stale number in the records

The 2026-10-30 crawl checkpoint records `themoviebox.db` = **44 posts / 0 releases / 0 sources**.
Measured now (file mtime **2026-10-31 06:58**, i.e. after that session):

| table | rows | shape note |
|---|---|---|
| `posts` | **44** | all `media_type='series'`; `is_18_plus=1` on **0**; `keys_both` **0** |
| `releases` | **218** | keyed by `post_canonical_key` — **there is no `post_id` column** |
| `sources` | **60** | `release_id` → `releases.id` |
| `sitemap_cache` | 44 | one `loc` per post |

The older checkpoint line is **left verbatim where it stands** (it is absorbed trunk text and it was
true when written); this section is the correction of record.

## 2. Referential integrity is clean; coverage is not

- **0 orphan releases** (every `post_canonical_key` resolves to a post) and **0 orphan sources**
  (every `release_id` resolves to a release). The re-derivation did not strand rows.
- **42 of 44 posts have at least one release.** The two with none:
  `Squid Game` (2021, `squid-game_2021`) and `The Night Agent` (2023, `the-night-agent_2023`).
- **14 of 44 posts have no source at all** — 32 % of the works in the vault are catalogued but
  unplayable. Only 60 of the 218 releases carry a source, and 30 of those 218 rows are
  duplicates, so the honest figure is 30 prints across 30 distinct files (§6).

## 3. The two structural defects that a re-crawl will not fix by itself

1. **The releases are season packs, not episodes.** `season_number` is non-null in **218 / 218** and
   `episode_number` is non-null in **0 / 218**. Labels read `Vikings S1-S6 S00 SD`,
   `The Walking Dead S1-S11 S00 SD` — a whole series run collapsed into one row per season-set.
   Rule §10 ("capture all seasons/episodes") is therefore **not met** by this vault, and no amount of
   link crawling changes that: it is a parser-granularity gap in
   `Fast_Fetch/importers/import_themoviebox.py`, not a fetch gap.
2. **All 60 sources are one CDN, and 30 of them are duplicates — not an untested embed path.**
   60/60 are `service='themoviebox'`, `status='active'`, `playback_type='direct'`, `bridge_url` empty
   in 218/218 releases, `source_url == final_url`. My first reading of that was "`#22`/`#23`'s Dooplay
   embed resolution has produced zero rows here, so either the endpoint is dead or it was never
   tried". **Reading `import_themoviebox.py` says the opposite**: this site's own backend is
   Aoneroom — `SERVICE = "themoviebox"`, `MEDIA_HOST_HINTS = ("aoneroom.com",)`, and the module
   writes `source_url` and `final_url` as the same value by construction. Measured, all 60 URLs are
   `macdn.aoneroom.com/media/vone/<date>/<hash>-{sd,ld}.mp4` (56 `-sd`, 4 `-ld`), which is the
   work's print, not a trailer and not a missing embed. The header of that file warns that a host
   filter alone cannot separate trailer from print and that `NONPLAYABLE_KEYS` is what does it —
   nothing here contradicts that. **The `#19` question I wrote in §4.1 was therefore the wrong
   question, and the correction is the finding: there is no embed gap.**

   What there *is*: 60 source rows over **30 distinct files**, because 30 of the 218 release rows
   are byte-identical twins (§6).

## 4. What #19's bounded re-crawl should be, in priority order

Frozen now (no crawl while the freeze holds, and the box read 99.7 % busy CPU at 16:32), but the plan
follows directly from §2 and §3 and is small enough to stay honest about its cost:

| # | Target | Rows | Why this order |
|---|---|---|---|
| 1 | detail probe on the **14** source-less series | 14 page-fetches, the same requests as row 2 | the payload either names a print or it does not; that decides whether these works are crawlable or metadata-only by the site's own declaration |
| 2 | the **14** source-less posts | 14 detail fetches | turns catalogued-but-unplayable into playable; biggest user-visible win per request |
| 3 | the **2** release-less posts | 2 detail fetches | closes the only true holes in §2 |
| 4 | episode lists for the **218** season packs | the expensive half, and the only half that needs a real budget | §3.1; must be a parser fix + a bounded sweep, not a re-crawl of everything |

Host-gated through `link_health.host_gate()` as landed on 2026-10-30; no shorteners, no CAPTCHAs, no
timed redirects, one site at a time, writes to `themoviebox.db` only — never into
`fast_fetch.db` or the merged catalog (Rule §9).

## 5. What #24's discovery ceiling can honestly claim

The vault contains **44 series and no movies** (`media_type` split: `series: 44`). So any ceiling
statement for this site must be scoped to *series discovered by the sitemap walk that produced these
44 `sitemap_cache` locs*, and must not be phrased as "the catalog" or "the site". 44 posts against a
`sitemap_cache` of exactly 44 `loc` rows also means the vault is a **detail-tier sample**, not a
discovery result — the sitemap was not walked to exhaustion, so #24's number is a floor with an
unmeasured gap above it, and §3.1's episode question is what actually bounds the work.

## 6. The duplicate-row defect, and why the merge cannot catch it

`SELECT COUNT(*) - COUNT(DISTINCT post_canonical_key || '|' || label) FROM releases` → **30**.
218 rows, 188 distinct `(key, label)`, max copies 2, **30 of the 42 works with releases affected**.
The twins are identical on every compared column — `label`, `quality`, `resolution`, `codec`,
`size_bytes`, `season_number`, `origin_url` — 188 distinct tuples for 218 rows. Each twin carries
its own source row pointing at the same file, which is why 60 sources hide 30 prints.

The obvious fix is a constraint, and there isn't one to add: the target's
`UNIQUE(release_id, url)` is keyed on `release_id`, so two sibling releases with the same URL are two
rows no constraint recognises as duplicates. They pass straight through `_collect_staging_post` into
`download_sources`, and the catalog then reports a work as having twice the renditions it has. The
collapse therefore has to happen where the rows are read, and it must not be a `DISTINCT` on the
label — same label with two different files is two prints, which is the whole point of the quality
tiers. `merge_catalogs._collapse_identical_releases` now compares the mapped release *and* its
sources, keeps the first, and reports the count as `stats["duplicate_releases_dropped"]`.

Two offline cases in `Fast_Fetch/test_merge_catalogs.py`: the collapse with a genuine second
rendition in the same fixture that must survive, and a positive control — same label, same quality,
different file — that must **not** be collapsed. **Neither was executed locally** (local test-module
runs are frozen in this window; `test_merge_catalogs.py` is in CI's list, so CI judges them and this
line is the honest status until a green run says otherwise).

**Not done, deliberately:** the 30 rows stay in `themoviebox.db`. Deleting another lane's crawl output
is not this segment's call — the same rule that left 18 sidecar pairs alone (§5 of the census). The
merge-side collapse makes the duplicates harmless on the way in; removing them from the vault is
`#19`'s business when the crawl unfreezes.
