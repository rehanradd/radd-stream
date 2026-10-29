# Account identity — the measured answer, and what a fix has to change

Written 2026-10-29 21:10 in response to the owner's question to the Antigravity lane:
*"if someone enter sombody else name would not that user loged in somebody else account or do
we using any save method to pervent it"*. Every claim below was read off the code on this host
at the pushed tip `51f7576`; nothing here is inferred from a doc.

## 1. The answer, in one line

There is no name-based login to collide with — but the phone-number sign-in **is** a credential
guess, and today **knowing somebody's mobile number is sufficient to open their library.**

## 2. What identity actually is

| Piece | Where | What it does |
|---|---|---|
| The only identifier | `App/.../data/ServerSettingsRepository.kt:496` `SYNC_KEY_KEY` | one opaque string kept in DataStore; sent as `Authorization: Bearer` (`network/RaddStreamApi.kt:37`) |
| Server-side identity | `Fast_Fetch/accounts.py:413-420` | `user_accounts(key_hash)` — `sha256:` of the presented key. **There is no name, email or phone column in that table at all.** |
| Phone → key | `App/.../sync/SyncContract.kt:136,208-221` | `base64url(SHA-256("phone-sync/v1\|03XXXXXXXXX"))[:16]`, client-side, with a **public** domain separator |
| Open-by-key | `Fast_Fetch/accounts_api.py:377-385` → `accounts.py:895-922` | `POST /api/v2/account` accepts a `sync_key` **supplied by the caller**; an already-known key returns `created: False` and simply reopens that account |
| Row scoping | `accounts.py:1186-1190, 1282-1284, 1301-1306` | every favorite/progress read is `WHERE account_id = ?` — the id resolved from the presented key |

So the question "can somebody log in as me by typing my name" has the wrong shape: names are never
sent. The real question is "can somebody present my credential", and for the phone path the answer is
yes, deterministically, in one request.

**What limits it today:** nothing that binds a key to a person. Only `AttemptTracker`
(`accounts.py:658-779`), consulted on the *failure* path (`:816-820`), and the per-IP token bucket
`account = (30, 60.0)` (`redact.py:1112`, applied at `viewer.py:3066`). A wrong guess gets throttled;
**the right guess is never challenged**, and a number the attacker already knows is one request, not a
brute force. The app already tells its users this in plain words — `ui/screens/SettingsScreen.kt:283-289`
renders "anyone who knows it can derive the same key", and `accounts.py:125-128` documents the phone
space as enumerable offline. The derived key is 16 characters, and `MIN_SYNC_KEY_CHARS = 16`
(`accounts.py:189`) — so the phone-derived credential passes the server's own entropy band exactly;
the shape check at `_check_sync_key_shape:637-652` was written to reject weak keys and cannot
distinguish this one from a random token.

**The larger, uglier half of the same problem:** the deployed host is plain HTTP with no TLS
(`ORACLE_DEPLOYMENT.md`; `nginx` listens on 80 only). The bearer key crosses the wire unencrypted, so
on a shared Wi-Fi network a captured header beats a guessed number, and no amount of hashing on our
side fixes that. Any *real* account — one holding money, a subscription, or a device-trust record —
must not exist on this host until there is TLS.

## 3. The three asks and what each one costs

The owner's follow-up asks were: (a) no registration form — an anonymous account created silently at
install, with coins/streak/upgrade available to it; (b) a 3-day premium granted on install; (c) device
identification so reinstalling cannot farm that trial again.

| Ask | Exists today | Missing | Where the fix must sit |
|---|---|---|---|
| Silent anonymous account | `accounts.create_account()` (`accounts.py:895`) already mints a strong key server-side, and guest mode is the app's default (`SettingsScreen.kt:225-230`) | any install/device identifier at all — `ANDROID_ID`, `Settings.Secure`, `AdvertisingId` return **zero** hits across `App/app/src` | mint at first launch and never accept a caller-typed key: delete the `sync_key` argument at `accounts_api.py:385`, add an install id beside `SYNC_KEY_KEY` (`ServerSettingsRepository.kt:496`) |
| 3-day trial | `user_accounts.vip_until` (`accounts.py:413`) with exactly one writer — operator approval (`payments.py:483`) | a `trial_until`/`trial_granted_at` column and any grant path that is not a human | `accounts.py:412-482` DDL + `_NEW_COLUMNS:488-500`, then a second writer that is *not* `payments` |
| Un-farmable trial | per-key attempt tracking | any server-side device record; Play Integrity / attestation (zero hits) | a `user_devices` table keyed by a value the **server** derives, checked on the create path |

One structural point that decides the design: **a client-supplied device id cannot be trusted for
anything**, because the attacker controls the client — reinstalling and sending a new fake device id
is exactly the abuse being prevented. The honest options, in ascending strength, are Android's
`Settings.Secure.ANDROID_ID` (survives app reinstall on the same signing key + user + device, but OEM
rotation and custom ROMs break it), the Advertising ID (user-resettable, and a user can reset it), and
**Play Integrity API attestation** (Google-signed, free, no server cost, needs the app to ship through
Play and a server that verifies the nonce). The first two are deterrents, not guarantees; only the
third is a real answer, and it is $0.

So the trial rule that is actually enforceable is: grant the 3 days **once per attested device**,
record the hash of the attestation's device pointer server-side, and let an unattested install get a
shorter, clearly-labelled preview rather than the full grant. Pretending a self-reported id is a
guarantee would be a claim this codebase cannot keep.

## 4. What this is worth, stated plainly

The current sync account protects bookmarks and resume positions — nothing more. Its catalog is
already public (`/api/v1/posts` needs no key), so a takeover exposes a watch list, not a library worth
stealing, and no money path exists yet. Read-only count on the live `user_state.db` at 21:12 today:
`user_accounts 0`, `user_favorites 0`, `user_progress 0`, `payment_transactions 0`,
`sync_key_attempts 3` — the feature has never had a user, so nothing is exposed by fixing it in place.
That is why the takeover is a **defect to fix
before monetization**, not an emergency to fix tonight: it becomes expensive the moment `vip_until` can
be bought, because then stealing a key steals a paid membership.

Ordering that follows from the measurements, not from preference:

1. Stop honouring a caller-supplied `sync_key` on create, and stop deriving a credential from a phone
   number client-side. This is the defect itself and it is small.
2. Grant the trial server-side on a row the client cannot write.
3. Device binding via Play Integrity when the app can ship through Play — before claiming in any doc
   that the trial is un-farmable.
4. TLS before any real money moves over this API. Free-`$0` TLS on a bare IP with no domain is not
   available from the usual CA path, so this item is a cost/complexity decision for the owner, not a
   ticket an agent can close silently.

## 5. Open questions this document refuses to answer by guessing

- Whether `ANDROID_ID` is acceptable as a *weakened* trial gate while Play Integrity is not yet wired,
  or whether shipping a gate that is known-bypassable is worse than shipping no gate and a shorter
  preview. Not decided here.
- Whether the anonymous account is recoverable at all when a viewer uninstalls without ever claiming
  it. If the key is the only record and the key dies with the app, "silent account" means "silently
  lost bookmarks" — which is a UX decision with a data-loss tail, not an implementation detail.

## 6. Ruled — the owner answered, and the recovered plan is now the document of record

At **20:34** the owner answered §3's asks and §5's first question directly:
*"okay **use level 2** and when user install app anymouse account automatically create without
anything … on install gave user **3 day premium experince** by default and also if possible can we
identify a device so user can not temper and keep creating accounts randomly … but there option where
user can enter there info etc and get **1 day premium experince** … and we will store if user enter
name phone pin etc. and save direct phone number if we need to conatct user so we can."* At **20:59**
they chose the payment rail: *"**Option 2** so we have complete trust"*.

The Antigravity lane wrote that plan at 21:00 and was logged out at 21:49:47 without committing it; it
lived only in its own scratch directory. I recovered it and put it, verbatim, with my review, at
**`docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md`**. That file is now the document of record for the login
lifecycle, the trial gate, RaddRelay and the admin-panel settings; this §6 exists so a reader of the
older document is not left with two questions still hanging.

Both of §5's open questions are now answered, and I am recording the ruling rather than the reasoning
twice:

1. **`ANDROID_ID` — yes, as a weakened gate, and only under that name.** The owner's device-identification
   ask is served by `SHA-256(ANDROID_ID|Build.HARDWARE|Build.FINGERPRINT)`, which I will build. It is not
   a guarantee: `Build.FINGERPRINT` changes on every OTA (so a legitimate update looks like a new device),
   and all three inputs are client-reported and spoofable on a rooted phone — Play Integrity returns
   **zero** hits across `App/app/src` today, measured again at 22:5x. So the grant ships labelled
   `trial_gate='android_id_ota_vulnerable'` and the admin panel reports how many trials came through the
   weak gate. "Un-farmable" is a word this codebase may not use until `trial_gate='play_integrity'`.
   Full reasoning: R5 of the architecture doc.
2. **Recoverability of a never-claimed anonymous account: it is not recoverable, and that is now a stated
   product fact rather than an accident.** Minting is silent and the key is the only handle, so an
   uninstall before linking loses the bookmarks — the data-loss tail §5 named. The owner's
   `+1 day for entering name/phone/PIN` step is exactly the moment that tail closes, which is why the
   linking banner is a *recovery* affordance and not only a reward, and why the PIN must be a
   verification factor against a server-minted key (PBKDF2, per-account salt) rather than the source of
   the key: `base64url(SHA256("radd-stream-v2"+phone+pin))` is one unsalted digest over a 10⁴ space,
   strictly weaker than the 10⁹ phone-derived defect §1 documents. Full reasoning: R6.

One correction to §2 of this document while I am here: it is written at tip `51f7576`, and since then
the credential table has gained a second live question — `user_state.db` holds
`user_accounts`/`payment_transactions` (not the catalog DB), which is why §4's count of `0` rows is the
right place to fix this in place. And §2's "no name, email or phone column in that table at all" stays
true; Level 2 adds them deliberately, on a volunteered account only.
