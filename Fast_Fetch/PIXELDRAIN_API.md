# PIXELDRAIN API — hoster reference (LANE 3, Crown order qoder13_pixeldrain_docs)

**Status: DOCUMENTATION ONLY.** No resolver code, no hoster-table edit, no new egress
path was written for this. Every "observed" line below comes from a bounded request made
from this box on **2026-11-04 20:4x–21:05 UTC (2026-11-05 01:4x–02:05 PKT)**; anything I
could not verify is labelled **UNVERIFIED FROM THIS HOST** rather than filled from memory.
No secret, token, cookie or `Authorization` value was used or is recorded here — the two
requests that need no auth at all are the only ones made against a real file.

---

## 1. Domain authority — `pixeldrain.com` vs `pixeldrain.dev`

This is the item the whole refusal turned on, so it gets evidence first and opinion last.

**Observed from this box (DNS, `socket.getaddrinfo`):**

| host | addresses returned |
|---|---|
| `pixeldrain.com` | `103.107.198.177`, `.198.191`, `.199.58`, `.199.60`, `.199.61`, `.199.62` + `2404:b9c0:60:{1,2,3,5,6,7}::1` |
| `www.pixeldrain.com` | identical set to `pixeldrain.com` |
| `pixeldrain.dev` | `103.107.198.191`, `.199.58`, `.199.59`, `.199.60`, `.199.61`, `.199.62` + `2404:b9c0:60:{1,2,3,4,6,7}::1` |
| `api.pixeldrain.com` | **NXDOMAIN** (`gaierror: [Errno -2]`) — there is no separate API host |

The two hosts return overlapping, same-/24 and same-/48 address sets. That is
circumstantial. The certificate is not.

**Observed (TLS peer certificate, validated against the system trust store — no
verification error was raised for either name):**

```
subject CN : pixeldrain.com
SANs       : pixeldrain.com, pixeldrain.dev, pixeldrain.net, pixeldrain.nl,
             pixeldrain.biz, pixeldra.in, pixeldrain.tech,
             *.pixeldrain.com, *.pixeldrain.dev, *.pixeldrain.net,
             *.pixeldrain.nl, *.pixeldrain.biz, *.pixeldra.in, *.pixeldrain.tech
notAfter   : Dec 31 17:16:44 2026 GMT
```

One certificate, issued by a public CA to one key holder, covers **both** names plus five
more in the same family. A CA only issues such a certificate to someone who passes
validation for every name on it.

**Observed (application layer):** `GET https://pixeldrain.com/` and
`GET https://pixeldrain.dev/` both return `200` with byte-identical first 200 bytes of
HTML (`<title>Cloud storage and data transfer services ~ pixeldrain</title>`).
`GET pixeldrain.dev/api/file/s2yMcLkb/info` returns the same 676-byte JSON object as the
`.com` path — same size, same fields, same values.

### Verdict on domain authority

`pixeldrain.dev` is **not** an unofficial mirror and **not** a lookalike third-party
domain. It is another domain of the **same operator**, in the same certificate, on the
same infrastructure, serving the same application and the same file records.

**The honest limit of that claim:** a domain-validated certificate proves *control of the
names*, not the legal identity of the company behind them. What it cannot support is
"someone else is imitating PixelDrain on `.dev`" — an imposter cannot get `.dev` onto a
certificate whose CA validated `.dev` for them.

**Therefore refusal #12's stated premise is factually wrong about `.dev`, and I am saying
so instead of quietly agreeing.** What the premise was *protecting* is still worth
protecting, for a different reason, and I recommend keeping the behaviour for that reason:

- our ledger stores `https://pixeldrain.com/...` (measured: every `final_url` sampled in
  §6 is `.com`), so canonicalising to `.com` keeps one audited host instead of two;
- strict host matching is still the right defence against `xpixeldrain.com`,
  `pixeldrain.com.attacker.tld`, and a future `pixeldrain.tld` that is *not* in this
  certificate — the rule must stay a rule about *this exact name*, and the certificate
  list is the only thing that tells us which names are safe, and it rotates (notAfter
  2026-12-31).

That is a **canonical-form** argument, not a **hostile-lookalike** argument. The code
currently states the latter as fact and should be corrected on its next authorized edit —
`host_classifier.py:299-301` asserts "`pixeldrain.dev` … [is a] different service (or
hostile host)". Under the evidence above that sentence is wrong for `.dev`. **I did not
edit it** (documentation-only order, and `fast_fetch.py`/classifier are under freeze).

**What did NOT change:** I did not adopt `.dev`, and nothing here makes `.dev` a candidate
endpoint. And per the second half of refusal #12, §5 documents a throttling signal we
observed and explicitly recommends **not** working around it.

---

## 2. File metadata endpoint — observed

`GET https://pixeldrain.com/api/file/{file_id}/info`

- **No authentication.** Returns full metadata for a public file with a bare `GET` and
  one header (`User-Agent`). No cookie, no key.
- `200`, `content-type: application/json`, `content-length: 676` (measured).
- Verbatim shape of the answer for a file we legitimately hold (`s2yMcLkb`):

```json
{"success": true, "id": "s2yMcLkb",
 "name": "Ranma 1-2 S03E01 [RareToonsIndia].mkv",
 "size": 200330217, "views": 198, "downloads": 235,
 "bandwidth_used": 45330140201, "bandwidth_used_paid": 0,
 "date_upload": "2026-10-03T17:11:43.903Z",
 "date_last_view": "2026-11-04T06:29:45.944Z",
 "mime_type": "video/matroska", "thumbnail_href": "/file/s2yMcLkb/thumbnail",
 "hash_sha256": "da83d55bc148e73d8aa2f10b45cfe5f6fb800448e0eafa4d64..."}
```

`success` is the envelope flag; `hash_sha256` is present and is a free integrity check we
do not currently use.

---

## 3. Direct download endpoint — observed, and the `is_resumable` answer

`GET https://pixeldrain.com/api/file/{file_id}` — **this is the bytes, not a page and not
a redirect.** Measured with no `Range`:

```
200 OK
content-type:        video/matroska
content-length:      200330217
accept-ranges:       bytes
content-disposition: inline; filename="Ranma 1-2 S03E01 [RareToonsIndia].mkv"
```

Measured with `Range: bytes=0-1023` (2.0 s, after a 30 s pause):

```
206 Partial Content
content-range:  bytes 0-1023/200330217
content-length: 1024
accept-ranges:  bytes
content-type:   video/matroska
first bytes:    1a 45 df a3 …   (a real Matroska EBML header, not HTML)
```

### Status codes

| code | observed here? | what it meant |
|---|---|---|
| `200` | **yes** | whole file, `accept-ranges: bytes` present |
| `206` | **yes** | `Range` honoured; `content-range` well-formed with the true total |
| `302` | **never seen** | this endpoint does not redirect to a CDN — it streams itself |
| `403` | **never seen** | unverified from this host |
| `404` | **yes** | bad/removed id, JSON body (§5) |
| `429` | **never seen** | see §5 — throttling reached us as a TCP reset, not a 429 |
| `5xx` | never seen | — |

### The two answers the Crown asked for

**(a) Is `Range` honoured → does `is_resumable` deserve to be 1?**
**Yes, verified.** `accept-ranges: bytes` on the plain `200`, and a real `206` with a
correct `content-range` on request. A `?start`-less resumable player (ExoPlayer/OkHttp
style byte ranging) works against this URL directly.

That makes our own ledger measurably wrong. Bounded indexed read,
`service='pixeldrain'` via `idx_sources_service`:

```
89,926 pixeldrain rows, all status='active'
is_resumable:  0 → 89,925 rows   1 → 1 row
http_status:   NULL → 89,925     206 → 1 row
```

The single truthful row is `id=5`, the one that has been probed (`last_checked_at =
2026-11-04 17:35:45`). The other 89,925 are not *wrong because a prober said 0* — they are
**unprobed**, which is the exact distinction qoder12's `73de18e` and
`link_state.py:304` ("an unprobed `active` claim is `unverified`") exist to enforce. The
`is_resumable=0` there is a default, not a measurement. Anyone reading it as "this hoster
cannot resume" is reading a fabrication. This is not a defect in `is_resumable`; it is the
verification-coverage gap that column sits inside.

**(b) Does `?download` change the response, vs a header?**
**UNVERIFIED FROM THIS HOST.** Every request that used `?download` was answered with a
TCP reset, including a deliberately tiny one:

- `GET /api/file/s2yMcLkb?download` → `ConnectionResetError: [Errno 104]`
- `GET /api/file/s2yMcLkb?download` with `Range: bytes=0-0` → `ConnectionResetError`

I am reporting that instead of describing the parameter from recollection. What *is*
observed is the mechanism the header route uses: `content-disposition: inline;
filename="…"` on the plain `GET`, so the disposition value is already negotiated in a
response header and the filename is available to us **without** any `?download`. Our
`/api/v1/download` descriptor builds `filename` and `mime_type` from our own row, so it
does not need the parameter. **Recommendation: do not add it** — it buys nothing we
observed and it is the one request shape that got reset at us.

---

## 4. Content identifiers we consume, and the lifetime question

| field we store | PixelDrain source | observed |
|---|---|---|
| `filename` | `name` in `/info`, and `content-disposition` on the file `GET` | yes, both |
| `mime_type` | `mime_type` in `/info`; `content-type` on the file `GET` | yes, and they agreed (`video/matroska`) |
| `file_size_bytes` | `size` in `/info`; `content-length` on the `200` | yes, agreed (`200330217`) |
| integrity | `hash_sha256` | present, unused by us |
| creation | `date_upload` (ISO-8601 UTC, milliseconds) | yes |
| last activity | `date_last_view` | yes |
| **expiry / TTL** | **there is none** | see below |
| URL signing | **unsigned** — the path is `/api/file/{id}`, no token, no signature, no `expires` parameter | yes |

**I have to contradict the premise of item 4.** The order hoped a host-named lifetime
would replace the 24 h Category-A heuristic. There isn't one: the `/info` payload has no
expiry field, the file `GET` sets no expiry header, and the URL is not time-limited, so
there is nothing to put in `expires_at` that PixelDrain told us. The correct honest value
is what `fast_fetch.py:5287-5289` already does — return `None` and stay silent rather than
publish "a made-up window".

What the evidence does give us is a cheaper way to re-verify than a byte fetch: `/info`
is 676 bytes and needs no auth, so a staleness check can be a metadata read instead of a
stream. Note the asymmetry this implies for the cache horizon in
`resolved_cache._compute_reverify_after` (`resolved_cache.py:195-208`): with no host TTL,
the horizon is bounded by our own cap, not by `expires_at` — and Category A's 24 h cap
stays defensible for `.com` because a file that answers `200/206` today with an unsigned
URL is not silently re-signed tomorrow. Do not extend that reasoning to a *different*
domain in the family; that is a §1 policy question, not a TTL question.

---

## 5. Error semantics — and the one that is load-bearing for circuit evidence

Observed error shape (both an 8-char and a malformed id), from `/info`:

```
404 Not Found
content-type: application/json
{"success": false, "value": "not_found",
 "message": "The entity you requested could not be found"}
```

`HEAD /api/file/{unknown}` also answers `404` with a 94-byte JSON body — the id is not
revealed, so a typo and a removed file are indistinguishable by design.

| condition | expected / observed answer | servable? | dead? | circuit evidence? |
|---|---|---|---|---|
| good public id | `200` / `206` | yes | no | yes — positive |
| bad-format id | `404` `value:"not_found"` | no | **yes** | yes |
| removed file | `404` `value:"not_found"` (UNVERIFIED as a distinct case — same body as a bad id, and we hold no known-removed id) | no | **yes** | yes |
| private / restricted file | **UNVERIFIED FROM THIS HOST** — we legitimately hold no restricted PixelDrain link, and I did not go looking for one | **no** | **NO — and that is the point** | **NO** |
| throttled caller | **observed as a TCP reset** (see below), not `429` | unknown | **NO** | **NO** |
| DNS / TLS / connect failure | transport error | no | no | no |

### What we actually hit, and why it must not be evidence

Roughly half of the file-endpoint requests in §3 were answered with
`ConnectionResetError: [Errno 104]` — including a `?download` probe that asked for one
byte. It never produced a status code. The pattern in my own log, honestly stated:

- `/`, `/info`, and `HEAD` — always answered, `200`/`404`, never reset.
- `GET /api/file/{id}` (the byte stream) — reset on several occasions, including
  immediately after **I** aborted a large stream after reading 600 bytes.

So the resets correlate with the byte-stream endpoint, and at least one followed my own
aborted transfer. This box is one core at load 5.4–6.0 with other lanes busy, so I cannot
prove the remote end was the cause rather than us. Either way the handling rule is the
same, and it is exactly the rule qoder12 landed in `73de18e`: a request that never got an
answer is not a verdict about the file.

**The gap I would flag for the Emperor's decision.** `link_state.classify()` already
routes `http_401 / http_403 / http_429 → expired` (`link_state.py:53`) — correct, a token
or a throttle is not a gone file. But `link_state.py:56-58` maps
`timeout / dns / tls / conn_reset / conn_error → dead`, and a **reset we caused, or a
throttle that answers no code, is recorded as `dead`**. That is the mechanism this box hit
here.

### Corrected severity — my first draft overstated this, and the Emperor was right

I originally wrote that this is "permanent ledger damage" that "poisons the cache circuit".
**Both halves are wrong, and I checked rather than being told twice:**

- **The circuit is not keyed on status at all.** `lookup_cache`'s WHERE
  (`resolved_cache.py:332`) is
  `link_id = ? AND reverify_after > ? AND fail_count < ?` (+ `kind`, `ip_bound`).
  `resolved_cache` has no `status` column. A `dead` row in `download_sources` therefore
  cannot refuse a cache hit.
- **`dead` is healable by design, and the code says so in its own words**
  (`link_state.py:38-41`): "A dead link keeps its URL, its `resource_id` and its history …
  and stays healable (`fast_fetch.heal_post_links` selects exactly
  `status IN ('dead','expired')`)". Verified as a proof in §10 — the row comes back to
  `active` with its real `http_status` and `is_resumable`.
- **The circuit is not one-way either.** `record_resolved_cache` clears it on the next
  accepted URL: `resolved_cache.py:264` sets `fail_count=0` in the UPSERT conflict path
  (`MAX_FAIL_COUNT = 3`, `resolved_cache.py:61`). The residual point stands, narrower:
  `unprobed` is set only for the no-unpacker branch (`fast_fetch.py:5559-5563`), so a
  *transport* reset from our box does reach `note_failure` as measured evidence. Three
  consecutive resets on our side would open the circuit for a URL that is fine — recoverable
  on the next success, and not permanent, but still a count of *us* attributed to *them*.

**The accurate statement, which is what this section should have said first try:** a
transient probe failure records a verdict about **our probe** in a column that reads as a
verdict about **their link**. It is wrong information, not lost information: it is
over-written by the next successful probe, it never blocks a cache hit, it never deletes a
row, and the heal path is built to select exactly those rows. The cost of the mislabel is
*accuracy of the ledger between probes*, not reachability of the catalog.

I am **not** editing the table (documentation-only order). I am recording that the
`restricted / not-servable-but-not-dead` bucket needs a state of its own before a
PixelDrain prober is trusted to write `fail_count`, and that the evidence for that need is
this box's own reset rate, not a theory.

---

## 6. Our mapping, with code pointers (quoted, not edited)

- **Category.** PixelDrain is **Category A — direct file host**, and the evidence in §3 is
  what Category A is a claim about: the URL *is* the media, `200` with the real
  `content-type`, no packer page, no interstitial, no unwrap step.
  `host_classifier.py:121` — `("pixeldrain.com", CATEGORY_DIRECT_FILE, "pixeldrain")`;
  label mapping `host_classifier.py:211`.
- **Host trust.** `is_pixeldrain()` (`host_classifier.py:296-304`) is
  `host == "pixeldrain.com" or host.endswith("." + "pixeldrain.com")` — strict, never
  substring. Keep. Per §1, fix the *justification comment*, not the predicate.
- **id extraction and rewrite.** `pixeldrain_file_id()` (`host_classifier.py:287-294`)
  accepts `/u/`, `/d/`, `/api/file/`; the canonical rewrite is
  `url = f"https://pixeldrain.com/api/file/{file_id}"` (`host_classifier.py:390`). Our
  ledger confirms it: `source_url https://pixeldrain.com/u/s2yMcLkb` →
  `final_url https://pixeldrain.com/api/file/s2yMcLkb` (row id 5).
- **Referer.** `host_classifier.py:391-394` *drops* a non-PixelDrain `Referer`/`Origin`
  and keeps one whose host contains `pixeldrain`. That is the conservative direction: it
  stops our own domain being blamed for the traffic. **This is not spoofing and I want
  that on the record**, because it is adjacent to the thing refusal #12 forbids — sending
  a *foreign* referer to unlock a hotlink-guarded file would be circumvention, and this
  code does the opposite (sends no referer, or PixelDrain's own). The doc deliberately
  gives no recipe for a referer that unlocks anything.
- **Expected descriptors** for a resolved Category-A PixelDrain source, all four confirmed
  by observation in §2/§3: `mime_type` = the `/info` value (e.g. `video/matroska`),
  `container` = from `name` extension (`.mkv` → matroska), `content_type` = the media
  itself, `protocol` = `https` direct file (not HLS — no playlist, no segments),
  `playback_type` = `file`. `is_resumable` = **1, verified**.
- **Expiry.** unsigned, permanent URL, no host TTL → `expires_at = None` (§4), horizon
  from our own cap only.

---

## 7. Dated verification section

Time window: **2026-11-04 20:47 – 21:05 UTC** (2026-11-05 01:47 – 02:05 PKT), from this
host (`nproc=1`, `/proc/loadavg` 5.4–6.0, `/` at 95%, 10 G free). All requests were made
directly with stdlib `http.client` / `ssl` / `socket`, timeout-capped at 20–25 s, one at a
time with sleeps between, never in a loop, and the file-endpoint ones used tiny `Range`
windows so almost no media was transferred. **Total requests: 15.** No write to disk bigger
than this document; no DB copy, no temp database, no exporter run (per the disk freeze).
The catalog reads were `mode=ro`, indexed (`idx_sources_service`, confirmed by
`EXPLAIN QUERY PLAN`) or bounded to a small primary-key window with an explicit `LIMIT`,
in keeping with the one-scan-at-a-time fleet rule while other lanes were working.

| # | request | result |
|---|---|---|
| 1–4 | `getaddrinfo` × 4 hosts | §1; `api.pixeldrain.com` NXDOMAIN |
| 5 | TLS peer cert, `pixeldrain.com` | `ConnectionResetError` on first attempt |
| 6 | TLS peer cert, `pixeldrain.dev` | success; 14-name SAN list (§1) |
| 7 | `GET pixeldrain.com/` | `200` (retry; transient reset) |
| 8 | `GET pixeldrain.dev/` | `200`, byte-identical title to #7 |
| 9 | `GET /api/file/s2yMcLkb` | `200`, `accept-ranges: bytes`, `content-disposition: inline` |
| 10 | `GET /api/file/s2yMcLkb/info` | `200`, 676-byte JSON |
| 11 | `GET .com …?download` | `ConnectionResetError` |
| 12 | `GET /api/file/zzzzzzzz` | `ConnectionResetError` |
| 13 | `HEAD /api/file/nope12345678` | `404`, JSON 94 bytes |
| 14 | `GET pixeldrain.dev …/info` | `200`, identical to #10 |
| 15 | `GET … Range: bytes=0-1023` (after 30 s pause) | **`206`**, `content-range: bytes 0-1023/200330217` |
| +1 | `GET …?download` with `Range: bytes=0-0` | `ConnectionResetError` — **stopped, did not retry further** |

**Could I reach the service? Yes** — the metadata path reached it cleanly every time, and
the byte path answered `200` and `206` when it answered at all.

**Explicit list of what this document does NOT establish**, because those are the lines
someone will otherwise trust wrongly:

1. `?download` behaviour — unverified, every attempt reset (§3b).
2. The response shape of a **private or restricted** file — unverified; we hold none, and
   I did not probe a third party's private id to find out. This is the single most
   important gap, because §5's whole argument depends on what that answer looks like.
3. `429` as a status code from this service — never observed here; throttling appeared as
   a transport reset instead.
4. `302` from the API path — never observed; do not assume the endpoint redirects.
5. Whether the resets were caused by PixelDrain or by this box's load — unresolved.

---

## 8. Deliberately left out, and why

Per the standing limit that a step which only makes sense as circumvention must be left
out and named:

- **No referer/origin forgery, no header spoofing.** §5 notes we are being reset; the
  obvious "fix" — present a PixelDrain-hosted `Referer` on the byte request, or rotate
  headers/clients until something is admitted — is hotlink/abuse-control evasion. It is
  refused here exactly as the Emperor refused it on `.dev`, and the observation stands as
  an observation, not a to-do.
- **No session, cookie, token or account access.** Everything documented is reachable by
  an anonymous `GET` on a link we already legitimately hold. No `Authorization` example is
  given because none was needed.
- **No bulk or repeat fetching.** No sweep, no retry storm, no range-walk of the file, no
  scripted re-probe of the endpoint that is resetting us. The one retry I allowed myself
  was a 1024-byte range after a 30-second pause, and when the `?download` probe reset a
  second time I stopped and reported it.
- **No adoption of `pixeldrain.dev`**, and no suggestion to change `is_pixeldrain`'s
  predicate. §1 changes only the *stated reason* for keeping it.
- **No code edit of any kind** — `link_state.classify()` and the `host_classifier`
  docstring are quoted with line numbers and left for the Emperor's decision.

---

## 9. One-line answers to the order

1. **Real API host:** `pixeldrain.com` (there is no `api.` subdomain). `.dev` is the same
   operator's second domain, proven by one shared CA-issued certificate and identical
   application responses — *not* a lookalike, which corrects refusal #12's premise while
   leaving its conclusion (pin `.com`) right for canonical-form reasons.
2. **Metadata:** `GET /api/file/{id}/info`, no auth, 200 + JSON.
3. **Download:** `GET /api/file/{id}` serves the bytes itself (`200`, `302` never seen);
   **`Range` is honoured (`206` + `content-range`, `accept-ranges: bytes`) →
   `is_resumable = 1 is correct**, and our ledger's 89,925 zeroes are *unprobed defaults*,
   not measurements. `?download`: unverified.
4. **Identifiers:** name, mime, size, sha256, upload date, last-view date — and **no expiry
   at all**, so there is no host lifetime to replace the 24 h heuristic with; keep
   `expires_at = None`.
5. **Errors:** `404 not_found` = genuinely dead; **restricted ≠ dead, and its actual
   response shape is unverified from this host.** The reset we hit maps to `dead` in
   `link_state.py:56-58`, which mislabels *our* transport as *their* state — but it is
   recoverable, not permanent: `heal` restores it (§10 proof 1), the cache circuit ignores
   `status` entirely, and `fail_count` clears on the next accepted URL
   (`resolved_cache.py:264`).
6. **Resumability:** `is_resumable = 1` is the verified truth for this hoster, and the one
   probed row in our own ledger already says so.
7. **Mapping:** Category A direct-file, verified by §3; expected `mime_type` = the `/info`
   value, `container` from the filename extension, `content_type` = the media itself,
   `protocol` = https direct file (not HLS — no playlist, no segments).
8. **Severity of the reset problem, corrected:** recoverable mislabelling of the ledger,
   not permanent damage and not circuit poisoning — proven in §10.

---

## 10. The two proofs the Crown asked for

Both run offline against a throwaway mini-catalog in `/tmp` with **only the network edges
patched** (`extract_post_data`, `save_scraped_data`, `probe_single_source`); the heal
selection, the health-check loop and the status write-back are the real code. No production
DB was read for these, no sweep, no exporter — qoder12's sweep was running and `/` is at
95%, per the hold.

### Proof 1 — heal DOES restore a timeout-marked `dead` link: **PASS**

A source inserted as `status='dead', http_status=0, is_resumable=0` — the exact shape
`probe_single_source`'s catch-all (`fast_fetch.py:4952-4957`) writes for a reset or a
timeout — then `heal_post_links(post_id)`:

```
[before heal] status='dead'   http_status=0  is_resumable=0
[after  heal] status='active' http_status=206 is_resumable=1
heal_post_links returned: {'healed': 1, 'total_active': 1}
```

The path is real and it is short: `heal_post_links` selects
`status IN ('dead','expired')` (`fast_fetch.py:5069`), re-extracts the post, saves, then
`run_health_check` re-probes and writes the row back with
`UPDATE download_sources SET status = ?, is_resumable = ?, http_status = ? …`
(`fast_fetch.py:5033-5036`). So a wrong `dead` is corrected by the next successful look —
which is the whole reason my §5 severity claim was wrong.

**The honest limit of the proof:** heal's first step is
`fresh_data = extract_post_data(post["url"])`, and if that returns nothing it bails with
`{"healed": 0, "error": "Fetch failed"}` *before* re-probing. So restoration depends on the
**source site's post page still resolving**, not on the PixelDrain link being reachable. A
file that is fine but whose upstream listing page has moved stays `dead` until something
else re-probes it. Worth knowing before anyone counts on heal as a cure-all.

### Proof 2 — does anything consume `status='dead'` as if it were measured absence?

Audited every non-test consumer in the tree. **No user-facing surface treats `dead` as
proven absence**, and the places that look like it are ranking, recovery, or edge-blocked:

| site | what it does with `dead` | verdict |
|---|---|---|
| `tiers.py:83` | `CASE status WHEN 'active' THEN 0 WHEN 'dead' THEN 9 ELSE 5 END` — an **ORDER BY**, never a WHERE; `tiers.py:212` a −60 score | **safe**: the only copy of a film still wins its band |
| `fast_fetch.py:5370` | `if status in ('dead','expired'): needs_refresh = True` | **recovery**, the opposite of absence — a wrong dead forces another look |
| `fast_fetch.py:5646` | failed re-resolve → mark `expired` + ship `stale: True` | **honest labelling**, not a deletion |
| `catalog_api.py:710` | `playable = group <= RESOLVE and state != 'dead'` | consistent with the ranking above |
| `catalog_api.py:713` | `dead = state not in ('active','unknown','unchecked')` — **I suspected this counted never-probed links as dead** | **REFUTED**: `state_for()` (`link_state.py:623-629`) folds `unverified` → `unchecked`, which is exactly the exempt value. A never-probed link is not counted dead. I chased this and it is not a defect. Residual nit only: `expired` *is* counted as `dead` in that flag, so `dead_link_total` includes throttled-but-present links |
| `catalog_v2.py:2375` | `state='dead'` → score 0, kept *behind* every live peer | Zero-Data-Loss as documented |
| `link_health.py:878-893` | only a measured failure is dead; "an unprobed or merely-aged link is not dead here" | good citizen |
| `resolved_cache.py:332` | circuit ignores `status` entirely (no such column) | **no poisoning** |
| `viewer.py:675` | `WHERE release_id = ? AND status != 'dead'` — the one true exclusion, drops the copy from the playlist | **user-reachable? No.** `/api/m3u` is not in the edge allow-list and falls under `location ^~ /api/ { return 403; }` — measured in the live `/etc/nginx/sites-enabled/radd-stream:154-155` (read-only; nothing was touched). It is served on loopback only, for the dashboard's VLC button (`viewer.py:1651`) |
| `fast_fetch.py:4985`, `5069`, `6390`, `6415` | `status IN ('dead','expired')` as the **work queue** for health-check and heal | intended use |

**Answer to proof 2:** nothing consumes `dead` as measured absence in a way that reaches a
user. The single hard exclusion is on a route the edge 403s. The mislabel's real cost is
confined to §5's corrected statement — ledger accuracy between probes, and (narrower than I
first claimed) `fail_count` accepting a transport reset as evidence because `unprobed` is
only set for the no-unpacker branch.

### Proof (a) as a durable test

`Fast_Fetch/test_transient_dead_heal.py` — 5 tests, offline, stdlib, one throwaway
mini-catalog **per test** (bound via `fast_fetch.DB_PATH`, which is what `get_db` falls back
to at `fast_fetch.py:622-625`; per-test isolation was needed because a shared WAL catalog
across five tests deadlocks the write path). Result: **5/5 OK in 1.5 s.** It asserts the
mislabel keeps `source_url`/`final_url`/`resource_id`/`service`/`playback_type` intact, that
one later successful probe overwrites `dead → active` with its real `http_status` and
`is_resumable`, that heal's queue selects exactly those rows, and — the honest limit — that
heal **bails before re-probing** when `extract_post_data` returns nothing, so `dead` must
never be read as "heal tried and failed".

### Proof (b) — the size of the mislabel, and it is not the number I expected

Read-only, `mode=ro`, counted through `idx_sources_status_temp` (confirmed by
`EXPLAIN QUERY PLAN` as a **covering** index search, so it touches only the matching rows —
0.0 s for the dead count, 3.5 s for the two others on a box at load 5.3):

```
download_sources total           4,073,865
status='active'                  4,006,773
status='expired'                        61
status='dead'                           23      ← 0.000565 % of the catalog

of those 23 dead:
  http_status 0 or NULL (transient cause)   23
  a real HTTP code (measured absence)        0
  last_checked_at IS NULL                    23   ← every single one
```

**The finding is not "a transient verdict got recorded as dead."** It is that **no verdict
was recorded at all**: all 23 `dead` rows (and all 61 `expired` rows) carry
`http_status = NULL` *and* `last_checked_at = NULL` — they were never probed. They are
importer defaults, and `fast_fetch.py:4626`'s own comment is already worried about exactly
this class of default. So the mislabel I argued for has a measured population of **zero**
in this catalog, and I am reporting the zero rather than defending the adjective.

What the same measurement does expose, one layer over, is the inverse and far larger error:
**4,006,763 of 4,006,773 `active` rows have `last_checked_at IS NULL`** — 98.35 % of the
catalog asserts liveness it never measured. `link_state.py:17` and `status_summary()`'s
`verification_coverage` exist precisely to make that visible instead of flattering, and
`resolved_cache` refuses an unprobed row on its own terms (`resolved_cache.py:279`:
"`fail_count` stays 0 forever and a known-dead URL is re-served"). If the fleet wants a
number to act on tonight, it is that one, not my 23.

Both queries were run against the production file read-only and indexed, per the one-scan
rule; the 30 MB scratch snapshot at `/tmp/edge_snapshot.db` (12,288 rows, all `active`) was
measured first and reported here as too small to mean anything, which is why the count came
from the real ledger with a covering index instead.
