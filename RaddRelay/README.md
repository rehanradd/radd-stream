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

> **Server contract, measured 2026-10-31:** the route now exists on trunk
> (`viewer.py:3406` `_merchant_relay`, landed `0e5ae28`; mounted on the public
> POST chain after `payments.verify_merchant_header`). `payments.WEBHOOK_PATH`
> and `RelayService.WEBHOOK_PATH` are the **same literal**
> `/api/v2/payment/sms-webhook` — if either line moves, they must move together.
> The route answers on the **loopback** ports only: nginx allow-lists
> `/api/v2/account` and `^~ /api/` answers 403 for everything else, **by design**
> (a static merchant secret must not cross a plain-HTTP public edge). The
> sanctioned transport is the operator phone's outbound SSH tunnel:
>
> ```bash
> autossh -M 0 -N -L 127.0.0.1:8099:127.0.0.1:8080 ubuntu@<host>
> ```
>
> so the app's default URL is `http://127.0.0.1:8099`. **A public-IP base URL is
> wrong** until the host has TLS: it reaches nginx, which 403s the route.

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
| `401` | **Dead-lettered** (kept, visible, replayable) and logged — this is the only status that means the secret was checked and rejected |
| `403` | **Retried**, logged as *a proxy refused the route* — a proxy never checked the credential, so this is a URL/transport problem, not a secret problem |
| `404` | Retried — the route is not deployed on whatever answered |
| `408` / `429` / `5xx` / no network | Kept, retried with backoff (30 s → 2 min → 10 min) |
| other `4xx` | **Dead-lettered** (kept, replayable) and logged — the request itself is wrong (malformed payload, bad TID shape) |

`Reject` never deletes a payment. The item moves to a separate **dead-letter**
list (capped at 100, newest first), counted on the status line, shown in the
log, and moved back onto the queue by **Replay dead letter**. The server is
replay-safe (it dedupes on gateway + TID + amount), so keeping a refused item
can only help; deleting it would destroy the only record that money arrived.

The server treats `tid` as the idempotency key. RaddRelay already refuses to
send the same TID twice while it is queued, dead-lettered, or within its last
500 relayed TIDs.

---

## 3. Install and configure

1. Build or install the APK (see §5). It is a normal sideloaded app; there is no
   Play Store distribution.
2. Open **RaddRelay**.
3. Set **Server URL** (default `http://127.0.0.1:8099`, the tunnel endpoint) and
   the **Merchant secret** the server operator generated. Tap **Save**.
4. Tap **Send test**. It POSTs an intentionally invalid body to the real
   webhook with the real secret header. The status tells you which cause you
   have: `401` = wrong secret, `403` = a proxy refused the route (the URL is
   the public edge, not the tunnel), `404` = route not deployed, `4xx` from the
   handler = route reached and secret accepted. An invalid body can never be
   recorded as a payment, and the test never touches the queue.
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

- **Service** — running/stopped, queued count, dead-letter count, whether a
  secret is set;
- **Server** — the configured URL;
- **Relay log** — every queued, relayed, retried, dead-lettered and replayed
  TID with a timestamp (last 300 lines, in memory).
- **Replay dead letter** — moves refused payments back onto the queue, for
  after the cause (secret, URL, payload) is fixed.

Failures are visible, not silent: a wrong secret shows `DEAD … HTTP 401`, a
public-edge URL shows `retry … HTTP 403 — a proxy refused the route`, a dead
network shows `offline — N queued`, and the queue survives a process restart.

### Exercising the path without sending money

Use **Send test** (above): it hits the real URL and secret and cannot record a
payment.

Debug builds additionally accept an injected SMS through the receiver:

```bash
adb shell am broadcast -n com.raddstream.relay/.SmsReceiver \
  -a com.raddstream.relay.DEBUG_SMS \
  --es sender 8558 \
  --es body "Rs.1 received. TID: 1234567890."
```

**Expect this to fail.** The receiver requires `android.permission.BROADCAST_SMS`
(only the telephony stack holds it), so the adb shell is very likely refused —
use the in-app button instead. If it does get through, the injection is relayed
like a real payment.

---

## 5. Build and test

The project pins the same toolchain as `App/` (AGP 8.5.2, Kotlin 2.0.0,
compileSdk 34, minSdk 26).

```bash
cd RaddRelay

# One-time: create the wrapper if this checkout does not have one
gradle wrapper --gradle-version 8.7

./gradlew :app:assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:testDebugUnitTest      # SmsParserTest (12) + RelayVerdictTest (9)
```

On the Oracle box no Android SDK is installed, so both commands belong on a
machine with the Android toolchain (or in CI). The parser suite is plain JVM
JUnit and needs no emulator.

---

## 6. Security notes

- The merchant secret is stored in the app's private `SharedPreferences`; it is
  readable on a rooted phone. Treat it like a password and rotate it if the
  phone is lost.
- The server is HTTP-only today, and the manifest enables cleartext traffic
  because the **default URL is the local end of an SSH tunnel**
  (`127.0.0.1:8099`). Inside the tunnel nothing is on the wire in clear; a
  public-IP base URL would put the secret and TIDs on the wire, which is why it
  is not the default and is refused by the edge anyway. If HTTPS becomes
  available on the host, point the URL at `https://` and remove
  `android:usesCleartextTraffic`.
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
| `retry … HTTP 404` | The route is not deployed on whatever answered — check that the tunnel is up and points at the server's loopback port. |
| `retry … HTTP 403 — a proxy refused the route` | The URL is the **public edge**, which 403s this route by design. Use the tunnel endpoint (`http://127.0.0.1:8099`). This is not a secret problem. |
| `DEAD … HTTP 401` | Secret mismatch, checked before the body was read. Fix the secret, then **Replay dead letter**. |
| `DEAD … HTTP 4xx` (not 401) | The payload was refused (bad TID shape or amount). The item is kept; replay after fixing the app. |
| App stops after some hours | Battery optimisation. Set the app to Unrestricted and re-start the relay. |
| `service start refused (…NotAllowedException)` in the log | Android 12+ refused a background foreground-service start (the service had been killed). The TID is already queued; open the app (or wait for the next start) and it is sent. Keep the relay running to avoid it. |

---

## 8. Provenance

Built 2026-10-31 for the Radd Stream fleet under task `RADDRELAY-COMPANION`.
The first hosted run (`raddrelay-ci.yml`, run 41153481156) executed the Gradle
step, so `SmsParserTest`'s 12 tests have run. `RelayVerdictTest` (9 tests) was
added after that run and has **not** executed locally — the box was under a load
freeze — so its first CI run is its execution record.
