# q5 lane, 2026-10-30 — the engagement pillars are now admin-controllable, and one shadowed name cost four 500s `[Q5-ENGAGE-KNOBS]`

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## q5 lane, 2026-10-30 — the engagement pillars are now admin-controllable, and one shadowed name cost four 500s `[Q5-ENGAGE-KNOBS]`

Task #22 deliverable **(c)**, on a fresh worktree off the search lane's tip `1d483ee`. `MONETIZATION_FIELDS`
goes 17 → **33 fields** with a new whole-number kind (`_INT = "count"`) and 16 engagement knobs — the three
ad cadences, five coin numbers, four streak numbers, the streak timezone and the three PKR pass prices — and
`remote_config()` publishes an `engagement` block. An operator changes a cadence, a coin cost, a streak grant
or the ladder in `/admin`; no code push. Spec update: `docs/MONETIZATION_PILLARS_SCHEMA.md` §11.

**The design choice that mattered:** the published block is built **over `engagement.remote_view()`** with
the row applied on top, not spelled out again in the settings module — so on an untouched deployment
`remote_config()["engagement"] == engagement.remote_view()` and one assertion covers the shape *and* every
number. `0` means "use the default", never unlimited and never free, resolved through the consumer's own
`resolve_caps`; the two honest exceptions are `streak_day_boundary_hour` 0 (= midnight, a real setting) and
PKR prices (published as stored, because nothing clamps a price, same as `vip.monthly_pkr`). `ceiling =
consumer's ceiling` on save (`_INT_MAX` vs `engagement.CAP_MAX`, `_clamp_hour`'s 0..23) so the card, the body
and the ledger cannot show three numbers for one knob. `pass_monthly_vip_pkr` **250** (plan doc `:46`) stays
separate from `vip_monthly_pkr`: a pass and a membership are two products.

**The defect I found in my own diff.** The settings helper was first named `_count`, which shadowed
`admin_panel._count(conn, table)` — the row counter every projection screen uses. My 65-test file stayed
green; `test_operator_isolation.py` answered **four 500s** with the real cause swallowed by `GENERIC_ERROR`.
Reproduced on a clean `1d483ee` worktree (base OK) to prove it was mine, got the traceback by monkeypatching
`_problem`, renamed to `_setting_count`, green again. Fleet lesson worth keeping: **check for duplicate
top-level names before adding a module-level helper to `admin_panel.py`, and run the whole file, not just
the new tests.**

**Held, on purpose.** `admin_panel.py:1080 vip_monthly_pkr` is still **200** and `payments.py:85
PLAN_DEFAULTS["vip_monthly"]` is still `(200, 30)` even though Q4 ruled ₨250 authoritative — two tests pin
the 200 today, and the reconciliation belongs to the payments/admin lane's files, not to a settings commit.
Three published numbers are display-only until their spend route reads the row (`engagement.py:534` rewarded
cap, `:710` streak grants, `:753` pass coin costs); `ad_grant(caps=…)` already binds the cadences. Lowering one of
those three today shows a phone a price gentler than the charge — the one thing §A forbids — so the safe
operator action is to leave them at their defaults until a route reads the row. No
workflow edited: `test_engagement.py`/`test_admin_panel.py` are still not CI steps, and adding one to the
shared 20-module list is a separate decision. `test_download_endpoint.py` 2/20 failures reproduced
identically on the clean base — pre-existing, another lane's.

**Gate.** Local, offline `-S` stdlib on printed `tempfile` fixtures while the box sat at load 6.1–8.0:
`test_admin_panel.py` 65 OK, `test_engagement.py` 25 OK, `test_payments.py` 85 OK,
`test_operator_isolation.py` 28 OK; the first two re-run on the landing base together, 90 OK.
Hosted Backend CI judged this exact content five times — runs `40945093282`,
`40945927750`, `40946874655`, `40948111468`, `40949404738`, each `completed success` with every `🧪` step
success and none skipped — because the refs moved under each gate and the change was cherry-picked rather than
forced (the list is **21** modules from `c3459b3`: Q4 added `test_adult_twin_probe.py` plus its CI step while I
was gating; `54662d2` after the fifth gate was a capacity doc with no Python);
`master`+`main` were
fast-forwarded only onto a sha that had come back green, by the heredoc askpass. `/opt/radd-stream` untouched, no live `/api/data`, no `full=True`,
no `/api/v1/stats` poll, no Gradle, no heavy run, **no service restart**, no production settings write.

### 2026-10-30 02:26–02:45 — MovieBox: `0 releases / 0 sources` explained and the shape loss fixed `[Q2-MOVIEBOX]`

- **Measured, read-only, two reads total:** one detail page (200, 410 KB, captured at
  `/tmp/moviebox_capture/sample_detail.html`) and one `/wefeed-h5api-bff/detail?subjectId=…` call (200,
  39.8 KB). Both carry `detailUrl`/`sniffUrl`/`sourceUrl` as empty strings, `dl: null`, and
  `resource.seasons[].resolutions[]` = 360/480/720/1080 with per-season episode counts. The only
  mp4 anywhere is the trailer. So the importer *did* fetch and parse (6 rows `scraped=1`, posts
  carry page-derived `raw_meta`) — the site publishes no playable URL to an unauthenticated
  client. **(The vault is not mergeable and must not be counted as a playable site.)**
- **The real defect was shape loss:** declared renditions were kept only as `raw_meta`, so a work
  listing twenty renditions stored as `0 releases`. Now one release per (season, tier) with an
  empty source list, mirrors stored with status (`dead` kept), `metadata_only` counted by sources.
  `test_themoviebox_links.py` (7 tests, 0.02 s, in-memory/devalue fixtures, captured `resource`
  block verbatim) + `test_themoviebox_import.py` 47/47; CI step added (26 test steps).
- **Nothing crawled.** Vault on disk untouched at 44/0/0; the bounded re-crawl command, gate and
  expected cost (≈40 s for 6 pages; expect `sources=0`) are queued in CONTINUITY.md.
