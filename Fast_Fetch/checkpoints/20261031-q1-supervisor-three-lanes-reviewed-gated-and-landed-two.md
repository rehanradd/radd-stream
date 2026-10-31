# Session 2026-10-31 — qoder1 (supervisor): three lanes reviewed, gated and landed; two are held back

**Lane:** qoder1 — `.qoder` (chief supervisor / orchestrator) · **Base:** trunk `6a441ec`
**Host state at gate:** load `0.40 → 2.19`, 1 vCPU, no Gradle run by this session (the owner's
load-under-0.5 rule for builds still binds), no service restart, no nginx change, no tag.

## What was actually found running

All four workers were **idle at their prompt** when this session polled — nothing was in flight,
despite the dispatch note claiming three tasks were mid-run. Verified per lane against branches,
processes and the GitHub API rather than against the note:

| lane | pane | what it really produced |
|---|---|---|
| qoder2 | idle, ctx 22% | `q2-raddrelay` (`48aef8d`, 11 files, 1,282+) and `q2-dub-collision` (`b37b74c`). It also honoured the isolation order: `RaddRelay/` was moved out of `/opt/radd-stream` to `/tmp/q2_rrelay`, so the live tree gained nothing new. |
| qoder3 | idle | **Abandoned** the `[Q1-ADULTKEY-NET]` brief at `765f297` (read-path net only — no corroborated fold, no `test_adult_key_reconcile.py`, no CI step, no production count) and shipped the owner's auth task instead: `q3-backend-auth-payments` (`ad3228b`, 6 commits, 2,756+/53− over 11 files). |
| qoder4 | idle | `q4-player-zero-buffer-20261031` (`fa40960`, 15 files, 1,304+). Its "hosted CI green" claim is the one worker claim this session **confirmed independently**: `🔨 CI — Android Build & Test`, push event, `completed success`, run 47, attempt 1. |
| qoder5 | pid 1909845 alive, **pane unreadable** | `639e126` on `q5-ci-20261030`, but the terminal still emits `65;NaN;NaNM[…` escape garbage. It cannot be read or instructed; needs a relaunch by the owner. |

A fifth lane, **q6** (`/tmp/q6_docs`), is doing doc-truth work and is already merged (`14ecb57`).
Trunk had meanwhile moved to `6a441ec`, the owner had cut **`v1.0.0`** and documented the keystore
secrets as active — retiring this file's long-standing "signing is blocked, `tags: 0`" note.

## Landed (each merge is `--no-ff` into an isolated worktree, never `/opt/radd-stream`)

**`0e5ae28` ← `q3-backend-auth-payments`.** The branch that moves money, so it was read, not just
run. Gate: its own `test_device_trials_and_webhook.py` 83 OK, `test_database.py` 133 OK,
`test_vidout.py` 6 OK, plus `test_api_v2` 46, `test_admin_panel` 65, `test_payments` 85,
`test_accounts` 61, `test_accounts_api` 38 — every run `nice -n 19`, one at a time.
Security review recorded in the merge body: `RADD_MERCHANT_SECRET` compared with
`hmac.compare_digest` and an **unset secret authorises nothing** (no default, no warn-and-continue);
the header is verified **before** a byte of body is read and a test asserts `rfile.tell() == 0`;
PINs are PBKDF2-HMAC-SHA256 @120k with a fresh 128-bit per-row salt, constant-time verified, and the
branch explicitly refuses the recovered spec's `unsalted-SHA256(phone+pin)`; the relay credits only
on exact gateway + TID + the PKR **this server quoted**, is replay-safe and audited under
`payments.RELAY_REVIEWER`. Edge re-measured against `/etc/nginx/sites-enabled`: the webhook is not
in the allow-list and `location ^~ /api/` 403s it, so it is loopback-only exactly as its docstring
claims. Imports are stdlib only. Adult path untouched. Accepted and stated: a device id is a trial
**gate**, not an attestation, and the phone is stored in the clear so the operator can match an SMS.
Hosted verdict at that sha: **`completed success` on both `master` and `main`** (2 suites = the
backend workflow on the two refs; the Android workflow filters on `App/**` and correctly did not run).

**`8ca798a` ← `q4-player-zero-buffer-20261031`.** App lane, so its gate is hosted Android CI (742
tests, 0 lint errors, debug APK), and the landed tree is byte-identical to what CI judged.
`LocalVideoOpen`'s two refusals are the part worth keeping in prose: only `content`/`file` schemes
(an `https` intent would reach the player past the stream handle, the adult redaction and the
provenance) and no `BROWSABLE` category, so a browser link cannot land there either. This merge also
recovers `UniversalSourceTest.kt` — the file that existed only as untracked work on the live tree and
that I rescued to `q1-rescue-untracked` rather than watch a `git clean` delete.
**Regression flagged, not hidden:** `setSeekParameters(SeekParameters.CLOSEST_SYNC)` is **absent** on
this head (0 grep hits in `PlaybackService.kt`), so Session 31's scrub-seek fix did not survive into
the landed app; it exists only in `docs/rescue/20261031-live-tree-player-cache.patch`.

**`a424ffc` ← `q2-dub-collision`.** 13 offline tests OK, read-only and index-only, stdlib only. The
conflict it brought was the two append-only indexes (`checkpoints/README.md`, this file) — resolved by
keeping both lanes' lines and recomputing the count, which `test_docs_invariants.py` (18 OK) now
enforces rather than my arithmetic.
**The finding that reshapes task #13:** every staging vault declares `canonical_key` PRIMARY KEY or
UNIQUE (measured DDL: themoviebox, filmyhit, hindilinks4u, world4ufree), so **a dub twin cannot exist
inside one staging database** — the second subject with the same title+year is refused or collapses
onto the first row. The collision is only observable *across* databases, which is also the shape of
the merged ledger. A key-level reconciliation is therefore a **merge-time** problem, not a
staging-time column default, and a key-hiding clause computed against a staging vault would hide
nothing the staging rule could produce.

## Held back (not merged, dispatched instead)

* **`q3-adultkey-net` `765f297`** — an untested change to the *adult listing path* is the one class of
  diff this fleet must not land incidentally. Missing: the corroborated fold, `test_adult_key_reconcile.py`,
  the CI step, the read-only production count, and a decision about which single table owns the concept
  (`adult_justified_keys` vs `adult_fold_journal` — two tables for one idea is how a fix becomes folklore).
* **`q2-raddrelay` `48aef8d`** — reviewed enough to say it is **not safe to land yet**: it is an SMS-reading
  companion app, and nothing in the repo builds it (`ci.yml` filters on `App/**`, and `RaddRelay/` is a
  separate Gradle project at the root), so it has no CI at all. Its permission scope, the sender allow-list
  for the 8558/3737 numbers and the user-consent story are unreviewed. Reported rather than merged.
* `q4-deeplink-20261030` (`6881570`) and `q5-ci-20261030` (`639e126`) — one commit each on trunk, not yet read.

## Open hazards this session did not resolve

Live tree `/opt/radd-stream` is still 60 files dirty and ~473 lines behind in `viewer.py`; orphan agent
pid 1845966 is still running; qoder5's pane is still unreadable; 42 remote heads and 56 worktrees of
fleet sprawl; and **App Session 39/40 still name seven test files that exist nowhere on this host** —
that lane's own claim, left for the owner to retract or recover rather than edited by me from memory.

**Next action for a worker:** qoder4 re-lands the seek line with a guard; qoder2 adds the census CI step
and produces the three numbers in a quiet window; qoder3 finishes or formally closes the launch gate.
