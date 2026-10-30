# 2026-10-28 — Session: moviesmela.pk reaches its whole catalog, pkembed resolves, and three hosts are retired on evidence (Qoder, orchestrator)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 — Session: moviesmela.pk reaches its whole catalog, pkembed resolves, and three hosts are retired on evidence (Qoder, orchestrator)

Owner tasking for this session was a sequence, not a wish list: finish pkembed, fix the by-media parity
bug, record the rpmplay/filemoon verdicts, then take the MoviesMela staging database to completion with
a *bounded* live probe, and report per-site what is playable. Every commit below is local; the owner
gates and pushes. Full shas, in the order they were made:

| SHA | What it is |
| :--- | :--- |
| `8dd9c70` | `unwrap_pkembed` — the base-36 Dean-Edwards chain, renditions, `duration_expiry_from_url` |
| `7162e3e` | `viewer.py`: a by-media row answers `subtitled` the way a `q=` row already did |
| `5a9341e` | the NEEDS-JS verdicts for rpmplay and filemoon, written as measurements in `host_resolvers.py` |
| `e97d833` | `sync_catalog` writes the queue while it reads it (`QUEUE_FLUSH_BATCH = 40`) |
| `faeb99d` | pkembed also serves the bare `/<filecode>.html` page — the shape the histogram revealed |
| `7390716` | a synopsis keeps no markup, and the queue keeps its payload (this session's two audited defects) |

**pkembed, and why the media hostname is never stored.** The chain is four requests at most: the embed
page, one packed `<script>`, `to_base` unpack at radix 36 with the JS escapes resolved *first* (a
`\\'` inside the literal survives no substitution-then-parse order), and a `Range: bytes=0-511` with no
Referer to the mp4. Two things the owner asked for are encoded rather than assumed. `e=43200` here is a
twelve-hour *lifetime* stamped alongside an issue epoch in `s`, so the answer is
`duration_expiry_from_url` = `s + e - now`; the old `expiry_from_url` reads `43200` as a 1970 epoch and
would call a working file expired — each function rejects the other host's query on digit count, which
is the test. And `final_url` is only ever the *result of this call*: the durable identifier is the embed
URL, so `sources.source_url` holds `pkembed.site/embed-<id>.html` and the signed CDN URL is not
persisted anywhere. Live proof from the owner's own check on `crawlers-2026`: 206 video/mp4, 201,886,684
bytes, `_l` and `_n` renditions, 12-hour window.

**The bare `/<filecode>.html` shape came out of the staging histogram, not out of a guess.** After the
full crawl I grouped `sources` by service and saw `pkembed.site` 7 rows *apart from* `pkembed` 4,193 —
the same host named two ways, meaning seven pages had an embed URL whose path my rule did not recognise
as a file code. `PKEMBED_CONTENT_RE` was `^/embed-[A-Za-z0-9]+\.html$`; the site also publishes
`/<filecode>.html`. Measured before widening: `https://pkembed.site/zp8vd43rpa80.html` unpacks to
`noc.vkpluscdn.site` renditions and answers 206, i.e. the identical chain. The same *shape* measured
negative on mxdrop (`/e/<id>` only; `/x` there is not an embed), so `MXDROP_CONTENT_RE` stayed narrow —
widening a host rule without a live 206 behind it is exactly the "loosen the host rules" failure the
owner forbade. The widened rule broke two older tests that used fictional short codes
(`embed-x.html`); those fixtures now use real 12-character codes, because a length floor of `{6,}` is a
statement about the host and the fixtures must agree with it.

**Two defects that only an audit of the finished rows could show (`7390716`).**

1. `extract_synopsis` removed the block tags it *named* (`<p>`, `<div>`, `<li>`, `<hN>`) and nothing
   else, so a post that wrapped its embed in empty anchors stored its own markup into a display column:
   3 of the 9 synopsis rows this build wrote began with `<a href=`, and one of them is a sentence that
   repeats its own title, i.e. the correct value was NULL. Now every tag goes before the length, SEO and
   restatement tests judge the text, so a body that is only markup is simply no synopsis. Two tests,
   both from the measured page shape.
2. `export_staging` overwrote `sitemap_cache.raw_json` with the page's parse result. That payload is the
   entire reason a crawl needs no socket — without an `"id"` key in it, `_parse_record` falls back to a
   REST lookup — so **10,430 of 20,888 queue rows had quietly become re-fetchable-only**, and the
   docstring promise in `_queue_json` ("content.rendered travels with the queue row") was true only for
   rows that had never been indexed. `raw_json` is now written on a fresh insert and left alone
   afterwards; a full `sync` restored all 20,888 payloads, and re-running the 119 pending pages through
   a harness that replaces the network primitive with a raiser printed
   `REQUESTS ATTEMPTED 0` while still processing all 119 pages (`pages=119 works=1 releases=1
   sources=3 declined=118 failed=0`). One stale row was corrected locally by applying the fixed rule to
   it, not by editing prose: `posts` columns are `COALESCE(excluded.x, posts.x)`-merged — deliberately,
   so several pages of one work each contribute — which also means a value an old build wrote can never
   become NULL through a re-crawl.

**The queue-flush change, and the number it explains.** `e97d833` exists because the owner caught a
discrepancy: my first pass reported "Queued 10460 pages" while my own measurement of the REST feed is
**20,888 posts across 1,045 pages** (`x-wp-total: 20888`, `x-wp-totalpages: 1045`). The old
collect-all-then-commit design kept only what had been committed when a run died — and my run died,
because I sent it SIGTERM. It also held every page body in RAM at once (57 MB resident at 335 s, still
climbing). Flushing every 40 rows fixed both: the re-run reached 20,888 exactly and RSS stayed
39–43 MB. The lesson for the next agent is procedural, not architectural: `TaskStop` on a crawling
command sends a real SIGTERM to a real importer, and a queue count read mid-kill is not a measurement.

**The by-media parity bug the other session recorded as "not mine" is fixed** (`7162e3e`). It was a real
API drift, pre-existing at `67bfe69` and not caused by any importer work: `viewer.api_v1_get_posts`
returned a `subtitled` key that the by-media projection did not, so the same work answered the same
question differently depending on the route. The fix is in `viewer.py`, not `media_search.py` — that
module stays free of viewer imports — by applying the existing `_subtitled_posts()` existence test to a
by-media page when `full` is off. `_subtitled_posts` answers from the release grammar itself (`describe()`
per print, prefiltered by a `%sub%` SQL pass that cannot drop a true positive), so there is no second
vocabulary of subtitle flags. The test now *derives* the difference — `media_only = set(bare) -
set(by_word)` from `media_search`'s own output — instead of hand-listing keys, which is how the drift
escaped in the first place. `test_media_search.py` is 23 OK.

**Staging database, at handover** (`/home/ubuntu/radd-stream-data/moviesmela.db`, 175 MB, never
committed, `PRAGMA integrity_check` ok):

| Measure | Value |
| :--- | :--- |
| `sitemap_cache` | 20,888 rows — 20,770 `indexed`, 118 `re-check`, 0 parked; payload shape `WP` on all 20,888 |
| `posts` | 16,677 works — 14,465 movie, 1,907 complete_season, 305 series |
| `releases` | 20,770 (one page = one print; 3,057 carry an episode number, up to 141) |
| `sources` | 57,818 — 37,360 `iframe`, 20,160 `url`, 298 `download`, 0 `subtitle`, 0 `direct_byte` |
| status | 97 `active`, 9 `js_required`, 50 `redirect`, 30 `unknown`, 57,632 `unverified` |
| top services | do7go.com 19,575 · embedpk.net 16,445 · mxdrop 15,967 · pkembed 4,193 · ok.ru 1,252 |
| metadata | 16,677 with poster · 16,635 with year · 8 with synopsis · 0 orphan rows · 0 duplicate `canonical_key` · 0 display strings carrying markup |
| adult | 19 posts flagged `is_18_plus=1` (79 sources beneath them) — stored, never displayed |

**The three things that look like a systematic miss and are not.** (a) 118 pages decline: they are
`watch-online-movies-article`, `bollywood-actors-and-actresses`, category and listing shells — no player,
nothing to index, `last_note='no-players'`. (b) 20,770 releases collapse onto 16,677 works: the site
publishes the same work on several URLs (one per quality claim), and `canonical_key` is the work. (c) 8
synopses: this site's REST `content.rendered` is the player markup plus an SEO sentence — "Watch X
(2014) From link 1 Below… print quality free download" — which `extract_synopsis` is written to reject.
Four hundred sampled queue bodies confirmed it. A synopsis is stored only where the site wrote prose;
the eight kept rows are exactly that, including two live-streaming articles and one Turkish gambling page
the site genuinely publishes as a "movie" post (its lone `download` source is `basaribet.online`, kept
with `unverified` rather than hidden).

**The bounded probe, and why 57,632 rows stay `unverified` on purpose.** The owner's sizing is right: a
full `--probe` crawl is ~30k requests, not a night's work and not polite. So: 50 most-recent
mxdrop/pkembed pages requeued, `nice -n 15 … crawl --probe --workers 2 --delay 0.2` → `pages=168
works=50 releases=50 sources=186 declined=118 failed=0`. Of the 100 resolvable rows in that sample,
**97 reached `active` on a real 206** — mxdrop 47 `active` / 3 `unknown`, pkembed 50 `active` / 0
`unknown`. The JIT resolver is what probes the rest, on demand, after the gated deploy; a stored
`unverified` is an honest statement that nobody looked, not a defect.

**Coverage, still measured not claimed.** `importers/test_moviesmela_import.py` **179 OK, 1242/1242
lines, `UNCOVERED []`**; `importers/test_host_resolvers.py` **107 OK, 334/334, `UNCOVERED []`** — same
`/tmp/cov.py` `sys.settrace` + `threading.settrace` harness (denominator `code.co_lines()` minus AST
docstring spans, no pragmas anywhere, dead defensive branches deleted instead of excused). Gate, all
green offline: kisskh 129, pagalmovies 54, filmiyin 38, `test_database` 65, `test_vidout` 6,
`test_media_search` 23, `test_redact` 49, `test_api_v2` 46, `test_admin_panel` 56, `test_catalog_api`
114, `test_provenance_stamping` 12, `test_operator_isolation` 22, and
`import fast_fetch, viewer, merge_catalogs` ok.

**Hosts retired on measurements, in `host_resolvers.py`'s docstring rather than in code that pretends to
work.** The rule the owner set is one bounded attempt: no JSON and no direct media URL ⇒ NEEDS-JS, move
on. `movieshub.rpmplay.xyz` is a Vite SPA — `GET /` is 1,386 bytes titled "Loading…" with an empty body;
`/api/v1/player?t=test` answers `{"error": "Token is invalid"}`; `/api/v1/video?id=test` answers
`{"message": "Request is invalid"}`; `/api/v1/info` returns 3,040 hex chars = 95 sixteen-byte blocks that
differ *from the first byte* between two calls 12 s apart. No static key, no IV, no hex-decode helper
outside hls.js. `filemoon.to` is the same shape one tier worse: `/e/<anything>` is a 1,605-byte "Byse
Frontend" `<div id="root">` shell and `GET /assets/index-DocunfmE.js` refuses the TLS handshake (curl
exit 35). Both were read, not guessed — the payloads are in the docstring for whoever re-tests next year.

**Per-site verdicts for the rest of the build order, playable vs download-only.**

| Site | Verdict | Evidence |
| :--- | :--- | :--- |
| MoviesMela | **playable** for mxdrop + pkembed, iframe-only elsewhere | 20,160 `url` rows, 97/100 probed `active`; 37,360 `iframe` rows are catalog metadata, never a watchable link (Android has no WebView) |
| HindiDubbedPK (`movieshub.rpmplay.xyz`) | **NEEDS-JS** | the four measurements above |
| Moviehax | **not resolvable in one attempt** | its player is filemoon (NEEDS-JS), and the post body itself is a Dooplay AJAX shell: 107,946 bytes containing zero iframes and zero media URLs, only `admin-ajax` plus a `"nonce"` |
| Dotmovies (`thedotmovies.in`) | **download-only** | no media URL anywhere in the page; each download is three `mobilejsr.com/view/<id>` shortener links behind a captcha (the view page is 18,816 bytes *with* the captcha); its titles duplicate the thebollyflix/10xflix family already in the catalog |
| ApneTV (`apne.tv`, `apnetv.co`) | **blocked to this client** | 403 from Cloudflare on the first request — no page, no JSON |
| Dizilah | **blocked to this client** | 403 |

A captcha-gated shortener is a line this project does not cross: recording that the link exists, and
that a human must solve a captcha to reach it, is catalog metadata; writing a solver would be defeating
another service's access control. That is the whole of the Dotmovies verdict.

**Reported, not touched: another account's `mp4moviez` WIP.** `Fast_Fetch/importers/test_mp4moviez_import.py`
is untracked and cannot run: it does `from Fast_Fetch.importers.mp4moviez_import import (…)`, and
(i) there is no `mp4moviez_import` module — the file is `import_mp4moviez.py`; (ii) `Fast_Fetch` is not
an importable package from that working directory, so the suite dies even earlier with
`ModuleNotFoundError: No module named 'Fast_Fetch'`; (iii) of the six names it imports, only
`harvest_links` exists — `import_mp4moviez`, `parse_movie_page` (real name `parse_page`),
`create_staging_schema` (`init_db`), `clean_title` (`clean_text`) and `classify_adult_content` (inline in
`parse_page`, lines 145–149) do not. It is not mine to stage or fix, so it stays untracked and the owner
decides which account finishes it.

**Deliberately not done.** No merge into `fast_fetch.db` — verified untouched at handover:
`/home/ubuntu/radd-stream-data/fast_fetch.db` still 7,647,232 bytes, mtime 2026-10-27T01:59, 203 posts,
0 rows with `source_site='moviesmela'`. No service restart, no live API change, no `fast_fetch.py` edit.
No `--probe` beyond the 50-row sample and no mass probing. No headless browser, no JS engine, no captcha
solver. No Referer on any media request, ever — measured: the mxdrop mp4 answers 206 with none and 403
with `Referer: https://www.moviesmela.com/`. `App/`, `mp4moviez` and the other untracked workers in this
checkout are not mine to stage; `git add` named exactly the paths above and nothing else was committed.
Databases stay out of Git.


