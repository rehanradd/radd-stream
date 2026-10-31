# 2026-11-01 00:xx — q3 backend lane `[Q3-KEYPROV-MEMO]`: a phone number is a credential the
# server cannot see — the decision memo qoder1 asked for, measured before written

Lane: **qoder3**. Tree: `/tmp/q3_coins`, branch `q3-coins-engine`, based on `1f97bfe` (the coins
wire the owner landed). No new branch, no tag, no service action, no write to `/opt/radd-stream`.
This is a **memo, not a patch**: qoder1 asked for the durable control and its cost, so there is no
code change here. Requested as `Q1 -> Q3 SECURITY FINDING` at ~00:35 after `836c31f` deleted
`SyncContract.quickLoginKey` on the client.

## What qoder1 got right, and the one place the finding is bigger than stated

Confirmed from my own file, not from the dispatch: `accounts.py:24` does state it out loud — the
server "never receives the number, cannot tell a derived key from a random one, and treats it
identically". `create_account` is create-on-present (`accounts.py:1090`, mint-or-shape at `:1103`,
the single INSERT at `:1112-1113`), so an unknown well-shaped key becomes a row and answers
`created: True`.

The framing I would sharpen: qoder1 described the **guess** direction ("one hash, one request, full
library"). The guess is real but it is not the worst branch, because a guesser who is wrong gets one
`UnknownAccount` and nothing tells them they were close. The **pre-registration** branch needs no
guess at all and is silent:

1. Attacker knows a number — their own contact, a number they were given, a number on a business card.
2. Attacker computes the 16 characters offline exactly the way the deleted `quickLoginKey` did.
3. Attacker `POST`s it as `sync_key`. Create-on-present makes it **their** account (`:1103` → `:1112`).
4. The victim's app, on its next sync, writes favorites and progress into the attacker's row and
   reads back whatever is there. Neither side is ever refused; the limiter never fires because every
   request on that path is a *success* path.

That is first-writer-wins on a credential the victim cannot see and was never told to keep. It is
permanent until rotation, and rotation is the expensive option. So the class is not "someone can
guess your list"; it is "someone who knows your number can *own your account id before you do*."

## Measured, before writing (all of it read-only, one process, `nice -n 19`)

Target file: `/home/ubuntu/radd-stream-data/user_state.db` — 147,456 B, mtime 10-31 20:57, no
`-wal`/`-shm` present at measurement. That is the file the service uses: the unit (`pid 1835070`)
carries `RADD_DB_PATH` and `RADD_ADMIN_TOKEN` and **no** `RADD_USER_STATE_DB`, so
`accounts.default_db_path()` (`accounts.py:449-461`) falls through to `config.DATA_DIR`
(`config.py:128-131`, `/home/ubuntu/radd-stream-data` because it exists), and a depth-4 `find` for
`user_state.db` over `/home/ubuntu` and `/opt/radd-stream` returned exactly one path. Opened with
`?mode=ro`, so nothing here created or touched a WAL.

| measured | value |
|---|---|
| `user_accounts` rows | **0** |
| rows with `phone` / `pin_hash` / `linked_at` NOT NULL | 0 / 0 / 0 |
| revoked rows | 0 |
| `user_favorites` rows | 0 |
| `user_progress` rows | 0 |
| `device_trials` rows | 0 |
| `sync_key_attempts` rows | 3 (2 per-key-hash buckets + 1 `*global*`) |
| those buckets' windows | 2 failures total, both on **10-27 16:24 and 17:09**, `locked_until` 0 |
| `coin_ledger` / `streak_state` in this file | **absent** — the coins tables are not created on this host yet |

Table inventory for the file: `device_trials, payment_review_audit, payment_transactions,
sqlite_sequence, sync_key_attempts, usage_device, usage_dim_metric, usage_metric, user_accounts,
user_favorites, user_progress, user_state_meta, verified_incoming_tids`.

The deduction that matters more than the count: `_authenticate` resolves a key by `key_hash` and
raises `UnknownAccount` when the row is missing (`accounts.py:1003-1006`), so **a successful
authenticated request requires an existing row**. With 0 rows, this host has never served a
successful account read or write — the two October attempt buckets are the entire recorded auth
history, and both are failures. No bucket value, key hash, phone digit or PIN appears in this note:
buckets are `sha256:` digests by construction (`accounts.py:1008` passes `wanted`), and I printed
only their shape (`bucket TEXT PRIMARY KEY`, `accounts.py:574`) rather than their contents.

So: the class is **real, documented, and currently unpopulated**. The exposure is prospective on this
host, not yet instantiated on data — which is the single most decision-relevant fact here, because it
means the cheapest moment to fix it is exactly now.

## The enumerability fact qoder1 asked for: confirmed, and it is worse than "not detectable"

**Confirmed: a client-minted key cannot be told apart from a server-minted one, at any layer.**

* `new_sync_key()` returns `secrets.token_urlsafe(12)` — "12 random bytes render as exactly 16
  base64url characters" (`accounts.py:763-769`). The deleted client derivation was
  `base64url(SHA-256("phone-sync/v1|<number>"))[:16]` — **also exactly 16 characters**. Length,
  alphabet and shape separate nothing.
* Both branches converge on one line: `plaintext = new_sync_key() if key is None else
  _check_sync_key_shape(key)` (`accounts.py:1103`). `_check_sync_key_shape` validates only a length
  band and transmissibility — `MIN_SYNC_KEY_CHARS = 16` / `MAX = 256` (`:200-201`), no whitespace or
  control chars (`:815-828`). It never measures entropy and cannot: entropy is a property of the
  generator, not the string.
* The stored form is identical for both: `wanted = _hash_key(plaintext)` (`:1104`) →
  `"sha256:" + sha256(key)` (`:771-797`, prefix const at `:299`). One unsalted digest, no per-source
  marker, no KDF — and `_hash_key`'s own docstring already says a number-derived digest is
  offline-brute-forceable "no matter what this function costs".
* The row records nothing about provenance: `user_accounts` columns are
  `id, key_hash, created_at, last_seen_at, revoked_at, vip_until, linked_at, profile_name, phone,
  pin_hash` (`accounts.py:535-550`) and the create path writes exactly
  `key_hash, created_at, last_seen_at, revoked_at` (`:1112-1113`). **There is no column in which
  "who minted this" could live.**

Consequence, stated the way qoder1 predicted: **(a) is forward-only.** No `WHERE` clause, no
backfill and no audit can classify an existing row. `created_at` is the only lever, which is why (b)
can only ever be a time-window proxy that catches server-minted accounts too.

`phone IS NOT NULL` looked like a cheaper proxy for the population at risk — it is not: the phone
column is written by the profile-link path (`link_profile_with_pin`, `accounts.py:1391`), which is a
different act from deriving a key from a phone. A viewer can have one without the other in either
direction. Today both counts are 0, so the distinction is unmeasurable anyway.

## Why the limiter cannot help, with the number

`DEFAULT_MAX_FAILURES = 8` per bucket in a 600 s window, 900 s lockout (`accounts.py:205-207`).
qoder1's §16.5 per-IP token buckets and this counter are both **failure-path** devices —
`_authenticate` consults the tracker only when the lookup missed, by documented design: "a burned-out
bucket must never be able to deny a real key" (`accounts.py:994-997`). So neither can slow an attacker
who presents the *right* string (no failure recorded), and neither fires on pre-registration at all
(the key is unknown, therefore created, therefore a success). Tightening them would trade real
viewers' traffic for nothing on this class. That is why the control has to sit at provisioning.

## The durable control: (a), and specifically where it must sit

**(a) — stop create-on-present on the wire. `POST /api/v2/account` mints server-side; an unknown key
answers 401 and never becomes a row.**

It is the only candidate that kills the *class* rather than the *instance*: (b) rotates a population it
cannot identify, using a clock-based proxy that mislabels server-minted accounts, and signs viewers
out; (c) documents a door that the next viewer walks through. Under (a) an attacker cannot
pre-register anything, because registration is something the server does with its own 96 bits.

Placement, measured rather than assumed — **the change is one call site, and it is complete**:

* `accounts_api.py:698` is the only place a caller-supplied `sync_key` reaches the store:
  `accounts.create_account(db_path, key=payload.get("sync_key"))`.
* The zero-friction trial path does **not** take a client key: `grant_or_resume_device_trial`
  (`accounts.py:1182`) mints through `_mint_account_row` (`:1142-1153`, `new_sync_key()` at `:1148`)
  and the wire calls it with a device id only (`accounts_api.py:715`). So there is no side door to
  close, and closing `:698` closes the class.
* Keep the `key=` parameter on `accounts.create_account` — the test suite and the operator path
  construct deterministic accounts with it (`test_accounts.py:146`, `:165`, `:171`;
  `payments.py:1026`, `:1042`, `:1054`, `:1058`; `engagement.py:1127`). Removing it from the module
  would break six files for a benefit the wire layer already delivers. The control belongs at the
  HTTP boundary, which is where the untrusted input is.

## What (a) costs, named honestly

1. **Broken clients today: zero viewers.** Measured above — 0 accounts, 0 favorites, 0 progress, 0
   device trials, and a success requires a row (`accounts.py:1003-1006`). Nobody can be bricked who
   is not already brickable by the door itself. This cost is zero *only now*; it grows by one viewer
   per convenience sign-in from the moment the APK is installed until the server change lands.
2. **Older APKs that still send `sync_key`:** a real, small, code-visible cost. The server must
   **refuse loudly** — 400/401 with the existing machine-readable `weak_sync_key` → `invalid_params`
   mapping (`accounts_api.py:196`), so the client falls back to the trial path it already uses. What
   it must **not** do is silently ignore the field and mint its own: that would hand the device a key
   different from the one it stored locally, quietly forking two libraries. The tempting minimal patch
   is the wrong one, and it is worth saying so before someone writes it.
3. **A property genuinely lost:** client-side mint exists so "a device that loses the server keeps its
   own key" (`accounts.py:1094-1096`). Under (a) first provisioning needs one successful request. The
   module's own contract already requires the app to work with no account at all, and the trial path
   already mints server-side, so what is lost is narrow: purely-offline provisioning of a key you
   intend to sync later. I accept that trade and say plainly that it is a trade, not a free win.
4. **(a) does not fix anything already derived offline and never sent.** Correct, and it does not need
   to: the exposure requires presentation, and (a) removes the ability of a presented-but-unknown key
   to *become* an account.
5. **It does not fix the personal-data half.** The server still stores `phone` in the clear so the
   operator can find an account by it, by the module's own admission (`accounts.py:38-45`). (a) makes
   the number non-credential; it does not make the number absent. That is a separate owner decision
   and it lives in backups and any future export.

## The documentation defect this exposes in my own file

`accounts.py:26-31` still states the blast radius is "a bookmark list" and that a captured key lets an
observer only "read or scribble on a list of catalog work keys". That was true when it was written. It
is **false now**: the same 16 characters are the only credential for `/api/v2/account/coins`,
`/coins/history`, `/coins/earn` and `POST /coins/redeem`, whose receipt is a signed VIP pass that
`redact.parse_vip_pass` accepts on the download path. A phone-derived key therefore puts a *payable
entitlement* behind a computable string. The coins wire is `1f97bfe`, mine, and I did not update that
docstring — so the module's headline claim now understates its own risk. That line must be corrected in
whatever commit implements (a), not left as a stale reassurance.

## Also recorded, same window: the merge gate answered, and the answer inverts the supervisor's read

qoder1 measured `size=56` on both `fast_fetch.db` names at 00:3x and concluded they are "bare SQLite
headers — empty databases", so the mission "merges into an empty file at a path production does not
read". **The measurement is right and the reading of it is wrong, and the truth is the more dangerous
of the two.** A `stat` without `-L` reports a *symlink's own* size, and 56 is the character count of
`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`. Measured:

```
/opt/radd-stream/Fast_Fetch/fast_fetch.db            type=symbolic link  ->  merged_catalog_20261025.db  (mtime 00:32:17)
/home/ubuntu/radd-stream-data/fast_fetch.db          type=symbolic link  ->  merged_catalog_20261025.db  (mtime 00:32:29)
/opt/radd-stream/Fast_Fetch/fast_fetch.db.bak_empty_8mb  type=symbolic link -> merged_catalog_20261025.db (mtime 00:32:10)
stat -Lc ino:  both the alias and the catalog are inode 813810, size 6396899328, mtime 10-29 10:52
```

So the mission's target resolves — twice, by both spellings — to **the 6.4 GB file the public API
serves**. A true SQLite header is 100 bytes and starts with the magic; the `od -c` anyone gets from
these paths shows `SQLite format 3\0` *because `od` follows the link* into the catalog. The four gate
questions, answered against that:

**(1) Which path.** `/opt/radd-stream/Fast_Fetch/fast_fetch.db` at 00:2x was an 8,093,696-byte regular
file holding **0 posts / 0 releases / 0 `download_sources`** (measured once, pre-relink). At 00:32 it
became a symlink to the production catalog, so the mission's literal command writes production. And
`merge_catalogs.py:473` resolves the target as `--target-db` **or `$RADD_DB_PATH` or
`BASE_DIR/fast_fetch.db`**, while `/home/ubuntu/.bashrc:158` gained
`export RADD_DB_PATH="/home/ubuntu/radd-stream-data/merged_catalog_20261025.db"` in the same minute —
so omitting `--target-db` also writes production. There is no spelling of the mission that is safe,
and rule 9 of root `AGENTS.md` forbids the one that is possible. I have written to none of them.

**(2) Backup.** `cp`/`cp -a` is not a valid backup of a WAL-mode database: content can live in the
`-wal`, and a byte hash of a 6.4 GB file taken "after the copy" proves nothing about a file another
process can write. The online-consistent forms are `sqlite3 src ".backup dst"` or `VACUUM INTO`
(this box's CLI is 3.45.1, both present), verified on the **copy** by size + `PRAGMA integrity_check`
+ per-table counts — not by comparing against a moving source. A usable prior snapshot already
exists and qoder1 found it: `preapply_20261029_1726.db`, 6,396,899,328 B, mtime 10-29 18:57, which is
after the live file's last write (10-29 10:52). Its `-wal` is **0 bytes** (mtime 00:26:24) and nothing
holds it (`fuser` empty), so it is complete as it stands; and it is *not* a rollback point for a merge
I have not started, because no merge has run.

**(3) WAL discipline.** Measured, all metadata only: every `-wal` in play is 0 bytes — vegamovies
(00:22:57), bolly4u (00:23:09), katmoviehd (00:23:11) — and `filmyhit.db` and `mp4moviez.db` have **no
`-wal`/`-shm` at all**, which is what a rollback-journal database looks like. The catalog's own pair,
created 00:23 while I held read-only opens, was **gone by 00:32** (last connection closed, SQLite
checkpointed and removed it). No process holds any of these names now. A 0-byte wal means no
un-checkpointed frames, so those main files *are* the whole database and no checkpoint was needed
before reading them. I ran **no** `wal_checkpoint` anywhere, deliberately: the rule is never to
checkpoint a file another writer owns, and the service owns the catalog. One genuine hazard worth
naming rather than asserting: SQLite builds `-wal`/`-shm` names from the **path string it was handed**,
so opening the alias journals into `Fast_Fetch/fast_fetch.db-wal` — a second WAL pair for inode 813810
that the service never reads. The orphan pair beside the alias is dated 10-29 22:42, i.e. no writer has
used the alias since it was relinked. I have not reproduced the two-WAL failure mode and will not do
so against production; the control is simply that nothing may open either alias for write.

**(4) Adult ordering.** The fold is in the tool and on by default — `reconcile_adult_on_merge`
(`merge_catalogs.py:244-275`, using `fast_fetch.corroborated_adult_exposures` +
`apply_corroborated_adult_fold`, journalled in `adult_fold_journal` so `backfill_adult_key.py --undo`
reverses it) — but it runs at the **end** of each `merge_site_db` (`:279-302`, `adult_fold=True`;
`--no-adult-fold` opts out at `:464`). On a copy that is fine; on a file the public reads, rows are
appended first and reconciled after, which is too late to call a pre-merge reconciliation.
Measured entering (one pass each, read-only): vegamovies **445**, bolly4u **972**, katmoviehd
**1,017**, filmyhit **117**, mp4moviez **91** flagged rows = **2,642** entering a catalog already
holding **15,068** flagged over **150,799** posts (that number reported from the earlier measurement,
not re-queried). Post-merge counts are **not measurable** — no merge ran. `mp4moviez.db` cannot enter
at all as things stand: its tables are `sitemap_cache,posts,sqlite_sequence,releases`, so
`_source_family` (`:41-47`) raises before any row is read. And the honest limit on the fold: it is
*corroborated*, not the raw key-level `MAX(is_18_plus)` (which stays forbidden as an un-corroborated
rule), so unless a merge report prints `adult_exposures_remaining == 0`, the merged file is **NOT
deployable** until q5's key reconciliation runs on it — I will state that in the report rather than
let a green integrity check imply compliance. On dub collisions I have nothing: q2's
`[Q2-DUB-COLLISION-CENSUS]` query exists and its numbers are still queued on the load hold, so the
merge's `posts_conflicted` counter (`:330-365`, which retargets a canonical key rather than silently
picking) is the only figure I could report, and it does not distinguish a flagged twin from an
unflagged one.

Timeline for whoever owns the relink: `preapply`'s wal/shm touched 00:26:24/00:26:52, the three
`.bashrc`-adjacent symlinks at 00:32:10 → 00:32:29, `/home/ubuntu/.bashrc` modified 00:32,
`/tmp/q1_and_27c1034.log` at 00:31 and the `/tmp/q1_night_id` checkout at 00:33. I am not the author of
any of it and I have not undone it — `/opt/radd-stream` is the live tree, not my workspace.

## Status

* No account code changed, no branch created, no tag, no service action, no nginx change, no write to
  `/opt/radd-stream`, no read of the 6.4 GB catalog in this window (its flagged count is the already
  measured **15,068** over **150,799** posts, reported from that measurement rather than re-queried).
* Load at 00:36 was `5.35, 4.42, 3.22` — above qoder1's 4.0 floor, so nothing heavy was run and the
  merge stays frozen.
* Recommendation to qoder1: **(a), placed at `accounts_api.py:698`, with a loud refusal rather than a
  silent ignore, and the `accounts.py:26-31` blast-radius sentence corrected in the same commit.**
  While the population is 0 the cost of doing it now is one client-visible error code; the cost of
  doing it later is (b) with no way to aim it.
