# Documentation re-scan, 2026-10-30 — record only

**Scope of this file:** q4-master's queue item (b) — *"re-scan `App/docs` and `docs/` for any
other claim stated in present tense that a 2026-10-30 measurement contradicts"*. It is a
**record**, not a fix: nothing below is edited here, because the brief said record-only. Each
hit gives the location, the claim as written, the measurement that contradicts it, and the
one-line replacement its owner can apply.

**Measured against:** the working tree at `8935d49` (`/tmp/q3_docfix`, q3 lane) plus the
deployed tree's own HEAD as a read-only `git -C /opt/radd-stream show`, and
`systemctl is-active`. No file outside the worktree was written; `/opt/radd-stream` was read
with `git show` / `rev-parse` only, never as a workspace. No request was fired at the public
edge for this scan, and no production database was opened.

**Not touched:** claims already marked historical or corrected in place. `docs/PROJECT_MAP.md`
and `App/docs/PLAYER_SPEC.md` carry dated ⚠️ CORRECTED blocks that quote the old wording and
then retire it; those reads correctly, so they stay. The three files q4 already corrected at
`079fcbb` (`AGENTS.md` root, `ANTIGRAVITY_HANDOFF.md`, `docs/SENIOR_MENTOR_DIRECTIVE_QODER.md`)
were not re-edited either.

## 1. The measurement set

| What | Where | Value |
|---|---|---|
| Bearer-token parsing exists | `Fast_Fetch/viewer.py:393` | `def _bearer_token(headers)` reads `Authorization: Bearer …` |
| Capability check exists | `Fast_Fetch/viewer.py:401` | `request_is_vip()` — sync account with live `vip_until`, or a server-minted signed pass; the docstring says a typed `vip=1` is deliberately not trusted |
| Every public request is rate-limited | `Fast_Fetch/viewer.py:3134-3158`, called at `:3206` (GET) and `:3569` (POST) | `_public_gate()` → `redact.limiter.check(self._bucket_for(path, method), client_ip)`, attaches the `RateLimit-*` triple, answers 429 (v2 problems+`Retry-After`, v1 `error="rate_limited"`), and 404s `OPERATOR_ONLY_ROUTES` at the edge |
| Bucket table | `Fast_Fetch/api_v2.py:212` `ROUTE_BUCKETS` + `:236` `ROUTE_ARITY` | 16 route heads: play, resolve, report, offset, browse, search, suggest, works, episodes, releases, manifest, stats, sync, collections, health, `feed.m3u`; `bucket_for()` falls back to `browse`, so a v1 path pays into a bucket too |
| CORS is an empty allow-list, not `*` | `Fast_Fetch/redact.py:1305`, `:1308` | `CORS_ALLOW_ORIGINS: frozenset[str] = frozenset()` and `cors_headers_for()` emits a header **only** for a listed origin; nothing anywhere assigns to it (grepped `Fast_Fetch/*.py`), and `Access-Control-Allow-Origin` appears **zero** times in `viewer.py` |
| v2 is dispatched by the server | `Fast_Fetch/viewer.py:3240-3246` | `if api_v2.is_v2(path): … api_v2.route_get(self, path, query_params, db_path=DB_PATH, …)` |
| The deployed tree has that code too | `git -C /opt/radd-stream show HEAD:…` | HEAD `bf9e565`; `viewer.py` contains `_public_gate` 4×; `redact.py:1278` is the same empty frozenset; `systemctl is-active radd-stream` → `active` |
| Downloads and Continue Watching exist in app source | `App/app/src/main/kotlin/com/raddstream/app/` | `ui/navigation/Screen.kt:34` `object Downloads : Screen("downloads")`, `ui/screens/DownloadsScreen.kt`, `data/downloads/DownloadService.kt`, `viewmodel/ContinueWatchingTile.kt`, `viewmodel/PlayerViewModel.kt`, `data/local/WatchHistory.kt` (+ `AppDatabase.kt`, `di/DatabaseModule.kt`) |
| Cast / DLNA / Android TV do not | same tree, grepped | zero hits for `CastButton`, `com.google.android.gms.cast`, `MediaPlayerSession`, `Dlna` |
| A per-phone attempt budget does not | grepped `Fast_Fetch/*.py` | no `per_phone` / `device_budget`; `BUCKET_LIMITS` (`redact.py:1108`) is documented in-file as per client IP |

**What these measurements are worth, and what they are not.** They are code facts: the gate,
the token parsing, the empty CORS allow-list and the route table exist and are wired at the
named lines, in the tree the service loads on its next start. They are **not** runtime proofs —
I did not fire a request at the public edge, I did not read `/api/data`, and I did not check
when the running process was started, so I cannot say the *currently resident* process answers
with `RateLimit-*`. Nor do the Kotlin files prove the feature works: the app's status line in
`AGENTS.md` is still "device verification pending", and CI green is a build+unit gate, not a
phone.

## 2. Hits — present-tense claims the table above contradicts

### H1 · `App/docs/TECH_STACK.md:48-51`
> "There is **no auth token injection to configure** — `viewer.py` implements no authentication,
> no API key, and no bearer token, and answers every response with
> `Access-Control-Allow-Origin: *`. … ⚠️ Reality (verified against viewer.py 2026-10-22)"

Contradicted by `viewer.py:393` (`_bearer_token`), `viewer.py:401` (`request_is_vip`),
`redact.py:1305` (empty `CORS_ALLOW_ORIGINS`) — and by the deployed HEAD `bf9e565`, which
carries all three. The date stamp makes it honest history only if it stops asserting "is".
**Replacement:** "`viewer.py` parses `Authorization: Bearer` for the sync-account and
signed-pass VIP checks (`:393`, `:401`), sends CORS only to an empty-by-default allow-list
(`redact.py:1305`), and rate-limits every public request (`_public_gate`); the app still has no
login screen to put a token in, and the deployed host is plain HTTP with no TLS."

### H2 · `App/docs/PLAN.md:256-258` (the §3.3 parenthetical)
> "A `token` field would be pointless today: `viewer.py` implements no authentication — no API
> key, bearer token, or session — and answers with `Access-Control-Allow-Origin: *`. Add real"

Same contradiction as H1, same replacement, shortened to the server-profile sentence: the token
field is still pointless **for the app's own reason** — there is no client-side login flow to
fill it — not because the server cannot verify one.

### H3 · `Fast_Fetch/AGENTS.md:836` (rule 9, "Public API exposure")
> "the current HTTP API has no authentication and wildcard CORS; secure or restrict
> fetch/heal/resolve routes before proxying them publicly"

The dangerous half of this is that it is *advice written off a stale premise*: an agent obeying
it today would go and "restrict routes" that are already edge-restricted
(`_public_gate` 404s `OPERATOR_ONLY_ROUTES`; nginx allow-lists the public routes) and would
still believe CORS is wildcard. **Replacement:** "the public API has a per-IP token bucket and
an empty CORS allow-list by default (`viewer.py:3134`, `redact.py:1305`) and no client login
flow yet — what remains exposed is metadata over plain HTTP: keep operator routes off the
public allow-list."

### H4 · `docs/PROJECT_MAP.md:161`
> "What remains true is the exposure that matters: the public edge is plain HTTP with no TLS,
> no API key, no session and no rate limit."

Three of the four are still true (plain HTTP, no TLS, no client session). **"no rate limit" is
not** — `_public_gate` runs `redact.limiter.check()` on every public GET and POST at the
checked-out tip *and* at deployed HEAD `bf9e565`. This is the highest-value hit in the file
because `PROJECT_MAP.md` is what every new lane reads first. **Replacement:** "…plain HTTP with
no TLS and no client session; per-IP rate limiting is in code (`_public_gate`,
`viewer.py:3134`) and nginx adds no `limit_req` of its own."

### H5 · `Fast_Fetch/API_V2.md:1317` (§17 checklist, first item)
> "- [ ] **All of Layer 2**: every `/api/v2` endpoint; `/manifest` content per §7.1."

Contradicted by `api_v2.py:212`/`:236` (16 heads with buckets *and* arity) and
`viewer.py:3240-3246` dispatching them, with `test_api_v2.py` asserting every route's bucket is
declared (CI step). **Replacement:** check the box for the route surface and leave the real
remainder explicit: "`/manifest` content per §7.1 and the Layer-2 response choosing measured
`rank_score` (§17 next item) are outstanding; the routes themselves are live in code."

### H6 · `App/docs/PLAN.md:296-298` (and the §3.2/§3.3 rows it summarises)
> "Still genuinely not implemented: Continue Watching, offline Downloads (DownloadManager),
> Cast/DLNA, Android TV."

Two of the four are in the tree: `ContinueWatchingTile.kt` + `WatchHistory.kt`/`AppDatabase.kt`
and `Screen.kt:34` `Downloads` + `DownloadsScreen.kt` + `DownloadService.kt`. Cast/DLNA and
Android TV are genuinely absent (zero grep hits). **Replacement:** "Not implemented: Cast/DLNA
and Android TV. Continue Watching and offline Downloads exist in source but are unverified on a
device — `AGENTS.md` still carries 'device verification pending'."

## 3. Checked and still true — do not re-litigate these

- `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md:132-136` — a per-phone budget "does not exist yet";
  correct, no `per_phone`/`device_budget` anywhere, `BUCKET_LIMITS` is still per client IP.
- `App/docs/PLAN.md:250-253` — §3.1 external-player hand-off `DetailScreen.kt` `ACTION_VIEW`
  chooser, and §3.2 Cast/DLNA ❌: both consistent with the tree.
- `docs/PROJECT_MAP.md:79` `tags: 0` / `releases: 0`, and the keystore-secrets block in
  `AGENTS.md` — measured earlier this session at `GET /actions/secrets → total_count: 0` and a
  `workflow_dispatch` release run that died at the signing preflight in 10 s.
- The Robolectric trap (`ScreenSnapshotTest`, `PosterCardProvenanceTest` excluded from every
  local arm64 run, only the hosted runner judges them) — still true, and still the reason a
  green local Gradle build proves nothing about those nine.
- Everything under `docs/SESSION_CHECKPOINT.md` with a date stamp in its own heading: it is a
  log. Line 1662's "Android CI is red … Now tasked" and line 2717's "the app lane is red again"
  are entries in dated blocks, not present-tense claims, and §2 of
  `docs/PROJECT_MAP.md` now carries the correction. Leave them.

## 4. Flagged to the owner, deliberately NOT edited

These assert a **production state or a production action**. Per the standing brief
(*"if a doc claims a production action — restart, swap, deploy, backfill — stop and flag it"*)
they are recorded here untouched, and I verified none of them beyond the two read-only facts in
§1 (deployed HEAD `bf9e565`, unit `active`):

- `docs/API_SURFACE_AUDIT.md:225` (row 2): "`/api/v1/stats` rebuilt synchronously under a cold
  cache — 503 for up to 15 s after every restart | fix exists at the tip (`34f22c6`), **not
  deployed**". Whether the resident process has that fix is a restart question, and restarts are
  the owner's call only.
- `docs/API_SURFACE_AUDIT.md:226-227` (rows 3-4): "**pending deploy**" twice — same category.
- `docs/API_SURFACE_AUDIT.md:228` (row 5): `limit_req_status` — "config change, needs owner
  sign-off (touches nginx on a live host)".
- `docs/FULL_MASTER_FEATURE_INVENTORY.md:1004` (D-18): "Working tree dirty (105 paths); HEAD not
  deployed". I did not inspect `/opt/radd-stream`'s working-tree cleanliness at all — git
  content filters are configured there, so a `git status` read would not be trustworthy anyway.
- Same file, D-19/D-20 (`:1005-1006`): admin token as a static systemd literal, HF token in an
  env file. Credential-handling claims about the live host — owner review, not an agent's.
- `docs/MONETIZATION_AND_FLEET_PLAN.md:71` / `docs/MONETIZATION_PILLARS_SCHEMA.md:210`: the
  withdrawal scheme "is not implemented and will not be". q5's `6bfbd5c` landed 16 operator
  engagement *knobs*; that does not make the withdrawal sentence wrong, but anyone editing
  those two files should re-read them against `MONETIZATION_FIELDS` (now 33 fields) rather than
  trust my line count.

## 5. What this scan did not cover

Two globs, one pattern set: `docs/**/*.md` and `App/docs/*.md` plus the root/`Fast_Fetch/*.md`,
searched for present-tense status verbs (`is red`, `disabled`, `never`, `not implemented`, `no
auth`, `no rate limit`, `no tests`, `not deployed`, `tags: 0`, `unimplemented`). It will miss a
stale claim that phrased itself differently. It says nothing about `README.md`, `DISCLAIMER.md`,
`ORACLE_DEPLOYMENT.md`, `Fast_Fetch/{DAO,SITES,CONTINUITY,ANDROID_INTEGRATION}.md` prose beyond
those patterns, and no doc was re-measured against the running service — the code and the
deployed *source* are all this file claims.
