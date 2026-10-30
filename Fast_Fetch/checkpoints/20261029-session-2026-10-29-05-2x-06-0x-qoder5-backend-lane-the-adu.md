# Session 2026-10-29 (05:2x–06:0x, qoder5 backend lane) — the adult flag moved from the row to the work `[Q5-P1-ADULTKEY]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (05:2x–06:0x, qoder5 backend lane) — the adult flag moved from the row to the work `[Q5-P1-ADULTKEY]`

MASTER's PRIORITY 1 order: a live 18+ display leak, measured read-only on
`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`. The finding worth keeping is *where* the
bug was. **No guard was missing.** `redact.adult_clause` filtered every row it was handed, the
per-post bails at `viewer.py:676-682`/`:2677` fired, `redact.link_is_adult` denied the redirectors, and
`/api/m3u` was already 403 at the edge. The public list route served an 18+ work because the row it was
filtering had legitimately never been flagged: 442 `canonical_key` values carried a flagged row *and* an
unflagged one, so 455 works were hidden at one address and public at another. A per-row law over a
per-key identity is the defect, and adding another `WHERE` clause to a public route would have fixed
nothing.

**1. The law reconciled at the key (`fast_fetch.py`).** `inherit_key_adult(conn, canonical_key)` sets
`is_18_plus = 1` for every row sharing the key (`UPDATE posts SET is_18_plus = 1 WHERE canonical_key = ?
AND is_18_plus IS NOT 1`) — one bounded statement, resolved by `idx_posts_canonical_key`, run inside the
`BEGIN IMMEDIATE` of the write that set the flag, so the ingest and the repair cannot disagree. The
degenerate `unknown` key is refused: it is the shared bucket for every titleless payload, so propagating
from it would hide unrelated works across the catalog on the strength of one bad page. Pinned by
`KeyLevelAdultIdentityTests.test_a_flagged_write_reconciles_every_row_sharing_the_key` and
`test_the_unknown_key_never_spreads_a_flag`.

**2. New writes filed under the work, not the slug.** `ledger_canonical_key(clean_title, year, supplied)`
now decides the key: `generate_canonical_key(clean_title, year)` when it yields something, the supplied
slug only as the fallback for a payload with no usable title. All 21 importers keep their own fields
untouched — nothing was edited out of a parser, the slug simply stopped being the identity. `clean_title`
was already populated on every row, which is the part that stings: the correct input existed and was not
used. **An existing row keeps the key it was filed under** (the `if existing:` branch overwrites
`canonical_key` with `existing["canonical_key"]`), because writing the derived key there would re-key rows
that `releases` and `post_sources` point at as a side effect of an ingest — that is the 55,876-row
migration MASTER explicitly kept out of this order. Consequence proved: `test_two_sites_writing_one_film_
collapse_into_one_post` shows one `posts` row with both sites in `post_sources`.

**3. The repair tool (`Fast_Fetch/backfill_adult_key.py`, new).** Same shape as `backfill_animated_flag.py`:
report → `--apply` (ledger) → `--apply --projection` (`cat_works` fold + retiring the 8 adult-excluded
stats stamps so `/api/v1/stats` recounts live rather than publishing a pre-flip number). It **refuses to
commit unless the public total dropped by exactly the number of rows it flipped** — `if flipped !=
before - after: rollback`. `BackfillAdultKeyToolTests.test_apply_drops_the_public_total_by_exactly_the_
rows_flipped` proves that arithmetic on a synthetic db. **Never run against prod by an agent:** MASTER owns
that file and the merge queue is inside it; the reviewed invocation is
`python3 -S Fast_Fetch/backfill_adult_key.py /home/ubuntu/radd-stream-backups/prebatch4_20261029_051444.db`
then the same with `--apply --projection`.

**4. The residual, measured — and it is index-bound, not a re-spend.** MASTER's measurement covered the
same-key exposure; the *different-key* residual needed the projection, which is where the title-folded
identity already lives. `SELECT COUNT(DISTINCT p.id) FROM cat_works w JOIN cat_work_sites s ON s.work_id =
w.id JOIN posts p ON p.id = s.post_id WHERE w.is_18_plus = 1 AND COALESCE(p.is_18_plus,0) = 0` — plan:
`SCAN w USING COVERING INDEX idx_cat_works_type`, then `SEARCH s USING INDEX sqlite_autoindex_cat_work_sites_1`
and `SEARCH p USING INTEGER PRIMARY KEY`. Checked that plan *before* running it, read-only URI mode, nice 19,
2–3 s per statement; no scan of the 6.4 GB ledger. **953 works flagged in the projection still have 1,190
distinct unflagged ledger rows served under another key**, and only 2 of the 1,190 are season-fold artifacts
(`naruto-shippuden_s01` vs `_s02` — those must NOT be reconciled, and the key-level law does not touch them
because their keys differ). Shape: `suzume-2022` vs `suzume_2022`, `puli-2015` vs `puli_2015`,
`kaliyugam-2064` vs `kaliyugam_2064`, plus `puli__2015` and `kaliyugam_2025__2064` where the title's year and
the `year` column disagree. By site: filmyzilla 437, 9xmovies 344, moviezguru 190, hindilinks4u 151,
7starhd 36, then a tail. **Caveat that makes this a floor, not a count:** the projection stamp says
`posts=130,016` while the ledger now holds 150,799, so ~20k rows from batches 3–4 are not folded into any
work yet and cannot appear in this measure. The re-key migration stays planned; it is not attempted here.

**5. The doc-vs-code contradiction, settled — and it was wording, not a P0.** I swept for a reachable
flagged row first, because MASTER made that the stop-everything case: `/api/v1/stream` and
`/api/v1/download` both bail through `redact.link_is_adult`, the detail route and `/api/m3u` bail on
`post["is_18_plus"]`, `api_v1_get_posts` and `/api/v1/search/by-media` apply `adult_clause`, and
`resolve_live_source` independently refuses an adult link. **Nothing public reaches a flagged row**, so
step 5 is the half about the panel. Two things were actually wrong in the code: `fetch_database_payload`
filtered adults in *both* modes while its own docstring promised the operator "raw ledger rows" — which
made the dashboard's `🔞 18+ ADULT` badge (`viewer.py:1648`) dead code, a badge that could never fire — and
`/api/v1/stream`/`/api/v1/download` skipped the adult check when `full` was set, i.e. **the operator port
would play a flagged link** and answered `{"success": false, "error": "Source restricted (18+ content)"}`
on the public port, which told a caller that the row existed and why it was hidden. Both fixed: the two
redirector checks are unconditional, the deny is a uniform `not_found` on both ports, and the operator
listing now shows the flagged row and its flag. That is legitimate because of the *network* fact, not a
policy preference: `/api/data` is in `OPERATOR_ONLY_ROUTES` so this process 404s it on the public port,
nginx `^~ /api/` 403s it at the edge, and the operator port binds loopback only. `AGENTS.md` and
`Fast_Fetch/AGENTS.md` now state the invariant in these words; the older "every presentation surface must
filter `is_18_plus=1`" line was wrong about the panel and is gone. Root `AGENTS.md` had already been
rewritten upstream at `ba89084`/`ac638ca` while I worked, so I rebased onto it and kept its measurements
(including the honest one: the operator port's boundary is **loopback**, not `RADD_ADMIN_TOKEN` — `/` answers
200 on 8081 with no token — so I removed my own "token-gated" phrasing from both guides rather than repeat it).

**Tests.** `test_database.py` 76 → **88** (`KeyLevelAdultIdentityTests` ×7, `BackfillAdultKeyToolTests` ×5)
and `test_redact.py` 49 → **58** (`AdultDenialOnBothPortsTests` ×9, two loopback `viewer.make_server`
instances — one public, one `operator=True` — driving real HTTP). Against the untouched base `e96bf84`:
**10 of the 12 identity/tool tests fail** (3 failures + 7 errors) and **3 of the 9 denial tests fail**, the
three being exactly the claims that were false before — the operator-port deny, the panel listing the
flagged row, and `reconcile_key_adult` existing at all. Two fixture facts worth recording so nobody
re-derives them: `vegamovies` and `hdhub4u` entries in the redact fixture share `clean_title="Example Film"`
and therefore **collapse to 2 posts, not 3**, now that the key is derived; and a bare numeric id is refused
with **400** on the public port (unsigned), so the uniform-404 claim is proved with minted handles on both
ports and with the raw id only where it is accepted. One case the new law does not paper over: a key that
already holds two rows makes `_find_existing_post` **raise** `ValueError("… matches multiple records;
refusing an arbitrary merge")` — pre-existing, correct, and now pinned by
`test_a_key_with_two_rows_refuses_an_arbitrary_merge` instead of being quietly changed.

**Gate** (the 15 `backend-ci.yml` modules, one module per invocation, `nice -n 19`, run on the exact tree
that was committed — the earlier pass was stopped because I edited `backfill_adult_key.py` after it started):
| # | module | result | tests |
|---|---|---|---|
| 1 | `test_database` | OK | 88 |
| 2 | `test_vidout` | OK | 6 |
| 3 | `test_catalog_v2` | OK | 91 |
| 4 | `test_release_descriptor` | OK | 24 |
| 5 | `test_link_health` | OK | 57 |
| 6 | `test_link_state` | OK | 28 |
| 7 | `test_evidence_writeback` | OK | 12 |
| 8 | `test_api_v2` | OK | 46 |
| 9 | `test_redact` | OK | 58 |
| 10 | `test_tiers` | OK | 23 |
| 11 | `test_catalog_api` | OK | 127 |
| 12 | `test_provenance_stamping` | OK | 12 |
| 13 | `test_merge_catalogs` | OK | 5 |
| 14 | `test_site_scout` | OK | 25 |
| 15 | `test_backup_manager` | OK | 14 |

616 tests, 15/15 modules, run on `20f5fcc` — the rebased tree, after the last code edit
(`backfill_adult_key.py`: `COUNT(DISTINCT p.id)` for the residual and a required `keys` argument on
`apply_ledger`), so nothing validated a stale file. Log: `/tmp/q5_scratch/gate_adult.log`.

**Hosted proof.** `6978167` pushed to `master` and `main` (fast-forward from `ac638ca`, askpass flow, token
never in a URL or argument): 🐍 Backend CI **`completed / success`** on both —
run **40798264109** (master) and **40798264323** (main). The live edge still answers
`/api/v1/posts?q=4+Play` → `total=1`, id **23519**, and `total=135,779` overall (measured over HTTP at
this moment): the deployed checkout is not this code and the 455 rows are not yet flipped, so the endpoint
is **not** fixed in production yet.

**Boundaries respected.** The production catalog was opened in `?mode=ro` and read through covering-index
and primary-key paths only; no statement of mine wrote it, no `PRAGMA integrity_check`, no full scan, and
the `EXPOSED_KEYS_SQL` grouped pass over `posts` was **not** re-run there — MASTER already spent it. Stdlib
only, no dependency, no parser deleted, nothing under `App/`, no DB in Git. **`radd-stream` was not
restarted** (owner-reserved): the live `/api/v1/posts?q=4+Play` will keep serving id 23519 until MASTER runs
the backfill against `prebatch4_20261029_051444.db` *and* the owner activates the new code. **Code green on
main; live activation pending owner restart, and the 455-row backfill pending owner execution.**

