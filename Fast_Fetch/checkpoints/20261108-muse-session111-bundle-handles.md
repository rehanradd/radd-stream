# Session 111 — v2 bundle handles name ledger rows — 2026-11-08

Branch `session111-bundle-handles` from `dc7b6080` (Session 110).
Author rehanradd. Builder does not push, deploy, or touch the live DB or
live tree — the parent pushes and gates. All verification ran against
fixture DBs, never the live catalog.

## 1. THE LIVE PROBLEM — VERIFIED BY THE PARENT 21:2x PKT 2026-11-08

POST /api/v2/play `{"work_id": 54221}` answered 200 with release 624764
(Arthur's Whisky), playable True, 5 candidates — but pressing the bundle's
OWN `stream_id` tokens at /api/v1/stream (no-follow) 404'd on all 5.
Decoding a bundle token gave 1915585, a `cat_links` id; no
`download_sources` row 1915585 exists, so the stream route found nothing.
The copies were fine: the same release's ledger rows 903161/903164/903165/
903168/903171 (all 1xplayer) pressed 302/302/302/404/302 when minted
directly. `cat_links` rows 1915585/88/89/92/95 map to them via
`cat_links.ledger_link_id` (903161 etc.).

Consequence: **no v2-bundle stream handle has ever played in the app.**
The earlier minted-handle press proofs (302s) bypassed the bundle and
stay valid as resolver proofs only. The 21:13 user message ("Arthur's
Whisky now plays") was WRONG — routing works (200, right film/print) but
playback via the bundle still fails; the correction to the user is the
parent's, with the live proofs owed after the gate deploy (see §5).

Why the old tests never caught it: in every projected fixture the two id
spaces coincide — `cat_links` ids are assigned in projection order from 1
while ledger ids were assigned in ingest order from 1, so `cat id ==
ledger id` for every row and minting either one presses the same row.
Production diverges on every rebuild (cat ids restart from 1, ledger ids
keep growing). The new suite breaks the coincidence the same way
(cat ids +500 after projecting: cat 501 names ledger 1).

## 2. THE FIX — DONE

Code (`catalog_api.py`, `api_v2.py`; resolver, adult scope, quality gate,
route_play fallback logic all untouched):

- `catalog_api._link_view` mints `stream_id` from the row's
  `ledger_link_id`, never from `link["id"]`. The no-secret fallback mints
  the raw ledger id the same way. A row with NULL `ledger_link_id` carries
  `stream_id: None` and `playable: False` — no handle to nothing, and it
  cannot win a play tier or travel as a backup (`tiers.playable()` reads
  the view's `playable` flag). The row stays in the bundle (zero data
  loss: still listed, still counted); only its handle is honest. Shape
  identical for every row that has a ledger id (a fresh projection has
  zero NULLs — `test_project_readonly` asserts 0 orphans).
- `api_v2.py` /resolve JSON: the same mismatch lived there — it echoed its
  cat-id `link_ref` under the name `stream_id`. New `_ledger_stream_handle`
  mints the ledger handle (None when there is no ledger id); `link_ref`
  stays the cat handle for re-entering /resolve. Fail closed on a missing
  row or an unreadable column: no handle, never a guess.

Mint-site audit (every `redact.mint_token` call site; verified by grep):
correct and unchanged — `viewer.link_view` (ledger row), `viewer`
download descriptor / stream-route JSON / download-route filename
(parsed ledger id), `viewer` M3U playlist (ledger rows), `api_v2`
`feed_playlist` + `link_ref_for`/`link_ref_parse` (cat ids, consumed by
the cat-native /resolve route — NOT stream handles, deliberately
untouched), `redact` art handles (post ids, /api/v1/art's own universe).
Fixed — the two above. Note: /resolve stays cat-only on purpose; making
it also accept ledger ids would resolve a NEW bundle handle to whatever
unrelated cat row happens to hold that number (wrong film).

Edge noted, not changed (out of scope — route_play fallback logic is
Sessions 109/110's): bundle-level `playable` is group-based, so a print
whose ONLY copies lack ledger ids still reports `playable: True` while
every candidate's `stream_id` is None and every tier is download-only.
Only a stale pre-`ledger_link_id` projection can produce that shape;
live is rev-4 with the column populated.

## 3. TESTS — 6 NEW, NEGATIVE CONTROL RUN

New module `Fast_Fetch/test_bundle_handles.py`, registered in
`backend-ci.yml` (🧪 step after `test_catalog_api.py`; 🧪 count 55 → 56,
gate modules 51 → 52). Fixture: one 720p print ("Loopback Film", 720p so
the quality gate never interferes), two copies, cat ids +500, a loopback
media server (video/mp4 + Range) so the REAL resolver's Stage-2 probe
passes offline, and a real /api/v1/stream socket server. 6 tests:
(a) `_link_view` handle parses to the row's `ledger_link_id`, not its cat
id; (b) the bundle's OWN handle pressed through the real /api/v1/stream
socket → 302 to the loopback media URL (no mock); (c) NULL-ledger row:
`stream_id` None, `playable` False, tier winner is the linked copy, no
backup handle names the unlinked row; (d) directly minted ledger handle
still 302s (no regression — passes on old code too); (e) /resolve JSON:
`link_ref` parses to the cat id, `stream_id` to the ledger id, they
differ; NULL-ledger row carries `stream_id` None there too;
(f) /feed.m3u handles stay cat-native (regression guard against
over-fixing the feed).
`test_api_v2.py`: 3 assertions strengthened (not weakened) — the two
resolve answers and the bundle-handle round-trip now assert the handle
parses to the row's `ledger_link_id` as well as to its cat id. They pass
before and after in that fixture (ids coincide there); the distinguishing
proof is the new module. No pinned count changed; test_api_v2 stays 58
tests, test_catalog_api 133, test_tiers 38.

Negative control (only `catalog_api.py` + `api_v2.py` stashed, tests +
fixture kept): 4/6 fail without the fix — (a) handle parses to 501 not 1,
(b) bundle handle 404s (`not_found`, the exact live shape), (c) NULL row
still carries a handle, (e) resolve `stream_id` parses to 501 not 1 —
while (d) and (f) pass on the old code, as they should. Stash popped
cleanly afterwards; the fix is what makes the tests pass, not the
fixtures. (The new module run before the fix also reproduced the bug
verbatim: bundle handles parsed to 501/502, press 404.)

## 4. GATE — VERIFIED

Full backend gate (`~/workspace/run-backend-gate.py`, reads the module list
from `backend-ci.yml`): 52/52 modules PASS, FAILED MODULES: 0, exit 0.
Baseline (unmodified tree, same runner): 50/51 PASS — the single failure
was `test_docs_invariants`, caused solely by the then-unregistered new
module (its message names `test_bundle_handles.py`); everything else was
already green, so this session's gate is a clean 52/52, not a fix-up.
The 4 importer modules the gate script's regex misses, all solo OK:
`test_dub_collision_census` 13, `test_themoviebox_links` 7,
`test_themoviebox_detail_api` 18, `test_themoviebox_import` 53.
`test_docs_invariants` solo OK (22 tests: registration + the 111 count).
`test_bundle_handles` 6 OK, `test_api_v2` 58 OK, `test_catalog_api`
133 OK, `test_tiers` 38 OK.

## 5. LIVE PROOFS OWED (PARENT, AFTER THE GATE DEPLOY — NOT ATTEMPTED HERE)

- work_id 54221 bundle's OWN handles press 302 (the fix's live proof).
- Ali Baba release 1252022 plays via a sibling print (Session 110's
  owed proof — needs the bundle handles to work first).
- Minted presses 302/302/402/302 unchanged (uploadflix, 1xplayer,
  Chalk Line 1080p 402, Mentalist 720p 302).
- Correction to the user: the 21:13 "Arthur's Whisky now plays" message
  was wrong — routing worked, playback did not. Only the live 302 on a
  bundle handle closes this.

## 6. COLLISION NOTE — SESSION 112 SHARES THIS CLONE

While this session built, the self-check cron spawned the Session 112
builder (21:27 PKT checkpoint) in the SAME workspace clone, branch
`session112-d25-resolvers` off `dc7b6080`, porting 6 D2.5 unwrappers
(vidbolt, vibuxer, vidrift, iqsmart, filmu, cineverse) + tests from
`eb199eb` with `RESOLVER_VERSION` 1 → 2. Its uncommitted work
(`Fast_Fetch/importers/host_resolvers.py` + `test_host_resolvers.py`,
later `fast_fetch.py` + `test_database.py`) was in the working tree
throughout this session's gate runs; it touches no file this session
touches except `backend-ci.yml`, which Session 112 may also register a
step in — the parent should expect a possible conflict there at merge
time. Zero file overlap between the two commits (this session's 8 files
vs Session 112's 4). The sibling committed first, `22f3d28d` ("Session
112: land D2.5 host resolvers ... + play-path dispatch"); this session's
commit is on `session111-bundle-handles` with explicit paths only, and
HEAD was returned to `session112-d25-resolvers` afterwards so the sibling
lands on its own branch. On disk the tree now reads as Session 112's
commit — this session's files show their `dc7b6080` versions until
`session111-bundle-handles` is checked out; the commit `0fd989b1` holds
the work.
