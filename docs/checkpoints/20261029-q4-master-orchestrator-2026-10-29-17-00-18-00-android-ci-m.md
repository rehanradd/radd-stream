# q4 (Master Orchestrator), 2026-10-29 ~17:00–18:00 — Android CI made green, capacity measured, two docs claims retired, apply blocked on owner words

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## q4 (Master Orchestrator), 2026-10-29 ~17:00–18:00 — Android CI made green, capacity measured, two docs claims retired, apply blocked on owner words

**Fleet.** All four worker lanes were driven without idle time; pane IDs migrated to session names
(`qoder1`…`qoder5` → %0–%4) after a ~16:57 restart, so every dispatch went by name and was
re-verified by grepping the pane for its unique token. Delivered: `Q5-FORENSICS-8235` (verified at
scrollback line 346), `Q2-HUMTV-LAND-AND-NEXT`, `Q3-ADMIN-DEVICE-TRACKING`,
`Q5-PATTERN-SPLIT-DECISION`. Staged and still undelivered: `Q1-CACHE-WIRING` (qoder1 was generating
26+ min; it is mid-way through real Media3 1.3.1 forensics — decompiled `DefaultMediaSourceFactory`
and `MimeTypes.inferContentTypeForUriAndMimeType` and found that MIME is authoritative and an
unknown type falls through to `ProgressiveMediaSource` with sniffing. That is a genuine playback
defect, so I let it run rather than interrupt it).

**THE HEADLINE: Android CI is GREEN for the first time.** It was never red-for-code, it was
**unfed**: `5446771` (`fix(ci): the 9 hosted test failures and all 23 lint errors`) was local-only on
a `master` that had silently diverged — `git merge-base --is-ancestor 5446771 origin/master` → NO, 2
local-only vs 26 remote-only — and `ci.yml` triggers on `App/**`, so the last run was `11742e0`
(2026-10-28T21:21, failure). Cherry-picked onto `f0c1ca3` as `2caadb3`, pushed to both refs
(fast-forward, askpass, one attempt, no force), and run `40874380668` came back `completed success`
on `master` AND `main`: 14/14 steps, `BUILD SUCCESSFUL in 7m 2s`, `:app:testDebugUnitTest` executed,
`:app:lintDebug` clean. I did not verify locally on purpose — those two suites are excluded on
arm64 (Robolectric #9166), so only the hosted runner can judge them. Lesson for every lane: **when a
gate goes quiet, check whether the branch diverged before you blame the code.**

**Signing is impossible today, and the doc that said otherwise is corrected.**
`/actions/secrets` → `{"total_count": 0}` from a lane with `permissions {admin: true, push: true}`.
Proved by execution, not inference: `workflow_dispatch` on release.yml (run `40876596427`) failed in
**10 s** against the **7m 02s** build, i.e. at the `🗝️ Verify signing secrets are present` preflight
(`release.yml:53`), never reaching build/sign/publish — nothing was released. I did **not** generate
a replacement keystore: a different signing key makes every later upgrade incompatible with the first
install, and the key is the owner's to supply. `tags: []`, `releases: 0`, Release workflow had **0
runs ever** before my probe.

**`--apply` against the production catalog is blocked on the owner's own words and I will not
manufacture them.** `audit_adult_flags.py --help` requires `--owner-go OWNER_GO` = "the owner's own
words authorising this exposure event", plus `--prod`. The owner delegated *decisions* to me but never
wrote a word authorising an adult-exposure event; typing my own paraphrase into that field would be
fabricating consent. q5's gate is correct and stays. So production rows are un-flagged by exactly
zero lanes right now; the hardened auditor (mandatory fsync'd preimage, `retest_freed`,
public-total self-verify) is what makes it safe when the words arrive.

**PATTERN DECISION — I overturned q5's framing with a 12-title sample per token** (read-only,
`mode=ro`, `nice -n 15`, `ionice -c3`, LIMITed LIKE on `title`, 17:45):
`adult` 10/12 genuine adult ("Adult Short Film", "[18+] … Brazzers Originals English Adult Short
Film"), `naughty` 13/14 genuine (Brazzers, TeamSkeet, `naughty-ass-meets-angry-cock-2025`) → **KEEP
both**. `hunters` 0/12 and `rabbit` 0/12 adult (KPop Demon Hunters ×3, Transformers Prime: Beast
Hunters, Hansel & Gretel Witch Hunters, Were-Rabbit, 1001 Rabbit Tales, Peter Rabbit, **Jojo Rabbit**,
Rabbit Hole, Black Rabbit) → **REMOVE both**. q5 had reported all four as one class of "genre nouns";
acting on that single class would have pushed real porn into a general-audience app. Bonus measured
fact: `Trollhunters` and `Looney Tunes: Rabbits Run` are `is_18_plus=0` because the patterns are
word-boundary anchored — the anchors are load-bearing and must not be loosened. Also accepted q5's
4,246 over my 8,235 (four flag-bearing columns vs whole-row text); mine was never the actionable
measure.

**CAPACITY — measured, replaces my own estimate in the plan doc §G.** Loopback against the live
service: posts p50 314 ms / **3.2 rps** single-client at load 6.95; **3.7 rps** at 4 clients; **4.2
rps** at 4 clients on a quiet box; search 2.9 rps. Throughput is flat in concurrency → one vCPU is
the limit, not the connection layer (the server is genuinely threaded: `ThreadedHTTPServer
(ThreadingMixIn, HTTPServer)`, `viewer.py:2982`). **The first wall a user hits is our own limiter, not
the CPU**: `redact.BUCKET_LIMITS` (`redact.py:1108`) is play 30/60s, browse 60/60s, reports 10/60s,
account 30/60s, keyed per client IP — 8 concurrent clients from one address got **24/24 `429` with
`Retry-After: 36`** at load 3.6, and `/api/v1/stats` 429s after ~10 calls because its bucket is
10/min. Dominant cost is the ~300–480 ms 20-post query, which is why the projection rebuild beats
any micro-optimization, and `is_18_plus` is unindexed (full scan of 150,799 rows). Even at **load
14** with Gradle and a prod snapshot running, `/api/v1/stats` answered in **20 ms** and
`/api/v1/posts?page_size=10` in **242 ms** — everything on this box is nice'd, so user-facing latency
survives the fleet. Derived, with assumptions stated as mine: ~15–25 concurrent browsers before p50
passes 1 s; order 1,000–1,500 DAU comfortable at $0, a few thousand at degraded evening latency.

**THREE LIVE-TREE HAZARDS FOUND, ONE OF THEM CREATED BY ME.**
1. I ran `git checkout f0c1ca3` **inside `/opt/radd-stream`** — the live deployment tree — while
   looking for PARTNER_API.md. Against my own written rule. I restored it to `bf9e565`/`master` and
   then proved no work was lost (`is18Plus` present in `Models.kt`, `version = 7` in
   `AppDatabase.kt`, 33 files/+1,675 intact, stash list empty). Both checkouts used `2>/dev/null`, so
   a *refused* checkout would have been silenced — that is why I verified instead of assuming. Use
   `git show <sha>:<path>` or a worktree; never the live tree.
2. The live tree carries **33 modified files / +1,675 lines of uncommitted lane work including a
   +191-line `viewer.py`**, while systemd runs `WorkingDirectory=/opt/radd-stream` with
   `Restart=on-failure RestartSec=5`. An OOM kill therefore silently promotes ungated code to the
   public API. I compile-checked the 8 core modules (all OK) so a crash-restart cannot hard-fail on
   syntax; that is a floor, not a gate. Left the drafts in place and am recording them rather than
   committing over another lane's work.
3. qoder1 was running **Gradle inside `/opt/radd-stream/App`** (pids 1267017 → daemon 1253663
   -Xmx1536m + Kotlin daemon 1257464) while my consistent prod snapshot ran on the same disk; load
   hit 15.19. I did not kill a build mid-flight. I removed the load I owned instead — SIGSTOP'd my
   own paused audit, then terminated it (it was mine, read-only, no writes) and later reclassified
   the snapshot from idle to best-effort/n7. Gradle-in-the-live-tree is in q1's staged directive.

**Merge posture.** Consistent snapshot via the sqlite3 backup API (NOT `cp`, WAL makes a byte copy
inconsistent) is at ~320 MB of 6.4 GB and crawling because idle-class I/O is starved at load 14; the
nightly `d50ca7d7` backup and the auditor's own preimage are the reasons this isn't urgent. Merge
batch 4 stays held: new vaults now derive correct flags from the fixed patterns, so the adult defect
is no longer a merge blocker, but a finished snapshot and a quieter box are. q2 landed Hum TV
(`35f9e89`, on both refs) with the honest licensing line in the message, as instructed.

**Landed by me this window:** `2caadb3` (Android fixes), `e726efc` (AGENTS.md secrets + CI-health
corrections, and `docs/MONETIZATION_AND_FLEET_PLAN.md` **which was untracked** — the owner's
directive plus my orchestrator decisions existed only in the live tree, one `git clean` from
deletion; now on both refs), plus this entry. Both pushes fast-forward to `refs/heads/master` and
`refs/heads/main`.

---

