# Session 2026-10-30 (q3 lane) — launch readiness JOB A: the operator's own reads are bounded, and the boundary is named in code `[Q3-OPS-READS]`

> Written directly as a dated session file, which is the convention the documentation diet set:
> `docs/SESSION_CHECKPOINT.md` item 4 — one dated file per session in `checkpoints/`, nothing appended
> to the pointer files. `Fast_Fetch/CONTINUITY.md` carries the pointer and the open items only.

Worktree `/tmp/q3_launch`, branch `q3-launch-reads`, base trunk `072158f`. Nothing was committed or
pushed from `/opt/radd-stream`, no service was restarted, no production catalog was read.

## What master asked, and what the code was already doing

The brief listed five measured facts about `127.0.0.1:8080` / `:8081` and asked for three deliverables:
bound `/api/data`, put the credential in front of the operator READ routes, and prove both offline.
Before writing anything I read trunk, and **two of the five bullets were already closed in code**:

- `/api/data` was already paginated (`_LEDGER_PAGE_DEFAULT` 50 / `_LEDGER_PAGE_CEILING` 200,
  `has_more` derived from fetching one extra row so there is no `COUNT`), pinned by
  `test_bounded_ledger.py`.
- The bearer token was already required on **every** route of the operator port and fail-closed when
  `RADD_ADMIN_TOKEN` is unset, pinned by `test_operator_isolation.py`.

The five measurements are true of **the running tree**, not of trunk: `/opt/radd-stream` is behind and
`systemd`'s `ExecStart` loads that checkout. That distinction is now written into
[`docs/ADMIN_PANEL_ACCESS.md`](../docs/ADMIN_PANEL_ACCESS.md) instead of living in a chat log, because
a stale table with no date on it is what let a later lane quote 2026-10-29 as current.

## What this session actually changed

1. **A cap the operator cannot see is a cap that gets mistaken for the whole table.** The page
   contract gains `truncated` (rows remain behind this page) and `clamped` (the requested size was
   reduced), plus `ceiling`. `/api/data` now passes the caller's raw `limit` down instead of clamping
   it first — clamping at the route makes `clamped` structurally unable to ever be true. The
   dashboard's pager prints `· CLAMPED`.
2. **`/api/sitemap` was the sibling nobody bounded**: its route handed `?limit=` to SQL through a bare
   `int()`, which raised a 500 on `?limit=abc` and would have materialised a caller-sized list of
   dicts on a 1-vCPU / 11.9 GB box. The cap is `_SITEMAP_ROW_CEILING = 500`, enforced **inside
   `search_sitemap_api`** — the function that touches SQL, not just the one route that happens to
   call it — and the route uses `bounded_int` so a nonsense value answers 200 with the default
   instead of 500. Response shape unchanged (a bare list); `renderSitemapRows(rows)` reads it.
3. **The ordering is now in the code comment, not only in the docs.** `viewer.py`'s
   `OPERATOR_ONLY_PREFIXES` block used to conclude "the boundary is the token *and* loopback". Root
   `AGENTS.md` forbids describing the dashboard as token-gated, and the phrase invites exactly that
   reading, so it now says: **loopback is the reachability boundary — both ports bind 127.0.0.1 and
   nginx forwards neither — and the token is the credential checked *inside* it, second, after the
   peer address.** A token does not make the panel reachable.
4. **`docs/ADMIN_PANEL_ACCESS.md` contradicted the law it quoted.** Two table rows and one sentence
   called `/admin` and the panel "token-gated" while the same file said never to write that. Reworded,
   dated, and given the running-tree-vs-repository note above.
5. **New guard, extending the enumeration**: `test_docs_invariants.py` pins two sentences from
   `ADMIN_PANEL_ACCESS.md` (the ordering, and the running-tree note) so the wording cannot drift back.

## Tests

`Fast_Fetch/test_operator_read_bounds.py` — 18 offline tests: the page contract (oversized clamped and
admitted; honest size not marked; `"abc"`/`""`/`None`/`[]`/`{}` → default, no crash; `0`/`-1` → 1 and
marked; `truncated` distinguishes "rows remain" from "end of ledger"; `truncated == has_more`; the
contract survives an absent DB; every key present on every page), the sitemap cap (620 rows seeded,
cap bites at 500; the route 200s on `abc`/`-3`/`99999999`; the public port still 404s it), and the
credential over **two real `HTTPServer`s on `127.0.0.1` port 0** — bogus token 401/403 on
`/api/v1/stats`, `/api/v1/rules`, `/api/data`, `/api/sitemap`, `/`, `/client`; an absent credential
returns the *identical* body to a bogus one; the real token 200s; the wire reports the clamp; unsetting
`RADD_ADMIN_TOKEN` fails the whole port closed; the public allow-list is unchanged; and the
operator-only route set is asserted as a snapshot so widening it fails a test rather than a review.

One test failed on the first run and it was the code's fault, not the test's:
`test_the_row_count_is_capped_at_the_ceiling` returned 620 because I had bounded only the route. Hence
change 2 above.

Registered as `.github/workflows/backend-ci.yml` `🧪` step **30** (from 29 — count with
`grep -c 'name: 🧪'`, per root AGENTS.md).

Local runs on this box, `nice -n 19`, one at a time, load ~3 at session start:
`test_operator_read_bounds.py` 18 OK in 5.5 s · `test_bounded_ledger.py` 10 OK in 3.7 s ·
`test_operator_isolation.py` 28 OK in 64.2 s · `test_admin_panel.py` 65 OK in 32.7 s ·
`test_database.py` 133 OK in 65.5 s · `test_docs_invariants.py` 17 OK in 1.4 s.
`test_admin_panel.py` at 32.7 s against the 266.312 s root `AGENTS.md` records is the same module
measuring the box, not the suite (rule 7); CI's timing is the record. Note for whoever next edits
`AGENTS.md`: it still says `test_database.py` is "76 tests" and it is 133.

## Not done, honestly

- Not landed, not deployed, not measured against production: this is a branch. `curl` on this box
  still answers the way the 2026-10-29 table says it does until master merges and the owner restarts.
- `/api/sitemap`'s response shape is still a bare list, so it carries no `truncated` flag; adding one
  would break `renderSitemapRows`. The cap holds; the visibility does not. Deliberate, and stated
  rather than fixed silently.
- The prose check for the forbidden phrase was **not** automated: "token gate" also appears in
  `Fast_Fetch/README.md`, `MASTER_AI_RUNBOOK.md`, `DATABASE_SCHEMA.md` and `SITES.md` meaning an
  *upstream site's* token gateway. A regex guard there would be noise, so the two pinned sentences in
  `ADMIN_PANEL_ACCESS.md` are what is tested.
