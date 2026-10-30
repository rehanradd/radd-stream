# Previous checkpoint — 2026-10-27 (VIP claim is a real server round-trip)

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## Previous checkpoint — 2026-10-27 (VIP claim is a real server round-trip)

- **Goal:** close the last fake in the monetization path — the app stored a transaction ID
  locally and claimed it had been kept, while `Fast_Fetch/payments.py` already served a real
  ledger. Wire the client to it, read the entitlement back, and gate something honest on it.
- **Done here (app):**
  1. **Real payment call.** `POST api/v2/account/payment` with the bearer sync key and body
     `{"plan","method","tid"}` (`RaddStreamApi.submitVipTid`, `SyncAccountRepository.submitPayment`).
     Named for the screen's verb; the doc on it records that **`/api/v1/vip/submit-tid` does not
     exist** and that `phone` is not collected, so nobody re-invents either.
  2. **Entitlement read-back.** `GET api/v2/account/entitlement` → `{vip, vip_until, pending}`,
     refreshed at launch, on every "Sync now", and on a 6-hour clock from the Application;
     throttled to 60 s, keeps the last good answer on a transient failure, clears on sign-out.
     The type is `AccountEntitlement`, because `CatalogV2.kt:216` already owns `Entitlement`.
  3. **No local VIP minting.** `VipViewModel` prices plans/channels in the server's own spelling,
     posts when signed in, keeps the draft on the device when not, and re-files a kept draft
     once an account exists. Refusal text is ours (`VipSubmission.outcome`), never the server's
     `detail`.
  4. **Honest gating.** Entitlement or a rewarded pass silences `AdSlotPolicy` and the
     `DetailScreen` sponsor card. **No quality/resolution gate was invented** — remote config
     publishes no such flag.
  5. **Three false UI claims corrected** ("this server has no payment collection endpoint",
     the reference is "not sent anywhere automatically", and the privacy footnote).
  6. **Drift pinned by `VipWireContractTest`**, which reads `payments.py` and `redact.py` off
     disk and pins plan names, plan days, fallback prices, channel names and both projection
     field sets, plus that `tid` appears in neither projection.
- **Also landed in the same tree (worker session, task P-A-05):** `RemoteConfigWatcher` polls
  `/api/v1/app/remote-config` every 5 min and `MainActivity` shows a full-screen
  `MaintenanceScreen`; `VipRemoteConfig` now decodes `feature_flags`, `ads`,
  `link_shorteners`. Reviewed and sound: the flags the server does *not* send (`sharing`,
  `search`) default to `true`, so an absent key cannot switch a real feature off.
- **Checks run and exact result:** `:app:compileDebugKotlin :app:testDebugUnitTest` →
  BUILD SUCCESSFUL, 410 tests / 50 suites / 0 failures (all 50 result XMLs newer than the
  run). Backend unchanged this round; `python3 -S Fast_Fetch/test_database.py` was 64 OK and
  `test_vidout.py` 6 OK at the last backend milestone.
- **Operational finding — this is the one to remember:** concurrent Gradle invocations in
  `App/` on this 1-vCPU host corrupt each other's kapt output (`BUILD FAILED`, zero compile
  errors, `Unable to delete directory .../generated/source/kapt`). Builds now go through a
  queue that waits for other agents and holds an exclusive lock, and `App/AGENTS.md` §1a
  replaces the stale "never run gradlew locally" rule with the real constraint. A file-reading
  drift test can also fail purely from a source file being written mid-test — re-run before
  believing it.
- **Known limitations:** no device or emulator, so the posted claim, the operator approval and
  the entitlement countdown are compile/unit-verified only. `PosterCardProvenanceTest` still
  self-skips (no aarch64 Robolectric runtime; needs an x86_64 runner, and Actions is disabled
  at the account level). The new maintenance overlay has no escape hatch to Settings — tracked
  as a follow-up.
- **Next concrete action:** commit this milestone once a build runs with no overlapping agent
  build; then the keep-chip (`DownloadsScreen` "In-app keeps" still plays through the network
  handle instead of the bytes already on the device).

