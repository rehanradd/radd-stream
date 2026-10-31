# 2026-11-01 — q5 backend lane `[Q5-UPD1A-OPTIONA]`: the update banner gets an identity, and the key gets a gate before it gets a mask

Two branches, both based exactly on trunk `03d580a`, neither landed by me:
`q5-upd1a-sec2-20261101` holds the backend half (`85ee077`, UPD-1a) plus this entry, and
`q5-option-a-sec2-20261101` holds the Android half (`8c9fdf3`, Option A). They were one branch until
the supervisor ruled a green backend lane must land ahead of a red one and must not carry another
lane's file: `8c9fdf3` is `c5c1b7a`'s content replayed onto trunk, so the App commit no longer has
`Fast_Fetch/admin_panel.py` in its ancestry. Supervisor owns trunk. Rules honoured: no tag, no
service touch, no `/opt/radd-stream` write, no local Gradle (load1 5.4–7.7 all night against an owner
bar of 0.5), `nice -n 19` and one python module at a time.

## What UPD-1a changes (`85ee077`, `Fast_Fetch/admin_panel.py` + `test_admin_panel.py`)

`remote_config` now publishes three flat, additive fields beside the banner it already published:

| field | kind | default | rule |
|---|---|---|---|
| `apk_update_sha256` | new `_DIGEST` | `""` | exactly 64 lowercase hex, or empty; case normalised on write |
| `apk_update_size_bytes` | `_INT` | `0` | own ceiling 500,000,000 |
| `apk_update_version_code` | `_INT` | `0` | own ceiling 2,100,000,000 |

Why each is a decision: **flat**, because `VipRemoteConfig.kt` decodes `apk_update_url` at the top
level of a body cached 60 s on every phone, so nesting would break an un-updated client.
**Its own kind**, because a checksum is compared rather than printed and therefore fails silently:
a 63-character paste, a trailing space or one uppercase digit stores fine as `_TEXT` and then never
matches the hash of a correctly downloaded file — the operator sees a banner that will not appear,
not a row that cannot be right. **Its own `_INT_MAX` entries**, because the default ceiling is
1,000,000 — one megabyte — so the first size any real build produces would have been refused; the
test saves 5,000,000 to prove that. `""`/`0` mean *nothing published*, never *unchecked*: that is
the rule UPD-1b will enforce (no digest, no banner), written down here so the halves are reviewed
together.

Honest scope: **no shipped client reads these fields**, so this changes nothing on a phone by
itself, and the `/admin` hint says so. `openDownload` fires `ACTION_VIEW` and never asks for
`REQUEST_INSTALL_PACKAGES`, so verifying bytes we never receive is not reachable from that path —
UPD-1 can make the *offer* conditional, never the *install* verified.

## What Option A changes (`8c9fdf3`, six files under `App/`)

`SyncContract.kt`, `DeviceTrial.kt`, `MainActivity.kt`, the new `ui/screens/TrialKeyReveal.kt`, and
the two JVM test files `SyncContractTest.kt` (+5 tests) and `DeviceTrialTest.kt` (+1). No Python.

`SyncContract.keyPreview` is the only place a stored key reaches the UI at rest. It used to return
`key.take(6) + "…" + key.takeLast(4)`. The server mints `secrets.token_urlsafe(12)`
(`accounts.py:768`; its own header at `:18` calls it 96 bits) — 16 base64url characters, six bits
apiece — so the "preview" disclosed **60 of the 96 bits of a live bearer credential** in a static
text field, leaving 2^36 to search, on a screen built to be screenshotted. Its
`length <= 12` branch returned a short string whole: unreachable for a key the server would accept
(the band starts at 16), which is why it survived review and exactly the shape a fail-open has.
Both are gone: it returns eight hex digits of `SHA-256(namespace, newline, key)` as `abcd-ef01`,
and `""` for anything outside `isUsableSyncKey`.

The mask ships with a gate, or it does not ship — that was the ruling (Q1-GATE-5, superseded by
Q1-SEC2-RULING-2) and the reasoning was mine: the silent trial mints on the process scope at
launch (`RaddStreamApplication.kt:74` → `SyncAccountRepository.startDeviceTrial`), the server
stores the key one-way and says so about itself (`accounts.py:1200-1208`: "a device that lost it
cannot be given it back"), there is no recovery route, and the only display was the Settings card.
A viewer who browsed straight past it lost the account and found out on the second device. Masking
that would have made a real loss less visible.

So `DeviceTrial.keyToRevealAtLaunch` (pure, four-row truth table, testable on the JVM) drives
`TrialKeyRevealDialog`, rendered by `MainActivity` above the nav graph. Its `onDismissRequest` is a
no-op and every exit a Material3 dialog has — back, tap outside, scrim — arrives at that lambda, so
the only route out is "I have written it down", which clears `trialKeyUnseen` and cannot put the
key back on a screen. That is what finally makes the card's own sentence — "shown once, when it was
created" — true rather than nearly true.

**SEC-2b is retired, and it was retired for a reason worth keeping.** Q1's original gate condition
was "phone+PIN re-link that prints a fresh key". Reading the route found it is not a client change:
`profile-link` sits behind the bearer check (`accounts_api.py:719`), so it is unreachable to exactly
the viewer who needs it, and building it means a **new unauthenticated credential-minting route on
a 10^4-entropy authenticator** (phone number, which is not secret, plus four digits) guarding a
payable VIP entitlement. Recovery is routed to the backend/owner lane as its own decision, next to
the create-on-present memo (`20261101-00xx-q3-lane-…`).

**Residual, recorded as accepted and not as fixed.** The key is still plaintext in the app's private
DataStore (`ServerSettingsRepository.kt:512,530`); a rooted device or an adb backup still reads the
real value; the deployment is plain HTTP so the key crosses the wire in the clear. A mask defends a
screen, not a filesystem, and shoulder-surfing is not the threat model of a phone with a rooted
filesystem. This commit closes "60 bits of the credential in every screenshot", nothing more.

## Measured, and what is NOT measured

- `test_admin_panel.py` at `85ee077`: `Ran 71 tests in 145.770s / OK`, `nice -n 19`, load1 5.57.
  Six of the 71 are new. `test_docs_invariants.py` after this entry: `Ran 22 tests in 19.185s / OK`,
  `nice -n 19`, load1 5.75 — and that run was started before the standing instruction narrowed local
  modules to `load1 < 4.0`, so it is recorded as a rule miss against the new bar, not as a
  re-measurement to repeat.
- **Hosted CI, measured by the supervisor rather than by me:** `q5-upd1a-sec2-20261101` at `85ee077e`
  is `completed success` on Backend CI (run 217), against a trunk `03d580a` that is green on both
  `main` and `master` (runs 215, 216). So the backend half's gate is already judged; the docs commit
  on top of it changes `Fast_Fetch/**` and so feeds the same workflow, which is where its own
  22-test guard re-runs at no cost to this box.
- Mutation receipt, both couplings at once: delete the `_DIGEST` branch from `_validated` **and**
  delete the two `_INT_MAX` entries → `Ran 3 tests … FAILED (failures=3)`, including
  `AssertionError: 400 != 200` at `test_admin_panel.py:687` (the ceiling is load-bearing).
  Reversed by re-adding the hunks — not by `git checkout --` — and proved by `git status --short`
  and `git diff --stat` both empty against `85ee077`, then the same three tests `OK in 2.842s`.
- **Option A is uncompiled on this box.** No local Gradle at load1 > 0.5, so the hosted runner is
  the first thing that types these lines, and `testDebugUnitTest` is where `SyncContractTest`
  (+5 tests) and `DeviceTrialTest` (+1) actually run. Recorded as unrun. A `push` touching `App/**`
  starts that workflow; if it is red, that is the finding and it gets reported, not worked around.

## Commands UPD-1a / Option A left for the next lane

1. **UPD-1b** (client, gated by `testDebugUnitTest`): make `AppUpdate.from`
   (`viewmodel/HomeViewModel.kt`) refuse to surface a banner unless the URL is https-or-loopback,
   `ApiProvider.isSameOriginAsServer` (`ApiProvider.kt:107`, today used only by
   `EmbedWebViewModel.kt:77`) agrees, and `apk_update_sha256` is non-empty — plus a `versionCode`
   comparison so "newer" stops being a guess. Blocked on nothing but the ruling; the fields it
   needs exist as of `85ee077`.
2. Owner decision, unchanged: recovery of a lost key. Today the answer is "you cannot", and the
   gate makes that answer visible instead of silent.
3. Live-host delta not measured here: adding three `/admin` inputs shifts the dashboard's rendered
   byte size, so the `46,476 B` figure quoted in `AGENTS.md`, `docs/ADMIN_PANEL_ACCESS.md` and
   `docs/API_SURFACE_AUDIT.md` is now a stale measurement. It was a live-host read of a
   data-dependent page at 2026-10-29 05:47 — re-measure it on the host or convert the claim to the
   method, do not re-number it here.
