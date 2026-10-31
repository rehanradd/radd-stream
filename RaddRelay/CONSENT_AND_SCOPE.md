# RaddRelay — Consent, Permissions, and Scope

Written for the supervisor's review before any code judgement (Q2-CENSUS-CI-AND-RELAY, Job B).
It answers, in order: what the app is allowed to read, what it will never read, what leaves the
phone, what happens to anything else, how the operator consents, and where the merchant secret
lives. Where the implementation differs from the brief, the difference is stated rather than
smoothed over.

## 1. What the app does

It is a foreground service that listens for incoming payment SMS from **two short-codes only**
(JazzCash `8558`, EasyPaisa `3737`), extracts the amount and the transaction id (TID), and POSTs
`{"gateway", "tid", "amount"}` to `{server}/api/v2/payment/sms-webhook` with an
`X-Merchant-Secret` header. It is a one-way notifier: it does not reply to SMS, does not send SMS,
does not read the inbox, and has no UI that displays message bodies.

## 2. Permissions declared, and why each one

From `app/src/main/AndroidManifest.xml`:

| Permission | Why it exists | What it does NOT grant |
|---|---|---|
| `RECEIVE_SMS` | Receive the `SMS_RECEIVED` broadcast for incoming messages | **`READ_SMS` is deliberately absent** — the app cannot open the inbox or read any historical message |
| `INTERNET` | POST the payment event to the configured server | — |
| `ACCESS_NETWORK_STATE` | The offline queue drains when connectivity returns | — |
| `POST_NOTIFICATIONS` | Android 13+ requires it before the persistent "relay active" notification can be shown | — |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC` | Run the relay outside the app with a visible notification (Android 14 requires the typed permission) | — |
| `RECEIVE_BOOT_COMPLETED` | Restart the relay after a reboot **only if the operator had enabled it** | — |

Not requested: `READ_SMS`, `SEND_SMS`, `READ_PHONE_STATE`, `READ_CONTACTS`, `READ_CALL_LOG`,
storage, camera, microphone, location.

`SmsReceiver` is protected by `android:permission="android.permission.BROADCAST_SMS"`, which only
the telephony stack holds — another app cannot feed it a synthetic "payment". `BootReceiver` only
acts on the system-only `BOOT_COMPLETED` broadcast.

## 3. Sender allow-list — exact, not fuzzy

`SmsParser.gatewayFor(sender)` trims the sender and compares **exact equality** against `"8558"`
and `"3737"`. There is no substring, prefix, or "contains JazzCash" test. A personal number, a bank
alert, a saved contact named "JazzCash", or `8558-1` is rejected before the body is looked at. The
allow-list is the only path into the parser.

## 4. What is actually read

`SMS_RECEIVED` is delivered to the receiver for every incoming SMS — that is the only SMS API that
does not require `READ_SMS`, and it is how Android works. The app's handling is what makes the
scope small:

- every multipart part whose sender is **not** exactly 8558 or 3737 is discarded immediately;
- only parts from the two senders are concatenated (multipart bodies split amount and TID);
- the joined body must match one of the two **anchored** patterns or nothing is produced;
- the matched body is never retained after `parse()` returns.

There is no inbox scan, no cursor over `content://sms`, and no historical message access.

## 5. What leaves the phone — and what never does

The POST body is exactly:

```json
{"gateway": "8558", "tid": "123456789012", "amount": 1500}
```

Plus the `X-Merchant-Secret` header. **The message body is never sent.** If the server contract
needs the raw text, that is a change the supervisor must ask for — the brief's payload is
`{gateway, tid, amount}` and that is what is implemented.

| Data | Sent? | Logged? | Persisted on device? |
|---|---|---|---|
| Message body | **no** | **no** | **no** |
| Sender number | no (mapped to `gateway`) | as `gateway` label | no |
| TID | yes | yes (in the in-memory log) | yes — active queue, dead-letter list, relayed-TID set (capped at 500) |
| Amount | yes | yes | yes — while queued or dead-lettered |
| Merchant secret | as a header only | **never** | yes — private SharedPreferences, see §8 |

The in-memory relay log (`RelayLog`) holds up to 300 lines of `queued/skip/rejected` events with
gateway, TID and amount; it lives in RAM, is refreshed on screen once a second, and dies with the
process. There is no file log and no `Logcat` write of a body or a secret.

## 6. A body that is not a payment SMS

If the sender is 8558 or 3737 but the text does not match the payment pattern (promo, OTP,
balance warning, a wording change on the bank's side), `SmsParser.parse` returns `null`:

- nothing is queued;
- nothing is POSTed;
- nothing is written to the relay log (there is no entry to write);
- the operator sees no notification change.

There is no "looks like money" fallback. The two patterns are the whole extraction rule, so a
wording change produces silence, not a guessed TID. That is deliberate: a wrong TID is worse than
a missed one, because the server treats a re-sent TID as idempotent but a made-up TID as a new
payment.

When the server refuses a payment in a way retrying cannot fix (most often a wrong secret, or a
payload the ledger will not accept), the item moves to a **dead-letter** list rather than being
deleted: still on the device, counted on the status line, visible in the log, and replayable from
the app. The server dedupes on gateway + TID + amount, so replaying can only ever help; deleting
would destroy the only record that the money arrived.

## 7. Consent and control are explicit

- The app is **sideloaded by the owner** of the phone; it is not in any store.
- Nothing runs until the operator presses **Start relay**: the service is not started by install,
  and `BootReceiver` only restarts it when the operator had set the enabled flag.
- While running, a persistent notification reads **"RaddRelay Active - Listening for
  JazzCash/EasyPaisa"**. Android does not let it be dismissed.
- **Stop relay** ends the service and clears the enabled flag.
- Uninstalling removes the private preferences: queue, relayed-TID set, server URL, secret.

## 8. The merchant secret

- **Never in the APK.** No `BuildConfig` field, no asset, no hardcoded string; the app has no
  secret until the operator types one.
- **Never printed.** It is not in the relay log, not in an exception message, and not in any
  `Log.*` call.
- **Where it is kept:** the app's private `SharedPreferences` file (`raddrelay`), readable only by
  this app's UID (`MODE_PRIVATE`), in the device's credential-encrypted storage.

This is the honest difference from the brief's wording ("`RADD_MERCHANT_SECRET` as an environment
value on the operator's own device"): Android has no environment variables for an installed app,
and compiling the value in would put it in the APK, which the same sentence forbids. The
equivalent guarantee — value comes from the operator's device, not from the build — is met; the
value does persist on the device so the relay survives a reboot. If the supervisor prefers
**no persistence at all** (re-enter on every Start, or wrap it in the Android Keystore), say so and
it is a small change in `RelayPrefs` / `MainActivity`.

## 9. Limits and open points for the supervisor

1. **The webhook exists on trunk.** `viewer.py:3406 _merchant_relay`, landed as
   `0e5ae28`, is mounted on the public POST chain and calls
   `payments.verify_merchant_header` before reading the body. `payments.WEBHOOK_PATH` and
   `RelayService.WEBHOOK_PATH` are the **same literal** `/api/v2/payment/sms-webhook`; quote that
   equality wherever either is edited so the two cannot drift.
2. **The default URL is the tunnel**, `http://127.0.0.1:8099`, because the route answers on the
   loopback ports only (nginx `^~ /api/` 403s the rest by design). A public-IP base URL is wrong
   until the host has TLS. `usesCleartextTraffic="true"` therefore means "the local end of an SSH
   tunnel is HTTP", not "the secret crosses the public internet".
3. **Cleartext + device compromise.** Inside the tunnel nothing is clear on the wire; anyone with
   the unlocked phone can still read the secret from private storage. The secret's power is limited
   to posting payment events; a per-device-revocable secret is the right mitigation if the server
   grows that feature.
4. **Use the in-app "Send test" button, not adb.** The button POSTs an intentionally invalid body
   to the real webhook with the real secret header, so 401 / 403 / 404 / 4xx-from-handler each name
   a distinct cause, and an invalid body can never be recorded as a payment. The debug `adb`
   broadcast route is expected to fail: the receiver requires `BROADCAST_SMS`, which the shell UID
   does not hold (not run on a device; not claimed to work).
5. **`BootReceiver` is exported with no permission — deliberately.** It is bounded by two checks on
   the action itself: it returns unless the intent is exactly `BOOT_COMPLETED` and the operator had
   enabled the relay. `BOOT_COMPLETED` is a system-protected broadcast, so no ordinary app can
   spoof it. If a future change adds any other action to that receiver, the bound is gone.
6. **What has and has not been executed.** `raddrelay-ci.yml` run 41153481156 executed the Gradle
   step, so `SmsParserTest`'s 12 tests have run on the runner. `RelayVerdictTest` (9 tests, the
   status→verdict table and its positive control) was added after that run and has not executed
   locally — the box was under a load freeze — so its first CI run is its execution record.
