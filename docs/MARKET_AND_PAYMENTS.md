# Market, Payments, and Rollout — verified against primary sources

**Owner mandate this answers:** competitor/market research (local, international, hidden, overrated),
easier/free subscription collection than a JazzCash/EasyPaisa Merchant Till ID, how to receive
international payments in Pakistan, and the Pakistan → India → Asia → Europe → world sequence at $0
infrastructure cost.

Written 2026-10-29 18:58 by the orchestrator. The draft this replaces (`/tmp/agy2_market_report.md`,
194 lines, produced by the OpenRouter "agy2" lane) is folded in here **with its errors corrected**,
because three of them would have cost the owner real money and one of them is a plan I refuse to
build.

**How to read the numbers.** Anything marked **[UNVERIFIED]** is a plausible figure from a secondary
source that I could not confirm and did not invent. Do not put one in a pitch. Anything marked
**[CORRECTED]** was wrong in the draft and I recomputed it. Primary-source claims carry the page they
came from.

---

## 1. The two rails the draft recommended do not exist for us

### 1.1 Wise cannot receive for a Pakistan resident — the draft's #1 action is void

The draft's top-ten action #2 was *"Open Wise Account (PK individual) and switch AdMob/AdSense payout
to Wise USD details"*, and its §4 inference was *"Wise is the only viable self-serve receive path for
a PK individual today."*

Checked against Wise's own help centre, article 2813542 *"Where do I need to live to hold money with
Wise?"* (the page's country table was last updated 2026-10-05). The list of countries whose residents
may hold money in a Wise account is, in full: Andorra, Argentina, Australia, Austria, Bahrain,
Belgium, Bouvet Island, Brazil, Bulgaria, Canada, Cayman Islands, Chile, China, Colombia, Costa Rica,
Croatia, Cyprus, Czechia, Denmark, Estonia, Finland, France, French Guiana, Georgia, Germany,
Gibraltar, Greece, Guadeloupe, Guam, Guernsey, Hong Kong, Hungary, Iceland, India, Ireland, Israel,
Isle of Man, Italy, Japan, Jersey, Kuwait, Latvia, Liechtenstein, Lithuania, Luxembourg, Macao,
Malaysia, Malta, Martinique, Mayotte, Monaco, Netherlands, New Zealand, North Macedonia, Norway, Peru,
Philippines, Poland, Portugal, Qatar, Réunion, Romania, Saint Barthélemy, Saint Martin, Saint Pierre
and Miquelon, Saudi Arabia, Singapore, Sint Maarten, Slovakia, Slovenia, South Africa, South Korea,
Spain, Sweden, Switzerland, Taiwan, Thailand, United Kingdom, United States, Uruguay.

**Pakistan is not on it.** India and the Gulf states are, Pakistan is not. So a PK-resident account
cannot hold a USD balance and cannot be issued USD receiving details — which is the exact thing the
draft told the owner to open and route ad payouts into. Wise in Pakistan is *send-and-convert* only;
Wise's own PK blog states that money coming into Pakistan lands in a local bank account in PKR, and
that residents "cannot directly sign up for Wise accounts" in the receiving sense.

Consequence: **do not spend owner time opening a Wise account for this purpose.** If the owner already
holds one from before the restriction tightened, it may keep older features — the same article says
"older Wise accounts have access to different features than new ones" — but nothing should be designed
around that.

### 1.2 Google does not pay AdSense/YouTube earnings into borderless accounts, and Play Billing is not available to this app

- Google's own AdSense support answer (thread 201308856) is blunt: AdSense **"does not pay to Payoneer
  or any other virtual/borderless account. It will only make payments to physical banks located in the
  country"** of the account. Payoneer's marketing pages say the opposite ("receive AdSense payments
  with a Payoneer multicurrency account"); for a Pakistan-based AdSense account the Google answer
  governs, because Google controls the wire.
- The practical rail is therefore the boring one, and it already works for PK creators: **AdSense EFT
  in PKR to a local bank account** (the banks named in the field are MCB, UBL, HBL, Bank Al Habib,
  Meezan). No intermediary, no USD details, no extra fee layer. **[UNVERIFIED as a 2026 policy
  statement — confirm in the owner's own AdSense → Settings → Payment method before acting.]**
- **Google Play Billing, which the draft ranked as the lowest-friction collection method, is not
  reachable by this product.** The same report's §5 says Play Store auto-bans reported apps in the
  India/Pakistan tiers, and the app's catalog is aggregated from third-party sites. Listing on Play to
  collect ₨250/month would put the entire distribution channel at risk to add a rail worth ~$0.14 per
  10,000 DAU per month (§2.2). That contradiction is the draft's, not mine; the resolution is to keep
  the app off Play's storefront assumptions and not to build payment code that presumes Play Billing.

### 1.3 Merchant-of-record services are out for the same reason

Paddle and Lemon Squeezy require a US/UK/EU entity. The draft marked this **[VERIFY]**; it is the
documented requirement of both services and I am confirming it as **not available to a PK resident
without a foreign entity**, which costs more than the revenue it would unlock at our scale.

---

## 2. Revenue arithmetic — the draft broke its own formula

The draft's stated formula (§2) is:

```
Daily Revenue = DAU × Sessions/DAU × Ads/Session × Fill Rate × (eCPM / 1000)
```

Its **Pakistan** table obeys it (50,000 DAU, mid case: 50,000 × 2.2 × 3.0 × 0.55 = 181,500 impressions
→ × $0.18/1000 = **$32.67/day**, exactly what it printed). Its **India** and **Tier-1** tables do not.
The draft printed "$1.98/day" for 50k DAU at a $0.45 India eCPM, when the same 181,500 impressions at
$0.45 are **$81.68/day**, and "$35.20/day" for 50k DAU at an $8.00 Tier-1 eCPM, which is
**$1,452/day**. Both are understated by ~41×, i.e. they were computed at roughly 1/40th of the stated
DAU. **[CORRECTED]** — recomputed with the report's own mid-case engagement assumptions
(2.2 sessions/DAU, 3.0 ads/session, 55% fill ⇒ 181,500 impressions/day at 50k DAU):

| Geo band | eCPM | Daily @ 50k DAU (mid) | Monthly |
|---|---|---|---|
| Pakistan | $0.12 / $0.18 / $0.25 | $21.78 / **$32.67** / $45.38 | $653 / $980 / $1,361 |
| India | $0.25 / $0.45 / $0.70 | $45.38 / **$81.68** / $127.05 | $1,361 / $2,450 / $3,812 |
| Tier-1 (EU/US) | $4.00 / $8.00 / $14.00 | $726 / **$1,452** / $2,541 | $21,780 / $43,560 / $76,230 |

Two things survive the error, and they are the parts that matter strategically:
1. **Geo mix is the dominant variable.** The PK→Tier-1 spread at identical engagement is ~44×, versus
   2–3× for fill rate or ads-per-session. The draft's conclusion is right even though its numbers were
   wrong.
2. **Absolute revenue at this scale is small.** Even corrected, a Pakistan-first launch at 50k DAU is
   ~$1,000/month gross, and this box cannot serve 50k DAU anyway (see
   [`MONETIZATION_AND_FLEET_PLAN.md`](MONETIZATION_AND_FLEET_PLAN.md) §G, which I have today corrected
   twice for search latency and transient memory). Treat ad revenue as covering a second box, not as
   the project's purpose.
3. The eCPM bands themselves are **[UNVERIFIED]** — 2026 AdMob geo benchmarks from a blog, not from
   AdMob. Fill rate for this inventory in PK is the number most likely to be worse than assumed,
   because catalog/browse traffic monetises below video.

### 2.1 What the ad pillars actually do

The owner's three pillars (capped pre-roll 1-per-25-min, one native feed card per 12 posters, app-open
ad 1-per-4-h) are compatible with the arithmetic above at roughly 2.5–3.5 ads/session, so no change is
needed to the plan — the change is to stop expecting the coin/pass layer to carry it.

### 2.2 The micro-pass conclusion the draft reached is right, and the owner's plan overrides it

The draft's action #10 was *"Kill micro-pass code paths (Rs 20/50/250), remove wallet, streak, coin
logic."* Its arithmetic — 6 friction steps per purchase, ~0.5%/0.3%/0.15% conversion, ₨20/₨50/₨250 ≈
$0.07/$0.18/$0.90 at an assumed 278 PKR/USD **[UNVERIFIED rate]** ⇒ about **$0.14/month per 10,000 DAU**
against **$196/month** from ads at the same scale — is honest and I have not been able to break it. The
support cost of manually verifying TXN screenshots exceeds that revenue by orders of magnitude.

**I am not executing action #10.** The owner's written directive makes the coin wallet, the 7-day
streak, and the PKR micro-passes product pillars, and a directive beats my opinion about its revenue
efficiency. What I did instead, and what is already recorded in the fleet plan:
- **Coins buy passes. Coins are never cash-outable, and no withdrawal path is built.** (An earlier
  request for a withdrawal-style scheme was refused for that reason; see the report's own §3 friction
  analysis — a payable wallet turns a $0 app into a money-transmission business requiring an SBP
  licence, which is the opposite of $0.)
- Passes stay as an **entitlement mechanism** (ad-free window, VIP screen) rather than as the revenue
  plan, so they cost nothing to keep and stay useful the day a real rail exists.
- Collection is **not** wired to a Merchant Till ID until someone can actually pay into it and have it
  verified without manual screenshot review.

### 2.3 Cheaper collection than a Merchant Till ID — ranked by what a user must do

The owner asked specifically for an easier or free way to collect subscriptions than a
JazzCash/EasyPaisa Merchant Till ID. Ranked by user steps, from the draft's §3 and my own corrections:

| Rail | Available to an unregistered sole-dev today? | User steps | Real cost | Verdict |
|---|---|---|---|---|
| **Raast / Raast-ID P2M** | No — needs a sponsor bank or an aggregator's merchant onboarding | 2–3 (pick merchant, confirm in bank app) | ~0 on the rail itself | **The one worth pursuing.** SBP's instant rail; free-to-cheap, and a QR/deep-link merchant ID removes the "type the Till ID then send us a screenshot" step that makes Till IDs unusable. Requires the same paperwork as an aggregator, so it is a *goal*, not a today. |
| **Aggregator gateway** (PayPro, SaferPay, NayaPay Business) | Generally yes for sole-prop with CNIC + bank account **[UNVERIFIED per provider]** | 3–4 (redirect, OTP, return) | ~2.5–3.5% + flat | Best realistic step-up once there is anything to collect. |
| **Direct carrier billing (Jazz)** | No — telco partnership, registered company | 1 | 25–30% telco cut | The friction winner and the paperwork loser. Revisit only with a registered entity. |
| **Merchant Till ID** (current plan) | Yes | 6 | 0% | **Worst UX of anything on the list.** User opens wallet → Pay Merchant → types Till ID → amount → PIN → screenshots → you verify by hand. |
| **Personal wallet direct transfer** | Yes | 6+ | 0 | Same as Till ID plus manual reconciliation of strangers' transaction IDs. Not a product feature. |
| **Google Play Billing / IAP** | No (see §1.2 — storefront risk dominates) | 1 | 15% | Not available to this app in practice. |

Honest summary: **there is no free *and* low-friction collection rail for an unregistered PK developer
in 2026.** Every rail with 1–3 user steps requires an entity, a partnership, or merchant onboarding;
every rail available at $0 today requires the user to leave the app and the operator to verify a
payment by hand. The plan that follows from that is not to hunt for a magic rail but to (a) keep
collecting nothing while DAU is near zero, (b) pursue Raast P2M merchant IDs as the first real step
because it collapses the "type an ID + screenshot" flow, and (c) keep passes as entitlements so the day
a rail lands, the product already has the semantics.

---

## 3. Competitor landscape — kept, with every user number flagged as soft

Retained from the draft because the *structure* is what's useful, not the magnitudes. Every MAU figure
below is **[UNVERIFIED]**; none is load-bearing for any decision in this repo.

| Segment | Who | Why we lose or win |
|---|---|---|
| **PK local, licensed** | DRAMATOK, AirTV, Shortzium, Tapmad | They own rights (PTV/Geo/ARY/PSL) and telco bundles. We cannot match content provenance; we can match buffering and discovery. |
| **PK/IN unlicensed APKs + Telegram** | DramaBox/DramaCool-class wrappers, ThopTV/Pikashow/OlaTV/HD Streamz clones, GDrive/1fichier link channels | **The actual competition.** Same catalog source. They monetise with interstitials, popunders and link shorteners. We beat them only on UX — and the owner has permanently retired link shorteners, CAPTCHAs and timer redirects, so that is the one axis we must win. |
| **Global FAST** | Tubi, Pluto TV, Samsung TV Plus, Freevee/Roku | Requires 50M+ MAU and a licensed library to amortise content. Not a model available at $0. |
| **Copy these** | NewPipe/SkyTube (local-only, no account, background play, SponsorBlock), Stremio's *player* UX, AnimeKisa-class multi-CDN fallback + episode memory, Ko-fi/BMAC for donor-funded groups | Real, cheap, ours to copy: resume-where-you-left-off, manual quality/source selection, multi-CDN failover, and a skip-intro marker are features, not rights problems. |
| **Overrated — unit economics fail** | Quibi (dead), Viki/Rakuten, Crunchyroll free tier, "Netflix for X" local startups | All die on the same rock: content cost per title ($5–15k) against tier-2/3 ad eCPM. Our cost per title is $0 because we license nothing, which is the same fact that makes this a catalog-aggregation project and not a streaming service. |

**Adopted from this section, already dispatched or already built:** multi-CDN/source failover and
episode resume (Android lane), a friction-free playback path with no redirects (owner directive), and
crowdsourced intro/outro markers as a *local* feature with no server cost. **Rejected:** the draft's
"Addon Loader for legal isolation".

### 3.1 Why the addon-loader idea is rejected

The draft proposed shipping a core app that is a "legal player" while scraped sources arrive as
user-installed addons, so that "liability shifts to addon devs" — and ranked it action #5. That is a
structure designed to make the same behavior look like something else. This project's standing rule is
the opposite: *describe the code's behavior accurately to users and tools, and do not frame work to
bypass another service's safety rules.* Bundling nothing while shipping a curated manifest of scraped
sources does not change what the software does, and writing it down as a compliance strategy would be
a lie we told ourselves. If an addon architecture ever ships, it ships because it is better
engineering (pluggable sources, user choice, cleaner code), and its description must say what the
sources are.

What I *have* kept from that line: **the DMCA agent designation and a published repeat-infringer
policy**, which are a real, cheap, honest obligation if US/EU traffic is ever expected, and which are
worth having before someone asks. That is owner action #1 in §5 below, not agent work.

---

## 4. Rollout sequence, with the enforcement claims labelled as estimates

The draft's §5 instrument citations (Copyright Ordinance 1962 as amended / PEMRA in Pakistan; IT Rules
2021 + Cinematograph Act 2023 + s.69A blocking in India; DSM Directive Art. 6 and Art. 17 and the
Italian blocking precedent in the EU; DMCA §512 and the "red flag knowledge" limit in the US) are the
right instruments to name. **Every timeline in it is a prediction, not a measurement** — "6–18 months
before notice", "block or ban likely in 6–12", "3–9 months per market" have no source and must not be
planned against as if they did.

What survives as sequencing, because it does not depend on those guesses:
1. **Pakistan first**, because it is where the demand, the language, and the payment rails we can
   actually reach already are. Urdu UI and community subtitles are the work, not a new market.
2. **India next only as a language/catalog investment** (Hindi/Telugu/Tamil strings, subtitle sidecars),
   because those assets are reusable everywhere including inside Pakistan, and because enforcement
   there is the most predictable in the region. Do not buy a payment rail for it.
3. **Bangladesh / Nepal / Sri Lanka** as the next real audiences: large Android bases, existing
   Hindi/Urdu demand overlap, and lower competitive polish than the Gulf.
4. **Gulf, then Southeast Asia, web-first**, with local wallets treated as unavailable until an entity
   exists.
5. **Europe/US: not with this catalog.** The draft's own conclusion, which I agree with and which is
   not a legal opinion: a scraped catalog cannot be the product in a market with Art. 17 injunction
   practice or in a US storefront. The honest paths there are licensed, Creative-Commons, public-domain,
   or user-generated content, and that is a different project with a different cost base (content
   licensing is exactly the $0-incompatible expense). If the owner wants Europe, the decision to make
   is what we would *own or license*, not which addon hides what we already serve.

---

## 5. Owner actions (not agent tasks), ranked by what unblocks money or risk

| # | Action | Why | Cost |
|---|---|---|---|
| 1 | **Decide whether a registered sole-prop entity is worth forming** | It is the gate on every low-friction rail (Raast P2M merchant, aggregator gateway, DCB). Nothing in the collection ladder above moves without it. | PKR admin cost + time |
| 2 | **Confirm AdSense payment method in your own account** (local-bank EFT in PKR vs anything else offered) | §1.1–1.2: the draft sent you to open a Wise account that cannot receive for a PK resident. The real rail is probably already in the AdSense settings screen. | 10 min |
| 3 | **Publish a DMCA agent + repeat-infringer policy if any international traffic is wanted** | Cheap, honest, and a prerequisite for anything US-facing. | ~$6 + a page |
| 4 | **Do not add the four keystore secrets until a device build is actually being distributed** — or add them and I will cut the first release | CI has no signing key (`actions/secrets` returns `total_count: 0`), so no signed APK/AAB exists. A debug APK is available on every green Android run today. | $0 |
| 5 | **Keep the service restart decision for a quiet window with a clean live tree** | The running process predates `34f22c6` by 33 h and answers `/api/v1/stats` with fields `main` deleted; a restart fixes the code currency problem but would promote 56 dirty paths if done now. | — |

Nothing here is queued on an agent. The agents' work in this area is already dispatched: localization
strings, subtitle sidecar support, multi-CDN failover, and the admin-panel device/usage tracking — all
of which are useful regardless of which rail wins.

---

## 6. What I did *not* accept from the draft, and why

| Draft claim | Status |
|---|---|
| "Wise is the only viable self-serve receive path for a PK individual" | **False.** Wise's own hold-money list excludes Pakistan (article 2813542, table updated 2026-10-05). |
| "Switch AdMob/AdSense payout to Wise USD details" | **Not possible as written**, and Google states AdSense pays only physical banks in the account's country. |
| India / Tier-1 revenue tables | **Arithmetic error, ~41× understated.** Corrected in §2 with the draft's own formula. |
| "Payoneer $100 minimum withdrawal" | **[UNVERIFIED]** — Payoneer's pricing page documents up-to-2% withdrawal and ~1% conversion with a $1.00 minimum *fee*, not a $100 minimum withdrawal. Do not plan on the $100 figure either way. |
| JazzCash "60M registered, PKR 16.8T GTV (Mar 2026)" | **[UNVERIFIED]** — plausible, unconfirmed. Not load-bearing. |
| All competitor MAU figures | **[UNVERIFIED]** as the draft itself marked them. Kept for structure only. |
| "DCB requires PKR 100k+ setup" | **[UNVERIFIED]** — no public price list; the partnership requirement itself is the blocker. |
| Kill the wallet/streak/passes (action #10) | **Overridden by the owner's directive**, with the cash-out path refused (§2.2). |
| Addon Loader for "legal isolation" (action #5) | **Refused as framed** (§3.1). Engineering value only. |
| Cloudflare Workers edge for source-link resolution (action #8) | **Deferred, not refused** — it is a legitimate caching/abuse-mitigation measure, but the draft justified part of it as hiding the host, and I will not build infrastructure whose stated purpose is evading enforcement. Origin protection can be justified on reliability grounds alone if we do it. |
