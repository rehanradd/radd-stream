#!/usr/bin/env python3
"""Offline tests for the zero-friction entry and for money that arrives by SMS:
`accounts.grant_or_resume_device_trial`, `accounts.link_profile_with_pin` and
`payments.sms_webhook` (plus its `viewer` mount and its `admin_panel` surface).

    python3 -S Fast_Fetch/test_device_trials_and_webhook.py

Same discipline as `test_accounts.py` / `test_payments.py` / `test_admin_panel.py`:
every case is a plain function call against a temp `user_state.db` inside a temp
directory. No port is opened, no network is touched, no live database is read or
written, and `RADD_USER_STATE_DB` is pinned for the whole run so a forgotten path
argument cannot reach the deployment's real ledger. The one thing that is not a bare
function call is `viewer.DashboardHandler._merchant_relay`, driven through a
duck-typed stub handler — still no socket and no thread.

`RADD_MERCHANT_SECRET` is *deleted* from the environment for every case unless the
case puts it back, because a fail-closed default is only proven by testing the unset
deployment. PIN hashing is PBKDF2 at `accounts.PIN_ITERATIONS` (120,000, the floor
ruled by `docs/RADD_RELAY_AND_AUTH_ARCHITECTURE.md` R6), measured at a 56.6 ms
median per derivation on this box's one core, so these cases share one fixture per
class and link a profile no more than the arithmetic needs.

What the cases are about, in the order that matters:
  1. a device gets its free trial ONCE: the `device_trials` row is the record of the
     grant, so no reinstall, revocation or replay mints a second one — and the one
     path that does, an account pruned as idle past retention taking its expired
     trial row with it, is asserted here as a priced decision rather than hidden;
  2. a resumed trial never returns a plaintext sync key, because `device_id` is
     chosen by the client and handing a key back on it would be a takeover;
  3. the bonus day for a linked profile is granted once per account, the PIN behind
     a re-link is a salted, bounded, cost-scarce digest, and a PIN is never
     authority for the account;
  4. the relay credits only an exact match on gateway + TID + the PKR this server
     quoted, one TID buys exactly one membership, a replay cannot refresh a stale
     record, and every failure path falls back to `pending` for a human;
  5. a callback without the merchant secret is refused before its body is read, and
     no payment artifact and no profile secret rides an account-surface response.
"""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts            # noqa: E402
import accounts_api        # noqa: E402
import admin_panel         # noqa: E402
import api_v2              # noqa: E402
import payments            # noqa: E402
import viewer              # noqa: E402

SECRET = "test-install-secret"
TOKEN = "operator-token-for-tests"
MERCHANT = "relay-secret-never-real"
P = accounts_api.PREFIX
DAY = 86400.0
NOW = 1_800_000_000.0
#: A plausible installation id: 36 characters of the shape Android's
#: `Settings.Secure.ANDROID_ID`-derived uuid actually arrives in.
DEVICE = "a1b2c3d4-0001-4eee-8b0d-cafe56789012"
OTHER_DEVICE = "beefcafe0123456789abcdef01234567"
JAZZ_TID = "9823145671"
EASY_TID = "150923456789"
RAAST_TID = "RAST2024AB39C7D1E5"
PIN = "4721"
PHONE = "+92 300 1234567"


class Fixture(unittest.TestCase):
    """One temp accounts ledger, one temp catalog, merchant secret unset."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / "user_state.db"
        self.catalog = root / "catalog.db"
        env = mock.patch.dict("os.environ", {
            "RADD_USER_STATE_DB": str(self.state),
            "RADD_ADMIN_TOKEN": TOKEN})
        env.start()
        self.addCleanup(env.stop)
        # `patch.dict` snapshots the whole mapping and puts it back on stop, so the
        # merchant secret can simply be removed for the duration: every case starts
        # on a deployment that forgot it, which is the one that must credit nothing.
        os.environ.pop(payments.MERCHANT_SECRET_ENV, None)
        with closing(sqlite3.connect(str(self.catalog))) as conn:
            conn.execute("CREATE TABLE cat_works (work_key TEXT,"
                         " is_18_plus INTEGER DEFAULT 0)")
            conn.execute("INSERT INTO cat_works VALUES"
                         " ('movie:in:1000:sample katmoviehd title', 0)")
            conn.commit()
            # The operator's own price row, so `price_table` reads the same PKR
            # figures here that a deployed server would charge.
            admin_panel._ensure_monetization(conn)
            conn.commit()
        self.conn = accounts.connect(self.state)         # installs the schema
        self.addCleanup(self.conn.close)

    # ── fixtures ─────────────────────────────────────────────────────────
    def trial(self, device=DEVICE, *, now=NOW, **extra):
        return accounts.grant_or_resume_device_trial(self.conn, device,
                                                     now=now, **extra)

    def account(self, device=DEVICE, *, now=NOW):
        """A trial account plus the plaintext key it was minted with."""
        made = self.trial(device, now=now)
        self.assertTrue(made["created"], made)
        return made

    def paid_claim(self, plan="vip_monthly", method="jazzcash", tid=JAZZ_TID,
                   account_id=None, **extra):
        return payments.submit_payment(self.conn,
                                       account_id or self.account()["account_id"],
                                       plan=plan, method=method, tid=tid,
                                       catalog_path=self.catalog, **extra)

    def relay(self, gateway="jazzcash", tid=JAZZ_TID, amount=200, **extra):
        return payments.sms_webhook(self.conn, gateway=gateway, tid=tid,
                                    amount=amount, **extra)

    def column(self, account_id, name):
        return self.conn.execute("SELECT %s FROM user_accounts WHERE id = ?"
                                 % name, (int(account_id),)).fetchone()[0]

    def rows(self, table):
        return self.conn.execute("SELECT * FROM %s" % table).fetchall()

    # ── HTTP-edge helpers (still no socket) ──────────────────────────────
    def post(self, path, body=None, headers=None):
        return accounts_api.route_post(path, body or {}, db_path=self.state,
                                       catalog_path=self.catalog, secret=SECRET,
                                       headers={} if headers is None else headers)

    def bearer(self, made):
        return {"Authorization": "Bearer %s" % made["sync_key"]}

    def payload(self, answered):
        self.assertIsNotNone(answered)
        return json.loads(answered[2].decode("utf-8"))


class TrialLedgerSchema(Fixture):
    """The grant must have somewhere to live that outlives the account it points at,
    or "one trial per device" is a suggestion."""

    def test_the_two_new_tables_arrive_through_the_accounts_init_path(self):
        names = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("device_trials", names)
        self.assertIn("verified_incoming_tids", names)

    def test_device_trials_columns_are_exactly_the_spec(self):
        columns = [row[1] for row in self.conn.execute(
            "PRAGMA table_info(device_trials)")]
        self.assertEqual(columns, ["device_id", "account_id", "first_seen_at",
                                   "trial_expires_at"])

    def test_the_device_id_is_the_primary_key_and_nothing_else_is(self):
        keys = {row[1]: row[5] for row in self.conn.execute(
            "PRAGMA table_info(device_trials)")}
        self.assertEqual(keys["device_id"], 1)
        self.assertEqual([name for name, pk in keys.items() if pk], ["device_id"])

    def test_the_relay_record_is_keyed_on_gateway_and_tid_together(self):
        keys = {row[1]: row[5] for row in self.conn.execute(
            "PRAGMA table_info(verified_incoming_tids)")}
        self.assertEqual(sorted(name for name, pk in keys.items() if pk),
                         ["gateway", "tid"])

    def test_a_tid_has_no_unique_index_because_one_payment_can_be_claimed_twice(self):
        # The rule is enforced by reading (`_claim_already_credited`), not by a
        # constraint a live table may already violate.
        indexed = self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('index','table')"
            " AND tbl_name = 'payment_transactions'").fetchall()
        self.assertNotIn("UNIQUE", " ".join(str(row[0] or "") for row in indexed))

    def test_the_profile_columns_are_additive_on_an_older_database(self):
        """A `user_state.db` written before this release must gain the four columns
        through `ensure_schema`, because that is the only migration path there is."""
        with tempfile.TemporaryDirectory() as work:
            legacy = Path(work) / "legacy.db"
            with closing(sqlite3.connect(str(legacy))) as conn:
                conn.execute("CREATE TABLE user_accounts (id INTEGER PRIMARY KEY"
                             " AUTOINCREMENT, key_hash TEXT UNIQUE NOT NULL,"
                             " created_at REAL NOT NULL)")
                conn.execute("INSERT INTO user_accounts(key_hash, created_at)"
                             " VALUES('sha256:deadbeef', ?)", (NOW - 10 * DAY,))
                conn.commit()
                accounts.ensure_schema(conn)
                columns = {row[1] for row in
                           conn.execute("PRAGMA table_info(user_accounts)")}
                self.assertTrue({"vip_until", "linked_at", "profile_name", "phone",
                                 "pin_hash"} <= columns, columns)
                self.assertIsNotNone(conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                    " AND name = 'device_trials'").fetchone())


class TrialGrant(Fixture):
    def test_a_new_device_mints_an_account_with_three_days(self):
        made = self.trial()
        self.assertTrue(made["created"])
        self.assertFalse(made["reissued"])
        self.assertIsInstance(made["sync_key"], str)
        self.assertEqual(made["first_seen_at"], NOW)
        self.assertEqual(made["trial_expires_at"], NOW + 3 * DAY)
        self.assertEqual(made["vip_until"], made["trial_expires_at"])
        self.assertEqual(made["trial_seconds_remaining"], 3 * DAY)
        self.assertTrue(accounts.vip_status(self.state, made["sync_key"])["vip"])

    def test_the_trial_clock_is_the_three_days_the_owner_asked_for(self):
        self.assertEqual(accounts.TRIAL_DAYS, 3)
        self.assertEqual(accounts.PROFILE_BONUS_SECONDS, DAY)

    def test_a_second_visit_resumes_the_same_clock_and_gives_no_key(self):
        made = self.account()
        again = self.trial(now=NOW + DAY)
        self.assertFalse(again["created"])
        self.assertFalse(again["reissued"])
        self.assertIsNone(again["sync_key"])
        self.assertEqual(again["trial_expires_at"], made["trial_expires_at"])
        self.assertEqual(again["account_id"], made["account_id"])
        self.assertEqual(again["trial_seconds_remaining"], 2 * DAY)

    def test_a_reinstall_cannot_buy_a_second_three_days(self):
        """Ten resumes a week apart must all carry the original expiry — this is the
        entire reason the ledger exists rather than trusting `vip_until`."""
        made = self.account()
        for offset in range(1, 11):
            resume = self.trial(now=NOW + offset * DAY)
            self.assertEqual(resume["trial_expires_at"], made["trial_expires_at"])
            self.assertFalse(resume["created"])

    def test_the_trial_ends_when_the_clock_says_and_not_later(self):
        made = self.account()
        inside = accounts.vip_status(self.state, made["sync_key"],
                                     now=made["trial_expires_at"] - 1)
        outside = accounts.vip_status(self.state, made["sync_key"],
                                      now=made["trial_expires_at"] + 1)
        self.assertTrue(inside["vip"])
        self.assertFalse(outside["vip"])

    def test_a_revoked_account_is_replaced_but_the_expiry_is_not(self):
        made = self.account()
        accounts.revoke_account(self.conn, made["sync_key"], now=NOW)
        later = self.trial(now=NOW + 2 * DAY)
        self.assertTrue(later["reissued"])
        self.assertNotEqual(later["account_id"], made["account_id"])
        self.assertIsInstance(later["sync_key"], str)
        self.assertEqual(later["trial_expires_at"], made["trial_expires_at"])
        self.assertEqual(later["vip_until"], made["trial_expires_at"])
        self.assertFalse(accounts.vip_status(self.state, later["sync_key"],
                                             now=NOW + 4 * DAY)["vip"])

    def test_a_trial_whose_account_row_is_simply_gone_also_reissues(self):
        made = self.account()
        self.conn.execute("DELETE FROM user_accounts WHERE id = ?",
                          (made["account_id"],))
        self.conn.commit()
        later = self.trial(now=NOW + DAY)
        self.assertTrue(later["reissued"])
        self.assertEqual(later["trial_expires_at"], made["trial_expires_at"])

    def test_the_reissued_key_is_the_one_the_device_may_use_and_the_resume_is_stable(
            self):
        made = self.account()
        accounts.revoke_account(self.conn, made["sync_key"], now=NOW)
        again = self.trial(now=NOW + DAY)
        third = self.trial(now=NOW + 2 * DAY)
        self.assertFalse(third["reissued"])
        self.assertFalse(third["created"])
        self.assertIsNone(third["sync_key"])
        self.assertEqual(third["account_id"], again["account_id"])

    def test_two_devices_are_two_accounts_and_never_one_clock(self):
        first = self.account()
        second = self.trial(OTHER_DEVICE, now=NOW + DAY)
        self.assertTrue(second["created"])
        self.assertNotEqual(second["account_id"], first["account_id"])
        self.assertEqual(second["trial_expires_at"], NOW + 4 * DAY)
        self.assertEqual(first["trial_expires_at"], NOW + 3 * DAY)

    def test_a_device_id_is_trimmed_and_nothing_more(self):
        made = self.account()
        padded = self.trial("   %s   " % DEVICE, now=NOW + DAY)
        self.assertEqual(padded["account_id"], made["account_id"])
        self.assertEqual(len(self.rows("device_trials")), 1)

    def test_a_device_id_the_server_cannot_store_is_refused_before_any_write(self):
        for junk in ("", "   ", "short", "x" * 200, "two words", "../etc/passwd",
                     'quote"inside', "line\nbreak", "<script>", "id;DROP TABLE",
                     None, 1234, 12.5, [], {}, True):
            with self.subTest(device=junk):
                with self.assertRaises(accounts.WeakDeviceId):
                    accounts.grant_or_resume_device_trial(self.conn, junk, now=NOW)
        self.assertEqual(len(self.rows("device_trials")), 0)
        self.assertEqual(len(self.rows("user_accounts")), 0)

    def test_a_zero_length_trial_grants_nothing(self):
        made = self.trial(trial_days=0)
        self.assertEqual(made["trial_expires_at"], NOW)
        self.assertEqual(made["trial_seconds_remaining"], 0.0)
        self.assertFalse(accounts.vip_status(self.state, made["sync_key"],
                                             now=NOW)["vip"])

    def test_the_device_id_primary_key_is_what_settles_a_first_sight(self):
        """Two requests that both believe a device is new cannot both keep an
        account: the second INSERT collides, and the row that survives is the
        winner's, with the winner's clock."""
        made = self.account()
        loser = accounts.create_account(self.conn, key="o" * 20)["account_id"]
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO device_trials(device_id, account_id,"
                              " first_seen_at, trial_expires_at) VALUES(?, ?, ?, ?)",
                              (DEVICE, loser, NOW, NOW + 30 * DAY))
        self.conn.rollback()
        resume = self.trial(now=NOW + DAY)
        self.assertFalse(resume["created"])
        self.assertEqual(resume["account_id"], made["account_id"])
        self.assertEqual(resume["trial_expires_at"], made["trial_expires_at"])

    def test_prune_keeps_the_trial_record_of_an_account_that_is_still_in_use(self):
        """A live account may be paid, so its expired trial row must not be collected
        — that row is the only thing standing between the device and a free second
        three days."""
        made = self.account(now=NOW - 400 * DAY)
        self.conn.execute("UPDATE user_accounts SET last_seen_at = ?", (NOW,))
        self.conn.commit()
        pruned = accounts.prune_accounts(self.conn, idle_days=365, now=NOW)
        self.assertEqual(pruned["trials_removed"], 0)
        self.assertEqual(len(self.rows("device_trials")), 1)
        self.assertEqual(self.trial(now=NOW)["trial_expires_at"],
                         made["trial_expires_at"])

    def test_prune_collects_a_trial_only_once_the_device_is_gone_entirely(self):
        made = self.account(now=NOW - 400 * DAY)
        self.conn.execute("DELETE FROM user_accounts WHERE id = ?",
                          (made["account_id"],))
        self.conn.commit()
        pruned = accounts.prune_accounts(self.conn, idle_days=365, now=NOW)
        self.assertEqual(len(self.rows("device_trials")), 0)
        self.assertEqual(pruned["trials_removed"], 1)

    def test_prune_of_an_idle_account_takes_its_expired_trial_in_the_same_pass(self):
        """The decision with a price on it, stated in `prune_accounts`: `idle_days`
        of total silence deletes the account, and the trial clock goes with it, so
        that device comes back and is treated as new. Asserting the number here keeps
        the price visible rather than implicit."""
        made = self.account(now=NOW - 400 * DAY)
        pruned = accounts.prune_accounts(self.conn, idle_days=365, now=NOW)
        self.assertEqual(len(self.rows("user_accounts")), 0)
        self.assertEqual(pruned["trials_removed"], 1)
        fresh = self.trial(now=NOW)
        self.assertTrue(fresh["created"])
        self.assertEqual(fresh["trial_expires_at"], NOW + 3 * DAY)

    def test_prune_leaves_an_unexpired_trial_of_a_deleted_account_for_the_report(
            self):
        made = self.account(now=NOW - DAY)
        self.conn.execute("DELETE FROM user_accounts WHERE id = ?",
                          (made["account_id"],))
        self.conn.commit()
        accounts.prune_accounts(self.conn, idle_days=365, now=NOW)
        self.assertEqual(len(self.rows("device_trials")), 1)


class ProfileLink(Fixture):
    def setUp(self):
        super().setUp()
        self.made = self.account()
        self.account_id = self.made["account_id"]
        # The lockout window is the one piece of this module that is deliberately
        # process-global state: `attempt_tracker` keeps its buckets between calls,
        # so a suite that burns wrong PINs would inherit somebody else's lock and
        # report `Locked` where it meant to prove `PINMismatch`. Every case gets its
        # own tracker, and its own high ceiling — the ceiling is not what these
        # cases are about, and the one that tests it constructs a tracker of three.
        self.tracker = accounts.AttemptTracker(max_failures=1_000)

    def link(self, *, now=NOW + DAY, pin=PIN, name="Ali Khan", phone=PHONE,
             **extra):
        extra.setdefault("tracker", self.tracker)
        return accounts.link_profile_with_pin(self.conn, self.account_id,
                                              name=name, phone=phone, pin=pin,
                                              now=now, **extra)

    def test_the_first_link_banks_the_remaining_trial_and_adds_one_day(self):
        later = NOW + DAY
        linked = self.link(now=later)
        self.assertTrue(linked["bonus_granted"])
        self.assertEqual(linked["vip_until"], self.made["trial_expires_at"] + DAY)
        self.assertEqual(self.column(self.account_id, "vip_until"),
                         self.made["trial_expires_at"] + DAY)
        self.assertEqual(self.column(self.account_id, "linked_at"), later)

    def test_a_lapsed_trial_is_extended_from_today_not_from_a_date_nobody_can_see(
            self):
        expired = NOW + 10 * DAY
        linked = self.link(now=expired)
        self.assertEqual(linked["vip_until"], expired + DAY)

    def test_the_bonus_is_granted_once_however_many_times_the_call_is_replayed(self):
        first = self.link()
        again = self.link()
        third = self.link()
        self.assertTrue(first["bonus_granted"])
        self.assertFalse(again["bonus_granted"])
        self.assertFalse(third["bonus_granted"])
        self.assertEqual(third["vip_until"], first["vip_until"])

    def test_the_pin_is_stored_salted_and_cost_tagged_never_as_plaintext(self):
        self.link()
        stored = self.column(self.account_id, "pin_hash")
        self.assertTrue(stored.startswith(accounts.PIN_HASH_PREFIX), stored)
        self.assertNotIn(PIN, stored)
        parts = stored[len(accounts.PIN_HASH_PREFIX):].split("$")
        self.assertEqual(len(parts), 3)
        self.assertEqual(int(parts[0]), accounts.PIN_ITERATIONS)
        self.assertEqual(len(parts[1]), 32)          # 128-bit salt, hex
        # two links of the same PIN are different digests, so one stolen table
        # cannot be searched with one precomputed list.
        other = accounts.create_account(self.conn, key="n" * 20)["account_id"]
        accounts.link_profile_with_pin(self.conn, other, name="Sana", phone=PHONE,
                                       pin=PIN, now=NOW)
        self.assertNotEqual(stored, self.column(other, "pin_hash"))

    def test_a_re_link_needs_the_pin_already_on_file(self):
        self.link(name="Ali")
        with self.assertRaises(accounts.PINMismatch):
            self.link(name="Somebody Else", pin="9999")
        self.assertEqual(self.column(self.account_id, "profile_name"), "Ali")

    def test_a_wrong_pin_is_answered_401_and_a_revoke_is_answered_like_any_read(self):
        self.assertEqual(accounts.PINMismatch.status, 401)
        self.link()
        accounts.revoke_account(self.conn, self.made["sync_key"], now=NOW)
        with self.assertRaises(accounts.UnknownAccount):
            self.link()

    def test_an_account_id_nobody_holds_is_refused_exactly_like_a_revoked_one(self):
        with self.assertRaises(accounts.UnknownAccount):
            accounts.link_profile_with_pin(self.conn, 999999, name="Ali",
                                           phone=PHONE, pin=PIN, now=NOW)

    def test_the_pin_bucket_burns_and_still_admits_the_owner(self):
        tracker = accounts.AttemptTracker(max_failures=2, window_seconds=600.0,
                                          lock_seconds=900.0)
        self.link(tracker=tracker)
        with self.assertRaises(accounts.PINMismatch):
            self.link(pin="0000", tracker=tracker)
        with self.assertRaises(accounts.Locked):
            self.link(pin="0000", tracker=tracker)
        bucket = accounts._pin_bucket(self.account_id)
        row = self.conn.execute("SELECT failures, locked_until FROM sync_key_attempts"
                                " WHERE bucket = ?", (bucket,)).fetchone()
        self.assertEqual(int(row[0]), 2)
        self.assertGreater(float(row[1]), NOW)
        self.assertNotIn(accounts.GLOBAL_BUCKET,
                         {r["bucket"] for r in
                          self.conn.execute("SELECT bucket FROM sync_key_attempts")},
                         "a wrong PIN is not evidence anybody guessed the key")
        # consulted on the failure path only: a burned window cannot deny the person
        # who actually knows their four digits, and a success forgets the window.
        self.assertEqual(self.link(pin=PIN, tracker=tracker)["name"], "Ali Khan")
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM sync_key_attempts WHERE bucket = ?", (bucket,)).fetchone())

    def test_a_pin_is_a_pin_and_not_a_sync_key_and_neither_is_the_other(self):
        """No column of this database can be spent as the other kind of credential:
        `pin_hash` holds a PBKDF2 digest, and a `sha256:` key digest must fail."""
        self.link()
        self.conn.execute("UPDATE user_accounts SET pin_hash = ? WHERE id = ?",
                          (accounts._hash_key(PIN), self.account_id))
        self.conn.commit()
        with self.assertRaises(accounts.PINMismatch):
            self.link()

    def test_an_absurd_iteration_count_is_refused_instead_of_computed(self):
        self.link()
        salt = "00" * 16
        for count in ("999999999999999", "12", "0", "-1", "abc"):
            self.conn.execute("UPDATE user_accounts SET pin_hash = ? WHERE id = ?",
                              ("%s%s$%s$%s" % (accounts.PIN_HASH_PREFIX, count,
                                               salt, "11" * 32),
                               self.account_id))
            self.conn.commit()
            with self.subTest(count=count):
                with self.assertRaises(accounts.PINMismatch):
                    self.link()

    def test_a_malformed_digest_never_verifies_anything(self):
        self.link()
        for junk in (None, "", "pbkdf2_sha256$", "pbkdf2_sha256$1000$aa",
                     "revoked:" + "e" * 64, 12345):
            self.conn.execute("UPDATE user_accounts SET pin_hash = ? WHERE id = ?",
                              (junk, self.account_id))
            self.conn.commit()
            with self.subTest(stored=junk):
                with self.assertRaises(accounts.PINMismatch):
                    self.link()

    def test_a_pin_that_is_not_four_to_eight_ascii_digits_is_refused(self):
        for junk in ("123", "123456789", "", "12 34", "abcd", "07a1", "1-2-3-4",
                     "١٢٣٤", "²³", None, 4721, 47.21, [], PIN + "\n" + PIN):
            with self.subTest(pin=junk):
                with self.assertRaises(accounts.WeakPIN):
                    accounts.link_profile_with_pin(self.conn, self.account_id,
                                                   name="Ali", phone=PHONE,
                                                   pin=junk, now=NOW)

    def test_a_phone_is_digits_only_and_two_countries_stay_two_numbers(self):
        self.assertEqual(accounts._normalize_phone(PHONE), "923001234567")
        self.assertEqual(accounts._normalize_phone("0300-1234567"), "03001234567")
        self.assertEqual(accounts._normalize_phone("(0300) 123 4567"), "03001234567")
        for junk in ("call me", "", "1234567", "1" * 17, None, 3001234567, []):
            with self.subTest(phone=junk):
                with self.assertRaises(accounts.WeakProfile):
                    accounts.link_profile_with_pin(self.conn, self.account_id,
                                                   name="Ali", phone=junk,
                                                   pin=PIN, now=NOW)

    def test_a_name_is_collapsed_clean_and_bounded(self):
        self.assertEqual(accounts._check_profile_name("  Ali\t\nKhan  "), "Ali Khan")
        # punctuation is somebody's name; an empty one is not, and this server does
        # not decide what a person may be called.
        self.assertEqual(accounts._check_profile_name(";;;"), ";;;")
        for junk in ("", "   ", "\x00\x01", "\n\n", None, 42, "n" * 61):
            with self.subTest(name=junk):
                with self.assertRaises(accounts.WeakProfile):
                    accounts._check_profile_name(junk)

    def test_control_characters_are_stripped_rather_than_refused_when_a_name_survives(
            self):
        linked = self.link(name="Ali\x00\nKhan")
        self.assertEqual(linked["name"], "Ali Khan")
        self.assertNotIn("\n", str(self.column(self.account_id, "profile_name")))

    def test_the_answer_is_four_fields_and_carries_no_secret(self):
        linked = self.link()
        self.assertEqual(sorted(linked), ["account_id", "bonus_granted", "linked",
                                          "name", "phone", "vip_until"])
        blob = json.dumps(linked, default=str)
        for forbidden in (PIN, accounts.PIN_HASH_PREFIX, '"pin_hash"', '"key_hash"',
                          '"sync_key"'):
            self.assertNotIn(forbidden, blob, forbidden)


class AccountSurfaceRoutes(Fixture):
    """`POST /api/v2/account/anonymous` and `POST /api/v2/account/profile-link`,
    driven through the same function the HTTP handler calls."""

    def test_anonymous_needs_no_credential_and_returns_the_key_once(self):
        answered = self.post("%s/anonymous" % P, {"device_id": DEVICE})
        self.assertEqual(answered[0], 201, answered)
        account = self.payload(answered)["account"]
        self.assertTrue(account["created"])
        self.assertIsInstance(account["sync_key"], str)
        self.assertEqual(account["trial_expires_at"],
                         account["first_seen_at"] + 3 * DAY)

    def test_anonymous_answers_the_clock_and_never_a_row_number(self):
        made = self.payload(self.post("%s/anonymous" % P, {"device_id": DEVICE}))
        resume = self.payload(self.post("%s/anonymous" % P, {"device_id": DEVICE}))
        self.assertEqual(sorted(made["account"]),
                         ["created", "first_seen_at", "reissued", "sync_key",
                          "trial_expires_at", "trial_seconds_remaining", "vip_until"])
        self.assertNotIn("account_id", json.dumps(made))
        self.assertNotIn("sync_key", resume["account"], "a resume must not re-serve")
        self.assertEqual(resume["account"]["trial_expires_at"],
                         made["account"]["trial_expires_at"])
        self.assertEqual(self.post("%s/anonymous" % P, {})[0], 400)

    def test_anonymous_ignores_a_trial_length_it_was_never_given(self):
        answered = self.post("%s/anonymous" % P, {"device_id": DEVICE,
                                                  "trial_days": 3650})
        account = self.payload(answered)["account"]
        self.assertEqual(account["trial_expires_at"],
                         account["first_seen_at"] + 3 * DAY)

    def test_anonymous_refuses_a_device_id_that_is_not_one(self):
        for junk in ("", "id with spaces", "x" * 200, None):
            answered = self.post("%s/anonymous" % P, {"device_id": junk})
            self.assertEqual(answered[0], 400, junk)
            self.assertIn(b'"invalid_params"', answered[2])

    def test_profile_link_is_authenticated_and_writes_onto_the_key_holders_row(self):
        made = self.payload(self.post("%s/anonymous" % P, {"device_id": DEVICE}))
        key = made["account"]["sync_key"]
        refused = self.post("%s/profile-link" % P, {"name": "Ali", "phone": PHONE,
                                                    "pin": PIN})
        self.assertEqual(refused[0], 401, refused)
        linked = self.post("%s/profile-link" % P, {"name": "Ali", "phone": PHONE,
                                                   "pin": PIN},
                           headers={"Authorization": "Bearer %s" % key})
        self.assertEqual(linked[0], 201, linked)
        profile = self.payload(linked)["profile"]
        self.assertEqual(profile, {"linked": True, "name": "Ali", "phone":
                                   "923001234567", "bonus_granted": True,
                                   "vip_until": made["account"]["vip_until"] + DAY})

    def test_profile_link_ignores_an_account_id_it_did_not_ask_for(self):
        key = self.payload(self.post("%s/anonymous" % P,
                                     {"device_id": DEVICE}))["account"]["sync_key"]
        other = accounts.create_account(self.conn, key="t" * 20)["account_id"]
        answered = self.post("%s/profile-link" % P,
                             {"name": "Ali", "phone": PHONE, "pin": PIN,
                              "account_id": other},
                             headers={"Authorization": "Bearer %s" % key})
        self.assertEqual(answered[0], 201, answered)
        self.assertIsNone(self.column(other, "linked_at"))

    def test_no_account_response_carries_a_pin_a_digest_or_a_phone_of_someone_else(
            self):
        key = self.payload(self.post("%s/anonymous" % P,
                                     {"device_id": DEVICE}))["account"]["sync_key"]
        headers = {"Authorization": "Bearer %s" % key}
        bodies = [("anonymous",
                   self.post("%s/anonymous" % P, {"device_id": OTHER_DEVICE})),
                  ("link",
                   self.post("%s/profile-link" % P, {"name": "Ali", "phone": PHONE,
                                                     "pin": PIN}, headers=headers)),
                  ("wrong pin",
                   self.post("%s/profile-link" % P, {"name": "Ali", "phone": PHONE,
                                                     "pin": "0000"},
                             headers=headers))]
        for label, answered in bodies:
            text = answered[2].decode("utf-8")
            for forbidden in ('"pin"', '"pin_hash"', accounts.PIN_HASH_PREFIX,
                              '"key_hash"', '"account_id"', "Traceback"):
                self.assertNotIn(forbidden, text, "%s: %s" % (label, forbidden))
        # the caller's own phone may come back; the PIN it was guard-railed with may
        # not, and neither may anything a guesser could work offline against.
        for label, answered in bodies[1:]:
            self.assertNotIn(PIN, answered[2].decode("utf-8"), label)

    def test_a_bad_profile_is_a_400_and_a_wrong_pin_is_a_401(self):
        key = self.payload(self.post("%s/anonymous" % P,
                                     {"device_id": DEVICE}))["account"]["sync_key"]
        headers = {"Authorization": "Bearer %s" % key}
        self.assertEqual(self.post("%s/profile-link" % P, {"name": "",
                                                            "phone": PHONE,
                                                            "pin": PIN},
                                   headers=headers)[0], 400)
        self.assertEqual(self.post("%s/profile-link" % P, {"name": "Ali",
                                                            "phone": PHONE,
                                                            "pin": "12"},
                                   headers=headers)[0], 400)
        accounts.link_profile_with_pin(self.state, 1, name="Ali", phone=PHONE,
                                       pin=PIN, now=NOW)
        refused = self.post("%s/profile-link" % P, {"name": "Ali", "phone": PHONE,
                                                     "pin": "9999"}, headers=headers)
        self.assertEqual(refused[0], 401, refused)
        self.assertIn(b'"unauthorised"', refused[2])

    def test_the_payer_may_ask_only_about_itself(self):
        made = self.account()
        answer = payments.entitlement(self.state, made["sync_key"], now=NOW)
        self.assertEqual(sorted(answer), ["pending", "vip", "vip_until"])
        self.assertTrue(answer["vip"])
        self.assertFalse(answer["pending"])
        # A key this server never minted, and one it minted and destroyed, take the
        # identical path: `accounts._authenticate`'s miss, which raises rather than
        # answering. Returning `{"vip": False, ...}` for a stranger would be worse
        # than refusing — it would tell a guesser that the shape of the question is
        # right and only the answer is no, and it would make a revoked account look
        # like a paying one whose clock ran out.
        with self.assertRaises(accounts.UnknownAccount):
            payments.entitlement(self.state, "k" * 20, now=NOW)
        second = accounts.create_account(self.state, key="p" * 20)
        accounts.revoke_account(self.state, second["sync_key"], now=NOW)
        with self.assertRaises(accounts.UnknownAccount):
            payments.entitlement(self.state, second["sync_key"], now=NOW)


class MerchantSecret(Fixture):
    def test_an_unset_secret_authorises_nobody(self):
        self.assertIsNone(os.environ.get(payments.MERCHANT_SECRET_ENV))
        self.assertFalse(payments.merchant_authorized(MERCHANT))
        self.assertFalse(payments.merchant_authorized(MERCHANT, env={}))
        self.assertFalse(payments.merchant_authorized("", env={
            payments.MERCHANT_SECRET_ENV: MERCHANT}))

    def test_the_comparison_is_the_whole_header_value_or_nothing(self):
        env = {payments.MERCHANT_SECRET_ENV: MERCHANT}
        self.assertTrue(payments.merchant_authorized(MERCHANT, env=env))
        self.assertTrue(payments.merchant_authorized(" %s " % MERCHANT, env=env))
        self.assertFalse(payments.merchant_authorized(MERCHANT + "x", env=env))
        self.assertFalse(payments.merchant_authorized(MERCHANT[:-1], env=env))
        for junk in (None, 1234, b"bytes", [], {}):
            self.assertFalse(payments.merchant_authorized(junk, env=env), junk)

    def test_the_header_is_read_by_its_documented_name(self):
        env = {payments.MERCHANT_SECRET_ENV: MERCHANT}
        self.assertTrue(payments.verify_merchant_header(
            {payments.MERCHANT_SECRET_HEADER: MERCHANT}, env=env))
        self.assertFalse(payments.verify_merchant_header(
            {"Authorization": "Bearer %s" % TOKEN}, env=env))
        self.assertFalse(payments.verify_merchant_header({}, env=env))
        self.assertFalse(payments.verify_merchant_header(None, env=env))


class RelayCredits(Fixture):
    """`payments.sms_webhook` — and the three conditions an automatic credit needs."""

    def test_money_that_arrives_first_is_filed_and_spent_by_the_claim_that_follows(
            self):
        filed = self.relay()
        self.assertTrue(filed["recorded"])
        self.assertEqual(filed["reason"], "recorded")
        self.assertFalse(filed["approved"])
        unclaimed = payments.unclaimed_credits(self.conn)
        self.assertEqual([row["tid"] for row in unclaimed], [JAZZ_TID])
        self.assertEqual(unclaimed[0]["amount_pkr"], 200)
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.assertEqual(claim["status"], payments.STATUS_APPROVED, claim)
        self.assertEqual(payments.unclaimed_credits(self.conn), [])
        self.assertTrue(accounts.vip_status(self.conn, made["sync_key"])["vip"])

    def test_a_claim_that_arrives_first_is_credited_by_the_callback_that_follows(
            self):
        """The ordinary ordering: the payer submits the form, then the SMS lands."""
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="easypaisa",
                                        tid=EASY_TID, catalog_path=self.catalog)
        self.assertEqual(claim["status"], payments.STATUS_PENDING)
        answered = self.relay(gateway="easypaisa", tid=EASY_TID, amount=200)
        self.assertTrue(answered["approved"], answered)
        self.assertEqual(answered["reason"], "credited")
        self.assertTrue(answered["matched"])
        self.assertFalse(payments.has_pending(self.conn, made["account_id"]))

    def test_the_relay_is_named_as_the_reviewer_and_the_audit_names_no_tid(self):
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.relay()
        audit = payments.audit_for(self.conn, claim["payment_id"])
        self.assertEqual(audit[0]["reviewer"], payments.RELAY_REVIEWER)
        self.assertIn("relay confirmed PKR 200", audit[0]["note"])
        self.assertNotIn(JAZZ_TID, json.dumps(audit))
        self.assertEqual(audit[0]["new_vip_until"],
                         audit[0]["prior_vip_until"] + 30 * DAY)

    def test_one_tid_buys_exactly_one_membership_however_many_accounts_ask(self):
        first = self.account()
        payments.submit_payment(self.conn, first["account_id"], plan="vip_monthly",
                                method="jazzcash", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        credited = self.relay()
        self.assertTrue(credited["approved"])
        until = self.column(first["account_id"], "vip_until")
        replay = self.relay()
        self.assertFalse(replay["approved"])
        self.assertEqual(replay["reason"], "already-credited")
        thief = self.trial(OTHER_DEVICE, now=NOW + DAY)
        stolen = payments.submit_payment(self.conn, thief["account_id"],
                                         plan="vip_monthly", method="jazzcash",
                                         tid=JAZZ_TID, catalog_path=self.catalog)
        self.assertEqual(stolen["status"], payments.STATUS_PENDING, stolen)
        self.assertTrue(self.column(thief["account_id"], "vip_until") <=
                        thief["vip_until"])
        self.assertFalse(payments.unclaimed_credits(self.conn))
        replayed = self.relay()
        self.assertEqual(replayed["reason"], "already-credited")
        self.assertEqual(self.column(first["account_id"], "vip_until"), until)

    def test_a_partial_payment_buys_nothing(self):
        made = self.account()
        payments.submit_payment(self.conn, made["account_id"], plan="vip_yearly",
                                method="jazzcash", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        answer = self.relay(amount=50)
        self.assertFalse(answer["approved"])
        self.assertEqual(answer["reason"], "amount-mismatch")
        self.assertTrue(payments.has_pending(self.conn, made["account_id"]))
        until = self.column(made["account_id"], "vip_until")
        self.assertEqual(until, made["trial_expires_at"])

    def test_a_partial_payment_filed_before_the_claim_is_checked_against_the_price(
            self):
        self.relay(amount=50)
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_yearly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.assertEqual(claim["status"], payments.STATUS_PENDING, claim)
        self.assertEqual(len(payments.unclaimed_credits(self.conn)), 1)

    def test_a_relay_that_names_the_wrong_network_credits_nothing(self):
        made = self.account()
        payments.submit_payment(self.conn, made["account_id"], plan="vip_monthly",
                                method="easypaisa", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        answer = self.relay(gateway="jazzcash", tid=JAZZ_TID, amount=200)
        self.assertFalse(answer["approved"])
        self.assertEqual(answer["reason"], "gateway-mismatch")
        self.assertTrue(payments.has_pending(self.conn, made["account_id"]))

    def test_an_amount_that_is_not_whole_pkr_is_not_a_payment(self):
        made = self.account()
        payments.submit_payment(self.conn, made["account_id"], plan="vip_monthly",
                                method="jazzcash", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        for junk in (None, "", 250.5, "two fifty", True, [], {}, -200, "0x10"):
            with self.subTest(amount=junk):
                answer = self.relay(amount=junk)
                self.assertFalse(answer["approved"], junk)
                self.assertEqual(answer["reason"], "no-amount", junk)

    def test_a_string_amount_the_sms_printed_verbatim_is_still_pkr(self):
        made = self.account()
        payments.submit_payment(self.conn, made["account_id"], plan="vip_monthly",
                                method="jazzcash", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        self.assertTrue(self.relay(amount="200")["approved"])

    def test_a_gateway_or_tid_the_ledger_does_not_recognise_is_refused(self):
        for gateway in ("westernunion", "", None, "JazzCash!", "bank"):
            with self.subTest(gateway=gateway):
                with self.assertRaises(payments.InvalidPayment):
                    payments.sms_webhook(self.conn, gateway=gateway, tid=JAZZ_TID,
                                         amount=200)
        for tid in ("", "12", "1" * 41, "has space", None, "982314567a",
                    "98231456", 12.5, [], {}):
            with self.subTest(tid=tid):
                with self.assertRaises(payments.InvalidPayment):
                    payments.sms_webhook(self.conn, gateway="jazzcash", tid=tid,
                                         amount=200)
        self.assertEqual(len(self.rows("verified_incoming_tids")), 0)

    def test_a_json_number_tid_is_the_same_reference_as_the_sms_printed_it(self):
        """A relay that forwards `9823145671` as a JSON number rather than a string
        has sent the same ten digits, and refusing it would lose a real payment to a
        formatting accident."""
        answer = self.relay(tid=int(JAZZ_TID))
        self.assertTrue(answer["recorded"])
        self.assertEqual([row["tid"] for row in
                          self.rows("verified_incoming_tids")], [JAZZ_TID])

    def test_a_gateway_spelling_with_case_and_padding_is_the_same_gateway(self):
        answer = self.relay(gateway="  JazzCash ", tid=JAZZ_TID, amount=200)
        self.assertTrue(answer["recorded"])
        self.assertEqual([row["gateway"] for row in
                          self.rows("verified_incoming_tids")], ["jazzcash"])

    def test_a_record_older_than_a_week_is_not_a_credits_worth_making(self):
        self.relay(now=NOW)
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog,
                                        now=NOW + payments.VERIFIED_TID_MAX_AGE_SECONDS
                                        + DAY)
        self.assertEqual(claim["status"], payments.STATUS_PENDING, claim)

    def test_a_replay_cannot_make_a_stale_record_fresh(self):
        self.relay(now=NOW)
        again = self.relay(now=NOW + payments.VERIFIED_TID_MAX_AGE_SECONDS + DAY)
        self.assertFalse(again["recorded"])
        self.assertEqual(again["reason"], "already-recorded")
        stored = self.conn.execute("SELECT verified_at FROM"
                                   " verified_incoming_tids").fetchone()[0]
        self.assertEqual(stored, NOW)
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog,
                                        now=NOW + DAY * 8)
        self.assertEqual(claim["status"], payments.STATUS_PENDING)

    def test_the_response_is_machine_words_and_no_payment_artifact(self):
        answer = self.relay()
        self.assertEqual(sorted(answer), ["approved", "matched", "reason",
                                          "recorded", "verified"])
        blob = json.dumps(answer)
        self.assertNotIn(JAZZ_TID, blob)
        self.assertNotIn("200", blob)
        self.assertNotIn("account_id", blob)

    def test_a_state_file_without_the_relay_table_fails_toward_the_human(self):
        """`verified_incoming_tids` is new, and a database that predates it must not
        turn an ordinary claim into a 500. The filing path has nowhere to put a
        record and says the ledger is unavailable; the direct-match path never needed
        the table and still credits, because the callback itself is the proof."""
        made = self.account()
        self.conn.execute("DROP TABLE verified_incoming_tids")
        self.conn.commit()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.assertEqual(claim["status"], payments.STATUS_PENDING, claim)
        self.assertEqual(payments.unclaimed_credits(self.conn), [])
        direct = self.relay()
        self.assertTrue(direct["approved"], direct)
        with self.assertRaises(payments.PaymentError):
            self.relay(tid=EASY_TID)

    def test_a_relay_credit_survives_losing_the_delete_but_not_the_next_read(self):
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.relay()
        self.conn.execute("INSERT OR REPLACE INTO verified_incoming_tids(gateway,"
                          " tid, amount_pkr, verified_at) VALUES(?, ?, ?, ?)",
                          ("jazzcash", JAZZ_TID, 200, NOW))
        self.conn.commit()
        self.assertTrue(payments._claim_already_credited(self.conn, JAZZ_TID))
        again = payments._credit_from_relay(self.conn, payment_id=claim["payment_id"],
                                            gateway="jazzcash", reference=JAZZ_TID,
                                            paid=200, now=NOW)
        self.assertFalse(again["approved"])
        self.assertEqual(again["reason"], "already-credited")


class WebhookMount(Fixture):
    """`viewer.DashboardHandler._merchant_relay`, driven by a handler that is just
    a header mapping, a body and two capture sinks.

    The stub's headers are a plain dict, so the exact spellings the mount asks for
    (`X-Merchant-Secret`, `Content-Length`) are what it looks up — a real
    `http.client.HTTPMessage` is case-insensitive, which is why the mount passes
    `self.headers` through rather than reading names itself.
    """

    class Stub:
        def __init__(self, body=b"", headers=None, checker=None):
            self.headers = dict(headers or {})
            self.rfile = io.BytesIO(body)
            self.sent = []
            self.checker = checker

        def send_json(self, data, status=200, extra_headers=None):
            self.sent.append((status, "application/json", json.dumps(data)))

        def send_bytes(self, data, content_type="", status=200, extra_headers=None):
            self.sent.append((status, content_type,
                              data.decode("utf-8", "replace")
                              if isinstance(data, bytes) else str(data)))

        @property
        def answered(self):
            # exactly one answer per request — a mount that writes twice puts two
            # statuses on one socket, which is a bug and not a detail.
            self.checker.assertEqual(len(self.sent), 1, self.sent)
            return self.sent[0]

    def call(self, body=b"", headers=None):
        stub = self.Stub(body, headers, checker=self)
        viewer.DashboardHandler._merchant_relay(stub, payments.WEBHOOK_PATH)
        return stub

    def signed(self, body, secret=MERCHANT):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        headers = {"Content-Length": str(len(raw))}
        if secret is not None:
            headers[payments.MERCHANT_SECRET_HEADER] = secret
        return self.call(raw, headers)

    def test_the_route_is_the_one_the_owner_documented(self):
        self.assertEqual(payments.WEBHOOK_PATH, "/api/v2/payment/sms-webhook")

    def test_the_mount_is_a_public_route_and_not_an_operator_one(self):
        path = payments.WEBHOOK_PATH
        self.assertNotIn(path, viewer.OPERATOR_ONLY_ROUTES)
        self.assertFalse(path.startswith(viewer.OPERATOR_ONLY_PREFIXES))
        self.assertFalse(accounts_api.is_account(path))   # so it cannot ride there
        self.assertTrue(api_v2.is_v2(path))               # so it must precede that

    def test_no_secret_no_answer_and_the_body_is_never_read(self):
        body = json.dumps({"gateway": "jazzcash", "tid": JAZZ_TID,
                           "amount": 200}).encode("utf-8")
        stub = self.Stub(body, {"Content-Length": str(len(body))})
        viewer.DashboardHandler._merchant_relay(stub, payments.WEBHOOK_PATH)
        status, content_type, text = stub.sent[0]
        self.assertEqual(status, 401)
        self.assertIn("application/problem+json", content_type)
        self.assertIn('"unauthorised"', text)
        self.assertEqual(stub.rfile.tell(), 0, "the mount read a body it never needed")

    def test_a_wrong_secret_and_no_secret_answer_identically(self):
        missing = self.call(b"", {"Content-Length": "0"}).answered
        wrong = self.signed(b'{"gateway": "jazzcash"}', secret="not-it").answered
        self.assertEqual(missing[0], 401)
        self.assertEqual(wrong[0], 401)
        first, second = json.loads(missing[2]), json.loads(wrong[2])
        self.assertEqual({k: first[k] for k in ("status", "code", "instance",
                                                "title")},
                         {k: second[k] for k in ("status", "code", "instance",
                                                 "title")})

    def test_a_deployment_that_forgot_the_secret_credits_nothing(self):
        """The unset-variable case, with the header supplied by the caller: this is
        the failure that a default secret would have turned into free VIP."""
        status = self.signed(json.dumps({"gateway": "jazzcash", "tid": JAZZ_TID,
                                         "amount": 200}),
                             secret=None).answered[0]
        self.assertEqual(status, 401)
        self.assertEqual(self.rows("verified_incoming_tids"), [])

    def test_the_secret_in_the_environment_opens_the_route_and_nothing_else(self):
        with mock.patch.dict("os.environ", {payments.MERCHANT_SECRET_ENV: MERCHANT}):
            status, content_type, text = self.signed(json.dumps(
                {"gateway": "jazzcash", "tid": JAZZ_TID, "amount": 200})).answered
            self.assertEqual(status, 200, text)
            self.assertIn("application/json", content_type)
            answer = json.loads(text)
            self.assertEqual(sorted(answer), ["approved", "matched", "reason",
                                              "recorded", "verified"])
            self.assertTrue(answer["recorded"])
        self.assertEqual(len(self.rows("verified_incoming_tids")), 1)

    def test_a_body_that_is_not_a_json_object_is_a_400_after_the_secret_passes(self):
        with mock.patch.dict("os.environ", {payments.MERCHANT_SECRET_ENV: MERCHANT}):
            for junk in (b"not json", b"[1,2,3]", b'"a string"', b'{"a": 1',
                         b"{", b"12"):
                with self.subTest(body=junk):
                    status, content_type, text = self.signed(junk).answered
                    self.assertEqual(status, 400, junk)
                    self.assertIn("application/problem+json", content_type)

    def test_a_nonsense_payment_shape_is_a_400_rather_than_a_500(self):
        with mock.patch.dict("os.environ", {payments.MERCHANT_SECRET_ENV: MERCHANT}):
            for body in ({"gateway": "paypal", "tid": JAZZ_TID, "amount": 200},
                         {"gateway": "jazzcash", "tid": "no", "amount": 200},
                         {"gateway": "jazzcash"}):
                with self.subTest(body=body):
                    status, _type, text = self.signed(json.dumps(body)).answered
                    self.assertEqual(status, 400, text)
                    self.assertIn('"invalid_params"', text)

    def test_an_empty_body_records_nothing_and_says_so(self):
        with mock.patch.dict("os.environ", {payments.MERCHANT_SECRET_ENV: MERCHANT}):
            status, _type, text = self.signed(b"").answered
            self.assertEqual(status, 400, text)     # no gateway at all -> refused

    def test_the_mount_credits_a_pending_claim_end_to_end(self):
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.assertEqual(claim["status"], payments.STATUS_PENDING)
        with mock.patch.dict("os.environ", {payments.MERCHANT_SECRET_ENV: MERCHANT}):
            answer = json.loads(self.signed(json.dumps(
                {"gateway": "jazzcash", "tid": JAZZ_TID, "amount": 200})).answered[2])
        self.assertTrue(answer["approved"])
        self.assertEqual(payments.payment(self.conn, claim["payment_id"])["status"],
                         payments.STATUS_APPROVED)
        self.assertTrue(accounts.vip_status(self.conn, made["sync_key"])["vip"])

    def test_the_mount_never_answers_a_sentence_about_anybody_s_money(self):
        with mock.patch.dict("os.environ", {payments.MERCHANT_SECRET_ENV: MERCHANT}):
            text = self.signed(json.dumps({"gateway": "jazzcash", "tid": JAZZ_TID,
                                          "amount": 200})).answered[2]
        for forbidden in (JAZZ_TID, '"200"', ": 200", '"amount"', '"account_id"',
                          '"tid"'):
            self.assertNotIn(forbidden, text, forbidden)


class OperatorSurface(Fixture):
    """`admin_panel` is where a relay-confirmed payment with no claim has to be
    visible: the operator is the only person who can explain it."""

    def page(self):
        data = admin_panel.screen_payments(self.state)
        return data, admin_panel.render_payments_page(data, {})

    def test_the_screen_carries_the_unclaimed_money_and_the_page_prints_it(self):
        self.relay(gateway="easypaisa", tid=EASY_TID, amount=200)
        data, page = self.page()
        self.assertEqual([row["tid"] for row in data["unclaimed"]], [EASY_TID])
        self.assertIn("Relay-confirmed, unclaimed", page)
        self.assertIn(EASY_TID, page)                 # loopback may print a TID
        self.assertIn(payments.RELAY_REVIEWER, page)
        self.assertIn("relay", data["note"])

    def test_a_spent_record_leaves_the_list_because_a_credit_consumes_it(self):
        made = self.account()
        self.relay()
        payments.submit_payment(self.conn, made["account_id"], plan="vip_monthly",
                                method="jazzcash", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        data, page = self.page()
        self.assertEqual(data["unclaimed"], [])
        self.assertIn("nothing to show", page)

    def test_the_pending_queue_shows_the_relay_approval_of_its_own_row(self):
        made = self.account()
        claim = payments.submit_payment(self.conn, made["account_id"],
                                        plan="vip_monthly", method="jazzcash",
                                        tid=JAZZ_TID, catalog_path=self.catalog)
        self.relay()
        data, _page = self.page()
        self.assertEqual(data["pending_count"], 0)
        outcomes = {row["payment_id"]: row["status"] for row in data["recent"]}
        self.assertEqual(outcomes[claim["payment_id"]], payments.STATUS_APPROVED)

    def test_the_account_surface_still_sees_no_ledger_row(self):
        made = self.account()
        payments.submit_payment(self.conn, made["account_id"], plan="vip_monthly",
                                method="jazzcash", tid=JAZZ_TID,
                                catalog_path=self.catalog)
        self.relay()
        answer = payments.entitlement(self.state, made["sync_key"], now=NOW)
        self.assertEqual(answer["pending"], False)
        blob = json.dumps(answer)
        for forbidden in (JAZZ_TID, "vip_monthly", "radd-relay", '"tid"'):
            self.assertNotIn(forbidden, blob, forbidden)


if __name__ == "__main__":
    unittest.main(verbosity=2)
