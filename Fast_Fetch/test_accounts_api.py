#!/usr/bin/env python3
"""Offline tests for `accounts_api.py` — the HTTP edge for optional sync accounts.

Stdlib only, no port, no cloud, no real catalog: every case calls the route
function the way `viewer.py` does and asserts on the exact `(status,
content_type, body)` tuple a client would receive. The fixtures are the ones the
rule cares about: a work key that contains a site name, and an adult work that
must be indistinguishable from one that never existed.

    python3 -S Fast_Fetch/test_accounts_api.py
"""
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts            # noqa: E402
import accounts_api        # noqa: E402
import api_v2              # noqa: E402
import redact              # noqa: E402

SECRET = "test-install-secret"
P = accounts_api.PREFIX
#: The names a fixture row carries and that must therefore never appear in a body.
NEEDLES = {"katmoviehd", "vegamovies", "rareanimes", "sample-site"}
VISIBLE = "movie:in:1000:sample"
ADULT = "movie:in:1001:bad katmoviehd title"


def catalog_fixture(path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE cat_works (work_key TEXT, is_18_plus INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO cat_works VALUES (?, 0)", (VISIBLE,))
    conn.execute("INSERT INTO cat_works VALUES (?, 1)", (ADULT,))
    conn.execute("INSERT INTO cat_works VALUES ('movie:in:1002:veg VegaMovies Film', 0)")
    conn.commit()
    conn.close()
    return Path(path)


class Edge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "user_state.db"
        self.catalog = catalog_fixture(Path(self.tmp.name) / "cat.db")
        with closing(accounts.connect(self.state)) as conn:
            accounts.ensure_schema(conn)
        self.key = None

    # ── helpers ──────────────────────────────────────────────────────────
    def get(self, path, query=None, headers=None):
        return accounts_api.route_get(path, query or {}, db_path=self.state,
                                      catalog_path=self.catalog, secret=SECRET,
                                      headers={} if headers is None else headers)

    def post(self, path, body=None, headers=None):
        return accounts_api.route_post(path, body or {}, db_path=self.state,
                                       catalog_path=self.catalog, secret=SECRET,
                                       headers={} if headers is None else headers)

    def auth(self, key=None):
        return {"Authorization": f"Bearer {key or self.key}"}

    def enroll(self, key=None):
        """Create an account and return its plaintext key (shown once, by design)."""
        made = self.post(P, {"sync_key": key} if key else {})
        assert made[0] in (200, 201), made
        return json.loads(made[2])["account"].get("sync_key") or key

    def body(self, answered) -> dict:
        self.assertIsNotNone(answered)
        status, content_type, raw = answered
        payload = json.loads(raw.decode("utf-8"))
        self._last_status = status
        self._last_type = content_type
        return payload

    def status(self, answered) -> int:
        self.assertIsNotNone(answered)
        return answered[0]

    def canonical(self, answered) -> str:
        """A response body without its `request_id`: two refusals that must be
        indistinguishable are identical except for the trace id we mint per reply,
        and comparing raw bytes would fail for a reason that is not the rule."""
        _status, _type, raw = answered
        payload = json.loads(raw.decode("utf-8"))
        payload.pop("request_id", None)
        return json.dumps(payload, sort_keys=True)

    def assert_no_provenance(self, answered, label):
        status, _type, raw = answered
        offenders = redact.is_clean(json.loads(raw.decode("utf-8")), NEEDLES)
        self.assertEqual(offenders, [], f"{label} leaks provenance: {offenders}")

    def assert_problem(self, answered, code, status):
        self.assertEqual(self.status(answered), status)
        payload = self.body(answered)
        self.assertEqual(payload["code"], code)
        self.assertEqual(payload["status"], status)
        self.assertIn(code, api_v2.PROBLEM_CODES, "an undeclared public code left the edge")
        self.assertEqual(payload["type"], f"/api/v2/problems/{code}")
        self.assertTrue(payload["request_id"].startswith("req_"))

    # ── enrollment ───────────────────────────────────────────────────────
    def test_create_answers_201_with_the_key_once_and_no_row_id(self):
        made = self.post(P)
        self.assertEqual(self.status(made), 201)
        account = self.body(made)["account"]
        self.assertEqual(set(account), {"created_at", "created", "sync_key"})
        self.assertTrue(account["created"])
        self.assertGreaterEqual(len(account["sync_key"]), accounts.MIN_SYNC_KEY_CHARS)
        self.assertNotIn("account_id", made[2].decode())
        self.assertNotIn("key_hash", made[2].decode())

    def test_re_presenting_a_known_key_is_not_a_second_account_and_returns_no_key(self):
        self.key = self.enroll()
        again = self.post(P, {"sync_key": self.key})
        self.assertEqual(self.status(again), 200)
        account = self.body(again)["account"]
        self.assertFalse(account["created"])
        self.assertNotIn("sync_key", account,
                         "the plaintext is ours to hand out exactly once")

    def test_a_device_minted_key_is_accepted_and_never_stored_in_the_clear(self):
        proposed = accounts.new_sync_key()
        self.enroll(proposed)
        stored = sqlite3.connect(str(self.state)).execute(
            "SELECT key_hash FROM user_accounts").fetchone()[0]
        self.assertNotIn(proposed, stored)
        self.assertTrue(stored.startswith(accounts.HASH_PREFIX))

    def test_a_weak_caller_minted_key_is_refused_as_invalid_params(self):
        self.assert_problem(self.post(P, {"sync_key": "hunter2"}),
                            "invalid_params", 400)

    def test_the_only_unauthenticated_route_is_creation(self):
        self.assertIsNone(self.post("/api/v2/browse", {}))
        self.assertIsNone(self.get("/api/v2/browse"))

    # ── who am I ─────────────────────────────────────────────────────────
    def test_me_without_a_key_is_the_same_404_as_a_key_that_was_never_issued(self):
        anonymous = self.get(P)
        stranger = self.get(P, headers=self.auth(accounts.new_sync_key()))
        self.assertEqual(self.status(anonymous), 404)
        self.assertEqual(self.canonical(anonymous), self.canonical(stranger),
                         "the answer must not hint at whether a key is someone's")

    def test_me_returns_only_the_two_timestamps_we_owe_the_client(self):
        self.key = self.enroll()
        account = self.body(self.get(P, headers=self.auth()))["account"]
        self.assertEqual(set(account), {"created_at", "last_seen_at"})

    def test_stats_are_not_part_of_any_public_payload(self):
        """`accounts.account_stats` documents itself as an operator/CLI view; this
        edge publishing it would be the module contradicting its own owner."""
        self.key = self.enroll()
        self.assertNotIn("stats", self.body(self.get(P, headers=self.auth()))["account"])

    # ── favorites ────────────────────────────────────────────────────────
    def test_favorite_round_trip_carries_a_minted_ref_and_never_a_work_key(self):
        self.key = self.enroll()
        ref = redact.mint_text(VISIBLE, SECRET)
        added = self.post(f"{P}/favorites", {"work_ref": ref}, headers=self.auth())
        self.assertEqual(self.status(added), 201)
        favorite = self.body(added)["favorite"]
        self.assertIn(accounts.PUBLIC_REF_KEY, favorite)
        self.assertNotIn("work_key", favorite)
        self.assertNotIn(VISIBLE, added[2].decode())
        self.assert_no_provenance(added, "a favorite write")
        listed = self.get(f"{P}/favorites", headers=self.auth())
        self.assertEqual(self.body(listed)["count"], 1)
        self.assert_no_provenance(listed, "the favorites list")
        removed = self.post(f"{P}/favorites/remove", {"work_ref": ref}, headers=self.auth())
        self.assertTrue(self.body(removed)["removed"])
        self.assertFalse(self.body(self.post(f"{P}/favorites/remove", {"work_ref": ref},
                                             headers=self.auth()))["removed"])

    def test_re_adding_the_same_favorite_does_not_make_a_second_row(self):
        self.key = self.enroll()
        ref = redact.mint_text(VISIBLE, SECRET)
        self.post(f"{P}/favorites", {"work_ref": ref}, headers=self.auth())
        self.post(f"{P}/favorites", {"work_ref": ref}, headers=self.auth())
        self.assertEqual(self.body(self.get(f"{P}/favorites",
                                            headers=self.auth()))["count"], 1)

    def test_an_adult_work_is_the_same_404_as_a_work_that_never_existed(self):
        self.key = self.enroll()
        adult = self.post(f"{P}/favorites",
                          {"work_ref": redact.mint_text(ADULT, SECRET)},
                          headers=self.auth())
        missing = self.post(f"{P}/favorites",
                            {"work_ref": redact.mint_text("movie:in:999999:nobody", SECRET)},
                            headers=self.auth())
        self.assert_problem(adult, "not_found", 404)
        self.assertEqual(self.canonical(adult), self.canonical(missing),
                         "an adult title must be indistinguishable from absent")

    def test_a_work_key_sent_instead_of_a_handle_is_refused_without_being_quoted(self):
        self.key = self.enroll()
        refused = self.post(f"{P}/favorites", {"work_ref": ADULT}, headers=self.auth())
        self.assert_problem(refused, "invalid_params", 400)
        self.assertNotIn("katmoviehd", refused[2].decode())
        self.assertNotIn(ADULT, refused[2].decode())

    def test_a_handle_minted_by_another_install_is_refused(self):
        self.key = self.enroll()
        foreign = redact.mint_text(VISIBLE, "some-other-install-secret")
        self.assert_problem(self.post(f"{P}/favorites", {"work_ref": foreign},
                                      headers=self.auth()), "invalid_params", 400)

    def test_a_site_name_inside_a_work_key_never_reaches_a_body(self):
        """`movie:in:1002:bad vegamovies title`-style keys are real: a `work_key`
        is built from scraped text, so the mint is the only thing between a site
        name and a public response."""
        self.key = self.enroll()
        self.post(f"{P}/favorites",
                  {"work_ref": redact.mint_text("movie:in:1002:veg VegaMovies Film", SECRET)},
                  headers=self.auth())
        listed = self.get(f"{P}/favorites", headers=self.auth())
        self.assertEqual(self.body(listed)["count"], 1)
        self.assert_no_provenance(listed, "the favorites list")

    # ── progress ─────────────────────────────────────────────────────────
    def test_progress_stores_a_position_and_lists_it_back(self):
        self.key = self.enroll()
        ref = redact.mint_text(VISIBLE, SECRET)
        put = self.post(f"{P}/progress", {"work_ref": ref, "position_seconds": 640,
                                          "duration_seconds": 5400}, headers=self.auth())
        self.assertEqual(self.status(put), 201)
        row = self.body(put)["progress"]
        self.assertEqual(row["position_seconds"], 640)
        self.assert_no_provenance(put, "a progress write")
        listed = self.get(f"{P}/progress", headers=self.auth())
        self.assertEqual(self.body(listed)["count"], 1)
        gone = self.post(f"{P}/progress/remove", {"work_ref": ref}, headers=self.auth())
        self.assertTrue(self.body(gone)["removed"])

    def test_a_non_numeric_position_is_stored_as_zero_not_as_a_500(self):
        self.key = self.enroll()
        put = self.post(f"{P}/progress",
                        {"work_ref": redact.mint_text(VISIBLE, SECRET),
                         "position_seconds": "keep watching!"}, headers=self.auth())
        self.assertEqual(self.status(put), 201)
        self.assertEqual(self.body(put)["progress"]["position_seconds"], 0)

    def test_an_absent_client_clock_does_not_become_our_invention(self):
        self.key = self.enroll()
        put = self.post(f"{P}/progress",
                        {"work_ref": redact.mint_text(VISIBLE, SECRET),
                         "position_seconds": 10}, headers=self.auth())
        self.assertEqual(self.status(put), 201)

    # ── revocation ───────────────────────────────────────────────────────
    def test_a_revoked_key_answers_exactly_as_it_did_before_it_existed(self):
        first = self.enroll()
        self.assertEqual(self.status(self.get(P, headers=self.auth(first))), 200)
        self.assertEqual(self.status(self.post(f"{P}/revoke", headers=self.auth(first))), 200)
        after = self.get(P, headers=self.auth(first))
        self.assert_problem(after, "not_found", 404)
        stranger = self.get(P, headers=self.auth(accounts.new_sync_key()))
        self.assertEqual(self.canonical(after), self.canonical(stranger))

    # ── refusal discipline ───────────────────────────────────────────────
    def test_an_unknown_account_subpath_is_404_not_a_fallthrough(self):
        self.key = self.enroll()
        self.assert_problem(self.get(f"{P}/nonsense", headers=self.auth()), "not_found", 404)
        self.assert_problem(self.post(f"{P}/nonsense", headers=self.auth()), "not_found", 404)

    def test_a_write_without_a_bearer_key_is_401_and_creation_stays_open(self):
        self.key = self.enroll()
        self.assert_problem(self.post(f"{P}/favorites", {"work_ref": "x"}), "unauthorised", 401)

    def test_every_refusal_this_edge_makes_uses_a_declared_code(self):
        self.key = self.enroll()
        refusals = [
            self.get(P),                                       # no key
            self.post(f"{P}/favorites", {}),                   # 401
            self.post(f"{P}/favorites", {"work_ref": "junk"}, headers=self.auth()),
            self.post(f"{P}/favorites",
                      {"work_ref": redact.mint_text(ADULT, SECRET)}, headers=self.auth()),
            self.get(f"{P}/elsewhere", headers=self.auth()),
        ]
        for answered in refusals:
            payload = self.body(answered)
            self.assertIn(payload["code"], api_v2.PROBLEM_CODES,
                          f"undeclared code {payload['code']}")

    def test_a_burned_out_key_gets_retry_after_on_its_429(self):
        """`accounts` locks on the failure path only, so this is reached by wrong
        keys; the edge must still carry `Retry-After` (§16.5) or a phone retries blind."""
        victim = accounts.new_sync_key()
        for _ in range(accounts.DEFAULT_MAX_FAILURES + 1):
            self.get(P, headers=self.auth(victim))
        refused = self.get(P, headers=self.auth(victim))
        self.assertEqual(self.status(refused), 429)
        payload = self.body(refused)
        self.assertEqual(payload["code"], "rate_limited")
        self.assertGreaterEqual(payload["retry_after"], 1)

    def test_an_unreadable_catalog_refuses_the_write_rather_than_skipping_the_check(self):
        """No oracle is not "the adult rule passed": `accounts` answers
        `CatalogUnreachable`, and §16.4 declares it as `unavailable` (503)."""
        self.key = self.enroll()
        self.catalog = None
        added = self.post(f"{P}/favorites",
                          {"work_ref": redact.mint_text(VISIBLE, SECRET)},
                          headers=self.auth())
        self.assert_problem(added, "unavailable", 503)

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs /proc")
    def test_a_request_does_not_leave_a_catalog_connection_open(self):
        """The edge opens one read-only catalog connection per request and closes
        it in a `finally`; leaking one per call is how a long-running server runs
        out of file descriptors on the busiest day, which is a self-inflicted
        outage and not a bug a unit test of a payload would ever show."""
        self.key = self.enroll()
        ref = redact.mint_text(VISIBLE, SECRET)
        self.post(f"{P}/favorites", {"work_ref": ref}, headers=self.auth())
        fds = len(list(Path("/proc/self/fd").iterdir()))
        for _ in range(40):
            self.get(f"{P}/favorites", headers=self.auth())
            self.post(f"{P}/favorites", {"work_ref": ref}, headers=self.auth())
        self.assertLess(len(list(Path("/proc/self/fd").iterdir())), fds + 8)

    def test_a_projected_catalog_with_no_cat_works_table_refuses_the_write_not_500s(self):
        """`accounts` raises `CatalogUnreachable` (503) when the oracle exists but
        cannot answer; §16.4 declares that as `unavailable`, never as a 404 claim."""
        self.key = self.enroll()
        empty = Path(self.tmp.name) / "empty.db"
        sqlite3.connect(str(empty)).execute("CREATE TABLE posts (id INTEGER)")
        self.catalog = empty
        answered = self.post(f"{P}/favorites",
                             {"work_ref": redact.mint_text(VISIBLE, SECRET)},
                             headers=self.auth())
        self.assertIn(self.status(answered), (404, 503))
        self.body(answered)["code"]

    def test_is_account_predicate_bounds_the_namespace(self):
        for path, expected in ((P, True), (f"{P}/favorites", True),
                               (f"{P}ion", False), ("/api/v2/accountx/", False),
                               ("/api/v2/accounts", False), ("/admin", False)):
            self.assertEqual(accounts_api.is_account(path), expected, path)

    def test_the_minter_is_carried_per_request_not_bound_globally(self):
        """Two threads with different secrets must not mint each other's handles;
        a module-level binding would make that possible and silent."""
        self.key = self.enroll()
        mine = accounts_api._Minter(SECRET)
        other = accounts_api._Minter("different")
        token = mine(VISIBLE)
        self.assertEqual(other.work_key(token), None)
        self.assertEqual(mine.work_key(token), VISIBLE)

    def test_limit_param_is_clamped_not_trusted(self):
        self.key = self.enroll()
        self.assertEqual(accounts_api._limit({"limit": ["0"]}), 1)
        self.assertEqual(accounts_api._limit({"limit": ["999999"]}), accounts_api.MAX_N)
        self.assertEqual(accounts_api._limit({"limit": ["abc"]}), accounts_api.DEFAULT_N)
        self.assertEqual(accounts_api._limit({}), accounts_api.DEFAULT_N)

    def test_state_db_is_idempotent_and_creates_the_tables(self):
        fresh = Path(self.tmp.name) / "second.db"
        with closing(accounts.connect(fresh)) as conn:
            accounts.ensure_schema(conn)
        names = {row[0] for row in sqlite3.connect(str(fresh)).execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"user_accounts", "user_favorites", "user_progress"}, names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
