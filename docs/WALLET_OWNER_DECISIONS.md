# DECISION MEMO: the three wallet questions that are the owner's, not this lane's

**What this file is.** A decision memo, not a specification and not a patch. **Nothing in it is
implemented**, and that is deliberate: qoder1's instruction on this work was *"write the decision
memo, name the option you recommend and the one that costs a viewer money, and do NOT implement a
wallet rule that has no owner sign-off."* Each question below is a rule about someone's money, so
the answer is a signature, not a commit. Written at trunk `c2528e1`, branch
`q3-wallet-memo-on-c2528e1`, q3 backend lane, 2026-11-01.

Every citation was re-opened at that line before being written down. Where a repo document and the
code disagree, the disagreement is recorded in §4 rather than resolved by editing either one.

---

## A. Who mints the account credential — `accounts_api.py:698` (fleet item #30)

**The fact, in one line.** `POST /api/v2/account` passes the caller's own string straight into the
account store:

```python
created = accounts.create_account(db_path, key=payload.get("sync_key"))
```

`accounts.create_account` (`accounts.py:1090-1103`) takes `key` as *"a token the app minted"* and
mints a 96-bit `secrets.token_urlsafe(12)` only when `key is None`. So the credential that *is* the
account — the bearer string every `/api/v2/account*` route authenticates with — is today chosen by
the client, and a client that derives it from a phone number produces a digest of a
searchable input rather than 96 bits of randomness.

**Measured cost of deciding now, versus deciding later.** Read-only, one `?mode=ro` open of the file
the running unit actually uses (`/home/ubuntu/radd-stream-data/user_state.db`; measurement
2026-11-01 00:xx, full method and table inventory in
[`checkpoints/20261101-00xx-q3-lane-the-phone-derived-sync-key-decision-memo.md`](../Fast_Fetch/checkpoints/20261101-00xx-q3-lane-the-phone-derived-sync-key-decision-memo.md)):

| measured | value |
|---|---|
| `user_accounts` rows | **0** |
| `coin_ledger` / `streak_state` | **tables absent on this host** |
| successful authenticated requests ever served | **0** — `_authenticate` raises `UnknownAccount` on a missing row (`accounts.py:1003-1006`) |

That is the whole reason this question is cheap today and expensive later: **nobody has an account,
so a server-mint-only rule costs no viewer anything while the table is empty.** The same rule, landed
after the base exists, is a different decision with a different bill — see the option that costs
money below.

**The options.**

| # | Option | Who it protects | What it costs |
|---|---|---|---|
| **A1** | **Refuse a client-supplied `key` at `:698`; the server mints and shows it once**, exactly as the `anonymous` entry already does | the wallet, from an offline guess over a phone-number input space | zero viewer cost today; one app-side change (store the returned string instead of deriving one) |
| **A2** | Same refusal, but landed **after** accounts exist, with no import path | nobody who already holds a derived key | **the viewer's money** — see below |
| **A3** | Keep accepting a client-minted key (status quo) and put the honesty in the app's copy | nothing but the schema | keeps the first-writer-wins hazard: someone who knows a number can own that account id before its owner does |

**Recommendation: A1, and land it while `user_accounts` is still 0 rows.** It is the only option that
removes the low-entropy input instead of re-describing it, and it is the only one whose cost is
measured at zero. The recommendation has an expiry date attached to it on purpose: A1 is free
*today*, and the same patch is not free next month.

**The option that costs a viewer money: A2.** An existing account whose stored `key_hash` is
`sha256:` of a derivable value is **not** orphaned by the server refusing new client keys — the row
stays valid forever. It is orphaned on the *human's* side, because the app stops presenting the
string that unlocks it. What that viewer loses is concrete: the balance they earned, any pass they
paid money for, their favorites and progress. And it is unrecoverable by the operator, because
`key_hash` is one-way and a phone-derived digest is **indistinguishable in that column from a minted
one** — there is no query that finds the affected rows and no re-key path in the code today. If A1
lands after accounts exist, the only safe companion is an in-app *"enter your old sync key"* import;
a silent re-mint is the thing that eats the wallet.

**Do not confuse this with a hashing change.** A PBKDF2 migration of `_hash_key` is a storage-form
change (additive and per-row, because the prefix tag in `_hash_key` records the form) and **it does
not answer A1/A2/A3**: the file itself says so, at `accounts.py:779-789`, and §4 quotes it. Buying
slow hashing instead of making the decision would advertise a protection the code does not have.

---

## B. What the public wallet route may say about a viewer's history — fleet item #11

**The fact.** `GET /api/v2/account/coins/history` returns the viewer's own ledger rows — `reason`,
`ref`, `created_at` per grant (`ledger(...)` in `engagement.py`). On this host every
`/api/v2/account*` route is reachable in the clear: nginx allow-lists the prefix and there is no TLS
terminating at the edge. The recorded hazard is in
[`checkpoints/20261031-q3-lane-the-coins-wire-and-the-plain-http-wallet.md`](../Fast_Fetch/checkpoints/20261031-q3-lane-the-coins-wire-and-the-plain-http-wallet.md),
and it is worth separating two costs that chat logs tend to blur into one:

- **the privacy cost** is the rows: which days a viewer opened the app, how steadily, on what clock —
  an attendance pattern on an unencrypted line, for a service whose public face is a Pakistani
  catalog. `redact.scrub_text` does not help here, because those values are the response's own
  payload, not secrets the redactor knows.
- **the money cost is not the rows.** It is that every one of those requests carries the 16-character
  bearer key, and that key *is* the account. Whoever reads it can call `POST /coins/redeem` and take
  the balance into a pass, and can replay the `signed VIP pass` in the response body against
  `/api/v1/download` and `/api/v1/stream` until it expires. The viewer loses money; the rows are only
  how they find out.

**The options.**

| # | Option | Effect |
|---|---|---|
| **B1** | **Aggregate-only on the public route**: `{balance, granted_today, by_reason}`, no per-row `ref`/`created_at`; the per-row ledger stays where an audit already lives — the operator read surface on the loopback port | removes the attendance pattern from the cleartext wire; **removes nothing of the money cost**, because the key still rides every request |
| **B2** | Status quo: rows stay on the public route until TLS exists | the viewer keeps a self-service audit trail; the wire keeps both costs |
| **B3** | Refuse `/coins/history` outright until TLS terminates | smallest wire surface; the viewer can no longer see their own wallet at all, and neither can support without a loopback read |

**Recommendation: B1, written here as the ruling rather than left in a chat log — with the
precondition stated next to it.** B1 is the correct shape for a public route because a wallet's
history is an audit artifact, and audits belong to the party that can be held to keep them: the
operator on loopback. But signing B1 does not make the wallet confidential, and anyone who reads this
file as permission to skip TLS is reading the wrong half of it. **The decision that protects money is
TLS at the edge**, which is an owner action on nginx and not something this lane may change. The
three mitigations already named for the owner — terminate TLS, scope `/api/v2/account/coins*` to
app-only paths, or accept it as written — stand, and none of them is a code review.

**The option that costs a viewer money: B2.** It is not the rows that spend them; it is that B2 keeps
a route live on a channel where the credential that redeems the balance is readable by anyone on the
same network path. B1 costs the viewer the *convenience* of auditing their own wallet and moves that
audit to a party who can perform it; B2 costs them the wallet.

---

## C. Whether a rewarded ad can ever pay, and who says it finished

**The fact.** `POST /api/v2/account/coins/earn` takes `reason="daily_login"` and answers
`rewarded_ad` with **403 naming the missing ad-network callback**. The reason is not caution: the
ledger's own source law (`engagement.py:105-107`) is

```python
#: The only sources allowed to mint a positive delta. There is deliberately no
#: 'client' entry (§A: no coin created by a client claim).
SERVER_SOURCES = frozenset({"server", "admin"})
```

while `rewarded_ad` **is** in the reason vocabulary (`engagement.py:110-112`) and the constant that
prices it is documented as paying only a verified completion — `COINS_PER_REWARDED_AD`
(`engagement.py:118-120`): *"Coins credited per *server-verified* rewarded completion"*. The engine's
own self-check (`engagement.py:1139-1144`) asserts that `source="client"` raises `BadSource`, and the
paid event it models instead is a callback carrying an `idempotency_key`
(`engagement.py:1147-1152`). So the file already answers part of this question: what it will buy is a
verified callback, not a claim. The app side already carries ad machinery
(`AdCadenceGovernor`, `AdSlotPolicy`), so the promise is closer to existing than the attestation is.

**The options.**

| # | Option | Effect |
|---|---|---|
| **C1** | Keep the 403; `SERVER_SOURCES` stands until a network is named | no ad pays today; nothing on screen may promise one |
| **C2** | **Server-to-server callback**: the ad network posts a signed completion to a new route, which verifies signature + per-account nonce, then calls `grant_coins(source="server")` | coins are honest and the ledger's source law is unchanged; needs a contract with a network, a key to verify with, and a replay window |
| **C3** | Accept a client-asserted completion (add `client` to `SERVER_SOURCES`) | the daily cap becomes the only barrier between a script and a wallet |

**Recommendation: C1 now, C2 the moment the owner names an ad network — and C2 is a real project, not
a flag.** The route is already written so that C2 is one new handler plus a verification helper; no
existing owner has to change, which is the point of leaving the 403 in place rather than quietly
relabelling a client claim as `server`. Relabelling would make the one column whose job is *who
vouched* lie, and then the ledger cannot be trusted for anything else either.

**The option that costs a viewer money: C3.** Two ways, and both are the same mechanism. A farmable
wallet gets corrected, and the predictable correction is a `refund` — which the ledger classes as a
**debit** (`SPEND_REASONS = frozenset({"redeem_pass", "refund"})`, `engagement.py:1116`, and the
comment at `:1113-1115` calls it "a compensating row — the append-only way to undo a mistake") taken
from balances that exist: the viewer who earned coins honestly pays part of the bill for the ones who
did not. And the second move, tightening `COINS_PER_REWARDED_AD` or `REWARDED_DAILY_CAP` after the
fact, reprices every viewer's effort downward in substance if not in name. C1 costs a viewer only a
reward that was never going to be honest.

---

## 4. Recorded contradictions — reported, not resolved here

1. **PBKDF2 for a derived key.** The coins checkpoint (2026-10-31) wrote that making the phone-derived
   key defensible "is an owner decision with a schema consequence: a PBKDF2 migration can be additive
   and per-row". `accounts.py:779-789` says the opposite about what a slow KDF buys: *"A key the APP
   derived from a phone number is the opposite case: its real input space is the phone space, so the
   digest of one is brute-forceable offline no matter what this function costs… the honest fix is in
   the app's copy."* Both are true of different things — the migration is cheap to store, and it is
   worthless as a defense. The decision that is not worthless is A1.
2. **`rewarded_ad` is a reason but not a claimable grant.** `engagement.py:111` lists it in the reason
   vocabulary, `engagement.py:107` refuses the source that could produce it from a phone, and the
   self-check at `engagement.py:1139-1145` exists specifically to prove that refusal holds. A reader
   of the reason list alone would conclude ads pay; a reader of the source line alone would conclude
   the reason is dead code. Neither is true — the reason is live for a *server-verified* completion
   that no route on this host can yet obtain. That seam is question C, and the file's own vocabulary
   cannot close it.
3. **"the API filters 18+" is still true for flagged rows and false for the works they name**, per
   root `AGENTS.md`, and the wallet does not touch it. Named here only because §B's operator-read
   half runs over the same read surface that carries that known gap.

---

## 5. What signing each option costs to implement, so the owner does not have to ask again

| Sign | Files touched | Rough surface | Standing rule it must respect |
|---|---|---|---|
| **A1** | `Fast_Fetch/accounts_api.py` (drop the `key=` passthrough at `:698`), `Fast_Fetch/accounts.py` (a `key=None`-only creation path), `App/**` (store the minted key), `Fast_Fetch/test_coins_engine.py` + the account tests | small; the refusal is one argument removed | the app must never re-derive what the server handed out, and a re-presented key answers `created=False` with `sync_key=None` (`accounts.py:1098-1099`), so the plaintext is readable exactly once |
| **B1** | `Fast_Fetch/accounts_api.py` (history projection), `Fast_Fetch/engagement.py` (an aggregate read beside `ledger(...)`), its tests | small | a public response carries opaque handles, never raw upstream addresses; the operator read stays loopback-only |
| **C2** | one new handler + signature verification, a nonce store, a replay window, the network's contract and key | **not small** — this is a project, and it is the owner's to schedule | `SERVER_SOURCES` stays `{server, admin}`; the server, not the phone, vouches |

**What this lane will not do without one of those signatures:** change a grant rule, change a cap,
change a price, change what the wallet route reveals, or touch nginx. None of the three questions is
blocked on measurement — every number needed to answer them is already in this file, and the one that
could move (`user_accounts` rows) moves only upward.
