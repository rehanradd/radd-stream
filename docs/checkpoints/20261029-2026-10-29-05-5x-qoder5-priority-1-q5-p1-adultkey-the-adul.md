# 2026-10-29 05:5x — qoder5 (PRIORITY 1 `[Q5-P1-ADULTKEY]`): the adult flag moved from the row to the work

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 05:5x — qoder5 (PRIORITY 1 `[Q5-P1-ADULTKEY]`): the adult flag moved from the row to the work

**qoder5 delivered `[Q5-P1-ADULTKEY]` — the adult law moved from the row to the work.** `fast_fetch.
inherit_key_adult()` reconciles `MAX(is_18_plus)` across every row sharing a `canonical_key`, inside the
`BEGIN IMMEDIATE` of the write that set it, bounded by `idx_posts_canonical_key`, and refuses the
degenerate `unknown` key. New ledger rows are filed under `generate_canonical_key(clean_title, year)`
(`ledger_canonical_key`) instead of the importer's page slug; **stored rows keep the key they were filed
under**, so the 55,876-row re-key migration is still not attempted. `Fast_Fetch/backfill_adult_key.py` is
the reviewed repair (report → `--apply` → `--apply --projection`) and **will not commit unless the public
total dropped by exactly the rows it flipped**. Tests: `test_database.py` 76 → 88, `test_redact.py` 49 → 58;
10 of the 12 identity/tool tests and 3 of the 9 denial tests fail on the untouched base `e96bf84`.
Two code defects surfaced while settling the doc contradiction, both now fixed: `fetch_database_payload`
filtered adults in *operator* mode too, which made the dashboard's `🔞 18+ ADULT` badge permanently dead,
and `/api/v1/stream` + `/api/v1/download` skipped the adult check when `full` was set — **the operator port
would play a flagged link** — while the public port answered `Source restricted (18+ content)`, telling a
caller the row existed and why it was hidden. Both redirectors are now unconditional and answer a uniform
`not_found` on both ports; the panel may list a flagged row and its flag because `/api/data` is 404 on the
public port of this process, `^~ /api/` 403 at nginx, and loopback-only at the socket. No public route could
be found that reaches a flagged row, so step 5 was wording plus those two, not a P0.
**Residual, measured read-only through covering-index/PK paths (checked `EXPLAIN QUERY PLAN` first, 2–3 s,
nice 19, nothing written):** **953 works** are flagged in `cat_works` while **1,190 distinct unflagged ledger
rows** for the same title and year are public under a *different* key — `suzume-2022` vs `suzume_2022`,
`puli-2015` vs `puli_2015`, `kaliyugam-2064` vs `kaliyugam_2064`, and `puli__2015`/`kaliyugam_2025__2064`
where the title's year and the `year` column disagree. By site: filmyzilla 437, 9xmovies 344, moviezguru
190, hindilinks4u 151, 7starhd 36, then a tail. Only 2 of the 1,190 are season-fold artifacts
(`naruto-shippuden_s01` vs `_s02`) and those must stay unreconciled. That figure is a **floor**: the
projection stamp still says `posts=130,016` against a 150,799-row ledger, so batch 3–4 rows are not folded
into any work and cannot show up in the measure.
**Handoff — the owner runs these, not an agent.** Against the fresh snapshot, in this order:
`python3 -S Fast_Fetch/backfill_adult_key.py /home/ubuntu/radd-stream-backups/prebatch4_20261029_051444.db`
(read-only report: expect ~455 exposed rows and the public total before/after), then the same command with
`--apply --projection`, then the merge into prod. `EXPOSED_KEYS_SQL` is the one grouped pass over `posts`
that no agent re-spends. **`radd-stream` was not restarted** — until the owner activates, live
`/api/v1/posts?q=4+Play` still serves id 23519. **Code green on `main`; activation and the 455-row
backfill both pending the owner.** `AGENTS.md` and `Fast_Fetch/AGENTS.md` now state the invariant as
enforced, rebased onto `ac638ca` so upstream's own measurement survives: the operator port's boundary is
**loopback**, not `RADD_ADMIN_TOKEN` (`/` answers 200 on 8081 with no token; the token guards `/admin`
alone) — my earlier "token-gated" phrasing was removed from both guides instead of repeated.

