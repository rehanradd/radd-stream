# FINDING — the nightly backup snapshots the credential and payment store, and scope is decided by directory membership

> **Status: finding, not fix.** Owner decision, opened 2026-11-01. Nobody edited
> `Fast_Fetch/backup_manager.py`, the `radd-backup-hf` unit, its timer, or `~/.bashrc` to produce this
> file, and nothing here stops or kills a running job. Written by q5 on Q1's routing; Q1 owns the report
> to the owner.

## What happened, from the journal

`radd-backup-hf.service` (timer `OnCalendar=*-*-* 03:40:00`) started at **03:47:16** and enumerated
**49 databases** — its own first log line, not an inference:

```
03:47:17 [*] Found 49 databases: [... 'fast_fetch.db', ... 'merged_catalog_20261025.db', ...
         'resolvers.db', ... 'user_state.db', 'vegamovies.db', 'world4ufree.db']
04:44:03 [*] Safely vacuuming user_state.db...
04:44:56 [*] Creating compressed archive radd-stream-backup_20261031_224717.tar.gz...
```

At the time of writing the unit is still `activating` (`systemctl show -p ActiveState` → `activating`,
`NRestarts=0`, main pid 2297341) and no archive of that name exists in `/home/ubuntu/radd-stream-backups`
yet — only `radd-stream-code_*.tar.gz` from earlier runs. **The compression had not finished and the
upload had not started**, which is the one window in which this is a decision rather than a fact about
the past. I did not use that window and no agent should: it is the owner's job to stop or let run.
**(That window closed without either happening: see the 06:1x update below — the unit was killed by its own
2 h deadline, so no archive was ever built and nothing was uploaded.)**

## The mechanism, read from trunk `6014dd5`

| line | what it does | why it matters |
|---|---|---|
| `backup_manager.py:507` | `--dir` defaults to `/home/ubuntu/radd-stream-data` | the credential store lives in the same directory as the catalog |
| `:526` | `dbs = sorted(data_dir.glob("*.db"))` | **scope = membership.** Any `.db` dropped there is in the archive |
| `:139-153` | loops `db_paths`, `VACUUM INTO`, hashes, counts, adds to tar | no name is ever checked |
| `grep -n 'exclude\|user_state\|allow' backup_manager.py` | **zero hits** | there is no allow-list, no deny-list, no classification |

Three things this table gets right that a summary of it must not blur:

- **`VACUUM INTO` (`:95`) does not touch the source.** It reads and writes a fresh consistent snapshot,
  so the running job is not corrupting anything. That half of the original reassurance stands.
- **`_db_row_counts` (`:46`, adult count at `:61`) is catalog-shaped**: it counts only `posts`, `releases`,
  `download_sources`, `sources`, `post_sources`, `sitemap_cache` and `posts_adult`. For
  `user_state.db` it finds none of those and writes `{}` into the manifest, so the manifest itself does
  not disclose row counts of the account tables. Do not add that to the finding; the DB content does.
- **`fast_fetch_old_7mb_backup.db` failed** (`[!] Safe vacuum failed … unable to open database file`)
  and the loop simply continued. That is a *separate* defect: `create_backup_archive` returns whatever
  succeeded, with no minimum set, so a backup can silently omit a database an operator believes is
  covered. Same root cause as the headline — membership decides scope, and success decides nothing.

## Update, 06:1x — the run did not finish, and what that changed (q5, from Q1's measurement)

Q1's state message at 06:1x: `radd-backup-hf` **failed at 05:47:16 on `TimeoutStartSec=2h`** — the first
failure in four nights; the last good backup is **Oct 31 05:13**. He also found **22 GB of VACUUM
snapshots stranded in `/tmp/tmpjbp1_4w9`** (mode 0700, owned by `ubuntu`, containing a `user_state.db` at
0644), and ordered it left alone as evidence and the owner's call. I read only `ls -ld` on that directory
(`drwx------ 2 ubuntu ubuntu 4096 Nov  1 04:44`); I did not list or open inside it, did not delete it, and
have written no large file to `/tmp` — my two test modules use `tempfile` and remove themselves.

Four consequences, and the arithmetic is worth showing because it is the finding:

1. **The timeout is arithmetic, not bad luck.** The journal's own start was 03:47:16; the failure is
   05:47:16 — **exactly 7,200 s**, so the pass consumed its entire budget and was killed mid-work. With
   49 databases in scope and a 6.2 GB catalog among them, tonight's set cannot finish inside the unit's
   deadline. The scope defect and the deadline are therefore *the same decision*: an allow-list of catalog
   DBs changes the runtime, and a `TimeoutStartSec` sized to a set that includes the credential store
   guarantees either a timeout or a 22 GB `/tmp` residue. Do not "fix" this by raising the timeout alone.
2. **Nothing cleans the staging directory on a failed run**, which is a fourth defect in
   `safe_vacuum_sqlite`'s caller and a fifth in this file: `:88-89` unlinks a pre-existing *target* and
   `:91` creates the parent, but no path removes the snapshot set when the run is killed, times out, or
   fails half its databases. The result is that a **copy of `user_state.db` now sits on local disk at
   0644** inside a 0700 directory, with its lifetime governed by nothing in this repo. The directory mode
   is what stands between that and every other user on the box reading it, which is a stronger reason
   than any style preference to name the staging path explicitly instead of inheriting `tempfile`.
3. **The exposure this night is local, not off-box.** No archive was created, so nothing left. That is a
   *narrower* claim than the one this file makes about a successful night, and it is the correct one to
   make about the stranded 22 GB: it is a copy of an empty credential store on the owner's own disk.
4. **The restore side just got sharper.** "A backup that excludes the account store cannot rebuild one"
   (§ the proposed rule) is now true with no ambiguity: the newest off-box copy of *anything* is Oct 31
   05:13, so the account store has no current protection in either direction, and q3 is right that its
   merge needs a snapshot taken by q3 at merge time — the nightly job is not a safety net tonight, and by
   §1 above it will not be one tomorrow either unless scope or deadline moves.

What I did **not** change: the scope mechanism (`:526`), the three code defects above it, the allow-list
design, or the instruction that this is the owner's call. I did not touch the unit, the timer, `~/.bashrc`,
or the evidence directory.

## The three defects in the snapshot function itself

Separate from scope, Q1 measured `safe_vacuum_sqlite` (`:78-100`) and I corroborated each line against
trunk `6014dd5` with `git show 6014dd5:Fast_Fetch/backup_manager.py`. None of them is fixed here.

1. **`:85` `if not source.exists(): return False` is not a total probe.** `Path.exists()` swallows
   `ENOENT`/`ENOTDIR`/`EBADF`/`ELOOP` and **re-raises `EACCES`**, so an unreadable-but-present database
   does not return `False` — it raises out of the function, out of the loop at `:139-153`, and out of the
   run. This is the same class Q5 just retired in `config.py` for `DATA_DIR` (the `_probe_dir` helper,
   `grep -c _probe_dir Fast_Fetch/config.py` → 2), reappearing in the backup path. The failure mode is
   the worst one for a nightly job: no `[!]` line at `:99`, because the exception is not raised inside
   the `try` at `:93`.
2. **`:95` interpolates the path into SQL**: `conn.execute(f"VACUUM INTO '{target.as_posix()}'")`.
   `VACUUM INTO` takes a literal, not a bound parameter, so there is no `?` form to switch to — the
   quoting has to be done by hand (`'` doubled) or the filename has to be rejected before it gets here.
   A path containing a single quote is a breakage vector at minimum: it splits the literal, the statement
   fails, `:99` logs and `:144` appends nothing, and the archive continues to build without that database.
   Every input to it today is a `*.db` name under `:507` plus a fixed staging directory, so this is
   latent, not live — say that rather than implying an injection was exploited.
3. **`:96` `conn.close()` is inside the `try`, not in a `finally`.** If `:95` raises, the connection
   object is left to garbage collection, and a leaked **read** transaction on a WAL database blocks
   checkpointing for every later writer against that file. The docstring at `:81` promises "Does NOT
   disrupt active crawler processes writing to WAL"; on the failure path the function breaks that promise
   in exactly the way it claims to avoid.

And one more, in the same three lines: **`:94` `sqlite3.connect(str(source))` opens the production
catalog read-write**, not `mode=ro`. A `VACUUM INTO` cannot modify the source, so nothing does today —
but the snapshot job holds a write-capable handle on a 6.2 GB live file, and the only thing between that
and a real write is the text of the statement it chooses to run. The URI form is the cheap fix:
`sqlite3.connect(f"file:{quoted}?mode=ro", uri=True)`.

## What is in the file, and what is not proven about it

`user_state.db` (147,456 B, `-rw------- ubuntu ubuntu`) was read with **one bounded read-only schema
query by Q1, not by me** — a production read is frozen on this box and I have not opened the file. His
measurement: 13 tables including `user_accounts`, `payment_transactions`, `payment_review_audit`,
`sync_key_attempts`, `verified_incoming_tids`, `usage_device`, `user_favorites`, `user_progress`,
`user_state_meta`. Treat that list as his, cited from `/tmp/q1_backup_correction.txt`, and re-run it
before repeating it: `sqlite3 -readonly` plus `SELECT name FROM sqlite_master WHERE type='table'`.

What the code proves about those columns, line by line:

- **A minted sync key is not offline-searchable.** `accounts.py:768` returns
  `secrets.token_urlsafe(12)` — 96 bits of uniform randomness — and `:771-795` says in its own docstring
  that an attacker holding the file "faces 2^96 preimages whatever we spend per hash". So the unsalted
  `HASH_PREFIX = "sha256:"` at `:299` / `:795` is a considered choice, not an oversight.
- **A phone-derived key is exactly the opposite, and the file says so too.** Same docstring,
  `:782-790`: "A key the APP derived from a phone number is the opposite case: its real input space is
  the phone space, so the digest of one is brute-forceable offline no matter what this function costs."
  Whether any row in `user_accounts` holds an app-derived key is **not measured by anyone in this
  lane** — that is the question the owner should ask before deciding severity, and it is answerable with
  one read-only query on `key_hash` shapes.
- **The PIN is the weak secret the file already admits.** `:278` stores
  `pbkdf2_sha256$<iters>$salt$digest`; the comment at `:264-266` states it is "NOT protection against an
  attacker who owns the file and can spend the whole machine offline for a week on 10^4 guesses". A copy
  of `user_state.db` off-box turns that accepted-risk sentence into a live condition.
- **Payment and behaviour rows leave the box regardless of any of the above**:
  `payment_transactions.tid`, `verified_incoming_tids.tid`, `user_favorites.work_key`,
  `user_progress.work_key`, `usage_device`. Those are entitlement identifiers, what a person watches,
  and device identity — a catalogue of who pays for what and what they watched, shipped to an external
  target every day.

So the correct one-line description of tonight's job is: **the credential and payment store is wired into
a scheduled off-site copy, and the thing that decides whether it is in that copy is the name of the
directory entry, not a policy** — with the store empty today, which is the next section.

## Cardinality, measured 05:25 by Q1: the store ships **empty**, so the exposure is prospective

Q1 followed the schema read with bounded read-only counts on the same file
(`/tmp/q1_backup_counts_20261101.txt`-style measurement, his numbers, not mine — re-run before repeating):

| table | rows |
|---|---|
| `user_accounts` | **0** |
| `user_accounts.key_hash` non-null | **0** |
| `payment_transactions` | **0** |
| `user_favorites` | **0** |
| `verified_incoming_tids` | **0** |
| `sync_key_attempts` | **3** |

So the archive ships the credential and payment **schema** with no credentials and no payments in it
today. That is a material downgrade and it has to be stated in both directions:

- **What it does not change.** The scope mechanism (`:526`, membership decides) is unchanged, the
  non-total probe at `:85` is unchanged, `try/finally` is unchanged, and the egress-on-env-presence shape
  at `:542`/`:546` is unchanged. The allow-list rule below is still correct and still needs the owner.
- **What it does change — severity, and the last bullet above.** "Payment and behaviour rows leave the
  box" is true of the *table*, not of its contents: there are no payment or favourite rows to leave. Read
  that bullet as prospective. So is the phone-derived-key brute force: with 0 rows and 0 non-null
  `key_hash` there is nothing to attack yet. The first convenience sign-in mints the first unsalted
  `sha256:` digest (`accounts.py:299`), and from that moment the nightly archive carries a live secret —
  which is precisely why the exclusion is worth deciding **now**, while it costs nothing, rather than
  after the first paying viewer appears.
- **The one non-zero table is not innocent either, and is not a credential.** `sync_key_attempts` has 3
  rows; whatever that table records (rate-limit state, by its name and the `:771-795` neighbour) it is
  operational data, not a secret, and nobody in this lane has read its columns.

The rule stands; the alarm does not. Anyone repeating this finding should give these six numbers in the
same breath as the table name.

## Where it goes, and why deleting it later is not revoking it

The HF path authenticates cleanly — `_hf_git_env` (`:384-409`) writes a 0700 askpass helper, sets
`GIT_ASKPASS`/`GIT_TERMINAL_PROMPT=0`, and the token never enters a URL, argv, `.git/config` or a log.
That is the right construction and it should be said plainly, because the finding is about scope, not
about credential hygiene. Two facts change the blast radius:

1. **The transport is git + LFS** (`:427` `https://huggingface.co/datasets/{repo_id}`, `:451-453`
   `lfs track *.tar.gz *.db *.zip`, `:460` `git add -A`). An archive that lands there is in the dataset's
   history; deleting the file, or deleting it from the working tree, does not remove a copy a reader has
   already fetched or one that history still holds. Rotation of the stored keys, not deletion of the
   file, is the remedy — and that is the owner's call with the token state in front of him.
2. **Upload can fire on the mere presence of a token.** `:546` reads
   `if args.hf or args.all or os.environ.get("HF_TOKEN"):` and `:542` likewise uploads to GitHub Releases
   when `GITHUB_TOKEN` is set and no other destination flag was passed. Egress is therefore decided by
   the environment, not by the operator's flag — the same shape as the `RADD_DB_PATH` interactive-shell
   hazard, and the reason `~/.bashrc:158` matters beyond this one unit.

`GET https://huggingface.co/api/datasets/radddao/radd-stream-backups` answers **401** with no token
(measured by Q1; a 401 proves nothing is world-readable today, and does not prove the repo exists or
that it is private by policy rather than by token).

## The proposed rule — for the owner, with a test, not shipped tonight

1. Scope becomes an **explicit allow-list of catalog databases** (the per-site `*.db` set plus the
   unified catalog), and an unknown or credential-bearing name is **refused, not skipped**. Refusing
   loudly is the point: `:99` logs a failure, `:144` appends only what succeeded, and a new `.db` is silently included either way.
2. `user_state.db` is **never** in scope for this archive. If the account store needs a backup, it
   needs its own unit with its own retention, its own target and its own decision — different data,
   different risk, different owner approval.
3. A test that cannot be satisfied by the current code, and that is the whole reason to write it first:
   `test_backup_scope.py`, fixtures in a tempdir, asserting `collect_databases(tmp)` returns the
   allow-listed names and **raises or refuses** on `user_state.db`, and that the refusal is what happens
   when a name is unknown — no chmod, no real paths, no writes outside the tempdir. That is the same
   mock-and-tempdir shape `test_config_data_dir.py` uses for the probe fix, so it is cheap to review.
4. A manifest that fails loudly: assert the expected catalog set was snapshotted, so
   `unable to open database file` turns a partial backup into a non-zero exit instead of a `[!]` line in
   a journal nobody reads until a restore.
5. **The snapshot function gets its own three-line change, reviewable independently of the policy
   question**: a total probe at `:85` (reuse the `config.py` `_probe_dir` shape, or `try/except OSError`
   returning `False` so `EACCES` is a reported failure and not a crash), `try/finally` around
   `conn.close()`, and the read-only URI form at `:94` with the target path quote-escaped or validated —
   `VACUUM INTO` takes a literal, so the escaping is on us either way. None of these change what the
   archive contains, which is why they are separable from items 1-2 and why the owner can approve them
   without first answering the retention question.
6. **This changes what the restore path can restore.** A backup that excludes the account store cannot
   rebuild one, so the owner must decide where `user_state.db` is protected instead — a 147 KB file
   holding the only copy of every viewer's paid entitlement is not something to drop out of the only
   off-site set. Do not implement 1-4 without that answer. The empty-table measurement above makes that
   decision cheaper than it looked at 04:44, not unnecessary: there is nothing to migrate yet, and the
   protection needs to exist before the first row rather than after.

## What nobody should do because of this finding

Do not kill the running unit, do not disable the timer, do not edit `~/.bashrc` (the backup's
`ExecStart=/bin/bash -ic` is how it loads its token), do not add a `--dry-run` to the shipped command
line to "make it safe while we think" — a silent no-upload is how an owner ends up believing there is an
off-site copy. And nobody should re-quote my earlier line, now corrected in
`Fast_Fetch/checkpoints/20261101-q5-docstruth-release-row-the-ci-blind-spot-and-two-instruments.md`,
that tonight's snapshot is the merge plan's backup: it is not, and q3 must take its own at merge time.
