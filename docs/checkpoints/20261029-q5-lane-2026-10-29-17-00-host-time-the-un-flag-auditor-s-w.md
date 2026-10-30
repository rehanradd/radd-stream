# q5 lane, 2026-10-29 ~17:00 host time — the un-flag auditor's write contract is closed and the live ledger is measured `[Q5-P1C-PATTERN-FIX-GO]`

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## q5 lane, 2026-10-29 ~17:00 host time — the un-flag auditor's write contract is closed and the live ledger is measured `[Q5-P1C-PATTERN-FIX-GO]`

- **Answers to the two numbers the brief asked for.** Rows whose ONLY match was `unrated|uncut`:
  **4,246** of the 15,068 flagged. Full split of the live `posts` table (one `mode=ro`, `nice -n 19`
  pass, `is_18_plus` is unindexed so it is a full scan): **9,069** carry true-adult evidence in their
  own stored text, **4,246** are version-word-only, **1,753** have no ledger evidence at all (vaults
  resolve those). 14,931 distinct flagged `canonical_key`s; the sibling gate blocks 4 candidates on a
  true-adult sibling and freeing all 4,246 would leave **39 mixed keys**.
- **Why 4,246 and not the owner's 7,663, stated once so nobody re-litigates it:** 7,663 is the
  whole-row measure (genres, synopsis, `raw_meta`, site-wide ingest rules); 4,246 is the measure over
  the four columns the flag is re-derived from (`title`, `clean_title`, `slug`, `url`) — which is what
  `audit_adult_flags.classify` and `save_scraped_data` actually act on. Both are true; only the
  second is actionable from the ledger. Cross-check: a full copy of the catalog
  (`prebatch4_20261029_051444.db`, zero prod I/O) reports 15,020 flagged = live 15,068 − the 48
  genuine flips the owner kept in the 10:48 rollback.
- **Four patterns still hiding mainstream works, reported not touched** (item 1: "do not weaken any
  other pattern"): `\bhunters\b` 128 rows / 127 sole-match (*KPop Demon Hunters*, *Transformers Prime:
  Beast Hunters – Predacons Rising*, *Holy Night: Demon Hunters*), `\brabbit\b` 61/56 (*The Curse of
  the Were-Rabbit*, *1001 Rabbit Tales*, *Rabbit School*), `\bnaughty\b` 169/149, `\badult\b` 1,480/82
  (*Shin-chan: The Adult Empire Strikes Back*). They are genre nouns, not person/studio/act, so they
  fail the rule now in `AGENTS.md`; removing any is an exposure decision for the owner.
- **Item 3 shipped at `8ad9862`:** report mode opens the ledger read-only and so cannot write even if
  the code below it is wrong; `COUNT(*)` only under `--apply`; the preimage is mandatory and
  fail-closed (file fsync + **directory** fsync + re-read and compare the id list, `PreimageRefused`
  → exit 1 with nothing written); post-transaction self-verify `flipped == rows` **and**
  `public_after − public_before == flipped`; then `retest_freed` re-SELECTs every freed row and
  re-classifies its **own** text, rolling back the transaction if any of them is true-adult.
  `--journal` is opt-in and never contains a title. **No `--apply` against prod by this lane, ever.**
- **Item 4 verdict: no test asserted the lie.** `AdultContentFilterTests` (`test_database.py:1376`)
  pins studio evidence only (Tushy / RealityKings slug / Vixen → 1, clean title → 0); a sweep of every
  `test_*.py` found no assertion that a bare `unrated`/`uncut` title is adult. The only surviving
  `Uncut` assertions prove the correct direction (`test_hindilinks4u.py:100` flags "Hotshots (2025)
  18+ Uncut"; `VersionWordIsNotAdultTests` asserts the mainstream titles and an uncut **slug** → 0).
- **Docs corrected at this sha:** `test_database.py` is **124** tests (AGENTS.md said 76, in three
  places), `test_catalog_v2.py` **96** (was 91), **66** `test_*.py` modules (was 60), `fast_fetch.py`
  **6,513** lines (was 6,366); the root guide's adult section now carries the 4,246/9,069/1,753 split,
  the per-pattern census and the four live false positives, and `Fast_Fetch/AGENTS.md`'s stale
  "455 unflagged twins" is replaced by the measured 2,600 keys / 3,486 served rows.
- **Gate + push:** `/tmp/gate_q5.sh` (17 invocations: CI's 15 + `importers/test_host_resolvers.py` +
  `importers/test_convert_mp4moviez.py`) from a clean worktree at **`776020c`** —
  **17/17 PASS, 843 tests, failures=0**. Both refs were racing: `main` at `c4a13027` (my merge of the
  partner-API lane), `master` at `f6637c99` (the validator lane re-committing the same auditor content
  on a different base). Reconciled by merge, fast-forwardable from both tips — never force, never
  amend a published sha — and `776020c` pushed to `refs/heads/master` and `refs/heads/main`.
- **Next in this lane:** item 5 — `safe_link_rollup` in `catalog_v2.py`, then `/api/v2/account/wallet`
  (coin balance, daily streak grant, pass purchase verification), stdlib only, no schema change without
  a migration test, server-authoritative balance. **Held for the owner:** projection rebuild,
  `/api/data` bounding, the mass un-flag, merge batch 4 / kuttymovies / DesiSerials into prod.

