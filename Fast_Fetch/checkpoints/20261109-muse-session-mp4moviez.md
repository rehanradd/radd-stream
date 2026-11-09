# Muse [MUSE-SESSION-MP4MOVIEZ]: mp4moviez converter verification + staging vault

Date: 2026-11-09 ~21:55 PKT. Builder: Muse (subagent, parent = main chat).
Base: main 32f2c19. Branch: `session-mp4moviez-converter` (NOT merged — parent
merges after review; data merge into the live catalog waits for the rev-6 swap).

## What this is
mp4moviez is a CONVERTER job, not a live scrape. The first mp4moviez pass
wrote a private schema (posts.source_url, no canonical identity, no source
rows) that `merge_catalogs.py` refuses. Two converter modules already existed
in main and were unverified + unregistered; this session verifies them,
registers them in the gate, and runs the copy converter against the real
legacy DB on the VM to produce the staging vault.

- `Fast_Fetch/importers/convert_mp4moviez.py` — copy converter: reads the
  legacy DB read-only, writes a NEW staging vault (`--source` → `--target`).
  Groups legacy posts by `fast_fetch.generate_canonical_key(title, year)`;
  survivor = member with most releases; releases merge across members,
  deduped by (quality, url). Nothing invented: `final_url` NULL, `status`
  `unverified`, `playback_type` `download`.
- `Fast_Fetch/importers/import_mp4moviez.py` — in-place converter (`convert`
  subcommand, rewrites the legacy DB's own tables in one transaction) plus
  the `anchor_from()` / `CONTENT_ANCHOR_RE` (`^c\d+$`) definitions the
  emptied-pages count is measured with. NOT run here — the live
  `mp4moviez.db` stays in legacy form on purpose until the queue owner says so.

## Tests (solo, CI way, all green)
- `python3 -S Fast_Fetch/importers/test_convert_mp4moviez.py` — **15 OK**
- `python3 -S Fast_Fetch/importers/test_mp4moviez_import.py` — **23 OK**
- `python3 -S Fast_Fetch/test_docs_invariants.py` — **22 OK** (after the
  registration below)

## Gate registration (Session 122 fixup-1 pattern)
- `backend-ci.yml`: two new 🧪 steps after `test_themoviebox_import.py`
  (`test_convert_mp4moviez.py`, `test_mp4moviez_import.py`, both
  `python3 -S Fast_Fetch/importers/<module>.py`). 🧪 count 65 → **67**.
- `test_docs_invariants.py`: both modules removed from UNREGISTERED.
  Invariants pass (22 OK).

## Converter run (live-tree code, VM, 21:56 PKT)
Run from `/opt/radd-stream` (live tree @ f7a4c91) so it uses the live-tree
code — md5sums of `convert_mp4moviez.py`, `import_mp4moviez.py`,
`fast_fetch.py`, `merge_catalogs.py` verified IDENTICAL to main @ 32f2c19
before running. Source `/home/ubuntu/radd-stream-data/mp4moviez.db`
read-only; target `/home/ubuntu/radd-stream-data/mp4moviez_staging.db`
rebuilt with `--force` (the old Oct 29 file was a stale partial output of
the same converter: 11,403 posts / 54,263 releases — off by 1 post and 4
releases from the fresh run; regenerable, nothing else used it).

Command:
`python3 -S Fast_Fetch/importers/convert_mp4moviez.py --source
/home/ubuntu/radd-stream-data/mp4moviez.db --target
/home/ubuntu/radd-stream-data/mp4moviez_staging.db --force` — exit 0.

Stats (converter's own conservation accounting, both OK):
- legacy posts 29,848 = staged 11,404 + collapsed 18,155 + skipped 289
  (not-a-work 187, listing 102, unknown-key 0) [29,848/29,848 OK]
- legacy releases 54,267 = sources 54,267 + deduped 0 + no-url 0 +
  on-skipped-posts 0 [54,267/54,267 OK]
- legacy posts without releases 16,168; staged without releases 666;
  posts_18_plus 43; sitemap rows 32,967; grouped/selected keys 11,404.

## Staging verification (direct sqlite3, read-only, VM)
- posts **11,404**; releases **54,267**; sources **54,267**; is_18_plus **43**.
- No invented data: `final_url IS NOT NULL` = 0; `status` only
  `unverified`; `playback_type` only `download`.
- Posts with no releases: **666**.

## The emptied-pages answer (measured, not from the docstring)
The legacy DB holds 16,168 link-less posts. By the project's own
`CONTENT_ANCHOR_RE` (`^c\d+$` on `anchor_from(url)`), **14,741** of them
carry a content anchor (the emptied work pages; the import docstring's
14,730, measured 2026-10-28, is 11 fewer — the 8 two-digit anchors plus the
3 bare `c` anchors from `/c/contact-us.htm`-style paths, which the older
count excluded; totals reconcile exactly at 16,168, so it is a
classification edge, not lost rows). Reconciled against staging `raw_meta`
(`legacy_post_ids` per post):
- **13,889** collapsed onto staged posts WITH releases — their films survive
  with links from sibling re-posts (same title+year, new `c<id>` path).
- **852** are members of the **666** link-less staged posts (852 anchored +
  914 non-anchored link-less rows = 1,766 rows in 666 keys).
- **0 dropped.** The 289 skipped rows are all link-less, no-anchor rows
  (category/listing/static pages); `releases_on_skipped_posts` = 0.

## Why 18,155 collapsed (read this before the merge)
Grouping is by `generate_canonical_key(title, year)`, not by slug: the site
re-posts each film ~2.6x on average under new `c<id>` paths, so 29,559 parsed
rows become 11,404 distinct works. The OTHER converter
(`import_mp4moviez.py`, in-place) keeps slug-keyed re-posts and would write
28,066 posts; `merge_catalogs.py` collapses same-key rows onto one catalog
record by design, so both routes should land ~11,404 catalog records — the
end state agrees, only the staging shape differs. This session ran the copy
converter because the task ordered it; the parent judges at merge time.

## What remains (parent)
- Review + merge branch `session-mp4moviez-converter` to main (CI on the
  branch must be green first — Backend + Android by run id).
- Data merge staging → live catalog AFTER the rev-6 swap (~23:00 PKT);
  NOT done here. Rollback for the merge: backup-2031 set (verified).
- mp4moviez is NOT in `domain_registry.json` — no registry change was
  needed for this converter job (no live scrape).
- Cast/genres/tags stay 0 in staging (the legacy scrape never read them);
  the 29,848-cast gap needs an importer + merge of its own (the 124
  backfill proved 0 mp4moviez URLs in live `post_sources`).
