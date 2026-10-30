# 2026-10-27 — Session: Champion Earning Engine, backend half (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: Champion Earning Engine, backend half (Qoder)

### Completed
- **`viewer.py`**: `GET /api/v1/download` now branches on audience. The operator port
  (`full=True`) and the JSON descriptor (`redirect=0`) are untouched; a public 302 for a
  non-VIP caller is routed through a shortener when one is configured.
  - `cat_shortened_links` is created by `_ensure_schema()` with exactly
    `original_url TEXT PRIMARY KEY, shortener_name TEXT, shortened_url TEXT,
    created_at INTEGER`; cache is consulted before any network call and written with
    `INSERT OR REPLACE` only after a successful shorten.
  - `shorten_download_url()` reads configured networks from
    `admin_panel.shortener_targets()`, rotates them per hour via
    `rotate_shortener_targets()` (stable bucket on `SHORTENER_ROTATION_SECONDS`), tries
    every configured target, and returns `None` on total failure so the caller falls
    back to the direct URL. `call_shortener()` is stdlib `urllib.request` only, 6 s
    timeout, 64 KiB response cap.
  - `_shortened_from_body()` accepts only `http(s)` results from a 2xx reply, rejects a
    same-as-original URL, and ignores unknown shapes rather than trusting them.
  - The shortened 302 deliberately omits `Content-Disposition` so the interstitial is
    rendered instead of saved as a file; the direct fallback keeps the attachment name.
- **VIP decision is not a forgeable flag.** `request_is_vip()` accepts either a bearer
  sync key resolved through `accounts.vip_status()` (`vip_until > now`) or a signed
  `vip`/`vip_token` query minted by `redact.mint_vip_pass()`. A bare `vip=1`, `vip=true`,
  an expired pass or a garbage token are all treated as free.
- **`redact.py`**: `mint_vip_pass()`/`parse_vip_pass()` — versioned HMAC tool (8-byte
  tag, expiry packed as big-endian int64), returning `None` for anything not minted by
  this secret or already expired.
- **`accounts.py`**: `user_accounts.vip_until REAL NOT NULL DEFAULT 0` (additive
  migration via `_NEW_COLUMNS`), surfaced in the authenticated account dict, plus the
  read-only `vip_status()` which never bumps `last_seen_at`, never touches the limiter,
  and answers `{"vip": False, "vip_until": 0.0}` for missing/revoked/blank keys.
- **`admin_panel.py`**: `shortener_targets()` reads ShrinkMe/DropLink API tokens
  server-side. Tokens stay in the operator surface; `remote_config()` still projects only
  booleans, so the public client learns *whether* monetisation is on, never the secret.
- **`test_download_endpoint.py`** (new, 18 tests): cache-first behaviour and exact table
  columns, cache hit skipping the API, falling back when unconfigured/failing, live vs
  expired account VIP, signed pass accepted and `vip=1`/`true`/expired/garbage rejected,
  conservative reply parsing, hourly rotation, and the operator port never monetised.

### Checks
- Requested command: `python3 -S -m unittest test_database.py test_vidout.py
  test_admin_panel.py test_download_endpoint.py` → **144 tests OK**.
- `test_redact` 49 OK; `test_accounts test_accounts_api test_operator_isolation` 112 OK.

### Not done
- No live shortener call was made (no real ShrinkMe/DropLink token exists on this box),
  so the network path is exercised against a stub fetcher only. Nothing committed (no
  commit requested).

---

