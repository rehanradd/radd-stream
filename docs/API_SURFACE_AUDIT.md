# API Surface Audit — every route, three vantage points, measured

Written 2026-10-29 after the public edge was re-audited end to end. Every number below is
a response this host produced, not a claim copied from another document. Where an earlier
document said something different, that document is wrong and is named in
[Retractions](#retractions).

Scope: what a caller can actually reach on `http://92.4.95.252/`, on the two loopback
ports behind it, and what nginx decides in between.

---

## 1. The edge: what nginx forwards, and with what limits

From `/etc/nginx/sites-enabled/radd-stream`, `/etc/nginx/conf.d/radd-stream-rate-limit.conf`
and `/etc/nginx/proxy_params` (read in full, 2026-10-29).

`limit_req zone=radd_stream_api` is `rate=10r/s` keyed on `$binary_remote_addr`. Every
forwarded route is `limit_except GET HEAD { deny all; }` except `/api/v2/account*`, which
also allows POST/PUT/DELETE.

| Route at the edge | Form | burst | `proxy_read_timeout` | Verbs |
|---|---|---|---|---|
| `/api/v1/posts` | prefix | 30 nodelay | 15 s | GET HEAD |
| `/api/v1/stats` | exact | 30 nodelay | 15 s | GET HEAD |
| `/api/v1/stream` | prefix | 30 nodelay | 15 s | GET HEAD |
| `/api/v1/app/remote-config` | exact | 30 nodelay | 15 s | GET HEAD |
| `/api/v2/account*` | `^~` prefix | 30 nodelay | 15 s | GET HEAD POST PUT DELETE |
| `/api/v1/search/by-media` | exact | 20 nodelay | **30 s** | GET HEAD |
| `/api/v1/download` | exact | 20 nodelay | **30 s** | GET HEAD |
| `/download/` | static alias | — | — | served from `/var/www/download/` |
| `^~ /api/` | prefix | — | — | **403 — everything not listed above** |
| `/` | catch-all | — | — | proxies **code-server** on `127.0.0.1:8443`, not the app |

Two properties of that config are worth stating plainly because they shape the failure
modes below:

1. **`limit_req_status` is not set anywhere.** nginx's default for a request over the
   limit is **503**, not 429. A client that behaves correctly and simply asks too often is
   told *the service is broken*, and a client that retries on 503 will retry. The
   application's own 429 (`redact.limiter`, `viewer.py:3074`) is a *second*, separate
   ceiling that a caller can reach only if it survives the first.
2. **The edge is the only working per-IP control today**, because the application bucket
   was keyed on a header the caller types (§3).

---

## 2. Measured matrix

All edge rows are `127.0.0.1` on this host, which is the same nginx the public IP uses;
`000` means curl gave up at the `-m` deadline.

### 2.1 Post-restart, 19:17–19:20 (cold caches)

| Request | Status | Bytes | Time |
|---|---|---|---|
| `/api/v1/posts/159` (flagged) | **404** | 45 | 19 ms |
| `/api/v1/posts/158` | 200 | 98,502 | 255 ms |
| `/api/m3u?id=159` | 403 | 146 | 5 ms |
| `/api/m3u?id=158` | 403 | 146 | 3 ms |
| `/api/m3u` | 403 | 146 | 7 ms |
| `/api/v1/app/remote-config` | 200 | 570 | 19 ms |
| `/api/v1/stream?id=1` | 400 | 56 | 29 ms |
| `/api/v1/download?id=1` | 400 | 56 | 40 ms |
| `/api/v2/account/ping` | 404 | 220 | 90 ms |
| `/download/radd-stream.apk` | **200** | header 320 | — |
| `/download/` | 403 (directory index; `autoindex off`) | 148 | — |
| `/api/v1/posts?page=abc` | **502** | 150 | 48 ms |
| `/api/v1/stats` | **000 at 15.005 s** | 0 | exceeded nginx's 15 s |
| `/api/v1/search/by-media?q=ra` | **000 at 15.002 s** | 0 | *would have* 30 s at the edge |
| `/api/v1/posts?limit=1..100` (default) | 200 | 11.5 KB | ~296 ms |

`/api/v1/posts` answers `total=135731` and, whatever `page_size` is set to, `limit=20`
with 20 items — see §4.2.

### 2.2 The two loopback ports, 18:5x (pre-restart)

Neither `127.0.0.1:8080` nor `:8081` is bound beyond loopback and nginx forwards neither
directly; `8081` is the operator port.

| Path | `:8080` (public app) | `:8081` (operator) | Edge |
|---|---|---|---|
| `/` | 1,355 B page | **46,476 B dashboard, no token** | code-server |
| `/client` | 20,510 B PWA | — | 401 (code-server) |
| `/admin` | — | **401 without `RADD_ADMIN_TOKEN`** | 401 |
| `/api/v1/rules` | 404 | **200** | 403 |
| `/api/v1/stats` | 200 | 200 with a *bogus* bearer token | 15 s timeout when cold |
| `/api/v1/posts/158` | 98,000 B | **179,543 B** (provenance present) | 200 |
| `/api/m3u?id=159` | 200, **0 bytes** | 200, **0 bytes** | 403 |
| `/api/m3u?id=158` | 200, real playlist | 200, real playlist | 403 |
| `/api/health-check` | — | **ran 25,481 ms then timed out, unauthenticated** | 403 |

**The operator port's trust boundary is the loopback interface, not the token.** The
token gates `/admin` only; the dashboard HTML itself, `/api/v1/rules` and `/api/v1/stats`
answer on `:8081` to anything that can open a loopback socket, including any process on
this VM and any other agent lane. That is the accurate description; "token-gated" is not.

`/api/m3u?id=159` returning **200 with zero bytes** rather than 403/404 is a *correct
outcome* (nothing is listed, nothing plays) reached by an uninformative status code.

---

## 3. The limiter was minting unlimited buckets (fixed, not yet deployed)

`redact.client_ip` (`Fast_Fetch/redact.py:1176`) keyed the application rate-limit bucket on
the **leftmost** `X-Forwarded-For` entry — a string the caller types. Proof, three requests
to the live edge with three different invented values:

```
X-Forwarded-For: <missing>  → RateLimit-Limit: 60  RateLimit-Remaining: 59
X-Forwarded-For: 1.2.3.4    → RateLimit-Limit: 60  RateLimit-Remaining: 59
X-Forwarded-For: 9.9.9.9    → RateLimit-Limit: 60  RateLimit-Remaining: 59
```

Every spoofed value restarted the budget, so the 60/60 s "browse" ceiling was decoration,
and only nginx's `10 r/s` was real. The same bug had a human cost in the other direction:
through a carrier NAT or a stranger's proxy, an honest user inherited whichever bucket some
other caller's header text named.

`/etc/nginx/proxy_params` sets `X-Real-IP $remote_addr` and overwrites whatever the caller
sent, and `$remote_addr` at nginx *is* the address `limit_req` counts. The fix keys on that,
falls back to the **rightmost** XFF entry (the one our own proxy appended), and trusts no
forwarded header at all when the socket peer is not loopback — i.e. when the request never
came through the proxy we ship. Regression test:
`test_the_bucket_key_is_the_address_the_edge_saw_not_the_one_claimed` in
`Fast_Fetch/test_redact.py`.

Not deployed: the running service loads `/opt/radd-stream`'s tree (§5).

---

## 4. Parameter truth (two things I got wrong first)

### 4.1 `?page=abc` was a free 502 for anyone
`viewer.py` parsed `page` with a bare `int()`; a non-numeric value raised out of the handler,
the connection closed without a response, and nginx answered **502**. Measured above, and
the same class of crash is in the journal on its own:
`ValueError: invalid literal for int() with base 10: '1/v1/models'`.
Fixed by `viewer.bounded_int()` — malformed or out-of-range input falls back to the
documented default inside the documented band (`page` 1..1,000,000, `limit` 1..100), with
`test_a_non_numeric_pager_is_answered_not_crashed` covering it.

### 4.2 There is no `page_size` parameter — my earlier "11 KB for one post" was my error
`/api/v1/posts` reads only `limit` (`viewer.py:3230`, clamped to 100) and `page`; the response
echoes `limit` and `page`. `page_size` is ignored and `limit` stays at its default 20, so an
11 KB body for `?page_size=1` was 20 items, not one. No Kotlin client and no backend module
references `page_size`. **A caller that assumes `page_size` will silently page through the
catalog 20 at a time forever** — that matters for the sellable API, so the parameter name is
now documented rather than inferred. It also means my `page_size` sweep never asked for more
than 20 rows: it is not what exhausted memory (§5).

### 4.3 `/api/v1/search/by-media`
`limit` is read with a `try/except` (defaults to 10) but is **not** magnitude-clamped; the real
bound is downstream — `media_search.py:42 CANDIDATE_WINDOW = 200`, applied as
`min(CANDIDATE_WINDOW, max(limit * 4, limit))`. A huge `limit` therefore cannot amplify work,
but the *window* it chooses is what makes this route slow: the `LIMIT` bounds the response,
never the scan (`SCAN p`, two `USE TEMP B-TREE FOR count(DISTINCT)`, one `FOR ORDER BY`, and
**no index on `clean_title` or `title` at all**).

---

## 5. The OOM incident, and what it says about capacity

At **19:14:31** the kernel killed the service:

```
Out of memory: Killed process 265554 (python3) total-vm:9552712kB, anon-rss:8038108kB
oom-kill: ... task_memcg=/system.slice/radd-stream.service
radd-stream.service: Consumed 45min 19.011s CPU time, 7.5G memory peak, 1.3G memory swap peak
```

invoked by a `copilot-runtime` allocation, i.e. the whole VM was out, and the service was
the largest eligible victim. systemd restarted it at 19:14:36 (the unit has `Restart=`), so
the site flapped without anyone deciding to restart it.

Consequences, all measured after the fact:

- **What the restart loaded** is `/opt/radd-stream`'s working tree: commit `bf9e565` **plus ten
  uncommitted edits from other lanes** (`redact.py`, `viewer.py`, `catalog_v2.py`,
  `test_catalog_api.py`, `test_merge_catalogs.py`, `SITES.md`, `AGENTS.md`, `CONTINUITY.md`,
  `importers/convert_mp4moviez.py` + its test) **plus nine untracked files**. `git merge-base`
  says the live tree and the pushed tip (`7736bcc`) **diverged at `19abff7`**: the tip is 35
  commits ahead, the live tree 2 (`5446771`, `bf9e565`). So production does not contain
  `34f22c6` (the stats fix) or anything after it, and the tip does not contain `5446771` —
  the fix for the 9 hosted test failures and 23 lint errors, which has **never been run by
  CI**, because it was never pushed. `5446771` is now preserved at local ref
  `salvage/live-tree-ci-fix-5446771` so a `git reset` of the live tree cannot destroy it.
- **The adult invariant still holds after the restart** (§2.1): flagged post 404, `/api/m3u*`
  403 at the edge. This was the first thing checked, before anything else.
- **`/api/v1/stats` and `/api/v1/search/by-media` are unavailable at the edge while the
  process warms** — both exceed the 15 s `proxy_read_timeout`. Staleness is the cheaper
  version of this defect; cold-cache absence is the expensive one.
- **Capacity, honestly**: the service was at **8,038,108 KiB anonymous RSS** when it was killed,
  but 28 minutes after the restart, answering ordinary requests, it sits at **65,892 KiB**. So
  ~7.7 GiB is not this process's resting size — it is a *transient* peak that some large read
  produces (the full-ledger surfaces and a cold `/api/v1/stats` rebuild are the known ones),
  which is exactly why `VmHWM` and not `VmRSS` is the metric to plan against. At the moment of
  the kill the fleet was also holding ~3 GiB across four `qodercli` runtimes, ~1 GiB of JVM and
  the local model, with swap 4.7/6.1 GiB used and a 15-minute load average of 16.59, and the
  apply/backup job was walking the 6.4 GB catalog. **The fleet and the API cannot both run at
  peak on this box.** Any job that walks the whole catalog (a merge, a backfill, a projection
  rebuild) is a candidate OOM while lanes are active, and the next victim may be a lane's
  process instead. Heavy catalog work waits for the lanes to go idle; that is why merge batch 4
  is still held even though its backup gate is now satisfied.

One thing I caused and must own: I fired `GET /api/health-check` at `:8081` during the audit.
It is an unauthenticated-on-that-port route that runs long outbound probes on a daemon thread;
it ran 25,481 ms and timed out on my client while the work continued server-side. It added load
to a machine that OOM-killed minutes later, and probing it again on a production host is not
something to do to learn a status code.

---

## 6. Open defects, ranked by what they cost a user

| # | Defect | User-visible cost | Status |
|---|---|---|---|
| 1 | search scans 135,731 posts with no index on `clean_title`/`title` | the first read a phone makes; 15 s at the edge when cold | diagnosis + plan handed to the app-lane; `q=a` was **not** fired at production to measure it further |
| 2 | `/api/v1/stats` rebuilt synchronously under a cold cache | 503 for up to 15 s after every restart | fix exists at the tip (`34f22c6`), not deployed |
| 3 | app limiter keyed on caller text | abuse ceiling effectively nginx-only; honest NAT users share strangers' buckets | fixed in code + test, pending deploy |
| 4 | `?page=abc` → 502 | unauthenticated crash-response, free for anyone | fixed in code + test, pending deploy |
| 5 | no `limit_req_status` | over-limit clients get 503 and retry harder instead of backing off | config change, needs owner sign-off (touches nginx on a live host) |
| 6 | operator port answers without its token | any local process reads the full ledger and `/api/v1/rules` | loopback-only by design today; document as such, or bind the dashboard behind the token too |
| 7 | `page_size` silently ignored | a client pages 20 forever and thinks it fetched everything | documented; consider honoring it as an alias only if a client ever asks |

---

## Retractions

- "`/download/` is a dead public APK path" — wrong. The **directory** 403s because
  `autoindex off`; `/download/radd-stream.apk` answers 200 and the file is there
  (22,738,552 bytes, plus `radd-stream-android-bundle.zip`).
- "`page_size=1` returned 11 KB, so the parameter is ignored in a dangerous way" — the
  conclusion was right that it is ignored, but the framing was wrong: it is ignored because
  **it has never existed**, and the body was the ordinary 20-item page. Neither this nor the
  sweep caused the OOM.
- "the deployed stats are stale but serving" — after a cold restart they are not serving at
  all; they blow the edge timeout. Staleness was the mild symptom.
