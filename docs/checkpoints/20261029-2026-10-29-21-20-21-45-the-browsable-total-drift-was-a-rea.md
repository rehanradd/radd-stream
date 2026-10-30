# 2026-10-29 21:20–21:45 — the browsable-total "drift" was a real adult-flag rollback, and it is audited

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 21:20–21:45 — the browsable-total "drift" was a real adult-flag rollback, and it is audited

The open question at the last hand-off was why public `/api/v1/posts` `total` read 135,731 when I had
recorded 134,815, with the 6.4 GB catalog file untouched since 10:52:37. It is not drift and not a
filter regression; it is two audited writes, and the arithmetic identity holds exactly.

- **Measured read-only** (`file:...?mode=ro&immutable=1`, no `integrity_check`, one `COUNT` each):
  `posts` **150,799**, `is_18_plus=1` **15,068**, browsable **135,731** = 150,799 − 15,068. The
  05:14 rollback copy `prebatch4_20261029_051444.db` gives the same 150,799 posts with **15,020**
  flagged. So post count never moved; **48 rows gained the flag**.
- **Who wrote them:** `/home/ubuntu/radd-stream-backups/adult_flip_rollback_journal.txt`, six lines,
  timestamped 10:52:37 — "rolled back 407 of 455 key-reconciliation flips / kept (true adult
  evidence): 48 / public total 135324 -> 135731", preimage
  `adult_flip_preimage_20261029_104859.json` (455 rows, captured 10:48:53). The journal names its own
  root cause: `ADULT_TITLE_PATTERNS` contains `\buncut\b` and `\bunrated\b`, which are version labels.
  The sequence is therefore 135,779 (05:12) → 135,324 (all 455 flipped at 10:48) → 135,731 (407
  undone). Nothing is unexplained, and the direction of the change is *tighter* hiding, not a leak.
- **`stats.posts` and `total` are different numbers on purpose and I had been reading them as a
  conflict:** `stats.posts` is `COUNT(cat_works WHERE adult_clause)` (`_counted_stats`), 116,922 works
  − 13,342 flagged = **103,580**; `/api/v1/posts` `total` counts *post rows*, 135,731. Both verified
  against the same file at 21:35. Canonical works are fewer than posts because merges dedupe.
- **What the 19:14 crash-restart actually deployed** (this is the part of #19 that changes the facts,
  not just the risk): production now answers the **adult-excluded stamped stats shape**
  (`active_sources 0`, `sources_by_state {dead 21, unchecked 3696910, unknown 8543}`, 4.9 ms) and its
  list rows carry `subtitled`. Both were false on `bf9e565`, which was the last sha anyone reviewed.
  `docs/PROJECT_MAP.md` claimed "the running process still serves the old shape" — corrected in place,
  with the caveat that the running code cannot be reproduced from any pushed ref.
- **Production has never had an account or a payment.** The live catalog has 31 tables and *none* of
  `user_accounts`, `user_favorites`, `user_progress`, `payment_transactions` is among them — so
  "0 accounts" is stronger than a row count: the schema has never been created there.
  `app_remote_config` holds exactly 1 row with `updated_at = 0`: every payment handle column empty,
  both shortener tokens empty, `vip_monthly_pkr 200` / `vip_yearly_pkr 1500` at defaults,
  `maintenance_mode 0`, `feature_quality_gate 0`. `cat_shortened_links` = 0 rows. **The flag column
  `feature_link_shorteners` is absent from that table (18 columns where the pushed code declares 19),
  and `/opt/radd-stream/Fast_Fetch/admin_panel.py` (mtime 10-27 17:25) contains no occurrence of it.**
  So on production the "shorteners permanently retired" directive is currently enforced only by the
  tokens being empty — which is precisely the fragility the pushed guard in
  `admin_panel.py:1327-1346` exists to remove, and one more reason #19's deploy is worth deciding on.
- **Doc corrections shipped this window** (all measured, each row keeps its old value visible):
  `FULL_MASTER_FEATURE_INVENTORY.md` B-SEC-08 said "PBKDF2-style hash" — `accounts.py:593-624` stores
  one **unsalted SHA-256, prefix-tagged `sha256:`**, with `AttemptTracker` at `:658` on the failure
  path only; admin settings are **17** fields, not 15, and none of them encodes the engagement
  pillars (ad cadences, coin wallet, streak, ₨20/50/250 ladder) — that is gap M-MON (#22), restated
  here rather than invented as a doc error; Android test files/annotations are **81 (80 with
  `@Test`) / 637**, not 47/381; and the shortener row no longer says "server ✅" without saying the
  policy retired it. A dated header tells the reader the rest of the appendix is still a 10-27
  measurement.
- **Live-tree warning, recorded rather than acted on:** `/opt/radd-stream` carries uncommitted edits
  to `docs/PROJECT_MAP.md` (+54/−10) plus ~29 code/doc paths from the App and backend lanes (the
  cache/`keepNow` wiring, `catalog_v2.py`, `redact.py`, `CONTINUITY.md`). I did not commit from,
  reset, or clean it. My corrections were made in `/tmp/q4_ipfix` on the pushed tip, so the live
  draft and the pushed doc now differ; whoever resolves #19 should expect that doc collision.
- **This closes the open question `2c217d5` left standing at 18:56** ("two flagged-row counts disagree
  by 48", 15,020 vs 15,068). It was never a measurement error on either side: both were true, of two
  different moments, and the 10:52:37 rollback journal is the event between them. No re-derive, no
  re-flag, no reconciliation needed for those 48 rows — the audit trail already explains them, and the
  pattern bug it names (`\buncut\b`, `\bunrated\b` in `ADULT_TITLE_PATTERNS`) is task #12's subject,
  which is still blocked on the owner's verbatim `--owner-go`.
- **Gate re-run at this tip, in the worktree (never in the live tree), per `2c217d5`:** `test_database.py`
  **133 tests OK** in 30.7 s, `test_vidout.py` **6 OK**, `importers/test_host_resolvers.py` **171 OK**.
  `AGENTS.md` still advertises "76 tests (measured 2026-10-29)", which is the live tree's stale count,
  and I am *not* editing it: the live tree holds uncommitted `AGENTS.md` edits, and the previous note
  in this file already decided that line belongs to whoever owns that changeset. The number a lane
  should expect at the tip today is 133.
- **Fleet/SLO:** load 5.22 falling to 2.34 (one core), 8,608 MiB available, swap unchanged, all five
  worker panes `in_mode=0` and generating; no Gradle run (load gate 0.5 far away), merge batch 4 (#9)
  still held.

### 21:50–22:10 — the cold `/api/v1/stats` path is the capacity defect, and the projection is why

- `/api/v1/stats` on loopback measured **22.1 s**, then **42.2 s**, then **0.008 s**. Not noise:
  `_get_cached_stats` (`viewer.py:2956`) caches for 120 s per process, and on a miss it calls
  `_counted_stats`, which is a `COUNT(*)` over `cat_works`, a join-scan over `releases`, and a
  `GROUP BY state` across 3.78 M links.
- **The miss is structural, not occasional.** `cat_projection_meta` carries 18 keys and **none** of
  `works_safe`, `releases_safe`, `links_resumable_safe`, `links_temporary_safe`,
  `links_by_state_safe` is present — and the function is deliberately all-or-nothing ("a partial
  stamp falls back to counting"). The projection itself is also stale: `posts=130016`,
  `releases=1383752`, `links=3783959` — the pre-batch-3 catalog, against 150,799 posts live. So every
  120 s, whether or not anyone asks, the public `^~ /api/` allow-listed stats route re-runs three big
  scans.
- **Bounded accurately, because I checked:** the server is `ThreadedHTTPServer(ThreadingMixIn,
  HTTPServer)` (`viewer.py:3018`), so a slow stats request does not block the accept loop; but it is
  CPython work under the GIL on a **1-vCPU** box, so a 42 s scan starves every other handler's Python
  for its duration. For the owner's "how many users can this VM serve" question the honest sentence is
  *not* a requests-per-second figure — it is that one unauthenticated public endpoint can cost 42 s of
  the only core, and the fix is a stamp, not a cache layer.
- Dispatched into q2's job with these numbers (task #10). Told it explicitly not to add a second
  cache: the 120 s cache already exists, the defect is the missing stamp.
- **Android CI regressed to red at `0ff0164`** (run 40909885234, job 123574653479):
  `:app:compileDebugUnitTestKotlin FAILED`, BUILD FAILED in 2 m 17 s, on two errors in the
  ad-cadence test sources — `AdCadenceRowsTest.kt:75:9` unresolved `assertFalse`, and
  `AdCadenceGovernorTest.kt:265:44` passing an anonymous object where `FakeSwitch` was expected.
  Green at `2caadb3` was real and this is a newer commit, so the app lane is red again; queued the
  exact two lines to q1 with the standing rules attached (fix, do not delete assertions; load < 0.5
  before any Gradle; `/tmp/qbuild.sh`; report the CI conclusion, not a local build). Backend CI is
  independently green at `dea1e41` and `66f8edd`. Total runs now 79.
- **VIP price authority decided by me, per the owner's standing "decide everything yourself":**
  `docs/MONETIZATION_AND_FLEET_PLAN.md:46` says Monthly VIP ₨250, and *two* code defaults say 200
  (`payments.py:85`, `admin_panel.py:929`). Both 200s are defects, not a document disagreement. The
  live `app_remote_config` row reads 200 with `updated_at = 0`, i.e. the never-saved default, so
  fixing the code fixes the quote and **no production data write is authorized or needed**. q5 has
  the task. If any client code baked 200 in, it must read remote config instead.
- **The real reason the 19:14 deploy happened, and it is a process change, not an incident — with one
  claim of mine softened twenty minutes later.** Every worker lane's status line reads
  `/opt/radd-stream` (q1's reads `/opt/radd-stream/App`), which is the CLI's launch directory; I took
  that as proof the lanes edit production, and it is not. `git worktree list` shows **27 worktrees**,
  including `/tmp/q1_ad`, `/tmp/q1_id`, `/tmp/q2_ledger`, `/tmp/q2_scen`, `/tmp/q3_admin`,
  `/tmp/gate_q5` — so the qoder lanes do keep their commits off the live tree. What the live tree's
  dirt actually is: drafts whose only copy is there (the App player/cache files match **no** lane
  worktree I compared them against) plus one file that matches `/tmp/q2_ledger`, plus
  `MONETIZATION_AND_FLEET_PLAN.md` at 43 lines *behind* the pushed version. The instruction to every
  lane still stands and for a better reason than I first gave: the launch directory is not the
  workspace, and the tree that systemd restarts into must be nobody's workspace. Verified state of
  #26 is therefore "worktree discipline exists, live-tree residue does not belong to a lane we can
  name" — and the residue is now snapshotted, not assumed.

### 22:10–22:35 — my own wrong claim corrected, the real account store measured, and a near-miss revert

- **I published a wrong statement twenty minutes ago and it is corrected here, not deleted:** my
  21:40 entry said production "has no account or payment tables at all", counted from
  `merged_catalog_20261025.db`. The substantive conclusion holds — there is not one real account,
  favourite, progress row or payment anywhere — but the store is a **different file**.
  `accounts.py:148,179,328` put `user_state.db` outside the checkout, and that file is
  `/home/ubuntu/radd-stream-data/user_state.db`, mtime **19:33**. Quoting my catalog claim as if it
  were the account claim would send the next reader to the wrong file.
- **`user_state.db`, measured read-only at 22:15:** `user_accounts 0`, `user_favorites 0`,
  `user_progress 0`, `payment_transactions 0`, `payment_review_audit 0`, `sync_key_attempts 3`,
  `usage_device 0`, `usage_metric` 1 row, `usage_dim_metric` 4 rows, `user_state_meta` =
  `schema_version 1`. So the owner's "how many users/accounts/money do we have" question has a hard
  answer today: **zero accounts, zero payments, 42 recorded playback starts** (day 20755), and all
  four dimensions on those 42 are `unknown` — installs, geo, locale and app_version were never
  attributed. I am not calling them humans; nothing in the repo proves who pressed play.
- **The 42 rows and the `usage_*` tables came from unpushed code.** `grep -rln
  "playback_start|usage_device"` over the pushed tip returns nothing, and over `/opt/radd-stream`
  returns nothing; the only copy of the module is `/tmp/q3_admin/Fast_Fetch/usage_stats.py` (+
  `test_usage_stats.py`), q3's, at `d6861bb`, not landed. So the live operator state file now carries
  schema and counters that no ref can reproduce or read. The design itself is right (salted
  `dev-` digests, aggregates only, no IP read, incremental UPSERT instead of scanning the 1.7M-row
  ledger, loopback-only surface) and it is the answer to the owner's admin-panel
  active/live/devices/accounts/money ask — it just must not be developed against production data.
  Told q3: prove the resolved path inside its own test, do not delete the rows (that is mine to gate),
  land the module with tests green.
- **A near-miss I almost caused, recorded because it is the reason the live-tree rule exists:** I
  copied `/opt/radd-stream/docs/MONETIZATION_AND_FLEET_PLAN.md` over my worktree's version on the
  reasonable-looking theory that a file the live tree shows as `??` must be unpushed. It *is* tracked
  at the tip, and the live copy is **43 lines shorter** — the 18:58 primary-source update block and
  the entire "Correction 2026-10-29 20:20" shortener-flag section. `git diff --stat` before committing
  caught it and I restored the pushed version. So the live tree is not merely dirty: on this file it
  is behind, and the AGENTS.md warning about a silent revert of pushed work is now a measured
  instance rather than a hypothesis.
- **Snapshot taken, nothing deleted:** `/home/ubuntu/radd-stream-backups/livetreestate_20261029_2220/`
  holds `tracked.patch` (2,932 lines), `status.txt` (59 entries, 26 untracked) and copies of the
  untracked files. Read-only `git diff` plus `cp -a`; the live tree was not committed from, reset, or
  cleaned. If a future session is tempted to restore it to a ref, the only copy of some in-flight work
  is now in that directory, not in the tree.
- **Two directives became tracked at `e9fbd09`+1** (`App/docs/PLAYER_AND_CACHE_DIRECTIVE.md`, 40 lines,
  and `docs/GITHUB_AUTHORITY_NOTICE.md`, 7 lines) — added verbatim after a secret scan
  (`ghp_`/`github_pat_`/long-base64/private-key patterns: no hits). Before this commit the
  owner's universal-player brief and the "only repository agents may push to" notice existed solely
  inside the deployment tree, so the silently-deployed system was partly built from files no ref
  contains.
- **Merge state measured per site (task #5, and the real shape of #9).** Live catalog carries 31
  `source_site` values over 150,799 posts; top five are hindilinks4u 23,678, filmyzilla 15,228,
  katmoviehd 12,881, moviesmela 12,489, 9xmovies 11,462. Two things fall out of that list:
  **`mp4moviez` and `kuttymovies` are absent entirely** — mp4moviez has 29,848 posts in its vault plus
  11,403/11,404 in two staging copies, kuttymovies 900 — so batch 4 is real unmerged volume, not a
  duplicate, and it stays held only because the box is busy, not because the work is done. And several
  merged sites hold far more in their vault than they contribute live (filmyhit 16,943 vs 935,
  katmoviehd 38,154 vs 12,881, bolly4u 15,192 vs 4,253, world4ufree 14,768 vs 3,382, ssrmovies 13,916
  vs 6,678, 10xflix 13,775 vs 7,082, hdhub4u 11,224 vs 6,557, multimovies 10,498 vs 3,703, pagalmovies
  6,846 vs 3,642, filmiyin 3,837 vs 895). Dedup explains part of that; it does not obviously explain
  a 935-from-16,943 ratio, and `identity_suspect=41432` / `release_dups=295711` in
  `cat_projection_meta` says the merge has real collision work pending. **Nobody should quote "all
  sites merged" until that surplus is accounted for** — that is the honest state of #5.
- Also new since the last entry: `humtv_staging.db` (64 posts), `hindidubbedmovies.db` (40),
  `bollyflix.db` (38), `hindianimeszone.db` (36), `moviehax.db` (35) and `themoviebox.db` (**0 posts**,
  created 20:12 tonight) — six more vaults, none of them in the live `source_site` set yet.

