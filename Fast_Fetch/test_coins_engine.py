#!/usr/bin/env python3
"""Offline tests for the coins HTTP surface — `GET /coins`, `GET /coins/caps`,
`GET /coins/history`, `POST /coins/earn`, `POST /coins/redeem` on `accounts_api.py`.

`engagement.py` owned the wallet long before this surface existed: the append-only
`coin_ledger` with its `RAISE(ABORT)` triggers, the derived `SUM(delta)` balance, the
earning caps, the streak ladder, the pass prices and the one `resolve_ladder` that turns
an operator row into both. So these tests do not judge an engine — they judge the edge,
and specifically the three ways an edge around a wallet goes wrong:

* it starts carrying its own numbers (a second balance, price list or cap constant),
  which is the defect JOB B removed from the pricer and the one rule `admin_panel`'s
  `_INT_MAX` mirror exists to keep from ever coming back;
* it lets a caller name whose wallet it is, or how many coins it earned;
* it refuses a request after writing part of it.

Every case therefore asserts on the ledger rows as well as the reply: a 400, a 402, a
403 and a replay all leave `coin_ledger` byte-for-byte as they found it, and the coin
figure a route reports is the figure `engagement` wrote — never a figure this file
agrees with it about.

Two refusals are the interesting ones because they refuse the brief rather than a bad
client, and both are measurements of this host, not caution: `rewarded_ad` needs the ad
network's own completion callback and the only completion signal here is client-reported
`usage_stats` telemetry, which `engagement.py` calls analytics and not money; and
`watch_time` measures playback this server never sees, because `/api/v1/stream` is a
*redirect* and the bytes leave from the source's own host.

    python3 -S Fast_Fetch/test_coins_engine.py
"""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import accounts            # noqa: E402
import accounts_api        # noqa: E402
import admin_panel         # noqa: E402
import engagement          # noqa: E402
import redact              # noqa: E402

SECRET = "test-install-secret"
P = accounts_api.PREFIX
COINS = f"{P}/coins"
DAY_SECONDS = 86_400.0
#: Fixture words that name a source. They may not appear in any body this surface
#: emits; the scan that proves it (`test_no_body_on_the_wallet_names_an_account_or_a_source`)
#: asserts on a field it expects to be there first, so an empty haystack cannot go green.
NEEDLES = ("katmoviehd", "vegamovies", "rareanimes")
VISIBLE = "movie:in:1000:sample"
ADULT = "movie:in:1001:bad katmoviehd title"
#: Rewards this server will not sell are refused by name; this one is the brief's, and
#: the refusal is the assertion.
REFUSED_PLAN = "unlock_1080p"
#: "use the fixture's own key". Distinct from `key=None` — "send no credential at all",
#: which is how the 401 cases are asked — and from a real key, which is how somebody
#: else's wallet is reached.
_DEFAULT = object()


def catalog_fixture(path) -> Path:
    """A catalog the route can hold open read-only, the way `viewer.py` does."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE cat_works (work_key TEXT, is_18_plus INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO cat_works VALUES (?, 0)", (VISIBLE,))
    conn.execute("INSERT INTO cat_works VALUES (?, 1)", (ADULT,))
    conn.commit()
    conn.close()
    return Path(path)


class Wallet(unittest.TestCase):
    """Shared fixture: one temp state DB, one temp catalog, one enrolled account."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "user_state.db"
        self.catalog = catalog_fixture(Path(self.tmp.name) / "cat.db")
        with closing(accounts.connect(self.state)) as conn:
            accounts.ensure_schema(conn)
        # The wallet's own tables, installed the way the first request would install
        # them: `engagement.connect` is the owner's documented entry point and runs the
        # DDL plus the append-only triggers, so a fixture that skipped it would be
        # asserting against a database no live host has ever had.
        with closing(engagement.connect(self.state)):
            pass
        # A private limiter: `accounts_api.LIMITER` is process-global, so a suite that
        # burns wrong keys would inherit somebody else's lock and answer 429 where it
        # meant to prove 401. The lockout is not what any case here is about.
        limiter = mock.patch.object(accounts_api, "LIMITER",
                                    accounts.AttemptTracker(max_failures=1_000))
        limiter.start()
        self.addCleanup(limiter.stop)
        self.key = self.enroll()
        self.account_id = self.own_id(self.key)

    # ── the wire ──────────────────────────────────────────────────────────
    def get(self, path, query=None, headers=None, key=_DEFAULT):
        return accounts_api.route_get(
            path, query or {}, db_path=self.state, catalog_path=self.catalog,
            secret=SECRET, headers=self.auth(self.key if key is _DEFAULT else key,
                                             headers))

    def post(self, path, body=None, headers=None, key=_DEFAULT):
        return accounts_api.route_post(
            path, body or {}, db_path=self.state, catalog_path=self.catalog,
            secret=SECRET, headers=self.auth(self.key if key is _DEFAULT else key,
                                             headers))

    def auth(self, key=None, headers=None):
        if headers is not None:
            return headers
        return {} if key is None else {"Authorization": f"Bearer {key}"}

    def enroll(self):
        made = self.post(P, {}, key=None)
        assert made[0] == 201, made
        return json.loads(made[2])["account"]["sync_key"]

    def own_id(self, key) -> int:
        return accounts.authenticate(self.state, key,
                                     tracker=accounts_api.LIMITER)["account_id"]

    def body(self, answered) -> dict:
        self.assertIsNotNone(answered)
        status, content_type, raw = answered
        self._status = status
        self._type = content_type
        return json.loads(raw.decode("utf-8")) if raw else {}

    def code(self, answered) -> str:
        """The declared problem code of a refusal (`api_v2.problem`'s shape)."""
        self.assertEqual(answered[1].split(";")[0], "application/problem+json", answered)
        return json.loads(answered[2].decode("utf-8"))["code"]

    # ── the ledger, read straight off the file ────────────────────────────
    def rows(self, account_id=None):
        """Every `coin_ledger` row, oldest first, with `typeof(delta)` beside it.

        The type travels because 'money is a whole number' is a column property, not a
        JSON one: a `float` delta would survive every assertion on a reply body and only
        show its rounding here.
        """
        with closing(sqlite3.connect(str(self.state))) as conn:
            conn.row_factory = sqlite3.Row
            sql = ("SELECT id, account_id, delta, reason, ref, source, created_at,"
                   " typeof(delta) AS delta_type FROM coin_ledger")
            if account_id is None:
                return [dict(row) for row in conn.execute(sql + " ORDER BY id")]
            return [dict(row) for row in
                    conn.execute(sql + " WHERE account_id = ? ORDER BY id",
                                 (int(account_id),))]

    def wallet_state(self) -> tuple:
        """`(row_count, sum_of_deltas)` for the whole ledger — what a refusal must not
        move. `SUM` is taken in SQL, not in Python, so a float credit cannot be made to
        look like an integer by an accidental `int()` in the test."""
        with closing(sqlite3.connect(str(self.state))) as conn:
            row = conn.execute("SELECT COUNT(*), COALESCE(SUM(delta), 0),"
                               " COALESCE(SUM(delta * 1.0), 0.0) FROM coin_ledger"
                               ).fetchone()
        return (int(row[0]), int(row[1]), float(row[2]))

    def settings(self, **values):
        """Write the operator's `app_remote_config` row, on a handle that may write.

        The route holds the catalog *read-only* (`_catalog_handle` opens `mode=ro`), so
        the row has to be seeded from outside it — which is also how the real deployment
        works: only `/admin` saves a setting, the API only reads one.
        """
        unknown = sorted(key for key in values if key not in admin_panel._FIELD_BY_KEY)
        assert not unknown, unknown
        with closing(sqlite3.connect(str(self.catalog))) as conn:
            admin_panel._ensure_monetization(conn)
            for key, value in values.items():
                conn.execute(f"UPDATE app_remote_config SET {key} = ?", (value,))
            conn.commit()

    def grant(self, amount, *, reason="admin_grant", key=None, idempotency=None):
        """Credit the wallet the way the owner allows, to set up a spend."""
        with closing(engagement.connect(self.state)) as conn:
            return engagement.grant_coins(
                conn, key or self.account_id, amount=amount, reason=reason,
                source="admin", ref="test-topup", idempotency_key=idempotency)

    def spend(self, amount, *, reason="refund", idempotency=None):
        """Debit the wallet through the owner, for the `typeof(delta)` and
        derived-sum cases — `grant_coins` refuses a negative amount on purpose, so a
        compensating row has to come from `spend_coins`."""
        with closing(engagement.connect(self.state)) as conn:
            return engagement.spend_coins(conn, self.account_id, amount=amount,
                                          reason=reason, idempotency_key=idempotency)

    def published_engagement(self) -> dict:
        """The `engagement` block `remote-config` would put on the wire for this exact
        catalog row, read through the owner rather than restated here."""
        with closing(sqlite3.connect(str(self.catalog))) as conn:
            return admin_panel.remote_config(conn)["engagement"]

    def bucket(self, offset_seconds=0.0) -> str:
        """The civil-day bucket the streak uses, `offset_seconds` from now — the same
        two private helpers the enforcement path calls, so a fixture cannot invent a
        day the ledger would not count as adjacent."""
        moment = time.time() + offset_seconds
        return engagement._day_bucket(moment, engagement.STREAK_TZ_DEFAULT,
                                      engagement.DAY_BOUNDARY_HOUR_DEFAULT)

    def yesterday_bucket(self) -> str:
        """Yesterday, defined as 'the bucket an instant one second before today's
        bucket start falls in' — which is exactly one day back whatever the clock reads,
        unlike `now - 24h`, which can be two days back across a rollover."""
        today = self.bucket()
        start = engagement._bucket_start_epoch(
            today, engagement.STREAK_TZ_DEFAULT, engagement.DAY_BOUNDARY_HOUR_DEFAULT)
        return engagement._day_bucket(start - 1.0, engagement.STREAK_TZ_DEFAULT,
                                      engagement.DAY_BOUNDARY_HOUR_DEFAULT)

    def claim(self, reason="daily_login", **extra):
        return self.post(f"{COINS}/earn", {"reason": reason, **extra})

    def redeem(self, plan, **extra):
        return self.post(f"{COINS}/redeem", {"plan": plan, **extra})


# ── the earn route ─────────────────────────────────────────────────────────────


class Earn(Wallet):
    def test_a_daily_login_credits_the_ladders_own_grant(self):
        """The reply's number is the ledger's number, and neither is this file's."""
        shipped = engagement.resolve_streak_grants()["coins"][1]
        answered = self.claim()
        self.assertEqual(answered[0], 200, answered)
        earned = self.body(answered)["earned"]
        self.assertEqual(earned["status"], "started")
        self.assertEqual(earned["coins_granted"], shipped)
        self.assertEqual(earned["current_streak"], 1)
        rows = self.rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["delta"], shipped)
        self.assertEqual(rows[0]["reason"], "streak_day")
        self.assertEqual(rows[0]["source"], "server")
        self.assertEqual(self.body(self.get(COINS))["balance"], shipped)

    def test_a_replayed_login_is_a_noop_and_mints_no_second_coin(self):
        """Idempotence is the abuse case: the day is claimed by one guarded `UPDATE`,
        and the credit's `idempotency_key` is derived from the civil day rather than
        from anything the client typed — so there is no fresh event id that buys a
        second coin. Ten claims in a row are one ledger row."""
        empty = self.wallet_state()
        self.assertEqual(empty[0], 0, empty)
        earned = self.body(self.claim())["earned"]
        self.assertEqual(earned["status"], "started")
        settled = self.wallet_state()
        self.assertEqual(settled[0], 1, settled)
        self.assertEqual(settled[1], earned["coins_granted"], settled)
        for _ in range(9):
            replay = self.body(self.claim())["earned"]
            self.assertEqual(replay["status"], "same_day_noop", replay)
            self.assertEqual(replay["coins_granted"], 0)
            self.assertIsNone(replay.get("pass"))
            self.assertEqual(self.wallet_state(), settled, "a replay moved the ledger")
        self.assertEqual(len(self.rows()), 1, self.rows())

    def test_a_login_the_day_after_advances_the_streak_and_pays_that_days_grant(self):
        """The ladder, not a flat daily bonus: day 3 pays `resolve_streak_grants`'s own
        day-3 number, and the streak the reply shows is the one the row now holds.

        One claim only. The credit's key is `streak:<account>:<bucket>:coins`
        (`engagement.py:928`) and the day is claimed by the guarded `UPDATE` at
        `:912`, so a bucket can hold exactly one credit — claiming twice inside one
        real day to simulate two civil days would have the second grant deduped away
        by the ledger's own idempotency, and the state this fixture needs (a streak
        that stopped yesterday) is a `streak_state` seed, not a second wallet row.
        """
        day3 = engagement.resolve_streak_grants()["coins"][3]
        with closing(sqlite3.connect(str(self.state))) as conn:
            conn.execute("INSERT OR IGNORE INTO streak_state(account_id, updated_at)"
                         " VALUES(?, 0)", (self.account_id,))
            conn.execute("UPDATE streak_state SET last_counted_day = ?,"
                         " current_streak = ?, best_streak = ? WHERE account_id = ?",
                         (self.yesterday_bucket(), 2, 2, self.account_id))
            conn.commit()
        earned = self.body(self.claim())["earned"]
        self.assertEqual(earned["status"], "advanced", earned)
        self.assertEqual(earned["current_streak"], 3)
        self.assertEqual(earned["coins_granted"], day3)
        self.assertEqual(self.rows()[-1]["ref"], "streak-day-3")
        self.assertEqual(self.body(self.get(COINS))["balance"], day3)

    def test_a_saved_streak_knob_is_the_number_the_phone_sees_and_the_ledger_writes(self):
        """One row, one number, both sides — the `_INT_MAX` mirror's reason for existing.

        Before this surface, `record_engagement_day` paid `STREAK_GRANTS_COINS` while
        `/api/v1/app/remote-config` published `streak_day1_coins`, so an operator
        lowering the bonus changed the number a phone drew and not the number the wallet
        got. The route resolves the table once and hands it to the grant, so this single
        assertion pair is the whole law: published == enforced.
        """
        self.settings(streak_day1_coins=25)
        self.assertEqual(self.published_engagement()["streak"]["grants"]["day1_coins"], 25)
        earned = self.body(self.claim())["earned"]
        self.assertEqual(earned["coins_granted"], 25)
        self.assertEqual(self.rows()[0]["delta"], 25)

    def test_a_zero_override_pays_the_shipped_grant_rather_than_free_coins(self):
        self.settings(streak_day1_coins=0)
        earned = self.body(self.claim())["earned"]
        self.assertEqual(earned["coins_granted"],
                         engagement.resolve_streak_grants()["coins"][1])

    def test_a_body_naming_its_own_reward_or_owner_is_refused_and_writes_nothing(self):
        """`amount` is the key a caller sends to price itself; `account_id` is the key a
        caller sends to spend somebody else's coins. Both are 400s opened before the
        wallet is, and neither is answered by a lesson about which key was wrong."""
        before = self.wallet_state()
        for extra in ({"amount": 500}, {"minutes": 15}, {"account_id": 99},
                      {"event_id": "abc"}, {"reason": "daily_login", "coins": 1}):
            payload = dict(extra)
            payload.setdefault("reason", "daily_login")
            answered = self.post(f"{COINS}/earn", payload)
            self.assertEqual(answered[0], 400, (payload, answered))
            self.assertEqual(self.code(answered), "invalid_params")
        self.assertEqual(self.wallet_state(), before)

    def test_a_rewarded_ad_claim_is_refused_because_nothing_here_can_attest_it(self):
        """The brief's earning rule, refused on a measurement.

        The cap exists and works (`_enforce_rewarded_cap`), the reason exists and is
        legal (`LEDGER_REASONS`), and the amount exists (`COINS_PER_REWARDED_AD`) — what
        does not exist is a completion signal this server owns: the only one on the host
        is `usage_stats`' client-reported counter, and `grant_coins` would refuse the
        `source="app"` this route would need, because `SERVER_SOURCES` is the ledger's
        way of saying a client claim mints nothing. Labelling a relayed claim `server`
        would make the one column whose job is *who vouched* lie.
        """
        before = self.wallet_state()
        answered = self.claim("rewarded_ad")
        self.assertEqual(answered[0], 403, answered)
        self.assertEqual(self.code(answered), "forbidden")
        detail = json.loads(answered[2].decode("utf-8"))["detail"]
        self.assertIn("callback", detail)
        self.assertEqual(self.wallet_state(), before)
        # Positive control: the cap and the reason are real, so this is a refusal about
        # attestation and not a route that forgot how to count. The owner's own path
        # still credits a server-attested grant and the cap still fires at ten.
        self.grant(engagement.COINS_PER_REWARDED_AD, reason="rewarded_ad")
        self.assertEqual(self.body(self.get(COINS))["rewarded_grants_today"], 1)
        with closing(engagement.connect(self.state)) as conn:
            with self.assertRaises(engagement.RewardedCapReached):
                for i in range(engagement.REWARDED_DAILY_CAP):
                    engagement.grant_coins(conn, self.account_id, amount=5,
                                           reason="rewarded_ad", source="server",
                                           idempotency_key=f"ad-test-{i}")

    def test_a_watch_time_claim_is_refused_and_writes_nothing(self):
        before = self.wallet_state()
        answered = self.claim("watch_time", minutes=30)
        self.assertEqual(answered[0], 400, answered)   # `minutes` is refused first
        self.assertEqual(self.wallet_state(), before)
        answered = self.claim("watch_time")
        self.assertEqual(answered[0], 403, answered)
        self.assertIn("redirect", json.loads(answered[2].decode("utf-8"))["detail"])
        self.assertEqual(self.wallet_state(), before)

    def test_an_unknown_reason_is_a_400_and_never_a_silent_zero(self):
        answered = self.claim("streak_bonus")
        self.assertEqual(answered[0], 400, answered)
        self.assertEqual(self.code(answered), "invalid_params")
        self.assertEqual(self.wallet_state(), (0, 0, 0.0))

    def test_the_day_seven_milestone_mints_the_pass_the_ladder_promise_it(self):
        """The streak's one non-coin reward, and the only place a route hands out a
        signed pass without a coin being spent: day 7 of the ladder, verified against
        `redact`'s own parser rather than a shape this file invented."""
        hours = engagement.resolve_streak_grants()["pass_seconds"] // 3600
        self.assertEqual(hours, engagement.STREAK_PASS_SECONDS // 3600)
        with closing(sqlite3.connect(str(self.state))) as conn:
            conn.execute("INSERT OR IGNORE INTO streak_state(account_id, updated_at)"
                         " VALUES(?, 0)", (self.account_id,))
            conn.execute("UPDATE streak_state SET last_counted_day = ?,"
                         " current_streak = ?, best_streak = ? WHERE account_id = ?",
                         (self.yesterday_bucket(), engagement.STREAK_PASS_DAY - 1,
                          engagement.STREAK_PASS_DAY - 1, self.account_id))
            conn.commit()
        earned = self.body(self.claim())["earned"]
        self.assertEqual(earned["current_streak"], engagement.STREAK_PASS_DAY)
        self.assertEqual(earned["coins_granted"], 0, earned)
        expires = earned["pass_expires_at"]
        self.assertAlmostEqual(expires - time.time(),
                               engagement.STREAK_PASS_SECONDS, delta=120)
        self.assertEqual(redact.parse_vip_pass(earned["pass"], SECRET), expires)
        # Day 7 pays a pass and not a coin: `resolve_streak_grants` has no coin entry for
        # it, so the milestone must not quietly hand out both.
        self.assertEqual(self.rows(), [], self.rows())


# ── the read routes ────────────────────────────────────────────────────────────


class Reads(Wallet):
    def test_the_balance_is_the_derived_sum_and_nothing_else(self):
        """There is no `user_coins.balance` column to be stale about: the reply and the
        spender read one `SUM(delta)` over the same rows."""
        self.assertEqual(self.body(self.get(COINS)), {
            "balance": 0, "rewarded_grants_today": 0,
            "caps": dict(engagement.remote_view()["wallet"])})
        self.grant(70)
        self.spend(20)
        self.assertEqual(self.body(self.get(COINS))["balance"], 50)
        self.assertEqual(sum(row["delta"] for row in self.rows()), 50)

    def test_the_caps_block_is_the_ledgers_own_projection_called_not_copied(self):
        """The route publishes `engagement.remote_view()["wallet"]` rather than
        restating a cap: this file may not hold a number the wallet also holds.

        `rewarded_daily_cap` is deliberately the *shipped* number even when the operator
        row saves another, because `_enforce_rewarded_cap` still enforces the constant —
        `remote_view()`'s own docstring names that as the last unwired knob, and wiring
        it would change what a day of ads pays, which is an owner decision rather than a
        routing decision. A cap published here that the ledger ignored would be the
        second number, and the lie would be this route's.
        """
        self.settings(rewarded_daily_cap=3)
        caps = self.body(self.get(COINS))["caps"]
        self.assertEqual(caps, dict(engagement.remote_view()["wallet"]))
        self.assertEqual(caps["rewarded_daily_cap"], engagement.REWARDED_DAILY_CAP)
        with closing(engagement.connect(self.state)) as conn:
            for i in range(engagement.REWARDED_DAILY_CAP):
                engagement.grant_coins(conn, self.account_id, amount=1,
                                       reason="rewarded_ad", source="server",
                                       idempotency_key=f"cap-{i}")
            with self.assertRaises(engagement.RewardedCapReached):
                engagement.grant_coins(conn, self.account_id, amount=1,
                                       reason="rewarded_ad", source="server",
                                       idempotency_key="cap-over")

    def test_rewarded_grants_today_counts_the_rows_the_cap_counts(self):
        """One bucket, one query, shared by the refusal and the wallet screen —
        `_rewarded_count` is why these two numbers cannot disagree."""
        self.assertEqual(self.body(self.get(COINS))["rewarded_grants_today"], 0)
        with closing(engagement.connect(self.state)) as conn:
            for i in range(4):
                engagement.grant_coins(conn, self.account_id, amount=5,
                                       reason="rewarded_ad", source="server",
                                       idempotency_key=f"seen-{i}")
            engagement.grant_coins(conn, self.account_id, amount=5,
                                   reason="streak_day", source="server",
                                   idempotency_key="not-an-ad")
        self.assertEqual(self.body(self.get(COINS))["rewarded_grants_today"], 4)

    def test_the_caps_route_prices_what_the_wallet_routes_charge(self):
        """Route 4 exists so a phone can price a redeem without pulling the whole public
        config body, which makes it the most convenient place to put a second price list.

        So the assertion here is not `caps == a number this file expects` — it is that
        one saved row moves the list, the earn and the spend together. `streak_day3_coins`
        and `coin_redeem_day` are the two knobs this surface enforces from the row (the
        earn route hands `resolve_streak_grants(values)` to `record_engagement_day`, the
        redeem hands `resolve_ladder(values)` to `redeem_pass`), so both halves are the
        resolver's own output and a copy made here would be the divergence.

        The day keys arrive as `"3"`, not `3`: `resolve_streak_grants` returns a table
        keyed by day and JSON makes every key a string. Left alone deliberately — the
        alternative is this route renaming the ladder tier by tier, which is the second
        mapping `admin_panel._engagement_public`'s docstring exists to forbid.
        """
        self.settings(streak_day3_coins=44, coin_redeem_day=7)
        caps = self.body(self.get(COINS + "/caps"))
        self.assertEqual(caps["streak"]["coins"]["3"], 44, caps)
        self.assertEqual(caps["passes"]["day"]["coins"], 7, caps)
        self.assertEqual(caps["passes"]["day"]["pkr"],
                         engagement.resolve_ladder()["day"]["pkr"], caps)
        cost = caps["passes"]["day"]["coins"]
        self.grant(cost)
        answered = self.redeem("day")
        self.assertEqual(answered[0], 200, answered)
        self.assertEqual(self.body(answered)["redeemed"]["cost"], cost)
        self.assertEqual(self.rows()[-1]["delta"], -cost, self.rows())

    def test_the_caps_route_publishes_the_enforced_cap_rather_than_the_saved_one(self):
        """The one block on this route that does not follow the row, pinned so the day it
        starts is a decision rather than a drift.

        `rewarded_daily_cap` is enforced from `REWARDED_DAILY_CAP` by
        `_enforce_rewarded_cap`, so publishing the saved 3 here would tell a phone it had
        three ads today when the ledger hands out ten. The mirror law is 'the number a
        client reads is the number the server enforces' — which points at the constant
        until the constant is wired to the row, and at the row afterwards.
        """
        self.settings(rewarded_daily_cap=3)
        caps = self.body(self.get(COINS + "/caps"))["caps"]
        self.assertEqual(caps["rewarded_daily_cap"], engagement.REWARDED_DAILY_CAP)
        self.assertNotEqual(caps["rewarded_daily_cap"], 3)

    def test_the_history_page_is_bounded_newest_first_and_carries_its_own_count(self):
        for i in range(5):
            self.grant(10 + i, idempotency=f"row-{i}")
        page = self.body(self.get(COINS + "/history", {"limit": ["3"]}))
        self.assertEqual(len(page["entries"]), 3, page)
        self.assertEqual(page["count"], 3)
        self.assertEqual([e["id"] for e in page["entries"]],
                         sorted((e["id"] for e in page["entries"]), reverse=True))
        self.assertEqual([e["delta"] for e in page["entries"]], [14, 13, 12])
        self.assertEqual(len(self.body(self.get(COINS + "/history"))["entries"]), 5)

    def test_a_limit_that_is_not_a_number_is_the_default_not_an_error(self):
        self.grant(10)
        for junk in ([""], ["abc"], ["-4"], []):
            page = self.body(self.get(COINS + "/history", {"limit": junk}))
            self.assertEqual(len(page["entries"]), 1, page)

    def test_the_wallet_is_scoped_to_the_key_that_asked_for_it(self):
        """Two accounts, two wallets, no route between them."""
        self.claim()
        other_key = self.enroll()
        other_id = self.own_id(other_key)
        self.assertNotEqual(other_id, self.account_id)
        self.assertEqual(self.body(self.get(COINS, key=other_key))["balance"], 0)
        self.assertEqual(self.body(self.get(COINS + "/history", key=other_key))["count"], 0)
        self.grant(500, key=other_id)
        self.assertEqual(self.body(self.get(COINS, key=other_key))["balance"], 500)
        self.assertEqual(self.body(self.get(COINS))["balance"],
                         engagement.resolve_streak_grants()["coins"][1])
        self.assertEqual(self.rows(other_id)[0]["account_id"], other_id)

    def test_no_body_on_the_wallet_names_an_account_or_a_source(self):
        """`account_id` is a server primary key (§16.9 gives a client nothing to point
        at) and a scraped site name is provenance — both are scanned for in every shape
        this surface can emit, with a positive control so a scan that matched nothing
        cannot go green."""
        self.claim()
        self.grant(300)
        bodies = [self.get(COINS), self.get(COINS + "/caps"),
                  self.get(COINS + "/history"), self.claim(),
                  self.redeem("day")]
        haystack = " ".join(answered[2].decode("utf-8") for answered in bodies
                           if answered[2])
        self.assertIn("balance", haystack)              # positive control
        for needle in ("account_id", "canonical_key", "work_key", "source_site",
                       "url", "slug"):
            self.assertNotIn(f'"{needle}"', haystack, needle)
        for word in NEEDLES:
            self.assertNotIn(word, haystack.lower(), word)

    def test_a_refusal_detail_never_quotes_a_balance_a_cost_or_a_site(self):
        """A 402 that says "you need 200, you have 40" is a shopping list for whatever
        mints coins, and the numbers are the caller's own to read from `GET /coins`."""
        answered = self.redeem("monthly_vip")
        self.assertEqual(answered[0], 402, answered)
        detail = json.loads(answered[2].decode("utf-8"))["detail"]
        self.assertNotIn("0", detail)
        self.assertFalse(any(ch.isdigit() for ch in detail), detail)

    def test_every_coin_on_the_wire_and_in_the_column_is_a_whole_number(self):
        """The money law for coins: a `delta` is `INTEGER`, a reply's `balance` is an
        `int`, and a `float` anywhere in this surface is a rounding step waiting to
        disagree with the ledger."""
        self.claim()
        self.grant(engagement.resolve_ladder()["day"]["coins"])
        self.assertEqual(self.redeem("day")[0], 200)
        rows = self.rows()
        self.assertTrue(any(row["delta"] > 0 for row in rows), rows)
        self.assertTrue(any(row["delta"] < 0 for row in rows), rows)
        self.assertTrue(all(row["delta_type"] == "integer" for row in rows), rows)
        for key in ("balance", "rewarded_grants_today"):
            value = self.body(self.get(COINS))[key]
            self.assertIsInstance(value, int)
            self.assertNotIsInstance(value, bool)
        for entry in self.body(self.get(COINS + "/history"))["entries"]:
            self.assertIsInstance(entry["delta"], int)


# ── the redeem route ───────────────────────────────────────────────────────────


class Redeem(Wallet):
    def test_a_short_wallet_is_refused_and_the_ledger_does_not_move(self):
        """The half-applied spend is the failure this ordering exists to prevent:
        `resolve_ladder` first, the guarded debit second, the signature last — so a
        refusal writes no row and leaves the balance where it was."""
        before_rows, before_sum, _ = self.wallet_state()
        answered = self.redeem("day")
        self.assertEqual(answered[0], 402, answered)
        self.assertEqual(self.code(answered), "licence_required")
        self.assertEqual(self.wallet_state()[:2], (before_rows, before_sum))
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.body(self.get(COINS))["balance"], 0)

    def test_a_redeem_debits_once_and_mints_one_pass_at_the_ladders_own_price(self):
        cost = engagement.resolve_ladder()["day"]["coins"]
        self.grant(cost)
        answered = self.redeem("day")
        self.assertEqual(answered[0], 200, answered)
        receipt = self.body(answered)["redeemed"]
        self.assertEqual(receipt["cost"], cost)
        self.assertEqual(receipt["reward"], "day")
        self.assertEqual(receipt["balance"], 0)
        self.assertFalse(receipt["already_applied"])
        self.assertEqual(redact.parse_vip_pass(receipt["pass"], SECRET),
                         receipt["expires_at"])
        self.assertGreater(receipt["expires_at"], time.time())
        spends = [row for row in self.rows() if row["reason"] == "redeem_pass"]
        self.assertEqual(len(spends), 1, spends)
        self.assertEqual(spends[0]["delta"], -cost)
        self.assertEqual(spends[0]["ref"], "day")

    def test_the_price_charged_is_the_price_the_saved_row_publishes(self):
        """`resolve_ladder` is the only function that turns a settings row into a
        ladder, and this route hands the resolved table to `redeem_pass` rather than
        describing it again — so the two halves of one number are one read."""
        self.settings(coin_redeem_day=7)
        self.assertEqual(self.published_engagement()["passes"]["day"]["coins"], 7)
        self.grant(7)
        receipt = self.body(self.redeem("day"))["redeemed"]
        self.assertEqual(receipt["cost"], 7)
        self.assertEqual(self.rows()[-1]["delta"], -7)

    def test_a_second_tier_costs_its_own_number_and_not_the_firsts(self):
        ladder = engagement.resolve_ladder()
        for plan in ("weekend", "monthly_vip"):
            cost = ladder[plan]["coins"]
            self.grant(cost, idempotency=f"fund-{plan}")
            receipt = self.body(self.redeem(plan))["redeemed"]
            self.assertEqual(receipt["cost"], cost, plan)
            self.assertEqual(receipt["reward"], plan)
        spends = [row for row in self.rows() if row["reason"] == "redeem_pass"]
        self.assertEqual([row["ref"] for row in spends], ["weekend", "monthly_vip"],
                         spends)

    def test_a_quality_unlock_is_refused_because_the_pass_cannot_carve_it(self):
        """Not caution: `redact._VIP_PASS_VERSION` packs a version, an expiry and a tag
        — no title, no scope — and `/api/v1/posts?quality=` is a release-*existence*
        filter, not an entitlement gate, because the player picks the band. A coin spent
        here buys a receipt for nothing the server enforces, and `coin_ledger.ref`
        forbids naming a title even in the audit trail."""
        self.grant(engagement.resolve_ladder()["day"]["coins"])
        settled = self.wallet_state()
        self.assertGreater(settled[0], 0, "the funding grant did not land")
        answered = self.redeem(REFUSED_PLAN)
        self.assertEqual(answered[0], 403, answered)
        self.assertEqual(self.code(answered), "forbidden")
        self.assertIn("scope", json.loads(answered[2].decode("utf-8"))["detail"])
        self.assertEqual(self.wallet_state(), settled, "a refusal moved the ledger")

    def test_a_plan_the_ladder_does_not_sell_is_a_400(self):
        """The name space is `resolve_ladder`'s; there is no reward table in this file
        to fall out of agreement with it."""
        before = self.wallet_state()
        for plan in ("vip_24h", "day_pass", "", "MONTHLY_VIP", "monthly vip"):
            answered = self.redeem(plan)
            self.assertEqual(answered[0], 400, (plan, answered))
            self.assertEqual(self.code(answered), "invalid_params")
        self.assertEqual(self.wallet_state(), before)

    def test_a_body_naming_a_title_is_refused_because_no_per_title_reward_is_sold(self):
        before = self.wallet_state()
        ref = redact.mint_text(VISIBLE, SECRET)
        for extra in ({"media_id": 1000}, {"work_ref": ref}, {"work_key": VISIBLE}):
            answered = self.post(f"{COINS}/redeem", {"plan": "day", **extra})
            self.assertEqual(answered[0], 400, (extra, answered))
        self.assertEqual(self.wallet_state(), before)

    def test_two_redeems_never_buy_more_pass_than_the_wallet_paid_for(self):
        """`redeem_pass` derives its idempotency key from the second, so two claims
        inside one second collapse to `already_applied` and two a second apart are two
        spends. That boundary is a clock, so this asserts the invariant instead of a
        count: the coins that left the ledger equal the passes the caller was handed,
        and a collapsed replay writes no extra row."""
        cost = engagement.resolve_ladder()["day"]["coins"]
        self.grant(cost * 2)
        started = self.wallet_state()
        first = self.body(self.redeem("day"))["redeemed"]
        second = self.body(self.redeem("day"))["redeemed"]
        self.assertEqual(first["balance"], cost * 2 - cost)
        spends = [row for row in self.rows() if row["reason"] == "redeem_pass"]
        if second["already_applied"]:
            self.assertEqual(len(spends), 1, spends)
            self.assertEqual(second["balance"], first["balance"])
        else:
            self.assertEqual(len(spends), 2, spends)
            self.assertEqual(second["balance"], 0)
        self.assertEqual(self.wallet_state()[1], started[1] - cost * len(spends))

    def test_a_pass_bought_with_coins_is_the_credential_the_bypass_checks(self):
        """The redeem is only worth its price if the token it returns is the one the
        download path accepts, so the round trip is asserted against `redact
        .parse_vip_pass` — the verifier `viewer.py:456` calls — rather than a shape this
        file invented. A pass signed with another secret must not parse."""
        cost = engagement.resolve_ladder()["day"]["coins"]
        self.grant(cost)
        receipt = self.body(self.redeem("day"))["redeemed"]
        self.assertIsNotNone(redact.parse_vip_pass(receipt["pass"], SECRET))
        self.assertIsNone(redact.parse_vip_pass(receipt["pass"], "wrong-secret"))


# ── authentication and routing ─────────────────────────────────────────────────


class Edge(Wallet):
    ROUTES = ((None, COINS, None), (None, COINS + "/caps", None),
              (None, COINS + "/history", None),
              ("POST", COINS + "/earn", {"reason": "daily_login"}),
              ("POST", COINS + "/redeem", {"plan": "day"}))

    def test_every_wallet_route_refuses_a_caller_with_no_key(self):
        """401 rather than the favorites routes' 404: this is not a lookup that can
        miss, it is a question only an account can ask. And it is asked before the
        wallet is opened, so an unauthenticated sweep of this host writes nothing."""
        before = self.wallet_state()
        for method, path, payload in self.ROUTES:
            answered = (self.post(path, payload, key=None) if method
                        else self.get(path, key=None))
            self.assertEqual(answered[0], 401, (path, answered))
            self.assertEqual(self.code(answered), "unauthorised")
        self.assertEqual(self.wallet_state(), before)

    def test_a_key_that_is_not_here_is_answered_the_way_every_account_route_answers_it(self):
        """404, not 401 — and that is the pre-existing contract, not a wallet exception.

        `_refused` maps `accounts.UnknownAccount` to the same answer a missing favorite
        gets, so a wrong sync key cannot be told apart from an account that has no
        wallet, which is the property that keeps this host from being an account
        enumerator. What a wallet route adds is only the other half: the refusal happens
        before `engagement` is opened, so a bogus key cannot create the ledger's tables
        or move a row either.
        """
        before = self.wallet_state()
        for method, path, payload in self.ROUTES:
            answered = (self.post(path, payload, key="not-a-real-sync-key") if method
                        else self.get(path, key="not-a-real-sync-key"))
            self.assertEqual(answered[0], 404, (path, answered))
            self.assertEqual(self.code(answered), "not_found")
        self.assertEqual(self.wallet_state(), before)

    def test_the_wallet_routes_do_not_shadow_the_routes_already_mounted(self):
        """`/coins` is a new tail under a prefix `viewer.py` already dispatches whole —
        so the neighbours must still answer exactly as they did, and `coins/balance`
        must *not* resolve, because a second read of one balance is a second owner."""
        self.assertEqual(self.get(COINS + "/balance")[0], 404)
        self.assertEqual(self.get(P)[0], 200)
        self.assertEqual(self.body(self.get(P + "/favorites")),
                         {"favorites": [], "count": 0})
        self.assertEqual(self.post(P + "/coins/earn/bogus", {})[0], 404)

    def test_a_problem_body_keeps_the_v2_shape_rather_than_inventing_one(self):
        """No new code is minted for a wallet: the refusal vocabulary is `api_v2`'s, so
        an account refusal and a catalog one are the same document."""
        answered = self.redeem("monthly_vip")
        body = json.loads(answered[2].decode("utf-8"))
        self.assertEqual(body["type"], "/api/v2/problems/licence_required")
        self.assertEqual(body["status"], 402)
        self.assertIn("request_id", body)
        self.assertEqual(body["instance"], f"{COINS}/redeem")
        self.assertNotIn("account_id", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
