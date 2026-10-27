#!/usr/bin/env python3
"""Real scenario tests for the optional sync-key account (`Fast_Fetch/accounts.py`).

Offline and hermetic in the `test_catalog_v2.py` style: a temp-file database per test,
`setUp`/`tearDown`, no network, no live catalog, no shared state. The catalog the adult
and existence rules are checked against is a fixture — either a `dict`-backed callable or
a throw-away sqlite file with a `cat_works` table — because the rule under test is this
module's behaviour, not the projector's.

Nothing is mocked inside `accounts.py`. Where a case would pass for the wrong reason it
says so: the two-device test asserts on the ROWS, not on a call count; the
stale-progress test asserts the stored numbers, not a flag; the plaintext test reads the
database file's bytes.

Run: python3 -S Fast_Fetch/test_accounts.py
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import accounts
import redact

#: Every test runs on a fixed instant instead of the wall clock, so the attempt
#: window, the idle cutoff and the progress tie-break are all decided by the case
#: that is being asserted and never by how long the box took to get here.
T0 = 1_792_900_000.0

VISIBLE = ("movie:dune:2021", "series:the-office:2005", "series:packed-season:2020")
ADULT = ("movie:flagged-film:2019",)
ABSENT = ("movie:never-indexed:1999",)


def fake_catalog(visible=VISIBLE, adult=ADULT):
    """The `callable(work_key) -> bool` form of the visibility oracle: an adult work
    and an absent work both answer False, which is the whole of §13 as this module
    sees it."""
    allowed = set(visible)
    banned = set(adult)

    def check(work_key):
        return str(work_key) in allowed and str(work_key) not in banned
    return check


def make_catalog_db(path, visible=VISIBLE, adult=ADULT):
    """A real `cat_works` fixture, for the cases that exercise the
    connection/path form of the oracle rather than the callable form."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE cat_works (work_key TEXT UNIQUE NOT NULL,"
                 " is_18_plus INTEGER NOT NULL DEFAULT 0)")
    conn.executemany("INSERT INTO cat_works(work_key, is_18_plus) VALUES(?, 0)",
                     [(key,) for key in visible])
    conn.executemany("INSERT INTO cat_works(work_key, is_18_plus) VALUES(?, 1)",
                     [(key,) for key in adult])
    conn.commit()
    conn.close()


class StateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "user_state.db"
        self.conn = accounts.connect(self.db_path)
        self.addCleanup(self.conn.close)
        # A private limiter per test: the module-level `accounts.attempt_tracker`
        # is process-wide and its in-process windows would otherwise leak from one
        # test into the next, which is exactly the kind of flake that hides a real
        # lock-out bug.
        self.tracker = accounts.AttemptTracker(max_failures=3, window_seconds=60.0,
                                               lock_seconds=30.0)
        self.catalog = fake_catalog()

    def new_account(self, now=T0):
        return accounts.create_account(self.conn, now=now)

    def tearDown(self):
        accounts.attempt_tracker.reset()


# ── accounts and keys ─────────────────────────────────────────────────────────


class CreateAccountTests(StateTestCase):
    def test_schema_is_installed_and_idempotent(self):
        for table in ("user_accounts", "user_favorites", "user_progress",
                      "sync_key_attempts", "user_state_meta"):
            self.assertTrue(self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,)).fetchone(), f"{table} missing")
        first = accounts.ensure_schema(self.conn)
        self.assertEqual(first["added_columns"], [])      # nothing to add twice
        self.assertEqual(accounts.schema_version(self.conn), accounts.SCHEMA_VERSION)

    def test_wal_and_busy_timeout_are_set(self):
        """WAL, because this table is read on every browse request and written only
        when someone hearts a title; busy_timeout, because the projection runs
        beside us."""
        self.assertEqual(str(self.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
                         "wal")
        self.assertGreater(int(self.conn.execute("PRAGMA busy_timeout").fetchone()[0]), 0)

    def test_created_account_returns_the_plaintext_key_once_and_stores_no_plaintext(self):
        account = self.new_account()
        self.assertTrue(account["created"])
        key = account["sync_key"]
        self.assertEqual(len(key), 16)                    # secrets.token_urlsafe(12)
        self.assertNotIn("=", key)                        # urlsafe, header-friendly
        stored = self.conn.execute("SELECT key_hash FROM user_accounts").fetchone()[0]
        self.assertEqual(stored, "sha256:" + hashlib.sha256(key.encode()).hexdigest())
        self.assertNotIn(key, stored)
        self.assertNotIn("password", self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='user_accounts'").fetchone()[0])

    def test_plaintext_key_never_appears_in_the_database_file(self):
        """The assertion people skip: hash-on-read is only a claim if the bytes say
        so. The file is checkpointed first, so the WAL cannot be holding the answer."""
        key = self.new_account()["sync_key"]
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.commit()
        raw = self.db_path.read_bytes()
        for wal in (Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            if wal.exists():
                raw += wal.read_bytes()
        self.assertNotIn(key.encode("ascii"), raw)
        self.assertNotIn(key.encode("utf-16-be"), raw)
        # and the hashed form is in there, i.e. we are looking at the right file
        self.assertIn(("sha256:" + hashlib.sha256(key.encode()).hexdigest()).encode(), raw)

    def test_minting_twice_gives_two_independent_accounts(self):
        a, b = self.new_account(), self.new_account(now=T0 + 1)
        self.assertNotEqual(a["sync_key"], b["sync_key"])
        self.assertNotEqual(a["account_id"], b["account_id"])
        self.assertEqual(len({a["sync_key"], b["sync_key"]}), 2)

    def test_client_minted_key_is_accepted_and_is_idempotent_on_replay(self):
        key = accounts.new_sync_key()
        first = accounts.create_account(self.conn, key, now=T0)
        self.assertTrue(first["created"])
        replay = accounts.create_account(self.conn, key, now=T0 + 5)
        self.assertFalse(replay["created"])
        self.assertIsNone(replay["sync_key"])             # not ours to hand back twice
        self.assertEqual(replay["account_id"], first["account_id"])
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_accounts").fetchone()[0])

    def test_weak_or_untransmissible_caller_key_is_refused(self):
        for bad in ("short", "x" * 300, "has space" + "x" * 20, "tab\tx" * 4, 1234,
                    ["not", "a", "string"], "quote\"inside" + "x" * 20,
                    "back\\slash" + "x" * 20, "\x01" + "x" * 30):
            with self.assertRaises(accounts.WeakSyncKey, msg=repr(bad)):
                accounts.create_account(self.conn, bad, now=T0)
        self.assertEqual(0, self.conn.execute(
            "SELECT COUNT(*) FROM user_accounts").fetchone()[0])
        # `None` is the one non-string a caller may pass: it means "mint one here",
        # not "use this key", so it must not be refused as weak.
        self.assertTrue(accounts.create_account(self.conn, None, now=T0)["created"])

    def test_a_low_entropy_key_is_not_stored_even_if_it_was_supplied(self):
        """A refused key must not leave even its hash behind: a guessable string an
        attacker typed in, persisted as an account, is a target we created."""
        with self.assertRaises(accounts.WeakSyncKey):
            accounts.create_account(self.conn, "password", now=T0)
        self.assertEqual([], self.conn.execute("SELECT key_hash FROM user_accounts").
                         fetchall())


class ResolveAccountTests(StateTestCase):
    def test_resolve_returns_the_account_and_never_a_hash(self):
        account = self.new_account()
        row = accounts.resolve_account(self.conn, account["sync_key"], now=T0,
                                      tracker=self.tracker)
        self.assertEqual(row["account_id"], account["account_id"])
        self.assertNotIn("key_hash", row)
        self.assertNotIn("sync_key", row)

    def test_wrong_revoked_and_never_issued_keys_are_the_same_answer(self):
        """Indistinguishable, and provably so: the same class, the same code, the
        same status, the same message — for a key that was guessed, a key that was
        revoked, and a key nobody ever had."""
        live = self.new_account()
        revoked = self.new_account(now=T0 + 1)
        accounts.revoke_account(self.conn, revoked["sync_key"], now=T0 + 2,
                                tracker=self.tracker)
        answers = []
        for key in (live["sync_key"][:-2] + "zz", revoked["sync_key"],
                    accounts.new_sync_key(), "", None, 42, "x" * 43):
            try:
                accounts.authenticate(self.conn, key, now=T0 + 3, tracker=self.tracker)
                self.fail(f"{key!r} resolved")
            except accounts.UnknownAccount as exc:
                answers.append((type(exc).__name__, exc.code, exc.status, exc.detail))
        self.assertEqual(1, len(set(answers)), f"the three answers differ: {answers}")
        self.assertEqual(("UnknownAccount", "not_found", 404, "not found"), answers[0])

    def test_revoke_makes_the_hash_unreachable_in_form_as_well_as_in_law(self):
        account = self.new_account()
        key = account["sync_key"]
        wanted = accounts._hash_key(key)
        accounts.revoke_account(self.conn, key, now=T0 + 1, tracker=self.tracker)
        stored = self.conn.execute("SELECT key_hash, revoked_at FROM user_accounts"
                                   " WHERE id = ?", (account["account_id"],)).fetchone()
        self.assertTrue(stored[0].startswith(accounts.TOMBSTONE_PREFIX))
        self.assertNotEqual(wanted, stored[0])
        self.assertIsNotNone(stored[1])
        # a tombstone can be produced by no presented key, so the miss is structural
        self.assertFalse(accounts._verify_hash(stored[0], wanted))
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM user_accounts WHERE key_hash = ?", (wanted,)).fetchone())

    def test_revoked_library_is_unreachable_and_not_deleted_auditors_can_still_read(self):
        account = self.new_account()
        key = account["sync_key"]
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              now=T0, tracker=self.tracker)
        accounts.revoke_account(self.conn, key, now=T0 + 1, tracker=self.tracker)
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_favorites").fetchone()[0])   # not yet collected
        with self.assertRaises(accounts.UnknownAccount):
            accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                    now=T0 + 2, tracker=self.tracker)

    def test_double_revoke_answers_like_an_unknown_key(self):
        account = self.new_account()
        accounts.revoke_account(self.conn, account["sync_key"], now=T0,
                                 tracker=self.tracker)
        with self.assertRaises(accounts.UnknownAccount):
            accounts.revoke_account(self.conn, account["sync_key"], now=T0 + 1,
                                    tracker=self.tracker)

    def test_touching_an_account_bumps_last_seen_at_most_once_per_interval(self):
        """The bump is throttled: `last_seen_at` decides pruning, not presence, so
        writing it on every page of the catalog would turn every browse into an
        UPDATE on this file."""
        account = self.new_account()
        key = account["sync_key"]
        interval = accounts.LAST_SEEN_WRITE_INTERVAL
        # inside the throttle window: resolved fine, clock deliberately left alone
        accounts.authenticate(self.conn, key, now=T0 + 5, tracker=self.tracker)
        seen = self.conn.execute("SELECT last_seen_at FROM user_accounts").fetchone()[0]
        self.assertAlmostEqual(T0, seen)
        accounts.authenticate(self.conn, key, now=T0 + interval - 1, tracker=self.tracker)
        self.assertEqual(seen, self.conn.execute(
            "SELECT last_seen_at FROM user_accounts").fetchone()[0])
        # past the throttle window the clock moves, and it moves to the request's
        # instant — which is exactly what keeps a used account alive through a prune
        accounts.authenticate(self.conn, key, now=T0 + interval, tracker=self.tracker)
        bumped = self.conn.execute("SELECT last_seen_at FROM user_accounts").fetchone()[0]
        self.assertAlmostEqual(T0 + interval, bumped)
        accounts.authenticate(self.conn, key, now=T0 + 2 * interval, tracker=self.tracker)
        self.assertAlmostEqual(T0 + 2 * interval, self.conn.execute(
            "SELECT last_seen_at FROM user_accounts").fetchone()[0])


# ── two devices, one library ─────────────────────────────────────────────────


class TwoDeviceSyncTests(StateTestCase):
    def test_two_devices_with_the_same_key_see_one_library(self):
        """The entire point of the feature, asserted on rows: device A writes, device
        B (a different connection, a different thread in the real host) reads the same
        two favorites and the same progress, and then device B's write is visible to A.
        """
        key = self.new_account()["sync_key"]
        device_a = accounts.connect(self.db_path)
        self.addCleanup(device_a.close)
        device_b = accounts.connect(self.db_path)
        self.addCleanup(device_b.close)

        accounts.put_favorite(device_a, key, "movie:dune:2021", catalog=self.catalog,
                              added_at=T0, tracker=self.tracker, now=T0)
        accounts.put_favorite(device_b, key, "series:the-office:2005", catalog=self.catalog,
                              added_at=T0 + 1, tracker=self.tracker, now=T0 + 1)
        accounts.put_progress(device_a, key, "series:the-office:2005", catalog=self.catalog,
                              season_number=2, episode_number=1, position_seconds=300,
                              duration_seconds=1200, client_updated_at=T0 + 2,
                              tracker=self.tracker, now=T0 + 2)

        for device in (device_a, device_b):
            titles = sorted(row["work_key"] for row in
                            accounts.list_favorites(device, key, catalog=self.catalog,
                                                    tracker=self.tracker, now=T0 + 3))
            self.assertEqual(["movie:dune:2021", "series:the-office:2005"], titles)
        progress = accounts.list_progress(device_b, key, catalog=self.catalog,
                                         tracker=self.tracker, now=T0 + 3)
        self.assertEqual(1, len(progress))
        self.assertEqual(300.0, progress[0]["position_seconds"])
        self.assertEqual((2, 1), (progress[0]["season_number"],
                                  progress[0]["episode_number"]))
        # one account row, not one per device
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_accounts").fetchone()[0])
        # device B's next write lands on device A's row, and A sees it
        accounts.put_progress(device_b, key, "series:the-office:2005",
                              catalog=self.catalog, season_number=2, episode_number=1,
                              position_seconds=600, duration_seconds=1200,
                              client_updated_at=T0 + 4, tracker=self.tracker, now=T0 + 4)
        self.assertEqual(600.0, accounts.get_progress(
            device_a, key, "series:the-office:2005", season_number=2, episode_number=1,
            tracker=self.tracker, now=T0 + 5)["position_seconds"])

    def test_a_second_device_can_present_the_key_as_a_path_too(self):
        """Every public function takes a connection OR a path — the HTTP host keeps a
        connection, a one-shot route takes the path, and both must agree."""
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.db_path, key, "movie:dune:2021", catalog=self.catalog,
                              added_at=T0, tracker=self.tracker, now=T0)
        self.assertEqual(1, len(accounts.list_favorites(self.db_path, key,
                                                        catalog=self.catalog,
                                                        tracker=self.tracker, now=T0 + 1)))
        self.assertEqual(1, len(accounts.list_favorites(self.conn, key,
                                                        catalog=self.catalog,
                                                        tracker=self.tracker, now=T0 + 1)))


# ── favorites ────────────────────────────────────────────────────────────────


class FavoriteTests(StateTestCase):
    def test_re_add_is_idempotent_and_keeps_one_row_per_scope(self):
        """The NULL-scope defect class: with NULL season/episode in a UNIQUE index a
        re-add would file a second row, because SQLite calls NULL DISTINCT from NULL.
        """
        key = self.new_account()["sync_key"]
        first = accounts.put_favorite(self.conn, key, "movie:dune:2021",
                                     catalog=self.catalog, added_at=T0,
                                     tracker=self.tracker, now=T0 + 9)
        again = accounts.put_favorite(self.conn, key, "movie:dune:2021",
                                     catalog=self.catalog, added_at=T0 + 500,
                                     tracker=self.tracker, now=T0 + 500)
        rows = accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                       tracker=self.tracker, now=T0 + 501)
        self.assertEqual(1, len(rows))
        self.assertEqual(first["added_at"], again["added_at"])
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_favorites").fetchone()[0])

    def test_the_earliest_added_at_claim_wins_in_both_directions(self):
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              added_at=T0 + 100, tracker=self.tracker, now=T0 + 100)
        behind = accounts.put_favorite(self.conn, key, "movie:dune:2021",
                                      catalog=self.catalog, added_at=T0 + 10,
                                      tracker=self.tracker, now=T0 + 200)
        self.assertEqual(T0 + 10, behind["added_at"])
        ahead = accounts.put_favorite(self.conn, key, "movie:dune:2021",
                                     catalog=self.catalog, added_at=T0 + 900,
                                     tracker=self.tracker, now=T0 + 900)
        self.assertEqual(T0 + 10, ahead["added_at"])

    def test_season_and_episode_scope_are_distinct_favorites(self):
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.conn, key, "series:the-office:2005",
                              catalog=self.catalog, season_number=2, episode_number=1,
                              tracker=self.tracker, now=T0)
        accounts.put_favorite(self.conn, key, "series:the-office:2005",
                              catalog=self.catalog, season_number=2, episode_number=2,
                              tracker=self.tracker, now=T0 + 1)
        whole = accounts.put_favorite(self.conn, key, "series:the-office:2005",
                                      catalog=self.catalog, tracker=self.tracker,
                                      now=T0 + 2)
        self.assertEqual((0, 0), (whole["season_number"], whole["episode_number"]))
        rows = accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                       tracker=self.tracker, now=T0 + 3)
        self.assertEqual(3, len(rows))
        self.assertEqual({(0, 0), (2, 1), (2, 2)},
                         {(r["season_number"], r["episode_number"]) for r in rows})

    def test_delete_favorite_reports_whether_a_row_actually_went(self):
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              tracker=self.tracker, now=T0)
        self.assertTrue(accounts.delete_favorite(self.conn, key, "movie:dune:2021",
                                                 catalog=self.catalog,
                                                 tracker=self.tracker, now=T0 + 1))
        self.assertFalse(accounts.delete_favorite(self.conn, key, "movie:dune:2021",
                                                  catalog=self.catalog,
                                                  tracker=self.tracker, now=T0 + 2))
        self.assertEqual([], accounts.list_favorites(self.conn, key,
                                                     catalog=self.catalog,
                                                     tracker=self.tracker, now=T0 + 3))

    def test_a_favorite_is_never_stored_as_a_title_or_a_url(self):
        """Provenance, structurally: there is no column to put it in, and no caller
        string other than a validated work key is accepted."""
        key = self.new_account()["sync_key"]
        schema = self.conn.execute("SELECT sql FROM sqlite_master"
                                   " WHERE name='user_favorites'").fetchone()[0]
        for banned in ("title", "url", "source_site", "site", "service", "note"):
            self.assertNotIn(banned, schema.lower(), f"{banned} column in user_favorites")
        for bad in ("https://vegamovies.ninja/dune/", "http://x/y", "//cdn/p.jpg",
                    "movie\\flag", "x" * 400, "", "movie:dune:2021\nnote"):
            with self.assertRaises(accounts.UnknownWork, msg=repr(bad)):
                accounts.put_favorite(self.conn, key, bad, catalog=self.catalog,
                                      tracker=self.tracker, now=T0)
        self.assertEqual([], self.conn.execute(
            "SELECT work_key FROM user_favorites").fetchall())

    def test_favorite_cap_is_enforced_without_losing_the_existing_rows(self):
        key = self.new_account()["sync_key"]
        rows = [(f"movie:title-{i}:20{10 + i % 15}",) for i in range(6)]
        self.conn.executemany("INSERT INTO user_favorites(account_id, work_key,"
                              " season_number, episode_number, added_at)"
                              " VALUES(1, ?, 0, 0, ?)", [(w, T0) for (w,) in rows])
        with unittest.mock.patch.object(accounts, "MAX_FAVORITES", 6):
            with self.assertRaises(accounts.AccountFull):
                accounts.put_favorite(self.conn, key, "movie:dune:2021",
                                      catalog=self.catalog, tracker=self.tracker, now=T0)
        self.assertEqual(6, self.conn.execute(
            "SELECT COUNT(*) FROM user_favorites").fetchone()[0])

    def test_limit_bounds_the_rows_returned_not_the_rows_stored(self):
        key = self.new_account()["sync_key"]
        for i, work in enumerate(VISIBLE):
            accounts.put_favorite(self.conn, key, work, catalog=self.catalog,
                                  added_at=T0 + i, tracker=self.tracker, now=T0 + i)
        page = accounts.list_favorites(self.conn, key, catalog=self.catalog, limit=2,
                                       tracker=self.tracker, now=T0 + 9)
        self.assertEqual(2, len(page))
        self.assertEqual("series:packed-season:2020", page[0]["work_key"])  # newest first
        self.assertEqual(3, self.conn.execute(
            "SELECT COUNT(*) FROM user_favorites").fetchone()[0])


# ── playback progress ────────────────────────────────────────────────────────


class ProgressTests(StateTestCase):
    def record(self, key, position, duration, stamp, **kw):
        return accounts.put_progress(self.conn, key, kw.pop("work", "movie:dune:2021"),
                                     catalog=self.catalog, position_seconds=position,
                                     duration_seconds=duration,
                                     client_updated_at=stamp, tracker=self.tracker,
                                     now=stamp, **kw)

    def test_newer_client_write_wins_and_older_client_write_is_ignored(self):
        """The stale write must LOSE, on the stored numbers, not on a flag: a device
        that re-sent an old position after a newer one must not move the playhead."""
        key = self.new_account()["sync_key"]
        self.record(key, 100, 2000, T0 + 10)
        self.record(key, 900, 2000, T0 + 20)
        stale = self.record(key, 300, 2000, T0 + 15)
        self.assertFalse(stale["applied"])
        self.assertEqual(900.0, stale["position_seconds"])
        row = accounts.get_progress(self.conn, key, "movie:dune:2021",
                                    tracker=self.tracker, now=T0 + 21)
        self.assertEqual(900.0, row["position_seconds"])
        self.assertEqual(2000.0, row["duration_seconds"])
        self.assertEqual(T0 + 20, row["client_updated_at"])
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_progress").fetchone()[0])

    def test_two_devices_with_different_clocks_settle_on_their_own_timestamps(self):
        """Our receipt clock is NOT the tie-break, so a device whose clock is behind
        can still win if its own stamp is later, and a device whose clock runs ahead
        cannot win with an earlier stamp."""
        key = self.new_account()["sync_key"]
        slow = self.record(key, 500, 2000, T0 + 40)          # clock 100 s behind ours
        self.assertTrue(slow["applied"])
        ahead = accounts.put_progress(self.conn, key, "movie:dune:2021",
                                      catalog=self.catalog, position_seconds=10,
                                      duration_seconds=2000,
                                      client_updated_at=T0 + 30,   # earlier on its clock
                                      tracker=self.tracker, now=T0 + 1000)
        self.assertFalse(ahead["applied"])
        self.assertEqual(500.0, ahead["position_seconds"])

    def test_a_tie_goes_to_the_row_the_server_already_holds(self):
        key = self.new_account()["sync_key"]
        self.record(key, 600, 2000, T0 + 10)
        again = self.record(key, 10, 2000, T0 + 10)
        self.assertFalse(again["applied"])
        self.assertEqual(600.0, again["position_seconds"])

    def test_a_future_client_clock_is_clamped_and_cannot_freeze_the_row(self):
        """A device whose clock says 2035 must not be able to win every comparison
        forever: the stamp is clamped to our receipt time, so an ordinary device can
        still update the very next second."""
        key = self.new_account()["sync_key"]
        year_2035 = T0 + 10 * 365 * 86400
        written = accounts.put_progress(self.conn, key, "movie:dune:2021",
                                        catalog=self.catalog, position_seconds=100,
                                        duration_seconds=2000,
                                        client_updated_at=year_2035,
                                        tracker=self.tracker, now=T0)
        self.assertEqual(T0, written["client_updated_at"])
        self.assertLessEqual(written["client_updated_at"], T0 + 1.0)
        # a sane device, stamped after our clamp, still gets its write applied
        later = self.record(key, 200, 2000, T0 + 1)
        self.assertTrue(later["applied"])
        self.assertEqual(200.0, later["position_seconds"])

    def test_position_is_clamped_into_the_duration_and_percent_is_never_stored(self):
        key = self.new_account()["sync_key"]
        row = self.record(key, 4000, 2000, T0 + 10)
        self.assertEqual(2000.0, row["position_seconds"])
        schema = self.conn.execute("SELECT sql FROM sqlite_master"
                                   " WHERE name='user_progress'").fetchone()[0].lower()
        self.assertNotIn("percent", schema)
        self.assertNotIn("url", schema)

    def test_a_progress_write_scoped_by_episode_does_not_touch_the_season(self):
        key = self.new_account()["sync_key"]
        self.record(key, 100, 1200, T0 + 1, season_number=1, episode_number=1)
        self.record(key, 200, 1200, T0 + 2, season_number=1, episode_number=2)
        whole = self.record(key, 300, 4800, T0 + 3)      # the season pack / whole work
        self.assertEqual((0, 0), (whole["season_number"], whole["episode_number"]))
        self.assertEqual(3, len(accounts.list_progress(self.conn, key,
                                                       catalog=self.catalog,
                                                       tracker=self.tracker, now=T0 + 4)))
        self.assertEqual(100.0, accounts.get_progress(
            self.conn, key, "movie:dune:2021", season_number=1, episode_number=1,
            tracker=self.tracker, now=T0 + 5)["position_seconds"])

    def test_invalid_numbers_are_refused_rather_than_stored(self):
        key = self.new_account()["sync_key"]
        for bad in (float("nan"), float("inf"), -5, "abc", None, {}, []):
            with self.assertRaises(accounts.InvalidProgress, msg=repr(bad)):
                accounts.put_progress(self.conn, key, "movie:dune:2021",
                                      catalog=self.catalog, position_seconds=bad,
                                      duration_seconds=1000, tracker=self.tracker, now=T0)
        self.assertEqual([], self.conn.execute("SELECT * FROM user_progress").fetchall())

    def test_delete_progress_forgets_one_scope_only(self):
        key = self.new_account()["sync_key"]
        self.record(key, 100, 1200, T0 + 1, season_number=2, episode_number=1)
        self.record(key, 100, 1200, T0 + 2, season_number=2, episode_number=2)
        self.assertTrue(accounts.delete_progress(self.conn, key, "movie:dune:2021",
                                                 season_number=2, episode_number=1,
                                                 tracker=self.tracker, now=T0 + 3))
        self.assertFalse(accounts.delete_progress(self.conn, key, "movie:dune:2021",
                                                  season_number=2, episode_number=1,
                                                  tracker=self.tracker, now=T0 + 4))
        self.assertFalse(accounts.delete_progress(self.conn, key, "https://x/y/",
                                                  tracker=self.tracker, now=T0 + 5))
        rows = accounts.list_progress(self.conn, key, catalog=self.catalog,
                                      tracker=self.tracker, now=T0 + 6)
        self.assertEqual([(2, 2)], [(r["season_number"], r["episode_number"]) for r in rows])

    def test_order_is_newest_client_update_first(self):
        key = self.new_account()["sync_key"]
        self.record(key, 1, 10, T0 + 1, work="movie:dune:2021")
        self.record(key, 1, 10, T0 + 3, work="series:the-office:2005")
        self.record(key, 1, 10, T0 + 2, work="series:packed-season:2020")
        listed = accounts.list_progress(self.conn, key, catalog=self.catalog,
                                        tracker=self.tracker, now=T0 + 9)
        self.assertEqual(["series:the-office:2005", "series:packed-season:2020",
                          "movie:dune:2021"], [row["work_key"] for row in listed])


# ── the adult rule, on both paths ────────────────────────────────────────────


class AdultRuleTests(StateTestCase):
    def test_a_flagged_work_key_is_refused_exactly_like_an_absent_one(self):
        key = self.new_account()["sync_key"]
        answers = []
        for work in (ADULT[0], ABSENT[0], "https://katmoviehd.fans/x/"):
            try:
                accounts.put_favorite(self.conn, key, work, catalog=self.catalog,
                                      tracker=self.tracker, now=T0)
                self.fail(f"{work} was accepted")
            except accounts.UnknownWork as exc:
                answers.append((type(exc).__name__, exc.code, exc.status, exc.detail))
        self.assertEqual(1, len(set(answers)),
                         f"the adult answer differs from the absent one: {answers}")
        self.assertEqual(("UnknownWork", "not_found", 404, "not found"), answers[0])
        self.assertEqual([], self.conn.execute("SELECT work_key FROM user_favorites")
                         .fetchall())
        self.assertEqual([], self.conn.execute("SELECT work_key FROM user_progress")
                         .fetchall())

    def test_progress_on_a_flagged_work_is_refused_identically(self):
        key = self.new_account()["sync_key"]
        for work in (ADULT[0], ABSENT[0]):
            with self.assertRaises(accounts.UnknownWork):
                accounts.put_progress(self.conn, key, work, catalog=self.catalog,
                                      position_seconds=10, duration_seconds=100,
                                      tracker=self.tracker, now=T0)

    def test_the_catalog_predicate_is_the_one_the_rest_of_the_backend_uses(self):
        """A real `cat_works` fixture: the flag decides, NULL means visible, and the
        file is opened read-only so this module can never be the thing that writes to
        a projection database."""
        catalog_path = Path(self.tmp.name) / "catalog_fixture.db"
        make_catalog_db(catalog_path, visible=VISIBLE, adult=ADULT)
        key = self.new_account()["sync_key"]
        self.assertTrue(accounts.work_is_visible(catalog_path, "movie:dune:2021"))
        self.assertFalse(accounts.work_is_visible(catalog_path, ADULT[0]))
        self.assertFalse(accounts.work_is_visible(catalog_path, ABSENT[0]))
        conn = sqlite3.connect(catalog_path)
        self.addCleanup(conn.close)
        self.assertTrue(accounts.put_favorite(self.conn, key, "movie:dune:2021",
                                              catalog=conn, tracker=self.tracker, now=T0)
                        is not None)
        with self.assertRaises(accounts.UnknownWork):
            accounts.put_favorite(self.conn, key, ADULT[0], catalog=conn,
                                  tracker=self.tracker, now=T0)
        # NULL is visible: only an explicit 1 hides a work, so a flag column we did
        # not write cannot silently delete somebody's library. `catalog_v2` declares
        # `is_18_plus INTEGER NOT NULL DEFAULT 0`, so the NULL row comes from a legacy
        # or foreign projection — the only shape where it can reach us at all.
        legacy_path = Path(self.tmp.name) / "catalog_legacy.db"
        legacy = sqlite3.connect(legacy_path)
        legacy.execute("CREATE TABLE cat_works (work_key TEXT UNIQUE NOT NULL,"
                       " is_18_plus INTEGER)")
        legacy.execute("INSERT INTO cat_works(work_key, is_18_plus)"
                       " VALUES('movie:nulled:1', NULL)")
        legacy.commit()
        legacy.close()
        self.assertTrue(accounts.work_is_visible(legacy_path, "movie:nulled:1"))

    def test_a_flag_that_arrives_after_the_bookmark_is_filtered_not_deleted(self):
        """§13 filtered at DISPLAY time and the zero-data-loss rule kept: the row
        survives the flag, and disappears from every read the way the title would."""
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.conn, key, "movie:flagged-film:2019",
                              catalog=fake_catalog(visible=VISIBLE + ADULT, adult=()),
                              tracker=self.tracker, now=T0)
        stored = self.conn.execute("SELECT work_key FROM user_favorites").fetchall()
        self.assertEqual([("movie:flagged-film:2019",)], [tuple(r) for r in stored])
        rows = accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                       tracker=self.tracker, now=T0 + 1)
        self.assertEqual([], rows)
        self.assertEqual({}, accounts.get_progress(self.conn, key, "movie:flagged-film:2019",
                                                    tracker=self.tracker, now=T0 + 2))
        accounts.put_progress(self.conn, key, "movie:flagged-film:2019",
                              catalog=fake_catalog(visible=VISIBLE + ADULT, adult=()),
                              position_seconds=5, duration_seconds=100,
                              tracker=self.tracker, now=T0 + 3)
        self.assertEqual([], accounts.list_progress(self.conn, key, catalog=self.catalog,
                                                    tracker=self.tracker, now=T0 + 4))
        # and it comes back when the flag clears, because nothing was destroyed
        again = accounts.list_favorites(
            self.conn, key, catalog=fake_catalog(visible=VISIBLE + ADULT, adult=()),
            tracker=self.tracker, now=T0 + 5)
        self.assertEqual(["movie:flagged-film:2019"], [r["work_key"] for r in again])

    def test_a_write_with_no_visibility_oracle_is_refused_rather_than_guessed(self):
        """Fail closed: an unwired catalog is a 5xx, not a silent accept of a
        possibly-flagged key, and not a 404 that would blame the user for our plumbing."""
        key = self.new_account()["sync_key"]
        with self.assertRaises(accounts.CatalogUnreachable) as ctx:
            accounts.put_favorite(self.conn, key, "movie:dune:2021", tracker=self.tracker,
                                  now=T0)
        self.assertEqual(503, ctx.exception.status)
        self.assertEqual([], self.conn.execute("SELECT * FROM user_favorites").fetchall())

    def test_an_unreadable_catalog_is_an_error_and_never_a_quiet_not_found(self):
        key = self.new_account()["sync_key"]
        missing = Path(self.tmp.name) / "nope.db"
        with self.assertRaises(accounts.CatalogUnreachable):
            accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=missing,
                                  tracker=self.tracker, now=T0)

        def broken(work_key):
            raise RuntimeError("sqlite exploded")
        with self.assertRaises(accounts.CatalogUnreachable):
            accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=broken,
                                  tracker=self.tracker, now=T0)
        # a catalog file with no cat_works at all: could not check, not "does not exist"
        empty = Path(self.tmp.name) / "empty.db"
        sqlite3.connect(empty).close()
        with self.assertRaises(accounts.CatalogUnreachable):
            accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=empty,
                                  tracker=self.tracker, now=T0)

    def test_the_catalog_is_never_written_to_by_this_module(self):
        """The projection database is somebody else's long-running job. This module
        must not write it, lock it, or even change its journal mode, so the checks are
        the bytes of the file and the absence of sidecars, not a row count alone."""
        catalog_path = Path(self.tmp.name) / "catalog_fixture.db"
        make_catalog_db(catalog_path)
        before = catalog_path.read_bytes()
        count = sqlite3.connect(catalog_path).execute(
            "SELECT COUNT(*) FROM cat_works").fetchone()[0]
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=catalog_path,
                              tracker=self.tracker, now=T0)
        accounts.list_favorites(self.conn, key, catalog=catalog_path,
                                tracker=self.tracker, now=T0 + 1)
        accounts.put_progress(self.conn, key, "series:the-office:2005",
                              catalog=str(catalog_path), position_seconds=10,
                              duration_seconds=1200, tracker=self.tracker, now=T0 + 2)
        self.assertEqual(before, catalog_path.read_bytes())    # byte for byte untouched
        for side in (str(catalog_path) + suffix for suffix in ("-wal", "-shm", "-journal")):
            self.assertFalse(Path(side).exists(), f"{side} was created by us")
        self.assertEqual(count, sqlite3.connect(catalog_path).execute(
            "SELECT COUNT(*) FROM cat_works").fetchone()[0])
        # and a write attempted through a read-only handle is an error, never a change
        with self.assertRaises(sqlite3.OperationalError):
            sqlite3.connect(f"file:{catalog_path}?mode=ro").execute(
                "INSERT INTO cat_works(work_key) VALUES('movie:ours:1')")


# ── migration ────────────────────────────────────────────────────────────────


class MigrationTests(StateTestCase):
    OLD_ACCOUNTS = """
        CREATE TABLE user_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL
        )"""
    OLD_PROGRESS = """
        CREATE TABLE user_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            work_key TEXT NOT NULL,
            season_number INTEGER NOT NULL DEFAULT 0,
            episode_number INTEGER NOT NULL DEFAULT 0,
            position_seconds REAL NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )"""

    def build_old_database(self):
        self.conn.close()
        self.db_path.unlink()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(self.OLD_ACCOUNTS + ";" + self.OLD_PROGRESS + ";")
        old_hash = accounts._hash_key("legacy-key-value-pair-aaaa")
        conn.execute("INSERT INTO user_accounts(id, key_hash, created_at)"
                     " VALUES(1, ?, ?)", (old_hash, T0 - 400 * 86400))
        conn.execute("INSERT INTO user_progress(account_id, work_key, season_number,"
                     " episode_number, position_seconds, duration_seconds, updated_at)"
                     " VALUES(1, 'movie:dune:2021', 0, 0, 400, 2000, ?)", (T0 - 10,))
        conn.commit()
        self.conn = conn
        return "legacy-key-value-pair-aaaa"

    def test_ensure_schema_adds_the_missing_columns_and_backfills_them(self):
        key = self.build_old_database()
        result = accounts.ensure_schema(self.conn)
        self.assertIn("user_accounts.last_seen_at", result["added_columns"])
        self.assertIn("user_accounts.revoked_at", result["added_columns"])
        self.assertIn("user_progress.client_updated_at", result["added_columns"])
        self.conn.commit()
        row = self.conn.execute("SELECT last_seen_at, revoked_at, created_at"
                                " FROM user_accounts WHERE id = 1").fetchone()
        self.assertEqual(row["created_at"], row["last_seen_at"])   # backfilled, not zero
        self.assertIsNone(row["revoked_at"])
        prog = self.conn.execute("SELECT client_updated_at, updated_at, position_seconds"
                                 " FROM user_progress").fetchone()
        self.assertEqual(prog["updated_at"], prog["client_updated_at"])
        self.assertEqual(400.0, prog["position_seconds"])          # the row is unmoved

    def test_a_migrated_legacy_library_still_works_and_still_beats_a_stale_write(self):
        key = self.build_old_database()
        accounts.ensure_schema(self.conn)
        self.conn.commit()
        rows = accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                       tracker=self.tracker, now=T0)
        self.assertEqual([], rows)                                  # no bookmarks yet
        self.assertEqual(400.0, accounts.get_progress(
            self.conn, key, "movie:dune:2021", tracker=self.tracker,
            now=T0)["position_seconds"])
        # the backfilled client_updated_at is the tie-break a new release needs
        stale = accounts.put_progress(self.conn, key, "movie:dune:2021",
                                      catalog=self.catalog, position_seconds=50,
                                      duration_seconds=2000, client_updated_at=T0 - 20,
                                      tracker=self.tracker, now=T0)
        self.assertFalse(stale["applied"])
        self.assertEqual(400.0, stale["position_seconds"])
        fresh = accounts.put_progress(self.conn, key, "movie:dune:2021",
                                      catalog=self.catalog, position_seconds=800,
                                      duration_seconds=2000, client_updated_at=T0 + 1,
                                      tracker=self.tracker, now=T0 + 1)
        self.assertTrue(fresh["applied"])

    def test_the_unique_scope_index_is_created_after_the_alters(self):
        key = self.build_old_database()
        accounts.ensure_schema(self.conn)
        self.conn.commit()
        indexes = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ux_%'")}
        self.assertIn("ux_user_prog_scope", indexes)
        self.assertIn("ux_user_fav_scope", indexes)
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              added_at=T0, tracker=self.tracker, now=T0)
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              added_at=T0 + 5, tracker=self.tracker, now=T0 + 5)
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_favorites").fetchone()[0])

    def test_migration_is_idempotent_and_never_drops_a_row(self):
        key = self.build_old_database()
        accounts.ensure_schema(self.conn)
        self.conn.commit()
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              tracker=self.tracker, now=T0)
        first = [(row[0], row[1]) for row in self.conn.execute(
            "SELECT work_key, position_seconds FROM user_progress")]
        for _ in range(3):
            added = accounts.ensure_schema(self.conn)["added_columns"]
            self.conn.commit()
            self.assertEqual([], added)
        self.assertEqual(first, [(row[0], row[1]) for row in self.conn.execute(
            "SELECT work_key, position_seconds FROM user_progress")])
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM user_favorites").fetchone()[0])

    def test_a_legacy_key_that_was_revoked_under_the_old_schema_stays_dead(self):
        key = self.build_old_database()
        accounts.ensure_schema(self.conn)
        self.conn.commit()
        self.conn.execute("UPDATE user_accounts SET key_hash = ? WHERE id = 1",
                          (accounts.TOMBSTONE_PREFIX + "deadbeef",))
        self.conn.commit()
        with self.assertRaises(accounts.UnknownAccount):
            accounts.authenticate(self.conn, key, now=T0, tracker=self.tracker)


# ── the attempt limiter ──────────────────────────────────────────────────────


class AttemptLimiterTests(StateTestCase):
    def test_the_third_failure_locks_the_key_and_the_lock_expires(self):
        guessed = accounts.new_sync_key()
        for step in range(1, 3):
            with self.assertRaises(accounts.UnknownAccount, msg=f"attempt {step}"):
                accounts.authenticate(self.conn, guessed, now=T0 + step,
                                      tracker=self.tracker)
        with self.assertRaises(accounts.Locked) as ctx:
            accounts.authenticate(self.conn, guessed, now=T0 + 3, tracker=self.tracker)
        self.assertEqual(429, ctx.exception.status)
        self.assertEqual("rate_limited", ctx.exception.code)
        self.assertEqual(30, ctx.exception.retry_after)
        # still locked for anybody who presents it inside the lock window
        for offset in (10, 25, 29):
            with self.assertRaises(accounts.Locked, msg=offset):
                accounts.authenticate(self.conn, guessed, now=T0 + 3 + offset,
                                      tracker=self.tracker)
        # the lock expires: the answer is back to the ordinary not-found, and the
        # budget has restarted rather than carrying the spent count over
        for step in (34, 35):
            with self.assertRaises(accounts.UnknownAccount, msg=step):
                accounts.authenticate(self.conn, guessed, now=T0 + step,
                                      tracker=self.tracker)
        # and three fresh misses lock it again — "come back later" is a pause, not a
        # pardon, and the restarted window is why a locked bucket still answers alike
        with self.assertRaises(accounts.Locked):
            accounts.authenticate(self.conn, guessed, now=T0 + 36, tracker=self.tracker)

    def test_a_burned_out_key_and_a_never_issued_key_answer_alike(self):
        """The identity of the answer survives the limiter: hammering key A and
        hammering key B to the same count gives the same two answers, so a lock is
        not a signal that this guess was closer than that one."""
        a, b = accounts.new_sync_key(), accounts.new_sync_key()
        seen = []
        for key in (a, b):
            for step in range(1, 4):
                try:
                    accounts.authenticate(self.conn, key, now=T0 + step,
                                          tracker=self.tracker)
                except accounts.AccountError as exc:
                    seen.append((type(exc).__name__, exc.code, exc.status))
        self.assertEqual(len(set(seen)), 2)      # not_found xN, then rate_limited xN
        self.assertEqual(seen[0], ("UnknownAccount", "not_found", 404))
        self.assertEqual(seen[-1], ("Locked", "rate_limited", 429))
        self.assertEqual(seen[:3], seen[3:])

    def test_a_valid_key_can_never_be_denied_by_the_limiter(self):
        """The property that decides whether this design is deployable: an anonymous
        attacker must not be able to lock a real user out of their own library."""
        victim = self.new_account()
        accounts.put_favorite(self.conn, victim["sync_key"], "movie:dune:2021",
                              catalog=self.catalog, tracker=self.tracker, now=T0)
        attacker = accounts.new_sync_key()
        for step in range(1, 20):
            try:
                accounts.authenticate(self.conn, attacker, now=T0 + step,
                                      tracker=self.tracker)
            except accounts.AccountError:
                pass
        account = accounts.authenticate(self.conn, victim["sync_key"], now=T0 + 20,
                                        tracker=self.tracker)
        self.assertEqual(account["account_id"], victim["account_id"])
        self.assertEqual(1, len(accounts.list_favorites(self.conn, victim["sync_key"],
                                                        catalog=self.catalog,
                                                        tracker=self.tracker,
                                                        now=T0 + 21)))

    def test_one_devices_typos_do_not_burn_another_devices_budget(self):
        """Buckets are per presented key, so the person next to you fat-fingering
        their own key cannot lock you out of yours."""
        key = self.new_account()["sync_key"]
        other = self.new_account(now=T0 + 1)["sync_key"]
        wrong = key[:-2] + "qq"
        for step in range(1, 4):
            try:
                accounts.authenticate(self.conn, wrong, now=T0 + step, tracker=self.tracker)
            except accounts.AccountError:
                pass
        with self.assertRaises(accounts.Locked):
            accounts.authenticate(self.conn, wrong, now=T0 + 4, tracker=self.tracker)
        # the real key, and an entirely unrelated key, both still work at the instant
        # the typo bucket is locked
        account = accounts.authenticate(self.conn, key, now=T0 + 5, tracker=self.tracker)
        self.assertTrue(account["account_id"])
        accounts.authenticate(self.conn, other, now=T0 + 5, tracker=self.tracker)
        # the locked bucket stays locked — a legitimate presentation clears only its
        # own window, never somebody else's
        self.assertEqual(3, int(self.conn.execute(
            "SELECT failures FROM sync_key_attempts WHERE bucket = ?",
            (accounts._hash_key(wrong),)).fetchone()[0]))
        self.assertGreater(float(self.conn.execute(
            "SELECT locked_until FROM sync_key_attempts WHERE bucket = ?",
            (accounts._hash_key(wrong),)).fetchone()[0]), T0 + 4)
        for presented in (key, other):
            self.assertIsNone(self.conn.execute(
                "SELECT 1 FROM sync_key_attempts WHERE bucket = ?",
                (accounts._hash_key(presented),)).fetchone())

    def test_the_lock_survives_a_restart_because_the_window_is_persisted(self):
        guessed = accounts.new_sync_key()
        for step in range(1, 4):
            try:
                accounts.authenticate(self.conn, guessed, now=T0 + step,
                                      tracker=self.tracker)
            except accounts.AccountError:
                pass
        locked_until = T0 + 3 + self.tracker.lock_seconds
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.conn.commit()
        restarted = accounts.AttemptTracker(max_failures=3, window_seconds=60.0,
                                            lock_seconds=300.0)      # a cold process
        second = accounts.connect(self.db_path)
        self.addCleanup(second.close)
        with self.assertRaises(accounts.Locked) as ctx:
            accounts.authenticate(second, guessed, now=T0 + 4, tracker=restarted)
        # the remaining time comes from the row, not from the new process's own
        # lock_seconds: a restart cannot shorten a lockout already handed out
        self.assertAlmostEqual(locked_until - (T0 + 4), ctx.exception.retry_after)
        self.assertLess(ctx.exception.retry_after, restarted.lock_seconds)
        # the cold process really did read the durable window rather than trusting
        # its own empty memory
        self.assertIn(accounts._hash_key(guessed), restarted._mem)

    def test_locking_is_one_way_so_hammering_cannot_extend_a_lockout(self):
        guessed = accounts.new_sync_key()
        for step in range(1, 4):
            try:
                accounts.authenticate(self.conn, guessed, now=T0 + step, tracker=self.tracker)
            except accounts.AccountError:
                pass
        bucket = accounts._hash_key(guessed)
        locked_until = self.conn.execute(
            "SELECT locked_until FROM sync_key_attempts WHERE bucket = ?",
            (bucket,)).fetchone()[0]
        self.assertAlmostEqual(T0 + 3 + 30.0, locked_until)
        for step in range(5, 12):
            try:
                accounts.authenticate(self.conn, guessed, now=T0 + step, tracker=self.tracker)
            except accounts.AccountError:
                pass
        self.assertAlmostEqual(locked_until, self.conn.execute(
            "SELECT locked_until FROM sync_key_attempts WHERE bucket = ?", (bucket,))
            .fetchone()[0])

    def test_the_durable_window_refills_once_the_fixed_window_ages_out(self):
        guessed = accounts.new_sync_key()
        for step in range(1, 3):
            try:
                accounts.authenticate(self.conn, guessed, now=T0 + step, tracker=self.tracker)
            except accounts.AccountError:
                pass
        fresh = accounts.AttemptTracker(max_failures=3, window_seconds=60.0,
                                        lock_seconds=30.0)
        self.assertEqual(2, fresh.state(self.conn, accounts._hash_key(guessed),
                                       now=T0 + 10)["failures"])
        self.assertEqual(0, fresh.state(self.conn, accounts._hash_key(guessed),
                                        now=T0 + 61)["failures"])
        with self.assertRaises(accounts.UnknownAccount):
            accounts.authenticate(self.conn, guessed, now=T0 + 62, tracker=fresh)

    def test_sweep_forgets_only_stale_windows(self):
        guessed = accounts.new_sync_key()
        try:
            accounts.authenticate(self.conn, guessed, now=T0, tracker=self.tracker)
        except accounts.AccountError:
            pass
        self.assertEqual(0, self.tracker.sweep(self.conn, now=T0 + 10))
        removed = self.tracker.sweep(self.conn, now=T0 + accounts.ATTEMPT_HORIZON_SECONDS + 1)
        self.assertGreaterEqual(removed, 1)
        self.assertEqual(0, int(self.conn.execute(
            "SELECT COUNT(*) FROM sync_key_attempts WHERE window_started_at < ?",
            (T0 + accounts.ATTEMPT_HORIZON_SECONDS,)).fetchone()[0]))

    def test_memory_cannot_grow_with_the_number_of_guessed_strings(self):
        big = accounts.AttemptTracker(max_failures=1000, cache_limit=16)
        for i in range(200):
            big.record_failure(self.conn, accounts._hash_key(f"guessed-{i}"), now=T0 + i)
        self.assertLessEqual(len(big._mem), 32)


# ── pruning ──────────────────────────────────────────────────────────────────


class PruneTests(StateTestCase):
    def seed(self, key, now):
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              tracker=self.tracker, now=now)
        accounts.put_progress(self.conn, key, "series:the-office:2005",
                              catalog=self.catalog, season_number=2, episode_number=1,
                              position_seconds=10, duration_seconds=1200,
                              tracker=self.tracker, now=now)

    def count(self, table):
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def test_prune_removes_only_accounts_idle_longer_than_the_horizon(self):
        old = self.new_account(now=T0 - 400 * 86400)["sync_key"]
        self.seed(old, T0 - 400 * 86400)
        fresh = self.new_account(now=T0 - 10 * 86400)["sync_key"]
        self.seed(fresh, T0 - 10 * 86400)
        young = self.new_account(now=T0 - 10 * 86400)["sync_key"]   # never used it

        result = accounts.prune_accounts(self.conn, idle_days=120, now=T0,
                                         tracker=self.tracker)
        self.assertEqual(1, result["removed"], "an account inside the horizon was pruned")
        self.assertEqual(1, result["favorites_removed"])
        self.assertEqual(1, result["progress_removed"])
        self.assertEqual(2, self.count("user_accounts"))
        self.assertEqual(1, self.count("user_favorites"))
        self.assertEqual(1, self.count("user_progress"))
        # the removed library is gone by key too, and the survivors still resolve
        with self.assertRaises(accounts.UnknownAccount):
            accounts.list_favorites(self.conn, old, catalog=self.catalog,
                                    tracker=self.tracker, now=T0 + 1)
        self.assertEqual(1, len(accounts.list_favorites(self.conn, fresh,
                                                        catalog=self.catalog,
                                                        tracker=self.tracker, now=T0 + 1)))
        self.assertEqual([], accounts.list_favorites(self.conn, young,
                                                     catalog=self.catalog,
                                                     tracker=self.tracker, now=T0 + 1))

    def test_an_account_kept_alive_by_its_last_request_survives_a_long_idle_horizon(self):
        """`last_seen_at` is the anchor: an old account used today is not idle, and a
        young account is never pruned for having been created too long ago."""
        key = self.new_account(now=T0 - 365 * 86400)["sync_key"]
        self.seed(key, T0 - 365 * 86400)
        accounts.authenticate(self.conn, key, now=T0 - 1, tracker=self.tracker)
        self.assertEqual(0, accounts.prune_accounts(self.conn, idle_days=120, now=T0,
                                                    tracker=self.tracker)["removed"])
        self.assertEqual(1, self.count("user_favorites"))

    def test_pruning_removes_children_without_relying_on_the_foreign_key_pragma(self):
        """The silent-failure class this file guards: `PRAGMA foreign_keys` is
        per-connection, so a cascade can be a no-op and the rows leak forever."""
        key = self.new_account(now=T0 - 365 * 86400)["sync_key"]
        self.seed(key, T0 - 365 * 86400)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)                      # foreign_keys defaults OFF
        result = accounts.prune_accounts(conn, idle_days=120, now=T0, tracker=self.tracker)
        self.assertEqual(1, result["removed"])
        self.assertEqual(0, self.count("user_favorites"))
        self.assertEqual(0, self.count("user_progress"))

    def test_revoked_tombstones_age_out_and_live_accounts_do_not(self):
        dead_id = self.new_account(now=T0 - 400 * 86400)
        live = self.new_account(now=T0 - 400 * 86400)
        accounts.revoke_account(self.conn, dead_id["sync_key"],
                                now=T0 - 200 * 86400, tracker=self.tracker)
        accounts.authenticate(self.conn, live["sync_key"], now=T0 - 1,
                              tracker=self.tracker)
        result = accounts.prune_accounts(self.conn, idle_days=120, now=T0,
                                         tracker=self.tracker)
        self.assertEqual(1, result["removed"])
        self.assertEqual(1, self.count("user_accounts"))
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM user_accounts WHERE id = ?", (dead_id["account_id"],))
            .fetchone(), "the tombstone survived the prune")
        survivor = accounts.authenticate(self.conn, live["sync_key"], now=T0 + 1,
                                         tracker=self.tracker)
        self.assertEqual(live["account_id"], survivor["account_id"])
        with self.assertRaises(accounts.UnknownAccount):
            accounts.authenticate(self.conn, dead_id["sync_key"], now=T0 + 2,
                                  tracker=self.tracker)

    def test_prune_is_a_no_op_on_an_empty_or_fresh_database(self):
        result = accounts.prune_accounts(self.conn, idle_days=0, now=T0,
                                         tracker=self.tracker)
        self.assertEqual(0, result["removed"])
        self.assertEqual(0, result["favorites_removed"])
        self.assertEqual(0, self.count("user_accounts"))


# ── the wire shape (provenance at the edge) ──────────────────────────────────


class PublicShapeTests(StateTestCase):
    def test_to_public_drops_the_internal_identifiers_and_uses_the_minted_ref(self):
        key = self.new_account()["sync_key"]
        accounts.put_favorite(self.conn, key, "movie:dune:2021", catalog=self.catalog,
                              tracker=self.tracker, now=T0)
        row = accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                      tracker=self.tracker, now=T0 + 1)[0]
        handle = lambda work: "opaque" + hashlib.sha256(work.encode()).hexdigest()[:8]
        public = accounts.to_public(row, handle)
        self.assertNotIn("work_key", public)
        self.assertNotIn("account_id", public)
        self.assertEqual(accounts.PUBLIC_REF_KEY, "work_ref")
        self.assertTrue(public["work_ref"].startswith("opaque"))
        self.assertNotIn("movie:dune:2021", str(public))
        self.assertEqual(row["added_at"], public["added_at"])

    def test_to_public_refuses_to_leak_a_raw_work_key_when_no_mint_is_given(self):
        row = {"work_key": "series:the-office:2005", "account_id": 7, "added_at": T0}
        with self.assertRaises(ValueError):
            accounts.to_public(row, None)
        with self.assertRaises(ValueError):
            accounts.to_public([row], None)

    def test_a_public_library_carries_no_provenance_key_for_redact_to_strip(self):
        """`redact.PROVENANCE` forbids the literal key name `work_key`, so a state
        row projected with `to_public` must contain no forbidden key at all — this is
        the check that the wire name we chose is really the one `redact` allows."""
        key = self.new_account()["sync_key"]
        for work in VISIBLE:
            accounts.put_favorite(self.conn, key, work, catalog=self.catalog,
                                  tracker=self.tracker, now=T0)
            accounts.put_progress(self.conn, key, work, catalog=self.catalog,
                                  position_seconds=10, duration_seconds=100,
                                  tracker=self.tracker, now=T0)
        mint = lambda work: redact.mint_text(work, "test-secret")
        payload = {"favorites": accounts.to_public_list(
            accounts.list_favorites(self.conn, key, catalog=self.catalog,
                                    tracker=self.tracker, now=T0 + 1), mint),
            "progress": accounts.to_public_list(
                accounts.list_progress(self.conn, key, catalog=self.catalog,
                                       tracker=self.tracker, now=T0 + 1), mint)}
        self.assertEqual([], redact.provenance_keys(payload))
        # the minted ref is an opaque digest: no title, hoster or site name anywhere
        # in the serialisable payload, which is the provenance rule at the wire edge
        blob = json.dumps(payload)
        for needle in ("dune", "office", "packed-season", "://", "katmovie"):
            self.assertNotIn(needle, blob)
        for row in payload["favorites"] + payload["progress"]:
            self.assertNotIn("work_key", row)
            self.assertIn(accounts.PUBLIC_REF_KEY, row)
        # the raw keys are still in the database: suppression at the edge, no data loss
        self.assertEqual(3, self.count_rows("user_favorites"))
        self.assertEqual(3, self.count_rows("user_progress"))
        self.assertIn("movie:dune:2021", str([row[0] for row in self.conn.execute(
            "SELECT work_key FROM user_favorites")]))

    def count_rows(self, table):
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
