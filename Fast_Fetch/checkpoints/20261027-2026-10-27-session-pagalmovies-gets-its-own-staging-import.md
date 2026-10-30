# 2026-10-27 — Session: pagalmovies gets its own staging importer (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: pagalmovies gets its own staging importer (Qoder)

**Goal:** build `Fast_Fetch/importers/import_pagalmovies.py` to the spec in
`pagalmovies_task.md` — stdlib only, writing exclusively to
`/home/ubuntu/radd-stream-data/pagalmovies.db`, extracting both the VidCloud
"Watch Online" embed and the 10Gbps skydrop/goFile mirror set.

**The site model, verified live** (the spec's `Protection Layer: none` is only half
right — the pages are plain HTTP, but `/download/<file_id>` refuses a request that
does not carry an on-site `Referer`, and buzzheavier sits behind a Cloudflare
challenge):

```
/movie/<post_id>/<slug>.html          quality-headed groups (pm-q-badge) + fileName anchors
/file/<file_id>/<name>.mp4.html       one printable file = one quality tier / episode / part
/download/<file_id>          302 ->   /download/<file_id>/vidcloud
                         302 ->   five.vidcloud.quest/s/<TOKEN>   (the VidCloud file page)
                             /d/<TOKEN>/<provider>  for watch_online, skydrop, gofile,
                                                    buzzheavier, sonicboom, transferit,
                                                    vikingfile, telegram
```

`watch_online` answers its own redirect chain with an `R2` object URL in a
`videoUrl=` hop — token-free, `206`-resumable, i.e. genuinely playable with no
client-side JS. `skydrop` lands on a **signed** `lh3.googleusercontent.com/pw/…=dv`
attachment, so it is stored `is_temporary=1`. goFile/sonicboom/transferit/vikingfile/
telegram are stored as real download bridges; buzzheavier is kept as `js_required`.
Nothing in the chain was dropped for being hard: statuses are `active`, `dead`,
`blocked`, `js_required` or `unknown` (never probed).

**Four things the live audit taught that the fixtures did not.**
1. **Half the sitemap is a graveyard.** A random sample of 160 queued URLs returned
   **72 live / 88 gone**; the newest ids (`296xx`) are gone almost without exception —
   the site 302s a stale id to its own homepage, whose `<h1>` reads *"The Best Free
   Movie Download Site…"*, not the string my fixture used. `parse_page` now reports
   *why* it declined (`removed` / `not-a-post` / `http-error`) and the crawler parks a
   page the site has provably removed **on the first sighting**, spending its three
   retries only on transport errors. At ~16k queued URLs that is roughly 8k wasted
   requests avoided.
2. **The old catalog's files are dead, not blocked.** `/download/<id>` for an old id
   answers **503 with the framework's bare `<title>Error</title>` page** — the row is
   gone. `blocked` (reserved for 401/403 and for the homepage bounce that happens when
   the Referer is missing) was a lie about what we saw, so that shape is now `dead`.
   Re-resolving the 23 rows the first probe pass had filed as `blocked` moved all 23 to
   `dead`.
3. **The site's SEO title carries the wrong year.** `The_40_year_old_virgin_(1965)` is
   dated `19 August,2005` in its own information block. Adopting filmiyin's rule —
   `explicit_year` from the Release Date field outranks the title, which filmiyin had
   already learned to trust — fixes it; sampled pages confirm those dates are premiere
   dates, not upload dates.
4. **Sizes are written `105.67 mb`**, lowercase, so the unit alternation had to lose its
   case-sensitivity. Zero releases now have a null `size_bytes`.

**Staging data so far** (bounded verification crawl, not the full one): 16,018 URLs
queued from `/sitemap.xml`; 321 pages indexed → **310 posts, 549 releases, 549 sources**
in `pagalmovies.db`, `queued 15,696 / parked 1`. 22 posts are `is_18_plus=1`, all driven
by the site's own labels (genre `Erotic, Adult, B-Grade`, shelf `Hot short films`,
platforms `Atrangii`/`Bablutv`/`Brazzers`); prose alone still cannot flag, per the
narrowed policy the filmiyin session established. Tiers in this slice are
`480p 540 / 1080p 5 / 720p 4` — the old pages really are 480p-only, while newer pages
(e.g. `Eyes (2026) Atrangii`) carry 720p **and** 1080p, and both `deep`-resolved to 8
providers each with `watch_online` → an R2 `.mp4`. Canonical keys are slug-derived with
the packaging right-trimmed, so `…atrangi…` and the re-published `…atrangii…` variant
share one key and `300`, `jailer-2`, `3-idiots`-style numeric titles survive it.
`export_staging` replaces releases per `origin_url`, so a season page and an episode-pack
page of one title keep each other's prints. No duplicate `canonical_key`, no post without
a release.

**Provenance:** a sweep of every `posts` display column for
`pagalmovies|filmyhit|coolmoviez|allmovieland|mp4moviez|vidcloud|filesdl|skydrop|buzzheavier|bit.ly|agl0|aj0|histats|telegram`
returns **zero hits**; the only columns that name the site are `source_site` (which the
unified catalog needs) and the `poster_url`/`bridge_url` resource URLs, which cannot
point anywhere else and still deliver the image. Sister-brand names are scrubbed out of
titles, release labels and synopses; the `Fun` info block's `n/a` placeholders are stored
as NULL, not as text.

**Deliberately not done, and what this session did push.** Pushed to `main` on the owner's
word: `import_pagalmovies.py`, `test_pagalmovies_import.py` and this log. **Not pushed and
still untracked:** `import_filmiyin.py` / `test_filmiyin_import.py` and `import_mp4moviez.py`
/ `test_mp4moviez_import.py` — the filmiyin pair is the code that `HEAD`'s prose has been
describing since `04126e7` without ever carrying it (recorded above), and the mp4moviez pair
is another account's in-progress work; both need their own owner decision. No merge into
`fast_fetch.db`, and no full crawl of the remaining 15,696 queued pages: `--probe` costs ~4
requests per file and the mirror host rate-limits around 30 per window, so the resolution
pass is a separate, deliberate run rather than a default. `fast_fetch.py`
(`DEFAULT_DOMAINS`, `normalize_url`, `sync_sitemaps`, `extract_post_data`, `SITE_CHOICES`)
and `viewer.py` were not touched, so this site is not yet reachable from the generic
pipeline; that is the operator's call too.

**Checks:** `importers/test_pagalmovies_import.py` **44 OK** (all offline, `http_get` /
`http_get_once` patched, fixtures trimmed from real markup),
`importers/test_filmiyin_import.py` 38 OK, `test_database.py` 64 OK, `test_vidout.py` 6 OK,
`python3 -c "import fast_fetch, viewer, merge_catalogs"` OK — one module per invocation,
no production catalog written. `merge_catalogs` contract tests confirm `_source_family`
reads this staging shape (`sources` present → `staging`) and `_post_release_rows` joins on
`post_canonical_key`, which is how this schema links releases.

