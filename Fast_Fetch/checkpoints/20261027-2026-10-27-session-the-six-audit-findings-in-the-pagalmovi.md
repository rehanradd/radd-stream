# 2026-10-27 — Session: the six audit findings in the pagalmovies importer, landed (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: the six audit findings in the pagalmovies importer, landed (Qoder)

**Goal:** the audit of the fully-crawled `pagalmovies.db` (6,842 posts / 9,447 releases)
named six defects. This session lands all six, each with an offline test, then heals the
~100 staging rows they had already written, and pushes. Staging isolation held throughout:
`fast_fetch.db` was opened read-only to count it and never written (203 posts, mtime 01:59,
0 pagalmovies rows — unchanged since before the crawl).

**The audit named six defects; they landed as seven edits in `import_pagalmovies.py`:**

1. **A title that is a year survived its own cleaning.** `1922 (2017) English Movie` came back
   as the lowercased slug (`1922 2017 english movie`) because the inline-year strip ran
   unconditionally and an empty result fell through to the slug. The strip is now guarded: it
   runs only when something survives it, and a **bracketed** year is read before a bare one,
   because the bracket is where the site's packaging starts while a bare four-digit run can be
   the work's name (`1922`, `1917`, `2018` are all films here). The site's Release Date still
   outranks both where it has one.
2. **A descriptor that opens a title was eaten.** `_strip_packaging` drops `dual`, `complete`,
   `movie`, `film`, `south`, `latest` wherever they sit, so *Dual* → nothing and
   *Complete Unknown* → *Unknown*. The leading token is masked out of the strip and put back
   afterwards; there is one call site and it is always the page's own `<h1>`. The empty-result
   fallback also keeps the site's title case instead of the lowercased slug.
3. **`genres='N/A'` (95 rows).** `_info_block` ran `_meaningful()` over a row's plain text but
   not over its link labels, and the site's placeholder genre is a link:
   `<b>Genre:</b> <a href="…/genre/N/A/1.html"><b>N/A</b></a>`. Labels go through `_meaningful`
   now too, so those rows store NULL like every other placeholder.
4. **Placeholder sizes.** Pages carry `0.000 MB` / `-1.000 B` / `1.499 KB` for files nobody ever
   measured; 6 releases stored them as 0–32,763 bytes. `parse_size_to_bytes` returns NULL for
   anything under a megabyte — no tier of a feature is that small, so a sub-MB number is the
   absence of a measurement, not a measurement. (`size_text` is still not a column: the releases
   shape is `merge_catalogs`' contract, and widening staging to keep a string we now reject was
   not worth the ripple.)
5. **`Pagal Premi (20012)`** — the site mistypes its own packaging year. A bracketed digit run
   longer than four is packaging now, never part of a name and never a year.
6. **The site's sidebar is not this post's metadata.** One identical rolling strip —
   `Hunkkaar: The Roar (2026) S01 Jiohotstar … | Waiting Hai (2026) … | Musafir Cafe (2026) …` —
   sits inside `<div class="Fun">` on 2,999 of 3,000 sampled pages and was stored in 6,839
   `raw_meta` blobs. It is three *other* titles' facts filed under this post, which is why it
   goes. Dropping it does not make the row free of platform words and was never meant to: a
   re-sweep after the heal still finds them in `title` (70), `clean_title` (56), `synopsis`
   (106), `cast_names` (122), `releases.label` (82) and the untouched `info_block`/`meta_tags`
   halves of `raw_meta` (276/163) — that is the site naming a title's own streaming home in its
   own page text, i.e. content, not a leak. The audit's provenance finding was about *foreign*
   provenance, and on that the strip was the whole of it: `Updated Webseries` now matches 0
   rows in `posts.raw_meta` and 0 in `sitemap_cache.raw_json`.
7. **The origin rotated mid-audit** (`www.pagalmovies.fit` → `www.pagalmovies.casa`, the old one
   301s to the new). `BASE_URL`/`SITEMAP_URL` point at the live origin. Queue entries and rows
   written before the rotation still parse, because `_is_site_url` decides membership by host
   pattern, not by `BASE_URL` — verified against a retired `.fit` queue entry below.

**Two more things the work turned up that were not on the list, now fixed too:**
`SITE_HOST_RE` was `pagalmovies?\.[a-z]{2,}|pagal\s?movies` — the second alternative is
unanchored, so `pagalmovies-copy.example.com` counted as the site and the crawler would have
followed its redirects as ours. It is label-anchored now (`(?:^|\.)pagal\s?movies?\.[a-z]{2,}`),
which is also what keeps the `.fit`/`.casa` pair working. And an **unclosed** site bracket
(`Aladin 2 (1994 Hindi Dubbed Movie`) left `( Hindi` hanging off a title: the head-seam split no
longer requires the closing character, and a bracket whose partners are missing is dropped.

**Healed in staging, offline, from data already stored** (no re-crawl, no production write;
`/tmp/pm_heal.py`, DB copied first to `pagalmovies.db.pre-heal-20261027`): 8 `clean_title`
values, 95 `genres='N/A'` → NULL (NULL rate 33 → 128), 6 sub-MB `size_bytes` → NULL, and the
`Updated Webseries` row stripped from 6,839 `raw_meta`/`raw_json` blobs. `PRAGMA integrity_check`
ok, 0 orphan releases, 0 orphan sources, 0 duplicate keys.

**Deliberately not done.** *7 rows whose stored year is the site's SEO title rather than its
own Release Date* (`the-40-year-old-virgin_1965`, `300_2006`, `cabin-fever_2002`,
`halloween-ii_2005`, `sister-act-2-…_1997`, `dead-alive-braindead_1992`, `jersey-boys_2012`)
would rekey under the precedence rule. Five have a free target key; **two collide with rows that
already exist** — the same film published on two pages with different years in the slug — so
correcting them is a merge decision (which row wins, whose releases survive), not a rewrite.
Left alone and named here rather than half-applied. *Titles that keep a trailing language word*
(`Pagal Premi Bhojpuri`) keep it: `_strip_packaging` has never stripped language names, and
doing so would take it away from rows like `Political Khiladi (ko 2) South Indian Hindi` that
the catalog already ships; that is a convention change, not a defect fix. *Stored `.fit` URLs*
in 6,842 `posts.url` / 9,447 `releases.bridge_url` / 9,447 `sources.*_url` rows are not
rewritten to `.casa`: they still resolve through the redirect, `sitemap_cache.loc` is the queue's
primary key, and rewriting it would re-queue all 16,018 URLs as new. *Still no merge into
`fast_fetch.db`.* *Still untracked, and not mine to push:* `import_filmiyin.py` /
`test_filmiyin_import.py`, `import_mp4moviez.py` / `test_mp4moviez_import.py`, and the
`App/` changes sitting in this same checkout.

**Checks:** `importers/test_pagalmovies_import.py` **54 OK** (was 44 — the new tests are
`TestAuditHygiene` plus the placeholder-size, placeholder-genre and sidebar cases),
`importers/test_filmiyin_import.py` 38 OK, `test_database.py` 64 OK, `test_vidout.py` 6 OK,
and `test_redact`, `test_api_v2`, `test_admin_panel`, `test_catalog_api`,
`test_provenance_stamping`, `test_operator_isolation`, `test_media_search` all OK;
`import fast_fetch, viewer, merge_catalogs, import_pagalmovies, import_filmiyin` OK.
`test_chain_walk_stores_every_provider` was **silently hitting the live network** — it called
`resolve_links` without patching `http_get_once`, so it passed or failed on the mirror host's
rate limit and would have gone red for reasons unrelated to the code. It now patches the chain
and is offline like the rest of the file. Live verification was done separately, deliberately:
`_parse_page` against three URLs taken from the new origin (titles, sizes and info-block keys
clean, sidebar gone) and against a retired-`.fit` queue entry that 301s to `.casa` and still
parses with `genres=None` and `size_bytes=None`. `merge_catalogs` re-checked on the healed rows:
`_source_family` → `staging`, `_collect_staging_post` returns `1922` / 2017 / `Crime, Drama,
Horror` with `317.36 MB` prints — into a temp target only.

**Where this landed.** `a681635`, fast-forwarded on `https://github.com/radddao/radd-stream.git`
for both `main` and `master` (`bc2bc0e..a681635`), the two branches identical as the owner
directed. Note for the next agent: this checkout's `origin` is
`https://github.com/rehanradd/radd-stream.git`, and the `GITHUB_TOKEN` on this host authenticates
as `radddao`, which GitHub refuses for that repo (403 on push; reads fine, and it sits at the same
`bc2bc0e`). `git push origin` will therefore keep reporting `ahead 2` no matter what lands on the
documented remote — the branch state to trust is `git ls-remote` against
`radddao/radd-stream.git`. The push used the askpass procedure against that explicit clean URL; no
token appeared in a URL, argument, file or log. The heal's pre-write copy of the staging database
is kept at `/home/ubuntu/radd-stream-data/pagalmovies.db.pre-heal-20261027` (outside Git) so the
row edits stay reversible until someone wants the space back.

