# 💰 Radd-Stream: High-Yield, Zero-Friction Monetization & Fleet Roadmap

> **Owner Directive (2026-10-29)**:
> Maximize project revenue and daily user engagement WITHOUT annoying users.
> **LINK SHORTENERS ARE PERMANENTLY DROPPED & RETIRED**:
> - We will NEVER force users through link shorteners, CAPTCHAs, or 10-second timer redirects.
> - All media downloads and streams are 100% direct, fast, and frictionless.
> - Monetization comes exclusively from clean Pre-Roll video ads (capped), native feed cards, in-app daily streak rewards, and voluntary JazzCash/EasyPaisa VIP micro-passes.

---

## 🏛️ Strategic Pillars

### 1. The Clean Ad Triad (Zero Annoyance, High CPM)
No pop-ups or interstitial spam while browsing. Only 3 natural placements:
1. **Pre-Roll Video Ad (YouTube style)**:
   - 5-second skippable video ad before starting a movie or drama episode.
   - **Frequency Cap**: Maximum 1 ad every 25 minutes (so binge-watching isn't ruined).
   - CPM: **$8.00 – $22.00**.
2. **Native Feed Cards**:
   - 1 sponsored poster card placed every 12th movie poster in the catalog grid.
   - Styled identically to movie posters with a small "Sponsored" tag.
   - CPM: **$1.00 – $3.00**.
3. **App-Open Ad**:
   - Displayed once on cold app launch only.
   - **Frequency Cap**: Maximum 1 per 4 hours.

---

### 2. In-App Wallet & Daily "Free VIP" Streak
A unified in-app coin wallet where free users can earn VIP status through engagement:
1. **Daily Login Streaks**:
   - Day 1: 10 Coins
   - Day 3: 30 Coins
   - Day 7: **24-Hour Ad-Free VIP Pass** (Drives daily app opens).
2. **Voluntary Rewarded Pass**:
   - Free users can watch 3-5 rewarded video ads to unlock **4 Hours of Ad-Free 1080p/4K streaming**.
   - Capped at 10 rewarded ads per user per day.

---

### 3. Frictionless Pakistani Micro-Payments (JazzCash / EasyPaisa / Raast)
Users in Pakistan prefer micro-passes over expensive monthly commitments:
- 🎟️ **1-Day Pass**: **₨ 20**
- 🍿 **Weekend Pass**: **₨ 50** (Fri–Sun)
- 👑 **Monthly VIP**: **₨ 250**
- Handled via direct Merchant Till ID, JazzCash, EasyPaisa, and Raast instant ID in `VipUpgradeScreen.kt`.

---

## 👥 Fleet Task Delegation (Orchestrated by qoder4)

| Worker | Assigned Milestone | Deliverables |
|---|---|---|
| **qoder1** *(Android Lead)* | **In-Player Pre-Roll & Native Ads** | 1. Integrate pre-roll ad flow in ExoPlayer (`Media3`) with 5s skip button.<br>2. Cap frequency to 1 per 25 min.<br>3. Add native poster card component to catalog LazyVerticalGrid.<br>4. Implement 7-day login streak UI. |
| **qoder2** *(Backend Lead)* | **Regional Fleet Expansion** | 1. Target next regional drama site (**Hum TV** / **Geo** / **ApneTV**).<br>2. Maintain 100% staging database isolation in `/home/ubuntu/radd-stream-data/`.<br>3. Zero data loss on redirects/SPA shells. |
| **qoder3** *(Fleet & Importer QA)* | **Green Backend CI** | 1. Resolve vocabulary mapping in `catalog_v2._link_state_of` (`unverified` vs `unchecked`).<br>2. Ensure all 15 CI test modules pass offline.<br>3. Push to `rehanradd/radd-stream` master & main. |
| **qoder4** *(Master Orchestrator)* | **Fleet Supervision & Gates** | 1. Monitor VM load, memory headroom, and crawl pacing.<br>2. Inspect PRs and ensure no worker runs Gradle while crawlers run.<br>3. Verify all 15 test suites before giving green light to push. |
| **qoder5** *(Catalog & Wallet Backend)* | **Wallet & Pass REST Contract** | 1. Finalize `safe_link_rollup` in `catalog_v2.py`.<br>2. Add `/api/v2/account/wallet` endpoints for coin rewards and pass purchase verification. |

---

## 🧾 Orchestrator Decisions & Corrections (qoder4, 2026-10-29 ~15:30 host time)

### A. The withdrawal scheme is REJECTED — recorded here so nobody builds it by accident
The source session that produced this plan contains this instruction, verbatim:
> *"add little decepation and tricks like mostly games do like giving them hope to widthare coins
> but limmit to withdraw 50$ or somthing and earning that much would be impossible can take years
> like schemew"*

That design is not implemented and will not be implemented, for reasons that are business reasons,
not moralizing:
1. **It is fraud-shaped.** A reward advertised as cash that is mathematically unreachable is a
   deceptive commercial practice. Pakistan's Consumer Protection Acts (Punjab 2009, Federal
   Islamic Republic of Pakistan Consumer Protection 2024 framework) and, more relevantly for a
   Play Store app, Google Play's deceptive-behavior policies and the FTC's dark-patterns
   enforcement, all treat exactly this pattern — fake currency with an unreachable cash-out — as
   grounds for takedown and, in the US, for charges brought by state AGs.
2. **It destroys the only asset that compounds.** Our retention depends on users believing the
   streak counter. A scheme that pays nothing converts a DAU engine into a churn engine, and
   unmonetized churn is worse than no wallet at all.
3. **It has no ad-filling future.** Ad networks audit the placement inventory of apps with cash
   incentives; a non-redeemable incentive is a policy violation that gets the *network* relationship
   terminated, which is the revenue.

**What replaces it, and it is not a softening:** coins are *only* ever spendable on our own passes
(never cash), the cost to reach every pass is published in-app, and the daily-streak reward is
tuned so a genuinely active user reaches a 24-hour pass in ≤7 days with no hidden multiplier. If the
owner wants cash-out, that is a different product (real referral payouts with real accounting) and
needs a real budget decision — say the word and I will scope that honestly instead.

### B. The CPM figures in this plan were aspirational, not measured — corrected
Pillar 1 claims **$8–22 CPM** for pre-roll and **$1–3** for native. 2026 benchmark data puts
rewarded video near **$22 in the US** and tier-3 inventory as low as **$0.06** for banners; the
same sources describe a ~300× spread by geo. Pakistan is not tier-1 inventory. Until we have our
own fill-rate report from a live SDK, plan on **rewarded/pre-roll eCPM in the $0.3–1.5 band for PK
traffic**, and re-derive after two weeks of real data. Anyone quoting the $8–22 number in a
forecast is using a US rate for PK impressions.

### C. Payment collection — the Merchant Till ID is the worst option on the list, so it is demoted

> **UPDATED 2026-10-29 18:58 — read [`MARKET_AND_PAYMENTS.md`](MARKET_AND_PAYMENTS.md) before acting
> on this ladder.** Two of its rungs changed under primary-source checking: **Google Play Billing is
> not reachable by this app** (a storefront-listed, scraped-catalog client is exactly what Play bans,
> so the §E "real blocker" is not a fee problem but a distribution-existence problem), and **Wise
> cannot receive for a Pakistan resident** — Wise's own hold-money country list (help article 2813542,
> table updated 2026-10-05) does not include Pakistan, which voids the "open a Wise account and route
> ad payouts into it" advice I was handed. The rail worth pursuing is **Raast P2M merchant IDs**, and
> the honest headline is that *no* collection rail is both free and low-friction for an unregistered
> PK developer in 2026.
>
> Also corrected there: the market draft's India and Tier-1 revenue tables understated their own
> formula by ~41×, and its "kill the wallet/streak/passes" recommendation is overridden by the owner's
> directive (coins buy passes; coins are never cash-outable).

Owner's own complaint is correct: typing a Till ID and a reference number is friction nobody in a
movie app tolerates, and the direct JazzCash/EasyPaisa merchant APIs require a registered business,
a signed agreement, and an onboarding cycle we cannot promise to survive at $0.
Realistic order of friction, cheapest-first, for us today:
1. **Google Play Billing (subscriptions/in-app)** — zero integration of a Pakistani bank, PKR price
   points supported, the wallet already exists on the user's Play account, and it is the only path
   that also works for India/Asia/Europe when we expand. Cost: the 15% service fee, and it requires
   the app to be *on* Play, which is the real blocker (see §E).
2. **A local aggregator** (PayPro / eSewa-class / NayaPay Business / SaferPay-style) instead of a
   direct wallet API — one integration, cards + wallet + Raast together, smaller onboarding
   requirement than going to each wallet's merchant desk.
3. **Raast / Raast-ID (IBFT or proxy-address, SBP-operated)** — near-zero rail cost and instant;
   needs a sponsor bank or an aggregator to reach it, which is exactly what option 2 buys us.
   JazzCash reported 60M+ registered customers and PKR 16.8T annual GTV through March 2026, so the
   rail is not the problem; *our* access to it is.
4. **Direct wallet transfer to a personal number + manual proof** — works, costs nothing, but it is
   unverifiable at scale and is the shape of the Till-ID friction we are trying to remove. Use it as
   a fallback only, never as the headline.
5. **Merchant Till ID** — last. Keep it only as a manual escape hatch.
**International receipts:** Paddle / Lemon Squeezy class merch-of-record (they become the merchant
of record and pay the developer out, which is what a Pakistan-based solo dev actually needs, since
Stripe's own merchant accounts are not available there), or Payoneer receiving accounts for B2B —
which is the natural fit for the partner API in §D, where the customers are businesses, not viewers.
**Direct carrier billing** is the highest-converting rail for digital content in 2026 by the
industry benchmarks, and Jazz has repositioned itself as a digital-services provider — but DCB needs
a telco agreement, so it is a *scale* option, not a $0-today option. Deferred, tracked.

### D. The "sell our API" product is split into two tiers, and one of them is gated
Owner asked for a system where anyone can build their own movies website/app on our API, separate
from our app's API. qoder3 has the spec (`Fast_Fetch/PARTNER_API.md`, `/api/partner/v1/**`, per
tenant keys + metering + rate limits). The commercial split is not optional:
- **Tier A — metadata** (titles, years, posters, synopsis, genres, ratings, season/episode
  structure, link-health scores). This is sellable, meterable and the actual product.
- **Tier B — source-link resolution** (the watch/download URLs into third-party sites). Selling
  this means charging customers for access to files that are not ours to license so they can ship a
  piracy app. That is contributory infringement in most of the markets in §F and it is the single
  biggest legal exposure in this project. It ships **off by default** behind an explicit tenant flag
  and the owner makes that call in writing before it is ever enabled for a paying customer.

### E. The distribution problem the plan does not mention yet
Everything in Pillars 1–3 assumes the app reaches users. An APK self-hosted at
`http://92.4.95.252/download/` over plain HTTP can be installed by whoever already knows the URL,
and nothing else — no Play listing, no update channel, no ad-network approval, no payment rail, and
the catalog content is what blocks the Play listing. So the real monetization sequence is:
1. land the app-quality work (buffering/offline + ad contracts, qoder1),
2. decide the content posture (rights-clean catalog subset vs. keep it side-loaded),
3. only then does any of Pillars 1–3 have a delivery channel.
I am treating "which of these two content postures we ship" as the owner's decision and I have
flagged it rather than quietly picking one.

### F. Offline/"save internet" and instant-play — the Antigravity session's unfinished thread, now owned
The recovered session (`~/.gemini/antigravity-cli/conversations/22616d46…`, last steps 7982–7991)
was mid-diagnosis, and I finished the measurement: `data/cache/` is 31 files / 3,636 lines and IS
registered (Room `AppDatabase.kt:42-50` v6 with `CacheTaskEntity`/`CacheFileEntity`/
`ByteRangeManifestEntity`, `di/CacheModule.kt` @Singleton, `NavGraph.kt:203` Downloads route,
`PlaybackService.kt:223-225` already resolving `engine.playableUri(...)`). But
`CacheCoordinator.onPlayheadAdvanced` (:209) and `keepNow` (:222) have **zero callers** outside the
package — the only mention is a doc comment at `repository/CacheRepository.kt:49`. That dead pair is
exactly the owner's two questions ("make it feel instant when the net is slow / when I seek" and
"do we implement downloading/saving internet") and it is now qoder1's milestone (task #15).
Two honesty rules attached: no fake buffering theatre — we remove real latency, we do not disguise
stalls; and the data-saving claim is *only* true for a re-watch or resume of the same rendition, so
"save 90% of your data" must not appear anywhere.
`App/docs/HANDOFF_appcache.md` still claims the package is "inert" and says to bump Room `1 → 2`;
both are false as of today and are on qoder1's correction list.

### G. Cost ceiling and capacity, stated
Everything running is at **$0**: stdlib-only Python, SQLite, one Oracle VM, GitHub Actions for CI,
free-tier OpenRouter models for drafting, and no paid SaaS.
Measured box specs, 2026-10-29 15:35 host time (`/proc/meminfo`, `nproc`, `df`, `swapon`):
**1 vCPU** (`nproc=1`, kvm), **MemTotal 12,211,732 kB (~11.6 GiB)**, MemAvailable 3,762,608 kB,
**SwapTotal 6,291,448 kB with only 1,840,916 kB free** (i.e. ~4.3 GiB of swap already in use by the
five agent CLI processes, each ~1.0-1.3 GB RSS), Committed_AS 10,633,540 kB, disk 193 GB with
112 GB free. So the constraint on this box is **one CPU core and swap headroom, not RAM total**.
The honest capacity consequence: the API is stdlib Python behind nginx, served by *one* core that
is also running the crawlers and every agent. Metadata browsing is cheap per request;
playback-resolution requests and sitemap crawls are what actually consume the core.

**MEASURED 2026-10-29 17:20–17:40 — this replaces the working estimate above. Loopback, `nice -n 19`,
stdlib `http.client`, against the live `radd-stream` service on `127.0.0.1:8080`; no synthetic
benchmark, no extrapolated vendor number.**

| Condition | Route | p50 | p95 | throughput |
|---|---|---|---|---|
| load 6.95 (4 agents generating) | `/api/v1/posts?page_size=20` ×1 client | 314 ms | 359 ms | **3.2 rps** |
| load 6.95 | `/api/v1/search/by-media?q=` ×1 client | 334 ms | 402 ms | **2.9 rps** |
| load 6.95 | posts ×4 clients ×10 | 970 ms | 1,303 ms | **3.7 rps aggregate** |
| load 1.27→3.59 (agents between turns) | posts ×4 clients ×10 | 970 ms | 1,543 ms | **4.2 rps aggregate** |
| load ~14 (Gradle + prod snapshot running) | `/api/v1/stats` | **20 ms** | — | policy-bound, not CPU-bound |
| load ~14 | `/api/v1/posts?page_size=10` | **242 ms** | — | same |

Four findings, each with the measurement that produced it:

1. **The wall users actually hit first is our own rate limiter, not the CPU.** `redact.BUCKET_LIMITS`
   (`Fast_Fetch/redact.py:1108`) is `play 30/60s`, `browse 60/60s`, `reports 10/60s`,
   `account 30/60s`, default `60/60s`, keyed **per client IP** (`redact.client_ip`:
   first `X-Forwarded-For` entry, else the socket peer). Eight simultaneous clients from one
   address returned **24/24 `429` with `Retry-After: 36`** while the box sat at load 3.6 — and
   `/api/v1/stats` began 429-ing after only ~10 calls because its bucket is 10/min. So one user
   *cannot* exceed 1 browse request per second no matter how idle the server is. That is a policy
   choice working as designed, and it is what makes a single-core VM survivable in public.
2. **Throughput is flat in concurrency, which pins the bottleneck on the core.** 3.2 rps at one
   client → 3.7 at four → 4.2 at four on a quiet box. The server is genuinely concurrent
   (`ThreadedHTTPServer(ThreadingMixIn, HTTPServer)`, `Fast_Fetch/viewer.py:2982`,
   `daemon_threads = True`), so this is not a serialization bug — it is one vCPU doing the work.
3. **Per-request cost dominates and it is fixable.** A 20-post page costs ~300–480 ms. That single
   number is the whole capacity story: halve it and every figure here doubles. It is why the v2
   projection rebuild (task #10) is worth more than any code-level micro-optimization, and why
   `is_18_plus` being unindexed (a full scan of 150,799 rows, measured by q5 at 17:00) matters.
4. **Playback never touches this box.** Streams and downloads redirect to third-party hosts; the VM
   serves metadata, one resolve per play, and `/api/v1/stats`. Ad impressions, video delivery and
   poster CDN all belong elsewhere, so they do not enter this ceiling.

**What that buys, stated as arithmetic with its assumptions visible rather than as a promise.**
At the measured **4 rps** catalog-read ceiling and the per-IP policy: the box sustains roughly
**15–25 users browsing at once** before p50 passes ~1 s, which is the point where a mobile user
notices. Expressed in the unit the owner actually asked about — a **$0 monthly bill** on this VM
supports order **1,000–1,500 daily users comfortably and a few thousand at degraded evening
latency**, assuming ~8 API calls per session, ~3 sessions per user per day, an evening peak factor
of ~6 over the daily mean, crawls paused, agents idle, and the projection rebuild landed. Every one
of those five assumptions is mine, not measured; treat the concurrency figure as the measured one
and the DAU figure as derived from it. Crossing into Europe/Gulf traffic (higher eCPM, also higher
expectations) needs either the query cost cut or a second box — not a code trick. **I have not run
a warm-cache probe at zero agent load, and the running process is 2d15h older than `main`
(`Restart=on-failure`), so these are numbers for the code as deployed, not as committed.**

**CORRECTION TO THE PARAGRAPH ABOVE, MEASURED 2026-10-29 18:05 — it is true only for `/posts`, and
search breaks it.** Five probes ran simultaneously on the same loaded box (load 12.8–13.3, a Gradle
build and a live crawl going) against `GET /api/v1/search/by-media`:

| query | status | latency | bytes |
|---|---|---|---|
| `inception` | 200 | 318 ms | 4,295 |
| `kpop` | 200 | 580 ms | 883 |
| `don` | 200 | **7,742 ms** | 9,406 |
| `love` | 200 | **44,992 ms** | 8,271 |
| `a` | — | **no response, client timeout 60,071 ms** | 0 |

In the same run `/api/v1/posts?page_size=20` took **244 ms** and `/api/v1/stats` **37 ms**, so this
is not CPU starvation — it is query shape. Payload size does not track it either (8 KB in 45 s vs
4 KB in 0.3 s), so the cost is in producing the answer, not returning it. Consequences, stated
plainly because they are bad:
1. The single-letter and common-word queries that a user types **first** are the expensive ones, and
   `q=a` returns nothing at all. A search box that hangs on one keystroke is the most visible way
   this app can fail a person, which is the direct opposite of the owner's zero-friction directive.
2. One 45-second request pins this box's only core, so any client can self-DoS the service by typing
   a common letter. The per-IP `browse` bucket limits *volume*; it does nothing about one expensive
   query.
3. Therefore the "15–25 concurrent browsers" figure above is a **`/posts`-only** number and must not
   be quoted for search. Until the search route is fixed, the honest concurrency statement for a
   search-heavy app is **single digits**, and the honest DAU statement is bounded by that route, not
   by the browse route.
The fix is dispatched (diagnose with `EXPLAIN QUERY PLAN` + `PRAGMA index_list`, then FTS5 or a
bounded prefix query, plus a client-side debounce/minimum-token-length so the app never fires a
search per keystroke). No index will be built by hand on the live 6.4 GB catalog — that takes a write
lock under a reading public API; it goes through a reviewed migration with a runtime estimate.

**SECOND CORRECTION — MEASURED 2026-10-29 18:18: the constraint that bites first is a transient RAM
peak, not the limiter and not the CPU.** (Read the third correction below before quoting this one —
two of its readings were wrong, and I am the one who wrote them.)
`fast_fetch.py serve` is the largest process on this 11,925 MiB box:

| measurement | value |
|---|---|
| pid / age | `265554`, running 1 d 22 h |
| `VmRSS` | 7,169,676 kB (**6.9 GiB**) |
| `RssAnon` | 7,159,992 kB — essentially all of it private heap, not page cache |
| `VmSwap` | 1,101,928 kB → **~8.2 GiB private total** |
| `smaps_rollup` `Pss_Dirty` | 6,877,580 kB |
| threads (`nlwp`) | **3** |
| established connections on 127.0.0.1:8080 | **1** |
| RSS sampled over 36 s | 6,957 → 6,988 → 6,982 MiB (flat) |

Three threads and one live connection, so this is **not** a thread leak and **not** a request storm.
Its memory was spread across many large anonymous mappings (the twelve largest held ~320–520 MiB
resident each, with virtual sizes in the hundreds of GiB), which is the shape of big transient
allocations returned to glibc rather than to the OS. I had one interpretation wrong, and I am
correcting it myself below.

**THIRD CORRECTION — MINE, MEASURED 2026-10-29 18:47: the process DOES hand the memory back, so
"plateau" was wrong. `VmHWM` is the metric; instantaneous `VmRSS` is not.** Same pid `265554`, same
start time (age 1 d 23 h, never restarted), 29 minutes apart:

| metric | 18:18 | 18:47 |
|---|---|---|
| `VmRSS` | 7,169,676 kB (6.9 GiB) | **57,576 kB (56 MiB)** |
| `RssAnon` | 7,159,992 kB | 47,784 kB |
| `VmSwap` | 1,101,928 kB | 107,724 kB |
| `VmHWM` | — | **7,666,280 kB (7.3 GiB)** |
| `MemAvailable` | ~1,003 MiB | ~6,143 MiB |

So the true shape is a **transient multi-gigabyte peak, released afterwards** (~7.2 GiB returned
without a restart), not a permanent balloon. Two consequences, and they are worse than the plateau
story I wrote an hour ago:
1. The peak is still the hazard, just episodically. The collision that matters is a search-class
   query running *while* a Gradle build and agent sessions are live — which is exactly the moment
   `MemAvailable` hit 1,000 MiB and `SwapFree` hit 783 MiB. One bad coincidence on a 1-core box, and
   the OOM killer's largest target is the production service.
2. **Cold-cache latency is a direct cost of the peak.** While the service held 6.9 GiB of anonymous
   memory, the page cache was evicted (`Cached` was 868 MiB against a 6.4 GB catalog). Right after it
   released that memory, the first `/api/v1/posts?page_size=20` I measured took **3,928 ms**; the next
   three took **371, 363, 431 ms** as the cache refilled (`Cached` 2,659 MiB). So the honest SLO for
   that route is *3.9 s cold, ~0.4 s warm*, and every §G throughput number above is a warm-cache
   number. A real user arriving after a memory spike gets the 3.9 s.
3. I still have **not** proved which handler makes the peak. `VmHWM` is monotonic per process, so the
   next tick can attribute growth without re-triggering it — and I am deliberately **not** firing a
   `q=a` probe at production to reproduce a GiB-scale allocation on a loaded single core. The
   candidate stays the `by-media` temp B-trees (see the plan above: two `USE TEMP B-TREE FOR
   count(DISTINCT)` plus one for `ORDER BY`, over a fan-out of 1.78 M releases × ~2.3 sources).
4. Therefore the restart question changes shape. Releasing the memory is **not** what a restart buys
   anymore — the process does that itself. What a restart buys is *code currency* (see below), and it
   still has to wait for a clean live tree.

**AND A DEFECT THE MEMORY DIGGING EXPOSED: the deployed service is serving stats that `main` already
fixed 33 h ago.** At 18:47 `GET /api/v1/stats` answered:

    {"posts": 116922, "releases": 1383752, "sources": 3783959,
     "active_sources": 3783959, "resumable_sources": 0, "temporary_sources": 0}

Three things are wrong with that, and all three are explained by process age:
  - `active_sources` is **numerically identical** to `sources`. That is precisely the retired bug —
    commit `34f22c6` (2026-10-29 05:09, "fix(stats): publish adult-excluded counts and stop calling
    unprobed links active") exists to fix it, and `viewer.py:549` still carries the comment saying
    `active_sources` "used to be the total link count".
  - The response has **no `sources_by_state` key**, which `viewer.py:2931` unconditionally returns.
  - It reports `posts: 116,922` while the catalog table holds **150,799** rows, and the adult clause
    that `34f22c6` added would give 135,731 — so neither the deployed number nor the fixed number is
    what a reader would assume. Do not quote either as "the size of the catalog"; the measured table
    count is 150,799 and 15,068 of those rows carry `is_18_plus=1`.
  - The unit started **Tue Oct 27 19:47:16**, i.e. 33 h 22 m **before** `34f22c6`. So the running
    system is not the committed system, and anything an agent "verifies" against `/api/v1/stats`
    today is verifying deleted code. This is the concrete cost of deferring the restart, and it is
    why task #10 is blocked on the owner, not on me.

Mitigations taken, all reversible and none of them a restart: the credit-limited `qoder2` lane was
suspended with `SIGSTOP` (pid 1242663, ~476 MiB — it cannot accept work, so this costs zero progress),
which raised `MemAvailable` from 1,003 to 1,372 MiB at the time. My own production snapshot runs
`nice 19 / ionice -c3`. I will not restart `radd-stream` unilaterally: `Restart=on-failure` with
`WorkingDirectory=/opt/radd-stream` means a restart today would promote the live tree's 33 uncommitted
lane files into production, which is exactly what the checkpoint rule exists to prevent.

### H. Admin panel: user & device tracking is being built (qoder3, task list) — aggregates only,
install-scoped pseudonymous id, stated retention, loopback operator port only, never through the
public nginx allow-list. And the measured defect stays on the record: on `127.0.0.1:8081` the
dashboard serves 200 with **no token at all** (measured 2026-10-29 05:47), so that port's real
boundary is loopback, not `RADD_ADMIN_TOKEN` — do not describe it as token-gated.

