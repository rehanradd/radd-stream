# Session 102 — Phase B: multimovies (2026-11-08)

Phase B of the scraper-audit build order: multimovies first (audit pick
#1 — the only site whose hosts the resolver already unwraps). Read-only
probes against the live site, the live catalog DB, and the live server
(`tracking-a-20261107` @ `f722da95`, Session 101 live since 02:08 PKT).
No live deploy in this session; the parent runs the gate deploy after.

## What was probed (fresh numbers — the D2.5 90/120 figures are UNVERIFIED, no primary probe record exists; these replace them for multimovies)

Site live: base `https://m1.multimovies.courses` 200, no redirect, 0.50 s;
`/sitemap.xml` 200, 0.43 s; `/robots.txt` 200, 0.53 s. VM load 0.80,
MemAvailable 10,369 MB at 02:12 PKT.

Catalog (live DB, read-only): multimovies posts 3,703; `download_sources`
joined via `releases.source_site='multimovies'` = 432,612 (the audit's
648,599 was a different grouping — do not quote either as one final
count without re-measuring the same way). Newest posts: 130016
Pennyworth: The Origin of Batman's Butler (series), 130015 Merry Berry
Love (series), 130014 Band of Brothers (series), 130013 The Chalk Line
(movie), 130012 Avatar: Seven Havens (series), 130011 May I Come in
Madam? (series), 130010 Kites (movie).

Service breakdown (multimovies, top): cineverse iframe 70,050; filmu
69,782; vidbolt 69,782; vidout 69,782; vidrift 69,782; nexus 69,780;
gd-mirror 59,896; iqsmart 26,918; hubcloud-ist download 26,740;
dl-fastdlserver-site 18,120; filesforever-mirror 13,952; gdmirror 10,889;
vcloud-beer 7,363; filebee-xyz 6,858; screenscape 6,649; fastdl-beer
6,524; nxstream 5,084; vidzee-mirror 4,489; modiplay 4,287;
filesforevermirror 3,257; peachify-mirror 2,831; nhd-stream 2,670;
vidlink-mirror 2,383; vixsrc-mirror 2,382; cinemaos-mirror 2,227;
gofile-io download 1,793; megaup-net 1,618; 1fichier-com 1,218;
vikingfile-com 1,210; mixdrop-ag 1,154. Count 0 for services named
`pkembed`/`mxdrop`/`vibuxer`/`vidly`/`streamhg` — those names do not
appear as `service` values; the hosts appear under the watch-server
names above.

### Probe run 1 — post 130013 The Chalk Line, first press (script /tmp/mm-probe1.sh)

| server | result | time |
|---|---|---|
| cineverse | 302 | 4.58 s |
| gdmirror (iqsmart) | 302 | 5.57 s |
| nexus | 302 | 5.47 s |
| vidrift | 302 | 9.23 s |
| vidout | 404 | 2.19 s |
| filmu | 404 | 1.95 s |
| vidbolt | 302 | 1.95 s |

5 of 7 watch servers play on first press. Tokens: cineverse
`AdPyZ_tMHEF4mSIFxw`, iqsmart `AdPyZ_tMHEF5Tsa8Lw`, nexus
`AdPyZ_tMHEF6ZceHWg`, vidrift `AdPyZ_tMHEF7tNLOhw`, vidout
`AdPyZ_tMHEF8Wal9JQ`, filmu `AdPyZ_tMHEF9b8kvWQ`, vidbolt
`AdPyZ_tMHEF-bZK56Q`.

### Probe run 2 — same 7 tokens, repeat press (/tmp/mm-probe2.sh)

cineverse 302 in 2.14 s (Location: modiplay `stream_proxy.php?url=…vibuxer.com/stream/…`),
iqsmart 302 in 2.47 s (Location: `hanerix.com/stream/…/master.m3u8`),
nexus **404 in 1.79 s** (was 302 first), vidrift 302 in 6.06 s
(Location: `embed.vidrift.net/api/orion/370f4fe85d325f7115c1889c837450ea/master.m3u8`),
vidout 404 in 1.94 s, filmu 404 in 1.95 s, vidbolt 302 in 1.76 s
(Location: `dash-hls-bridge.johndoesdmc.workers.dev/?url=…sacdn.hakunaymatata.com/dash/6412237077…`).
**Repeats are NOT milliseconds** — working copies still cost 1.8–6.1 s
(warm `final_url` re-probe / re-resolve), dead copies ~1.8–1.9 s.

### Probe run 3 — post 130010 Kites, first press (/tmp/mm-probe3.sh)

vidbolt 302 in 6.67 s, cineverse 302 in 3.98 s, vidout **302 in 2.48 s**
(was 404 on Chalk Line), filmu 404 in 2.00 s, nexus **302 in 2.75 s**
(was 404 on repeat for Chalk Line). **Vidout and Nexus are flaky
per-title, not consistently dead.**

## Why repeats are not milliseconds (traced in code)

`Fast_Fetch/fast_fetch.py`: the negative-cache check (~6222–6245)
returned `reason: negative_cache` only when the *primary* row itself
carried a fresh record — but a dead primary still ran the Stage-1
sibling failover (`resolve_release`, ~6715–6788) and the Stage-2 general
failover (~6792+, same-release LIMIT 10 then cross-release LIMIT 10,
10 s budget), each sibling re-resolved with `_failover=False`; and a
*working* primary with a warm `final_url` still pays a cached probe
(Stage-1 `probe_media` or Stage-2 `_stage2_probe`) plus, when
`needs_refresh` (bridge `final_url`, expiry, `is_temporary` > 6 h), a
full unwrap. The negative cache made repeats 4–7x faster than first
presses (Session 101 live proof: Pushpa 2 repeats 1.6–2.1 s vs 13.8 s
first), but the floor is the failover + re-probe work, not the cache
lookup. F1 below removes the two cases where the cache was consulted
and then ignored.

## Fixes in this session

### F1 — a negative-cache hit no longer refuses while a sibling plays (`fast_fetch.py`, `resolve_live_source`)

Session 101's early return refused the whole press when the *picked*
copy carried a fresh failure record — even when a sibling copy plays.
Multimovies is the shape that exposes it: 7 single-copy releases per
title, so the picked copy is very often the dead one while 5 siblings
play. The hit now only skips the picked copy's own work and falls
through to the sibling failover:

- The cache check sets a `_negative_cache_hit` flag instead of
  returning; `needs_refresh` starts True on a hit (cached probes would
  only re-prove the same negative), and the dispatch block is wrapped
  in `if _negative_cache_hit: … else:` — the hit branch classifies the
  backend (for the `stage1_tried` gate), records the failed address in
  `_cached_probe_failed_url` (final_url or source_url) so the stale
  fall-through does not re-probe it, and skips the unwrap.
- The failure re-record after a miss is now gated on `not
  _negative_cache_hit` (a hit must not stretch its own TTL on every
  press), and the expired-record clear changed from a second `if` to
  `elif` — the early return used to guard it, and without the return a
  fresh record would have been cleared at once.
- The stale fall-through comment now covers the record case (it used to
  say the address "failed its capped probe seconds ago in this same
  call" — a cache-hit address failed within the TTL, not this call).
- A lone copy with no playing sibling still refuses with no probe
  (reason is now `stale_probe_failed`, not `negative_cache` — the
  `negative_cache` reason value is retired; the row still carries
  `failure_class`).

Tests (`test_database.py`): `test_negative_cache_refuses_a_recently_failed_copy`
updated to the new reason; NEW
`test_negative_cache_hit_still_serves_a_playing_sibling` (first press
records + serves the sibling by failover; second press skips the picked
copy — exactly one probe, the sibling's — and serves it again; the
picked copy's record stays set) and NEW
`test_negative_cache_hit_with_all_siblings_dead_probes_nothing` (both
copies recorded; the repeat press probes 0 addresses).

### F2 — a single-copy Stage-1 release falls through to Stage-2 (`fast_fetch.py`, Stage-1 sibling failover)

The Stage-1 no-winner return (`stage1_all_copies_failed`) fired even
when the same-release sibling list was EMPTY — the ladder tried
nothing, yet refused before Stage-2 could run. That is the multimovies
shape (one copy per release) whenever the picked copy is a Stage-1
backend. The return now fires only `if _siblings:`; with no
same-release Stage-1 siblings the code falls through to the Stage-2
cross-release ladder.

Failover ordering does not help multimovies as written:
`tiers.candidate_order_sql` ranks `playback_type` direct(1)/url(2)/
download(3)/iframe(4) first — all 7 multimovies watch copies are
`iframe`, so they tie; `cineverse`/`gdmirror`/`nexus`/`vidrift`/`filmu`
are not in `SERVER_PREFERENCE` (only `vidout` rank 9 and `vidbolt`
rank 10 are), so they fall to ELSE 17 and the order collapses to
freshness/id — effectively id order, not proven-host order. Verified by
a live query: the cross-release candidate list for post 130013
(excluding release 1601601) in `candidate_order_sql("s")` order is
3702504 cineverse, 3702505 gdmirror, 3702506 nexus, 3702507 vidrift,
3702509 filmu, 3702510 vidbolt. Adding the multimovies server names to
`SERVER_PREFERENCE` is a follow-up, not this session: the measured
order needs the per-host play rates first, and this session's probes
show the rates are per-title flaky, not a stable ranking.

Test (`test_database.py`): NEW
`test_stage1_single_copy_release_falls_through_to_stage2` (vidbolt
primary, sole source in its release; warm direct sibling in a second
release; resolves success by failover, `resolve_copy` called exactly
once).

### F3 — filmu/vidly extractor reads the signed bridge master (`current_hosts.py`, `_unwrap_vidly`)

The old regex `https://[A-Za-z0-9.\-]+/media/[A-Za-z0-9]+/index\.m3u8`
matches zero times on the live filmu page — the page is now a Next.js
shell (`vidly.pro/movie/960875`, redirected from `embed.filmu.in`, 200,
56,825 B, no `__NEXT_DATA__`, 2 `m3u8` mentions). The media URL now
arrives as a CloudFront-signed master behind the same dash-hls-bridge
Workers proxy vidbolt uses:
`https://dash-hls-bridge.johndoesdmc.workers.dev/?url=https%3A%2F%2Fsacdn.hakunaymatata.com%2Fdash%2F4636220553102250728_0_0_1080_h265_13%2Fmaster.m3u8&Policy=…&Signature=…&Key-Pair-Id=…`
(771 chars). **The signed query is part of the URL: without it the
bridge 502s** (verified: truncated URL → HTTP 502 Bad Gateway; full
preload URL with Policy → 200 `application/vnd.apple.mpegurl`, body
`#EXTM3U…`). Fix: decode flight-data escapes first (`\/`→`/`,
`\u0026`→`&`, `\u003d`→`=`, `\x26`→`&`, `&amp;`→`&`), then regex the
bridge URL to the closing quote, keep the old `/media/` shape as
fallback. Verified against the saved page (`/tmp/filmu-960875.html`):
`_unwrap_vidly` returns 1 candidate, exact match with the page's
preload URL; legacy old-shape page still yields its candidate; empty
page → `unverified`; series path → `series_server_unverified`
(unchanged refusal).

Test (`test_database.py`): NEW
`test_unwrap_vidly_reads_the_signed_bridge_master` (escaped bridge URL
in a preload link → exact decoded candidate incl. Policy/Signature/
Key-Pair-Id; legacy shape; empty page; series refusal without fetching).

## Importer / watchConfig — verified working, no fix needed

- `parse_watch_servers` (`import_multimovies.py`, regex
  `watchConfig\s*=\s*(\{.*?\});`, `initialServers`/`sources`) returns
  **7 servers on both a movie page (The Chalk Line) and a series page
  (Pennyworth)**, same set: 1 Cineverse
  `https://rozgarlelo.modiplay.xyz/embed/tmdb/movie?id=960875`
  (modiplay front-end), 2 GD mirror
  `https://streams.iqsmartgames.com/embed/movie/tt12683756?key=e11a7debaaa4f5d25b671706ffe4d2`
  (iqsmart/StreamHG), 3 Nexus
  `https://www.moviesnexus.fun/movie/960875?sv=multi-audio`, 4 Vidrift
  `https://embed.vidrift.net/embed/movie/960875`, 5 VIDOUT
  `https://vidout.pages.dev/movie/tt12683756`, 6 Filmu
  `https://embed.filmu.in/movie/960875`, 7 VidBolt
  `https://vidbolt.xyz/movie/960875`. **No pkembed/mxdrop in the
  current watchConfig** — the audit's host list is the resolver's
  capability, not the site's current server list. Saved pages:
  `/tmp/mm-chalkline.html` (53,103 B), `/tmp/mm-pennyworth.html`
  (85,081 B).
- Importer dry-run works on the VM:
  `python3 import_multimovies.py --dry-run --only-root
  https://m1.multimovies.courses/movie/the-chalk-line --only-root
  https://m1.multimovies.courses/movie/kites --only-root
  https://m1.multimovies.courses/series/pennyworth-the-origin-of-batman-s-butler
  --limit-episodes 2` → `Sitemaps: 2 title maps / 10606 title pages; 7
  episode maps / 64697 episode pages.` → `[3/3] complete=3 skipped=0
  restricted=0 failed=0 releases=35 sources=35`. Sitemap discovery +
  page fetch + `watchConfig` extraction still work end-to-end (dry-run,
  no DB write). Current base URL: `https://m1.multimovies.courses`
  (`DEFAULT_BASE_URL` in `import_multimovies.py`); no domain rotation
  broke the importer.

## Detail shows all unplayable (NOT fixed — needs a design decision, not a one-line fix)

`GET /api/v1/posts/130013` (The Chalk Line), `/130010` (Kites),
`/130016` (Pennyworth) — every link `kind: "external"`, `playable:
false`, label "Standard". Releases: 7 per movie (one per watch server,
e.g. post 130013 releases 1601597–1601603, `download_sources` ids
3702504–3702510, all `playback_type: iframe`, `status: active`). Cause:
`link_view` maps `iframe` → `external`, and `playable` requires kind in
(`direct`,`resolve`) — so **every multimovies watch copy is
`playable=False` in detail even when it resolves**, unlike the audit's
"playable=True is a label" case for download copies. The app's v1 ladder
therefore cannot start from detail for these titles; only the raw
`/api/v1/stream?id=<token>` path was probed. Changing `link_view` to
call iframe copies playable would mislabel the many that do not
resolve — the honest fix is a measured `playable` (probe-backed), which
is Phase D data-truth work, not this session.

## Download mirrors are gone from current pages (NOT fixed — importer follow-up)

`download_page_urls` (same-host `/download/` links) returns `[]` for
both The Chalk Line and Pennyworth pages; `parse_download_mirrors`
finds 0 `dl-mirror-btn` elements; the Chalk Line HTML contains no
`/download/` href at all. Yet the catalog holds download rows for only
646 of 10,107 distinct multimovies posts (via `releases`). The
download-mirror extraction path in `import_multimovies.py` is therefore
broken against the current page shape (or the site removed the download
section) — a follow-up, not this session: the watch path is the
multimovies value, and the fix needs a fresh look at the live page
shape, not a guess.

## Vidout flakiness — root cause: VM DNS (NOT a code fix)

`resolve_vidout_playlist` (`fast_fetch.py:3892`, `http_get` timeout 12,
`extract_hls_playlist_url` at :3865 takes the first `.m3u8` in the
page) **works** — on the VM it returns
`https://vidmmo.com/hls/ZDBtrL1WMPQipj3EubEdG6tAKeYJ0Nt3/master.m3u8`
for tt12683756, tt1198101, and tv 79588 s1e1 alike (same playlist for
different titles — suspicious, record it, do not assume it is
per-title). But **`vidmmo.com` does not resolve on the VM** (`getent`
exit 2, `socket.gethostbyname` FAIL `[Errno -2] Name or service not
known`, curl root 000; VM resolver 127.0.0.53), while the same name
resolves from the local shell to 198.18.122.211 and
`vidout.pages.dev` resolves on the VM to 172.66.47.90 (local:
198.18.122.212). So the vidout playlist host is unreachable from the
VM's DNS — that is why vidout 404s even though its embed page (200,
213,674 B, 4 `m3u8` mentions) yields a playlist. Saved page:
`/tmp/vidout-tt12683756.html`. Needs a DNS/resolver check, not a code
guess. (A direct local `resolve_vidout_playlist` call earlier took 38 s
and returned HTTP 0 — the VM call returns in ~3–4 s.)

## Nexus flakiness — root cause: rate limiting (no free fix)

Fetching `https://www.moviesnexus.fun/movie/960875?sv=multi-audio`
from the VM returns **HTTP 429** (Cloudflare "temporarily rate
limited" page, 54,039 B) in 0.06 s — Nexus rate-limits the VM's single
egress IP, so it plays on some presses and 429s on others. No unwrapper
exists for Nexus (it falls through to `no_unwrapper`); its 302s come
from failover siblings, not from resolving Nexus itself. Per-IP limits
cannot be fixed for free — failover + negative caching are the
mitigations.

## DB state after probe 1 (rows 3702504–3702510)

cineverse `final_url` = modiplay stream_proxy; iqsmart = hanerix
master.m3u8; nexus `last_failed_at` 1794086202.8484, `failure_class:
no_unwrapper`; vidrift = orion master.m3u8; vidout `last_failed_at`
1794086203.32183, `no_unwrapper`; filmu `last_failed_at`
1794086219.75693, `unwrap_failed`; vidbolt = dash-hls-bridge URL.

## Token-decode dead end (do not retry as-is)

Decoding public `stream_id` tokens with
`redact.parse_token(tok, redact.signing_secret())` fails — `redact` has
no `signing_secret`; `viewer.signing_secret()` delegates to
`redact.stream_secret()`, which raises `RuntimeError` outside the
service environment. Rows were read directly from the live DB by
release/post id instead.

## Tests

- `test_database.py`: 156 OK (was 152; +4 new: F1 ×2, F2 ×1, F3 ×1;
  1 updated Session 101 test). A first run failed the two failover
  tests on a fixture mistake — the passing probe dict used kind
  `"direct"`, which `_stage2_accept` rejects (only `playlist`/`file`);
  fixed to `"file"`, all pass.
- `test_redact.py`: 76 OK. `test_multimovies_import.py`: 9 OK.
  `test_host_classifier.py`: 74 OK (16 skipped).
- Full backend gate: 49/49 PASS (FAILED MODULES: 0).
- Import verified after every edit (`import fast_fetch` OK).

## Not in scope (unchanged)

No new unwrappers (gofile/1fichier — Phase C). No V2 legacy-id /
wrong-film fix (Phase D). No projection rebuild. No panel changes. No
app code. No live deploy by this session.

## Next steps

1. Gate deploy of this session (parent): filmu should now 302 where it
   404d; repeat presses on a dead picked copy should serve a playing
   sibling instead of refusing.
2. Download-mirror extraction break (0 `dl-mirror-btn` / 0 `/download/`
   links on current pages) — importer follow-up.
3. `playable=False`/`kind=external` for multimovies watch copies in
   detail — needs the measured-playable design (Phase D).
4. `vidmmo.com` DNS failure on the VM — DNS/resolver check.
5. `SERVER_PREFERENCE` does not name the multimovies watch servers —
   add them only once per-host play rates are stable enough to rank.
6. Phase C: ssrmovies + gofile/1fichier unwrappers (then clicknupload).
