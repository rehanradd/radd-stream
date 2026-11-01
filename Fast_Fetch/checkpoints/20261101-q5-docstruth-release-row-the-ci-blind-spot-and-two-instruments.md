# 2026-11-01 — q5 backend lane `[Q5-DOCSTRUTH-RELEASE]`: the release row is retired, and the ceiling that hides its own breach

Branch `q5-agents-count-method-20261101`, rebased by merge onto trunk `f12ab3f` (`2236c05`), then
`6014dd5` landed as trunk and this session's work sits on it. Commits, all pushed to this lane ref,
none landed by me — `a4496da` (archive recount), `6014dd5` (PR-gate claim), `b48d15f` (release row),
`273b80d` (the 46,476 method conversion). Supervisor owns trunk. Rules honoured: no tag, no service
touch, no `/opt/radd-stream` write, no Gradle, no local test module, no production read; every
command here is `wc`, `grep`, `git` or an anonymous HTTPS read.

## What was false, and what replaced it

`AGENTS.md:256` (on trunk from `63396c1`) asserted *"All 4 keystore secrets verified; tag `v1.0.0`
pushed and signed release pipeline active. Release artifacts published at …/releases"*. Three of the
four clauses are false against the anonymous API at `6014dd5`; one is true:

| claim | verdict | the read that decides it |
|---|---|---|
| 4 secrets verified | **presence yes, use no** | run `41233720264`: `🗝️ Verify signing secrets are present` → `success`, job fails two gates later |
| tag `v1.0.0` pushed | true | `GET /tags` → `v1.0.1`, `v1.0.0` |
| pipeline active | false | `GET /actions/workflows/398476978/runs` → `total_count: 5`, every run `completed / failure` |
| artifacts published at `/releases` | false, and the damaging one | `GET /releases` → `[]` — zero. That URL sends a reader to an empty page |

Per-run failing step, read from `GET /actions/runs/<id>/jobs` — and this is where the supervisor's
memo needed correcting, not copying: **not all five died at the build step.** `40876596427`
(2026-10-29) died at the secrets preflight, back when the secrets genuinely were absent;
`41102348096` died at `🧪 Unit tests gate the release`; only `41104217171`, `41104231187` and
`41233720264` died at `🏗️ Build signed release APK + AAB`. A lane that reads "everything fails at
signing" debugs the wrong file.

The same overclaim lived in two places beside the row, and both are fixed here rather than queued:
the four secret rows read `✅ CONFIGURED & ACTIVE` (now `CONFIGURED; build step fails` for
`KEYSTORE_BASE64`, `CONFIGURED, never exercised` for the rest), and the App quick-command block still
said `tags: [] and releases: [] are measured empty and /actions/secrets returns [] — the owner adds
the four keystore secrets and tags`, which is 2026-10-29 advice telling a lane to ask the owner for
work that is already done. The historical dated lines — the `total_count: 0` measurement, the
2026-10-30 update, the release procedure and its arrow that has never fired — are **annotated, not
deleted**; the receipts table went under them in `docs/SPEC_AGENTS_MEASURED_NOTES.md`.

Two numbers I refused to quote because they did not reproduce: the supervisor's debug-APK artifact
`13059801760` / 22,204,083 B — the artifact on run `41247548668` is `13059544891` `app-debug-87` at
`size_in_bytes` 22,203,694 — and `/actions/secrets` `total_count: 4`, which answers **401** to me
anonymously. Presence is therefore cited by execution (the preflight step succeeding) rather than by
a listing this lane cannot reach. The `Last unit does not have enough valid bits` base64 story is the
supervisor's read of a job log, and the notes file says so in those words; job logs are 403
anonymously, so step names are the deepest proof any lane has without a token.

## The finding that outranks the row: the ceiling cannot see the pushes that breach it

`backend-ci.yml` triggers on `push` with `paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]`.
`test_docs_invariants.py::ByteBudgetTests` enforces the 32,000 B ceiling on root `AGENTS.md` — and a
commit whose only content is `AGENTS.md` plus `docs/**` **feeds no run at all**. Measured, not
inferred: after `b48d15f` and `273b80d` the five newest runs were `41250078546` (q3), `41249889922`
and `41249889905` (trunk `6014dd5`), `41248834072` and `41248834038` (`a4496da`) — neither docs-only
sha of mine produced one. This is exactly how a fabricated `31,849 B` claim survived a whole evening
last week: the file went over its ceiling, CI stayed silent, and only a manual `wc -c` found it.
Two ways to close it, and the choice is a supervisor/owner call because it prices hosted runs:

1. add `"AGENTS.md", "docs/**"` to the workflow's `paths:` list — a docs push then judges itself;
2. keep the filter and require every docs-truth lane to ship one `Fast_Fetch/**` path (a checkpoint
   line, as in this file) in the same branch, so the guard runs on the landing sha.

`AGENTS.md` is now **31,990 B — 10 B of headroom**. That is a warning to the next lane, not a
completion notice: the next truthful sentence added to that file needs a trim first.

## Two instruments changed under me tonight, and both are now mine to use

`load1` is retired as the gate. The number I had been reporting was a **systemd timer**:
`radd-backup-hf.timer` (`OnCalendar=*-*-* 03:40:00`) fired `backup-hf` → `Fast_Fetch/backup_manager.py`
at 03:47:16 and compressed every DB in `/home/ubuntu/radd-stream-data` for a private HF dataset
(`GET https://huggingface.co/api/datasets/radddao/radd-stream-backups` → 401 with no token). I did
not touch it and nobody should: `backup_manager.py:95` uses `VACUUM INTO`, which reads the source and
writes a snapshot, so it cannot corrupt the catalog, and the snapshot it just made is the
pre-merge-grade backup the frozen merge plan is waiting on.

The replacement, measured from my worktree after the memo — and the CPU term is why nothing heavy
starts here yet:

```
/proc/pressure/cpu      some avg10=100.00  full avg10=0.00
/proc/pressure/io       some avg10=0.25    full avg10=0.00
/proc/pressure/memory   some avg10=0.00    full avg10=0.00
MemAvailable 4,558 M   SwapFree 2,096 M
```

Memory has fully recovered since the supervisor's 04:18 sample (`some 29.95 / full 10.10`); the one
vCPU is still saturated. Under the new rule heavy work needs `cpu some < 60`, which is not true, so
this session stayed in the always-allowed class.

The sharper hazard was `~/.bashrc:158`: `export RADD_DB_PATH=…/merged_catalog_20261025.db` (6,396,899,328
B of live catalog), behind the non-interactive guard at `.bashrc:5-9`. Reproduced three ways from a
lane shell, matching the supervisor exactly:

```
bash -c  'echo ${RADD_DB_PATH:-UNSET}'  ->  UNSET
bash -l  'echo ${RADD_DB_PATH:-UNSET}'  ->  UNSET
bash -i  'echo ${RADD_DB_PATH:-UNSET}'  ->  /home/ubuntu/radd-stream-data/merged_catalog_20261025.db
```

`config.py:107` lets that variable beat `BASE_DIR` outright, so a worktree is no protection inside an
interactive shell. This lane's rule going forward: never wrap a Python or test invocation in
`bash -i`/`bash -ic`/an interactive tmux pane — every `python3 -S -c` in this session was the plain
form and printed `DB_PATH = /tmp/q5_gate5/Fast_Fetch/fast_fetch.db`, no `merged_catalog` substring —
never `export RADD_DB_PATH`, and never edit `~/.bashrc`, because the owner's backup unit runs
`ExecStart=/bin/bash -ic` precisely to pick that export up.

## Not measured, and it stays unmeasured tonight

The `46,476 B` dashboard figure: re-measuring it is a loopback production read, so `AGENTS.md:343`
is untouched (it already carries its own timestamp) and the two doc copies got the method instead of
a new number — dated read, page is data-dependent, `curl -s` piped to `wc -c`. Whether UPD-1a's
three new `/admin` inputs actually shifted that page was **not** established here; the claim was that
they might, which is why the figure became a method rather than a re-quoted count. No device pass, no
Gradle, no merge, no crawl. `q4-release-configure-truth-20261101` (`e3f0396`) touches only
`App/docs/*.md`, so it does not collide with any of the above and still carries the old release row in
its own base.

## What the next lane owes

1. Answer the `paths:` question in §"the ceiling cannot see the pushes" — one sentence from the
   supervisor, then it is a two-line workflow edit.
2. `docs/SPEC_AGENTS_MEASURED_NOTES.md` line ~44 (the CI-health row) still says "signing is genuinely
   blocked on the four absent keystore secrets" and "`tags: 0, releases: 0`". Dated 2026-10-29/30
   prose, superseded by the table this session added at the foot of the same file; append the
   re-measurement there rather than rewriting it, and it is a one-commit docs job.
3. `config.py:31` (`_read_brand`) and `config.py:110` (`_p.parent.exists()`) are the same non-total
   probe the `DATA_DIR` fix retired at `:131`; same `try/except OSError`, same `mock.patch` shape as
   `test_config_data_dir.py`, no behaviour change on a box that can read both paths.
4. `AGENTS.md` has 10 B of headroom. Anyone adding a truthful sentence there must free a sentence
   first, and the rotation of `Fast_Fetch/CONTINUITY.md` (this session: 11,958 → ~11.2 KB) is the
   model: move the pointer bullets verbatim into `checkpoints/README.md`, then re-count the archive
   line — digit-for-digit, because that count is a tested claim.

## Correction, appended 2026-11-01 after Q1's own retraction — the sentence above this line is wrong

§"Two instruments changed" says the 03:47 run made "the pre-merge-grade backup the frozen merge plan
is waiting on". It is not, and the reason is worse than a scope mismatch. Re-measured from the unit's
journal at `6014dd5`, and this is the deepest read available without touching a database:

```
03:47:17 [*] Found 49 databases: [… 'fast_fetch.db', 'merged_catalog_20261025.db', 'resolvers.db',
                                  'user_state.db', …]        ← the run's own enumeration
04:44:03 [*] Safely vacuuming user_state.db...
04:44:56 [*] Creating compressed archive radd-stream-backup_20261031_224717.tar.gz...
```

`backup_manager.py:526` picks scope with `sorted(data_dir.glob("*.db"))` over
`--dir /home/ubuntu/radd-stream-data` (`:507`) and `grep -n 'exclude\|user_state\|allow'` on that file
returns **nothing** — so "which databases leave the box" is decided by directory membership, and the
credential and payment store sits in the same directory as the catalog. The archive therefore carries
`user_state.db`; Q1's bounded read-only schema query found `user_accounts`, `payment_transactions`,
`verified_incoming_tids`, `sync_key_attempts` and `usage_device` in it (his measurement, cited from
`/tmp/q1_backup_correction.txt` — I did not open the file, a production read is frozen).

What I wrote before this line came from the fleet message that generalised one catalog file to the whole
archive, and I repeated it back to the supervisor in a status report: "the snapshot it just made is worth
more than the CPU it costs". That was a quoted claim, not a measured one, and the code that decides scope
was three lines from the file I had already opened tonight. The rule that would have caught it is the one
this lane already uses for everything else — a trunk fact is read from the sha, and `glob("*.db")` is a
trunk fact.

Sharpened, because the memo blurred it: an **unsalted `sha256:` over a minted key is not the hole** —
`accounts.py:768` mints 96 random bits and `:771-795` says so with the right reasoning. The hole is (a)
`accounts.py:782-790`'s own admission that an app-derived phone-shaped key *is* offline-bruteforceable,
whether such rows exist being unmeasured, (b) `:264-266` admitting a 4-digit PIN is not protection against
whoever owns the file, and (c) payment and viewing rows leaving the box either way. Full write-up with the
allow-list rule, the test that should be written first, and why git+LFS history means deletion is not
revocation: [`docs/BACKUP_SNAPSHOT_SCOPE_FINDING.md`](../../docs/BACKUP_SNAPSHOT_SCOPE_FINDING.md).
Nothing was killed, edited or disabled here; the unit is the owner's, the timer is the owner's, and
`~/.bashrc` stays alone.
