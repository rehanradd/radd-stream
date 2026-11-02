# 2026-11-02 — qoder9 App lane `[Q9-TLS-PRIMARY-HTTP-SESSION-FALLBACK]`

Supervisor order: change the app's base URL to `https://raddstream.duckdns.org/` and keep
`http://92.4.95.252` as a fallback. App code only — no nginx, no service, no live tree, no Blogger
sign-in and no blog change. Branch `q9-https-baseurl-fallback-20261102` off trunk `37ae67b`, worktree
`/tmp/q9_https_fallback`, pushed to its own branch only. **Not gated here; qoder1 gates on green CI.**

## The measurement the task rests on

Both probes run from this box before any edit, and both are still true at report time:

```
curl https://raddstream.duckdns.org/api/v1/posts?limit=1  → 200, ip=92.4.95.252, port=443, ssl_verify_result=0
openssl s_client … | x509 -noout -dates                   → notBefore=Nov  2 2026  notAfter=Jan 31 2027  CN=raddstream.duckdns.org (Let's Encrypt)
curl http://92.4.95.252/api/v1/posts?limit=1               → 200
```

TLS at the edge therefore exists as of today, which retires `App/AGENTS.md`'s "the backend has no TLS
at all" sentence and the corollary "a signed release APK cannot reach `http://92.4.95.252` … at all".
Both were corrected in place, inside the 15,000-byte ceiling that
`Fast_Fetch/test_docs_invariants.py` enforces — measured 14,999 B after the edit, which is why the
wording is terse.

## What landed

1. **`brand.properties`** — `network.default_server_url=https://raddstream.duckdns.org`, new
   `network.fallback_server_url=http://92.4.95.252`, `network.release_cleartext_for_default_host`
   **kept `false`** (the order asked for that, and it is now the honest value: the default is TLS).
2. **`Brand.fallbackServerUrl`** — same read path as `defaultServerUrl`: brand file, then
   `BuildConfig.BRAND_NETWORK_FALLBACK_SERVER_URL`, trimmed, blank when unset. No new plumbing: every
   brand key already becomes a `BuildConfig` field and a `brand.json` entry by itself.
3. **`ApiProvider`** — one address per session, chosen by `chooseSessionServer(saved, default,
   fallback, probe)`: `serverCandidates` orders them, `pickWorkingServer` probes in order through
   `DynamicServerDiscovery.probeNodeHealth` (`/api/v1/posts?limit=1`, 3 s, 200..399 = working).
   `DynamicServerDiscovery` was **not changed** — it is injected and its probe reused, which the
   order allowed as the smallest way.
4. **Cleartext stayed a named-host exception and got narrower.** `build.gradle.kts` derives the
   release host list as loopback (`127.0.0.1`, `localhost`, `10.0.2.2`) **plus the host of
   `network.fallback_server_url`, and only when that value literally parses as `http://`**. The
   default host and `network.cleartext.extra_hosts` still require the release switch, so the shipped
   policy names `92.4.95.252` and does **not** name `raddstream.duckdns.org` (it needs no cleartext).
   Debug keeps its own `src/debug/res/` copy, untouched.

## Two decisions the order left open, taken deliberately

- **The migration case.** A saved address that *is* the plain-HTTP fallback is the old shipped
  default outliving itself, not a decision to be on HTTP: the TLS default is tried **first** and the
  saved plain address drops to second. Without this, every install that had been working would keep
  starting on plain HTTP forever.
- **The fallback is offered only for our own addresses.** If the saved server is some other
  deployment, candidates are that server alone. Appending our box would re-probe a viewer's own
  catalog against our host — the app has no business choosing a server for someone who picked one.

## The bug found while implementing, and how it is fixed

`current()` used to re-read Settings on every call, so changing the server in Setup/Settings took
effect immediately. A naive "remember the fallback for the session" cache would have frozen a viewer
onto the old address until restart. The cache is therefore keyed: `SessionDecision(savedUrl,
serverUrl)` is reused **only while the saved value is unchanged**, so the failover survives the
session (nothing writes it) and a real server change still wins at once.

## Non-persistence, proved two ways

`chooseSessionServer` takes strings and returns a string — it holds no reference to anything that can
write, so the fallback cannot become the saved server by construction. `SessionFallbackGuardTest` then
scans `ApiProvider.kt` for `saveServerUrl`, `dataStore.edit` and `preferences[` and refuses any of
them, with `DynamicServerDiscovery.kt` (which genuinely does persist) as the positive control that
keeps the scan from passing by matching nothing.

## Error text

Nothing answering throws `ConnectException("No configured server answered")`, which
`friendlyNetworkError` renders as "The server didn't answer. It may be offline — try again in a
moment." A test asserts that sentence and asserts it quotes none of `92.4.95.252`, `raddstream`,
`duckdns`, `http` — because a debug build appends the raw text to what the person holding the phone
reads. Nothing configured at all still throws the existing `IllegalStateException` so routing lands on
Setup, not on a transport error.

## Tests and verification

`ApiProviderTest` and `SessionFallbackGuardTest` together cover the six cases the order named —
primary first, no fallback probe when the primary answers, the saved-old-IP migration, the fallback
never persisted, the cleartext host list, `normalizeServerUrl` refusing credentials and a query —
plus the no-fallback-key case, the third-party-catalog case, the both-dead error sentence, and a
fragment refusal. They read
`brand.properties` rather than typing `https://primary.test`, so a build that still shipped plain HTTP
as its default would fail them instead of passing.

**Nothing was compiled or run on this VM** beyond `python3 -S Fast_Fetch/test_docs_invariants.py`
(22 tests, OK, 0.34 s) — the load gate stands, so Kotlin correctness, the new unit tests and the
generated network policy are judged by hosted CI only. Run ids and verdicts are in the pane report;
no local number is claimed for a suite that did not run here.

## Owner follow-up this lane must not do

The Blogger deadman page (`network.gateway_discovery_url`) should be updated by the owner to
`primary https://raddstream.duckdns.org`, `backups ["http://92.4.95.252"]`. No Blogger sign-in, no
blog edit and no nginx/service change happened in this session, and the app does not depend on that
page for this feature: the fallback comes from the brand file.
