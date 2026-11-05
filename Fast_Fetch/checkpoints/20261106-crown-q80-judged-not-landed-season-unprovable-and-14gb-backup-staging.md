# 2026-11-06 · crown supervisor lane — order #80 judged and NOT landed; the ledger provably cannot express a season; the nightly backup is staging 14 GB of catalog into `/tmp`

Base for the judgement: `ba5f4207ca9a9f945d60c229e6f8bef8ae0b2061`. Trunk when written: `eab125d`.
Filing judged: `/tmp/crown_orders/Q14_RESULT_80_MERGE_SEASON_KEYS.md`. Verdict:
`/tmp/crown_orders/CROWN_VERIFY_80.md`. Order issued from it: `CROWN_ORDER_81_Q14_SEASON_LAW_PIN.md`.
Nothing was committed, pushed, tagged, deployed, restarted or deleted by this judgement; two scratch trees
(`/tmp/crown_o80_ctrl` at `ba5f420`, `/tmp/crown_o80_fix` with the lane's diff applied) and read-only catalog
access only.

## What the lane proved, and I re-measured

The season qualifier is erased at `fast_fetch.py:616` (`return derived`), **not** in `merge_catalogs` — the
order named the wrong file and the lane corrected the attribution. `merge_catalogs.py:139/:344/:380` only
carry the producer's string through as a *fallback*, and `ledger_canonical_key` reaches `supplied` only when
`derived` is empty or `unknown`. `supplied` at the live call site `:5087` is the staging vault's own
`canonical_key`, so a patch there is effective at the boundary rather than inert.

Mechanism, proved from the tokeniser rather than asserted: `generate_canonical_key:594` deletes
`season\s*\d+|s\d+` as distribution boilerplate, `:599` maps every non-alphanumeric run to `-`, and `:601`
appends `f"{t}_{year}"`. The only underscore a derived key can contain is therefore the year separator, so
**no derived key can ever end in `_sN`** — the ledger's key function is structurally incapable of expressing a
season. Confirmed by execution: `gen('MobLand Season 1', 2025) == gen('MobLand', 2025) == 'mobland_2025'`.

Red-before-green held: the lane's class run against pristine gave `Ran 8 — FAILED (failures=4)`, patched
`Ran 8 — OK`, whole module `Ran 48 in 16.0s — OK` including the seven-day-old trunk red at
`test_import_katmoviehd.py:996`. The idempotence pin is not vacuous — 2 of its 5 inputs change answer
pre-fix — which is what makes "0 stored rows touched" a property rather than a promise. The test diff is
append-only (81 insertions, 0 deletions), so no assertion was weakened.

## Why it was not landed, and why not for the lane's reason

The lane recommended against landing on its §7 adult cost. Re-priced on the axis the adult law actually uses
— `inherit_key_adult` propagates over `canonical_key`, so the question is whether the **year-form** key other
sites write still names the row — the katmoviehd vault gives: 2,490 season-form staging rows, 2,487 keys
moved, **332** rows whose pre-fix key is shared with another site, of which **20 WIDEN / 18 NARROW**, net
**+2**. That is not a hole; it is bidirectional and small.

The deciding cost is one the filing measured around without naming. All 2,487 adopted keys have shape
`stem_sN` — **the year is dropped in 100 % of them**, zero `stem_YEAR_sN` — so identity moves from
(title, year) to (title, season) for one producer's rows only. **207** of the resulting key strings exist
nowhere in the ledger today; distinct identities produced by that single site go **2,284 → 2,487**. And
because such a key is un-derivable by construction, each row it writes joins the "derived ≠ stored" drift set
permanently — 2,489 for katmoviehd, up to 9,494 across the ten vaults that carry season keys — added to the
69,773-of-150,799 the fleet already quotes as its headline identity failure. `key_census.py` refuses
`--apply` out loud (`:25/:40/:103`), so nothing will undo it and nothing will ever converge it. A key-scheme
change wearing a 34-line helper, under the "no new key scheme" fence that this order wrote for itself: the
fence was mine and it held only because the lane read it as a contradiction and filed it instead of silently
picking a side.

## Second surface, found by crown, unreported by the lane

`guard_canonical_key` computes its *replacement* key through the same function (`fast_fetch.py:818`), so the
patch changes not only verdicts but what the refusal path writes:

    cand='mars_2021' clean_title='Dune' year=2026 fallback='dune_s1'
      pre-fix -> 'dune_2026'    post-fix -> 'dune_s1'

Zero writes so far — the guard is trunk `45115bb`, the live tree is `bf9e565` and runs none of it, and
`key_refusal_journal` is absent from the catalog (`sqlite_master` → 0) — but any future commit message must
state it. The lane's §6 claim ("0 verdict flips") was verified and is if anything understated: `mobland_2025`
also corroborates a row whose year is 2019, so the year-blindness belongs to `canonical_key_corroborates` and
predates this patch.

## The nightly backup, measured while it ran

`python3 /opt/radd-stream/Fast_Fetch/backup_manager.py --dir /home/ubuntu/radd-stream-data --hf` (pid
375589, `nice 19`, started ≈03:35) staged into `/tmp/tmpj0uwpr7v`: `fast_fetch.db` **dereferenced** to
6,171,131,904 B plus `merged_catalog_20261025.db` copied again (3.2 GB at 04:06, growing to 6.4), 11 GB at
04:06, ~14 GB at completion. Free space during it: 66 G → 58 G → 56 G. One line causes it —
`dbs = sorted(data_dir.glob("*.db"))`, live `:526`, and **trunk `eab125d:645` carries the same line
unfixed**, so deploying does not remove the double copy. What trunk does add, and what the live `Oct 25 20:36`
copy entirely lacks: `free_bytes :138` / `required_bytes :146` / `_check_space :149-155` refusing to start,
`staging_root() :124-135` honouring `RADD_BACKUP_STAGING`, and `prune_local_archives :186` called at `:703`
only after an upload is verified. `/home/ubuntu/radd-stream-backups` is 45 GB across 41 entries and cannot
shrink on the host that has no prune function. Nothing was killed, demoted or deleted: the job was `nice 19`,
free space was never critical, and a half-deleted archive is worse than a large one.

## Fleet consequences

NOTICE 79's bulk-I/O halt stayed in force through this judgement — my own catalog work was one 120 MB
single-site vault read plus indexed point lookups on `idx_posts_canonical`, `mode=ro` +
`PRAGMA query_only=ON`, `ionice -c3 nice -n19`; that is the sampling §4 permits, not a covering scan.
Numbers retired by this entry: the filing's "2 files / 115 insertions" → **3 files / 116**; "2 of 6 red" →
**4 of 8 red**; "`Ran 46 tests`" → **`Ran 48`**; "1 mixed group ⇒ ≈26 adult hole" → **20/18/net +2**.
Owner decisions outstanding: **#5** season-as-a-column (the key-string route is closed), **#6** the backup
deploy + staging path + which archives may be pruned, plus the older deploy choice, the adult `--apply`
authorisation, and the AGENTS.md backlog.
