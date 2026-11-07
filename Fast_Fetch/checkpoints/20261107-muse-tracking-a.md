# Session 96 — Tracking A (aggregates-only): app usage block + consent gate (2026-11-07)

Tracking A was picked by the user 2026-11-07 18:26 PKT (aggregates-only first).
This session closes the app gap: the server engine (`usage_stats.py`) and the
panel v1 Usage page already existed; the app sent nothing. Nothing here is a
per-install timeline: rule 1 of `usage_stats.py` (one device row per bucket,
counters only) stands, and the server still cannot tell what any one person
watched.

## What the app now sends — only when the viewer says yes

- **First-run totals dialog** (`ui/screens/AnalyticsConsentDialog.kt`, new):
  "Anonymous usage totals". Plain-English draft text (totals only; never name,
  phone number, location, what you watch, what you search; no per-person
  record; changeable in Settings). Non-dismissible — both buttons are answers.
  The exact wording is the owner's to revise.
- **Consent store** (`ServerSettingsRepository`): `analyticsConsent` Flow
  (`"accepted"`/`"declined"`, null = never asked) + `saveAnalyticsConsent`;
  `installUuid()`/`ensureInstallUuid()` mint a random UUID (never a device id,
  IMEI, or SIM — impossible/forbidden since Android 10) **only** for a viewer
  who said yes.
- **Headers** (`ApiProvider.kt` interceptor): only when `Telemetry.consentAccepted`
  — `X-Install-Id`, `X-App-Version`, `X-Device-Class`, `X-Region`,
  `X-Audio-Lang`, `X-Subtitle-Lang`, `Accept-Language`. Declined/unasked viewers
  send byte-identical requests to before.
- **Usage block** (`AccountWire.kt`): `ProgressRequest.usage: Map<String, Int>?`
  (Gson omits nulls). `SyncAccountRepository.reportProgress` snapshots
  `Telemetry.takeUsageSnapshot()` before the call, attaches it when non-empty,
  and acknowledges only on `SyncAck.WRITTEN` — a failed or rejected write keeps
  the counters for the next attempt. Coins earned on progress, daily login, and
  share are counted (`coins_granted`) on the same ack path.
- **Counters** (`data/Telemetry.kt` + `data/UsageCounters.kt`, both new):
  `UsageCounters(store, gate)` — no-op unless the gate is true, unknown fields
  ignored, snapshot = known fields > 0, acknowledge subtracts exactly what was
  sent (later increments survive). Backed by SharedPreferences
  (`"radd_usage_counters"`, synchronous `commit()` — the crash handler and
  player callbacks cannot suspend), per-field cap 1,000,000.
  `Telemetry` holds the volatile snapshot (`consentAccepted`, install id,
  region/audio/subtitle/device class), `deviceClassFor(totalMemBytes)` —
  RAM-only (<3 GiB low, <6 GiB mid, else high; 0/unreadable → low; no model
  string — a model string is a fingerprint), `installCrashHandler()` (wraps the
  previous default handler, records "crashes", chains to it), and record helpers
  for playback attempts, buffer failures, playback errors, rewarded completions,
  coins granted.
- **Playback counting** (`PlaybackService.kt`): every initial load and failover
  hop counts a playback attempt; the auto-quality swap does not
  (`countAsAttempt = false`). `onPlayerError` counts first — network
  failed/timeout → buffer failure, anything else → playback error.
- **Rewarded VIP** (`VipViewModel.kt`): `grantRewardedVip` counts a rewarded
  completion only. **No coins are granted on it** — Monetag native-Android
  server verification is unconfirmed (postback documented for Telegram only;
  incentivized traffic prohibited without written confirmation).
- **Settings toggle** (`SettingsViewModel` + `SettingsScreen`): "Anonymous usage
  totals" card with a Switch right after the Disclaimer card. Flipping it
  refreshes the snapshot at once — off stops the next request's headers without
  a restart, on mints the install id and starts counting from that moment.
- **Wiring** (`RaddStreamApplication.kt`): `Telemetry.init(this)` +
  `installCrashHandler()` in `onCreate`, then a background refresh of the
  snapshot from DataStore (a throwing store leaves "not consented").
  (`MainActivity.kt`): renders the dialog when the answer is still null,
  after the disclaimer block.

## Server half

- `usage_stats.py`: `DIMS` gains `region`, `audio_lang`, `subtitle_lang`
  (seven dims). `usage_device` DDL + `ensure_schema()` migration add the three
  columns (`TEXT NOT NULL DEFAULT 'unknown'`, SQLite has no ADD COLUMN IF NOT
  EXISTS — old rows read 'unknown'; runs on every `_borrow`, so the LIVE
  `user_state.db` gains the columns on the first account call after deploy, no
  separate DB step). `attributes_from_headers()` reads them from `X-Region` /
  `X-Audio-Lang` / `X-Subtitle-Lang` through `clean_value` (odd values fold to
  `unknown`; geo still comes only from Accept-Language, never IP). `record_seen`
  upsert carries them with the same "keep known, never clobber with unknown"
  CASE pattern. `summary()` picks the new dims up automatically.
  `SCHEMA_VERSION` stays 1 (new columns have defaults; old rows remain readable).
- `test_usage_stats.py`: `AggregateOnlySchemaTests.DEVICE_COLUMNS` extended
  (the first failure was this set assertion — fixed by extending the expected
  set, not by weakening the rule-1 check); 6 new tests (region/languages from
  their own headers, never geo; odd values fold to unknown; stored + unknown
  never clobbers) + new `DimensionMigrationTests` (old-schema table gains
  columns with rows intact; migrated table accepts new dims; summary reports
  them). **100 tests OK (was 94). `test_redact` 76 OK.**

## App tests (new, JUnit4, JVM)

- `data/TelemetryCountersTest.kt`: the counters the app can send are exactly
  the server's `CLIENT_FIELDS`, read out of `Fast_Fetch/usage_stats.py` on disk
  (a server rename fails here, not silently); count lands/reads back; unknown
  field ignored; gate off → nothing recorded; acknowledge subtracts exactly
  what was sent; zero/negative ignored; `deviceClassFor` thresholds; two minted
  install ids differ and parse as UUIDs.
- `network/models/ProgressUsageWireTest.kt`: a progress write carries the usage
  block; no usage → no `"usage"` key on the wire; all eleven sent field names
  are in `Telemetry.USAGE_FIELDS`.

## Pre-push checks (vs base 2a558f84)

- Import diff: zero dropped, only additions (Telemetry ×7 files,
  AnalyticsConsentDialog ×1, ServerSettingsRepository + coroutines ×1);
  every new import is used.
- @Composable counts: SettingsScreen 11 → 11, MainActivity 0 → 0;
  AnalyticsConsentDialog is new with 1.
- `/*` vs `*/` balanced in all 14 Kotlin files; no literal `\"` artifacts.
- Full backend gate: 49/49 PASS (run-backend-gate.py).

## Deferred (follow-up session, not this one)

- Link-health report wiring: `POST /api/v2/links/{ref}/report` exists
  server-side (`api_v2.py:1679`, events played/stalled/failed/resolved);
  the app never calls it — `PlaybackRecovery.kt:14-17` marks the failover
  trail "future telemetry POST". Wire it next, under the same consent gate.
- `ad_requests` / `ads_filled` / `ad_impressions` / `ad_clicks` stay 0:
  no ad SDK yet. Honest — the server flags them `reported_by_client_pending`
  in `summary()` until an SDK exists.
- Consent text is a draft; the exact wording is the owner's to revise.
  Device class is RAM-only.

## CI / deploy

- Branch: `tracking-a-20261107` (cut from 2a558f84).
- Commit: `4b25a000` "Session 96: Tracking A — app usage block + consent gate".
- CI on 4b25a000: Backend 42388036597 **SUCCESS**; Android 42388036596
  **FAILED** at `:app:compileDebugKotlin` — one error, mine:
  `SyncAccountRepository.kt:742` called `earned.coinsGranted` on a nullable
  `CoinEarned?` after an Elvis check that does not smart-cast the receiver.
  The `reportShare` site compiled because `share?.granted == true` DOES
  smart-cast; the daily-login site did not. Fixed by hoisting the grant into
  a local val (`val granted = earned?.coinsGranted ?: 0`) — fix commit
  follows on the same branch; the verdict on it rides the next commit.
- CI on ee5e5a0f: Backend 42388723346 **SUCCESS**; Android 42388723476
  **FAILED** at `:app:testDebugUnitTest` — one test, mine:
  `BrandDriftTest.brandNameIsNeverHardcodedOutsideTheBrandFiles` — the new
  consent dialog hardcoded the literal "Radd Stream". Fixed by reading
  `Brand.name`; the test's own literal scan re-run locally reports zero
  offenders. Fix commit `83ff5bde` on the same branch.
- CI on 83ff5bde: Backend 42389771081 **SUCCESS**; Android 42389771075
  **SUCCESS** — branch fully green. APK **app-debug-267** (23,351,152 B).
- Deploy: gate deploy follows (backup set, checkout, public smoke,
  usage-migration check on live user_state.db).
