# Muse [PHASE-E-MOVIEBOX-FOLLOWUPS]: MovieBox search recovery + year+genre gap-fill + resolver transport retry

Date: 2026-11-10 ~00:05 PKT. Builder: Muse (subagent, parent = main chat).
Base: main 399f747. Branch: `session-moviebox-followups` (NOT merged — parent
merges after review; data merge into the live catalog waits for the parent gate).

## What this is

The Session 126 full harvest left three gaps, all named in its checkpoint as
follow-ups. This session builds all three.

## 1. Search-based recovery (`recover`)

The 172 seed rows that failed deterministically ("no-subject" — the detail
page answers HTTP 200 but its Nuxt payload carries no titled subject, no
`subjectId`) and the 43 metadata-only posts (title/year/poster, no tiers)
could not be reached by the HTML crawl. Recovery is the unlocked search API:

- `client_token()` — the site's own YC() from its JS bundle, stdlib:
  `<unix-seconds>,<md5(reversed decimal seconds)>`.
- `fetch_bearer_token()` — any API call with `X-Client-Token` answers with
  an `x-user` response header carrying a Bearer token. The token is never
  logged or stored; it is held only for the run.
- `search_subjects(keyword, token)` — POST `/subject/search` with
  `Authorization: Bearer <token>` ALONE (both headers together answer 400
  'invalid token'). Transport failures retried like `_api_request`.

Proven live from the VM before coding: token call HTTP 200 with x-user
present; search "aquaman" HTTP 200 with 3 items, exact title first
(Aquaman, type 1, subjectId 9083306165420838488). Target counts measured
on the source vault (read-only): **168 no-subject rows** (of 172 queued —
the other 4 failed another way) and **43 metadata-only posts**.

`recover_missing()` reads the targets from the source vault, searches each
by keyword — slug stem for no-subject rows (the trailing 12-char mixed-case
id is dropped, the dub marker `hindi` stays), clean title for metadata-only
posts — picks the hit by exact normalized-title match among accepted types
(1 movie, 2 series), and queues the detail page + subjectId into the
follow-up vault's sitemap_cache. It writes NO posts: `crawl --db
<follow-up>` then fetches the detail API and exports the full record, the
same two-step shape as sync-then-crawl. A 400 refetches the token once and
retries the keyword. A target search finds nothing for is counted in
`not_found` with its keyword, never silently dropped. A shared `_queue_loc`
helper now serves both `sync_catalog` and `recover_missing`.

## 2. Year+genre gap-fill (`gapfill`)

Every year walk hit the feed's 100-page cap (5,000 items), so each year
cell holds more works than the walk returned. A year+genre cell has its
own cap, and genre is a proven server-side filter — so `gapfill_catalog`
harvests each (year, genre) cell with `sort=Latest` (the only sort whose
pages are disjoint works) into the follow-up vault, deduping against the
source vault's keys (`harvest_catalog(known_keys=...)`) so already-staged
works are skipped, not re-staged. The genre vocabulary comes from the
source vault itself (`_genre_tokens`: the `genres` column holds
comma-joined combos with case variants, so tokens are split, counted
case-insensitively, and each keeps its most common spelling; default top
24, years 2019–2026). Resumable: a re-run skips every cell's
already-staged works the same way.

## 3. Resolver transport retry (`host_resolvers.http_request`)

`http_request` returned status 0 on the first TLS reset while the importer
retries 6x for the same edge (which resets ~2 of 3 handshakes). At press
time that surfaced as intermittent "unknown" verdicts on titles whose
streams exist (proven by re-probe: 8/9 series rows active on retry). Now
`http_request(transport_retries=3)` retries transport failures only, with
the importer's backoff shape; an HTTP answer (including 429) returns at
once, exactly as before. The default is 3, not 6 — the press path is
latency-bounded (4 attempts, ~80% first-pass success on a 1/3-per-attempt
edge). `unwrap_moviebox` needs no change: its default fetch IS
`http_request`, so the detail + play + probe chain inherits the retry.

## Tests (solo, CI way, all green)

- `test_themoviebox_search.py` (new, **19 OK**) — token shape + pinned
  md5, x-user parsing, Bearer-alone header discipline, 400 semantics,
  slug-stem keywords, exact-title hit picking, recover end-to-end offline
  (3 targets: 2 queued, 1 not-found with its keyword), 400-refetch, no
  token = nothing queued.
- `test_themoviebox_gapfill.py` (new, **9 OK**) — genre token splitting /
  case folding / limit, known-keys dedup (0 posts, 1 duplicate), one cell
  writes only what the source lacks, sort=Latest in the filter body,
  no-vocabulary = no cells, `_parse_years`, CLI defaults.
- `test_host_resolvers.py` (**222 OK**, was 218; +4 retry tests) —
  transport failure retried then succeeds, all retries exhausted still
  status 0 after exactly TRANSPORT_RETRIES+1 calls, HTTP 429 never
  retried, explicit `transport_retries=0` means one attempt.
- `test_themoviebox_import.py` 54 OK, `test_themoviebox_detail_api.py`
  18 OK, `test_themoviebox_links.py` 7 OK (unchanged).
- `test_docs_invariants.py` OK (after the registration below).

## Gate registration

- `backend-ci.yml`: two new 🧪 steps after `test_themoviebox_import.py`
  (`test_themoviebox_search.py`, `test_themoviebox_gapfill.py`), and a
  third for the resolver retry: `test_host_resolvers.py` was sitting in
  UNREGISTERED (pre-existing debt) and is now in the gate, removed from
  UNREGISTERED. 🧪 count 69 → **72**.
- New modules go straight into the gate; nothing added to UNREGISTERED.
- Checkpoint + README pointer + CONTINUITY count 130 → **131**.

## Live runs (VM, after this commit is pushed)

- `recover` then `crawl --db <follow-up>` then `stats --db <follow-up>`:
  queues the 168 + 43 targets, fetches their detail APIs, exports the
  records into `themoviebox_followup.db`. Run detached; verify counts
  against the 168 + 43 targets before reporting.
- `gapfill` (years 2019–2026 × top-24 genres, detached): harvests the
  capped cells into the same follow-up vault. Verify per-cell posts and
  the follow-up totals before reporting.
- Data merge of `themoviebox_followup.db` into the live catalog is a
  separate parent gate job (fresh backup first) — NOT done here.

## Deliberately not in this change

- No merge to main (parent reviews + merges). No data merge (parent gate).
- No `/platform/play-list` probe, no 123moviesfree.club harvest, no
  detail-rec BFS — all still open follow-ups from the Session 126 map.
- No change to the resolver's other fetch paths (`_cookie_jar_fetch`,
  `_unverified_fetch`): the task named `http_request`, and the MovieBox
  chain goes through it.
- The follow-up vault is deliberately separate from `themoviebox.db`:
  the source vault is already merged to live, and the merge gate must
  see exactly the new rows.
