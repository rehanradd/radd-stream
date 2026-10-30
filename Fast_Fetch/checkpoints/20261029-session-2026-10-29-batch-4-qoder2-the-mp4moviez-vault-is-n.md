# Session 2026-10-29 (batch 4, qoder2) — the mp4moviez vault is now counted, not assumed

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (batch 4, qoder2) — the mp4moviez vault is now counted, not assumed

**The repair.** `convert_mp4moviez.py` now stages works that carry no releases and
refuses to publish a vault whose arithmetic does not close. Measured on the legacy
file: **29,848 posts = 11,404 staged + 18,155 collapsed + 289 skipped** (187
not-a-work, 102 listing) and **54,267 releases = 54,267 sources**. The 16,168
legacy posts with zero releases are not lost: 14,113 of them collapse into
release-bearing works (episode pages of a series share the canonical key),
1,766 form the 666 release-less posts in the vault, and 287 are on skipped
listing/static pages. The four release URLs that used to vanish belonged to
`vijaypath-1(994)-…` — a real 1994 film whose slug misspells the year; the slug
is normalised, so all four are staged and every skipped-release counter is 0.

**What was already right.** The old vault was not gated on releases (it staged
666 release-less posts); the difference in post count is canonical collapse, not
a drop. Identity comes from the slug title + year as before, never the
"Download …" H1.

**Proof.** New vault `/home/ubuntu/radd-stream-data/mp4moviez_staging2.db`:
11,404 posts / 54,267 releases / 54,267 sources / 32,967 sitemap rows, 43
`is_18_plus=1`, 0 null canonical keys, 666 release-less posts, all sources
`unverified`. Full merge into a fresh temp target: 11,404 / 54,267 / 54,267 in
302.7 s, 0 conflicts. 15 converter tests (4 new conservation tests plus a
malformed-year test). The original `mp4moviez_staging.db` is left untouched as
the pre-repair artifact; the merge queue should take `mp4moviez_staging2.db`.

