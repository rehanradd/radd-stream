# Session 78 — Option A: operator page for movie requests (2026-11-07 ~02:50 PKT)

User order (02:50 PKT): "Do all one by one a and c first for b once everything
done then tell me. First complete all other works" — A (requests panel page)
first, then C (trunk merge rehearsal + landing), then B (his own device test of
APK 239) last, then tell him. Pricing (weekend 1,200 / monthly 5,000) NOT
answered — not applied. This session is A only.

## Agy's ask, checked against the code before building

Agy: "Add a simple /admin/requests tab in the Operator Web Panel so you can see
title, user handle, date, coin balance. One-click button: [Trigger Crawler] to
search our 18 scrapers for that title."

Checked:
- The panel is `Fast_Fetch/admin_panel.py` (v1, loopback 8081). The v2 panel is
  a separate workspace/gate deploy — porting the page there is a follow-up, NOT
  this build.
- `movie_requests` lives in the user-state DB, same file as the payment queue.
  The payments page pattern (`screen_payments` + `render_payments_page` + JSON
  screen + CSRF-bound one-click closes) is the exact template.
- The schema comment already names the workflow: status is
  ('open' | 'indexed' | 'declined'). No new status invented.
- **"Search our 18 scrapers for that title" does not exist.** No per-title
  multi-site search operation exists anywhere. What exists:
  `POST /admin/action/run-scraper` queues ONE bounded sync/crawl run for ONE
  site (limit clamped 1..1000, default 25), via `_spawn_fleet_run` + the
  `admin_fleet_audit` journal. 18 concurrent runs on a 1-vCPU box would crush
  it, and the busy-check already refuses a second run for the same site.
- Honest trigger: the button queues ONE bounded sync run for the ONE site the
  operator picks (select, default multimovies) and the page says so plainly —
  the run picks the title up only if that site lists it; watch the Fleet page
  for the run. The request stays 'open' until the operator marks it indexed
  (title found/added) or declined (not wanted/duplicate).

## What changed

- `engagement.py`: NEW `list_movie_requests(conn_or_path, *, status, limit,
  oldest_first)` (newest first; open queue oldest-first) and NEW
  `set_request_status(conn_or_path, request_id, status)` — status must be
  'indexed'|'declined', only from 'open'; a re-mark writes nothing and reports
  the status the row already holds; missing row → None; bad status → ValueError.
- `admin_panel.py`:
  - Extracted `_queue_crawler_run(site, mode, limit, crawler, db_path)` +
    `_crawl_limit(raw_limit)` + `_CrawlerBusy` / `_CrawlerSpawnFailed` from
    `_run_scraper_action` (busy-check + audit row + spawn live in one place
    now; the fleet action keeps its validation + responses, same
    `_spawn_fleet_run` patch point, so the existing fleet tests still cover it).
  - NEW `/admin/requests` page + `/admin/api/requests` JSON screen:
    `screen_requests` / `_request_rows` (open queue oldest-first + recent,
    per-account coin balance via `engagement.coin_balance`, account column is
    the same one-way `payments.account_hint` fingerprint + linked profile name,
    titles/notes scrubbed at the edge with `redact.scrub_text` — the ledger
    keeps the original text).
  - THREE new actions, mirroring `_review_payment` (shape → CSRF bound to
    (action, request id) → write): `/admin/action/trigger-request-crawl`
    (request_id + crawler handle + mode sync + limit; queues via
    `_queue_crawler_run`; request stays open; receipt carries the handle only,
    like the fleet receipt — a site name in a JSON body has no needle
    allow-list and would fail the whole answer closed), and
    `/admin/action/mark-request-indexed` /
    `/admin/action/mark-request-declined` (close one row). All registered in
    `_BODY_ACTIONS`; row-bound tokens, so correctly absent from
    `_ORIGIN_WRITES` like the payment reviews. Module docstring WRITES five →
    eight; `route_post` docstring updated the same way. Nav link on `/admin`
    next to Payment queue. HTML answers spend `_fleet_needle_allow()` because
    the trigger picker names the 18 configured sites (loopback-only, like the
    fleet card); the JSON screen names no site (handles only).
- Tests: `test_coins_engine.py` NEW `RequestQueue` class (6 tests: queue
  orders, status filter, unknown status raises, close reports changed,
  second close writes nothing, missing row None + bad status raises).
  `test_admin_panel.py` NEW `Requests` class (13 tests: JSON screen lists the
  open request with balance + hint and names no site; HTML page lists it with
  all three actions + the "does not search" warning; trigger queues one bounded
  sync for the picked site and leaves the request open; busy site refused
  before any spawn; bad handle/token/extra key refused, unknown id 404; closed
  request refused; form POSTs answer with the refreshed page + banner; indexed
  then declined reports already-indexed; wrong token cannot probe for a row;
  remote peer refused; page under OPERATOR_ONLY_PREFIXES). `takes_body` test
  extended to the three new actions.
- No app change. No v2 panel change. No schema change. No price change.

## Local verification (full backend cluster, before push)

- test_coins_engine 73 OK (was 67, +6), test_accounts_api 38 OK,
  test_api_v2 46 OK, test_admin_panel 107 OK (was 94, +13),
  test_engagement 34 OK, test_engagement_ladder 27 OK, test_redact 76 OK,
  test_accounts 64 OK, test_device_trials_and_webhook 83 OK,
  test_docs_invariants OK, test_download_endpoint 23 tests with ONLY the 2
  pre-existing operator-port 401s from Session 73 (same two test names;
  `viewer.py` NOT edited in this build).

## Open after this session

- Option C next: trunk merge rehearsal + landing of
  `muse/app-panel-connection-20261106` into main through the gate.
- Option B last: user's own device test of APK 239, once everything is done.
- V2 panel port of the requests page (follow-up, gate-deployed).
- Pass-ladder prices (weekend 1,200 / monthly 5,000) still unanswered.
