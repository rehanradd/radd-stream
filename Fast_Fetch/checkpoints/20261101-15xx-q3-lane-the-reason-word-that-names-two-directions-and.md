# 2026-11-01 15:2x — q3 backend lane `[Q3-REASON-LAW]` `[Q3-43/88/91]`

Dispatch (supervisor, this session): *"resolve `engagement.py:1141` self-check vs `refund`
`SPEND_REASONS:1116` contradiction **with a test**, and finish adult-flag **43/88/91**
reconciliation **read-only**, own worktree only, push and report sha. Gate held, no trunk push,
no production read."* Followed by: ruling (2) stands (no step-4 plan/trigger cost), and stop
after these two commits — `reason-law-test` + `checkpoint-counts`.

Branch `q3-reason-law-on-c2528e1`, base `c2528e1` (q1's standing item 5). Two commits.

## 1. The named contradiction is not a contradiction, and the test says which axis the law lives on

`_selfcheck()` prints `no-client-coin` (`engagement.py:1177`, asserted at `:1139-1145`) while
`refund` and `redeem_pass` sit in **both** `LEDGER_REASONS` (`:110-112`) and `SPEND_REASONS`
(`:116`). Read as money rules that looks like one word minting coins in two directions. Read
against its own comment at `:113-115` it is one append-only mechanism: a wrong credit is clawed
back by a compensating **debit** labelled `refund`, and a coin returned after a failed spend is a
**positive** `grant_coins` with the same label. The direction is the function; the word only says
*why*. Nothing in the ledger stores a direction — `delta` is the whole of it.

So the resolution is not a code edit, it is a gate. **A `print` inside `python3 -S
Fast_Fetch/engagement.py` is not a gate — no CI step runs that module's `__main__`.** The law the
self-check claims is now pinned in `test_coins_engine.py` as `ReasonLaw`, four cases, all
executed:

| property | how it is pinned |
|---|---|
| the overlap is declared, the asymmetry is the safety | `SPEND_REASONS ⊂ LEDGER_REASONS` (strict), and the complement is exactly `{rewarded_ad, streak_day, admin_grant}`; all three raise `BadReason` on a wallet that **could** pay, while `redeem_pass` does debit (positive control) |
| the word carries no direction | `refund` granted 7 and spent 7 ⇒ rows `[+7, −7]`, same reason twice, `coin_balance` back to 0 |
| no source reaches a debit, and the source law outranks the reason law | `spend_coins(..., source=...)` is a `TypeError` — the parameter does not exist, `source` is the literal `'server'` inside the guarded `INSERT … SELECT` (`:752-757`); and `grant_coins` checks source (`:712`) **before** reason (`:714`), so `BadSource` answers for `refund`, `redeem_pass`, `admin_grant` and a garbage reason alike, with `BadReason` on a legal source as the control that this is not an always-raising path |
| a client cannot name a refund | `POST /coins/earn {"reason":"refund"}` is `invalid_params` and moves nothing (`_EARN_KEYS:128`, `_EARN_DAILY_LOGIN:138`, fallthrough `:825-830`), controlled by the same route genuinely crediting `daily_login`; the two legal refund rows stay distinguishable because `_ledger_entry` publishes `source` beside `reason` — `:486-499` states that reason in prose, `:501-503` writes the field |

**Placement, and why it is not in `test_engagement.py`.** That module is the engine's own owner and
already holds `test_a_correction_is_a_new_compensating_row_not_an_edit` (`:72`) and
`test_a_client_source_is_refused_outright` (`:102`) — the natural home for this law. But
`test_engagement.py` is **not in `backend-ci.yml`** and **is** in `test_docs_invariants.py`'s
`UNREGISTERED` debt frozenset (`:576`), whose ratchet is exact set equality. Registering it means
editing CI and deleting a debt entry in the same commit as the test that benefits from it — three
owners touched where one was enough. `test_coins_engine.py` is registered (`:371-372`), imports
`engagement` directly, and already calls `grant_coins`/`spend_coins` as its fixture's setup path,
so the engine law lands beside the edge that could contradict it. **The debt entry stays open and
this is q1's call, not mine to close silently:** the engine's reason law is now tested by the
wallet-surface module, not by `test_engagement.py`.

Zero lines of `engagement.py` changed. This commit is test-only.

## 2. 43 / 88 / 91 — three identities, one site, and the middle number is the stale one

Run read-only on `/home/ubuntu/radd-stream-data` with `mode=ro` URIs, the converter's own two
calls (`convert_mp4moviez.py:264` `parse_slug` → `:277` `fast_fetch.generate_canonical_key`),
grouping exactly as the emitter at `:370` does (`max(is_18_plus)` per group). `fast_fetch.db` and
`user_state.db` were never named — the script asserts their names out of its own path list.
**1.84 s** single pass over 29,848 pages, `nice -n 19`, load 2.79→3.64.

| number | what it actually counts | measured now |
|---|---|---|
| **91** | flagged legacy **pages** — `SUM(is_18_plus)` over the raw `posts` table | **91** of 29,848 pages ✓ reproduces |
| **43** | flagged **works** at the converter's key identity — groups where `max(is_18_plus)=1` | **43** of 11,404 groups ✓ reproduces, and matches both on-disk vaults exactly |
| **88** | flagged rows *carried* by the 2026-10-29 run, whose `works` denominator was **28,066** | **not reproducible** — no artifact behind it; see below |

The mechanism is the dedup, and it is large: 29,848 pages − 289 that `parse_slug` refuses (a skip,
not a zero — `skipped_pages.none = 289`, `empty_title = 0`, `unknown_key = 0`) = 29,559 pages
folding into **11,404 keys**. The 91 flagged pages − 1 lost to that skip filter = 90 pages inside
**43** keys, and all 43 are multi-page: `house-arrest_2025` alone is **38 pages**, then
`gail-daughtry-and-the-celebrity-sex-pass_2026` (6), `bdsm_2023` (6),
`fifty-shades-of-grey_2015` (4), `porn-i-love-you_2025` (4). **72** of those 90 members carry no
url-bearing release row at all, so only ~18 flagged pages ever become a playable row — the flagged
*work* count was always going to be far below the flagged *page* count.

One pointer correction while the method is still fresh: the handoff text at
`20261101-06xx-…:98-99` cites `convert_mp4moviez.py:268` for `parse_slug`; on `c2528e1` that call
is at `:264` (`:268` is a `skipped_listing` counter). The two calls are the same functions the
brief named — the line pointer had drifted, not the method.

The two staging vaults are the same computation at the same identity, which is how I can say 43 is
not a discrepancy but the answer: `mp4moviez_staging2.db` = **11,404 posts / 43 flagged / 54,267
releases / 0 null keys / 0 keys carrying both flags**, and my independent re-derivation from the
legacy file is **11,404 groups / 43 flagged / 54,267 release rows** — every one of the three
figures equal. `mp4moviez_staging.db` = 11,403 / 43 / 54,263: one work and four releases short, a
slightly earlier converter build (mtime 05:25 vs 07:49, both before the two converter commits).

**What retires the 88.** The 2026-10-29 log line
(`checkpoints/20261029-…mp4moviez-becomes-mergeable-and-a-fleet.md:48-52`) records
`29,848 → 28,066 works, 54,267 releases, 344 duplicate pages merged, 16,168 rows skipped for
having no release, 9 takedown notices dropped, 88 adult rows carried` — and it ran on a **copy**
(`/tmp/mp4moviez_copy.db`) into a **throwaway target**, both long gone. 28,066 works from 29,848
pages means that run merged only 344 pages: it was counting at near-page identity, not at the
canonical key. Its `54,267` releases match the legacy file exactly, so it is the same source data
— the *grouping law* is what differs. So **88 was a flagged-page-adjacent figure under a 28,066
denominator that the converter no longer produces**, and the −16,663-post delta that
`20261101-01xx-…:59` recorded against the vault is not 16,663 lost works: it is 18,155 duplicate
pages folded at the correct media identity, with the release and source totals preserved intact
(54,267 = 54,267).

**One live stale claim I am reporting rather than editing.** `Fast_Fetch/SITES.md:83` still says
mp4moviez was *verified* at `28,066 works`. Under the converter that is on trunk today the number
is 11,404. That is a doc-truth defect with a measured replacement, in the same family as the
7-way contradiction report the supervisor ruled "recorded, not resolved now" — so it goes to q1
with the number to use, and I have not touched `SITES.md`.

**What this does NOT claim.** It does not say the adult law is complete: the 0-both-flags result
holds *within this one site's vault*, and the cross-site residual in CONTINUITY item 5 (2,600 keys
carrying both a flagged and an unflagged row, 3,486 publicly served rows) is untouched and is a
merged-catalog problem, not a staging one. It does not re-open the reassignment (q1 moved this to
q2; I ran the method because the supervisor dispatched it back to me as "finish … read-only"), and
it inherits the honesty note at `20261101-06xx-…:106-108`: the earlier dispatch had already
completed, so nothing here was ever a clean un-run handoff.

## Blocks and bounds

- **Gate held.** No trunk push, no merge, no tag, no restart, no production read, no crawl, no
  Gradle. Nothing of mine was ever run against `fast_fetch.db` or `user_state.db`.
- **Ruling (2) untouched**: no `EXPLAIN QUERY PLAN` and no trigger-cost measurement — step 4 stays
  queued as task #36 until the supervisor announces the lift.
- **Ruling (1) honoured on the route branch**: no new route; the plot disjunct rides the already
  allow-listed `/api/v1/search/by-media`.
- CI verdict is the hosted run's; locally I ran **only** `test_coins_engine.py ReasonLaw` (4 tests,
  1.47 s, `nice -n 19`). The rest of that module and every other module were not run: load reached
  8.54 with `cpu some avg10=96.53` earlier in the hour and is back to 6.37 as I write.
- `test_docs_invariants.py` was not run either; the archive count in `CONTINUITY.md` item 1 was
  re-derived from `ls Fast_Fetch/checkpoints/*.md` minus `README.md` (this file makes it 69:
  67 dated + 2 undated) and the bump is byte- and line-neutral.
