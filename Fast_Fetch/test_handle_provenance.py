"""G4 — handle provenance: what the opaque public ids actually protect, measured.

The money-and-keys verdict (`docs/MUSE_PHASE1_Q5_MONEY_AND_KEYS.md`) makes five claims about handles
(KD-1..KD-5) that were, until this module, *prose with line numbers*. This is the executable half, and it
is a guard, not a fix: **no format here is changed, and nothing in `redact.py` is edited.** KD-1 is a
wire-format change and is explicitly unauthorised (Muse, 07:2x) — so this module's job is to make the
existing property *checkable*, in both directions: what holds today, and what is a hole that a lane must
not mistake for coverage.

Read off the code at the sha this branch is based on:

| fact | value | cite |
|---|---|---|
| id handle | `version(1) + body(8) + tag(4)` = 13 bytes, 32-bit tag | `redact.py:856-862` |
| text handle | `version(129) + len(2) + body + tag(4)` | `redact.py:925-930` |
| VIP pass | `version(3) + body(8) + tag(8)` = 17 bytes, 64-bit tag | `redact.py:893-906` |
| keystream | `sha256(secret + salt + be32(counter))`, salt is a **constant per kind** | `redact.py:832-840` |
| public port | accepts handles only (`signed_only=not full`) | `viewer.py:3683`, `:3949`, `:4011` |
| unconfigured secret | returns the literal `"radd-stream-dev-secret-unconfigured"` | `redact.py:957`, `:960`, `:978` |

Stdlib only, no socket, no server, no production database: handles are minted against a literal test
secret, and the one path that touches a file (`stream_secret` persisting a generated secret) is given a
`tempfile` path and nothing else.

Written under the LIGHT-ONLY freeze, so the hosted step is this module's first execution.
"""

import base64
import hashlib
import os
import pathlib
import sqlite3
import struct
import tempfile
import unittest
from unittest import mock

import redact

ROOT = pathlib.Path(__file__).resolve().parent

#: A test secret, never a deployment credential. Nothing here reads an env var that holds a real value.
SECRET = "g4-test-secret-not-a-deployment-key"

#: The literal `redact.stream_secret` answers with when nothing is configured. Quoted from the source by
#: this test rather than imported, because the point of the test is that it is *public knowledge*.
UNCONFIGURED = "radd-stream-dev-secret-unconfigured"


def _unb64(token: str) -> bytes:
    """Decode a handle without using `redact`'s own private helper.

    Deliberately independent: a guard that decodes with the same function it is auditing cannot notice
    that function changing its shape.
    """
    return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))


def _forge(body: bytes, version: int = 1) -> str:
    """A handle with a valid-looking structure and an all-zero tag."""
    return base64.urlsafe_b64encode(bytes([version]) + body + b"\x00\x00\x00\x00").decode("ascii").rstrip("=")


class HandleShapeTests(unittest.TestCase):
    """KD-2, pinned: the two tag widths are different, and that difference is load-bearing."""

    def test_an_id_handle_is_thirteen_bytes_with_a_thirty_two_bit_tag(self):
        token = redact.mint_token(12345, SECRET)
        data = _unb64(token)
        self.assertEqual(13, len(data),
                         "id handle layout changed: version+body+tag was 1+8+4")
        self.assertEqual(1, data[0])
        self.assertEqual(struct.pack(">q", 12345),
                         bytes(a ^ b for a, b in zip(data[1:9],
                                                     _pad(SECRET, 8, "id"))))
        self.assertEqual(4, len(data[9:]),
                         "the id tag is no longer 4 bytes — if it is now 8, update KD-2 and say so")
        self.assertEqual(12345, redact.parse_token(token, SECRET))

    def test_a_vip_pass_is_seventeen_bytes_with_a_sixty_four_bit_tag(self):
        expires = 2_000_000_000.0
        token = redact.mint_vip_pass(expires, SECRET)
        data = _unb64(token)
        self.assertEqual(17, len(data), "pass layout changed: version+body+tag was 1+8+8")
        self.assertEqual(3, data[0])
        self.assertEqual(8, len(data[9:]),
                         "the pass tag and the id tag now have the same width — KD-2 is resolved, "
                         "re-measure before you believe that")
        self.assertEqual(expires, redact.parse_vip_pass(token, SECRET, now=1_000_000.0))

    def test_a_text_handle_carries_the_same_thirty_two_bit_tag(self):
        token = redact.mint_text("https://cdn.example/poster.jpg", SECRET)
        data = _unb64(token)
        self.assertEqual(129, data[0], "mint_text version byte moved")
        self.assertEqual(4, len(data[-4:]))
        self.assertEqual("https://cdn.example/poster.jpg", redact.parse_text(token, SECRET))

    def test_a_pass_carries_no_identity_at_all(self):
        """The docstring's claim at `:896-901`, tested rather than trusted.

        Two different "holders" minting the same expiry get byte-identical handles, which is what makes a
        pass a capability rather than an account — and it is also why there is no revocation list: the
        handle contains nothing to revoke.
        """
        a = redact.mint_vip_pass(2_000_000_000.0, SECRET)
        b = redact.mint_vip_pass(2_000_000_000.0, SECRET)
        self.assertEqual(a, b, "a pass now carries something per-holder — the no-identity claim is gone")
        data = _unb64(a)
        self.assertEqual(struct.unpack(">q", data[1:9])[0], int(2_000_000_000.0),
                         "the pass body is no longer exactly the expiry instant — something else moved in")
        self.assertEqual(17, len(data),
                         "there is now room in a pass for an identity: re-read `:896-901` before shipping")


def _pad(secret: str, n: int, salt: str) -> bytes:
    """The keystream, reproduced here so the attack tests do not lean on `redact._keystream`."""
    out = b""
    counter = 0
    key = secret.encode("utf-8")
    while len(out) < n:
        out += hashlib.sha256(key + salt.encode("utf-8") + struct.pack(">I", counter)).digest()
        counter += 1
    return out[:n]


class RefusalUniformityTests(unittest.TestCase):
    """A refusal must not be an oracle. Positive controls included, because a guard that always returns
    None is green by accident and tells you nothing about which check fired."""

    def test_a_tampered_handle_and_an_unminted_one_refuse_identically(self):
        good = redact.mint_token(99, SECRET)
        body = _unb64(good)[1:9]
        self.assertIsNone(redact.parse_token(_forge(body), SECRET, signed_only=True))
        self.assertIsNone(redact.parse_token("!!!not-base64!!!", SECRET, signed_only=True))
        self.assertIsNone(redact.parse_token("", SECRET, signed_only=True))
        self.assertIsNone(redact.parse_token(None, SECRET, signed_only=True))
        self.assertEqual(99, redact.parse_token(good, SECRET, signed_only=True),
                         "the positive control broke: refusals may not be the only answer this gives")

    def test_a_pass_minted_for_one_secret_does_not_validate_against_another(self):
        token = redact.mint_vip_pass(2_000_000_000.0, SECRET)
        self.assertIsNone(redact.parse_vip_pass(token, "a-different-secret", now=1_000_000.0))
        self.assertIsNotNone(redact.parse_vip_pass(token, SECRET, now=1_000_000.0))

    def test_an_expired_pass_refuses_and_an_unexpired_one_does_not(self):
        token = redact.mint_vip_pass(1_500_000_000.0, SECRET)
        self.assertIsNone(redact.parse_vip_pass(token, SECRET, now=1_600_000_000.0))
        self.assertEqual(1_500_000_000.0, redact.parse_vip_pass(token, SECRET, now=1_400_000_000.0))


class EnumerationDefenceTests(unittest.TestCase):
    """KD-3, corrected by measurement: the public port already refuses a bare row id.

    The verdict said the danger was `mint_token(id, secret) if secret else str(id)` at four sites. That is
    true and still worth fixing, but reading the mount changed the severity: `viewer` always passes
    `signing_secret()`, which is never empty (see `UnconfiguredSecretTests`), and the *accepting* side is
    gated by `signed_only=not full` (`viewer.py:3683`, `:3949`, `:4011`). So the live defence is this
    flag, and this test is what stops it from being removed quietly.
    """

    def test_the_public_port_refuses_a_plain_integer_entirely(self):
        for bare in (7, "7", "007"):
            self.assertIsNone(redact.parse_token(bare, SECRET, signed_only=True),
                              "a bare row id %r was accepted on the public path — enumeration is back" % (bare,))

    def test_the_loopback_operator_port_still_accepts_a_plain_integer(self):
        """Positive control, and the operator's own curl workflow pinned as behaviour."""
        self.assertEqual(7, redact.parse_token(7, SECRET, signed_only=False))
        self.assertEqual(7, redact.parse_token("7", SECRET, signed_only=False))

    def test_the_bare_id_fallback_sites_are_pinned_and_a_control_proves_the_scan_bites(self):
        """`... if secret else str(...)` remains in the two v2 modules; the mount never hands it a falsy secret.

        Asserting the idiom exists is a *fact pin*, not a safety property: it goes red when a lane removes
        it, which is the good direction. The control asserts the idiom is findable at all, so an empty
        grep can never read as "fixed".
        """
        sites = []
        for name in ("api_v2.py", "catalog_api.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if "else str(" in line:
                    sites.append("%s:%d" % (name, i))
        self.assertGreaterEqual(len(sites), 4,
                                "the bare-id fallback scan found %d sites (%s); four were measured at the "
                                "sha this branch is based on, so a reformat or a rename cannot read as a fix"
                                % (len(sites), ", ".join(sites)))
        self.assertTrue(redact.stream_secret(None), "the mount's secret is falsy: the fallback is now LIVE")


class KeyedKeystreamTests(unittest.TestCase):
    """KD-1, demonstrated rather than asserted. Nothing here changes a format.

    `_keystream(secret, n, salt)` is a function of the secret and a **constant salt per kind** — `"id"` for
    every row handle — so every 8-byte id body is masked with the same pad. One handle whose plaintext is
    known (the attacker's own row, which the API hands them) recovers the pad, and the pad de-masks every
    other id handle this deployment has ever issued.

    That is de-anonymisation, not forgery: the tag is HMAC under the secret, so the same tests assert that
    an attacker who recovers the pad still cannot mint a handle. If KD-1 ever lands a per-token nonce, the
    recovery assertion fails and this docstring tells the reader why that is good news.
    """

    def test_one_known_pair_recovers_the_pad_and_reads_another_row_s_handle(self):
        mine = redact.mint_token(12345, SECRET)          # the attacker's own row
        theirs = redact.mint_token(987654, SECRET)       # a row they are not told about
        pad = bytes(a ^ b for a, b in zip(struct.pack(">q", 12345), _unb64(mine)[1:9]))
        self.assertEqual(_pad(SECRET, 8, "id"), pad,
                         "the pad is no longer a fixed function of (secret, 'id') — KD-1 may be fixed")
        recovered = struct.unpack(">q", bytes(a ^ b for a, b in zip(_unb64(theirs)[1:9], pad)))[0]
        self.assertEqual(987654, recovered)

    def test_the_recovered_pad_does_not_not_authorise_a_forgery(self):
        """The other half, and the reason KD-1 is a privacy defect rather than an authorisation one."""
        mine = redact.mint_token(12345, SECRET)
        pad = bytes(a ^ b for a, b in zip(struct.pack(">q", 12345), _unb64(mine)[1:9]))
        forged_body = bytes(a ^ b for a, b in zip(struct.pack(">q", 987654), pad))
        self.assertIsNone(redact.parse_token(_forge(forged_body), SECRET, signed_only=True))

    def test_handles_are_stable_per_row_across_mints(self):
        """A corollary, stated because it is a tracking property: the same row always yields the same handle."""
        self.assertEqual(redact.mint_token(4242, SECRET), redact.mint_token(4242, SECRET))
        self.assertNotEqual(redact.mint_token(4242, SECRET), redact.mint_token(4243, SECRET))


class UnconfiguredSecretTests(unittest.TestCase):
    """KD-5, new since the verdict was written, and the finding that replaces KD-3's severity.

    `redact.stream_secret` has three answers for "nothing is configured", and two of them are the same
    literal **from the source** (`:957`, `:960`, `:978` — the last one swallows *every* exception, so a
    read-only data directory or a locked database lands here too). Handles minted with a key that is public
    knowledge are opaque to nobody who can read the repository: forging them is four lines using functions
    that already exist in this very module.

    This is pinned as a hole, exactly like `test_clip_bytes_guard.py` pins the 64 KiB ceiling: the test
    PASSES today, so a green run must never be read as "the unconfigured case is safe".
    """

    def test_the_literal_answer_is_in_the_source_and_is_not_a_secret(self):
        self.assertEqual(UNCONFIGURED, redact.stream_secret(None))
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "no-such-catalog.db"
            self.assertEqual(UNCONFIGURED, redact.stream_secret(missing))
        text = (ROOT / "redact.py").read_text(encoding="utf-8")
        self.assertEqual(3, text.count('"%s"' % UNCONFIGURED),
                         "the number of unconfigured fallbacks moved — re-read this section")

    def test_an_unconfigured_secret_still_mints_and_the_public_parser_accepts_it(self):
        """The failure mode in one line: nothing refuses, nothing logs, and a stranger can mint a handle.

        The attacker's handle is built here from the published constant only — no secret, no server, no
        database — and then fed to the parser with the secret the server itself resolved. If that
        validates, "opaque" is a word about the reader's attention, not about the wire.
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            server_secret = redact.stream_secret(None)
            self.assertEqual(UNCONFIGURED, server_secret,
                             "the unconfigured answer is no longer the source literal — KD-5 may be fixed, "
                             "then this test must be rewritten to demand a refusal instead of a match")
            forged_by_anyone = redact.mint_token(777, UNCONFIGURED)
            self.assertEqual(777, redact.parse_token(forged_by_anyone, server_secret, signed_only=True),
                             "a handle minted from the published constant is not accepted by the server — "
                             "if this is now a refusal, KD-5 is closed and the verdict needs updating")

    def test_the_configured_cases_are_the_ones_that_work(self):
        """Positive control for the two tests above: env wins, and a real database gets a random secret."""
        with mock.patch.dict(os.environ, {"RADD_STREAM_SECRET": "from-the-deployment"}):
            self.assertEqual("from-the-deployment", redact.stream_secret(None))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "catalog.db"
            sqlite3.connect(path).close()
            first = redact.stream_secret(path)
            self.assertNotEqual(UNCONFIGURED, first)
            self.assertGreaterEqual(len(first), 32, "the generated secret is not a 256-bit token")
            self.assertEqual(first, redact.stream_secret(path),
                             "the secret is not stable across calls — restarts would invalidate every handle")

    def test_a_database_that_cannot_be_written_falls_back_to_the_public_literal(self):
        """`:976-978` catches Exception, so an unwritable catalog is indistinguishable from no catalog.

        Forced with a directory in place of a file: `sqlite3.connect` on a directory raises `OperationalError`
        and the `except Exception` answers with the constant. No chmod, no real paths.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(UNCONFIGURED, redact.stream_secret(pathlib.Path(tmp)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
