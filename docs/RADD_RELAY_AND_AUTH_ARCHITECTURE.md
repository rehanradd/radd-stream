# RaddRelay + Zero-Friction Auth — the recovered spec, and what is wrong with it

**Provenance, stated before anything else.** The Antigravity lane (`agy`) wrote this plan at
**21:00** on 2026-10-29 and was logged out at **21:49:47** without ever answering the owner's last
question. The only copy lived outside the repository, in that tool's private scratch directory:
`/home/ubuntu/.gemini/antigravity-cli/brain/22616d46-a349-499a-9d4f-3406625c808d/radd_relay_and_auth_architecture.md`,
9,450 bytes, `mtime Oct 29 21:00`. I found it by reading that tool's own conversation database
(`history.jsonl` stores **only** the owner's messages — all 525 records are `display`/`timestamp`/
`workspace`/`conversationId`, no assistant turns — so the plan itself had to come from the
`steps.step_payload` blobs in `conversations/<id>.db`, and the artifact from the `brain/` dir).

It is reproduced in **Appendix A verbatim**, because the owner's instruction at 20:59 was
*"tell them about out this complete plan our login flow make sure **do ot miss any single thing**"*.
Nothing in Appendix A is edited. Everything I disagree with is below it, in my own voice, so the
audit trail keeps both.

**Read the review before building anything.** Two parts of the spec cannot run at all on this host
as written, and one part would make the payment rail approve itself.

---

## 1. Rulings, with the measurement that forces each one

### R1 — The webhook route in the spec is unreachable, and opening it is the wrong fix

The spec's transport is `POST https://<oracle-host>/api/v2/payment/sms-webhook`. Measured on
`/etc/nginx/sites-available/radd-stream` right now:

| Route | nginx answer | Line |
|---|---|---|
| `/api/v2/account*` | proxied, `limit_req burst=30 nodelay` | `:69` |
| `/api/v2/payment/sms-webhook` | **403** — falls into `location ^~ /api/ { return 403; }` | `:108` |

So as written, RaddRelay posts into a 403 and the owner would wait for VIP forever — the exact
5-minute-anxiety the whole feature exists to remove. **The fix is not to add a public `location`
block for it.** See R2.

### R2 — No TLS means the spec's `X-Merchant-Secret` crosses the network in clear text

This host is plain HTTP on port 80 (`ORACLE_DEPLOYMENT.md`; nginx listens on 80 only). A static
long-lived secret in a header over cleartext, sent from the operator's own phone over Pakistani
mobile data, is sniffable by anyone on the path — and whoever holds it can approve their own VIP
indefinitely, on our bill. The spec even writes `https://` in the example; there is no HTTPS
listener to satisfy it.

**Ruled:** RaddRelay's transport is an **outbound SSH tunnel from the operator phone**, not a public
HTTP endpoint:

```
autossh -M 0 -N -o ServerAliveInterval=30 \
  -L 127.0.0.1:8099:127.0.0.1:8080 ubuntu@92.4.95.252
# relay POSTs to http://127.0.0.1:8099/api/v2/payment/sms-webhook
```

Cost: **$0** (port 22 is already open and key-authenticated; the phone is the *initiator*, so the
host needs no new listener and no new firewall rule). SSH gives us encryption *and* device
authentication in one move, which is strictly better than a bearer secret over cleartext. WireGuard
is the alternative if we ever want it phone-less. `/api/v2/payment/*` **stays 403 at the public
edge**. That is not a regression; it is the control.

### R3 — Never approve on the relay's parsed amount; the plan is chosen server-side

The spec approves by matching a TID and crediting the plan. The existing code already refuses to let
an amount decide a plan — `payments.py:515-527`, `approve_payment`, whose docstring says the credit
is `days(plan)` and *"The plan's length is fixed by the plan, not by the row's amount … An unknown
plan raises rather than defaulting to 30 days."* Keep that invariant and extend it: the relay's
`amount` field is **evidence, never authority**. A customer who pays ₨20 against a ₨250 claim must
leave the row `pending` with a mismatch note; ₨20 is a real payment and the operator should see it.

**Also settled here, because the two documents disagree:** the fleet plan prices Monthly VIP at
**₨250** (`docs/MONETIZATION_AND_FLEET_PLAN.md`) while `payments.py:84-87` carries
`PLAN_DEFAULTS = {"vip_monthly": (200, 30), ...}` and the spec's worked example is *"Rs. 200"*.
**₨250 is authoritative**; the `200` default and the example are both stale. The relay's amount→plan
mapping must read the admin-configured price table at request time, never a literal. No production
data write is needed or authorised for this — it is a defaults-and-docs correction.

### R4 — Approving on TID alone is a brute-force path; require the triple, and make it idempotent

The spec's `verified_incoming_tids(tid, amount, gateway, received_at)` caches incoming SMS rows and
activates VIP when a later claim matches the TID. The regexes capture
`TID:?\s*([0-9]{10,12})` — a 10-to-12-digit numeric identifier, i.e. a space as small as 10¹⁰. If
matching is on TID alone, anything that can reach the endpoint can *guess* a valid TID for someone
else's pending payment and take their credit. Required before this ships, none optional:

1. Match on **(gateway, tid, expected_amount, payer phone suffix)** against a row that is
   `pending` — never against "any row", never against a row already `approved`.
2. **`UNIQUE(gateway, tid)`** so a replayed SMS cannot double-credit (the relay retries its offline
   queue by design, and `approve_payment` credits `max(now, vip_until) + days`, so a replay silently
   extends a membership).
3. A shared-secret comparison that does not leak length or timing (`hmac.compare_digest`), a
   timestamp + nonce window on the envelope, and a per-tunnel request bucket.
4. Every acceptance written to an append-only audit row: `{ts, tid, gateway, amount, payment_id,
   reviewer='radd-relay', match_basis}`. `reviewer` is a real column
   (`approve_payment(..., reviewer="")`), so operator-vs-relay attribution is free — record it.

### R5 — It is not a "Hardware Lock", and calling it one would be a claim this code cannot keep

The fingerprint is `SHA-256(ANDROID_ID | Build.HARDWARE | Build.FINGERPRINT)` over **client-reported
strings**. Two measured consequences:

- `Build.FINGERPRINT` **changes on every OTA update**. A legitimate user who updates Android looks
  like a brand-new device and gets a fresh 3-day grant (the abuse the owner asked me to prevent) —
  or, if the old row is kept, loses their trial for updating their phone.
- On a rooted device all three inputs are spoofable, and an emulator hands out fresh values for
  free. There is no attestation anywhere in this design — `Play Integrity`,
  `SafetyNet`, `attestation` return **zero hits** across `App/app/src` (measured, and recorded in
  `docs/IDENTITY_AND_TRIAL_ABUSE.md` §3).

**Ruled:** build it — it is a real deterrent against the common case, which is a viewer reinstalling
rather than an adversary with a rooted test rig — but name it honestly. In code, docs and UI strings
it is a **trial gate**, never "hardware-locked"/"un-farmable". Add `trial_gate TEXT NOT NULL`
(`'android_id_ota_vulnerable'` today, `'play_integrity'` when the app ships through Play) to
`device_trials`, so the admin panel can show *how many* grants came through the weak gate instead of
us guessing. Upgrading that gate is task #24's sibling, not a blocker for this one.

### R6 — Level 2 as specified reintroduces the exact defect we are fixing, only weaker

`sync_key = base64url(SHA256("radd-stream-v2" + phone + pin))` is one **unsalted** digest over a
**10⁴** key space. The current phone-derived key (`SyncContract.kt:136,208-221`) is already the
documented defect — "knowing somebody's mobile number is sufficient to open their library"
(`docs/IDENTITY_AND_TRIAL_ABUSE.md` §1) — and its space is 10⁹ enumerable offline. The PIN scheme is
the **same class** with a **thousand times less** entropy: one stolen `user_state.db` is crackable in
milliseconds, and then every linked account — including the VIP they paid for — is open.

**Ruled:** keep the UX (name + phone + 4-digit PIN, +1 day) and change the crypto:

- Phone + PIN is a **verification factor**, never credential material. On profile-link the server
  **mints a random ≥32-byte sync key** and returns it once; the client stores it exactly as the
  anonymous key is stored today.
- PIN is stored as `hashlib.pbkdf2_hmac('sha256', pin, salt, ≥120_000)` with a per-account random
  salt. (This is what I already told the qoder3 lane at 22:1x; the spec predates that ruling.)
- `AttemptTracker` (`accounts.py:658-779`) guards the verify path. The cross-device recovery step
  additionally needs a **per-phone** budget that does not exist yet: `BUCKET_LIMITS`
  (`redact.py:1108-1112`) is documented in-file as a "Token bucket **per client IP**", and its
  `account` entry is `(30, 60.0)`. So the limiter we have throttles the attacker's *address*, not the
  *account being attacked* — and the owner's own rollout (many viewers behind one carrier NAT, one
  adversary with many addresses) breaks it in both directions. Per-phone counts are new work, not a
  config change.

### R7 — The owner chose contact-data storage; here is the boundary I am drawing around it

The owner said, verbatim, *"we will store if user enter name phone pin etc. and save direct phone
number if we need to conatct user so we can"* (20:34) and *"Option 2 so we have complete trust"*
(20:59). That decision stands — it is the owner's, and the purpose (operator WhatsApp/support
contact) is legitimate and ours.

What follows from it, and is mine to decide:

- **Name and phone are written only on a volunteered, linked account.** Never on a silent anonymous
  mint. The anonymous population stays an **unjoined aggregate** (counts, cohort retention, ad
  cadence) so that the admin panel's user/device tracking — which the owner asked for — never turns
  "install" into "identified person".
- **PIN is never contactable data**: PBKDF2 only, per R6, and no admin surface may render it.
- **A delete path is mandatory, not optional.** The owner's stated rollout is
  Pakistan → India → Asia → Europe → world. Retaining a phone number with no deletion route is not
  defensible in the later stages of that ladder, so `admin_panel` gets "wipe contact info for account
  N" from day one (it keeps the ledger row and NULLs `name`/`phone`/`pin_hash`). Cheap now, ugly to
  retrofit.
- Reading SMS on the **operator's own phone**, filtered to `8558`/`3737`, is the owner's own device
  and own messages — that is what "complete trust" means here, and it is not customer surveillance.
  Two consequences I am applying: RaddRelay is **never published to Play** (sideloaded internal
  tool; Play's SMS policy exists for exactly this and we do not need the fight), and the whitelist is
  enforced in the `onReceive` gate, not just the regex, so a personal SMS cannot be relayed even if a
  parser is widened later.

### R8 — `/api/v2/account*` is already public, so a silent-mint endpoint needs its bounds on day one

Because `nginx:69` proxies the whole `/api/v2/account` prefix, adding `/api/v2/account/anonymous`
makes it internet-reachable with no config change. That is desirable (the owner wants zero-friction)
and dangerous in the same breath: an unbounded `INSERT` endpoint on 1 vCPU, in front of the same
process that was **OOM-killed at 19:14:31 today** (task #19), with a 30-burst limiter as its only
brake. And the accounting consequence: every scripted mint becomes a "user" in the very panel the
owner wants for tracking.

**Ruled:** anonymous mints are **provisional** rows — `account_kind='anonymous'`,
`activated_at NULL` until the first real read/write, plus a `device_id` gate per R5 — and the admin
panel reports `activated` separately from `minted`. GC of never-activated rows after 30 days is a
configured flag (`anonymous_provisional_ttl_days`), not a midnight cron nobody owns.

### R9 — The admin-panel settings the owner asked for at 21:28 (the spec never lists them)

The owner: *"make sure add all setting to admin panle like connecting with our RaddRelay.apk and also
all new setting to to set trial free vip rewards onm account create user coins control user tracking
etc."* Appendix A has **no** admin-panel section, so this is the gap the spec missed. Required fields
added to `admin_panel.MONETIZATION_FIELDS` (17 today, `:924-953` → `app_remote_config`):

| New field | Default | Controls |
|---|---|---|
| `trial_days_on_install` | 3 | the install grant |
| `trial_days_on_profile_link` | 1 | the +1 day reward |
| `anonymous_mint_enabled` | 1 | R8's kill switch |
| `anonymous_provisional_ttl_days` | 30 | provisional-row GC |
| `trial_gate_mode` | `android_id` | R5's gate ladder |
| `radd_relay_enabled` | 0 | dark until TLS-or-tunnel is proven |
| `radd_relay_last_seen_at` | (derived) | the owner's "is my phone still reporting?" question, answered without logs |
| `radd_relay_min_amount_match` | 1 | R3's strictness |
| `coin_earn_watch_minutes` / `coin_value_pkr` | existing coin rules | coins, admin-side |
| `device_tracking_enabled` | 1 | R7's aggregate-only counters |

**Schema caution, measured:** the live `app_remote_config` table has **18** columns and does **not**
carry `feature_link_shorteners`, while `MONETIZATION_FIELDS` lists it — so code and production schema
have already drifted apart once. The migration must therefore be **additive and idempotent**
(`ALTER TABLE … ADD COLUMN` guarded by `PRAGMA table_info`), never a recreate, and must not assume
the deployed shape equals the pushed one. That assumption is what broke today's stats projection
(see `docs/SESSION_CHECKPOINT.md`, 22:20 entry).

---

## 2. What I am building, and in what order

Ordering is by dependency and by risk, not by preference:

1. **Backend, safe today:** `device_trials` + provisional anonymous mint + server-minted key + PBKDF2
   profile-link + the admin fields above, all behind the existing `/api/v2/account` route, tests
   included. No payment path, no new public surface.
2. **RaddRelay backend, dark:** `/api/v2/payment/sms-webhook` implemented with R2–R4 (tunnel-only,
   triple match, `UNIQUE(gateway,tid)`, audit rows) and shipped with `radd_relay_enabled=0`.
3. **RaddRelay companion APK:** operator-phone-only, sideloaded, `8558`/`3737` gate in `onReceive`,
   offline queue, tunnel client. Verified against a **test** merchant number before it is ever pointed
   at real money.
4. **Android app:** silent mint on first launch, the `+1 Day Free VIP` banner, the linked-vs-anonymous
   distinction in Settings, and `trial_gate` surfaced nowhere to the user but stored server-side.
5. **Play Integrity** when the app ships through Play — before any document says the trial is
   un-farmable.

Two things in this plan are **not** closable by an agent and remain the owner's call, unchanged:
the release tag / signing (4 keystore secrets are still absent from Actions), and restarting the live
service (task #19). Everything above is code, tests, and docs.

---

## Appendix A — the spec as written by the Antigravity lane (verbatim, unedited)

> Reproduced byte-for-byte from the recovered artifact so that "do not miss any single thing" is
> literally true. Its `https://`, "Hardware Lock", 10⁴-PIN and TID-only-approval flaws are as written;
> my rulings on them are §1. Nothing here is an instruction to build as-is.

````markdown
# ⚡ Radd-Stream Master Architecture: Zero-Friction Auth & Real-Time Payment Relay

---

## 🏛️ 1. Executive Summary & Core Requirements

This document codifies the unified user lifecycle, trial enforcement, and automated monetization
rail for the `radd-stream` Android platform and Oracle Cloud backend.

### The Problem It Solves:
1. **Zero Registration Barrier**: Pakistani mobile users abandon apps that require upfront
   email/password signups.
2. **Instant Habit Formation**: Every fresh install receives **3 days of full VIP streaming**
   immediately.
3. **Anti-Abuse Hardware Lock**: Prevents users from clearing app cache or reinstalling to
   continuously get free 3-day trials.
4. **Frictionless Profile Linking (Level 2 Auth)**: Users voluntarily link their Name, Pakistani
   Phone Number, and 4-Digit Secret PIN in exchange for **+1 Extra Day of VIP**.
5. **Real-Time Payment Automation (Option 2 SMS Relay)**: Eliminates the manual 5-minute operator
   approval delay. A dedicated 200KB Android background relay on the operator's phone intercepts
   incoming JazzCash (`8558`) and EasyPaisa (`3737`) SMS messages and auto-approves customer VIP
   passes via webhook in **2 to 5 seconds**.

---

## 🔐 2. The Authentication Lifecycle (Zero-Friction + Level 2)

```
                            ┌────────────────────────────────────┐
                            │          APP FIRST LAUNCH          │
                            └─────────────────┬──────────────────┘
                                              │ (100% Background)
                                              ▼
                                 [Hardware Device Fingerprint]
                          SHA-256(ANDROID_ID + HARDWARE + FINGERPRINT)
                                              │
                                              ▼
                             POST /api/v2/account/anonymous
                                              │
                     ┌────────────────────────┴────────────────────────┐
                     ▼                                                 ▼
            【New Hardware Signature】                        【Known Hardware Signature】
        • Grants 3-Day Free VIP Pass                      • Carries over remaining trial hours
        • Mints Anonymous Account                         • Reinstalls/resets get 0 new days
                     │                                                 │
                     └────────────────────────┬────────────────────────┘
                                              ▼
                               ===============================
                               DIRECT TO HOME SCREEN & PLAYER
                               • Zero forms, zero passwords
                               • Accumulates Watch Coins
                               • Full 1080p/4K Direct CDN
                               ===============================
                                              │
                                              ▼
                          ┌──────────────────────────────────────┐
                          │  Settings Banner: Link Phone & PIN   │
                          │   Get +1 Extra Day of Free VIP!      │
                          └───────────────────┬──────────────────┘
                                              │
                                              ▼
                                User enters Name, Phone (0300...),
                                and 4-digit PIN (e.g. 7482)
                                              │
                                              ▼
                              POST /api/v2/account/profile-link
                                              │
                     ┌────────────────────────┴────────────────────────┐
                     ▼                                                 ▼
            [Backend Ledger]                                   [Customer Reward]
     • Stores direct Phone & Name for                   • +1 Extra Day VIP added
       Operator WhatsApp / Call contact                 • Multi-device recovery unlocked!
```

### 2.1 Hardware Device Fingerprint (Anti-Abuse Engine)
- **Signature Calculation**:
  ```kotlin
  val raw = "${Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)}|" +
            "${Build.HARDWARE}|${Build.FINGERPRINT}"
  val deviceId = MessageDigest.getInstance("SHA-256")
      .digest(raw.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
  ```
- **Backend Enforcement Table (`device_trials`)**:
  ```sql
  CREATE TABLE IF NOT EXISTS device_trials (
      device_id TEXT PRIMARY KEY,
      account_id INTEGER NOT NULL,
      first_seen_at REAL NOT NULL,
      trial_expires_at REAL NOT NULL
  );
  ```
- **Rules**:
  - If `device_id` is new: `vip_until = now + (3 * 86400)`. Stamped in `device_trials`.
  - If `device_id` already exists: `vip_until = max(now, trial_expires_at)`. No fresh 3 days granted.

### 2.2 Profile Linking (Level 2 Auth)
- **Data Captured**:
  - `name`: e.g. "Hamza"
  - `phone`: e.g. "03001234567" (Stored directly for operator WhatsApp / support outreach)
  - `pin`: 4-digit numeric code (e.g. "5821")
- **Sync Key Derivation**:
  `sync_key = base64url(SHA256("radd-stream-v2" + phone + pin))`
- **Reward**:
  - Instantly extends `vip_until += 86400` (+1 day).
  - Unlocks cross-device login: Entering the same Phone + PIN on another phone or Android TV recovers
    their active subscription and favorites immediately.

---

## ⚡ 3. Real-Time Payment Automation Engine (Option 2: RaddRelay)

```
[Customer sends Rs. 200 via JazzCash or EasyPaisa]
                        │
                        ▼
    Official Confirmation SMS arrives on Operator's Phone
    • From 8558: "Received Rs. 200 from 0301... TID: 9823145671"
    • From 3737: "You have received Rs. 200 from ... Trx ID: 8712345678"
                        │
                        ▼
            [RaddRelay Android App (Background)]
            • Foreground Service with low-power sticky notification
            • Strict Sender Whitelist: `8558` and `3737` ONLY (Personal SMS ignored)
            • Parses TID and Amount via regex
                        │
                        ▼ (Sent in <300ms)
       POST https://<oracle-host>/api/v2/payment/sms-webhook
       Headers: X-Merchant-Secret: <SECRET_OPERATOR_TOKEN>
       Body: { "gateway": "jazzcash", "tid": "9823145671", "amount": 200 }
                        │
                        ▼
             [Oracle Backend Engine]
             • Checks pending claims in `payment_transactions`
             • Calls approve_payment(row_id, reviewer="radd-relay")
                        │
                        ▼
     [Customer's App Updates to VIP in < 3 SECONDS!]
```

### 3.1 RaddRelay Android Architecture
- **Single Component**: `SmsReceiver : BroadcastReceiver` + `RelayForegroundService`.
- **Manifest Permissions**:
  - `android.permission.RECEIVE_SMS`
  - `android.permission.INTERNET`
  - `android.permission.FOREGROUND_SERVICE`
  - `android.permission.FOREGROUND_SERVICE_DATA_SYNC`
- **Battery Impact**: < 0.2% per 24 hours.
- **Fail-Safe Offline Queue**: If operator's phone briefly loses 4G/WiFi, messages are queued locally
  in Room SQLite and posted the second internet connectivity returns.

### 3.2 SMS Regex Parsers
```kotlin
// JazzCash (Sender: 8558)
val jazzcashRegex = Regex("""(?:Rs\.?|PKR)\s*([0-9,]+).*?TID:?\s*([0-9]{10,12})""", RegexOption.IGNORE_CASE)

// EasyPaisa (Sender: 3737)
val easypaisaRegex = Regex("""(?:Rs\.?|PKR)\s*([0-9,]+).*?(?:Trx ID|TID):?\s*([0-9]{10,12})""", RegexOption.IGNORE_CASE)
```

### 3.3 Backend Webhook Endpoint (`Fast_Fetch/payments.py` & `accounts_api.py`)
- **Route**: `POST /api/v2/payment/sms-webhook`
- **Security**: Validates `X-Merchant-Secret` header against environment `RADD_MERCHANT_SECRET`.
- **Pre-Caching & Instant Matching**:
  - If customer submitted TID first: Approves the pending row instantly.
  - If SMS arrives before customer submits TID: Stores in
    `verified_incoming_tids(tid, amount, gateway, received_at)`. When the customer taps "Submit
    Claim", the app instantly validates and activates VIP with zero delay.

---

## 📋 4. Next Implementation Steps

1. **Backend Endpoint**: Add `/api/v2/payment/sms-webhook` and `device_trials` logic to
   `Fast_Fetch/accounts_api.py` and `Fast_Fetch/payments.py`.
2. **Android App Updates**:
   - Add silent anonymous account auto-minting on launch in `RaddStreamApplication.kt`.
   - Update `VipUpgradeScreen.kt` and `SettingsScreen.kt` with the "+1 Day Free VIP" Phone+PIN
     linking prompt.
3. **`RaddRelay` Companion APK**:
   - Build a lightweight 200KB companion APK for the operator's phone to listen to 8558 & 3737.
````

---

## Appendix B — the owner's messages that produced this spec (verbatim)

Recovered from `~/.gemini/antigravity-cli/history.jsonl` (that file stores only owner turns, which is
why Appendix A had to be found elsewhere). Timestamps are host-local 2026-10-29.

- **20:34** — *"okay use level 2 and when user install app anymouse account automatically create
  without anything so when user install user do not see any registeration form and with that anymouse
  account user can still earn coins etc and upgrade etc. but there option where user can enter there
  info etc and get 1 day premium experince also on install gave user 3 day premium experince by
  default and also if possible can we identify a device so user can not temper and keep creating
  accounts randomly so with this they would not be able to get 3 day permium again and again we need
  to make it more better because when we ask user to create account its irritae most users and mostly
  people do not know about creating account in paskitan and also we will store if user enter name
  phone pin etc. and save direct phone number if we need to conatct user so we can."*
- **20:46** — *"and now also how do user buy preimum in our app using jazzcash our easypaisa etc. from
  anymouse account and what if user upgrade there account"*
- **20:54** — *"…user have to wait until i myself approve and if user did not get there account within
  under 5 mintues they can get worried so can we make fast and automatic system like create simple app
  which in pakistan moniter my mobile masseges and when it recived payment send easypisa and jazzcash
  message tilid etc into our database to oracle here and it just watch our selected message not all
  just watch jazzcash and easypaisa messages this wasy i just have to keep my moble always internet on
  an that app always keep running in backgroun"*
- **20:59** — *"Option 2 so we have complete trust and now stop qoder account if they are working
  already relted this tell them about out this complete plan our login flow make sure do ot miss any
  single thing"*
- **21:28** — *"and also make sure add all setting to admin panle like connecting with our
  RaddRelay.apk and also all new setting to to set trial free vip rewards onm account create user
  coins control user tracking etc."*
- **21:32** — *"gave this task to idle qoder account without distrubing other account and make sure it
  done work perfectly"*
- **21:48** — *"how can i see admin panle"* ← the last thing agy left unanswered; answered in
  **`docs/ADMIN_PANEL_ACCESS.md`**.

**One gap I will not paper over:** "level 2" and "Option 2" were choices from menus the Antigravity
lane presented *in its answers*, and that lane's replies are **not** in `history.jsonl`. What is
recovered above is enough to reconstruct both menus from the artifact's own §2.2 ("Level 2 Auth") and
§3 ("Option 2: RaddRelay"), and the artifact was written *after* both choices, so it is the
authoritative record of what was chosen. I have not invented any other option text.
