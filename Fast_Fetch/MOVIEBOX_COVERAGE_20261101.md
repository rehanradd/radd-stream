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
  unplayable. Only 60 of the 218 releases (27 %) carry a source.

## 3. The two structural defects that a re-crawl will not fix by itself

1. **The releases are season packs, not episodes.** `season_number` is non-null in **218 / 218** and
   `episode_number` is non-null in **0 / 218**. Labels read `Vikings S1-S6 S00 SD`,
   `The Walking Dead S1-S11 S00 SD` — a whole series run collapsed into one row per season-set.
   Rule §10 ("capture all seasons/episodes") is therefore **not met** by this vault, and no amount of
   link crawling changes that: it is a parser-granularity gap in
   `Fast_Fetch/importers/import_themoviebox.py`, not a fetch gap.
2. **Every source is a direct link.** 60/60 are `service='themoviebox'`, `status='active'`,
   `playback_type='direct'`, and **`bridge_url` is empty in 218/218 releases** while `origin_url` is
   populated in all of them. So the Dooplay/embed resolution path that exists in the importer
   (`#22`, `#23`, `resolve Dooplay embeds` per `66769c7`) has produced **zero rows in this vault**.
   Either the detail API stopped returning embeds, or the resolver ran against other sites only.
   This is the single most valuable thing for #19 to answer, and it is answerable with a handful of
   requests rather than a crawl.

## 4. What #19's bounded re-crawl should be, in priority order

Frozen now (no crawl while the freeze holds, and the box read 99.7 % busy CPU at 16:32), but the plan
follows directly from §2 and §3 and is small enough to stay honest about its cost:

| # | Target | Rows | Why this order |
|---|---|---|---|
| 1 | embed/detail probe on **3** known-good series | 3 requests | answers §3.2 for one page-fetch each; decides whether "0 embeds" is a dead endpoint or an untested path |
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
