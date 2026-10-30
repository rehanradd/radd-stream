# 2026-10-27 — Session: the shortener waterfall was 403, and what opening it actually proved (Qoder, orchestrator)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: the shortener waterfall was 403, and what opening it actually proved (Qoder, orchestrator)

**Goal:** the monetization rows the inventory filed as P0 — P-B-02 (free downloads earn zero
shortener revenue), P-B-03 (the VIP bypass can never trigger), M-MON-04 (point the client at
`/api/v1/download`). None of them needed a phone.

**What was wrong, in the order it was found.**
1. `/api/v1/download` is the **only** route that calls `shorten_download_url` — one call site,
   `viewer.py:3207` — and nginx's `^~ /api/` deny answered it **403**. The waterfall was not
   mis-tuned; nothing could reach it. Added `location = /api/v1/download` (GET/HEAD only).
2. `redact.mint_vip_pass` existed and **nothing called it**. `viewer.request_is_vip` would accept
   a pass forever, from nobody. Added `GET /api/v2/account/vip-pass`: 401 with no key, `402
   licence_required` for a free account, `200 {pass, expires_at, membership_until}` for a member,
   `410 licence_expired` only if the membership lapses between the check and the mint.
   `VIP_PASS_TTL_SECONDS = 6 h`, capped by `min(now + TTL, vip_until)` — the invariant this route
   exists to hold is that ten minutes of membership never buys six hours of capability, because a
   pass has no revocation list and the only leash is its expiry.
3. A capability in a query string is a credential in an access log. New `log_format
   radd_capability` in `nginx.conf` — the standard format **minus `$args`** — applied to
   `/api/v1/stream` and `/api/v1/download` only, with sentinels proved afterward: a served request
   carrying `?vip=PASSSENTINEL` left zero matches in `/var/log/nginx/access.log`, while unrelated
   routes still log their args.

**Design decision worth keeping:** the inventory's M-MON-04 build text was wrong and shipping it
verbatim would have been a regression. `test_download_endpoint.py` already says *"a shortened
target is a landing page, not the file"*, so pointing `DownloadService`'s OkHttp byte pipe at
`/api/v1/download?redirect=1` writes an interstitial into `Movies/RaddStream/*.mp4` and loses
pause/resume — and `/api/v1/stream` was never monetized, so the bearer header the same line asks
for would have bypassed nothing that was ever in the way. **No Kotlin was written for this task.**
Monetizing a free download requires handing it to something a human taps, which trades the app's
download promise for revenue: the owner's call, recorded in the inventory (M-MON-04 rewritten,
P-B-02/P-B-03 and caveats 2/5 corrected) rather than guessed at in a commit.

**Checks:** `test_accounts_api.py` **38 OK** — the nine vip-pass cases live in a `VipPass`
subclass of a new `EdgeFixture` mixin, because subclassing `Edge` for its `setUp` re-ran all 29
inherited cases (67 → 38, and the pass tests were passing twice). The one that matters:
`test_a_member_gets_a_pass_that_the_download_route_itself_accepts` calls
`viewer.request_is_vip` on the minted string, since the minting half and the consuming half are
written by different hands. `test_download_endpoint.py` 18, `test_database` 64, `test_vidout` 6,
`test_payments`, `test_catalog_v2`, `test_media_search` 21, `test_admin_panel`, `test_redact` 49
— all OK, one module per invocation, no live catalog written.
`sweep_public_edge.py --db /tmp/edge_snapshot.db --posts 8 --probe`, extended to scan the download
descriptor alongside the stream one: **OK — 0 flags**; the 11 hand-review hits were title text
(`'Short'`, `'Torrent'`, `'Nexus'`), and the only hosts named in a public body remained
`image.tmdb.org` / `m.media-amazon.com`.

**Live:** service restarted (4 polls to 200). `download?id=bad` → the server's own 400;
`account/vip-pass` → 401 problem body on the public port; POST `download` → 403; `/api/data` and
`/api/v2/health` → 403 unchanged. Backups: `radd-stream.pre-download.bak`,
`nginx.conf.pre-caplog.bak` (plus `radd-stream.pre-bymedia.bak` from the previous session).

**Two decisions the owner made after this shipped, recorded because they change what "done" means.**
1. **Keep the byte pipe.** Free downloads stay on `/api/v1/stream` with an honest pause that keeps
   its bytes; **free-tier shortener revenue is accepted at zero** and VIP purchases are the
   monetization. So the app half of P-B-02/M-MON-04 is closed *won't-fix*, not unfinished — the
   waterfall remains configured, reachable and tested, serving the browser hand-off and any future
   surface with a human at the end of it. Do not re-propose piping a shortener interstitial into
   `Movies/RaddStream/`.
2. **`main` was fast-forwarded to `master`** (`master:main`, pure fast-forward, no force, both heads
   at `095c3c7`; `main..master` was 25 and `master..main` was 0). `AGENTS.md`'s "push verified
   milestones directly to `main`" is the rule again, and `master` keeps the same commit rather than
   being deleted. **Verified, not discovered:** CI has never run and the cause is the account-level
   Actions switch `AGENTS.md` already records — `actions/runs` returns `total_count: 0` even for
   today's default-branch push, while `/actions/permissions` reports enabled/`all` because that is
   the *repository* setting, which sits under the account one. Zero tags and zero Releases match it.
   **"CI green" is unmet-by-default, not passed**, so the suites above are the gate and every session
   should keep running them before a push rather than waiting on a check that will never arrive.

