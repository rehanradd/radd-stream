# 2026-11-01 ~06:xx — q3 lane, Muse Phase 1: `remote_config` stops lying when the settings row cannot be read, and the double-spend argument becomes a thread test

Lane: **qoder3** (backend). Working head: `6014dd5` (trunk `main` == `master`), branch
**`q3-muse-phase1-20261101`**, worktree `/tmp/q3_muse`. Dispatch: `/tmp/q1_muse_phase1_q3.txt` — "coins
review open questions + admin remote_config backend, finish 21/26, push branch, CI green" — continuing from
`/tmp/muse_qoder3_fix.txt`. Ads parked; nothing here is ad work.

## Status

| | |
|---|---|
| Code changed | `Fast_Fetch/admin_panel.py` (`remote_config`), tests added to `Fast_Fetch/test_admin_panel.py` and `Fast_Fetch/test_coins_engine.py` |
| Tests **run** | **none** — the PSI freeze was in force at every moment I edited (see the instrument below). `py_compile` on all three files: OK. The hosted run on my sha is the judge. |
| Pushed | yes, to my own branch only. Nothing landed to trunk; that is q1's gate. |
| Merge | still frozen. Tonight's `backup-hf` does **not** satisfy my pre-merge snapshot — see §merge. |

## The defect I fixed, and why "defaults" was the wrong answer

`remote_config()` is the body every phone fetches at `/api/v1/app/remote-config`. When it could not read
the settings row it published **the shipped defaults with no marker**:

```
try:
    _ensure_monetization(conn)
    values = _read_monetization(conn)
except sqlite3.Error:
    values = None
if values is None:
    values = {key: default for …}      # ← and the body said nothing about it
```

`maintenance_mode` defaults to `0`, so a locked table or a half-migrated deployment answers every device
"maintenance is off, downloads on, cast on, a day pass costs ₨200" — while the operator's stored row says
otherwise and the ledger charges the stored price. On that field `false` is not the safe value; it is the
value that keeps playing. The module already had the right words for this state — `SETTINGS_UNAVAILABLE`
(`admin_panel.py:1604`), used by the operator card at `:1943` and the panel's empty state at `:3109` — and
the public projection simply did not say them. `_read_monetization`'s own comment (`:1845-1850`) records that
a swallowed error "be[came] answered with the *defaults*" and calls that the bug; the fix there was to make
the read positional, and the swallow itself stayed.

**Fix, additive and flat, because the body's contract is flat** (`:2251-2257` — `VipRemoteConfig.kt` decodes
top-level keys and caches for 60 s):

- `settings_unavailable: true|false`, a real boolean, same rule as every other flag in the body.
- `true` when the read raised **or** the row `_ensure_monetization` only just inserted is not there — one
  answer, because a client can only be told one thing.
- The defaults stay in the body. A degraded answer that drops keys would break the decode of the client that
  is worst off, and the whole point is that a phone must be able to read a bad moment without crashing.
- The rule the app half (q4) implements: **when `settings_unavailable` is true, keep the last cached config;
  do not act on these values.** That is the contract q4's Phase 1 "cache last good, fallback if server fails"
  work needs from the backend, and until this key existed there was nothing to key on.

Tests (`test_admin_panel.py`, class `Monetization`): the degraded case asserts the marker, that a degraded
body carries **exactly the healthy body's key set**, and that it prints `maintenance_mode: false` /
`vip_monthly_pkr: 200` — so the marker is load-bearing and not decoration. The missing-row case asserts the
same marker through `return_value=None`. The positive control asserts `assertIs(body["settings_unavailable"],
False)` on a healthy read with a stored `maintenance_mode: 1` published, which is what stops an
always-true flag from passing as a guard.

## The coins review's one honest gap, closed with threads

Answer (a) of the review (`checkpoints/20261101-…-the-coins-wire-and-the-plain-http-wallet.md`, "Three answers
with file:line") said the double-spend argument rests on the shape of `spend_coins` plus SQLite's single-writer
rule, and that the named test "is single-threaded — it proves the *accounting* invariant across repeated
calls, not two statements racing". `Redeem.test_two_redeems_never_buy_more_pass_than_the_wallet_paid_for`
cannot show the race because `redeem_pass` derives its default idempotency key from the second
(`engagement.py:988`), so two claims in one second collapse to `already_applied` **before the balance is
consulted**.

New `Concurrency.test_two_threads_redeem_a_wallet_that_covers_exactly_one_tier`: grant exactly one tier's
cost, start two threads that clear a barrier and each call `engagement.redeem_pass` on **its own connection**
with **its own idempotency key** — the only configuration in which the balance guard is the thing under test.
It asserts `sorted(outcomes) == [("insufficient", None), ("spent", False)]` (the `False` proves the winner
really spent rather than collapsed a replay), one `redeem_pass` ledger row, and
`wallet_state() == (2, 0, 0.0)` — so a refusal that wrote a row on its way out cannot pass by answering
`insufficient`. Each thread opens its own handle for the same reason the ten-thread spend test gives: sharing
one connection would test the driver's lock, not the guard.

## Open questions that are not mine to close, named in one line each

1. **Rewarded-ad S2S** — does a rewarded-ad route get the ad network's server-verified completion callback, or
   does `engagement.SERVER_SOURCES` (`:107`, `server`/`admin` only) stand and `POST /coins/earn` keep refusing
   `rewarded_ad`? Owner's decision; the code refuses today and that refusal is a measurement, not caution.
2. **`_commit` swallows `sqlite3.Error`** (`engagement.py:274-278`): if a commit ever fails after
   `spend_coins` inserted, `redeem_pass` mints from the returned figure while the debit rolls back — a free
   pass. Unreachable under SQLite's normal behaviour rather than safe; the fix is re-raising, one line, and
   it is the owner's file.
3. **Client-minted keys at `accounts_api.py:698`** (task #30) — memo written
   (`checkpoints/20261101-00xx-q3-lane-the-phone-derived-sync-key-decision-memo.md`), patch not written,
   because it is a provisioning policy and not a bug. It is cheapest to take **now**: q1's bounded
   read-only counts at 05:25 measure `user_accounts = 0` and `key_hash` non-null `= 0`, so switching to
   server-mint-only costs zero existing viewers. That number also closes the review's load-gated question
   ("are any existing account rows keyed by a derivable value?") — nothing exists to be keyed, so the
   exposure is prospective, not current.
4. **The 43 / 88 / 91 adult-flag spread — reassigned to q2 by q1, and I stopped.** The method is what was
   asked for, so it goes to q2's brief verbatim: group **all** legacy pages by
   `generate_canonical_key(parse_slug(source_url, year)["raw_title"].strip(), parsed_year)` — i.e. the
   converter's own two calls, `convert_mp4moviez.py:268` and `:277`, never the `clean_title` column — and
   count groups where `max(is_18_plus) = 1`, which is the exact expression `:370` uses; report that number
   (flagged *works*), the legacy `sum(is_18_plus)` (flagged *pages*), and the flagged groups that carry no
   release row at all, because those are the pages whose flag the skip filter deletes and the only way the
   third number can differ from the first two. `SELECT id, source_url, year, is_18_plus FROM posts` plus
   `SELECT post_id, url FROM releases` are the whole read set, and `parse_slug` returning `None` or a key of
   `unknown` is a skip, not a zero.
   **Recorded so the handoff is honest:** the command had already been dispatched and had completed when the
   reassignment arrived, so this is not a clean un-run handoff — the *method* is being transferred, not a
   result, and nothing here builds on its numbers. What I had measured earlier, under Muse's explicit
   read-only reconciliation instruction, is two files and it does change q2's starting point:
   `mp4moviez_staging.db` = 11,403 posts / 43 flagged / 54,263 releases / 54,263 sources / 0 null keys, and
   `mp4moviez_staging2.db` (34,181,120 B, mtime 2026-10-29 **07:49:17**, between the two converter commits) =
   **11,404 posts / 43 flagged / 0 null keys**. So **neither vault on disk is the 28,066 / 88 measured run** —
   the 88 has no artifact behind it in `/home/ubuntu/radd-stream-data`, which is precisely why Step 5.5 must
   assert
   against the converter's own printed accounting and not against a file that happens to sit at a path.

## Phase 3 prep — the FTS5 proof the spec demanded, and one finding that changes the design

Read `/tmp/q1_muse_cinefinder_spec.txt`; ownership as dispatched (q4 client, q3 backend, q5 QA). No Phase 3
code written — the spec gates it behind my Phase 1 gate. The capability proof, measured on this box:

- **The spec's own command is wrong**: `python3 -c "import sqlite3;print(sqlite3.dbinfo())"` raises
  `AttributeError: module 'sqlite3' has no attribute 'dbinfo'` — that function is not in the Python stdlib at
  any version, so a lane following the spec literally would conclude FTS5 is absent. The correct probe is
  `SELECT name FROM pragma_module_list` (plus an actual `CREATE VIRTUAL TABLE`).
- `sqlite3.sqlite_version` **3.45.1**; `pragma_module_list` carries **`fts5` and `fts5vocab`** (also fts3/fts4).
- On a temp **file** db: `CREATE VIRTUAL TABLE probe USING fts5(body, title)` + two inserts +
  `WHERE probe MATCH 'bicycle OR rome' ORDER BY bm25(probe)` → `[('Bicycle Thieves', -2.23e-06)]`, and
  `snippet(probe,0,'[',']','...',8)` → `a [ship] sinks at night`. FTS5 is compiled in and works; external-content
  tables need the `content=` form, not the `'external'` keyword (my first attempt raised `SQL logic error`).
- **The corpus finding, stated rather than invented:** the ledger holds **no subtitle or dialogue text**. The
  only subtitle signal in the tree is `audit_staging.py:100 / :158-162 / :207-208`, which counts
  `sources.playback_type = 'subtitle'` rows — i.e. pointers to subtitle *files*, not searchable words. A
  grep for subtitle|dialogue|transcript|caption across `fast_fetch.py`, `merge_catalogs.py`, `api_v2.py` schema
  returns **0**. So the FTS5 table can be populated today from `posts.synopsis` / plot text only, and the
  spec's "dialogue text goes to SQLite FTS5 plot/subtitle search" has no dialogue side until either the
  importer captures subtitle text or the client's on-device OCR supplies it per request. That is a design
  input for the route contract, not a reason to invent a corpus — and it is the finding the spec explicitly
  asked to be told.

## merge / backup — what tonight's run does and does not give me

The five-site merge stays **frozen** (owner rule, and the box is not idle). The 03:47 `radd-backup-hf` run is
**not** my Step 5.5 snapshot: `backup_manager.py:95` uses `VACUUM INTO`, which is a different mechanism from
the `.backup`-from-a-`-readonly`-connection my plan requires (my Step 2 folds dirty WAL frames into the copy
by construction and re-checks source mtime+size before and after; that is the guard qoder1's C2 rests on),
and the loop at `:136-150` snapshots every `*.db` in the data dir with no exclusion list, so the archive also
carried `user_state.db`. I take my own snapshot at merge time.

Two measurements for q5's write-up of the same function, reported and **not** edited (the file is q5's
tonight, and it is an owner call what the restore path may restore):

1. `VACUUM INTO` **does** work over a read-only connection — proved on a 2-file-KB temp db: open
   `file:…?mode=ro`, `VACUUM INTO '…'` succeeded, wrote an 8,192-byte snapshot, and the source's size **and
   mtime were unchanged**. So the snapshot the job wants does not need the handle it uses.
2. `sqlite3.connect(str(source))` at `:94` is nevertheless a **read-write** open, and a read-write open of a
   WAL database silently recovers and checkpoints the `-wal` into the main file — which is my crash test from
   the pre-merge plan (8,269,824 → 8,294,400 B, a stranded 37,112-byte `-wal` folded in) and the whole reason
   qoder1 withdrew the source-checkpoint instruction as **C1**. So "the source is read, never rewritten" is
   true of `VACUUM INTO` and not true of the connection that carries it: the job can grow the main file and
   empty the `-wal` of a live database it does not own. Not corruption — it is lossless and crash-safe — but
   it is a write, and it is the difference between "a snapshot" and "a snapshot that also nudges the live
   file". `:85`'s `source.exists()` and `:96`'s `conn.close()` outside a `finally` are the other two findings
   q1 named, and the third (`Path.exists()` re-raising `EACCES`) is the same class as the `config.py` probe fix
   at trunk `11c1008` that this lane was assigned and then reassigned away from.

## The freeze instrument, restated because load1 is retired

Measured at the moment I stopped editing: `cpu some avg10 = 99.51`, `cpu full 0.00`, `io some 1.34`,
`memory some 0.00 / full 0.00`, MemAvailable 5,091 MB, SwapFree above the floor. **`cpu some` is the binding
number**: it is ≥ 60, so no test module, no crawl, no Gradle, no production read. Docs, grep, edits, and
writing tests without running them are allowed and are what this entry is. The daily backup is the load's
name — `radd-backup-hf.timer` fires 03:40 + up to 600 s jitter and runs to `TimeoutStartSec=7200`, so this
window is a once-a-day shape and not a lane's stray process.

## Not run, and what CI therefore decides

`test_admin_panel.py`, `test_coins_engine.py` and `test_docs_invariants.py` were **not** run locally;
`py_compile` is the only thing I executed against the edited files, plus the read-only probes named above.
The hosted Backend CI run on this branch's sha judges them, and if the two new tests are wrong in some way I
have not seen, that run is where it shows.
