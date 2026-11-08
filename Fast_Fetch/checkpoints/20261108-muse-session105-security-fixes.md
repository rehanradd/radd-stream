# Session 105 — Security fixes (audit 2026-11-08, 21 findings)

Date: 2026-11-08 (PKT). Branch: `security-fixes-20261108`, base `d41342c2`
(Session 104b, live). Scope: audit items 1–12. No production DB writes, no
live-tree edits, no service restart, no deploy, no tag. Full gate **50/50
PASS, 1,949 tests** (`/tmp/gate-20261108-security.txt`). App changes are
code-only: no local Gradle run exists on this VM by owner order, so CI
(`ci.yml` on push) is their verification path — see the NOT-verified flags.

## Done, with evidence

- **1. HTTPS default — DONE (code), NOT verified on CI yet.** `brand.properties`:
  `network.default_server_url=https://raddstream.duckdns.org`;
  `release_cleartext_for_default_host=false` stays (now consistent — the
  release build reaches its HTTPS default; the flag is moot unless the
  default ever returns to HTTP). `build.gradle.kts` release block adds
  `isDebuggable = false`. nginx change is the parent's — see below.
- **2. Sync key at rest — DONE (code), NOT verified on CI yet.** New
  `SyncKeyCrypto.kt`: AES-GCM, random 12-byte IV prepended, `v1:`+base64,
  Keystore key `radd_stream_sync_key`, API 23+ only (below 23: plaintext,
  documented on the card). Key loss fails closed (decrypt null → signed
  out, ciphertext left in place). Repository encrypts on write, decrypts
  on read, migrates a legacy plaintext value once in the background (only
  if still the value seen). `AndroidManifest.xml`: `allowBackup="false"`
  with a comment — Auto Backup no longer carries DataStore/Room off the
  device. Copy is scheme-aware now: `revealWarning(serverUrl)` and
  `linkTransportWarning(serverUrl)` say HTTPS/TLS for the shipped default,
  plain-HTTP in the clear for a viewer-chosen HTTP server; `RaddStreamApi`
  KDocs and the "Four rules" KDoc updated the same way. Tests: new
  `SyncKeyCryptoTest.kt` (round-trip, distinct IVs, wrong key/tampered/
  garbage → null, `isEncrypted`, source scan that the write path encrypts
  and the manifest keeps backup off).
- **3. VIP trial IP budget — DONE.** `accounts.py`: `trial_ip_budget`
  (ip_hash PK, window_start, creations), 10 creations per IP per rolling
  24h, SHA-256 hashed IP, charged only on a NEW mint; `TrialBudgetExceeded`
  (429) threaded through `accounts_api.route_post(client_ip=...)` ←
  `viewer.py` `redact.client_ip(self)`. `test_device_trials_and_webhook`
  89 OK (+6), `test_accounts` 67 OK, `test_accounts_api` 38 OK.
- **4. Finish-watch farming — DONE.** New `watch_observations` (PK
  account/work/season/episode; first/last server receipt, max position);
  `put_progress` records on APPLIED writes only; one-time backfill from
  `user_progress` while the table is empty. `engagement.finish_watch_
  observed()` gates the +15 grant: span ≥ 0.9 × duration × 0.5 tolerance
  = 0.45 × duration (a 2x viewer passes; an instant claim pays nothing).
  `test_accounts` 67 OK (+3), `test_coins_engine` 82 OK. Stream-press
  signal NOT implementable: play/stream routes are anonymous, so progress
  reports ARE the server-observed evidence — that is the design, not a gap.
- **5. Quality gate ON by default — DONE (code), live flip is the
  parent's.** `admin_panel.py` MONETIZATION_FIELDS `feature_quality_gate`
  0→1. `_ensure_monetization` only adds missing rows, so the LIVE catalog
  row stays 0 until the parent flips it at gate time (`UPDATE
  app_remote_config SET feature_quality_gate = 1 WHERE id = 1;` or the
  panel Monetization UI). `test_admin_panel` 107 OK, `test_redact` 80 OK.
- **6. Handle expiry + secret out of DB — DONE.** `redact.py`: v2 tokens
  carry expiry (TTL 86400s); the signing secret lives in a file/env
  secret, the legacy `server_state` row is read read-only once and
  migrated. The live service already has the secret via env, so no
  rotation on deploy. `test_redact` 80 OK.
- **7. Contact form spam — DONE.** `contact_intake.py`: honeypot field
  `website` (filled → silent `(True, None)`, nothing written); per-IP/day
  cap 10/day + same-day dedup on body SHA-256 (`contact_ip_budget` in the
  panel DB); `rate_limited` → route maps to 429; no IP → no budget/dedup.
  `test_contact_intake` 15 OK (+7).
- **8. LAN share token — DONE (code), NOT verified on CI yet.**
  `LanShareServer.start()` mints a fresh 128-bit random per start (hex,
  32 chars, `LanShareProtocol.generateSessionToken()` — hex, not base64,
  because `java.util.Base64` needs API 26 and `android.util.Base64` is
  untestable on the JVM). The protocol checks `?token=<session>` in
  constant time (`MessageDigest.isEqual`) BEFORE the file-token lookup
  (wrong session → 403, reveals nothing about files); `shareUrl` carries
  it as `?token=`; the runner stores it in `LanShareStatus.Listening`
  (never in a status line or log); a restart invalidates every URL the
  last session handed out. `LanShareProtocolTest` +5 (missing/wrong/right
  session, check-before-lookup, minting, URL shape). **DEVIATION, owner
  decision owed:** the brief said bind loopback only, but loopback-only
  kills the feature outright (the runner advertises a LAN IPv4 and a peer
  on another device must reach it). Shipped token-only, LAN bind kept.
- **9. Cert pinning — DONE (code), NOT verified on CI yet.**
  `brand.properties` `network.tls_pins`: 3 chain pins (intermediate YE2
  `s/tdAOmUzd8syaTuqfgGvFcn6DzA5Cmb+Vby1ST+U3Y=`, Root YE
  `sCkq5UWXjg+7mKu9lMhhYF5bGLsy7VI/UNW3tccdR7w=`, ISRG Root X2
  `diGVwiVYbubAI3RW4hB9xU8e/CH2GnkuvVFZE8zmgzI=`; leaf never pinned).
  `Brand.kt` `tlsPins` accessor; `ApiProvider.certificatePinnerFor`
  (null unless host == default host and pins non-empty; malformed pin
  throws at build); `brandNetworkPolicyXml()` emits `<pin-set>` for the
  default host in the release config. Tests: `ApiProviderTest` +5,
  new `TlsPinsTest.kt` (HTTPS default, 3 pins decode to 32 bytes each,
  leaf absent, cleartext off).
- **10. Spend idempotency — DONE.** Route-side only: `idempotency_key`
  on redeem / redeem-download / request-movie / redeem-theme; validated
  (string, 1–128 chars, else 400); namespaced per account + operation as
  `client:{account}:{operation}:{token}` because `spend_coins` dedupes on
  the key alone (UNIQUE, no account scope) — a raw client key would let
  one account block or free-ride another's spend. `test_coins_engine`
  82 OK (+6, incl. cross-account).
- **11. Coin-price discrepancy — RESOLVED, no code.** Both stores agree
  (panel DB v5 + catalog DB: day 500 / weekend 1200 / monthly 5000 /
  download 100 / request 300 / theme 250); the page renders
  COIN_REDEEM_FIELDS from the catalog row via `get_monetization`; no
  "Week/Month/90 days" labels exist in panel code. The browser report was
  a misread. Follow-up owed (not done): a drift-guard test pinning the
  panel's coin rendering — needs a parent deploy decision.
- **12. Adult fold — PREPARED ONLY, numbers below.** Report mode on the
  live catalog path, `mode=ro` (verified: DB mtime/size unchanged
  2026-11-08 11:25:44, 6,397,145,088 bytes; no journal written).

## nginx change (parent applies at gate time — exact text)

Current state, read live: HTTP block `listen 80 default_server` serves the
full API over plain HTTP on the raw IP; HTTPS block `raddstream.duckdns.org`
(`listen 443 ssl`, cert to 2027-01-31) has NO HSTS header anywhere;
`raddflix_security.conf` defines `auth_limit` (5r/m), `register_limit`
(2r/m), `api_limit` (30r/s), `guest_limit` (1r/m) — verified by grep, NONE
is referenced anywhere (every location uses `radd_stream_api`); `radd_conn`
IS live (defined in `radd-stream-cache.conf`, used in both blocks).

1. In the port-80 server block, delete the 11 API location blocks
   (`/api/v1/posts`, `= /api/v1/stats`, `/api/v1/art`, `/api/v1/stream`,
   `= /api/v1/app/remote-config`, `^~ /api/v2/account`,
   `= /api/v1/search/by-media`, `= /api/v1/download`, `= /api/v2/play`,
   `= /api/v2/suggest`, `= /api/v1/contact`) and replace the catch-all
   `^~ /api/ { return 403; }` with:
   `location ^~ /api/ { return 301 https://raddstream.duckdns.org$request_uri; }`
   (one `^~` block suffices once the longer API prefixes are gone — a
   `^~` location does NOT override a longer plain prefix, so adding it
   alone would change nothing). `/download/`, `/operator/`, `/admin`,
   `/` (code-server) stay on HTTP — out of scope, browser surfaces only.
2. In the HTTPS block add:
   `add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;`
3. Delete the four dead zones from `raddflix_security.conf`
   (`auth_limit`, `register_limit`, `api_limit`, `guest_limit`).
   Then `nginx -t && systemctl reload nginx`, and verify `curl -s -o
   /dev/null -w "%{http_code} %{redirect_url}" http://92.4.95.252/api/v1/posts`
   answers `301 https://raddstream.duckdns.org/api/v1/posts`.

## Adult fold — dry-run numbers (fresh, 2026-11-08 ~13:20 PKT, mode=ro)

- Public posts 135,731; 394 keys hold flagged+unflagged; **407 exposed rows**.
- Gate: 407 = **agree 338** (334 keys fold) + **quarantine 69** (60 keys
  refused: `title_disagree` / `year_drift` — incl. mainstream twins the
  gate correctly refused: kantara-chapter-1, hi-nanna, lucifer, darbar,
  euphoria, black-mirror, peacemaker, love-death-robots). Drift vs
  2026-11-05 (364 agree / 43 quarantine): 26 more quarantined since.
- Audit: 15,068 rows carry the flag; 4,417 reproduce from
  `is_adult_title()`; **10,651 asserted-only** (incl. the 7,663
  uncut/unrated false flags) — cannot be propagated by the rule.
- Corroborated pass: **142 rows** publicly served under a flag the rule
  reproduces. Overlap with the agree set is **0 rows** (measured with
  `/tmp/fold-overlap.py`, read-only): the two gates are DISJOINT and
  complementary — the agree 338 all rest on asserted-only flags (same-key
  twins), the corroborated 142 all rest on rule-reproducible flags.
- Residual (same work, different key): **1,190 rows** — touched by neither
  pass; needs the re-key migration, not this fold.
- Reports saved: `~/workspace/goals/radd-stream-on-oracle-vm/hidden_files/
  fold-{report,audit,corroborate}-20261108.txt`.

## Apply plan (parent runs, with a FRESH verified backup first)

1. `python3 -S Fast_Fetch/backfill_adult_key.py --apply
   /home/ubuntu/radd-stream-data/merged_catalog_20261025.db` — flips the
   338 agree rows (334 keys); the script verifies flipped == public-total
   delta and rolls back on mismatch. Expect public 135,731 → 135,393.
   Add `--projection` to also fold into `cat_works` + retire safe stamps.
2. `python3 -S Fast_Fetch/backfill_adult_key.py --corroborate --apply
   <same db>` — flips the 142 rule-backed rows; script prints
   "corroborated exposures after the fold: N — must be 0". Expect public
   → 135,251. **Never** `--apply-all` (un-gated, hides the 69 quarantined).
3. Verify (read-only SQL + live): same-key exposed rows = 69 (quarantine
   only); `corroborated_adult_exposures` = 0; re-run the report — residual
   re-measured, not predicted; control titles still public AND playable
   (`/api/v1/posts?q=Kantara`, `?q=Hi Nanna` return rows; one play press
   302s). Undo per pass: `--undo` (key fold) / `--corroborate --undo`.

## Deliberately left out

- Audit 6 (ship release APK — owner-only tag), 11 (share coins — keep
  the 25/day cap), 13 (Play Integrity — items 3–4 are the server-side
  fix), 14 (WebView JS — keep hardening), 15 (DoS/per-link cooldown),
  16 (deadman switch — code present, NO live caller; needs signature /
  allowlist before ever wiring), 19 (str(ex) in operator-only routes +
  static resolve adult re-check — small, no time), 20 (admin lockout /
  TOTP — operator action), 21 (credit token in query string — bigger app
  change, skip). Coin drift-guard test (item 11 follow-up) and the LAN
  loopback question (item 8) are the two open owner decisions from this
  session. App items 1, 2, 8, 9 are code-complete but CI-unverified.
