"""Security helpers: hashing, tokens, masking, redaction, validation.

No secret is ever logged or printed by this module. Callers must never
put a password, token, hash, session token, raw URL, or transaction id
into an audit row, a log line, or a response body — see redact_payload().
"""
import base64
import hashlib
import hmac as hmac_mod
import re
import secrets
import struct
import time

PBKDF2_ITERATIONS = 600_000
SESSION_ABSOLUTE_S = 12 * 3600
SESSION_IDLE_S = 8 * 3600
LOCKOUT_ACCOUNT = 5
LOCKOUT_IP = 20
LOCKOUT_WINDOW_S = 15 * 60
LOCKOUT_S = 15 * 60

# Words that must never appear as keys or values in a public body, an
# audit row, or an export. A match fails the whole response closed.
PROVENANCE_KEYS = {
    "url", "final_url", "source_url", "signed_url", "token", "password",
    "password_hash", "session_token", "totp_secret", "recovery_code",
    "tid", "transaction_id", "api_token", "shrinkme_api_token",
    "droplink_api_token", "device_id", "full_ip",
}
_URL_RE = re.compile(r"https?://\S+")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def hash_password(password):
    salt = secrets.token_bytes(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2-sha256:%d:%s:%s" % (
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def check_password(password, stored):
    try:
        _algo, iters, salt_b64, dk_b64 = stored.split(":")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iters)
        )
        return hmac_mod.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def mask_ip(ip):
    """First 3 octets / prefix only, for audit display."""
    if not ip:
        return ""
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:3]) + ":*"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".*"
    return "masked"


def mask_secret(value):
    """Shortener/payment tokens: 'configured' only, never the value."""
    return "configured" if value else "not configured"


def mask_hint(value):
    """Truncated account hint: first 2 and last 2 characters only."""
    if not value:
        return ""
    v = str(value)
    if len(v) <= 4:
        return v[:1] + "***"
    return v[:2] + "***" + v[-2:]


def mask_contact(value):
    if not value:
        return ""
    v = str(value)
    if "@" in v:
        local, _, domain = v.partition("@")
        return (local[:1] + "***@" + domain) if local else "***@" + domain
    if len(v) > 4:
        return v[:2] + "***" + v[-2:]
    return "***"


def scrub_text(text, limit=200):
    if text is None:
        return ""
    t = str(text).strip()
    t = _URL_RE.sub("[link removed]", t)
    return t[:limit]


def redact_payload(obj):
    """Return a redacted copy, or raise ValueError on a provenance leak.

    Any key in PROVENANCE_KEYS, or any string value containing a URL,
    fails closed: the caller must refuse the whole response, never a
    partial render. The one exception is the operator-only payment
    detail view, which is handled by a separate, explicitly-gated
    function and is never passed through here.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in PROVENANCE_KEYS:
                raise ValueError("provenance leak: forbidden key %s" % k)
            out[k] = redact_payload(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_payload(v) for v in obj]
    if isinstance(obj, str):
        if _URL_RE.search(obj):
            raise ValueError("provenance leak: URL in value")
        return obj
    return obj


def check_no_provenance(obj):
    """True if redact_payload would pass; used by the leak-scan tests."""
    try:
        redact_payload(obj)
        return True
    except ValueError:
        return False


def valid_slug(value):
    return isinstance(value, str) and bool(_SLUG_RE.match(value))


def valid_hex(value):
    return isinstance(value, str) and bool(_HEX_RE.match(value))


def valid_domain(value):
    """Domain only: no scheme, no path, no query, no token."""
    if not isinstance(value, str) or "/" in value or "?" in value or ":" in value:
        return False
    if value.startswith(("http", "www.")) and "." not in value:
        return False
    return bool(_DOMAIN_RE.match(value)) and "." in value


def require_fields(body, allowed):
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise ValueError("unknown field: %s" % ",".join(unknown))
    return body


def capped_text(value, limit, field="text"):
    if not isinstance(value, str):
        raise ValueError("%s must be text" % field)
    if len(value) > limit:
        raise ValueError("%s is too long" % field)
    return value.strip()


def totp_code(secret_b32, when=None):
    """RFC 6238 TOTP, SHA-1, 30s step, 6 digits. Secret is base32."""
    if when is None:
        when = int(time.time())
    key = base64.b32decode(secret_b32.upper())
    counter = struct.pack(">Q", when // 30)
    digest = hmac_mod.new(key, counter, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return "%06d" % code


def check_totp(secret_b32, code, window=1):
    if not secret_b32 or not code:
        return False
    now = int(time.time())
    for step in range(-window, window + 1):
        if hmac_mod.compare_digest(totp_code(secret_b32, now + step * 30), str(code)):
            return True
    return False


def xor_encrypt(secret_key, plaintext):
    """Placeholder-grade secret wrapping (see decisions file).

    XOR keystream from SHA-256(key || counter). This is NOT a reviewed
    secret store; TOTP is disabled by default and the gate must review
    this before any live owner enables TOTP.
    """
    data = plaintext.encode()
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.sha256(secret_key + struct.pack(">Q", counter)).digest()
        out.extend(block)
        counter += 1
    return base64.b64encode(bytes(b ^ k for b, k in zip(data, out))).decode()


def xor_decrypt(secret_key, blob):
    try:
        data = base64.b64decode(blob)
    except Exception:
        return None
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.sha256(secret_key + struct.pack(">Q", counter)).digest()
        out.extend(block)
        counter += 1
    try:
        return bytes(b ^ k for b, k in zip(data, out)).decode()
    except Exception:
        return None
