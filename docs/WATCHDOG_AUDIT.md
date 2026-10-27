# WATCHDOG AUDIT — Read-Only Quality Monitor

> **Role:** quality assurance, code audit, progress monitoring.
> **Constraint:** this file is the *only* thing the watchdog writes. No application
> source, test, config, or deployment file is modified by an audit run.
>
> **Latest run:** 2026-10-27 01:51 PKT (2026-10-26 20:51 UTC)
> **Tree:** branch `master`, HEAD `27fc043`, 95 changed/untracked paths (dirty)
> **Auditor:** read-only watchdog pass (no edits)

---

## Verdict at a glance

| Area | Result |
|---|---|
| Unit tests (15 offline suites, 524 tests) | ✅ all pass |
| Python stdlib compliance | ✅ no third-party imports |
| Syntax errors | ✅ none |
| Live service health | ✅ active, 34.2 MB RSS (peak 34.4 MB) |
| System load / memory | ✅ load 2.19; 6.8 GB available |
| Secrets hygiene | ❌ **CRITICAL — live HF token in an executed script** |
| Redaction coverage | ⚠️ medium gap on the production DB |
| Endpoint latency | ⚠️ `/api/v1/stats` = 3.6 s |
| Deployment traceability | ⚠️ stale `.deployed_commit`; service runs dirty tree |
| App build re-verified this pass | ⛔ not run (read-only pass; see §7) |

---

## 1. CRITICAL — live Hugging Face token hardcoded in an executed script

**File:** `Fast_Fetch/auto_crawl_cron.sh:16`

```bash
export HF_TOKEN="hf_KuFLOz…REDACTED"   # value intentionally not reproduced here
```

Why this is critical, not theoretical:

- The script is **untracked but NOT gitignored** (`git check-ignore` exits 1), so a
  routine `git add .` would commit the token.
- It is the `ExecStart` of `radd-autocrawl.service`, which is **enabled and active**
  and runs as `ubuntu` on `OnCalendar=*-*-* 02,08,14,20:00:00`.
- The literal is `export`ed, so it is inherited by every child process spawned by
  the pipeline (`fast_fetch.py sync`, `merge_fleet.py`, `backup-hf`) and is visible
  in `/proc/<pid>/environ`.
- AGENTS.md requires credentials to come from the environment/config, never from a
  file in the tree. This file violates that rule.

**Recommended remediation (owner action, not performed by the watchdog):**

1. **Revoke/rotate** the token at the Hugging Face account now. Treat it as leaked;
   it has existed in plaintext on disk and in a running service environment.
2. Replace the literal with `: "${HF_TOKEN:?set HF_TOKEN in the service Environment}"`
   and supply it via `EnvironmentFile=` on the systemd unit (mode `0600`), matching
   how `RADD_DB_PATH` is already supplied in `/etc/systemd/system/radd-stream.service`.
3. Add `Fast_Fetch/auto_crawl_cron.sh` (or a broader `*.sh` policy) to `.gitignore`
   until the literal is removed, so no accidental commit occurs meanwhile.
4. Keep the watchdog out of the fix; this is an owner/agent action, not a monitor edit.

Related, lower-risk: `Fast_Fetch/test_backup_manager.py:122` contains
`hf_supersecrettoken1234567890` — a **dummy test fixture**, verified as fake. No action.

---

## 2. MEDIUM — redaction needle set silently loses 714/718 services on production

**File:** `Fast_Fetch/redact.py:1138-1155` (`site_needles`)

The new guard only scans `download_sources.service` / `source_name` when a
`idx_sources_service` index exists **by name**, or when the table has fewer than
100 000 rows:

```python
sub_cnt = conn.execute("SELECT count(*) FROM (SELECT 1 FROM download_sources LIMIT 100000)").fetchone()[0]
if has_service_idx or sub_cnt < 100000:
    ...
```

Measured against the live catalog (`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db`,
5.8 GB, `RADD_DB_PATH` of the running service):

- `download_sources` = **3 783 959** rows.
- Indexes present: `idx_sources_rel`, `idx_sources_res`, `idx_sources_status_temp`,
  `idx_sources_rel_status`. **No `idx_sources_service`.**
- Therefore `sub_cnt` = 100 000 → `sub_cnt < 100000` is false → **the whole block is skipped.**
- Distinct `service` values: **718**. Of those, **714 are not covered by
  `domain_registry.json` site names** (e.g. `1fichier`, `1cloudfile`, `animezia-mirror`, …).

The in-code comment says "`_registry_needles()` already carries all canonical hosters
and services," but measurement shows the registry is keyed by scraper site name, not
by download-service name. Net effect: on the production DB the comment's premise does
not hold and 714 hoster tokens are absent from the detection needle set.

**Severity rationale:** this weakens `redact.is_clean` / leak detection; it is not a
direct data exposure, and the skip is a deliberate performance trade-off (an
unindexed `SELECT DISTINCT service` cost 2.43 s in this audit). Still a documented
coverage regression versus the pre-change behaviour, which always scanned.

**Coverage gap in tests:** `Fast_Fetch/test_redact.py` exercises only the small-table
branch; there is no test that constructs a ≥100 000-row `download_sources` and asserts
the intended behaviour. The skip branch is effectively untested.

**Recommended (owner/agent):** either add a functional index on `download_sources(service)`
and match on index *presence* rather than a specific name, or replace the skip with a
bounded sampled scan (`SELECT DISTINCT service FROM download_sources LIMIT …`) so a
partial set is still added. Whichever is chosen, add a regression test for the
large-table path.

---

## 3. MEDIUM — `/api/v1/stats` latency on the 5.8 GB catalog

Measured against the running service (loopback, 30 s ceiling):

| Endpoint | Status | Time |
|---|---|---|
| `/api/v1/app/remote-config` | 200 | 0.003 s |
| `/api/v1/posts?limit=20` | 200 | 0.077 s |
| `/client` | 200 | 0.001 s |
| `/api/v1/stats` | 200 | **3.591 s** |

A first 5 s probe returned `000` (timeout), so stats sits near/over common client
timeouts under load. Cause is consistent with unbounded `COUNT(*)` over the largest
tables on a 5.8 GB file. `sweep_public_edge.py` now probes this path on every sweep
(added in this diff), so the cost is exercised repeatedly.

**Recommended:** cache the stats payload with a short TTL, or maintain counters
incrementally; keep the sweep probe but accept a cached response.

---

## 4. LOW — deployment traceability is stale

- `.deployed_commit` = `938f5f7`
- HEAD = `27fc043`
- Working tree = 95 changed/untracked paths
- The service was (re)started 10 minutes before this audit and runs
  `/opt/radd-stream/Fast_Fetch/fast_fetch.py` **from the dirty working tree**.

So the running service is neither at HEAD nor at the recorded deployed commit.
`ORACLE_DEPLOYMENT.md` treats `.deployed_commit` as the record of what is live; it is
currently wrong. This matters for every later "what is actually running?" question.

**Recommended:** update `.deployed_commit` only from a verified, tested release path,
and do not restart the service from an uncommitted tree except for deliberate local
testing (annotate it if so).

---

## 5. LOW — idle JVM daemons dominate memory

`free -m`: total 11 925, used 5 121, available 6 804. Load 2.19 / 0.82 / 0.69.

| PID | RSS | Process |
|---|---|---|
| 13769 | 1 408 764 KB (~1.34 GB) | Java (Kotlin/Gradle daemon) |
| 13429 | 913 044 KB (~0.87 GB) | Java (Gradle daemon) |
| 4275 | 680 776 KB | `agy` |
| 18784 | ~34 MB | `radd-stream.service` (the actual API) |

The two Gradle/Kotlin daemons are ~30 minutes old and idle, holding ~2.2 GB. The
backend itself is lean. No action was taken (stopping processes is outside the
read-only mandate); `./gradlew --stop` in `App/` would free the bulk of it when no
build is in flight.

---

## 6. LOW — admin token accepted via query string

`Fast_Fetch/admin_panel.py` gate order is correct and strong in the ways that matter:

- ✅ loopback peer check runs **before** any SQL;
- ✅ token compared with `hmac.compare_digest`;
- ✅ **fail-closed** when `RADD_ADMIN_TOKEN` is unset (empty never means open);
- ✅ identical 401 body for missing vs. wrong token.

One hygiene issue: `effective_token = token_header or query.get("token", ...)` means
the bearer token is also accepted as `?token=…`, which can land in access logs,
shell history, and browser referrers. The module docstring already acknowledges the
in-transit limitation and leans on the loopback requirement. Acceptable as-is for a
loopback-only surface; prefer header-only if the query path is not needed.

The `f"… {MONETIZATION_TABLE} …"` interpolations in `admin_panel.py` were checked:
`MONETIZATION_TABLE` is a module constant (`admin_panel.py:503`), and `_count()`'s
`table` argument is drawn only from fixed `_CAT_TABLES` / `_LEDGER_TABLES` tuples.
No user input reaches those SQL strings.

---

## 7. Test and compliance detail

### 7.1 Requested suites

| Suite | Tests | Result |
|---|---|---|
| `test_database.py` | 63 | ✅ OK (6.9 s) |
| `test_vidout.py` | 6 | ✅ OK (0.007 s) |
| `test_admin_panel.py` | 43 | ✅ OK (5.6 s) |

### 7.2 Additional offline suites covering the changed/new modules

| Suite | Tests | Result |
|---|---|---|
| `test_catalog_v2.py` | 91 | ✅ OK |
| `test_link_state.py` | 28 | ✅ OK |
| `test_link_health.py` | 57 | ✅ OK |
| `test_redact.py` | 49 | ✅ OK |
| `test_accounts.py` | 61 | ✅ OK |
| `test_operator_isolation.py` | 21 | ✅ OK |
| `test_download_endpoint.py` | 10 | ✅ OK |
| `test_backfill_tmdb.py` | 33 | ✅ OK |
| `test_evidence_writeback.py` | 12 | ✅ OK |
| `test_provenance_stamping.py` | 12 | ✅ OK |
| `test_release_descriptor.py` | 24 | ✅ OK |
| `test_backup_manager.py` | 14 | ✅ OK |

**Total: 524 tests, 0 failures, 0 errors.** `test_all_sites.py` was not run (live
network audit, out of scope for a read-only pass).

### 7.3 Python standard-library compliance

An `ast` walk over every `Fast_Fetch/**/*.py` resolved each import against
`sys.stdlib_module_names` plus local modules:

- **No syntax errors** in any file.
- **No third-party imports.**
- The only unresolved name is `Fast_Fetch` itself
  (`catalog_v2.py:2118`, `link_state.py:86,636`). This is an implicit-namespace
  package reference with an `except ImportError` fallback to a flat import; it is not
  a pip dependency. Note there is **no `Fast_Fetch/__init__.py`**, so the package-style
  path works only when the repo root is on `sys.path`. The guards handle the
  documented run-from-inside-the-directory case correctly.

### 7.4 Risky-pattern scan of the backend diff

`eval`, `exec`, `os.system`, `shell=True`, `pickle.loads`, and shelled `subprocess`
calls: **none** added. No SQL built from user input. The only f-string SQL is the
constant-table case described in §6.

### 7.5 App diff (static only)

- No hardcoded tokens/keys/passwords found under `App/app/src` (`.kt`/`.xml`).
- `AndroidManifest.xml` change adds `android:exported="false"`; no
  `usesCleartextTraffic` or `networkSecurityConfig` added.
- Kotlin compilation and instrumented/unit tests were **not** run this pass. Running
  Gradle would spawn another daemon and add build artifacts in a read-only role.
  App-level correctness therefore remains **unverified by this audit** until the
  nested workflow / a deliberate Gradle run confirms it.

---

## 8. Documentation drift (INFO)

- `AGENTS.md` "Agent Continuity Protocol" says `test_database.py` must be "36+ tests";
  the current count is **63**.
- `AGENTS.md` "Quick Commands Reference" labels it "54 tests"; actual is **63**.

Counts only ever grew; suggest updating the two references so a future agent does not
mistake a regression for the baseline.

---

## 9. What the watchdog did NOT do

- Did not edit any application source, test, config, unit file, or secret.
- Did not run `git add`, `commit`, `push`, `reset`, `checkout`, or `clean`.
- Did not stop processes (including the idle Gradle daemons).
- Did not run the live network site audit.
- This file is the sole write.

---

## 10. Next periodic checks

1. Re-confirm the HF token has been revoked and the script literal replaced (§1).
2. Re-run `test_database.py`, `test_vidout.py`, `test_admin_panel.py` and compare
   counts against the table in §7; investigate any drop.
3. Re-measure `/api/v1/stats` (§3) after any caching change.
4. Re-check `download_sources` index presence and the redaction needle count (§2).
5. Re-check systemd service RSS against the ~34 MB baseline and confirm whether
   orphaned Gradle daemons persist (§5).
6. Confirm `.deployed_commit` equals the commit the running service was started from (§4).
