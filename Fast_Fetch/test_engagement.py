#!/usr/bin/env python3
"""
Fast_Fetch/test_engagement.py — proves the structural invariants the engagement
pillars promise, and nothing about the running server.
════════════════════════════════════════════════════════════════════════════════════════
This runs against a **fixture** `RADD_USER_STATE_DB` inside a `tempfile` directory and
prints the resolved path on the first line, so "the live
`/home/ubuntu/radd-stream-data/user_state.db` was not touched" is visible in the run,
not asserted in prose. It imports only `accounts`, `engagement`, `redact` — never
`viewer` / `catalog_v2` / `api_v2` — so it stays light enough to run while the shared
box is loaded, and it never issues a request or opens the catalog. Stdlib only.

Run: `python3 -S Fast_Fetch/test_engagement.py`
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts      # noqa: E402
import engagement    # noqa: E402
import redact        # noqa: E402

SECRET = "unit-test-signing-secret"
PKT = timezone(timedelta(hours=5))    # Asia/Karachi is UTC+5 with no DST


def epoch_at(iso_local: str) -> float:
    """Epoch seconds for a Pakistani wall-clock string, independent of the host zone."""
    return datetime.strptime(f"{iso_local}+0500",
                             "%Y-%m-%dT%H:%M:%S%z").timestamp()


class EngagementFixture(unittest.TestCase):
    """Shared fixture: a temp user-state DB, one live account, one open connection."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "user_state.db"
        self.env = mock.patch.dict("os.environ",
                                   {"RADD_USER_STATE_DB": str(self.state)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.conn = engagement.connect(self.state)
        self.addCleanup(self.conn.close)
        self.account_id = accounts.create_account(
            self.conn, key="z" * 20)["account_id"]

    # ── 1. append-only, enforced by the database not by a docstring ──────────

    def test_the_coin_ledger_rejects_update_and_delete(self):
        engagement.grant_coins(self.conn, self.account_id, amount=10,
                               reason="admin_grant", source="admin", ref="seed")
        with self.assertRaises(sqlite3.Error):
            self.conn.execute("UPDATE coin_ledger SET delta = 999 WHERE account_id = ?",
                              (self.account_id,))
        with self.assertRaises(sqlite3.Error):
            self.conn.execute("DELETE FROM coin_ledger WHERE account_id = ?",
                              (self.account_id,))
        # the refusal is structural: the row is exactly as it was granted
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 10)

    def test_a_correction_is_a_new_compensating_row_not_an_edit(self):
        engagement.grant_coins(self.conn, self.account_id, amount=50,
                               reason="rewarded_ad", idempotency_key="over-credit")
        # undo the mistake the append-only way: a fresh -50 claw-back row, never an
        # edit of the original credit
        engagement.spend_coins(self.conn, self.account_id, amount=50,
                               reason="refund", ref="reverses over-credit")
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 0)
        rows = engagement.ledger(self.conn, self.account_id)
        self.assertEqual(len(rows), 2)          # both rows survive; history is intact
        self.assertEqual({r["reason"] for r in rows}, {"rewarded_ad", "refund"})

    # ── 2. the balance is derived, never stored ──────────────────────────────

    def test_there_is_no_balance_column_and_the_balance_is_the_sum(self):
        cols = {row["name"] for row in
                self.conn.execute("PRAGMA table_info(coin_ledger)")}
        self.assertNotIn("balance", cols)
        engagement.grant_coins(self.conn, self.account_id, amount=7,
                               reason="admin_grant", source="admin")
        engagement.grant_coins(self.conn, self.account_id, amount=3,
                               reason="streak_day", source="server")
        direct = self.conn.execute(
            "SELECT COALESCE(SUM(delta), 0) FROM coin_ledger WHERE account_id = ?",
            (self.account_id,)).fetchone()[0]
        self.assertEqual(int(direct), 10)
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), int(direct))

    # ── 3. no coin is created by a client claim ──────────────────────────────

    def test_a_client_source_is_refused_outright(self):
        with self.assertRaises(engagement.BadSource):
            engagement.grant_coins(self.conn, self.account_id, amount=1000,
                                   reason="rewarded_ad", source="client")
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 0)

    def test_an_unknown_account_cannot_hold_coins(self):
        with self.assertRaises(engagement.UnknownAccount):
            engagement.grant_coins(self.conn, 999999, amount=5,
                                   reason="admin_grant", source="admin")

    def test_a_non_whole_or_non_positive_amount_is_refused(self):
        for bad in (0, -5, "ten"):
            with self.assertRaises(engagement.BadAmount):
                engagement.grant_coins(self.conn, self.account_id, amount=bad,
                                       reason="admin_grant", source="admin")

    # ── 4. grants are idempotent ─────────────────────────────────────────────

    def test_a_retried_callback_credits_once(self):
        first = engagement.grant_coins(self.conn, self.account_id, amount=5,
                                       reason="rewarded_ad", idempotency_key="cb-42")
        replay = engagement.grant_coins(self.conn, self.account_id, amount=5,
                                        reason="rewarded_ad", idempotency_key="cb-42")
        self.assertTrue(first["granted"])
        self.assertTrue(replay["idempotent"])
        self.assertEqual(replay["balance"], 5)
        self.assertEqual(len(engagement.ledger(self.conn, self.account_id)), 1)

    # ── 5. you cannot spend what you do not have (atomically) ────────────────

    def test_a_spend_above_balance_is_refused_and_writes_nothing(self):
        engagement.grant_coins(self.conn, self.account_id, amount=10,
                               reason="admin_grant", source="admin")
        before = len(engagement.ledger(self.conn, self.account_id))
        with self.assertRaises(engagement.InsufficientCoins):
            engagement.spend_coins(self.conn, self.account_id, amount=11)
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 10)
        self.assertEqual(len(engagement.ledger(self.conn, self.account_id)), before)

    def test_a_spend_of_exactly_the_balance_is_allowed(self):
        engagement.grant_coins(self.conn, self.account_id, amount=10,
                               reason="admin_grant", source="admin")
        engagement.spend_coins(self.conn, self.account_id, amount=10)
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 0)

    # ── 6. rewarded ads are capped per day ───────────────────────────────────

    def test_rewarded_grants_stop_at_the_daily_cap(self):
        noon = epoch_at("2026-01-06T12:00:00")
        for i in range(engagement.REWARDED_DAILY_CAP):
            engagement.grant_coins(self.conn, self.account_id, amount=5,
                                   reason="rewarded_ad", idempotency_key=f"cb-{i}",
                                   now=noon)
        with self.assertRaises(engagement.RewardedCapReached):
            engagement.grant_coins(self.conn, self.account_id, amount=5,
                                   reason="rewarded_ad", idempotency_key="cb-overflow",
                                   now=noon)
        # a streak grant on the same day is not a rewarded ad and is not capped
        engagement.grant_coins(self.conn, self.account_id, amount=30,
                               reason="streak_day", now=noon)

    # ── 7. the day bucket: a Pakistani user at 02:00 (the asked-about case) ───

    def test_the_day_bucket_rolls_over_at_the_boundary_not_at_midnight(self):
        prev = "2026-01-04"
        day = "2026-01-05"
        # 01:59, 02:01, 03:59 local on Jan 5 all belong to the Jan 4 bucket
        for wall in ("2026-01-05T01:59:00", "2026-01-05T02:01:00",
                     "2026-01-05T03:59:00"):
            self.assertEqual(engagement._day_bucket(epoch_at(wall)), prev, wall)
        # 04:00 and later belong to Jan 5
        for wall in ("2026-01-05T04:00:00", "2026-01-05T04:01:00",
                     "2026-01-05T23:59:00"):
            self.assertEqual(engagement._day_bucket(epoch_at(wall)), day, wall)

    def test_a_two_am_session_does_not_double_credit_or_reset(self):
        late = epoch_at("2026-01-06T02:00:00")     # 02:00 PKT Jan 6 -> Jan 5 bucket
        tick = engagement.record_engagement_day(self.conn, self.account_id, now=late)
        self.assertEqual(tick["bucket"], "2026-01-05")
        self.assertEqual(tick["current_streak"], 1)
        # the same evening checked again an hour later is the same bucket: no grant
        later = engagement.record_engagement_day(
            self.conn, self.account_id, now=epoch_at("2026-01-06T03:30:00"))
        self.assertEqual(later["status"], "same_day_noop")
        self.assertEqual(later["current_streak"], 1)
        # it does not become a second "Day 1" either
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id),
                         engagement.STREAK_GRANTS_COINS[1])

    # ── 8. streak state machine: advance, gap resets, best is monotone ───────

    def test_consecutive_days_advance_and_a_missed_day_resets(self):
        base = epoch_at("2026-01-05T12:00:00")
        day = lambda n: base + timedelta(days=n).total_seconds()  # noqa: E731
        first = engagement.record_engagement_day(self.conn, self.account_id, now=day(0))
        self.assertEqual((first["status"], first["current_streak"]), ("started", 1))
        second = engagement.record_engagement_day(self.conn, self.account_id, now=day(1))
        self.assertEqual((second["status"], second["current_streak"]), ("advanced", 2))
        fourth = engagement.record_engagement_day(self.conn, self.account_id, now=day(3))
        self.assertEqual((fourth["status"], fourth["current_streak"]), ("reset", 1))
        self.assertEqual(fourth["best_streak"], 2)      # best survives the reset

    def test_streak_milestone_grants_fire_once_per_bucket(self):
        base = epoch_at("2026-01-05T12:00:00")
        for i in range(3):
            engagement.record_engagement_day(
                self.conn, self.account_id, now=base + i * 86400)
        # Day 1 (10) + Day 3 (30) = 40 coins, and each fired once
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 40)
        streak_grants = [r for r in engagement.ledger(self.conn, self.account_id)
                         if r["reason"] == "streak_day"]
        self.assertEqual(len(streak_grants), 2)

    def test_the_day_seven_milestone_mints_a_signed_pass(self):
        base = epoch_at("2026-01-05T12:00:00")
        result = None
        for i in range(engagement.STREAK_PASS_DAY):
            result = engagement.record_engagement_day(
                self.conn, self.account_id, now=base + i * 86400, pass_secret=SECRET)
        self.assertEqual(result["current_streak"], 7)
        self.assertIsNotNone(result["pass"])
        self.assertEqual(redact.parse_vip_pass(result["pass"], SECRET,
                                               now=result["pass_expires_at"] - 1),
                         result["pass_expires_at"])
        self.assertIsNone(redact.parse_vip_pass(result["pass"], SECRET,
                                                 now=result["pass_expires_at"] + 1))

    # ── 9. ad cadence is enforced server-side, and 0 never means unlimited ───

    def test_a_second_preroll_inside_the_window_is_denied(self):
        t0 = epoch_at("2026-01-05T12:00:00")
        first = engagement.ad_grant(self.conn, self.account_id, slot="preroll", now=t0)
        soon = engagement.ad_grant(self.conn, self.account_id, slot="preroll",
                                   now=t0 + 60)
        self.assertTrue(first["allow"])
        self.assertFalse(soon["allow"])
        self.assertEqual(soon["next_eligible_at"],
                         t0 + engagement.CAPS_DEFAULT["ad_preroll_min_gap_minutes"] * 60)
        later = engagement.ad_grant(
            self.conn, self.account_id, slot="preroll",
            now=t0 + 25 * 60)
        self.assertTrue(later["allow"])

    def test_a_zero_cap_resolves_to_the_default_never_to_unlimited(self):
        caps = engagement.resolve_caps(
            {"ad_preroll_min_gap_minutes": 0, "ad_app_open_min_gap_minutes": -5})
        self.assertEqual(caps["ad_preroll_min_gap_minutes"], 25)
        self.assertEqual(caps["ad_app_open_min_gap_minutes"], 240)
        # even an explicit 0 override cannot make the server deny-beatable
        t0 = epoch_at("2026-01-05T12:00:00")
        engagement.ad_grant(self.conn, self.account_id, slot="preroll", now=t0,
                            caps={"ad_preroll_min_gap_minutes": 0})
        second = engagement.ad_grant(self.conn, self.account_id, slot="preroll",
                                     now=t0 + 60, caps={"ad_preroll_min_gap_minutes": 0})
        self.assertFalse(second["allow"])

    def test_the_native_card_fires_once_every_n_posters(self):
        caps = {"ad_native_card_every_posters": 3}
        allows = [engagement.ad_grant(self.conn, self.account_id, slot="native_card",
                                      caps=caps)["allow"] for _ in range(6)]
        self.assertEqual(allows, [False, False, True, False, False, True])

    # ── 10. §A no-deception: no cash-out path, published costs, 250 monthly ──

    def test_no_table_has_a_cash_out_or_withdrawal_field(self):
        forbidden = ("withdraw", "cashout", "cash_out", "payout", "redeem_cash",
                     "bank", "iban")
        sql = "".join(str(row["sql"] or "") for row in self.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table'"
            " AND name IN ('coin_ledger', 'streak_state', 'ad_cadence_state')")).lower()
        for word in forbidden:
            self.assertNotIn(word, sql, word)

    def test_the_ladder_and_costs_are_published_with_monthly_at_250(self):
        view = engagement.remote_view()
        self.assertEqual(view["passes"]["monthly_vip"]["pkr"], 250)   # plan doc :46
        self.assertEqual(view["passes"]["day"]["pkr"], 20)
        self.assertEqual(view["passes"]["weekend"]["pkr"], 50)
        self.assertTrue(view["wallet"]["rewarded_daily_cap"] > 0)
        self.assertEqual(view["cadence"]["ad_preroll_min_gap_minutes"], 25)
        # costs are published for every plan the client could redeem
        for plan in engagement.PASS_LADDER:
            self.assertIn(plan, view["passes"])
            self.assertIn(plan, view["wallet"]["redeem_coin_costs"])

    def test_redeeming_a_pass_spends_coins_and_mints_a_verifiable_capability(self):
        engagement.grant_coins(self.conn, self.account_id, amount=100,
                               reason="admin_grant", source="admin")
        now = epoch_at("2026-01-05T12:00:00")
        redeem = engagement.redeem_pass(self.conn, self.account_id, plan="day",
                                        pass_secret=SECRET, now=now)
        self.assertEqual(redeem["balance"],
                         100 - engagement.PASS_LADDER["day"]["coins"])
        self.assertEqual(redact.parse_vip_pass(redeem["pass"], SECRET, now=now + 1),
                         redeem["expires_at"])
        # a wrong secret forges nothing
        self.assertIsNone(redact.parse_vip_pass(redeem["pass"], "other-secret", now=now))
        # the spend is on the ledger, so the deduction is auditable
        spends = [r for r in engagement.ledger(self.conn, self.account_id)
                  if r["reason"] == "redeem_pass"]
        self.assertEqual(len(spends), 1)

    def test_redeeming_without_enough_coins_mints_nothing(self):
        with self.assertRaises(engagement.InsufficientCoins):
            engagement.redeem_pass(self.conn, self.account_id, plan="monthly_vip",
                                   pass_secret=SECRET)

    def test_the_weekend_pass_expires_at_the_next_local_monday_midnight(self):
        engagement.grant_coins(self.conn, self.account_id, amount=100,
                               reason="admin_grant", source="admin")
        friday = epoch_at("2026-01-09T18:00:00")   # a Friday, PKT
        redeem = engagement.redeem_pass(self.conn, self.account_id, plan="weekend",
                                        pass_secret=SECRET, now=friday)
        expires_local = datetime.fromtimestamp(redeem["expires_at"], PKT)
        self.assertEqual(expires_local.weekday(), 0)     # Monday 00:00 local
        self.assertEqual((expires_local.hour, expires_local.minute), (0, 0))

    # ── schema lifecycle (mirrors the accounts.py idempotency contract) ──────

    def test_ensure_schema_is_idempotent_and_additive(self):
        result = engagement.ensure_schema(self.conn)
        self.conn.commit()
        self.assertEqual(result["schema_version"], engagement.SCHEMA_VERSION)
        self.assertEqual(result["added_columns"], [])     # nothing to add on a fresh run
        # re-running on a DB that already has rows changes nothing and loses nothing
        engagement.grant_coins(self.conn, self.account_id, amount=4,
                               reason="admin_grant", source="admin")
        engagement.ensure_schema(self.conn)
        self.conn.commit()
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 4)
        self.assertEqual(engagement.schema_version(self.conn), engagement.SCHEMA_VERSION)

    def test_the_fixture_is_the_temp_file_not_the_live_db(self):
        resolved = engagement.default_db_path()
        self.assertEqual(str(resolved), str(self.state))
        self.assertNotIn("radd-stream-data", str(resolved))


def main() -> int:
    # Print the resolved fixture path first, so the run itself proves the live
    # user-state DB was never the target.
    with tempfile.TemporaryDirectory() as probe:
        with mock.patch.dict("os.environ", {"RADD_USER_STATE_DB": probe}):
            print(f"[.] engagement fixture RADD_USER_STATE_DB = {engagement.default_db_path()}")
    return unittest.main(exit=False, verbosity=2).result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
