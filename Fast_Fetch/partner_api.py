#!/usr/bin/env python3
"""Partner API skeleton — `/api/partner/v1/**`.

Reference implementation of `Fast_Fetch/PARTNER_API.md`. It is **not registered on any live
server**: `viewer.py` does not import this module and `fast_fetch.py serve` routes nothing here.
Wiring it up is a deliberate, reviewable change, which is the same fence the spec asks for,
applied to the code rather than to the data.

Stdlib only. Tier B (source-link resolution) is fenced twice: a per-tenant column that
defaults to 0 and cannot be set by any request, and a module-level global that must also be
true. See PARTNER_API.md §1.1 before changing either.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
NAMESPACE = "/api/partner/v1"
KEY_PREFIX = "rk_live_"
QUERY_KEY_NAMES = ("key", "apikey", "api_key", "token")
MAX_BODY_BYTES = 8 * 1024

#: Global kill switch for source-link resolution. Off. A per-tenant DB flag does not
#: override it; both must be true for a URL to leave the building (PARTNER_API.md §1.1).
PARTNER_TIER_B_ENABLED = False

#: Bumped on any breaking change to the response contract, per §2.
CONTRACT_REVISION = "v1"

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS api_tenants (
      tenant_id TEXT PRIMARY KEY,               -- public id, echoed in X-Partner-Tenant
      key_hash TEXT NOT NULL UNIQUE,            -- sha256(key) hex; the plaintext is never stored
      key_prefix TEXT NOT NULL,                 -- first 12 chars, for support lookup only
      name TEXT NOT NULL,
      plan TEXT NOT NULL DEFAULT 'standard',
      rpm_cap INTEGER NOT NULL DEFAULT 60,
      daily_quota INTEGER NOT NULL DEFAULT 10000,
      status TEXT NOT NULL DEFAULT 'active'
             CHECK (status IN ('active','suspended','terminated')),
      allow_tier_b INTEGER NOT NULL DEFAULT 0 CHECK (allow_tier_b IN (0,1)),
      attribution_required INTEGER NOT NULL DEFAULT 1,
      issued_at INTEGER NOT NULL,
      revoked_at INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_usage (
      tenant_id TEXT NOT NULL,
      day TEXT NOT NULL,                        -- UTC YYYY-MM-DD
      requests INTEGER NOT NULL DEFAULT 0,
      refused INTEGER NOT NULL DEFAULT 0,        -- 4xx/429 are still load
      peak_rpm INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (tenant_id, day)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts INTEGER NOT NULL,
      tenant_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      work_id INTEGER,
      detail TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON api_audit(tenant_id, ts)",
)

#: code -> (status, title). The refusal shapes are contract, not implementation detail.
PROBLEMS = {
    "missing_key": (401, "No credential supplied"),
    "unknown_key": (401, "Unknown tenant"),
    "revoked_key": (401, "Credential revoked"),
    "credential_in_query": (401, "Credential must be sent as a header"),
    "tenant_suspended": (403, "Tenant suspended"),
    "plan_expired": (403, "Plan term ended"),
    "endpoint_not_in_plan": (403, "Endpoint not included in your plan"),
    "tier_not_enabled": (403, "This capability is not enabled for your tenant"),
    "not_found": (404, "Not found"),
    "stale_cursor": (409, "Catalog revision moved during the walk"),
    "invalid_input": (400, "Invalid input"),
    "body_too_large": (413, "Request body too large"),
    "rate_limited": (429, "Per-minute rate limit reached"),
    "quota_exhausted": (429, "Daily quota exhausted"),
    "tier_globally_disabled": (503, "Capability disabled service-wide"),
    "internal": (500, "Internal error"),
}

#: Route table. `tier` is enforced by `release_allowed()`, never by the client.
ROUTES = (
    ("GET", "/catalog", "A"),
    ("GET", "/works/{work_id}", "A"),
    ("GET", "/search", "A"),
    ("GET", "/works/{work_id}/seasons/{season}/episodes", "A"),
    ("GET", "/updates", "A"),
    ("GET", "/health/aggregate", "A"),
    ("GET", "/me", "A"),
    ("GET", "/me/usage", "A"),
    ("POST", "/resolve", "B"),
)


def _template_to_regex(path: str) -> re.Pattern:
    """/works/{work_id} -> a pattern with one named group per {placeholder}."""
    parts = []
    for chunk in re.split(r"(\{[a-z_]+\})", NAMESPACE + path):
        if chunk.startswith("{") and chunk.endswith("}"):
            parts.append(f"(?P<{chunk[1:-1]}>[^/]+)")
        else:
            parts.append(re.escape(chunk))
    return re.compile("^" + "".join(parts) + "$")


_TEMPLATES = tuple((method, _template_to_regex(path), path, tier)
                   for method, path, tier in ROUTES)


def utc_day(now: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def problem(code: str, detail: str = "", **extra) -> dict:
    status, title = PROBLEMS.get(code, PROBLEMS["internal"])
    body = {
        "type": f"{NAMESPACE}/problems/{code}",
        "code": code if code in PROBLEMS else "internal",
        "title": title,
        "detail": detail,
        "status": status,
    }
    body.update(extra)
    return body


def ensure_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        conn.execute(statement)
    conn.commit()


def issue_tenant(conn: sqlite3.Connection, *, name: str, plan: str = "standard",
                 rpm_cap: int = 60, daily_quota: int = 10000,
                 attribution_required: int = 1) -> tuple[dict, str]:
    """Create a tenant and return (row, plaintext_key). The plaintext exists only here."""
    key = new_key()
    tenant_id = "p_" + secrets.token_hex(4)
    conn.execute(
        "INSERT INTO api_tenants (tenant_id, key_hash, key_prefix, name, plan, rpm_cap,"
        " daily_quota, issued_at, attribution_required)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tenant_id, hash_key(key), key[:12], name, plan, int(rpm_cap), int(daily_quota),
         int(time.time()), int(attribution_required)))
    conn.commit()
    row = conn.execute("SELECT * FROM api_tenants WHERE tenant_id = ?",
                       (tenant_id,)).fetchone()
    return dict(row), key


def authorize(conn: sqlite3.Connection, *, header_key: str | None,
              query: dict | None = None) -> dict | str:
    """Return the tenant row, or a problem code. Never trusts a query-string credential."""
    query = query or {}
    if any(query.get(name) for name in QUERY_KEY_NAMES):
        return "credential_in_query"
    if not header_key:
        return "missing_key"
    row = conn.execute("SELECT * FROM api_tenants WHERE key_hash = ? AND revoked_at IS NULL",
                       (hash_key(header_key),)).fetchone()
    if row is None:
        known = conn.execute("SELECT 1 FROM api_tenants WHERE key_hash = ?",
                             (hash_key(header_key),)).fetchone()
        return "revoked_key" if known else "unknown_key"
    tenant = dict(row)
    if tenant["status"] != "active":
        return "tenant_suspended"
    return tenant


def route_for(method: str, path: str) -> tuple[str, str] | None:
    """(path_template, tier) for an exact match, or None."""
    for template_method, pattern, template, tier in _TEMPLATES:
        if template_method == method.upper() and pattern.match(path):
            return template, tier
    return None


def release_allowed(tenant: dict, tier: str) -> bool:
    """Tier B needs the tenant flag AND the global switch. Tier A needs neither."""
    if tier != "B":
        return True
    return bool(PARTNER_TIER_B_ENABLED and int(tenant.get("allow_tier_b") or 0))


#: Fixed-window per-minute counters. Process-local by design; the durable number is api_usage.
#: A restart rolls the window, which is documented in PARTNER_API.md §5 and is not a boundary.
_minute_counts: dict[str, tuple[int, int]] = {}


def check_rate(conn: sqlite3.Connection, tenant: dict, *, now: float | None = None) -> dict:
    """Meter one request. Returns headers, and `problem` when this request must be refused."""
    now = time.time() if now is None else now
    window = int(now // 60)
    tenant_id = str(tenant["tenant_id"])
    count = _minute_counts.get(tenant_id)
    if count is None or count[0] != window:
        count = (window, 0)
    count = (window, count[1] + 1)
    _minute_counts[tenant_id] = count
    used, remaining = count[1], max(0, int(tenant["rpm_cap"]) - count[1])
    reset = (window + 1) * 60

    day = utc_day(now)
    row = conn.execute("SELECT requests, refused FROM api_usage WHERE tenant_id = ? AND day = ?",
                       (tenant_id, day)).fetchone()
    today = int(row["requests"]) if row else 0
    refused_today = int(row["refused"]) if row else 0

    headers = {
        "X-Partner-Tenant": tenant_id,
        "X-RateLimit-Limit": str(tenant["rpm_cap"]),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
        "X-Quota-Daily-Limit": str(tenant["daily_quota"]),
        "X-Quota-Daily-Remaining": str(max(0, int(tenant["daily_quota"]) - today)),
    }
    if today >= int(tenant["daily_quota"]):
        conn.execute("INSERT INTO api_usage (tenant_id, day, requests, refused)"
                     " VALUES (?, ?, ?, ?) ON CONFLICT(tenant_id, day) DO UPDATE SET"
                     " refused = refused + 1", (tenant_id, day, today, refused_today + 1))
        conn.commit()
        return {"headers": headers, "problem": problem(
            "quota_exhausted", "Daily quota reached.",
            retry_at=(int(time.mktime(time.strptime(day + " 00:00:00", "%Y-%m-%d %H:%M:%S"))))
            + 86400), "counted": False}

    conn.execute("INSERT INTO api_usage (tenant_id, day, requests, peak_rpm)"
                 " VALUES (?, ?, 1, ?) ON CONFLICT(tenant_id, day) DO UPDATE SET"
                 " requests = requests + 1,"
                 " peak_rpm = MAX(peak_rpm, excluded.peak_rpm)",
                 (tenant_id, day, used))
    conn.commit()
    if used > int(tenant["rpm_cap"]):
        return {"headers": headers, "problem": problem(
            "rate_limited", "Per-minute cap reached.", retry_after=max(1, reset - int(now))),
            "counted": True}
    return {"headers": headers, "problem": None, "counted": True}


def audit(conn: sqlite3.Connection, tenant_id: str, kind: str, *, work_id=None,
          detail: dict | None = None) -> None:
    """Refusals are audited too; see PARTNER_API.md §6.3. Never a key, never a request URL."""
    conn.execute("INSERT INTO api_audit (ts, tenant_id, kind, work_id, detail)"
                 " VALUES (?, ?, ?, ?, ?)",
                 (int(time.time()), tenant_id, kind, work_id,
                  json.dumps(detail or {}, sort_keys=True, default=str)))
    conn.commit()


def handle(conn: sqlite3.Connection, *, method: str, path: str, key: str | None,
           query: dict | None = None, body_bytes: int = 0,
           now: float | None = None) -> dict:
    """The whole gate, in order: credential, edge size, rate, route, tier, then the handler.

    Tier A handlers read through `catalog_api` under `public_edge`/`redact.scrub` and are not
    implemented here — this function's job is that nothing reaches them without passing these
    checks, and that /resolve cannot be reached by a tenant nobody signed off.
    """
    if body_bytes > MAX_BODY_BYTES:
        return {"status": 413, "body": problem("body_too_large", "Max 8 KiB."), "headers": {}}
    tenant = authorize(conn, header_key=key, query=query)
    if isinstance(tenant, str):
        return {"status": PROBLEMS[tenant][0], "body": problem(tenant), "headers": {}}
    metered = check_rate(conn, tenant, now=now)
    if metered["problem"] is not None:
        return {"status": metered["problem"]["status"], "body": metered["problem"],
                "headers": metered["headers"]}
    matched = route_for(method, path)
    if matched is None:
        return {"status": 404, "body": problem("not_found"), "headers": metered["headers"]}
    template, tier = matched
    if not release_allowed(tenant, tier):
        # Two distinct refusals, one decision function: the global switch answers "may anyone
        # ever have this", the tenant flag answers "may you". Reporting them differently is
        # what lets an operator tell a signed-off customer from a trespasser.
        code = ("tier_globally_disabled" if not PARTNER_TIER_B_ENABLED else "tier_not_enabled")
        audit(conn, tenant["tenant_id"], "tier_b_refused",
              detail={"reason": code, "route": template})
        detail_text = ("Source-link resolution is disabled service-wide."
                       if code == "tier_globally_disabled" else
                       "Source-link resolution requires explicit per-tenant enablement by the"
                       " data owner. Tier A metadata is unaffected.")
        return {"status": PROBLEMS[code][0], "headers": metered["headers"],
                "body": problem(code, detail_text)}
    return {"status": 200, "headers": metered["headers"],
            "body": {"data": [], "tier": tier, "contract": CONTRACT_REVISION,
                     "route": template},
            "tier": tier, "tenant": tenant}


# ── self-test ────────────────────────────────────────────────────────────────

def self_test() -> int:
    """The four assertions that must not regress, per PARTNER_API.md §10."""
    failures: list[str] = []
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    def expect(name, ok, detail=""):
        if not ok:
            failures.append(f"{name}: {detail}")

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    expect("the three contract tables exist",
           {"api_tenants", "api_usage", "api_audit"} <= tables, str(sorted(tables)))

    global PARTNER_TIER_B_ENABLED

    tenant, key = issue_tenant(conn, name="Acme Streaming")
    expect("tenant defaults allow_tier_b to 0", int(tenant["allow_tier_b"]) == 0,
           f"got {tenant['allow_tier_b']}")
    stored_values = [str(v) for v in tenant.values()]
    expect("the plaintext key is nowhere in the stored row",
           not any(key in value for value in stored_values),
           "issuance must be the only place the plaintext exists")
    expect("the row carries the sha256, not a reversible form",
           hash_key(key) in stored_values, "key_hash must equal sha256(key)")

    ok = handle(conn, method="GET", path=NAMESPACE + "/search", key=key,
                query={"q": "dune"})
    expect("Tier A search is served", ok["status"] == 200 and ok["tier"] == "A", str(ok))

    fence = handle(conn, method="POST", path=NAMESPACE + "/resolve", key=key,
                   body_bytes=256)
    expect("resolve refused with the global switch off", fence["status"] == 503
           and fence["body"]["code"] == "tier_globally_disabled", str(fence["body"]))

    conn.execute("UPDATE api_tenants SET allow_tier_b = 1 WHERE tenant_id = ?",
                 (tenant["tenant_id"],))
    conn.commit()
    promoted = dict(conn.execute("SELECT * FROM api_tenants WHERE tenant_id = ?",
                                 (tenant["tenant_id"],)).fetchone())
    expect("per-tenant flag alone does not open Tier B",
           not release_allowed(promoted, "B") and PARTNER_TIER_B_ENABLED is False,
           "release_allowed must require the global switch too")

    PARTNER_TIER_B_ENABLED = True
    try:
        both = handle(conn, method="POST", path=NAMESPACE + "/resolve", key=key,
                      body_bytes=256)
        expect("both switches on serves Tier B for an enabled tenant",
               both["status"] == 200 and both["tier"] == "B", str(both["body"]))
        other, other_key = issue_tenant(conn, name="Never Signed Off")
        expect("a second tenant still defaults to fenced",
               int(other["allow_tier_b"]) == 0, f"got {other['allow_tier_b']}")
        expect("with the global switch ON, the tenant flag is what gates Tier B",
               release_allowed(promoted, "B") is True
               and release_allowed(other, "B") is False,
               "a gate that only checks the global switch is a single fence, not a double one")
        refusal = handle(conn, method="POST", path=NAMESPACE + "/resolve",
                         key=other_key, body_bytes=256)
        expect("global-on does NOT open Tier B for an unflagged tenant",
               refusal["status"] == 403
               and refusal["body"]["code"] == "tier_not_enabled", str(refusal["body"]))
        missing = handle(conn, method="GET", path=NAMESPACE + "/search", key=None)
        expect("missing credential is 401 missing_key", missing["status"] == 401
               and missing["body"]["code"] == "missing_key", str(missing["body"]))
        audited = conn.execute("SELECT COUNT(*) FROM api_audit"
                               " WHERE kind = 'tier_b_refused'").fetchone()[0]
        expect("refusals are audited", audited >= 2, f"{audited} rows")
    finally:
        PARTNER_TIER_B_ENABLED = False

    in_query = handle(conn, method="GET", path=NAMESPACE + "/search", key=None,
                      query={"q": "dune", "key": key})
    expect("a key in the query string is refused",
           in_query["status"] == 401 and in_query["body"]["code"] == "credential_in_query",
           str(in_query["body"]))

    unknown = handle(conn, method="GET", path=NAMESPACE + "/search", key=rk_bogus())
    expect("an unknown key is 401 unknown_key", unknown["status"] == 401
           and unknown["body"]["code"] == "unknown_key", str(unknown["body"]))

    caps = {}
    base = time.time()
    for i in range(int(tenant["rpm_cap"]) + 2):
        r = handle(conn, method="GET", path=NAMESPACE + "/catalog", key=key,
                   now=base + (i % 1))
        caps[r["body"].get("code", "ok")] = caps.get(r["body"].get("code", "ok"), 0) + 1
    expect("the minute bucket rolls and eventually refuses",
           caps.get("rate_limited", 0) >= 1, json.dumps(caps, sort_keys=True))

    rolled = handle(conn, method="GET", path=NAMESPACE + "/catalog", key=key,
                    now=base + 90)
    expect("the next minute is served again", rolled["status"] == 200, str(rolled["body"]))

    size = handle(conn, method="POST", path=NAMESPACE + "/resolve", key=key,
                  body_bytes=MAX_BODY_BYTES + 1)
    expect("oversized body is refused at the gate", size["status"] == 413, str(size["body"]))

    for name in failures:
        print("FAIL " + name)
    print(("SELF-TEST FAILED (%d)" % len(failures)) if failures else
          "SELF-TEST OK — schema defaults, double-fence, header-only credential, limiter roll")
    conn.close()
    return 1 if failures else 0


def rk_bogus() -> str:
    return KEY_PREFIX + "AAAAAAAAAAAAAAAAAAAAAAAA"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                       help="run the in-memory gate checks and exit")
    parser.add_argument("--schema", action="store_true",
                       help="print the DDL the owner may apply to a staging database")
    args = parser.parse_args(argv)
    if args.schema:
        print(";\n".join(SCHEMA) + ";")
        return 0
    if args.self_test:
        return self_test()
    parser.print_help()
    print(f"\nNothing is served. This module is unregistered on purpose;"
          f" see {BASE_DIR / 'PARTNER_API.md'} §10.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
