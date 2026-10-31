# 2026-11-01 — q5 `[Q5-APP-REALITY]`: the persona matrix, the code-reality audit, and an audit base that went stale mid-audit

Branch `q5-register-money-keys`, continuing from `f01f99a`. Owner-via-Muse mission: five lifecycle
personas, a real-code App audit, monetization/distribution strategy, and tickets for qoder1.
Read-only `.kt`/`.py` inspection plus markdown; **no Gradle, no crawl, no catalog read, no
instrumentation** — load sat between 6.5 and 9.9 the whole session, so all heavy work stayed frozen.

Deliverables written outside the repo, where the owner asked for them:
`/home/ubuntu/USER_PERSONA_QA_MATRIX.md` and `/home/ubuntu/APP_COMPETITIVE_AUDIT_AND_BENCHMARK.md`.
Both are graded against **trunk `7b7f040`** (== `d87f9e8` code-identical per Q1's 01:10 notice), not
against my own branch, and every row carries a `file:line`.

## Scope I declined, and why it belongs in the log

Two of the four mission sections were ad-network selection framed as "which vendor won't ban a
streaming scraper", Play-Store policy circumvention for indexers, and third-party store/Telegram
distribution promotion. That is the root `AGENTS.md` sentence this lane exists to keep: *"Do not
disguise its purpose or frame work to bypass another service's safety rules."* I said no in-session,
did the remaining work anyway, and the no is now part of the record rather than a silent omission.
What I did instead on the same subject: an integrity review of the reward path, because the money
layer is where a fraud hole actually lives (below).

## The mistake worth keeping

My first pass audited `/tmp/q5_ci` at `639e126` — and `git diff --stat HEAD 7b7f040 -- App/app/src/main`
came back **19 files, +1,680 lines**, including `sync/DeviceTrial.kt` (300 new lines: the entire
device-trial persona), `LocalVideoOpen.kt`, `PlaybackMediaItemFactory.kt`, `PlayerBuffering.kt` and a
rewritten `SyncContract.kt`. Had I published it, the report would have said "trial ABSENT" and
re-ordered a roadmap around features that already shipped hours earlier.

So the rule this session earned, and it is the same rule the docs guard exists to enforce: **an audit
is worth exactly its base sha.** Record the sha in the first line of any read-only report, or the
report is prose about a tree that no longer exists. Re-verified at `7b7f040` in a fresh detached
worktree (created with `git worktree add -d /tmp/q5_audit_7b7f040 7b7f040`, removed after; no writes),
which turned three CONFIRMED claims into NOW-FALSE and found one already fixed (`moreJob` now cancelled,
`SearchViewModel.kt:230`). Two of my own counts were themselves stale mid-write and got corrected
before publication: `src/test` is **94 files / 782 `@Test`** (not 84/715), and `App/app/src/androidTest`
**does not exist** — absent, not empty.

## Findings that outrank the reports

1. **The instrumentation source set is absent.** 782 JVM tests, zero device tests, no on-device run
   evidenced anywhere in the tree. That single fact is the honest answer to "what tier are we in":
   the engine is upper-tier, the verification is none.
2. **Self-hosted update has no integrity check.** `apk_update_url` is opened with `ACTION_VIEW` after
   only `WireText.isHttpUrl` (which accepts `http://`) — `HomeViewModel.kt:82`, `HomeScreen.kt:187-190`.
   `isSameOriginAsServer` exists (`ApiProvider.kt:107`) and is unused there; no hash, no signature, no
   `versionCode` check. Filed UPD-1. A config edit or an on-path attacker ships an APK.
3. **The trial is designed correctly and gates nothing.** Countdown from server seconds plus local
   elapsed (`DeviceTrial.kt:173`, doc rule 2 at `:19-23`) — a fast clock sees less, a backward clock
   gains nothing; reinstall does not re-grant because the server ledger keys the device
   (`trialAnswer:199-210`). And the code states its own limit plainly at `:13-18`: a device id is a
   claim, not proof, and no UI may say "verified" or "locked to your device". `PhoneCredentialGuardTest`
   (11) is a build-breaker keeping the deleted phone→key derivation deleted. Meanwhile expiry is
   cosmetic: nothing consumes `trialExpired`. Filed TR-1/TR-2.
4. **The reward path is three disconnected layers.** Backend cap and grant exist and are tested
   (`engagement.py:648-692`, `admin_panel.py:1124-1125`), the client parses the knobs
   (`VipRemoteConfig.kt:148-160`) with **zero consumers and no endpoint among the 13 routes**, and
   "Watch Ad" mints a local 4-hour pass on `System.currentTimeMillis()`
   (`VipUpgradeScreen.kt:127,373` → `ServerSettingsRepository.kt:561-569`) — disclosed honestly at
   `:376-378`. No ad SDK is in the Gradle files at all; `di/AdModule.kt:41` binds `NoAdInventory` and
   every `offer()` returns `None`. The governance layer (62 `AdCadence*`/`AdSlotPolicy` tests) was
   built before the SDK, which is the right order; the ticket is to keep it that way when the SDK
   arrives: server-verified grant + cap + refusal of an unknown-or-flagged `link_id`, same fail-closed
   law as stream/download (AD-1, AD-2, UX-9).
5. **The backend already ships data the player throws away.** `PlayBundle.kt:188-189,236` carries
   subtitle sidecars and `:162` carries an audio-track list; `PlaybackService.kt:282` builds the
   `MediaItem` without them, and the track pickers read only Media3's `currentTracks`. Cheapest
   visible quality win in the product (SUB-1, AUD-1). Also: quality "ladder" swaps whole URLs — there
   is no `setMaxVideoSize`/video `TrackSelectionParameters` anywhere, so "Auto" cannot cap data use.
6. **Credential hygiene, two live defects.** The 16-char server-minted key is sent as `Authorization:
   Bearer` over cleartext HTTP (`SyncAccountRepository.kt:71-73`), stored in plaintext DataStore
   (`ServerSettingsRepository.kt:512,530`), and `keyPreview` reveals **10 of 16 characters**
   (`SyncContract.kt:151-153`, rendered `SettingsScreen.kt:264-269`) on the very screen used to write
   it down. Filed SEC-1/2/3. SEC-1 needs the owner: there is no TLS on this host.
7. **Trunk has 36 `🧪` steps and the money-and-keys trio is still absent** —
   `test_docs_invariants.py:572,585` at `7b7f040` still lists `test_accounts.py`, `test_accounts_api.py`
   and `test_payments.py` in `UNREGISTERED`. My registration (`3163d76`, measured 61/38/85 green
   offline) has not landed. CI-1 stands, and it needs a rebase onto `7b7f040` before landing.

## One claim retired on sight

The brief's "10Gbps Google CDN streaming" is not a code fact and I did not repeat it as one: nothing in
either tree declares, measures or caps a bandwidth class; the app plays what `/api/v1/stream` redirects
to on third-party hosters over plain HTTP. The supportable claim is that cross-source failover is real
(`RenditionFailover.kt:57` driven at `PlaybackService.kt:576-581`).

## Queued, not run

* Search latency probe (once, `-m 3`, below load 4): `curl -sS -m 3 'http://127.0.0.1:8080/api/v1/posts?q=inception&limit=18' -o /dev/null -w '%{time_total}\n'`
* nginx over-limit status: re-confirm `grep -n limit_req /etc/nginx/sites-enabled/radd-stream` (read the
  enabled symlink), then `limit_req_status 429` — **owner action, it touches nginx on a live host.**
* The first device pass: the debug APK from a green hosted run; no tag, no signing decision required.

## Addendum — CI-1 re-issued at trunk

`701b344` on branch `q5-ci1-money-keys-on-trunk`, cut directly from `7b7f040` in a detached worktree
(`git worktree add -d /tmp/q5_ci1_rebase 7b7f040`), so it lands without a rebase: three `🧪` steps
appended after `test_coins_engine.py` (step 36) and the same three names pruned from `UNREGISTERED`.
Gate measured **39** steps there; `nice -n 19 python3 -S Fast_Fetch/test_docs_invariants.py` →
Ran 22 tests, **OK**. The stale "35 of the 86" comment is deleted rather than re-numbered to 39.
`3163d76`/`f01f99a` on `q5-register-money-keys` remain the branch history; **`701b344` is the one to
land.** Not duplicated: `test_coins_engine.py` gates the wallet surface, `test_accounts_api.py` adds
the cross-hand `viewer.request_is_vip` proof (`:423-437`).

## Addendum — two claims of mine that trunk corrected, logged because the reports are the deliverable

* "No coin/reward endpoint exists" — false on trunk. `/api/v2/account/coins` (`accounts_api.py:607`),
  `/coins/history:631`, `/coins/caps:645`, `POST /coins/earn:809`, `/coins/redeem:841` are live and
  gated. What is true is the client half: none of the 13 `RaddStreamApi.kt` routes calls them.
* My AD-1 ticket asked for a server-verified reward path before any client reward call. Trunk already
  does better than the ticket: `_REFUSED_EARN` (`:145-153`) returns a 403 for `rewarded_ad` and
  `watch_time` because "no ad network calls *this* server back" and a stream is a redirect the server
  never observes, and `engagement.SERVER_SOURCES`/`grant_coins:712` make a client claim mint nothing.
  AD-1 is therefore now a *guard* ticket — a rewarded credit may leave `_REFUSED_EARN` only in the same
  change that adds a signature-verified network callback, and never by relaying one under
  `source="server"`, "a lie in the one column whose whole job is who vouched" (`:57-60`).

## Not done

The 16 state-shaped `INVARIANTS` pin conversions Q1 assigned are still open and now sit behind this
mission in the queue.
