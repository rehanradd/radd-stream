# RaddRelay — payment SMS relay for the Radd Stream operator

RaddRelay is the tiny companion app that turns the operator's phone into the
payment-confirmation channel for JazzCash and EasyPaisa. It reads **only** the
merchant SMS sent by the two wallet shortcodes, extracts the transaction id and
amount, and posts them to the catalog server. Everything else on the phone — the
inbox, personal numbers, bank SMS — is untouched.

- Senders read: `8558` (JazzCash) and `3737` (EasyPaisa). Nothing else.
- Forwarded: `{"gateway": "8558" | "3737", "tid": "...", "amount": "..."}`.
- Never forwarded: the SMS body, the sender's number, the balance, the phone's
  contacts, or anything from another app.
- Target size: a few hundred KB. No AndroidX, no Compose, no third-party HTTP
  client, no analytics.

> **Reviewer entry point:** `CONSENT_AND_SCOPE.md` answers the permission,
> allow-list, body-handling and secret-storage questions in prose. CI lives in
> `.github/workflows/raddrelay-ci.yml` at the repository root (`RaddRelay/**`
> is a separate Gradle project, outside `App/**`).

> **Status, measured 2026-10-31:** the catalog backend does **not** implement
> `POST /api/v2/payment/sms-webhook` yet. `Fast_Fetch/accounts_api.py` exposes
> only the authenticated claim route `POST /api/v2/account/payment`
> (`{plan, method, tid}` from the app itself). This companion app is the client
> half; the webhook route, its `X-Merchant-Secret` check and its idempotency on
> `tid` still have to be added server-side before the relay can complete a
> payment in production. Until then the app will queue and retry (a 404 is
> treated as retryable), and the log will show `retry … HTTP 404`.

---

## 1. What happens to one SMS

1. `SmsReceiver` gets the `SMS_RECEIVED` broadcast. Multipart parts are joined
   per sender.
2. The sender is checked against the two shortcodes. Any other sender is dropped
   without parsing.
3. `SmsParser` applies the wallet's pattern:
   - JazzCash: `(?:Rs\.?|PKR)\s*([0-9,]+).*?TID:?\s*([0-9]{10,12})`
   - EasyPaisa: `(?:Rs\.?|PKR)\s*([0-9,]+).*?(?:Trx ID|TID):?\s*([0-9]{10,12})`
   - Both are case-insensitive, match across line breaks, and refuse to
     truncate a longer digit run into a "valid" TID.
4. `RelayService` de-duplicates by TID, appends to a persistent queue, and posts:

```http
POST {server}/api/v2/payment/sms-webhook
Content-Type: application/json
X-Merchant-Secret: <secret>
User-Agent: RaddRelay/1.0

{"gateway": "8558", "tid": "1234567890", "amount": 1500}
```

`amount` is sent as a JSON number when it is all digits (commas are stripped
before sending), otherwise as a string.

---

## 2. Server contract the app expects

| Response | App behaviour |
|---|---|
| `2xx` | TID marked relayed, removed from the queue |
| `409` | Treated as already recorded (idempotent), removed |
| `401` / `403` | **Dropped** and logged as `REJECTED … merchant secret rejected` — a wrong secret is a configuration error, retrying hides it |
| `408` / `429` / `5xx` / no network | Kept, retried with backoff (30 s → 2 min → 10 min) |
| other `4xx` | Dropped and logged as `REJECTED` |

The server should treat `tid` as the idempotency key. RaddRelay already refuses
to send the same TID twice while it is in the queue or within its last 500
relayed TIDs.

---

## 3. Install and configure

1. Build or install the APK (see §5). It is a normal sideloaded app; there is no
   Play Store distribution.
2. Open **RaddRelay**.
3. Set **Server URL** (e.g. `http://92.4.95.252`) and the **Merchant secret**
   the server operator generated. Tap **Save**.
4. Tap **Test connection**. It performs a read-only `GET /api/v1/stats` — a
   `HTTP 200` proves the URL and the network; it does not test the secret.
5. Tap **Start relay** and grant:
   - **SMS** — required, otherwise no payment is ever seen;
   - **Notifications** (Android 13+) — required for the persistent status
     notification that keeps the service alive.
6. Confirm the ongoing notification reads
   **“RaddRelay Active - Listening for JazzCash/EasyPaisa”**.

### Keep it alive

Foreground services are the supported way to stay running, but aggressive
battery managers still kill them. On the operator's phone:

- Settings → Apps → RaddRelay → Battery → **Unrestricted** (Samsung: remove from
  “Sleeping apps”; Xiaomi: Autostart **on** and “No restrictions”).
- Do not “force stop” the app; that cancels the relay until it is started again.
- After a reboot the service restarts by itself **if it was running when the
  phone went down** (the enabled flag is persisted).

---

## 4. Operating it

The main screen shows:

- **Service** — running/stopped, queued count, whether a secret is set;
- **Server** — the configured URL;
- **Relay log** — every queued, relayed, retried and rejected TID with a
  timestamp (last 300 lines, in memory).

Failures are visible, not silent: a wrong secret shows `REJECTED`, a dead
network shows `offline — N queued`, and the queue survives a process restart.

### Replaying a test message without sending money

Debug builds accept an injected SMS through the receiver:

```bash
adb shell am broadcast -n com.raddstream.relay/.SmsReceiver \
  -a com.raddstream.relay.DEBUG_SMS \
  --es sender 8558 \
  --es body "Rs.1 received. TID: 1234567890."
```

Release builds ignore the action. Note that a debug injection **is relayed like
a real payment** — point the app at a staging server, or use a TID the operator
will delete afterwards.

---

## 5. Build and test

The project pins the same toolchain as `App/` (AGP 8.5.2, Kotlin 2.0.0,
compileSdk 34, minSdk 26).

```bash
cd RaddRelay

# One-time: create the wrapper if this checkout does not have one
gradle wrapper --gradle-version 8.7

./gradlew :app:assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:testDebugUnitTest      # SmsParserTest — 12 tests, no device needed
```

On the Oracle box no Android SDK is installed, so both commands belong on a
machine with the Android toolchain (or in CI). The parser suite is plain JVM
JUnit and needs no emulator.

---

## 6. Security notes

- The merchant secret is stored in the app's private `SharedPreferences`; it is
  readable on a rooted phone. Treat it like a password and rotate it if the
  phone is lost.
- The server is HTTP-only today, and the manifest enables cleartext traffic for
  that reason. On hostile networks the secret and TIDs are visible on the wire;
  if HTTPS becomes available, point the URL at `https://` and remove
  `android:usesCleartextTraffic` from the manifest.
- SMS bodies are parsed in memory and discarded. Nothing is written to disk
  except the TID/amount/gateway of a pending or relayed payment.
- `READ_SMS` is not requested. The app never opens the inbox.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No notification after Start | Notifications permission denied (Android 13+). Grant it in Settings → Apps → RaddRelay → Notifications. |
| Payments never appear in the log | SMS permission not granted, or the SMS came from a different sender id (check the phone's message details; only `8558`/`3737` are read). |
| `not configured — N queued` | Server URL or merchant secret is empty. |
| `retry … HTTP 404` | The webhook route is not implemented on the server yet (see the status note at the top). |
| `REJECTED … merchant secret rejected` | Secret mismatch; regenerate/agree the secret with the server operator. |
| App stops after some hours | Battery optimisation. Set the app to Unrestricted and re-start the relay. |
| `service start refused (…NotAllowedException)` in the log | Android 12+ refused a background foreground-service start (the service had been killed). The TID is already queued; open the app (or wait for the next start) and it is sent. Keep the relay running to avoid it. |

---

## 8. Provenance

Built 2026-10-31 for the Radd Stream fleet under task `RADDRELAY-COMPANION`.
Parser tests were written but **not executed** in this session: the box was under
a load hold (no builds during it). Run `./gradlew :app:testDebugUnitTest` before
shipping.
