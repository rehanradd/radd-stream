"""Test helpers. Fixtures are MOCK only; no real credential, token,
URL, or transaction id is used anywhere in these tests."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_v2.security import hash_password  # noqa: E402
from admin_v2.services import Service  # noqa: E402


def make_service():
    tmp = tempfile.mkdtemp(prefix="adminv2-test-")
    svc = Service(tmp)
    owner_id = svc.create_owner("owner", "correct horse battery staple")
    owner = {"id": owner_id, "username": "owner", "role": "owner"}
    # Auditor, inserted directly (there is no admin-account creation
    # endpoint in v2, by design).
    svc.admin.execute(
        "INSERT INTO admin_users (username, password_hash, role, created_at) VALUES (?,?,?,?)",
        ("auditor", hash_password("correct horse battery staple"), "auditor", 1700000000),
    )
    svc.admin.commit()
    row = svc.admin.execute("SELECT * FROM admin_users WHERE username='auditor'").fetchone()
    auditor = {"id": row["id"], "username": "auditor", "role": "auditor"}
    return svc, owner, auditor


def good_checker(domain):
    return {"dns_ok": True, "tcp_ok": True, "tls_ok": True, "http_status": 200,
            "fingerprint_ok": True, "latency_ms": 120, "failure_reason": None}


def bad_checker(domain):
    return {"dns_ok": False, "tcp_ok": False, "tls_ok": False, "http_status": None,
            "fingerprint_ok": False, "latency_ms": None, "failure_reason": "dns_fail"}
