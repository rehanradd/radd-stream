# Session 2026-10-29 (qoder2 fleet lane) — Hum TV is the licensed pick, and the crawl stops on the memory floor `[Q2-REGIONAL-FLEET-GO]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (qoder2 fleet lane) — Hum TV is the licensed pick, and the crawl stops on the memory floor `[Q2-REGIONAL-FLEET-GO]`

**The licensing question, answered before the first fetch.** The standing fleet
brief asks whether a regional catalog has licensed, distributable source links or
is a second copy of pirated metadata. For `hum.tv`: it is HUM TV's own WordPress
site; `robots.txt` disallows only `/wp-admin/`; the WP REST catalog is open
(5,625 posts); and every episode page embeds exactly one YouTube video whose
oEmbed reports `author_name: "HUM TV"`, `author_url: https://www.youtube.com/@HUMTV`.
There are no download mirrors on the site (the only "Download" strings are the
WordPress media-modal template). So the vault stores the broadcaster's own embed
pointers, `playback_type=iframe`, and **zero** download rows — because the
rightsholder publishes none, not because one was dropped. ApneTV was rejected on
the same question (pirated aggregator; also 403/521/DNS on scouting) and Geo TV
lost to Hum TV only on crawlability (clean WP REST + sitemap).

**What ships.** `Fast_Fetch/importers/import_humtv.py` (sync / crawl / verify /
stats, stdlib only, one worker enforced, memory floor at start and after every
20-page flush) and `Fast_Fetch/importers/test_import_humtv.py` — 23 offline tests.
Three title grammars are handled (`Hurmat – Episode 06`, `Aakhir Kab Tak Episode
– 01`, `Ishq Murshid Episode 07`), `og:title` is entity-decoded (`&#8211;` is the
dash — without that every episode keeps its episode number in the *work* key), all
three embed URL shapes are read (`embed/`, `youtu.be/…&#038;embed=true`,
`watch?v=`), and the adult flag comes only from `fast_fetch.is_adult_title(title,
slug)` — no local pattern list and no `unrated`/`uncut` vocabulary (qoder5 retired
those words centrally in `ab78849`).

**Identity.** One post per work, `generate_canonical_key(title, series_year)`, one
release per episode page with season/episode. `series_year` is the earliest post
year for that slug base across the queue, so the 26 of 1,474 slug bases that start
in December and run into January stay one work instead of splitting into two
canonical keys. 5,624 of 5,625 slugs are descriptive; the single numeric slug
(`831-2`) cannot join the map and keys on its own date.

**Measured.** REST sync: 5,625 queued, 0 errors, 57 pages. Pilot: 25 pages → 4
works / 25 releases / 25 sources, 0 failed, 0 no-player. Full crawl started from
page 26 and **stopped itself on the directive's floor** after 180 more pages —
`[!] Stop: MemAvailable 2350 MB < 2500 MB`, `pages=180 posts=180 releases=180
sources=180 failed_rows=0` — because a Gradle/JVM lane and several agent
processes had taken the box under 2,500 MB. Vault at that point:
`/home/ubuntu/radd-stream-data/humtv_staging.db`, 47 works / 205 releases /
205 watch_links / 0 download_links / 205 unverified. The queue keeps the
remaining 5,420 pages untouched; the crawl resumes when MemAvailable is back
above the floor, and the five fleet numbers are reported only when it is drained.

