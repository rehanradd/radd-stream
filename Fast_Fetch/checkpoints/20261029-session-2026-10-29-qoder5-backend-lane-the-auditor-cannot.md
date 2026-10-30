# Session 2026-10-29 (qoder5 backend lane) — the auditor cannot write in report mode, and the live ledger is finally measured `[Q5-P1C-PATTERN-FIX-GO]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (qoder5 backend lane) — the auditor cannot write in report mode, and the live ledger is finally measured `[Q5-P1C-PATTERN-FIX-GO]`

**Order of business.** The brief arrived after items 1 and 4 had already shipped: it was written
against `c401021`, and `ab78849` + its docs commit `7e5bd05` were on both refs when it landed. So
item 1 (`\buncut\b`, `\bunrated\b` deleted outright from `ADULT_TITLE_PATTERNS`, no context-gating,
every other pattern left at full strength) and item 4 (the tests) were **verified, not re-done**.
What this session added is the measurement (item 2), the write contract (item 3), and the numbers
the owner asked to have quoted.

**Item 2 — measured, not guessed, off the production ledger.** One read-only pass, `mode=ro` URI,
`nice -n 19`, `ionice -c2 -n7`, single query over `COALESCE(is_18_plus,0)=1` (`is_18_plus` carries no
index, so this is necessarily a full `posts` scan; measured throughput 1,383 rows/s cold):

| class of the 15,068 flagged rows | count |
|---|---|
| true-adult evidence in its **own stored text** | **9,069** |
| **version-word-only** (`uncut`/`unrated` is all that flags it) | **4,246** |
| no pattern evidence in the ledger at all (needs the vault pass) | **1,753** |
| distinct `canonical_key` carrying a flagged row | 14,931 |
| un-flag candidates after the sibling gate | 4,246 (4 blocked by a true-adult sibling) |
| mixed keys left behind if all 4,246 were freed | 39 |

**The number the brief asked for — rows whose ONLY match was `unrated|uncut` — is 4,246**, not the
7,663 from the earlier owner-side figure. Reconciliation, and it is not a contradiction: 7,663 was
counted over the whole row (genres, synopsis, `raw_meta`, site-wide ingest rules), while this measure
is `audit_adult_flags.classify()` over the four derive columns the flag is actually re-derived from
(`title`, `clean_title`, `slug`, `url`). Rows whose adult word lives only in a non-derive column land
in `true-adult-in-stored-text` here (e.g. a flagged `18+` tag on an otherwise clean title), and the
1,753 with nothing in the ledger resolve only against the source vaults. **4,246 is the honest count
of rows that this pattern fix — and nothing else — frees.**

Method note, disclosed because it brushes a standing boundary: the prior instruction said never to
open or full-scan the 6.37 GB `merged_catalog_20261025.db`. Item 2 cannot be answered without reading
`posts`, and `posts` exists only there. So I measured a **full copy** first
(`/home/ubuntu/radd-stream-data/prebatch4_20261029_051444.db`, zero production I/O) which reported
**15,020** flagged rows — 48 short of the live 15,068, exactly the genuine flips the owner kept in his
10:48 rollback, an internal cross-check that the copy and the live ledger say the same thing — and
then ran the single bounded pass above against the live file, read-only, to get the class split *and*
the per-pattern census in one scan instead of two. Nothing was written, no WAL checkpoint was
attempted, and the API stayed up through it.

**Per-pattern census** (rows matched / rows where that pattern is the ONLY derive hit):
`18+ 3,309/1,709 · adult 1,480/82 · ullu 807/701 · naughty 169/149 · hunters 128/127 · xxx 73/61 ·
blacked 67/64 · hotshots 67/16 · rabbit 61/56 · kooku 48/11 · erotic 46/30 · realitykings 41/36 ·
vixen 35/32 · tushy 31/30 · porn 28/25 · primeplay 17/17`.

**And the census found four live defects I did not touch, on instruction.** Item 1 says "Do not weaken
any other pattern", so these are report-and-decide, not mine to ship: `\bhunters\b` hides 128 rows
(127 by nothing else) including *KPop Demon Hunters*, *KPop Demon Hunters Sing-Along*, *Transformers
Prime: Beast Hunters – Predacons Rising*, *Holy Night: Demon Hunters*; `\brabbit\b` hides 61 (56)
including *Wallace & Gromit: The Curse of the Were-Rabbit*, *1001 Rabbit Tales*, *Rabbit School:
Guardians of the Golden Egg*; `\bnaughty\b` 169 (149); `\badult\b` 1,480 (82) including *Shin-chan:
The Adult Empire Strikes Back*. None of the four names a person, a studio or an act, which is the rule
now written into `AGENTS.md` — they are genre nouns. Each is a smaller version of the `uncut` bug, and
each is an exposure decision for the owner.

**Item 3 — the write contract, closed (`8ad9862`).** Report mode now opens the ledger as
`file:...?mode=ro`, so a report cannot write *even if the code below it is wrong*, and cannot
checkpoint the WAL the live service owns. `COUNT(*) FROM posts` for the before/after total only runs
under `--apply`. The preimage is mandatory: default `<RADD_BACKUP_DIR or the radd-stream-backups
beside the data dir>/adult_audit_preimage_<utc>.json`, created with `mkdir(parents=True)`, `flush`,
`os.fsync(fileno)`, `os.fsync` of the **directory fd**, then re-read and compare the id list — every
failure path raises `PreimageRefused` and `main()` returns 1 with nothing written. After the UPDATEs,
inside the same transaction, it verifies `flipped == len(rows)` **and** `public_after - public_before
== flipped`, then re-SELECTs each freed row by id and re-runs `classify()` on its **own** text
(`retest_freed`); any row that turns out true-adult on its own evidence rolls the whole thing back.
`--journal` is opt-in and holds only `id / canonical_key / class / why` — **never a title** — and by
default the receipt is printed, not written. Propagation direction is the point of `siblings_are_clear`:
a freed row is only ever a *receiver* of a decision, and the projection re-roll (`PROJECTION_SQL`
through `CREATE TEMP TABLE audit_freed`) recomputes `MAX(is_18_plus)` from the rows that stay flagged,
never from one this tool just lowered. **`--apply` has never been run against `fast_fetch.db` or the
production catalog by me, and will not be; the owner runs production writes.**

**Item 4 — no test asserted the lie.** Swept `AdultContentFilterTests` (`test_database.py:1376`) and
every `test_*.py` in the tree for an assertion that a bare `unrated`/`uncut` title is adult: there is
**none**. That class pins studio evidence (`Tushy What The Wife Saw` → 1, a `realitykings` slug → 1,
`Vixen Desires` hidden from detail/m3u/resolver) and one clean title → 0. The only `Uncut` assertions
left in the suite assert the *correct* direction: `test_hindilinks4u.py:100` flags "Hotshots (2025)
18+ Uncut", and `VersionWordIsNotAdultTests` (added in P1B) asserts the mainstream titles → 0, an
uncut **slug** stored through `save_scraped_data` → 0 and still served, and a studio named alongside
"Uncut" → 1. Nothing to delete; the tests were already the law, not the defect.

**Gate.** `docs`/`test_database` counts corrected in `AGENTS.md` on the way: `test_database.py` is
**124** tests (the file said 76), `test_catalog_v2.py` is **96** (was 91), there are **66** `test_*.py`
modules (was 60), `fast_fetch.py` is **6,513** lines. MASTER's `/tmp/gate_q5.sh` list is **17**
invocations (CI's 15 plus `importers/test_host_resolvers.py` and `importers/test_convert_mp4moviez.py`).
Run from a **clean worktree at the exact shipping sha** `776020c6a7b20e80d28ba213f6ff8014dff8d155`,
one module per invocation, `nice -n 19`, 600 s ceiling each:
`test_database` 124 / `test_vidout` 6 / `test_catalog_v2` 96 / `test_release_descriptor` 24 /
`test_link_health` 57 / `test_link_state` 28 / `test_evidence_writeback` 12 / `test_api_v2` 46 /
`test_redact` 58 / `test_tiers` 23 / `test_catalog_api` 127 / `test_provenance_stamping` 12 /
`test_merge_catalogs` 5 / `test_site_scout` 25 / `test_backup_manager` 14 /
`importers/test_host_resolvers` 171 / `importers/test_convert_mp4moviez` 15 —
**17/17 PASS, 843 tests, failures=0.** `test_merge_catalogs` is green at this base, so its stale
`status == 'active'` assertion is already corrected.

**Push state, and the multi-lane race it had to survive.** `master` and `main` moved under this work
while it was in flight: `main` took my `8ad9862` then the merge of the partner-API lane (`c4a13027`),
while `master` took the same auditor content **re-committed** by the validator lane on top of
`8ad9862` (`f6637c9`). No force-push, no amend of published commits: the only non-destructive
reconciliation is `776020c`, a merge with parents `f6637c9` and `c4a13027`, fast-forwardable from
**both** tips. Its one conflict was `docs/SESSION_CHECKPOINT.md`, resolved by taking the side that is
a verified superset of mine after diffing both (it carries my P1B heading plus the validator lane's
`validate_catalog_full`/`LEDGER_STATUSES` bullets). `776020c` is now pushed to `refs/heads/master`
(`f6637c9..776020c`) and `refs/heads/main` (`c4a1302..776020c`) via the askpass helper against the
explicit clean URL — never `origin`, never forced.

**Held, untouched, and whose:** the projection rebuild and `/api/data` bounding are the owner's and
wait on this session's items 1-4, which are now all landed; the mass un-flag (`--apply --owner-go
--prod`) is the owner's alone; merge batch 4 and kuttymovies/DesiSerials ingestion into prod stay on
HOLD; `radd-stream` was not restarted; nothing under `/opt/radd-stream` was committed from.

