# Overnight fleet contract — 2026-10-28 (owner approved full autonomy, live API frozen)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Overnight fleet contract — 2026-10-28 (owner approved full autonomy, live API frozen)

- **Fleet, verified:** qoder1 (`~/.qoder`) = App region/settings + snapshot work; qoder2
  (`~/.qoder_account2`, me) = fleet orchestrator; qoder3 (`~/.qoder_account3`) = kisskh
  importer; `agy` (Antigravity) = roadmap/supervision; `vm_monitor` = pane tail. No Gemini
  CLI process exists on this host.
- **Rules enforced:** one Gradle build at a time (prefer `/tmp/qbuild.sh`; qoder1 ran one
  direct build at 00:24, no other build was started); at most two crawlers, both `nice`d;
  live API (`merged_catalog_20261025.db`, 115,938 posts) is frozen; staging DBs only; no
  secrets echoed; no `git add -A`, no force-push.
- **Site roster, verified live by probe:** 21 existing importers + kisskh (building) +
  dramacool.li + 5movierulz.green + moviecok.xyz + levidia.ch = 26 catalogs; plus four
  resolver adapters (vidsrc.sh, superembed.stream, vidlink.pro, 2embed.cc) = 30 integrations.
  Dead replacements ruled out: desiserials (.org parked, .com redirect), moviesflix (parked),
  isaimini (/lander), animepahe (challenge), asianc (timeout), apnetv (403), dramacool.ch
  (reset), kissasian.vip (for sale).
- **mp4moviez:** 29,848 posts stored; remaining 3,119 URLs are 2,565 adult pages + 442
  category listings + 112 Unicode-titled posts, and the site moved those pages to JS-gated
  `data-key` download buttons. The old `dl.php` parser cannot see links; a resolver upgrade
  is the follow-up, not a crawl outage.
- **Subtitle rule:** every `.vtt/.srt/.ass` track becomes its own `sources` row with
  `playback_type='subtitle'`, and the full track map is kept in `raw_meta`. Tracks are never
  dropped or deduplicated by language.
- **Subtitle audit result (verified by query):** the legacy pipeline stored **zero** subtitle
  rows — 17,541 filmiyin sources, 2,229+ dramacool sources and every sampled legacy range
  carry no `playback_type='subtitle'` row and no `.vtt` URL. Subtitle capture begins with the
  new importers; kisskh is the first catalog expected to yield real tracks.
- **Progress at 00:50:** commits `e6b5dd7` (5movierulz, moviecok, dramacool, resolvers),
  `ecb6a84` (levidia), `7069e2f` (filmiy.in importer that built the existing 3,837-post
  staging DB — it had been untracked, 38 tests) are local and **pushed**; GitHub master is
  `7069e2f`. qoder1's `3fb1a6c`, `a0ecbce`, `1a7b475` verified green and included.
- **Progress at 01:20:** dramacool finished (544 posts / 9,675 sources); 5movierulz finished
  (601 pages, 442 unique works / 6,491 sources); moviecok is crawling (753+ posts); levidia
  next. `Fast_Fetch/audit_staging.py` is committed and pushed (`9fa263f`): 27 catalogs,
  292,462 posts, 2.48M releases, 1.98M sources, 0 measurable subtitle rows, 17,373 adult-flagged
  posts, plus schema-drift warnings for every legacy DB. qoder1's App snapshot work landed as
  `6c923f7` after lint suppression was removed; 481 tests, 0 failures, `OVERLAP=NO`. GitHub
  master is `6c923f7`.
- **kisskh, ready for pilot:** suite is 129 tests OK in 9.6 s with no live socket; all three
  review findings fixed (missing-column migration for `sources`, single-quote slug path,
  subtitle rows stored `unverified`). Player-data was probed independently: eleven live
  `text/vtt` tracks per title (tl, km, en, id, ms, pt, ar, hi, de, fr, es), a sampled track
  returning HTTP 200.
- **Milestone closed at 02:00 — 30 integrations, verified.** 26 catalogs (21 legacy site
  parsers plus dramacool, 5movierulz, moviecok, levidia, kisskh) and 4 resolver adapters
  (vidsrc, vidlink, 2embed live; superembed documented-blocked) = 30. kisskh shipped as
  `44efa5a` (2 files, 2,784 lines, 129 tests) plus continuity `a311012`; GitHub master is
  `a311012`. Final kisskh staging: **669 works, 11,550 releases, 12,999 stream + 763 iframe +
  126,984 subtitle sources**, eleven languages at 11,533 rows each (ar, de, en, es, fr, hi,
  id, km, ms, pt, tl) from res.cloudinary.com and sub.cdnauto.xyz, every subtitle row honestly
  `unverified`, 10 adult-flagged works stored and never displayed, episode maps in `raw_meta`
  for all 669. Other new catalogs: dramacool 544/9,675; 5movierulz 442/6,491; moviecok
  1,738/7,452; levidia 147/2,976; filmiyin 3,837/17,541. The legacy 21 still carry no
  subtitle data (audit-proven), so kisskh is the first subtitled catalog.
- **Live-site constraint learned:** kisskh's REST listing at `per_page=100&_embed=1` returns
  5.3 MB and crosses a 30 s timeout; `per_page=20` with a 60 s listing timeout works. Do not
  combine `_fields` with `_embed` on that host — `_embedded` comes back empty.
- **Open items:** mp4moviez parser upgrade for JS-gated `data-key` downloads; the untracked
  `import_mp4moviez.py`/`test_mp4moviez_import.py` are unverified OpenRouter drafts (their test
  imports a module that does not exist) — do not commit them as-is. Eight new candidate
  domains probed today were all NXDOMAIN, so the roster stays at 26 catalogs.

