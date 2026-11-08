# Session 104 — Scraper Fixes (gap audit top 5 + runners-up, 19th site xprimehub)

Date: 2026-11-08 (PKT). Branch: `tracking-a-20261107`, base `770cc30a` (Session 103, live).
Scope: importers/scrapers + registry bases only. No host unwrappers (crack-methods
researcher owns those). No production DB writes in this session — VM dry runs only,
staging DBs under /tmp.

## What the gap audit found (before)

~1,060 links sampled across 54 posts (3 newest per site). Capture rates:
world4ufree 0% (gateway rotated w4links.space -> w4links.cfd), ssrmovies 65%
(24/69 buttons = dl.direct-cloud.top ignored; episode numbers dropped for all
series), bolly4u 42% (photojin rotated .study -> .buzz; filter AND unwrapper both
hardcoded), filmyzilla 0% real (importer stored fabricated fzcdn.store/file/<base64>
URLs that never appear on any page; real host is gdflix behind a gateway 302 it
never followed), hdhub4u 50% (downloads 70/70, watch 0/70 — playdrive 38 +
hubstream 16 + vidaraa 16 dropped; newest movie post lost whole — its only link
is hubdrive.blog), hdtvb max 4 of 9 mirrors (hubcdn hides 8; --resolve-direct
extracted hubcloud+gdflix then silently dropped them), rareanimes 66% (195/572
anchors lost: yournewdomain.com 101 hubcloud-alias mirrors + hubcloud.pw 26 have
no importer branch), toonworld4all 100% capture but 0% resolved by default,
10xflix/7starhd 88% (screenshot anchors + same-URL-different-quality dedup),
9xmovies 100% real (screenshot anchor was a bogus extra release).

## VM probes (before the fixes — all from the Oracle VM)

- linksddr: WORKS (newest 9xmovies post -> bridge, CSRF, unlock POST 200, 25 hrefs).
- fastilinks: WORKS (newest world4ufree post Jailer 2 -> w4links.cfd/115368/ ->
  fastilinks.beauty, unlock POST 200, 14 anchors).
- mobilejsr: WORKS with cookies (round 1 without a cookie jar: unlock POST 403;
  round 3 with CookieJar: POST 200; Indian Idol S017E07 -> 9 mirrors / 8 services).
- katmoviehd hidden API: WORKS (feed __data.json parses via parse_sveltekit_chunk,
  12 items; API GET 200, upload_links=9 keys).
- rogmovies.asia: CONFIRMED LIVE (user found it 07:14 PKT; home 200, 201,707 bytes;
  post-sitemap 1,000 locs; sample post -> 3 nexdrive.beer anchors = exactly the
  shape the old importer parses). Fix = base URL only.
- hdhub4us.co.in: LIVE HDHub4u-family site (home 200, 171,778 bytes). Mirror
  verdict: recorded as an hdhub4u known_mirror; exact-content comparison vs
  new12.hdhub4u.cl pending (see open items).
- xprimehub.pics recon: WP site, nexdrive shape (home 200, 159,334 bytes; title
  "XprimeHub - Download 18+ Indian OTT Web Series & Adult Movies Free"; sitemap
  index 39 locs; sample post -> exactly 1 nexdrive.beer link).

## Fixes built (all in Fast_Fetch/)

1. world4ufree: base .tours -> https://world4ufree.gay; gateway regex
   w4links.space -> w4links.[a-z]+ (any TLD); unwrap_fastilinks gained an optional
   referer param; scrape dispatch on "w4links." in bridge_url.
2. ssrmovies: button regex + findall accept secure.linkszilla.top/view/ OR
   dl.direct-cloud.top/d/; parse_ssrmovies_release_button returns "gateway";
   extract uses re.finditer + preceding "Ep NN" headings in document order;
   dedup key (url, episode); direct-cloud buttons resolve via
   fast_fetch.unwrap_direct_cloud (service direct_cloud).
3. bolly4u: base bolly4uv.com -> https://bolly4u.lol; photojin filter
   "photojin.study" -> "photojin." at 3 spots; unwrap_photojin derives /action URL
   + Origin from the landing page's own host (pj_origin).
4. filmyzilla: base thefilmyzilla.in -> https://www.filmyzilla80.com; fabricated
   fzcdn.store/file/<base64> source DROPPED (and unused import base64 removed);
   modern path follows the gateway 302 via resolve_direct_cdn and stores the real
   target as gdflix (or google_cdn); base_url derived from the post page's own
   domain; legacy server regex host widened www.filmyzilla\d+\.com ->
   [\w.-]*filmyzilla[\w.-]*; legacy path fetches the server page and resolves
   /verified/chqv/server_N/ buttons to their real host. (Late self-review fix:
   the legacy /download/ server_1/server_2 blocks labeled any non-gdflix
   target as google_cdn; they now use the same 3-way derivation as the modern
   path, and a docstring typo www.www.filmyzilla80.com was fixed. Tests re-run
   10/10, gate re-run 50/50.)
5. hdhub4u: base hdhub4u.fans -> https://new12.hdhub4u.cl; hubdrive added to all 3
   release regexes; is_hubdrive branch fetches the hubdrive page and runs
   unwrap_hubcloud_drive on each hubcloud href; NEW parse_hdhub4u_watch_links —
   playdrive.vip /e/.../s-20/ep-NN, hubstream.art /#..., vidaraa.cc /e/... stored
   as ordinary releases (service = watch host, never unwrapped; multimovies
   precedent: no kind column).
6. hdtvb: extract_post_data_hdtvb appends hubcloud + gdflix sources from
   resolve_hubcdn_direct. (Re-scoping hdtvb is an owner decision — not done.)
7. rareanimes: base .mov -> https://www.rareanimes.fans; dispatch now matches
   hubcloud.ist / hubcloud.pw / yournewdomain.com on the hubcloud branch.
8. toonworld4all: --resolve now default=True + new --no-resolve opt-out;
   build_parser() factored so the default is unit-testable.
9. 10xflix / 7starhd / 9xmovies: screenshot-label filter (r"screen\s?sho+?t"
   matches both "Screenshot" and "Screenshoot") + dedup on (url, quality).
   Bases: 10xflix.bond -> 10xflix.asia; 7starhd.dentist -> 7starhd.surgery;
   9xmovie.bayern -> 9xmovie.camera.
10. Other bases swept: rogmovies.one -> rogmovies.asia; moviezguru.guru ->
    moviezguru.technology; vegamovies new1.vegamovies.lease -> https://vegamovies.lease.
    Already correct, verified: desicinemas.pk, hindilinks4u.zip,
    new.katmoviehd.top, m1.multimovies.courses, new1.ssrmovies.page,
    toonworld4all.me. hdtvb base UNTOUCHED (owner decision).
11. Registry refresh (domain_registry.json, v1 shape kept; v2 is Session 105):
    updated_at 2026-11-08T02:37:07Z; 19 sites (xprimehub added). Mirrors: live
    first; previous active base kept where it redirects; dropped dead/hijacked
    (desicinemas.tv hijacked to koi5000sultan.com, desicinemas.chat dead,
    hdhub4u.fans landing page, new3/new2.hdhub4u.free dead, rogmovies.one/.quest
    vegamovies doorway). hdhub4us.co.in added as an hdhub4u mirror.
12. NEW importer import_xprimehub.py (~380 lines, modeled on import_rogmovies.py):
    sitemap sync (index -> post-sitemap1..5), nexdrive extraction, bridge stored
    as-is when resolve_bridges=False, nexdrive-page mirror resolution via
    _resolve_nexdrive_anchors (fastdl/vcloud/vegadrive/filepress unwrapped, rest
    as-is with domain as service), -:Episodes: N:- blocks, staging DB
    xprimehub.db, site 'xprimehub'. Every returned post carries "is_18_plus": 1.
13. Site authority: fast_fetch.py ADULT_SOURCE_SITES frozenset() ->
    frozenset({"xprimehub"}) with a dated evidence comment. is_adult_title() now
    returns 1 for any title with source_site='xprimehub'; save_scraped_data
    already passes source_site and ORs an importer-asserted flag, so both
    mechanisms agree.

## xprimehub — owner decision (07:16 PKT 2026-11-08)

User: YES, scrape it — just scrape. 19th site, new importer, scrape ALL its
content, tag EVERY row is_18_plus. Do NOT publish: flagged rows must never appear
on any public surface (no listing, no play — existing adult-flag rule; operator
panel is the only exception; NULL = PUBLIC). Hiding verified with a live check
after the dry run (see below). Dry-run on the VM first, no live DB writes until
the flag + hiding are proven.

## Tests

- NEW Fast_Fetch/test_xprimehub_import.py — 6 tests: extract parses nexdrive
  bridge; neutral title still flagged 18+ (site authority); site-authority unit
  checks; save path into temp DB carries the flag; sitemap sync (mocked client)
  ingests 1 post URL, skips category; registry entry check. Registered in
  .github/workflows/backend-ci.yml as a 🧪 step after test_hubcdn_unwrap.py —
  52 -> 53 🧪 steps; gate 49 -> 50 modules.
- Session104 test classes appended to 10 existing test files (world4ufree,
  ssrmovies, bolly4u, filmyzilla, hdhub4u, hdtvb, rareanimes, toonworld4all,
  10xflix, 7starhd, 9xmovies): 1-2 focused tests each, pure parse functions or
  fake clients, no network.
- Two tests updated for the changed adult-authority decision (NOT weakened —
  both still pin the exact set membership): test_database.py
  test_adult_source_site_authority_is_empty_and_fail_closed ->
  test_adult_source_site_authority_is_xprimehub_only; test_adult_corroborated_fold.py
  test_site_evidence_is_currently_no_evidence_at_all ->
  test_site_evidence_is_xprimehub_only (a plain film from bolly4u still does not
  agree; the same film from xprimehub does — site authority is now a witness
  only for xprimehub rows; xprimehub has zero live-catalog rows yet, so the
  2026-10-30 provenance numbers in that module's docstring are unaffected).
- Filmyzilla test fix: the _FakeFZClient returned "" as final_url, so the
  own-domain derivation built ":///download/..."; the fake now echoes the
  requested URL like the real client. (The importer was correct; the fixture
  was wrong.)
- Local results: world4ufree 8 OK; ssrmovies 8 OK; bolly4u 9 OK; filmyzilla 10 OK;
  hdhub4u 27 OK; hdtvb 9 OK; rareanimes 15 OK; toonworld4all 14 OK; 10xflix 7 OK;
  7starhd 6 OK; 9xmovies 6 OK; xprimehub 6 OK; test_database 182 OK;
  test_adult_corroborated_fold 44 OK.
- Full gate: python3 ~/workspace/run-backend-gate.py — 50/50 PASS, FAILED MODULES: 0.

## VM dry runs (probe104-dryrun.py, /tmp/session104-dryrun on the VM)

Per-site capture on the NEWEST live posts (before -> after, audit baselines):

- **world4ufree** (was 0%): Jailer 2 — 4 releases, 31 unwrapped sources; Bigg Boss
  S20 — 4 releases, 779 unwrapped sources (series; every episode's bridges unwrap);
  Madraskaaran — probe reported 0 under the 300s cap (the Bigg Boss unwrap consumed
  the budget); standalone re-test of the same bridge (w4links.cfd/116710/) unwraps
  8 pairs live (mediafire, gdflix, drivehub, gofile, cloudflare_worker...). Site
  restored.
- **ssrmovies** (was 65%, episodes dropped): Kapil Show S05 — 21 releases, 185
  sources, 15 services incl. direct_cloud, episodes [1..7] (Ep NN headings now
  captured); Indian Idol S17 — 21 releases, 240 sources, direct_cloud, episodes []
  (that page carries no Ep NN headings on its buttons); Dhamaal S02 — 27 releases,
  220 sources, direct_cloud, episodes []. Sources fully captured; episode
  attribution works where the page prints Ep NN headings.
- **bolly4u** (was 42%): Ramayana — 3 releases, 9 links, 3 photojin unwrapped;
  Jailer 2 — 3 releases, 9 links, 3 unwrapped; Kapil Show S05 — 1 release,
  7 links, 6 unwrapped. photojin.buzz links captured + unwrapped.
- **filmyzilla** (was 0% real — fabricated fzcdn): FZ80 Jailer 2 — 3 releases,
  7 sources, all filmyzilla_server; Onimusha S01 — 1 release, 1 source
  (filmyzilla_server). See the filmyzilla verdict below — fabrication is gone,
  but no playable source comes out of either current site live.
- **hdhub4u** (was 50%; newest movie post lost whole): The Dark Heaven — 5 releases,
  24 sources, services [fsl_r2, hubcloud, hubcloud_10g, hubdrive, pixeldrain]
  (hubdrive.blog now parsed — the lost post is recovered). Bigg Boss S20 — 126
  releases, 847 sources: 63 download + **63 watch** (playdrive, hubstream,
  vidaraa all captured; was 0/70 watch). Kapil Show S5 — 14 releases, 145
  sources: 7 download + 7 watch (playdrive). All 3 audit posts proven.
- **rareanimes** (was 66%; 195/572 anchors lost): Black Clover S01 — 71 releases,
  406 sources; Ranma 1/2 S03 — 6 releases, 42 sources; Attack on Titan S04 — 54
  releases, 258 sources. Total 706 sources; hubcloud + hubcloud_10g + fsl_r2 +
  pixeldrain + mega + razorshell all present — the hubcloud-family branches
  capture the previously lost anchors.
- **hdtvb**: probe BLOCKED — hdutv.com sitemap fetch returns HTTP 403 Forbidden
  from the VM. The hubcloud+gdflix append is in the code and unit-tested, but
  there is no live post to dry-run against. Re-scoping hdtvb stays an owner
  decision. UPDATE: the CLI phase later proved it live (2 posts, 72 sources,
  gdflix + hubcloud present — see CLI section); the probe's 403 was transient.
- **toonworld4all** (was 100% capture, 0% resolved by default): Ranma 1/2 2024 S03
  — 24 releases, 96 sources, services [filepress, gdflix, hubcloud, mega];
  Attack on Titan S04 — 120 releases, 480 sources, same services. Total 576
  sources, resolved by default now.
- **10xflix / 7starhd** (was 88%): Ape vs Mecha Ape — 3 releases (3 tiers, no
  screenshot release, no same-URL dupes), 32 sources, 11 services, on BOTH sites
  (byte-identical catalog confirmed live — the double-ingestion dedupe decision
  is still the owner's); Dhamaal S02E09 — 3 releases, 34 sources (10xflix) /
  24 sources (7starhd).
- **9xmovies** (was 100% real): Batman The Dark Knight — 3 releases, 26 sources
  (incl. uploadflix — the newly cracked host already appears in fresh scrapes);
  WWE SmackDown 6 Nov 2026 — 2 releases, 21 sources. No bogus screenshot release.
- **rogmovies** (was reported dead — alive at rogmovies.asia): Kankan Dey Ohle —
  3 releases, 13 sources; Baapya — 3 releases, 14 sources; The Dark Heaven — 3
  releases, 14 sources. Services [fastdl, filepress, fsl_r2, google_cdn,
  vegadrive] — nexdrive mirrors resolve to real hosts (the old importer stored
  the bridge as-is). Base fix = the whole fix.
- **xprimehub** (NEW, 19th site): Seclusion — 3 releases, 12 sources; Bergman
  Island — 1 release, 4 sources; California Love — 2 releases, 8 sources.
  Services [dropgalaxy, fastdl, google_cdn, hubcloud] — nexdrive-page mirrors
  resolve. **Every post is_18_plus: 1** (site authority + importer flag agree).

All 13 probe sites complete (runner DONE 08:30:38 PKT). CLI dry runs complete
(ALL CLI DONE 08:58:08 PKT — see below).

## CLI dry runs (run-cli.sh, /tmp/session104-dryrun/cli on the VM)

Two phases per site: (1) sync catalog URLs (--sync-api --max-pages 1 or
--sync-sitemap), (2) scrape --limit titles into a staging DB under /tmp.
No production DB touched. Counts are posts/releases/sources stored in the
staging DB after the scrape. Note: the runner's built-in query function had
a quoting bug (`WHERE type=table` — the SSH wrapper ate the quotes), so all
counts below come from the fixed standalone /tmp/session104-dryrun/query.py
re-run over every staging DB at the end.

- world4ufree: posts=2 releases=8 sources=167 services=[cloudflare_worker,
  drivehub, gdflix, gofile, mediafire, sendnow, usersdrive, vikingfile].
  Scrape hit the 600s cap (exit 124) on the 3rd post (Bigg Boss S20, the
  779-source series); 2/3 posts saved. The probe above has the full 3-post
  numbers (31 + 779 sources).
- ssrmovies: posts=3 releases=69 sources=645 services=[1fichier,
  clicknupload, direct_cloud, dl, fsl_r2, gdflix, gofile, hexload,
  hubcloud_10g, megaup, multiup, pixeldrain, stream, streamtape, vikingfile].
  EXACT probe match (69 releases, 645 sources); direct_cloud present.
- bolly4u: posts=3 releases=7 sources=40 services=[drivehub, google_cdn,
  movcloud, multicloud, sharedrive]. google_cdn = the photojin unwrap target.
- filmyzilla: posts=3 releases=9 sources=13 services=[filmyzilla_server].
  All gateway-fallback rows (honest, no fabrication); no playable source,
  same as the probe.
- hdhub4u: posts=2 releases=18 sources=18 services=[greenmotors]. The CLI
  picked 3 newer posts than the audit's (all greenmotors-only); save path
  proven. The audit-post proof is the hdhub4u-audit run below.
- hdhub4u-audit (seeded cache, the 3 audit posts only): posts=3 releases=145
  sources=1016 services=[fsl_r2, hubcloud, hubcloud_10g, hubdrive, hubstream,
  pixeldrain, playdrive, vidaraa]. EXACT probe match (145 releases, 1016
  sources); hubdrive=44 rows, watch (playdrive/hubstream/vidaraa)=70 rows.
  (A second query line in the log shows 271/1863 — that is a DUPLICATE from
  two overlapping audit runs racing on Bigg Boss; the true count is 145/1016.)
- hdtvb: posts=2 releases=12 sources=72 services=[cloudflare_r2, gdflix,
  gofile, hubcdn, hubcloud, pixeldrain]. gdflix + hubcloud present — the
  Session 104 append proven live. (The probe's sitemap 403 was transient;
  the CLI sync+scrape both exited 0.)
- rareanimes: posts=2 releases=77 sources=448 services=[fsl_r2, hubcloud,
  hubcloud_10g, mega, pixeldrain, razorshell]. hubcloud present (the fix).
  Re-run: the first attempt failed because the runner passed --max-pages,
  which this CLI does not have (argparse exit 2, runner bug); re-ran with
  --sync-api --sync-index + --limit 2.
- toonworld4all: posts=2 releases=144 sources=576 services=[filepress,
  gdflix, hubcloud, mega]. EXACT probe match (144 releases, 576 sources);
  resolved by default.
- 10xflix: posts=2 releases=6 sources=65 services=[1fichier, dl, frdl,
  gofile, hubdrive, megaup, mobilejsr, multiup, streamtape, vikingfile, voe].
- 7starhd: posts=2 releases=6 sources=65 — IDENTICAL counts and services to
  10xflix (byte-identical catalog, same 2 posts).
- 9xmovies: posts=99 releases=170 sources=1609 services=[1fichier,
  filepress, frdl, gofile, hubcloud, hubdrive, lulustream, megaup, multiup,
  savefiles, streamtape, uploadflix, vikingfile, vinovo, voe]. Note: --limit 2
  did not limit this CLI to 2 posts — it scraped the whole synced page (100
  titles, 99 saved). uploadflix (newly cracked) already appears in fresh
  scrapes.
- rogmovies: posts=2 releases=6 sources=22 services=[dropgalaxy, fastdl,
  filepress, gdtot, google_cdn, hubcloud]. Base fix proven via CLI.
- xprimehub: posts=2 releases=2 sources=10 flagged18+=2/2 services=[fastdl,
  filepress, fsl_r2, google_cdn, vegadrive]. Every post flagged 18+.
- vegamovies: posts=0 releases=0 sources=0. The 1 pending title was skipped
  as a review page (pre-existing importer behavior; Session 104 changed only
  its registry base, which the domain tracker verified live). Not a
  regression — the audit rated vegamovies 100% real and no fix was needed.
- moviezguru: posts=61 releases=129 sources=258 services=[google_drive].
  The sync is slow (0.10 titles/s, one full post fetch each); it hit the 600s
  cap and was SIGKILLed at 60/100 titles (exit 137), then the scrape added 1
  more post. Session 104 changed only its registry base (verified live by
  the domain tracker); the audit rated it 100% real and no fix was needed.

### Filmyzilla verdict (live, from the VM — the audit's expectation is NOT met)

The brief asked for: follow the gateway 302 to gdflix + drop the fabricated fzcdn
URLs. Both are DONE in code, and the gateway mechanism is proven live:
HQ /download/105261/server_1 -> 302 -> https://gdflix.dev/file/PHwypAkHUPxSizS.
But live post extraction yields no playable source from either current site:

- **FZ80** (www.filmyzilla80.com): movie pages link to server/<id>/<slug>.html
  pages; the 480p server page carries 4 /verified/chqv/server_N/ buttons, which
  resolve (one hop) to /dl/<id>/server_N/?token=... — and that page is a
  **Cloudflare Turnstile "Verify to Continue"** challenge (no links, one POST
  form). Same Turnstile wall the crack-methods researcher hit on fzcdn/filepress.
  The 720p/1080p server pages carry NO /verified/ buttons at all (different shape
  per quality), and /download/<id>/server_1 on FZ80 returns empty HTML (no 302).
  Stored sources are the real /dl/ links (honest, not fabricated), but they
  dead-end at Turnstile for a stdlib scraper.
- **HQ** (filmyzillahq.in): post pages (e.g. jewel-thief-7133.html) are bare
  detail pages — zero "download"/"server" mentions, no scripts except the
  Cloudflare beacon, no AJAX, no onclick. The sitemap's 16,138 locs are all bare
  post pages; no /movie/ or /download- locs. /download/105261/ returns 200 with
  0 bytes. The download IDs the gateway needs are exposed NOWHERE the crawler
  can see — the modern path cannot trigger from a post crawl.
- Net: filmyzilla no longer fabricates (the audit's core complaint is fixed),
  and the gateway-302 mechanism works when a gateway URL exists — but the
  current sites yield no playable source server-side. HQ download-ID discovery
  and the FZ80 Turnstile wall are follow-up work (headless browser / API hunt),
  not this session.

## xprimehub hiding proof (LIVE, scratch server on the VM, 08:5x PKT)

Scratch `fast_fetch serve` on loopback 18099, DB = the xprimehub CLI staging
DB + 1 unflagged control post, scratch secret only, no production DB. Results:
- `GET /api/v1/posts?limit=50` → 1 post returned: the CONTROL only;
  both flagged xprimehub rows ABSENT.
- `GET /api/v1/posts/1` (flagged) → 404; `GET /api/v1/posts/3` (control) → 200.
- `GET /api/v1/stream?id=<minted handle for flagged source 1>` → 404
  (handle minted with `redact.mint_token(1, <scratch secret>)`).
- Scratch server killed afterwards; port 18099 closed.
Code guards confirmed: list uses `redact.adult_clause("p")`, detail 404s on
`is_18_plus`, stream refuses flagged handles (test_redact AdultDenial tests
also green in the gate). Caveat: the control post uses a fresh
canonical_key ("control-film-2026") that shares no key with a flagged row,
so this proof does not exercise the `inherit_key_adult()` twin-hiding path —
a flagged xprimehub row sharing a canonical_key with a mainstream row would
hide the twin at write time (merge). Dry-run only, no live writes, so no
risk now; flag it again at merge time.
The proof script on the VM is /tmp/session104-dryrun/hide-proof.sh (rewritten
for the real staging schema — the first draft assumed wrong column names);
log /tmp/session104-dryrun/hide-proof.log.

## Open items / owner decisions (not blocking this session)

- Retire rogmovies: SUPERSEDED — rogmovies is ALIVE at rogmovies.asia (user
  found it 07:14 PKT); base update is this session's work.
- Re-scope hdtvb: still an owner decision (not done here).
- Torrentsave links in the catalog or not: undecided.
- Dedupe 10xflix+7starhd double ingestion at merge: undecided.
- hdhub4us.co.in exact-content comparison vs new12.hdhub4u.cl (mirror
  confirmation): pending.
- Negative-cache invalidation when a new unwrapper lands (no_unwrapper rows
  stale until TTL expiry): follow-up owed, not assigned here.
