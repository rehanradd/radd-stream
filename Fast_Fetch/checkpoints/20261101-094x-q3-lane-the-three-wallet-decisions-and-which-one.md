# 2026-11-01 09:4x — q3 backend lane `[Q3-WALLET-DECISIONS]`: three wallet rules put in front of the owner, and none of them implemented

**Branch:** `q3-wallet-memo-on-c2528e1`, base `c2528e1`. **Worktree:** `/tmp/q3_memo`, created fresh
with `git worktree add` off the trunk sha — no merge commit, no trunk pull, fast-forward proof
`git merge-base --is-ancestor c2528e1 HEAD`. **Nothing landed**: the gate is HELD (`qoder1`'s write
credential is dead, owner-only fix), so this branch goes to its own ref and nowhere near
`main`/`master`.

**Dispatch.** `[q1 SUPERVISOR 07:0x]`, item 2: *"Two of those five are the coins review's own open
questions. `c2ae2bf` closed the concurrent-redeem race with a test; whatever remains is a decision for
the owner, not code — write the decision memo, name the option you recommend and the one that costs a
viewer money, and do NOT implement a wallet rule that has no owner sign-off."*

**Deliverable:** `docs/WALLET_OWNER_DECISIONS.md` — one file, three questions, three recommendations,
three named costs, and a §5 "what signing costs to implement" table so the owner can decide without
another round trip. **Zero code changed on this branch.** That is compliance, not caution: a grant
rule, a cap, a price and a reveal are all the same object — someone's money — and the standing rule in
this repo is that the person who owns the ledger signs, not the lane that can write it.

## The three questions, in the memo's own words

| | Question | Recommend | The option that costs a viewer money |
|---|---|---|---|
| **A** (#30) | Who mints the credential that *is* the account — `create_account(db_path, key=payload.get("sync_key"))`, `accounts_api.py:698` | **A1: refuse client-supplied keys now**, server mints and shows once | **A2: the same refusal landed *after* accounts exist** without an in-app "enter your old sync key" import |
| **B** (#11) | Whether the public wallet route reveals the viewer's own ledger rows or only aggregates | **B1: aggregate-only publicly**, per-row audit stays with the operator on loopback | **B2: status quo rows on the cleartext wire** |
| **C** | Whether a rewarded ad may ever pay, and who attests it | **C1 now, C2 (a signed server-to-server callback) the moment a network is named** | **C3: accept a client-asserted completion** |

## The reasoning that is worth more than the conclusions

**A is cheap today and never cheap again.** The measured state is `user_accounts` = **0 rows**, read
2026-11-01 00:xx through a `?mode=ro` open of `/home/ubuntu/radd-stream-data/user_state.db` (the file
the running unit uses, established in the KEYPROV memo), together with the deduction that a successful
authenticated request *requires* an existing row because `_authenticate` raises `UnknownAccount`
otherwise (`accounts.py:1003-1006`). So this host has never served an account read or write, and a
server-mint-only rule currently costs exactly nobody anything. The cost is a function of *when the
decision is made*, which is why the memo attaches an expiry to its own recommendation instead of
presenting it as timeless.

**The orphaning is asymmetric, and only the human side is permanent.** An existing row whose
`key_hash` is `sha256:` of a derivable value is not broken by the server refusing new client keys — it
stays valid forever. It is lost because the app stops presenting the string that unlocks it, and the
operator cannot find it: `key_hash` is one-way and a phone-derived digest is indistinguishable in that
column from a minted one. **No production read was performed tonight** — this section reuses the
0-row measurement already recorded in the repo, which is the honest way to answer the question while
reads are barred.

**B conflates two costs unless they are pulled apart.** The privacy cost is the rows (`reason`, `ref`,
`created_at` — an attendance pattern on an unencrypted line, and `redact.scrub_text` cannot help
because those values are the response's own payload). The money cost is not the rows: it is the
16-character bearer key riding every `/api/v2/account*` request, which *is* the account and can be
spent at `POST /coins/redeem` by whoever read it. Naming B1 as the ruling therefore does **not** make
the wallet confidential — TLS at the edge does, and that is an owner action on nginx, which this lane
does not touch. A reader who takes B1 as permission to skip TLS has read the wrong half of the memo,
so the memo says that out loud rather than implying it.

**C was already half-answered by the engine, and I read the right lines this time.**
`SERVER_SOURCES = frozenset({"server", "admin"})` (`engagement.py:107`) carries the comment *"There is
deliberately no 'client' entry (§A: no coin created by a client claim)"*; `COINS_PER_REWARDED_AD`
(`engagement.py:118-120`) is documented as *"Coins credited per **server-verified** rewarded
completion"*; and `_selfcheck()` asserts that `grant_coins(..., source="client")` raises `BadSource`
(`engagement.py:1139-1145`) while modelling the paid event as a callback with an `idempotency_key`
(`:1147-1152`). So C2 is the option the file already assumes, and C3 would contradict the engine's own
contract — not merely loosen a cap. The correction matters: `engagement.py:1141` is **not** the engine
paying for an ad in production; it is the self-check proving a client claim cannot. My first draft of
the memo said it was, and `refund`'s home was also wrong (it is `SPEND_REASONS`, `engagement.py:1116`,
not `LEDGER_REASONS`). Both fixed by re-opening the file rather than by re-reading my own prose.

## Contradictions recorded, not resolved (the standing order on contradiction reports)

1. **PBKDF2 as a fix for a derived key.** The coins checkpoint (2026-10-31) wrote that making the
   phone-derived key defensible "is an owner decision with a schema consequence: a PBKDF2 migration can
   be additive and per-row". `accounts.py:779-789` says a slow KDF buys nothing there: *"its real input
   space is the phone space, so the digest of one is brute-forceable offline no matter what this
   function costs."* Both statements are true of different things — the migration is cheap to store and
   worthless as a defense — and the memo records that, because the tempting reading of the first is a
   patch that would advertise a capability the code does not have.
2. **`rewarded_ad` is a reason and not a claimable grant** (`engagement.py:111` vs `:107` vs the
   self-check at `:1139-1145`). The vocabulary cannot express "pending attestation", so a reader of any
   one line is misled by the other two.
3. Root `AGENTS.md`'s own admission — *"the API filters 18+" is true for flagged rows and false for the
   works they name* — still stands; the operator-read half that B relies on runs over the same surface.

## Blocked, one line each

- **Landing** — gate HELD; nothing pushed to `main`/`master`, no credential retried, no self-gating.
- **CI verdict** — my credential is blocked (`curl (55) Send failure: Broken pipe` on the Actions API);
  `qoder1` reads CI.
- **Any fresh number for A** — a new `user_state.db` read is a production read, barred. The memo reuses
  the recorded measurement and says so.
- **Load** — `cpu some avg10 99`, load 4.49 at 09:22, so no test module, no scan, no crawl, no merge,
  no Gradle on this branch. Docs and git only.

## Next, for whoever picks this up

The memo is the artifact; the decision is the owner's. On a signature, §5 of
`docs/WALLET_OWNER_DECISIONS.md` names the files and the standing rule each option must respect, and
the only one of the three that is a *project* rather than a change is C2 (a network contract, a
verification key, a nonce store, a replay window).
