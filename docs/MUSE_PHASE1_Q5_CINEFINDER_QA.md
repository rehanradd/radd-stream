# MUSE PHASE 1 (q5) — Cine-Finder QA: the guard design, the FTS5 measurement, and three contradictions

**My assignment** (`/tmp/q1_muse_cinefinder_spec.txt`, ownership table, qoder5 row): QA for both halves —
the guard that fails the build if any request path can carry clip/frame/screenshot bytes, the FTS5
capability test, and a written verdict on match quality. This file is the **Phase 1** deliverable: the
design and the measurements that Phase 3 must be built against. **No feature code was written** — the
spec gates code on a green Phase 1, and the corpus the feature needs does not exist yet (§4).

Method, same as the money-and-keys audit: read at branch
`q5-agents-count-method-20261101` (contains trunk `636eda5`); one offline temp-file SQLite experiment;
**no production read, no crawl, no route probe with a sample size > 1.** Ads are parked repo-wide and
nothing here un-parks them.

---

## 1. Three contradictions — you decide, I am not choosing

The spec says: *"If either doc contradicts this file, the doc wins and you tell me the contradiction
instead of choosing."* Here they are, with the line each is read at.

**C-1 — the route already exists.** The file assigns q3 "the one HTTP route that answers derived text
only", as if it were new. `/api/v1/search/by-media` is **live code on trunk**: the matcher is
`media_search.search_by_media` (`Fast_Fetch/media_search.py:312`), the endpoint is
`viewer.api_v1_search_by_media` (`Fast_Fetch/viewer.py:2990`, dispatched at `:3922`), it has its own test
module (`Fast_Fetch/test_media_search.py`, 30+ cases), and it is already swept from the public edge
(`Fast_Fetch/sweep_public_edge.py:272-289`). It is also already in nginx's allow-list
(`AGENTS.md`, Key Links table). So q3's Phase-3 task is a **modification of a shipped, tested,
publicly-swept route**, not a new one — which changes the guard obligations (§3), the review surface, and
what "no duplicate work" means here. **Recommendation:** have q3 state which it is before design.

**C-2 — the two source-of-record docs disagree with each other about what is searched.**
`docs/FULL_MASTER_FEATURE_INVENTORY.md` M-SRCH-03 (`:588-600`) describes **Track A = OCR text →
`GET /api/v1/posts?q=` (or `/api/v2/search` when projected)** and Track B = a Google Lens intent, with
**no FTS5 anywhere in the build**. `docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` — whose own title line
names its author, `meta-llama/llama-3.3-70b-instruct` — describes a `catalog USING fts5(title, duration,
aspect_ratio, audio_stream_metadata)` table behind that same `/api/v1/search/by-media` (`:19-55`), i.e. a
**file-metadata** search, not a dialogue search. The Muse file's "dialogue text goes to SQLite FTS5
plot/subtitle search" matches neither of them exactly. And the architecture doc's snippet is not
shippable as written: it opens `sqlite3.connect('catalog.db')` (a relative literal path, against
AGENTS.md rule 5), shares a module-level `cursor` across requests, indexes three columns that do not
exist in `posts`, and carries **no adult clause and no `redact.project`** — the two things that make any
public list lawful in this repo. **Treat that file as a generated draft, not as an architecture**; I put
that plainly because "the doc wins" would otherwise hand q3 a spec that violates the flag law.

**C-3 — the query the user flow promises cannot be answered from the ledger.** The Muse line is "Search
is by clip frames, screenshot, plot text, actor name and genre in one request." Measured against the real
schema (`fast_fetch.py:948-967`, `posts` columns: `url, slug, title, clean_title, year, content_type,
seasons, poster_url, backdrop_urls, imdb_rating, genres, synopsis, is_18_plus, is_animated, lastmod,
created_at, updated_at`):

| the request promises | the ledger holds | evidence |
|---|---|---|
| genre | **yes** (`genres`) | schema `:960` |
| plot text | **yes** (`synopsis`) | schema `:961` |
| dialogue / subtitle lines | **no text at all** — only a *link* to a subtitle file, as a `sources.playback_type='subtitle'` row; `audit_staging.py:158-162`, `:227-236` count those link rows, and nothing fetches or parses one | the spec anticipated exactly this: *"if the ledger holds no subtitle text today, that is the finding, say so rather than inventing a corpus"* — this is me saying so |
| actor name | **no** — no cast/actor column anywhere in the catalog schema; `backfill_tmdb.py` enriches artwork/rating/genre, not credits (grep for `cast|actor|starring` returns only `sqlite3.Row` and `CAST(...)` lines) | same method |
| clip frames / screenshot | **must never reach us** (hard rule), and there is no visual index on either side | the spec's own rule; I agree with it and it is not a gap to fill |

So a truthful Phase-3 request shape is **derived text only: ≤10 normalised OCR words + optional title +
optional genre**, and "actor name" is either dropped from the user flow or preceded by a credits
ingestion feature that nobody has scoped. Building the search first and discovering the corpus is missing
later is the expensive order.

---

## 2. The FTS5 capability test — measured, and the spec's prescribed instrument is wrong

The spec says to prove FTS5 with `python3 -c "import sqlite3;print(sqlite3.dbinfo())"` **and** a
`CREATE VIRTUAL TABLE`. Run once here, offline, against a temp file, under `nice -n 19`:

```
python 3.12.3  |  sqlite3.sqlite_version = 3.45.1
AttributeError: module 'sqlite3' has no attribute 'dbinfo'      ← the prescribed command FAILS
```

`sqlite3.dbinfo()` was added in **Python 3.14**; on this box's 3.12.3 it raises, so anyone following the
spec literally will conclude "FTS5 is unavailable" from an `AttributeError` about a *function*, not about
a capability. The working instruments are `sqlite3.sqlite_version` and the `CREATE` itself:

```
CREATE VIRTUAL TABLE t USING fts5(body, title)                    → ok
MATCH 'door'                                                      → [('Suzume 2022', -9.69e-07)]
MATCH 'heist OR chennai'                                          → [('Puli 2015',)]
ORDER BY bm25(t)                                                  → ranked, ok
aux tables written: t_data, t_idx, t_content, t_docsize, t_config  → ok
```

**Verdict: FTS5 is available and usable on this box** (library 3.45.1, `bm25()` present, `OR`/prefix
queries present). Two conditions attach to that verdict, and both belong in the Phase-3 design, not in a
chat message:

1. **It is a property of the interpreter, not of the repo.** The box runs one `python3`; the hosted CI
   runner and any future migration target run their own `libsqlite3`. So the capability must be probed by
   a **test that creates the virtual table in a tempdir** (which is what I did) and the code must fall
   back to the existing escaped-`LIKE` path when it raises `sqlite3.OperationalError`. Stdlib only, so
   there is no way to vendor a newer SQLite.
2. **Never assert on `dbinfo()`** — write the `CREATE` probe, and if a version floor is needed compare
   `tuple(int(x) for x in sqlite3.sqlite_version.split("."))` against a stated tuple.

**Written, run, and registered:** `Fast_Fetch/test_fts5_capability.py` (5 tests — version instrument,
`CREATE VIRTUAL TABLE` + shadow tables, a discriminating `MATCH` with `bm25()` ordering plus a
must-be-empty negative and a quoted-phrase case, the `tok*` prefix behaviour OCR depends on, and a
no-writes-outside-tempdir insurance), registered as `🧪 test_fts5_capability.py` in
`.github/workflows/backend-ci.yml` — required, because `WorkflowSuiteCoverageTests` fails any on-disk
module that is neither in the gate nor in its declared unregistered list. Ran green locally, once, at
`nice -n 19`. It **skips with a named reason** on an interpreter without FTS5 rather than reddening the
gate, because a capability the repo does not control must not be asserted as one it does.

Two things the module deliberately does *not* claim: it cannot report the runner's SQLite **number** to a
lane without a token (job logs are 401 anonymously; only step conclusions are readable), so it asserts a
**floor** instead — `assertGreaterEqual(sqlite3.sqlite_version, (3, 37))` — which means a green step *is*
the proof, and the specific version stays in the log where the owner can read it. And it does not test the
fallback path, because the fallback does not exist until q3 writes it; that is a Phase-3 test, listed as
unfinished rather than invented here.

---

## 3. The bytes guard — the design, with its positive control

The rule to enforce: **no request path in either half of this feature can carry clip bytes, frame bytes
or a screenshot.** A compliance boundary, as the spec says, so it must be a build failure and not a code
review habit. Following the repo's paired-guard convention (`App/app/src/test/kotlin/com/raddstream/app/
tooling/DeadCodeGuardTest.kt`, `StatsHonestyTest.kt`) — which is: walk the source tree, regex for the
forbidden shape, and **ship a test that proves the regex separates a hit from a miss**
(`DeadCodeGuardTest.kt:97`, `the reachability rule itself separates a live name from an orphan`). A scan
that matches nothing is green by accident; that is the failure mode the spec names.

**G1 — Android half (q4 owns the code, this is the guard it must ship).**
`NoClipBytesGuardTest.kt`, a `mainDir` walk like `DeadCodeGuardTest.kt:26-31`, failing the build on:
- any `RequestBody.create` / `.toRequestBody(` / `MultipartBody` whose media type matches
  `image/*`, `video/*` or `application/octet-stream`;
- any `@Body` parameter typed `ByteArray`, `Bitmap`, `File`, `InputStream`, or `RequestBody`;
- `MediaMetadataRetriever` / `ImageReader` / ML Kit `InputImage` results flowing into anything from the
  networking layer — the practical version is: **the package that owns the frames
  (`ClipAnalyzer`/`FrameExtractor`) may not import the package that owns the HTTP client**, asserted by
  an import-scan, which is cheap and unambiguous;
- `AndroidManifest.xml`: a `SEND`/share `intent-filter` may declare `video/*`, `image/*` **incoming**,
  which is fine and required — the guard must therefore be about *outbound* call shapes, not MIME
  strings in general. Getting this distinction wrong is how a guard ends up deleting the feature.
- **Positive control (mandatory):** the same test injects two fake sources into a temp dir — one
  `fun upload(frame: ByteArray)` and one compliant `fun search(text: String)` — and asserts the first is
  caught and the second is not. Without it the guard proves nothing, per the spec's own rule.

**G2 — Backend half (q3's route, my guard).** A pytest-style module in `Fast_Fetch/` (registered in
`.github/workflows/backend-ci.yml`, because `WorkflowSuiteCoverageTests` fails an unregistered module —
the trap I hit and documented): assert on the *dispatch* layer of `viewer.py` that the by-media route
(a) rejects a request with a body (it is a `GET`/query-param route; a body of any length must not be
read), (b) rejects `Content-Type: image/*|video/*|application/octet-stream` with the same uniform
refusal it uses for a client-supplied price, and (c) that **no handler on the public allow-list parses
multipart** — grep the dispatch table, don't trust the docs table. Positive control: a fixture that
plants a `read(length)` on that route must be caught.

> **Written, registered, and it changed the finding — 2026-11-01 06:3x (q5).**
> `Fast_Fetch/test_clip_bytes_guard.py`, 8 tests, step `🧪 test_clip_bytes_guard.py`. What the source said
> when I read it instead of predicting it: there are exactly **three** body reads in the modules that
> mount HTTP — `viewer.py:3529` and `viewer.py:4170` (both operator-port form paths, both clamped with
> `max(0, min(length, api_v2.MAX_BODY_BYTES))`) and `api_v2.py:1629` inside `read_body`, which rejects at
> `:1627` *before* reading, so an oversized body costs zero socket bytes — the difference between a cap
> and a ceiling you paid to find. My (a)/(b)/(c) framing was wrong in its shape: the public by-media route
> never reads a body at all, so there is nothing there to refuse; the refusal is `read_body`'s JSON shape
> check, which rejects `image/jpeg`, `multipart/form-data` and a raw clip POST alike.
>
> **The finding, and it is the reason this section was rewritten: the 64 KiB ceiling is NOT the compliance
> boundary.** `MAX_BODY_BYTES = 64 * 1024` (`api_v2.py:117`), and a 320x180 JPEG keyframe base64s to
> roughly 8–20 KB — it fits, it is valid JSON, and `read_body` hands it back as a dict. The clip rule is
> therefore enforced by a **field allow-list in the route that does not exist yet** (q3 owns it), not by
> anything in this file. That is pinned by a test which *passes today* on purpose
> (`test_a_small_base64_frame_inside_a_json_object_is_parsed_today`), so nobody can mark G2 satisfied by
> citing the cap; if a real allow-list later flips it to a refusal, the test tells you and the message
> tells you to update this doc.
>
> Scope decision, recorded because a guard's exclusions are where it lies: the by-name scan covers
> `viewer.py`, `api_v2.py`, `media_search.py`, `admin_panel.py`, `accounts_api.py` — not all of
> `Fast_Fetch/*.py`. A repo-wide scan hits `importers/import_filmiyin.py:659`, `elif "screenshot" in src`,
> which names a *link* off its URL and carries no request field. Flagging it would have bought a blanket
> exclusion; the honest alternative was to narrow the scanned set and say why.
>
> Cost honesty: written under the LIGHT-ONLY freeze, so **the hosted step is this module's first
> execution** — no local run, and every claim above is a read off the source at the sha.


**G3 — the law the spec forgot: the new corpus must carry the adult clause.** Today's route already
does: `media_search.py:168` builds `WHERE {redact.adult_clause('p')}` and `:388` projects rows through
`redact.project(r, "post_brief")`. An FTS5 virtual table does **not** inherit either: if Phase 3 populates
`catalog_fts` with synopsis text and queries it by `MATCH`, a flagged work is publicly listable through
the FTS index even while its `posts` row is correctly hidden — and because the flag law is per
`canonical_key` (`fast_fetch.inherit_key_adult`, AGENTS.md), the FTS table has to carry or join that key.
So the QA suite must include: **every text the FTS index can return is reachable by that text only if the
same query against `posts` would return it** — a differential test, seeded with a flagged row and its
unflagged twin. I would write this one first, before the index exists, as the spec suggests for the
backup-scope rule; a test that the current code cannot pass yet is the cheapest form of design review.

**G4 — pin the tag length and the handle property.** `redact.py` mints entitlement passes with an 8-byte
tag and row-id handles with a 4-byte tag (`:860`, `:904`); nothing stops a future `[:4]` landing on a
capability. One assertion per minter, and the KD-3 case from
[`MUSE_PHASE1_Q5_MONEY_AND_KEYS.md`](MUSE_PHASE1_Q5_MONEY_AND_KEYS.md) — a public response must not carry
a bare integer where a handle belongs (`api_v2.py:1141` and friends fall back to `str(id)` when the
signing secret is unset, which is a config accident away from shipping enumerable ids).

---

## 4. Match-quality verdict — the instrument, since the verdict cannot exist yet

A verdict on match quality needs something to measure. There is no FTS corpus and no OCR path today, so
writing "the quality is X" now would be the exact defect class I spent this week retiring in the docs.
What I can do in Phase 1 is fix the **acceptance instrument** so Phase 3 is judged and not argued:

- **Case set (12 known-title cases, fixture DB in a tempdir, no production rows):** 4 exact titles,
  4 plot-phrase queries drawn from the shipped `synopsis` text, 2 dialogue-shaped queries (≤10 words,
  deliberately *not* in any synopsis — these are the cases the corpus gap in §1-C3 will fail, and they
  should fail loudly rather than silently return the nearest title), 1 romanised-English query for a
  Urdu-titled work, 1 query naming an actor (must return the honest empty answer, per C-3).
- **Metrics, pre-declared:** `recall@1` and `recall@10` per case class; `p95 server latency` for the
  query (and the *cost basis stated first*, because this box is one core and `CAPACITY_MEASURED.md` is
  where a route's price is recorded before it gets traffic); and a **false-positive budget** — a search
  that answers a plausible wrong title to a dialogue query is worse than one that answers nothing,
  because the feature's promise is "find the movie", and the app surfaces Play on the result.
- **Pass bar:** exact-title recall@1 = 12/12 on the fixture; plot-phrase recall@10 ≥ 4/4; dialogue cases
  reported as *unanswerable by corpus*, not as failures of ranking; zero flagged rows returned; zero
  bytes of media in any request (G1/G2 must be green for the run to count).
- **Ranking rule already written for us:** M-SRCH-03's own `:600` says "exact FTS hit > fuzzy title >
  visual result" — the differential test in G3 is what makes that ordering lawful.

## 5. What I did NOT do, and what is blocked

- Did not write feature code, did not create an FTS table in any real DB (the probe above used a
  `mktemp` file, removed), did not touch `App/`, did not edit any route.
- **Blocked step (naming it, per the brief):** the hosted runner's `libsqlite3` **number**. Job logs are
  401 to an anonymous lane, so a lane without a token can read a step's *conclusion* but not its stdout;
  my module therefore asserts a floor (`>= 3.37`) so that a green step is itself the evidence, and the
  exact figure stays unread by me. Phase 1 also forbids running the full module list locally
  (`cpu some avg10` has been 99-100% all night), so the local verdict is this module plus the one
  neighbour I actually edited — two runs, both at `nice -n 19`.
- **Not blocked but deliberately not done:** choosing between C-1/C-2's competing route designs. That is
  q1's call, and the spec says so.
- Ads: parked. `COINS_PER_REWARDED_AD` (`engagement.py:120`) and the ad-cadence code were read only as
  part of the money audit; no ad behaviour is proposed here.
