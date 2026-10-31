# 2026-10-31 ~20:2x host (15:2x UTC) — qoder1 supervisor `[Q1-LANDING-SPREE]`: four branches landed green, one branch refused for putting a token in a URL, one found superseded, and a shared-repo `FETCH_HEAD` that nearly gated the wrong tree

**Scope:** supervision, gating and landing. No `.kt`, `.kts`, resource, workflow or `.py` source
file was written by this lane; no Gradle invocation (the owner's build hold stands until he reports
load under 0.5); no scraper run, no crawl, no catalog merge, no production database read; **no
service action of any kind** — `radd-stream.service` was not restarted, reloaded or stopped — and **no
tag was created, moved or deleted**. Work happened in dedicated worktrees under `/tmp`; `/opt/radd-stream`
was never committed from or reset. Load across the whole pass: 3.82–4.47 (1-min), `MemAvailable`
3,822–3,918 MB, `SwapFree` 3,419 MB — the hard floor never fired, and the only local execution was
one markdown-only guard run at `nice -n 19` that took **0.649 s**.

## 1 — the four landings, each with the hosted evidence that permitted it

| Landed sha | What it carried | Hosted verdict at that sha |
|---|---|---|
| `a51c0c4` | q4's onboarding merge (device fingerprint + 3-day trial modal) | `🔨 CI — Android Build & Test` **success** on both refs |
| `cc5f393` | the release-truth docs rewrite + the three re-pinned guard laws | `🐍 Backend CI` **success ×3** *and* `🔨 Android` **success ×3** |
| `787a1f2` | `App/docs/Q4_DEEPLINK_FINDINGS.md` + q4's slice-scoped `PlayerBufferingTest` guards | all **3** check runs `completed / success` |
| `52331af` | q2's Hum TV status + the documentation-diet rotation out of `Fast_Fetch/CONTINUITY.md` | `🔨 Android` **success**; `🐍 Backend` green at its docs parent `8caaed5`; guard re-run locally at the merged tree — see §3 |

Both refs now sit at `52331afd385a841e797d98404eeeab032a0e57ec`, verified with
`git ls-remote https://github.com/rehanradd/radd-stream.git refs/heads/master refs/heads/main`
after each push, not before. Every push was
`GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=<temporary askpass> git push <explicit clean URL> <sha>:refs/heads/<ref>`
— never `origin`, whose stored URL still carries the owner's unrevoked token — and no token was
printed, logged or placed in a URL, an argument or a file.

## 2 — `q2-dashboard` is refused, and the reason is a credential leak rather than a style opinion

The branch's *boundary* design is correct: `OPERATOR_ONLY_PREFIXES = ("/admin", "/operator")` and an
`_operator_gate` that answers an identical 401 for a wrong and a missing token, so the console cannot
be probed for token validity. What makes it unlandable is the login form it ships:

```
viewer.py:4338-4343   <form class="box" method="get" action="/operator/">
                      <input type="password" name="token">
```

A `method="get"` form whose field is named `token` puts `RADD_ADMIN_TOKEN` into the **request URL**.
That value then lands in nginx access logs, in browser history, in the `Referer` of every asset the
page loads, and in `history.pushState` if the operator reloads after signing in. It is the one thing
the operator credential is not supposed to become.

**Why "it is not logged today" is not a defence.** `log_message` is overridden at `viewer.py:3954` and
suppresses the URL today. That is exactly the kind of thing a later refactor drops — a guard that
lives in a logging cosmetic protects nothing, whereas a `method="post"` form (or one that writes the
token to `localStorage` and reloads) makes the leak structurally impossible. Verdict sent to q2:
fix the form, re-push on their branch, hand me the sha. No other lane's branch touches this file, so
nothing else waits on it.

## 3 — a trap that will bite every supervisor after me: `FETCH_HEAD` is shared, and the merge's push-diff is not the merge's content

Two measured findings, both of which changed a decision mid-pass.

**3a — never read `FETCH_HEAD` in this repo.** `git fetch <url> refs/heads/q1-humtv-docs-candidate`
in the shared `/opt/radd-stream` checkout printed `FETCH_HEAD=787a1f2…` — trunk, not the branch I
fetched. Another lane ran its own fetch between my fetch and my read, and `FETCH_HEAD` is one file
for the whole worktree. The empty `git diff 787a1f2 FETCH_HEAD` that followed read, for about a
minute, as "my candidate is identical to trunk, the Hum TV docs vanished in the merge". They had not.
The fix is to fetch into a lane-private refspace and resolve *that*:

```
git fetch <url> +refs/heads/<branch>:refs/remotes/q1sup/<branch>
git rev-parse refs/remotes/q1sup/<branch>     # not FETCH_HEAD
```

**3b — a merge commit can be green on one workflow and untested on the other.** Pushing `52331af`
onto a branch that already held `8caaed5` made the *push diff* `8caaed5..52331af`, which contains only
`App/**` files (trunk's content arriving by merge). `backend-ci.yml`'s `paths:` filter therefore
excluded it: `check-runs` at the merged sha lists **1** run (Android), while
`GET /actions/runs?branch=…` shows backend CI ran and passed at `8caaed5` and was `cancelled` for the
superseded Android run of the same commit. So "backend CI is green for this content" was true of the
parent, not of the tree I was about to land. Because `test_docs_invariants.py` is the guard that
catches a rotation losing a line, and a merge is precisely where a rotation can lose one, I ran that
module alone against the merged tree in a throwaway worktree — **18 tests, OK, 0.649 s** — rather than
land on an inference. It is the lane's own module plus nothing else, which is q4's standing rule.

Corollary for whoever reads a red/green list next time: a branch tip whose push-diff touches only one
side gets exactly one workflow, and `check-suites`/`check-runs` counts are not a proxy for "both gates
ran on this tree" — this is the second time today an empty-or-partial run list was about to be
misread, the first being `af68450` where two green check-suites were backend CI on two refs and the
Android workflow had **zero** runs at that head.

## 4 — `q1-ad-cadence` is superseded, and "it is green" was not the reason to merge it

Diffing trunk→branch (`git diff --stat <trunk>..<branch>`) printed **−771 lines**. The branch does not
add ad-cadence work; it *removes* tests and guards that trunk already carries as `9172809` + `68f0def`
— it is an older cut of the same feature, re-based never. Its CI status is irrelevant: a green branch
that deletes trunk tests is a regression with a badge. Instructed q4 to re-merge `q1-identity-fix`
(`5e74aa2`) onto current trunk instead (real conflicts in `App/AGENTS.md`,
`data/ServerSettingsRepository.kt`, `viewmodel/SettingsViewModel.kt`, and the one behaviour that must
survive is a stored **43-char** key passing through `quickLoginKey()` unchanged), and to leave
`q1-ad-cadence` closed. Rule recorded for the fleet: **diff direction before verdict.**

## 5 — the 54-remote-head inventory, turned into a decision list rather than a prune list

`git ls-remote --heads` holds 54 refs. Classified by measured state, not by name:

- **Landed (this pass + prior):** `a51c0c4`, `cc5f393`, `787a1f2`, `52331af`, plus `4a8c163`,
  `5bf6e59`, `d9d3615` and everything already inside them.
- **Green and reviewed, still open:** `e6482e9` (q2-scenarios-fixes, +2,840 lines, includes a real
  `/api/m3u` 400 fix), `2be6a86` (q3-launch-reads, bounds `/api/sitemap`), `7c36cec`
  (q3-engagement-ladder), `36a47a2` (q5-adultkey-prod-gap, docs). Four merge candidates for the next
  window, each needing its own tree-level guard run per §3b.
- **Red and diagnosed, not merged:** `q3-adultkey-net` (`765f297` — `Fast_Fetch/CONTINUITY.md` at
  13.9 KB / 139 lines against the 12,000 B / 120-line ceiling), `q2-dashboard` (§2),
  `q1-ad-cadence` (§4), and the inventory guard that was red on its own head.
- **Owner-only, never mine:** the ~31 stale heads and 97 registered worktrees are *pruning*, an owner
  action — deleting a branch is not housekeeping an agent may do to make a list shorter.

## 6 — who owes what next

| Lane | Owed | Blocking |
|---|---|---|
| q2 | the `method="post"` operator form, re-pushed with a sha | nothing else; Hum TV **ingest** and the dub-collision census stay queued in `CONTINUITY.md` "🕒" rows 5–6 until load1 < 3.5 |
| q3 | the coins-engine sha (`/api/v2/account/coins*` + `test_coins_engine.py` + a CI step) — trunk still shows none started; rebase `q3-adultkey-net` under the ceiling (**compress, do not delete**); answer the phone-derived-key question with file:line | the hosted gate is mine to run, not theirs |
| q4 | `q1-identity-fix` re-merge (§4) | no Gradle while the owner's hold stands |
| q5 | audit the remaining `test_docs_invariants.py` pins for other state-shaped strings (the `currently absent` pin proved that a guard can enforce a lie) | nothing |
| Owner | re-enter `KEYSTORE_BASE64` (the stored value is malformed — `Last unit does not have enough valid bits`), then the first real signed release; deploy trunk to the service (production is still pre-adult-fold); the §13 hue call; `DynamicServerDiscovery` and episode-offset keep-or-cut; `subtitled` deploy note; the dead `v1.0.0` tag at `6a441ec77` stays where it is until he moves it | every one of those is an owner action by rule |

**What this pass does not claim.** Nothing here was run on a device, no signed artifact exists, no
production behaviour changed, and the four landings are repository state — not deployment state. The
Hum TV crawl number in the checkpoint is a *plan with a measured price*, not a result: the importer
exists, is import-clean, and is byte-identical to `296ac5e`; the catalog it will write does not exist yet.

## 7 — the follow-up pass (same day, ~20:4x host): §5's "still open" list dispositioned

§5 is superseded by this section for three of its four items. What happened after the four landings,
each judged by a measurement rather than by the branch's name:

| Item as §5 left it | Measured outcome | State |
|---|---|---|
| `e6482e9` "green and reviewed, still open" | cherry-picked to `q1-edge-scenarios-20261031` (`89a1597` → `8137b16`), **hosted RED on exactly one step** | split — see below |
| `2be6a86` q3-launch-reads | `git cherry` said `+` (un-landed), which was **wrong**; the files are byte-identical to trunk (`git diff --numstat` empty) and its CI step is already present | closed as absorbed, **not** merged |
| `7c36cec` q3-engagement-ladder | same test: absorbed; merging it would have resurrected the deliberately retired `App/.github/workflows/*.yml` | closed as absorbed |
| `36a47a2` q5-adultkey-prod-gap | merged as `ae8f86d`, both workflows green at that head, two shared-index conflicts resolved by keeping every entry | **landed** |

**The split is the part worth keeping.** `8137b16` failed 5 of 22 cases in
`🧪 test_public_edge_scenarios.py` — and *not* because of the fix it carried. Root cause: trunk
`9859b8a` made **every** route on the operator port bearer-gated ("the loopback interface is not a
credential"), so four of the five fail on `401 != 404/200` before any route-level answer is reached,
and the fifth is a `KeyError: 'success'` on the 401 body. The fifth is different in kind:
`test_b_a_legacy_twin_is_closed_by_the_documented_repair` asserts a **key**-level
`redact.link_is_adult`, and trunk's is **per-row** — the 442 mixed-flag `canonical_key` hole that
root `AGENTS.md` still documents as open. So I did not merge the fix behind a red suite and I did not
weaken the suite: I cherry-picked the 9-line `/api/m3u` guard alone onto trunk as
`q1-m3u-400-20261031` = `5cde741` (`Fast_Fetch/viewer.py`, one file, +9/−1), gated it hosted — 35
`🧪` steps, job `124580818635` all green, zero non-green steps — landed it to `master` and `main`,
and re-measured **both trunk runs at the new head**: `41216445749` (master) and `41216459743` (main)
both `completed / success`. The failure list went to q2 verbatim, with the policy attached: fix the
transport, do not soften the adult assertion, and either gate case 5 on the repair existing or move it
to what trunk enforces today. Also re-flagged for that lane: `/api/health-check` still does the same
bare `int(query_params.get("id", [0])[0])` the m3u route just stopped doing.

**Two traps this pass re-confirmed.** (a) A `check-run` id is **not** a workflow-run id —
`/actions/runs/124580818635/jobs` answers 404, and the run is `41216095937`, read out of the
check-run's `details_url`. Query the jobs of the *run*. (b) A one-file `Fast_Fetch/**` push answers
exactly **1** check-run for the branch, because `ci.yml` filters on `App/**` — that is the filter, not
a missing gate; `/actions/runs?branch=<b>` is where you see the other workflow's history.

**What this section does not claim.** Production is untouched — `radd-stream.service` was not
restarted, so the live process still predates this fix; `8137b16` stays red and unlanded; `v1.0.0` is
still not tagged; no Gradle, no crawl, no production read ran here (load 3.4–7.0 all pass), and the
only local execution was the markdown guard.
