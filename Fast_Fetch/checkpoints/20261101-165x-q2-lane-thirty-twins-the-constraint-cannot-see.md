# 2026-11-01 16:5x — q2 lane: I was wrong about the embed gap by 25 minutes, and what the vault actually has

Tag: `[Q2-THIRTY-TWINS-THE-CONSTRAINT-CANNOT-SEE]` · Tasks #19 #21 · Branch `q2-census-pricing`
· Predecessor: `20261101-164x-q2-lane-no-staged-catalog-to-price-from-and-movi.md` (corrected in place)
· Artifacts: `Fast_Fetch/MOVIEBOX_COVERAGE_20261101.md` §3.2, §6

## The code that landed

`Fast_Fetch/merge_catalogs.py`: `_release_identity()` + `_collapse_identical_releases()`, called where
the merge loop takes `post_data["releases"]`, with a new reported counter
`stats["duplicate_releases_dropped"]`. Two offline cases in `test_merge_catalogs.py`. That is the
whole change — no vault was written, no row deleted, no schema touched, no crawl attempted.

## Why the collapse lives in the reader and not in a constraint

The vault holds **218 release rows for 188 distinct `(post_canonical_key, label)`** — 30 byte-identical
twins, max 2 copies each, across 30 of the 42 populated works — and each twin carries its own source
row for the *same* file, so **60 sources are really 30 prints**. `download_sources`'
`UNIQUE(release_id, url)` cannot see this: the twins have different `release_id`s, so SQLite is
correct to keep both and the duplication walks into the catalog as a work with twice the renditions
it has. A `DISTINCT` on the label would be worse than nothing — same label, different file is exactly
what the SD/HD tiers mean — so the comparison is on the mapped release **and** its sorted source
tuples, keeping the first. Hence: read path, positive control, and a number in `stats` so a lane sees
that it happened.

## The claim that did not survive contact with the importer

At 16:4x I published that 60/60 `direct` sources with `bridge_url` empty meant the Dooplay embed path
"has produced zero rows in this vault" and that #19 should spend three fetches finding out whether the
endpoint was dead. `import_themoviebox.py` says the opposite before any request: `SERVICE =
"themoviebox"`, `MEDIA_HOST_HINTS = ("aoneroom.com",)`, and `source_url == final_url` written by
construction — this is a **direct-CDN Aoneroom site**, and the 60 URLs are `macdn.aoneroom.com` prints
(56 `-sd`, 4 `-ld`), which the file's own header explains are separated from trailers by
`NONPLAYABLE_KEYS`, not by a host filter. **No request was needed to falsify that; one `grep` was.**
The shape of the mistake is worth naming, because it recurs: I inferred a missing code path from a
storage pattern that the code produces deliberately, and the inference felt like a finding precisely
because it was actionable ("go probe this"). §4 row 1 of the artifact is re-aimed at the 14 source-less
series, which is a real question.

## Verification status — read this as the limit of the claim

Both edited files compile (`py_compile`), and the suite parses to 10 cases with the two new ones
named. **Neither new case was executed locally**: local test-module runs stay frozen in this window and
the box read 99.7 % busy CPU at 16:32. `test_merge_catalogs.py` is in `backend-ci.yml`'s list, so CI
judges the collapse, and "landed" here means *pushed and CI-green or not* — not *demonstrated*.

**Closed 16:5x: it is demonstrated.** `65c9d2f` → run 41303255439 / job 124838402567,
`completed success`, and I checked the step rather than the headline — `🧪 test_merge_catalogs.py`
→ `success` (and `test_docs_invariants.py` → `success`, which is what keeps the trim from rotting
back). `aa5169f` (the §7/§8 partition analysis) is green on run 41303544356 too. That matters
specifically here because a green suite can also mean *my cases never ran*: the positive control
asserts `releases_merged == 3`, so if the collapse over-collapsed or the new methods went
undiscovered, that case fails rather than quietly passing. The collapse is therefore discriminating
on the hosted runner, not merely present in a diff.

## Handoffs

- **#19 when unfrozen:** the vault's 30 twins are a *repair* question the owner should decide (delete
  in place, or re-crawl idempotently); this lane leaves them where they are, same ruling as the 18
  sidecar pairs. Merging is already harmless with the collapse in.
- **#21's remaining real half:** `episode_number` NULL in 218/218 — season packs, not episodes; a
  parser change in `import_themoviebox.py`, plus the 14 works whose payload names no print.
- **q3:** `duplicate_releases_dropped` is now in every merge's stats. A non-zero count on some other
  site means the same crawl pattern, not a merge bug.

## Same segment — the 44 works partition three ways (artifact §7, §8)

`posts.seasons` crossed with "has a source" is a **total** split, not a tendency: `real-list ∩
no-source = 12 of 12`, `placeholder ∩ has-source = 30 of 30`, and the 2 NULLs are exactly the two
`sitemap_cache` rows carrying `scraped=2, error_count=2` (`Squid Game` 2021, `The Night Agent` 2023 —
failed fetches, not parse failures).

- **Group A (30 works, `seasons='[0]'`, one SD file each)** is the product problem. `_positive_int:575`
  documents that this site uses `0` for *no season / no episode*, and `_stamp_seasons` derives
  `seasons` from the releases — so `'[0]'` is the module's own statement that the work has no season
  structure, while the same rows are labelled `Lucifer S1-S6 S00 SD`. **The label asserts a six-season
  range the structured columns deny, and one file sits behind all of it.** Rule §10 is unmet here by
  mapping, not by fetching: 0 requests would fix it, but someone has to decide what a work-level print
  means for a series.
- **Group B (12 works, real season lists, no prints)** is the module behaving as designed —
  `_resource_renditions`' docstring says the payload names tiers with empty `detailUrl`/`sniffUrl`/
  `sourceUrl` and null `dl`, so each tier is stored as a declared print with an empty source list.
  Getting URLs is the **play-info mint** (`#22`'s path): an API call per work, not an HTML fetch. That
  is why #19's first row is 12 mints.
- **One published value is thrown away at the schema boundary:** `_resource_renditions` extracts
  `"episodes"` from `epNum`, but the `releases` insert (`:1969`) has no column for it and stored
  `raw_meta` carries only `page_url` + `quality_token`. Retaining `epNum` is the cheapest real fix in
  this file, and it preserves group B's shape without a second crawl.

I did **not** patch the importer for any of it: verifying a season/episode mapping needs a live payload
and the crawl freeze holds, so guessing at it would be a blind change to the module that already
carries the site's whole media law. Recorded as `#19`/`#21` work with the requests counted.
