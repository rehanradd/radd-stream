# 2026-10-29 — Session: Filmywap, FilmyHit and KuttyMovies get importers; six named anime hosts are retired on evidence (Qoder2, orchestrator)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 — Session: Filmywap, FilmyHit and KuttyMovies get importers; six named anime hosts are retired on evidence (Qoder2, orchestrator)

Master assigned three new crawlers in strict order, one crawler at a time, then an
anime/Asian scout. All three importers exist with their own offline suites, and the
scout is answered. No production database was opened and nothing was merged.

**Gate — 360 tests, all green:** `test_database.py` 76, `test_vidout.py` 6,
`importers/test_host_resolvers.py` 171, `import_filmywap` 33, `import_filmyhit` 30,
`import_kuttymovies` 44.

**Filmywap (`importers/import_filmywap.py`, `filmywap.db`).** `.site` is the only live
surface; `.wiki/.win/.online` land on an Airtel court-order iframe and `.cloud/.run/.sbs`
on a different brand (`filmstopia.com`), both recorded and not bypassed. 1,522
`/movie/<slug>` pages, schema.org `@graph`, and a public `/api/stream?slug=` JSON with
signed MP4 URLs (`?sign=&t=` expiry) plus one call per episode for series. Signed URLs
are stored `is_temporary=1` + `unverified`, with the API URL as the durable bridge.
≈80% of titles are series, so the full crawl is network-bound at ≈2.3 titles/min.

**FilmyHit (`importers/import_filmyhit.py`, `filmyhit.db`).** `.mobile` is the live host;
`.link` is NXDOMAIN and `.best` is Cloudflare 403. 20,997 sitemap URLs, 16,913 of them
`*-free-download` detail pages. Detail `@graph` gives IMDb `sameAs`, ISO duration and
`inLanguage`; each release anchor points at an `/all-format-downloads-…` bridge whose
`/d/…/server-N` endpoints sampled as 502 or a "Verify to Continue" interstitial, so the
endpoints are stored unverified and unfollowed and the bridge is the durable route.
Series are season packs.

**KuttyMovies (`importers/import_kuttymovies.py`, `kuttymovies.db`).** Seven rotations
probed: `.cc` 403, `.com`/`.download` doorways, six TLDs NXDOMAIN, `.vip` redirecting to a
page-only `kutty-movie.com`. `.wiki` is the catalogue: a Yoast `post-sitemap.xml` with 905
post permalinks (homepage dropped) whose slug set is *identical* to the REST API's
`X-WP-Total: 905`. Each post is read in one small REST call
(`?slug=…&_fields=…`), not a 90 KB HTML page. Titles all carry a parenthesised year and
444 are series-shaped. All 2,548 download anchors on all 905 posts are
`linkshub.website/url.php?id=<7-hex>`; the link is a 30-second robot gate, so it is
stored unverified and never followed. Series headings (`S01E01T05`) decide the episode
range: `episode_number` is the start, the end stays in `releases.raw_meta`.

**Crawl state at the time of writing.** Filmywap is the only crawl running
(`--workers 1 --delay 0.15`, nice 15, PID 863744): 24 posts / 1,281 releases after
10 minutes with 1,497 still queued — roughly eleven hours. FilmyHit has not been crawled
and KuttyMovies is only queued (905 rows in `sitemap_cache`, 0 scraped), both waiting for
the single crawl slot in the assigned order.

**SITES.md.** §15's "sites to add" table was wrong on four rows: World4uFree, Bolly4u,
9xmovies and MP4Moviez are already scraped and their DBs exist. §15 is now a measured
status table (scraped / built this session / still blocked), and §16–§19 document the
three new surfaces plus the scout result.

**Anime/Asian scout — the answer is "none of the named hosts".** melondrama and weibo.tv
time out; doramon.com is a parked lander; animesnow is NXDOMAIN; bato.to is owner-closed
(`coda-cj.jp/closed.html`); hianime/aniwatch/9anime/kaido/9anime.gs are blackholed from
this host; animesuge and myasiantv answer a 401 `?tkn=` token wall; animepahe, wcostream,
kisskh.co and wco.tv answer Cloudflare 403; gogoanime3.co is a 474-byte "Loading" stub and
gogoanime.at is for sale. The only hosts that publish clean sitemaps are **iq.com** and
**viu.com** — official DRM platforms whose sitemaps yield metadata only, not source links,
so they are not a fit. Existing coverage stays with animahd, rareanimes, toonworld4all,
dramacool and kisskh.

**Not done, on purpose.** No merge, no touch of `fast_fetch.db` or
`merged_catalog_20261025.db`, no Cloudflare/token/robot gate attempted anywhere. The
Filmywap crawl continues; FilmyHit and KuttyMovies crawls are the next two slots.

