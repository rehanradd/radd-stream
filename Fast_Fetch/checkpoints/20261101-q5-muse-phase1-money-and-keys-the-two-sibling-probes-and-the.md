# 2026-11-01 — q5 lane, MUSE PHASE 1: the money-and-keys verdict, the two sibling probes, and a capability test that corrects its own brief

Lane: **qoder5** (backend, account5). Supervisor: **q1**. Branch: `q5-agents-count-method-20261101`,
based on and containing trunk `636eda5` (`git merge-base --is-ancestor 636eda5 HEAD` → yes). Machine at
start: `cpu some avg10=99.96`, `memory some 0.37 / full 0.00`, `io some 0.77`, MemAvailable 5,535 MB,
SwapFree 2,995 MB — **heavy work frozen all night; nothing heavy was started here.**

## What was ordered

Q1's Phase-1 brief (`/tmp/q1_muse_phase1_q5.txt`): *money-and-keys verdict + design audit + QA docs, push
your branch, CI green on your exact sha*, with three items formally handed to me:

1. `backup_manager.py` — **a write-up, not a fix**; do not edit the file, do not kill the running job.
2. `docs/SPEC_AGENTS_MEASURED_NOTES.md:44` — my own stale CI-health row; one dated re-measurement
   appended, same method as the row Q1 landed.
3. `config.py:31` and `:110` — the two sibling non-total `Path.exists()` probes that the landed `:131`
   fix retired by name; write it, tests included, and run locally only my own new module plus at most one
   neighbour, `nice -n 19`, one at a time.

Plus QA for `/tmp/q1_muse_cinefinder_spec.txt`. Ads parked repo-wide.

## What landed, commit by commit

| commit | what | measured verdict |
|---|---|---|
| `4beb25e` *(prior turn)* | the backup-scope finding, the repo-map index line, the self-correction appended to my own release-row checkpoint, CONTINUITY item 16 + the PSI heading | Backend CI run **`41257853890`** `completed success` at that sha |
| this turn | finding doc extended with Q1's three `safe_vacuum_sqlite` defects + the design he specified; the 06:1x timeout/22 GB update; `SPEC_AGENTS_MEASURED_NOTES.md:44` re-measured in-cell; `config.py` probe totality + 5 new tests; `Fast_Fetch/test_fts5_capability.py` + its CI registration; `docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md`; `docs/MUSE_PHASE1_Q5_CINEFINDER_QA.md`; this checkpoint | local: `test_config_data_dir.py` **Ran 9 tests** OK in 0.596 s (was 4), `test_fts5_capability.py` **Ran 5 tests** OK in 0.109 s, both at `nice -n 19` |

## The probe work (item 3), and the one thing about it that is a trap

`_probe_dir` was defined at `config.py:132` and used once. Both siblings Q1 named run **earlier in the
same import** — `_read_brand` is first called at `:44+` and the `RADD_DB_PATH` branch is a module-level
`if` — so the fix is not "wrap two more calls", it is "move the helper above its first caller". It went
between `BRAND_FILE` and `_read_brand`, and its docstring gained the paragraph saying the name is
historical and the use is not, because a `Path` whose `stat` raises is unusable whether it names a file or
a directory. `grep -c _probe_dir Fast_Fetch/config.py` is now **4** (def + three call sites); every lane
that was told "2" should re-measure before repeating it.

Semantics I chose deliberately, and their cost: an **unstatable `RADD_DB_PATH` parent now answers
"absent"**, which routes into the branch that tries `mkdir(parents=True, exist_ok=True)`; when that also
fails the existing `except Exception` lands on `BASE_DIR / _DB_FILENAME`. So an unreadable parent changes
from *import dies* to *the checkout-local database is used* — which is the same trade `_probe_dir`
documents for `DATA_DIR`, and it is a trade, not a free win: a checkout-local DB is the hazard AGENTS.md
rule 9 names. It is only reached when `RADD_DB_PATH` points somewhere that cannot be statted, which on
this box is not the production catalog path (that one is readable, and stays honoured — pinned by
`test_an_env_override_with_a_readable_parent_is_still_honoured`).

**The tests were proved to bite, not just written.** Against trunk's *unfixed* `config.py` the new module
reports `failures=3` — `test_an_unstatable_brand_file_answers_as_absent_and_raises_nothing`,
`test_the_import_survives_a_brand_file_it_cannot_stat`,
`test_an_unstatable_db_parent_falls_back_to_the_checkout_and_raises_nothing` — and against the fixed file
all 9 pass. That run happened in a scratch directory under `/tmp` holding two copied files, deleted
afterwards; it wrote nothing to the repo or to a database. `DbPathProbeTests` also needs a `mkdir` mock,
not just an `exists` mock: without it the "absent parent" branch really creates directories and the test
asserts the wrong branch for the wrong reason. That is why `_mkdir_denied` exists.

## The finding (item 1), extended — and the number that makes it a deadline problem

The three defects Q1 measured in `safe_vacuum_sqlite` are corroborated at the sha: `:85` non-total
`source.exists()` (EACCES escapes the `try` at `:93`, so it does not even reach the `[!]` log at `:99`);
`:95` `VACUUM INTO '{target.as_posix()}'` — `VACUUM INTO` takes a **literal, not a bound parameter**, so
the escaping is ours and a quote in a path is a breakage vector (latent, not live: every input today is a
`*.db` basename under `:507`); `:96` `conn.close()` inside the `try`, not a `finally`, so a failed VACUUM
leaks a read transaction and blocks WAL checkpointing — breaking the promise the function's own docstring
makes at `:81`. Plus `:94` opens the production catalog **read-write** where `mode=ro` is the URI form.

Then Q1's 06:1x state: the unit **failed at 05:47:16 on `TimeoutStartSec=2h`**, first failure in four
nights, last good backup Oct 31 05:13, and **22 GB of VACUUM snapshots stranded in `/tmp/tmpjbp1_4w9`**
(0700 dir, a `user_state.db` at 0644 inside it) — ordered left as evidence. I read `ls -ld` on that
directory and nothing more; I did not delete it, list inside it, or write large files to `/tmp`.

The arithmetic is the new finding: journal start 03:47:16, kill 05:47:16 = **exactly 7,200 s**, so the
49-database pass cannot finish inside its own deadline. Scope and timeout are one decision — an allow-list
changes the runtime, and raising the timeout alone buys a bigger `/tmp` residue instead of a backup. A
fourth defect follows: **nothing cleans the staging set on a failed run**, which is how a copy of the
credential store came to sit on local disk with no policy deciding when it goes away.

## The CI-health row (item 2), re-measured the way Q1 landed his

Appended **in the same cell**, matching the file's own convention, with the status cell struck through
rather than deleted. Contents: the keystore clause is superseded (proved by execution — run
`41233720264` passes the secrets preflight and dies at the build step), `releases: []` is still true but
for the opposite reason (`GET /releases` → `count 0`, my read; `total 5` Release runs, all `completed
failure`: one at the preflight, one at the unit-test gate, three at the build step), `tags` is Q1's
measurement and I did not re-query it (his stop), and both trunk refs are green — backend `41249889905`
(`main`) / `41249889922` (`master`) at `6014dd5`, Android `41247548668` / `41247548391` at `636eda5` —
while `636eda5` (two `App/docs/*` files) fed **no backend run at all**, which is the path filter working
and is the concrete instance of the blind spot I documented last turn.

## The Phase-1 design audit (the headline brief), in one paragraph each

**Money** (`docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md`): integer end to end (whole-coin `delta INTEGER`,
balance *derived* by `SUM`, PKR through one int gate that rejects `bool` and bounds at 10,000,000),
client-supplied prices refused, check-and-debit in **one** `INSERT … SELECT … WHERE balance >= cost` so
two concurrent redemptions cannot both pass, append-only by database *triggers* rather than by convention,
idempotency as a UNIQUE constraint, a zero price refused as a broken settings row instead of free VIP, and
a broken ladder refused **before** any coin moves. Two defects, neither of them theft: **MD-1** a
same-key race raises `IntegrityError` (the guarded insert is plain, the grant path is `INSERT OR IGNORE`)
where the API promises `already_applied`; **MD-2** `INSERT OR IGNORE` on the money writer cannot
distinguish "duplicate key" from "the row was rejected", and is safe today only because `_require_account`
and the reason/source checks happen first — a load-bearing accident. Plus **MQ-1**: the default redeem
key is second-granular (`redeem:{account}:{plan}:{int(moment)}`), so a retry one second later is a second
purchase; the fix needs the app lane to own the key, so it is written as a decision, not a patch.

**Keys**: every comparison I could reach is `hmac.compare_digest`; a minted 96-bit sync key does not need
a slow KDF and the file argues that rather than assuming it; the PIN's weakness is admitted in the comment
and the real control is the attempt tracker with its in-process mirror and its no-self-extension rule. Two
properties are weaker than their names: **KD-1** `_keystream(secret, n, salt)` has **no per-token nonce**,
and every row id is packed to the same 8 bytes, so the pad is identical for all handles — one known
`(id, handle)` pair de-opaques every handle in the wild and drops the enumeration defence the docstring
claims (it does **not** enable forgery: the tag is still HMAC under the secret); **KD-2** the two handle
minters truncate to a 32-bit tag while the capability pass uses 64 — fine for a row handle, and a rule to
pin rather than a hole to panic over; **KD-3** every call site falls back to `str(id)` when the signing
secret is unset, which makes an opaque-handle property a configuration accident with no failing test.

**Cine-finder QA** (`docs/MUSE_PHASE1_Q5_CINEFINDER_QA.md`): three contradictions reported instead of
chosen — (C-1) the route q3 is being assigned *already exists* (`media_search.py:312`,
`viewer.py:2990`, `test_media_search.py`, already swept from the public edge), so this is a modification
of a shipped route; (C-2) the two source-of-record docs disagree with each other, and
`ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` is a generated draft whose snippet opens `catalog.db` by relative
literal, shares one module-level cursor, indexes three columns `posts` does not have, and carries **no
adult clause and no `redact.project`**; (C-3) the promised query is not answerable from the ledger —
`synopsis` and `genres` yes, **dialogue text no** (subtitle data exists only as link rows), **actor names
no** (no cast column), frames by hard rule never. The bytes guard is designed against the repo's own
paired-guard convention (`DeadCodeGuardTest.kt:97` is the positive control every refusal needs), and the
item I would write first is **G3**: an FTS5 virtual table does not inherit `redact.adult_clause`, so the
synopsis index becomes a public list of flagged works unless a differential test proves the FTS answer is
a subset of the `posts` answer.

**The FTS5 capability test corrected its own brief.** The dispatch says to prove FTS5 with
`sqlite3.dbinfo()`; measured, that attribute does not exist on this box's Python 3.12.3 (it landed in
3.14) and raises `AttributeError`, which a lane could easily read as "no FTS5". The working instruments
are `sqlite3.sqlite_version` (**3.45.1**) and a real `CREATE VIRTUAL TABLE … USING fts5` in a tempdir —
`MATCH`, `OR`, quoted-phrase and `tok*` prefix queries and `bm25()` all verified answering, including a
must-be-empty negative (`'goalke'` without the star returns 0, so the test is not secretly asserting
substring search). Hence `Fast_Fetch/test_fts5_capability.py`, registered as a `🧪` step (mandatory:
`WorkflowSuiteCoverageTests` fails an unregistered on-disk module). It asserts a **floor** rather than
printing a version, because a green step is the only evidence an anonymous lane can read — job logs are
401 — and it **skips with a named reason** on an interpreter without FTS5 instead of reddening a gate over
a property the repo does not control.

## Not measured, and what a reader must not conclude

No database was opened by me; no route was probed with a sample size > 1; no production path was written
to; `backup_manager.py`, `~/.bashrc`, the unit, the timer and the evidence directory are untouched. The
money/keys tables are statements about **code at a sha** — whether any phone-derived sync key exists,
whether `OR IGNORE` has ever swallowed a real rejection, and the cardinality of `payments` all need reads
nobody has run. The stranded 22 GB is Q1's measurement; my only read on it was `ls -ld`.

## Next, for q1

1. Gate and land this sha; CI on the exact sha is the last thing I do, not the first.
2. `AGENTS.md:343`'s `46,476` byte figure still needs ~30 B freed to land the same treatment I gave the
   other two copies — currently blocked on the file's 32,000 B ceiling, not on measurement.
3. `grep -c _probe_dir` is 4 now, not 2; if any lane's report quotes 2 as current, that number is mine to
   have changed and theirs to re-read.
4. The MD-1/MD-2/KD-1/KD-3 fixes are **not** in this branch. They are written as designs because Phase 1
   is a verdict, and because KD-1 changes a wire format — that needs your go, not a lane's.
5. **The probe class is bigger than the two lines I was handed — measured, and deliberately not fixed.**
   `grep -rn --include=*.py -E 'not [a-z_]+(\.[a-z_]+)*\.exists\(\)'` over the money/state/backup modules
   returns **eight more sites**: `engagement.py:247`, `accounts.py:485` (those two are the same
   open-the-database-lines duplicated across modules, and they guard the file that holds every credential
   and every coin), `payments.py:249` (inside `price_table`, so it sits on the *money* path), and
   `backup_manager.py:85`, `:140`, `:499`, `:522`, plus `link_state.py:1023`. Repo-wide there are 30
   `.exists()` call sites outside test files. I fixed the two Q1 named and left the eight with their lines
   in this record, because widening a handed scope silently is how a lane ends up reviewing its own work.
   If the fleet wants the class retired, the cheap way is to move `_probe_dir` out of `config.py` into one
   importable helper and have the eight call it — a decision, not a sweep.

---

## Addendum, 06:5x — three rulings landed on this lane, and the replay hazard they exposed

**1. The freeze is a rule now, not a message.** Q1 published it after retracting his own 06:16 partial
lift: LIGHT-ONLY until **two consecutive sustained sub-4 windows** AND `cpu some avg10 < 50` AND the hard
floors clear (mem ≥ 1500 MB, swap ≥ 800 MB, radd cgroup ≤ 1200 MB). One window was his error, said as
much, and the fix was a rule rather than a reproach. Gradle is outside anything a supervisor can open —
only the owner, at load < 0.5, which he has not confirmed. Practical consequence for this lane: **plan the
work so CI is the verifier**, which is also cheaper and was already true — `test_clip_bytes_guard.py`,
`test_fts5_capability.py` and `test_config_data_dir.py` all have their first execution on a hosted run.

**2. The sync-key digest is ruled *do not act*.** Q1, 06:5x: unsalted `sha256:` (`accounts.py:299`) stays
the owner's decision, and no lane changes the KDF now, because a hash-scheme change invalidates every
existing key and **this box has no migration gate**. Recorded as recommendation 7 in
[`../../docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md`](../../docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md) rather than
left in chat, because the person who will "helpfully" fix it is reading that file, not this thread. The
empty `key_hash` column makes a change *cheap*, never *silent*.

**3. The replay, and the collision nobody flagged.** Trunk moved to `c2ae2bf` (q3's `settings_unavailable`)
after my `14ceca7`, so my branch was no longer fast-forwardable and landing it would have reverted q3's
`admin_panel` change. Replay by cherry-pick onto the new trunk — Muse's ruling was CI-only with no local
master merge, so **no merge commit**, and a *new* branch ref (`q5-g2-clipguard-20261101`) instead of
force-pushing the old one.

The interesting part: q3 and this lane each added one checkpoint file and each independently edited the
same CONTINUITY line `67 → 68 session files (65 → 66 dated)`, for **different reasons**. Git saw identical
text on both sides and auto-merged it — cleanly, wrongly. The union is **69 files (67 dated + 2 undated)**,
and `test_docs_invariants.py` compares that claim against the directory listing on every run, so the
replay would have gone red on a line that merged without conflict. Fixed in `7ccf6b0`.

**The lesson for every lane, stated once:** an auto-merge is not a semantic merge. A count, a total, a
"last measured at", or a version number edited by two lanes for two reasons will always resolve cleanly
and will always be wrong after the union. `git diff --stat <trunk> HEAD` proves the footprint; it does not
prove the arithmetic. After any rebase, re-derive every number that describes the *tree*, not just the ones
you wrote.

---

## Addendum, 07:2x — the verdict closed with a guard, and the guard corrected the verdict

Muse's slice: *finish the money-and-keys verdict, CI-verifiable, no KD-1, no MD-1/MD-2 code yet, no trunk
push*. Delivered `test_handle_provenance.py` (17 tests, registered) plus the coverage close-out in
[`../../docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md`](../../docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md) §E.

**Two of my own claims turned out wrong, and writing the test is what found them — recorded in the order
they broke:**

1. **KD-3 was overstated.** I wrote "one env var away from being broken", pointing at
   `mint_token(...) if secret else str(id)`. The idiom is real at `api_v2.py:1024`, `:1141`, `:1342` and
   `catalog_api.py:703` — note `:1024` is wrapped across two lines, which is why a one-line grep returns
   three and why the guard counts the *idiom*, not the pair. But the mount never hands those sites a falsy
   secret: `viewer.py:3770` passes `signing_secret()`, which cannot return `""`. So the fallback is
   **latent**, reachable only via `catalog_api.configure_public()`'s default `secret=""`. The *live* defence
   is `signed_only=not full` at `viewer.py:3683`/`:3949`/`:4011`, and that is what the new test pins.
2. **KD-5 is the finding I should have led with.** `redact.stream_secret` returns the literal
   `"radd-stream-dev-secret-unconfigured"` on three paths (`:957`, `:960`, `:978`) — and `:978` is
   `except Exception`, so a read-only or locked data directory downgrades to a key that is in the public
   repository. Nothing refuses, nothing logs, the handles look opaque. Demonstrated by minting a handle from
   the literal alone and having the server's own parser accept it. The fix is a behaviour change in the
   *minting* class Muse barred, so it is reported, not shipped.

**The method note, because it generalises:** a prose verdict cites lines; a test verdict has to call the
function. Every claim that survived being executed stayed; KD-3 did not, and KD-5 was invisible until I
needed a secret for a mint. **A verdict with no executable artifact is a memo, and memos do not fail when
the code changes.**

**Offline status, as asked:** `test_accounts.py` 61, `test_accounts_api.py` 38, `test_payments.py` 85 — all
three offline by source (tempdir `user_state.db`, zero `urlopen`/`socket`/`subprocess`, zero
`config.DATA_DIR`/`DB_PATH`/`RADD_DB_PATH` references) and offline *by evidence*, since a hosted runner has
no data disk to read and the steps are green in the same job. Nothing was run locally: the counts come from
`grep -c`, the verdicts from CI.

**16 pin conversions: still open, 0 of 15 converted.** All 16 labels are still present in `INVARIANTS`
(`test_docs_invariants.py:60-278`, 98 entries). Two are now tolerable because the prose they quote was
reframed as history; thirteen still assert today's state as law, including `266.312 s`, a single sample off
a loaded box. Conversion is a docs-plus-guard change that *does* feed CI (it edits a `Fast_Fetch/` file), so
it is sliceable on your word.

**Still blocked, unchanged:** the five "Not measured" items need a production read; `/opt/radd-stream` was
never opened; no crawl, no merge, no Gradle, no tag, no service restart, no credential read or printed;
`backup_manager.py` and `accounts.py` were read and never edited; `/tmp/tmpjbp1_4w9` untouched.
