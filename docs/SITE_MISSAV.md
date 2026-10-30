# missav.live — recon note, measured 2026-10-30

> **Status: BLOCKED AT THE EDGE. No page shape was captured, so no HTML parser was
> written.** This note records what an unauthenticated client actually received, the
> requests that produced it, and precisely what this lane refused to do to get past it.
> The staging schema, the unconditional adult flag, the content-code key, the tier/mirror
> model and the crawl gate are implemented and tested; the one function that turns HTML
> into a record is deliberately absent, because writing it today would be fiction.

---

## 1. What was requested, and what came back

Two requests, `curl -sS -m 15`, honest bot User-Agent
(`radd-stream-catalog-bot/1.0 (+https://github.com/rehanradd/radd-stream)`), host printed
before each. Budget was six; two were spent and reconnaissance stopped on the evidence.

| # | URL | host | http | bytes | content-type | time |
|---|-----|------|------|-------|--------------|------|
| 1 | `https://missav.live/robots.txt` | `missav.live` | **403** | 5,485 | `text/html; charset=UTF-8` | 0.63 s |
| 2 | `https://missav.live/` | `missav.live` | **403** | 5,434 | `text/html; charset=UTF-8` | 0.49 s |

Both bodies are the same Cloudflare interstitial:

```html
<title>Just a moment...</title>
...
<p>Enable JavaScript and cookies to continue</p>
```

Markers present in both: `cloudflare`, `just a moment`, `cf-` assets. This is the managed
JS challenge, not a 404, not a geo-block page with an explanation, and not a rate limit
(no `429`, no `Retry-After`). It fires for **every path on the vhost**, including
`/robots.txt`.

Captured bodies: `/tmp/q5_missav/33b78d79.out` and `/tmp/q5_missav/f15eeb5c.out`.
They are never copied into the repo; they contain no site content, only the challenge.

## 2. Why `/robots.txt` being challenged matters more than the 403 on `/`

A well-behaved automated client asks `robots.txt` first. When that file is itself behind a
challenge, the site publishes **no crawl policy to an unauthenticated automated client** —
so the only honest reading is "do not crawl me automatically", not "no rules, therefore
anything". This lane takes that reading. It is also the reason the crawl is not merely
*queued for a quiet window* like fzmovies was: even at load 0.1 the gate would open and the
site would still refuse, so the blocker is the site, not the box.

## 3. What this lane refused to do

Each of these would have produced a page — and each is a way around the site's access
control, which the task's rule 4 forbids in spirit and in letter:

- **Solve the JS challenge** (headless browser, JS engine, challenge solver). That is the
  control, not an obstacle to it.
- **Spoof a browser User-Agent or Client-Hints** to get a different response for the same
  request. Same request, different answer, chosen because it defeats bot detection.
- **Replay a `cf_clearance` cookie** or any clearance token minted for another client.
- **Proxy / IP rotation / Tor** to find an egress the challenge does not greet.
- **Read the same pages through an archive or cache** to obtain the content the live
  site declined to serve to an automated client. It is public, but the purpose would be
  to route around the refusal, so it is out of scope here too.
- **Guess an API hostname** (`api.` / `www.` / JSON endpoints) and probe it. Unmeasured
  endpoints are not reconnaissance, they are speculation, and a 6-request budget should
  not be spent on guesses.

No credentials, cookies or tokens were sent anywhere. No DB was opened or written.

## 4. Consequence: what is and is not established

Established:

- The site answers an unauthenticated automated client with a Cloudflare JS challenge on
  all paths, including `robots.txt`.
- The challenge page is ~5.4 KB of HTML and costs ~0.5 s to be refused.
- Therefore there is **no** captured homepage, rail list, item page, tier markup, poster
  markup, subtitle-tag vocabulary or download-anchor shape for this site. Not one.

Not established, and deliberately not guessed:

- Rail/listing URLs and pagination.
- Where the per-title fields live, and in which format (JSON-LD? microdata? DOM?).
- How quality tiers are declared, and whether the site even declares tiers it cannot serve.
- The download-link shape and whether it needs a token/referer (rule 4's stop condition).
- The subtitle-tag vocabulary (`English subtitles`, `CJK subbed`, `no-sub`, …) — the
  owner named these as expected categories, not as measured strings.
- The content-code format. `ABC-123` in the task is the owner's example; the importer
  validates a *class* of codes, not a measured vocabulary (see `CODE_RE`).

## 5. The per-item request cost

**Unmeasurable today.** The only measurable figure is the cost of a refusal: one GET,
~5.4 KB, ~0.5 s, and no way to advance from it. Once a page is capturable the expected cost
is **1 request per item** — this importer stores links and never follows them (no tier, no
mirror, no download URL is fetched at ingest), so a bounded run of N items is N page
requests plus listing requests, and zero stream/download requests.

## 6. What would unblock the parser half — without automating the challenge

A human operating a normal browser (not this lane, not an automation) opens one item page
and saves it verbatim:

```
/tmp/q5_missav/item.html      # the item page, complete, no devtools editing
/tmp/q5_missav/listing.html   # one rail/listing page, if the site shows one
```

Then `extract_record(html)` in `import_missav.py` can be written against real bytes, and
`parse_item` gains a fixture the tests can hold. A saved page from a human's browser is
not an evasion — it is the site serving a human exactly what it promised to serve, and the
owner has directed the ingestion. That single step turns this from "blocked" to "ready to
crawl behind the standard gate". If a network lane with a different egress genuinely
receives the page (q2 is the only lane allowed to hit the network hard tonight), the same
two files from it are equally usable — but that lane must determine for itself whether it
is being challenged, and must not solve the challenge either.

## 7. What is implemented here anyway, and why it is worth having before the capture

`Fast_Fetch/importers/import_missav.py` implements the parts that do **not** depend on the
site's HTML, so the compliance-critical half is proven before any byte is fetched:

1. **Unconditional adult flag at the schema level.** `posts.is_18_plus` is
   `INTEGER NOT NULL DEFAULT 1 CHECK (is_18_plus = 1)`. A missav row cannot be written
   unflagged even by hand-written SQL; the test suite proves a direct
   `INSERT … is_18_plus=0` raises `sqlite3.IntegrityError`, and that an item whose title
   carries no adult wording still lands flagged.
2. **Content code → `canonical_key`, with a source prefix.** `STARS-123` → `missav-stars-123`.
   The prefix is deliberate: the adult law is per row while identity is per key, and
   `docs/ADULT_TWIN_PROBE.md` measured 442 keys that already hold both a flagged and an
   unflagged row. A missav row must never share a key with a clean row from another site,
   so its keys are namespaced by construction.
3. **Tier/mirror model.** Every declared tier becomes a `releases` row; a tier with no URL
   gets **no** `sources` row (nothing invented); a dead mirror is stored with
   `status='dead'` and kept.
4. **Subtitle tags preserved** as their own column *and* inside the tag list, because the
   owner asked for subtitle-language tags specifically.
5. **The crawl gate**, in code: load ≥ 4.0, MemAvailable ≤ 4000 MB, another importer
   running, or a missing/zero `--limit` all refuse, and `sync` refuses a second time for
   the measured site reason (§1) with a distinct exit code so the two causes stay
   distinguishable in logs.
6. **Staging only.** Default DB `/home/ubuntu/radd-stream-data/missav.db`; the module never
   names `fast_fetch.db` or any merged catalog, and the test suite asserts that.

## 8. Compliance posture, restated because it is the point

- Every row from this source is 18+ **by source**, and the schema enforces it.
- The importer adds no public surface: no route, no token, no list, no search. It writes a
  staging DB and nothing reads it. The existing enforcement (`redact.adult_clause` in
  `api_v1_get_posts`, the per-post bail, `redact.link_is_adult` on the redirectors with
  unknown-id ⇒ True, and nginx's allow-list) is untouched by this change.
- **Nothing here is merged.** Merge is Q4's, after the key-level reconciliation
  (task #13). An all-adult source merged before that would widen the measured twin hole.

## 9. What was delivered, and the gate it sits behind

- `Fast_Fetch/importers/test_import_missav.py` — **42 tests, all green**. The task's
  required cases are each an explicit test: every declared tier becomes a release; a tier
  with no URL gets no source row; a dead mirror is kept with `status='dead'`; subtitle
  tags survive verbatim; the content code becomes `canonical_key`; and an unlabelled title
  still lands flagged while a direct `is_18_plus=0` insert is rejected by the schema.
- **Registered** in `.github/workflows/backend-ci.yml` as step 28
  (`grep -c 'name: 🧪' .github/workflows/backend-ci.yml`). It is not excluded: that file's
  exclusion is about suites that open **on-disk captured fixtures**, and this one creates
  its own temp SQLite database and holds every fixture inline. The bullet was narrowed to
  say so, because "import" in a filename was never the reason.
- **Measured here: 42 tests in 9.670 s**, on a single core at load 8.86 with 1.7 GB
  available. The suite opens no socket, starts no subprocess and waits on no lock; that
  wall clock is contention. `test_admin_panel.py` is the calibration point (266 s here,
  1 s hosted). CI's timing is the record, not this box's.
- One earlier local run looked hung at test 40 for over four minutes. `faulthandler`
  showed it blocked inside `importlib` reading a stdlib source file — I/O starvation on a
  loaded box, not a test that waits. Recorded here because "the suite hangs" is the kind
  of claim that gets inherited by the next lane.
