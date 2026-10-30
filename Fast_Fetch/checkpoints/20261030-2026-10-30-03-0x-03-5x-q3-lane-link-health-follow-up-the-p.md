# 2026-10-30 03:0x–03:5x — q3 lane, LINK-HEALTH follow-up: the per-host serialiser is built, and the doc re-scan is recorded `[Q4 SERIALISER + queue b]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-30 03:0x–03:5x — q3 lane, LINK-HEALTH follow-up: the per-host serialiser is built, and the doc re-scan is recorded `[Q4 SERIALISER + queue b]`

**Step 1 — the CI verdict I left un-polled last time, taken once.** One round against
`api.github.com`, token read from `os.environ` inside `python3 -S`, nothing printed but statuses.
`/actions/workflows` confirms the id q4 quoted: **398476976 = 🐍 Backend CI — Stdlib Python
Tests** (`active`), alongside 398476977 (Android) and 398476978 (Release). Filtered by
`head_sha`, that workflow shows **two runs for `8935d49`, both `completed / success`** —
`40952762005` on `master` and `40952762106` on `main`, both created 2026-10-29T20:51:44Z. No DNS
flap this time (first attempt answered), and I did not poll again.

**Step 2 — `link_health.host_gate()`, the defect my own sweep doc named as the precondition.**
`docs/LINK_HEALTH_SWEEP.md` §3 said 1 in-flight request per host and §8 listed "a per-host
serialiser in front of `probe_many()`" as the one code change the sweep cannot start without;
q4 made it the priority. What landed:

- `host_key(url)` — scheme dropped, host lowercased, IPv6 re-bracketed, **port kept except 80 and
  443**, so `HTTP://Example.COM:443` and `http://example.com` are one edge while `:8080` stays
  separate. An unparseable URL keys to `""` and is still gated rather than slipping past.
- `host_gate()` — one `threading.RLock` per key in `_HOST_LOCKS` (registry guarded by its own
  `Lock`), **`RLock` deliberately**: a caller that gates a whole probe must not self-deadlock
  against the per-hop gate, and re-entrancy is same-thread, hence already sequential. Spacing
  `DEFAULT_HOST_SPACING_S = 1.0` (`RADD_HOST_SPACING_S` dials it, negatives clamp to 0, a
  non-numeric value raises at import rather than being ignored) plus `DEFAULT_HOST_JITTER_S = 0.2`,
  measured from the previous request's **release**, so a gap lands in 1.0–1.2 s. Release in
  `finally`, always. A worker whose host is busy **waits** — never skipped.
- Wired at exactly one place: `_chain()` wraps each `_raw_request()` hop. That is what keeps the
  guarantee "around the network call, never across a DB write" true by construction — `link_health`
  does not open a database at all — and it means hop A is released before hop B is knocked on,
  which the redirect test pins.
- `allow_private=True` drops the **wait**, not the lock. Politeness is owed to someone else's
  edge, not to the offline suite's own loopback stub, and this is why the 57 existing
  `test_link_health.py` probes did not suddenly gain a second apiece.

**Proof, offline.** `Fast_Fetch/test_host_serialiser.py` — **18 tests, 0.16 s**, in CI. The
harder half was making the claims deterministic instead of stopwatch-shaped: my first version
proved "never overlap" with sleeps and cost 17 s at load 7 (it now costs 0.16 s at load 6). The
"gate is really held" test asks a *second thread* to `acquire(blocking=False)` on the current
host's lock from inside the fake fetch — it would succeed if the gate were missing. Probing that
from the *same* thread proves nothing, because an `RLock` is re-entrant for its owner; that was
the bug in my own first draft of this file, and the tripwire caught it before I pushed.

**Local gate, run as CI runs it — one invocation per module, `nice -n 19 ionice -c3`.** The five
modules my change can actually reach: `test_link_health` **57 OK (11.94 s)**, `test_link_state`
**28 OK (158.07 s)**, `test_evidence_writeback` **12 OK (159.60 s)**, `test_link_sweep_budget`
**15 OK (0.018 s)**, `test_host_serialiser` **18 OK**. The full 23-module list is running in the
background on this box and, through `test_link_state`, has reported `test_database` **133 OK
(210 s)**, `test_vidout` **6 OK (0.64 s)**, `test_catalog_v2` **96 OK (700 s)**,
`test_release_descriptor` **24 OK (7.18 s)**, `test_link_health` **57 OK (60.9 s)** — same
module, 5× slower than my foreground run, which is the honest description of measuring on one
vCPU while another lane is doing network work.

**What CI has and has not verified for this sha.** It has (for `8935d49`, measured): the standing
22-module offline list green on both refs. It will (for the push below, not yet read): run
`test_host_serialiser.py` on an x86 runner, which is what makes the 18-test module a gate rather
than a local habit. It has **not** verified: that any sweep ran, that any real host was
knocked on politely (zero outbound probe traffic was generated here — every request in the suite
is a monkeypatched `_raw_request`), that spacing behaves under a real pool against a real 429, or
anything about the JIT path. And the scope is narrower than it looks: `link_state.probe_rows()`
is `probe_many()`'s only wrapper in the tree and **has no caller yet**, so this change alters no
live request path today. That is why I was willing to put a 1 s floor in at all.

**Step 3 — queue item (b), recorded not rewritten.** `docs/DOC_RESCAN_20261030.md` lists six
present-tense claims the code contradicts, each with file:line, the claim verbatim, the
measurement and a one-line replacement: the "viewer.py has no authentication and wildcard CORS"
sentence at **three** sites (`App/docs/TECH_STACK.md:48`, `App/docs/PLAN.md:257`,
`Fast_Fetch/AGENTS.md:836`), "no rate limit" at `docs/PROJECT_MAP.md:161`, API_V2 §17's unchecked
"All of Layer 2: every `/api/v2` endpoint", and `App/docs/PLAN.md:296`'s "Continue Watching and
offline Downloads not implemented". Nothing was softened, and the four `docs/` items that assert a
**production action or state** (`API_SURFACE_AUDIT.md:225-228` "not deployed"/"pending deploy",
`FULL_MASTER_FEATURE_INVENTORY.md:1004-1006` dirty-tree and token-at-rest rows) are **flagged to
q4 untouched** — I did not verify the resident process's start time against the checkout, so I
will not write a sentence about what is "deployed".

**One mistake of my own, recorded rather than hidden.** My first H4 replacement claimed "nginx
adds no `limit_req` of its own". I had grepped `/etc/nginx/sites-enabled/`, and **`grep -r` does
not follow symlinks** — `sites-enabled/radd-stream` points at `sites-available/radd-stream`,
which applies `limit_req zone=radd_stream_api burst=30 nodelay` on seven locations against a
`10 r/s` per-address zone. Corrected in commit `b6c039a` with the trap written down. That commit's
message has two blank holes because I put backticks in a `-m` string and the shell executed them;
the commit content is fine, the prose is not, and I left the history alone instead of rewriting a
pushed-anyway-unsigned commit.

**Limits honoured.** Load 5.2–7.0 on one vCPU throughout; nothing heavy run above load 8 and the
test execution was not deferred because the 1-min figure stayed under it. Zero writes to
`/home/ubuntu/radd-stream-data/`, zero production DDL, no `radd-stream.service` restart, no
scraper/crawl/merge, no Gradle, no `/api/data` or `full=True`, no repeated production curls.
Reads of `/opt/radd-stream` were limited to `git rev-parse` / `git show` — never a workspace.

---

