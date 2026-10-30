#!/usr/bin/env python3
"""The pass ladder is data, it is priced once, and a refusal writes nothing.

`Fast_Fetch/engagement.py` sells three passes — a day for ₨20 / 30 coins, a weekend
for ₨50 / 70, a 30-day VIP for ₨250 / 200 — and until this suite, the shape of that
ladder lived in two places that had to be kept in step by a human:

  * the spender computed a pass's expiry with `if plan == "weekend"`, *after*
    `spend_coins` had already debited the wallet. A tier the branch did not know was
    therefore discovered once the coins were gone: charged, and no pass.
  * the panel published a price by walking its own `(plan, coin knob, pkr knob)`
    tuple list, while the spender read `PASS_LADDER` directly. Two mappings of one
    settings row, agreeing only because nobody had edited one of them.

So this suite proves four things, and every one of them is a behaviour, not a style:

  1. **A tier says how it expires, in its own data** (`expiry_rule` →
     `engagement.EXPIRY_RULES`), and no comparison anywhere in the module tests a
     plan against a tier name. That is checked structurally with `ast`, so it cannot
     be re-broken by the next "quick" special case.
  2. **A new tier is an edit to `PASS_LADDER` alone** — a fourth tier supplied to
     `tier_expiry`/`redeem_pass` prices, spends and expires with no code change.
  3. **A tier whose data is wrong refuses and writes NOTHING** — balance unchanged,
     not one `coin_ledger` row, no token minted. This is the behaviour
     `Fast_Fetch/test_admin_panel.py` already proves for the settings form, extended
     to the money path.
  4. **The price a phone is shown is the price the server charges**, because both
     read `engagement.resolve_ladder(values)`: this suite asserts the panel's public
     body, the resolver, and the actual debit are one number for a repriced tier.

Money type is part of the contract: every price and every coin cost leaves this
module an `int`, never a `float`. A pass price is a whole number of rupees
(`payments.amount_pkr` is an `INTEGER` column and `_validated` refuses decimals),
and a float money field is how a ladder silently becomes wrong by a rupee.

Offline: a `tempfile` user-state DB, an in-process connection, no socket, no
network, no catalog, and never the live
`/home/ubuntu/radd-stream-data/user_state.db`.

    python3 -S Fast_Fetch/test_engagement_ladder.py
"""
from __future__ import annotations

import ast
import inspect
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts       # noqa: E402
import admin_panel    # noqa: E402
import engagement     # noqa: E402
import redact         # noqa: E402

SECRET = "ladder-suite-signing-secret"
PKT = timezone(timedelta(hours=5))          # Asia/Karachi, no DST

#: Everything a tier must carry. A missing key is a ladder that cannot be sold,
#: which is why `resolve_ladder` and `redeem_pass` refuse rather than default.
REQUIRED_TIER_KEYS = ("pkr", "coins", "expiry_rule", "coin_setting", "pkr_setting")


def epoch_at(iso_local: str) -> float:
    """Epoch seconds for a Pakistani wall-clock string, host zone irrelevant."""
    return datetime.strptime(f"{iso_local}+0500",
                             "%Y-%m-%dT%H:%M:%S%z").timestamp()


def defaults_row(**overrides) -> dict:
    """A full `app_remote_config` reading, as `_read_monetization` returns it (TEXT
    columns, so every value is a string), with the operator's edits applied."""
    row = {key: str(default) for key, _label, _kind, default
           in admin_panel.MONETIZATION_FIELDS}
    for key, value in overrides.items():
        row[key] = str(value)
    return row


class LadderFixture(unittest.TestCase):
    """One temp user-state DB, one funded account, one open connection."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "user_state.db"
        env = mock.patch.dict("os.environ", {"RADD_USER_STATE_DB": str(self.state)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.conn = engagement.connect(self.state)
        self.addCleanup(self.conn.close)
        self.account_id = accounts.create_account(
            self.conn, key="l" * 20)["account_id"]

    def fund(self, amount=10_000):
        engagement.grant_coins(self.conn, self.account_id, amount=amount,
                               reason="admin_grant", source="admin", ref="seed")
        return engagement.coin_balance(self.conn, self.account_id)

    def rows(self):
        with sqlite3.connect(self.state) as check:
            return check.execute(
                "SELECT COUNT(*) FROM coin_ledger WHERE account_id = ?",
                (self.account_id,)).fetchone()[0]


class TierDataTests(LadderFixture):
    """Each tier's own row must be enough to sell it."""

    def test_every_tier_carries_a_price_a_coin_cost_and_an_expiry_rule(self):
        for name, spec in engagement.PASS_LADDER.items():
            for key in REQUIRED_TIER_KEYS:
                self.assertIn(key, spec, f"tier {name!r} is missing {key}")
            self.assertIs(type(spec["pkr"]), int, name)
            self.assertIs(type(spec["coins"]), int, name)
            self.assertGreater(spec["coins"], 0, f"{name}: a free pass is a bug")
            self.assertIn(spec["expiry_rule"], engagement.EXPIRY_RULES,
                          f"tier {name!r} names a rule the module does not have")

    def test_every_tiers_knob_is_a_real_settings_field_at_the_shipped_price(self):
        """The ladder's `coin_setting`/`pkr_setting` names are not decoration.

        A tier may only name a knob the operator can actually save, and the stored
        default must be the number the ledger ships — otherwise the first read of a
        fresh row publishes one price and the spender charges another."""
        fields = admin_panel._FIELD_BY_KEY
        for name, spec in engagement.PASS_LADDER.items():
            for setting_key, money_key in (("coin_setting", "coins"),
                                           ("pkr_setting", "pkr")):
                knob = spec[setting_key]
                self.assertIn(knob, fields, f"tier {name!r} names a knob that is"
                                            " not in the settings form")
                shipped = spec[money_key]
                stored_default = fields[knob][3]
                self.assertEqual(int(stored_default), shipped,
                                 f"{knob} defaults to {stored_default} while the "
                                 f"ladder charges {shipped} for {name}")

    def test_no_computation_in_this_module_branches_on_a_tier_name(self):
        """The law, checked as syntax rather than as prose.

        `redeem_pass` used to hold `if plan == "weekend"`, and the reason that is
        forbidden is not tidiness: a branch on a name is a tier that can be added to
        the data and silently missed by the code, after the coins are spent. An
        `ast` walk is the only way to keep that true, because a docstring is allowed
        to *describe* the bug it prevents."""
        tree = ast.parse(inspect.getsource(engagement))
        tiers = set(engagement.PASS_LADDER)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for comparator in node.comparators:
                if (isinstance(comparator, ast.Constant)
                        and comparator.value in tiers):
                    offenders.append((node.lineno, comparator.value))
            # `plan == "weekend"` puts the name on the left too.
            if (isinstance(node.left, ast.Constant) and node.left.value in tiers):
                offenders.append((node.lineno, node.left.value))
        self.assertEqual(offenders, [],
                         f"tier names compared at lines {offenders}")

    def test_adding_a_tier_is_an_edit_to_the_data_alone(self):
        """A fourth tier supplied as data redeems, prices and expires with no code."""
        self.fund()
        extra = dict(engagement.PASS_LADDER)
        extra["week"] = {"pkr": 120, "coins": 120,
                         "coin_setting": "coin_redeem_day",
                         "pkr_setting": "pass_day_pkr",
                         "expiry_rule": "after_seconds",
                         "duration_seconds": 7 * engagement.DAY_SECONDS}
        moment = epoch_at("2026-01-05T09:00:00")
        self.assertEqual(
            engagement.tier_expiry("week", moment, ladder=extra),
            float(int(moment + 7 * engagement.DAY_SECONDS)))
        redeem = engagement.redeem_pass(self.conn, self.account_id, plan="week",
                                        pass_secret=SECRET, now=moment, ladder=extra)
        self.assertEqual(redeem["cost"], 120)
        self.assertEqual(redeem["balance"], 10_000 - 120)
        self.assertEqual(redeem["expiry_rule"], "after_seconds")
        self.assertEqual(redact.parse_vip_pass(redeem["pass"], SECRET, now=moment + 1),
                         redeem["expires_at"])

    def test_the_shipped_ladder_is_not_rewritten_by_resolving_a_price(self):
        engagement.resolve_ladder(defaults_row(coin_redeem_day=5, pass_day_pkr=9))
        self.assertEqual(engagement.PASS_LADDER["day"]["coins"], 30)
        self.assertEqual(engagement.PASS_LADDER["day"]["pkr"], 20)


class RefusalWritesNothingTests(LadderFixture):
    """The one failure a spend cannot have: coins gone, no pass."""

    def assert_refused(self, *, plan, ladder, exc, moment=None, **kwargs):
        balance_before = self.fund()
        rows_before = self.rows()
        with self.assertRaises(exc) as caught:
            engagement.redeem_pass(self.conn, self.account_id, plan=plan,
                                   pass_secret=SECRET,
                                   now=moment or epoch_at("2026-01-05T09:00:00"),
                                   ladder=ladder, **kwargs)
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id),
                         balance_before, str(caught.exception))
        self.assertEqual(self.rows(), rows_before,
                         "a refusal adds no ledger row at all")

    def test_a_tier_naming_an_unknown_expiry_rule_refuses_and_writes_nothing(self):
        broken = dict(engagement.PASS_LADDER)
        broken["moon"] = {"pkr": 10, "coins": 10,
                          "coin_setting": "coin_redeem_day",
                          "pkr_setting": "pass_day_pkr",
                          "expiry_rule": "when_the_moon_is_right"}
        self.assert_refused(plan="moon", ladder=broken, exc=engagement.BadLadder)

    def test_a_tier_naming_no_expiry_rule_at_all_refuses(self):
        broken = dict(engagement.PASS_LADDER)
        broken["dangling"] = {"pkr": 1, "coins": 1,
                              "coin_setting": "coin_redeem_day",
                              "pkr_setting": "pass_day_pkr"}
        self.assert_refused(plan="dangling", ladder=broken, exc=engagement.BadLadder)

    def test_an_after_seconds_tier_without_a_duration_refuses(self):
        broken = dict(engagement.PASS_LADDER)
        broken["endless"] = {"pkr": 5, "coins": 5,
                             "coin_setting": "coin_redeem_day",
                             "pkr_setting": "pass_day_pkr",
                             "expiry_rule": "after_seconds"}
        self.assert_refused(plan="endless", ladder=broken, exc=engagement.BadLadder)

    def test_a_tier_with_a_zero_or_non_numeric_duration_refuses(self):
        for bad in (0, -3600, "a day", None):
            broken = dict(engagement.PASS_LADDER)
            broken["rotten"] = {"pkr": 5, "coins": 5,
                                "coin_setting": "coin_redeem_day",
                                "pkr_setting": "pass_day_pkr",
                                "expiry_rule": "after_seconds",
                                "duration_seconds": bad}
            self.assert_refused(plan="rotten", ladder=broken,
                                exc=engagement.BadLadder)

    def test_an_unknown_plan_refuses_before_any_spend(self):
        self.assert_refused(plan="fortnight", ladder=engagement.PASS_LADDER,
                            exc=engagement.UnknownPlan)

    def test_a_tier_without_a_usable_coin_cost_refuses(self):
        broken = dict(engagement.PASS_LADDER)
        broken["gratis"] = {"pkr": 0, "coins": 0,
                            "coin_setting": "coin_redeem_day",
                            "pkr_setting": "pass_day_pkr",
                            "expiry_rule": "after_seconds",
                            "duration_seconds": 60}
        self.assert_refused(plan="gratis", ladder=broken, exc=engagement.BadAmount)

    def test_an_unsigned_request_refuses_before_any_spend(self):
        """No secret, no pass — and the wallet is untouched, so a typo in a caller
        cannot cost anyone anything."""
        balance = self.fund()
        with self.assertRaises(engagement.EngagementError):
            engagement.redeem_pass(self.conn, self.account_id, plan="day",
                                   pass_secret="", now=epoch_at("2026-01-05T09:00:00"))
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), balance)
        self.assertEqual(self.rows(), 1)

    def test_a_short_wallet_refuses_and_writes_nothing(self):
        """The guarded insert was already all-or-nothing; this pins that the new
        ordering did not move the debit ahead of the check."""
        self.fund(5)
        with self.assertRaises(engagement.InsufficientCoins):
            engagement.redeem_pass(self.conn, self.account_id, plan="monthly_vip",
                                   pass_secret=SECRET,
                                   now=epoch_at("2026-01-05T09:00:00"))
        self.assertEqual(engagement.coin_balance(self.conn, self.account_id), 5)
        self.assertEqual(self.rows(), 1)


class ExpiryRuleTests(LadderFixture):
    """The rules the data names, resolved to the instant the token carries."""

    def test_the_day_tier_expires_one_full_day_later(self):
        moment = epoch_at("2026-01-07T21:30:00")
        self.assertEqual(
            engagement.tier_expiry("day", moment),
            float(int(moment + engagement.DAY_SECONDS)))

    def test_the_monthly_tier_expires_thirty_days_later(self):
        moment = epoch_at("2026-01-07T21:30:00")
        self.assertEqual(
            engagement.tier_expiry("monthly_vip", moment),
            float(int(moment + 30 * engagement.DAY_SECONDS)))

    def test_the_weekend_tier_expires_at_the_next_local_monday_midnight(self):
        friday = epoch_at("2026-01-09T18:00:00")
        expires = datetime.fromtimestamp(
            engagement.tier_expiry("weekend", friday, tz="Asia/Karachi"), PKT)
        self.assertEqual(expires.weekday(), 0)
        self.assertEqual((expires.hour, expires.minute, expires.second), (0, 0, 0))
        # A Monday buy rolls forward, never to a past instant.
        monday = epoch_at("2026-01-12T08:00:00")
        later = datetime.fromtimestamp(
            engagement.tier_expiry("weekend", monday, tz="Asia/Karachi"), PKT)
        self.assertGreater(later.timestamp(), monday)
        self.assertEqual(later.weekday(), 0)

    def test_an_expiry_is_whole_seconds_because_that_is_what_the_token_stores(self):
        moment = epoch_at("2026-01-09T18:00:00") + 0.4
        for plan in engagement.PASS_LADDER:
            expires = engagement.tier_expiry(plan, moment, tz="Asia/Karachi")
            self.assertIs(type(expires), float, plan)
            self.assertEqual(expires, float(int(expires)), plan)

    def test_tier_expiry_refuses_a_plan_the_ladder_does_not_name(self):
        with self.assertRaises(engagement.UnknownPlan):
            engagement.tier_expiry("fortnight", epoch_at("2026-01-05T09:00:00"))


class PublishedPriceIsChargedPriceTests(LadderFixture):
    """One resolver behind the body a phone reads and the debit the server makes."""

    def charged(self, plan, values=None, moment=None):
        self.fund()
        return engagement.redeem_pass(
            self.conn, self.account_id, plan=plan, pass_secret=SECRET,
            now=moment or epoch_at("2026-01-05T09:00:00"), values=values)

    def test_the_default_row_publishes_and_charges_the_shipped_ladder(self):
        row = defaults_row()
        published = admin_panel._engagement_public(row)
        for plan, spec in engagement.PASS_LADDER.items():
            self.assertEqual(published["passes"][plan]["coins"], spec["coins"], plan)
            self.assertEqual(published["passes"][plan]["pkr"], spec["pkr"], plan)
            self.assertEqual(published["wallet"]["redeem_coin_costs"][plan],
                             spec["coins"], plan)
            redeem = self.charged(plan, values=row)
            self.assertEqual(redeem["cost"], spec["coins"], plan)

    def test_repricing_a_tier_moves_the_published_price_and_the_debit_together(self):
        """The defect this closes: the panel read its own tuple list while the
        spender read `PASS_LADDER`, so a cheaper day pass could be published without
        ever being charged. Now both are one call to `resolve_ladder`."""
        row = defaults_row(coin_redeem_day=12, pass_day_pkr=33,
                           coin_redeem_monthly=250, pass_monthly_vip_pkr=400)
        published = admin_panel._engagement_public(row)
        self.assertEqual(published["passes"]["day"]["coins"], 12)
        self.assertEqual(published["passes"]["day"]["pkr"], 33)
        self.assertEqual(published["wallet"]["redeem_coin_costs"]["day"], 12)
        self.assertEqual(published["passes"]["monthly_vip"]["pkr"], 400)
        cheap = self.charged("day", values=row)
        self.assertEqual(cheap["cost"], 12)
        self.assertEqual(cheap["balance"], 10_000 - 12)
        vip = self.charged("monthly_vip", values=row)
        self.assertEqual(vip["cost"], 250, "the other tier reprices independently")

    def test_the_panel_body_is_the_ledgers_projection_for_every_plan(self):
        """`_engagement_public` must not add, drop or rename a tier of its own."""
        published = admin_panel._engagement_public(defaults_row())
        self.assertEqual(set(published["passes"]), set(engagement.PASS_LADDER))
        self.assertEqual(set(published["wallet"]["redeem_coin_costs"]),
                         set(engagement.PASS_LADDER))
        self.assertEqual(published["passes"], engagement.passes_projection(
            engagement.resolve_ladder(defaults_row())))

    def test_a_zero_coin_paste_is_the_shipped_cost_and_never_a_free_pass(self):
        row = defaults_row(coin_redeem_day=0)
        self.assertEqual(admin_panel._engagement_public(row)["passes"]["day"]["coins"],
                         30)
        self.assertEqual(self.charged("day", values=row)["cost"], 30)

    def test_an_unusable_paste_answers_the_shipped_price_not_a_negative_one(self):
        """`_validated` refuses these at the form, so this is the belt for a row
        edited outside it: the spender must never charge -30 coins, which would be
        a grant disguised as a purchase."""
        for bad in ("twelve", "", None, -50, "0"):
            row = defaults_row(coin_redeem_day=bad)
            cost = engagement.resolve_ladder(row)["day"]["coins"]
            self.assertEqual(cost, 30, repr(bad))
            self.assertEqual(self.charged("day", values=row)["cost"], 30, repr(bad))

    def test_a_zero_pkr_price_is_a_deliberate_free_tier_not_a_sentinel(self):
        """The asymmetry, on purpose: 0 coins means "use the default" because a
        free pass would be a bug, while 0 rupees means "this tier is free today"
        because that is an act of the operator's will. `_validated` stores 0 for
        both kinds, so only the reading differs."""
        row = defaults_row(pass_day_pkr=0)
        self.assertEqual(admin_panel._engagement_public(row)["passes"]["day"]["pkr"], 0)
        self.assertEqual(engagement.resolve_ladder(row)["day"]["pkr"], 0)
        self.assertEqual(engagement.resolve_ladder(row)["day"]["coins"], 30)

    def test_no_price_or_coin_count_leaves_the_module_as_a_float(self):
        ladder = engagement.resolve_ladder(defaults_row())
        numbers = {f"passes.{plan}.{key}": value
                   for plan, row in engagement.passes_projection(ladder).items()
                   for key, value in row.items() if key in ("pkr", "coins")}
        numbers.update({f"wallet.{plan}": value for plan, value in
                        engagement.remote_view()["wallet"]["redeem_coin_costs"].items()})
        numbers.update({f"shipped.{plan}.{key}": value for plan, row
                        in engagement.PASS_LADDER.items()
                        for key, value in row.items() if key in ("pkr", "coins")})
        numbers.update({f"charged.{plan}": self.charged(plan)["cost"]
                        for plan in engagement.PASS_LADDER})
        for name, value in sorted(numbers.items()):
            self.assertIs(type(value), int,
                          f"{name} is {type(value).__name__}: money is a whole "
                          "number of rupees or coins, never a float")

    def test_the_published_ladder_names_the_rule_behind_every_expiry(self):
        """A client that reads `expiry_rule` must be able to tell a duration tier
        from a weekend tier without guessing from a `None` duration."""
        published = engagement.remote_view()["passes"]
        self.assertEqual(published["day"]["expiry_rule"], "after_seconds")
        self.assertEqual(published["weekend"]["expiry_rule"], "local_weekend_end")
        self.assertIsNone(published["weekend"]["duration_seconds"],
                          "a weekend has no fixed length; the rule is the answer")


class LadderAccessorTests(unittest.TestCase):
    """`pass_ladder()` is the older name for one table, not a second table."""

    def test_pass_ladder_and_resolve_ladder_are_the_same_numbers(self):
        self.assertEqual(engagement.pass_ladder(), engagement.resolve_ladder())
        row = defaults_row(coin_redeem_weekend=64)
        self.assertEqual(engagement.pass_ladder(row)["weekend"]["coins"], 64)


def main() -> int:
    with tempfile.TemporaryDirectory() as probe:
        with mock.patch.dict("os.environ", {"RADD_USER_STATE_DB": probe}):
            print(f"[.] ladder fixture RADD_USER_STATE_DB = "
                  f"{engagement.default_db_path()}")
    return unittest.main(exit=False, verbosity=2).result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
