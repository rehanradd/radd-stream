"""Emergency recovery (OD-03) — VM-local CLI ONLY, disabled by default.

No web endpoint ships for this. On the VM terminal only:
    python3 -m admin_v2.recovery --base-dir /path/to/admin-data enable
prints ONE one-time token, once, on that terminal. Only its SHA-256
hash (plus a 15-minute expiry) is stored, in admin_v2.db. A token is
single-use; after use or expiry it is gone. Nothing here prints,
logs, or stores a token value, and no HTTP route calls this module.
"""
import argparse
import hashlib
import secrets
import time

from .store import WRITE_LOCK, connect, migrate

TOKEN_TTL_S = 15 * 60


def _ensure_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS admin_recovery_tokens ("
        "id INTEGER PRIMARY KEY, token_hash TEXT NOT NULL, "
        "created_at INTEGER, expires_at INTEGER, used_at INTEGER)")
    conn.commit()


def enable_recovery(base_dir):
    """Generate one token, store only its hash. Returns the token
    (the CLI prints it once; callers must not store or log it)."""
    import os
    conn = connect(os.path.join(base_dir, "admin_v2.db"))
    migrate(conn)
    _ensure_table(conn)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with WRITE_LOCK:
        conn.execute(
            "INSERT INTO admin_recovery_tokens (token_hash, created_at, expires_at) "
            "VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), now, now + TOKEN_TTL_S))
        conn.commit()
    conn.close()
    return token


def verify_recovery(base_dir, token):
    """Single-use verify. Returns True only once, before expiry."""
    import os
    conn = connect(os.path.join(base_dir, "admin_v2.db"))
    migrate(conn)
    _ensure_table(conn)
    now = int(time.time())
    digest = hashlib.sha256(str(token or "").encode()).hexdigest()
    row = conn.execute(
        "SELECT * FROM admin_recovery_tokens WHERE token_hash=? AND used_at IS NULL "
        "AND expires_at>? ORDER BY id DESC LIMIT 1", (digest, now)).fetchone()
    if not row:
        conn.close()
        return False
    with WRITE_LOCK:
        conn.execute("UPDATE admin_recovery_tokens SET used_at=? WHERE id=?",
                     (now, row["id"]))
        conn.commit()
    conn.close()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="VM-local emergency recovery token.")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("action", choices=["enable"])
    args = parser.parse_args(argv)
    token = enable_recovery(args.base_dir)
    print("One-time recovery token (valid 15 minutes, single use). "
          "Show it once, then it is gone:")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
