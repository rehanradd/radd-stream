"""Offline tests for the operator usage aggregates.

Three rules own this module, and the tests below are grouped by them rather than
by function:

1. **Aggregates only.** No per-person timeline, no device-to-name join, no IP in
   any form. A device bucket is a salted truncated digest and the tables hold one
   row per bucket — so the tests assert the *schema* and the *bytes*, not just the
   numbers, because a counter table that grew a `day` column per device would
   still return correct counts.
2. **Loopback only.** Nothing here adds a route; the counters are earned on the
   account surface that already exists, and read out of `/admin/usage`.
3. **Incremental on write, on a single core.** Every number is a `COUNT` or a
   `SUM` over a table bounded by installs and days, never a scan of the catalog —
   so the report must work on a ledger file that has no catalog tables at all.

Everything runs against a temp SQLite file with an injected clock: no network, no
catalog, no `fast_fetch` rows.
"""

import json
import os
import sqlite3
import sys
import time
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accounts                        # noqa: E402
import accounts_api                    # noqa: E402
import admin_panel                     # noqa: E402
import catalog_v2                      # noqa: E402
import payments                        # noqa: E402
import usage_stats                     # noqa: E402

#: 08:00:00 UTC on a day number of 20833, so "40 minutes ago" cannot fall on
#: yesterday and make a window assertion depend on when the suite is run.
NOW = 1_799_971_200.0 + 28_800.0
DAY = 86_400.0

PK_HEADERS = {"Accept-Language": "en-PK,en;q=0.9", "X-App-Version": "1.4.2",
              "X-Device-Class": "phone"}
#: `accounts` refuses any sync key shorter than 16 characters, so every key in
#: this file is a shape a real client could present.
def sync_key(label):
    return ("q3-" + label + "-" + "k" * 24)[:40]


#: The name `admin_panel._gate` reads. It is spelled out rather than imported
#: because the gate is the thing under test: if the name changes, these tests must
#: fail loudly instead of silently running with an unset token.
TOKEN_ENV = "RADD_ADMIN_TOKEN"


class TempLedger(unittest.TestCase):
    """A state DB with the accounts schema and no catalog tables whatsoever."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "user_state.db")
        with accounts.connect(self.db) as conn:
            conn.commit()
        self.old_salt = os.environ.pop(usage_stats.DEVICE_SALT_ENV, None)
        self.addCleanup(self._restore_salt)

    def _restore_salt(self):
        if self.old_salt is None:
            os.environ.pop(usage_stats.DEVICE_SALT_ENV, None)
        else:
            os.environ[usage_stats.DEVICE_SALT_ENV] = self.old_salt

    def conn(self):
        return sqlite3.connect(self.db)

    def rows(self, sql, *args):
        with self.conn() as conn:
            return conn.execute(sql, args).fetchall()

    def has_table(self, table) -> bool:
        return bool(self.rows("SELECT name FROM sqlite_master WHERE type='table'"
                              " AND name=?", table))

    def columns(self, table):
        """`PRAGMA table_info` rather than the `pragma_column_list` table-valued
        function: this build of SQLite does not have the latter, and the pragma is
        the same answer."""
        with self.conn() as conn:
            conn.row_factory = sqlite3.Row
            return [row["name"] for row in conn.execute(
                "PRAGMA table_info(%s)" % table)]

    def stored_bytes(self) -> bytes:
        return Path(self.db).read_bytes()


# ── rule 1: the identifier ───────────────────────────────────────────────────

class DeviceIdentityTests(TempLedger):
    def test_token_is_prefixed_truncated_and_stable(self):
        one = usage_stats.device_token("install-abc")
        self.assertTrue(one.startswith(usage_stats.DEVICE_PREFIX))
        self.assertEqual(len(one), len(usage_stats.DEVICE_PREFIX)
                         + usage_stats.DEVICE_HASH_CHARS)
        self.assertEqual(one, usage_stats.device_token("install-abc"))
        self.assertNotIn("install-abc", one)

    def test_empty_input_yields_no_bucket(self):
        for value in ("", None, "   "):
            self.assertEqual(usage_stats.device_token(value), "", repr(value))

    def test_two_devices_do_not_collide(self):
        self.assertNotEqual(usage_stats.device_token("device-one"),
                            usage_stats.device_token("device-two"))

    def test_the_salt_re_keys_every_bucket(self):
        before = usage_stats.device_token("install-abc")
        os.environ[usage_stats.DEVICE_SALT_ENV] = "a-different-salt:"
        self.assertNotEqual(usage_stats.device_token("install-abc"), before)

    def test_one_way_means_the_raw_id_is_never_recoverable_or_stored(self):
        usage_stats.record_seen(self.db, install_id="plain-text-install-id",
                                now=NOW)
        self.assertNotIn(b"plain-text-install-id", self.stored_bytes())
        bucket = self.rows("SELECT device_hash FROM usage_device")[0][0]
        self.assertNotIn("plain", bucket)
        self.assertEqual(len(bucket), len(usage_stats.DEVICE_PREFIX)
                         + usage_stats.DEVICE_HASH_CHARS)

    def test_a_credential_falls_back_to_a_bucket_when_no_install_id_arrives(self):
        """Pre-change app builds send no `X-Install-Id`; they still identified
        themselves with a bearer key, and that key must not be stored either."""
        seen = usage_stats.record_seen(self.db, credential="secret-sync-key",
                                       credential_is_known=True, now=NOW)
        self.assertTrue(seen["device_hash"])
        self.assertNotIn(b"secret-sync-key", self.stored_bytes())
        again = usage_stats.record_seen(self.db, credential="secret-sync-key",
                                        credential_is_known=True, now=NOW + 1)
        self.assertEqual(again["device_hash"], seen["device_hash"])

    def test_an_unknown_credential_creates_no_device_row(self):
        """Rule 3, as a property of the table rather than an intention: a stranger
        guessing sync keys cannot grow `usage_device` one row per guess."""
        for guess in ("guessed-key-1", "guessed-key-2", "guessed-key-3"):
            usage_stats.record_seen(self.db, credential=guess,
                                    credential_is_known=False, now=NOW)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 0)
        self.assertEqual(self.rows(
            "SELECT total FROM usage_metric WHERE metric = 'account_request'")[0][0],
            3)

    def test_a_forged_install_header_on_an_unknown_key_marks_no_device(self):
        """`X-Install-Id` is client text, so it only names a bucket for a caller
        this server already knows; otherwise one valid-looking header per guess
        would do what a guessed key now cannot."""
        usage_stats.record_seen(self.db, install_id="spoofed-install",
                                credential="not-issued", credential_is_known=False,
                                now=NOW)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 0)

    def test_the_install_header_wins_over_the_credential(self):
        with_header = usage_stats.record_seen(
            self.db, install_id="iid-1", credential="key-1",
            credential_is_known=True, now=NOW)
        without = usage_stats.record_seen(self.db, credential="key-1",
                                          credential_is_known=True, now=NOW + 1)
        self.assertNotEqual(with_header["device_hash"], without["device_hash"])
        # …and both bucket under the header when the header is present, which is
        # what makes `distinct_devices` a device count rather than a key count.
        second_key = usage_stats.record_seen(self.db, install_id="iid-1",
                                             credential="key-2",
                                             credential_is_known=True, now=NOW + 2)
        self.assertEqual(second_key["device_hash"], with_header["device_hash"])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 2)


class AttributeTests(TempLedger):
    def test_geo_is_the_stated_region_subtag_not_an_address(self):
        attrs = usage_stats.attributes_from_headers(PK_HEADERS)
        self.assertEqual(attrs["geo"], "PK")
        self.assertEqual(attrs["locale"], "en-pk")
        self.assertEqual(attrs["app_version"], "1.4.2")
        self.assertEqual(attrs["device_class"], "phone")

    def test_a_bare_language_has_no_geo(self):
        attrs = usage_stats.attributes_from_headers({"Accept-Language": "ur"})
        self.assertEqual(attrs["geo"], usage_stats.UNKNOWN_VALUE)
        self.assertEqual(attrs["locale"], "ur")

    def test_no_header_means_no_dimension_and_no_ip_ever(self):
        attrs = usage_stats.attributes_from_headers({})
        self.assertEqual(set(attrs.values()), {usage_stats.UNKNOWN_VALUE})
        for name in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "Client-IP"):
            leaked = usage_stats.attributes_from_headers(
                {name: "203.0.113.9", "Accept-Language": "en-PK"})
            blob = " ".join(str(v) for v in leaked.values())
            self.assertNotIn("203.0.113.9", blob, name)

    def test_a_device_model_string_is_not_mined_from_user_agent(self):
        """A UA is a fingerprint; `device_class` comes from our own header."""
        attrs = usage_stats.attributes_from_headers(
            {"User-Agent": "SM-G991B/1.0 Android/13"})
        self.assertEqual(attrs["device_class"], usage_stats.UNKNOWN_VALUE)

    def test_odd_dimension_text_folds_to_unknown(self):
        for value in ("<script>x</script>", "a" * 33, "two words", "semi;colon",
                      "203.0.113.9", "10.0.0.1:8080"):
            self.assertEqual(usage_stats.clean_value(value),
                             usage_stats.UNKNOWN_VALUE, value)
        self.assertEqual(usage_stats.clean_value(" 1.4.2-rc1 "), "1.4.2-rc1")

    def test_an_unknown_attribute_never_clobbers_a_known_one(self):
        first = usage_stats.record_seen(self.db, install_id="iid-1",
                                        headers=PK_HEADERS, now=NOW)
        later = usage_stats.record_seen(self.db, install_id="iid-1",
                                        headers={}, now=NOW + DAY)
        self.assertEqual(later["geo"], usage_stats.UNKNOWN_VALUE)
        row = self.rows("SELECT geo, app_version FROM usage_device")[0]
        self.assertEqual(tuple(row), ("PK", "1.4.2"))
        self.assertEqual(first["install_day"], later["install_day"])


# ── the counters themselves ─────────────────────────────────────────────────

class WriteCounterTests(TempLedger):
    def test_install_day_is_set_once_and_never_moved(self):
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW - 40 * DAY)
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW)
        install_day, = self.rows("SELECT install_day FROM usage_device")[0]
        self.assertEqual(install_day, usage_stats.day_of(NOW - 40 * DAY))

    def test_last_seen_is_a_maximum_so_a_late_write_cannot_age_a_device(self):
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW)
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW - 5 * DAY)
        last_seen, = self.rows("SELECT last_seen_at FROM usage_device")[0]
        self.assertEqual(last_seen, NOW)

    def test_one_session_per_gap_not_one_per_request(self):
        """Rule 3: a browse-heavy phone must not become one row-write per tap."""
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW)
        for offset in (10, 60, 300, 890):
            usage_stats.record_seen(self.db, install_id="iid-1", now=NOW + offset)
        self.assertEqual(self._sessions(), 1.0)
        usage_stats.record_seen(self.db, install_id="iid-1",
                                now=NOW + 2 * usage_stats.SEEN_WRITE_INTERVAL)
        self.assertEqual(self._sessions(), 2.0)

    def _sessions(self):
        rows = self.rows("SELECT SUM(total) FROM usage_metric WHERE metric='session'")
        return float(rows[0][0] or 0)

    def test_anonymous_calls_count_requests_but_mark_no_device(self):
        usage_stats.record_seen(self.db, now=NOW)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 0)
        total, = self.rows(
            "SELECT total FROM usage_metric WHERE metric='account_request'")[0]
        self.assertEqual(total, 1)

    def test_an_unauthenticated_probe_buys_no_write_at_all(self):
        """A junk bearer must not turn a scan into a database write per hit."""
        usage_stats.record_seen(self.db, credential="", now=NOW,
                                count_request=False)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_metric")[0][0], 0)

    def test_the_day_bucket_is_utc_and_shared_with_reads(self):
        self.assertEqual(usage_stats.day_of(NOW), int(NOW // DAY))
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW)
        day, metric, total = self.rows(
            "SELECT day, metric, total FROM usage_metric")[0]
        self.assertEqual((day, metric, total), (usage_stats.day_of(NOW),
                                                "account_request", 1))

    def test_a_broken_ledger_is_silence_not_a_crash(self):
        """Analytics must never break the user's request. A directory where a
        database should be is the deterministic version of "the ledger cannot be
        written": overwriting a real file can succeed via WAL recovery instead."""
        broken = str(Path(self.tmp.name) / "broken.db")
        Path(broken).mkdir()
        self.assertIsNone(usage_stats.record_seen(broken, install_id="iid-1",
                                                 now=NOW))
        self.assertFalse(usage_stats.record_event(broken, metric="crash", now=NOW))
        self.assertEqual(usage_stats.record_client_usage(
            broken, {"usage": {"crashes": 1}}, now=NOW), {})
        # …and the panel, the only reader, answers an unusable ledger with its
        # unavailable screen rather than a 500 on the operator's own page.
        screen = admin_panel.screen_usage(broken, now=NOW)
        self.assertFalse(screen["available"])


class EventTests(TempLedger):
    def test_only_the_closed_vocabulary_is_counted(self):
        for name in usage_stats.METRICS:
            self.assertTrue(usage_stats.record_event(self.db, metric=name, now=NOW),
                            name)
        self.assertEqual(len(self.rows("SELECT DISTINCT metric FROM usage_metric")),
                         len(usage_stats.METRICS))

    def test_an_unknown_metric_is_refused_not_stored(self):
        for name in ("made_up_metric", "", "SELECT 1", "session ", "crash; DROP"):
            self.assertFalse(usage_stats.record_event(self.db, metric=name, now=NOW),
                             name)
        self.assertFalse(self.has_table("usage_metric"))

    def test_counts_are_clamped_non_negative_and_whole_of_nonsense(self):
        self.assertFalse(usage_stats.record_event(self.db, metric="crash", count=0,
                                                 now=NOW))
        self.assertFalse(usage_stats.record_event(self.db, metric="crash", count=-5,
                                                 now=NOW))
        self.assertFalse(usage_stats.record_event(self.db, metric="crash",
                                                 count="abc", now=NOW))
        self.assertFalse(usage_stats.record_event(self.db, metric="crash",
                                                  count=float("nan"), now=NOW))
        usage_stats.record_event(self.db, metric="ad_request", count=10 ** 9,
                                now=NOW)
        total, = self.rows("SELECT total FROM usage_metric")[0]
        self.assertEqual(total, usage_stats.MAX_EVENT_COUNT)

    def test_an_event_can_be_written_into_a_named_day(self):
        usage_stats.record_event(self.db, metric="playback_start", count=3,
                                 day=usage_stats.day_of(NOW - 2 * DAY))
        usage_stats.record_event(self.db, metric="playback_start", count=4, now=NOW)
        self.assertEqual(usage_stats.summary(self.db, now=NOW, window_days=1)
                         ["metrics"]["playback_start"], 4.0)
        self.assertEqual(usage_stats.summary(self.db, now=NOW, window_days=3)
                         ["metrics"]["playback_start"], 7.0)

    def test_dimension_splits_are_limited_to_the_four_known_dimensions(self):
        usage_stats.record_event(self.db, metric="ad_request", count=2, now=NOW,
                                 dims={"geo": "PK", "device_class": "phone",
                                       "ip_address": "203.0.113.9",
                                       "device_hash": "dev-nope"})
        stored = {row[0] for row in
                  self.rows("SELECT DISTINCT dim FROM usage_dim_metric")}
        self.assertEqual(stored, {"geo", "device_class"})
        self.assertNotIn(b"203.0.113.9", self.stored_bytes())


class ClientUsageTests(TempLedger):
    def test_the_apps_field_names_land_on_the_server_vocabulary(self):
        written = usage_stats.record_client_usage(
            self.db, {"usage": {"ad_requests": 100, "ads_filled": 60,
                                "ad_impressions": 40, "ad_clicks": 3,
                                "rewarded_completions": 5, "coins_granted": 900,
                                "playback_attempts": 12,
                                "playback_buffer_failures": 2,
                                "playback_errors": 1, "crashes": 2,
                                "errors": 4}},
            headers=PK_HEADERS, now=NOW)
        self.assertEqual(written, {"ad_request": 100.0, "ad_fill": 60.0,
                                   "ad_impression": 40.0, "ad_click": 3.0,
                                   "rewarded_completion": 5.0,
                                   "coin_granted": 900.0, "playback_attempt": 12.0,
                                   "playback_buffer_failure": 2.0,
                                   "playback_error": 1.0, "crash": 2.0,
                                   "error": 4.0})
        metrics = usage_stats.summary(self.db, now=NOW)["metrics"]
        for name, amount in written.items():
            self.assertEqual(metrics[name], amount, name)

    def test_unrecognised_names_in_the_usage_block_are_ignored(self):
        written = usage_stats.record_client_usage(
            self.db, {"usage": {"cooler_metric": 5000, "sql": "DROP TABLE"}},
            now=NOW)
        self.assertEqual(written, {})
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_metric")[0][0], 0)

    def test_a_missing_or_malformed_usage_block_is_not_an_error(self):
        for payload in (None, {}, {"usage": None}, {"usage": []}, "usage"):
            self.assertEqual(usage_stats.record_client_usage(
                self.db, payload, now=NOW), {}, repr(payload))

    def test_the_per_class_split_comes_from_the_device_class_header(self):
        for class_headers, count in (({"X-Device-Class": "tv"}, 3),
                                     ({"X-Device-Class": "phone"}, 1)):
            usage_stats.record_client_usage(
                self.db, {"usage": {"crashes": count, "errors": count,
                                    "playback_buffer_failures": count}},
                headers=class_headers, now=NOW)
        report = usage_stats.summary(self.db, now=NOW)
        self.assertEqual(report["crash_by_class"], {"tv": 3.0, "phone": 1.0})
        self.assertEqual(report["error_by_class"], {"tv": 3.0, "phone": 1.0})
        self.assertEqual(report["buffer_failure_by_class"],
                         {"tv": 3.0, "phone": 1.0})

    def test_record_client_usage_needs_no_device_argument(self):
        written = usage_stats.record_client_usage(self.db, {"usage": {"crashes": 2}},
                                                 now=NOW)
        self.assertEqual(written, {"crash": 2.0})

    def test_only_the_three_class_split_families_are_split(self):
        usage_stats.record_client_usage(self.db, {"usage": {"ad_clicks": 5}},
                                        headers=PK_HEADERS, now=NOW)
        dims = {row[0] for row in
                self.rows("SELECT DISTINCT dim FROM usage_dim_metric")}
        self.assertEqual(dims, set())

    def test_per_submission_clamp_stops_one_phone_reporting_a_billion(self):
        usage_stats.record_client_usage(self.db, {"usage": {"ad_impressions": 10 ** 9}},
                                        now=NOW)
        report = usage_stats.summary(self.db, now=NOW)
        self.assertEqual(report["metrics"]["ad_impression"],
                         float(usage_stats.MAX_EVENT_COUNT))
        self.assertEqual(report["revenue_estimate"]["ad_usd_in_window"],
                         round(usage_stats.MAX_EVENT_COUNT / 1000.0 * 0.9, 4))


class AdFunnelTests(TempLedger):
    def test_the_funnel_reads_request_fill_impression_click(self):
        usage_stats.record_client_usage(
            self.db, {"usage": {"ad_requests": 200, "ads_filled": 150,
                                "ad_impressions": 120, "ad_clicks": 6,
                                "rewarded_completions": 20,
                                "coins_granted": 900}},
            now=NOW)
        metrics = usage_stats.summary(self.db, now=NOW)["metrics"]
        self.assertLess(metrics["ad_click"], metrics["ad_impression"])
        self.assertLess(metrics["ad_impression"], metrics["ad_fill"])
        self.assertLess(metrics["ad_fill"], metrics["ad_request"])
        self.assertEqual(metrics["coin_granted"], 900.0)
        self.assertEqual(metrics["rewarded_completion"], 20.0)

    def test_fill_and_click_rates_are_derived_from_the_counts(self):
        usage_stats.record_client_usage(
            self.db, {"usage": {"ad_requests": 4, "ads_filled": 2,
                                "ad_impressions": 2, "ad_clicks": 1}}, now=NOW)
        estimate = usage_stats.summary(self.db, now=NOW)["revenue_estimate"]
        self.assertEqual(estimate["ctr"], 0.5)
        self.assertEqual(estimate["rewarded_per_1000_users"], 0.0)


class PlaybackDenominatorTests(TempLedger):
    """The stall rate's denominator must be the population its numerator counts.

    A buffer failure is something the *client* observed, so mixing a client
    numerator with a server-observed `playback_start` gives a rate that is neither
    — which is why `rate_denominator` is printed with the number.
    """

    def test_server_starts_alone_are_the_labeled_fallback(self):
        usage_stats.record_event(self.db, metric="playback_start", count=8, now=NOW)
        usage_stats.record_event(self.db, metric="playback_buffer_failure",
                                 count=2, now=NOW)
        playback = usage_stats.summary(self.db, now=NOW)["playback"]
        self.assertEqual(playback["rate_denominator"], "server_starts")
        self.assertEqual(playback["buffer_failure_rate"], 0.25)
        self.assertEqual(playback["server_stream_starts"], 8.0)
        self.assertEqual(playback["client_playback_attempts"], 0.0)

    def test_client_attempts_prefer_the_matching_population(self):
        usage_stats.record_event(self.db, metric="playback_start", count=8, now=NOW)
        usage_stats.record_client_usage(
            self.db, {"usage": {"playback_attempts": 20,
                                "playback_buffer_failures": 4}}, now=NOW)
        playback = usage_stats.summary(self.db, now=NOW)["playback"]
        self.assertEqual(playback["rate_denominator"], "client_attempts")
        self.assertEqual(playback["buffer_failure_rate"], 0.2)
        self.assertEqual(playback["server_stream_starts"], 8.0)

    def test_no_plays_at_all_is_a_none_not_a_zero_rate(self):
        playback = usage_stats.summary(self.db, now=NOW)["playback"]
        self.assertIsNone(playback["buffer_failure_rate"])
        self.assertEqual(playback["buffer_failures"], 0.0)


class RevenueTests(TempLedger):
    def test_the_estimate_prints_its_assumptions(self):
        out = usage_stats.revenue_estimate(
            metrics={"ad_impression": 1000, "ad_click": 50,
                     "rewarded_completion": 10}, users=100, days=30)
        self.assertTrue(out["estimate"])
        self.assertEqual(out["assumptions"]["ecpm_usd"], 0.9)
        self.assertEqual(out["assumptions"]["basis"],
                         "impressions x eCPM — not a network report")
        self.assertEqual(out["ad_usd_in_window"], 0.9)
        self.assertEqual(out["ad_usd_per_1000_users"], 9.0)
        self.assertEqual(out["ad_usd_per_1000_users_per_day"], 0.3)
        self.assertEqual(out["ctr"], 0.05)
        self.assertEqual(out["rewarded_per_1000_users"], 100.0)

    def test_the_band_and_the_fx_rate_are_overridable(self):
        os.environ["RADD_AD_ECPM_USD"] = "1.5"
        os.environ["RADD_PKR_PER_USD"] = "300"
        out = usage_stats.revenue_estimate(metrics={"ad_impression": 1000},
                                           users=100, days=1)
        self.assertEqual(out["assumptions"]["ecpm_usd"], 1.5)
        self.assertEqual(out["assumptions"]["pkr_per_usd"], 300.0)
        for name in ("RADD_AD_ECPM_USD", "RADD_PKR_PER_USD"):
            del os.environ[name]

    def test_a_garbage_environment_value_falls_back_instead_of_raising(self):
        os.environ["RADD_AD_ECPM_USD"] = "not-a-number"
        out = usage_stats.revenue_estimate(metrics={"ad_impression": 1},
                                           users=1, days=1)
        self.assertEqual(out["assumptions"]["ecpm_usd"], 0.9)
        del os.environ["RADD_AD_ECPM_USD"]

    def test_an_empty_population_is_never_a_division_by_zero(self):
        out = usage_stats.revenue_estimate(metrics={}, users=0, days=0)
        self.assertEqual(out["ad_usd_in_window"], 0.0)
        self.assertIsNone(out["ctr"])
        self.assertEqual(out["assumptions"]["window_days"], 1.0)


# ── the temporal fixture behind every window assertion ──────────────────────

class WindowReportTests(TempLedger):
    """Six devices, written to a known clock, so each number below is derivable.

    ╔═══════════╦═══════════════╦═══════════════╦════════╦════════╦════════════╗
    ║ bucket    ║ installed     ║ last seen     ║ live   ║ DAU    ║ cohort      ║
    ╬═══════════╬═══════════════╬═══════════════╬════════╬════════╬════════════╣
    ║ A install ║ NOW-35d       ║ NOW-20d       ║ no     ║ no     ║ D1,D7,D30   ║
    ║ B install ║ NOW-40d       ║ NOW-5d        ║ no     ║ no     ║ D1,D7,D30   ║
    ║ C header  ║ NOW-2min      ║ NOW-2min      ║ 5m     ║ yes    ║ too new     ║
    ║ D cred    ║ NOW           ║ NOW           ║ 5m     ║ yes    ║ too new     ║
    ║ E header  ║ NOW-40min     ║ NOW-40min     ║ 60m    ║ yes    ║ too new     ║
    ║ F header  ║ NOW-10d       ║ NOW-9d        ║ no     ║ no     ║ D1,D7       ║
    ╚═══════════╩═══════════════╩═══════════════╩════════╩════════╩════════════╝
    """

    def setUp(self):
        super().setUp()
        self.a = usage_stats.record_seen(self.db, install_id="iid-A",
                                         now=NOW - 35 * DAY)
        usage_stats.record_seen(self.db, install_id="iid-A", now=NOW - 20 * DAY)
        usage_stats.record_seen(self.db, install_id="iid-B", now=NOW - 40 * DAY)
        usage_stats.record_seen(self.db, install_id="iid-B", now=NOW - 5 * DAY)
        usage_stats.record_seen(self.db, install_id="iid-C", headers=PK_HEADERS,
                                now=NOW - 120)
        usage_stats.record_seen(self.db, credential="key-D",
                                credential_is_known=True, now=NOW)
        usage_stats.record_seen(self.db, install_id="iid-E", headers=PK_HEADERS,
                                now=NOW - 2400)
        usage_stats.record_seen(self.db, install_id="iid-F", now=NOW - 10 * DAY)
        usage_stats.record_seen(self.db, install_id="iid-F", now=NOW - 9 * DAY)

    def test_installs_are_a_distinct_device_count_not_a_request_count(self):
        installs = usage_stats.summary(self.db, now=NOW)["installs"]
        self.assertEqual(installs["distinct_devices"], 6)
        self.assertEqual(installs["new_today"], 3)          # C, D, E
        # …and the 30-day window adds nobody: A and B installed 35 and 40 days
        # back, F 10 days back but F IS in the window, so 4 of the 6 installs are
        # recent and the two aged-out ones are what `distinct_devices` sees extra.
        self.assertEqual(installs["new_this_window"], 4)     # C, D, E, F

    def test_live_sessions_are_the_three_windows_the_owner_asked_for(self):
        live = usage_stats.summary(self.db, now=NOW)["live_sessions"]
        self.assertEqual(set(live), {"5m", "30m", "60m"})
        self.assertEqual(live["5m"], 2)      # C, D
        self.assertEqual(live["30m"], 2)     # C, D (E at 40 min is outside)
        self.assertEqual(live["60m"], 3)     # C, D, E

    def test_active_users_are_rolling_not_calendar(self):
        active = usage_stats.summary(self.db, now=NOW)["active_users"]
        # dau: C, D, E (all seen within the last day).
        # wau adds B, last seen 5 days ago — a calendar-week query would have
        # dropped B into "last week" and under-counted.
        # mau adds A, last seen 20 days ago.
        self.assertEqual(active, {"dau": 3, "wau": 4, "mau": 6})

    def test_a_device_only_moved_by_max_cannot_re_enter_a_window(self):
        """`last_seen_at` is a maximum, so replaying an old visit must not
        silently drop a live device out of DAU."""
        before = usage_stats.summary(self.db, now=NOW)["active_users"]["dau"]
        usage_stats.record_seen(self.db, install_id="iid-C", now=NOW - 3 * DAY)
        self.assertEqual(usage_stats.summary(self.db, now=NOW)["active_users"]["dau"],
                         before)

    def test_retention_divides_only_by_the_cohort_that_had_the_chance(self):
        retention = usage_stats.summary(self.db, now=NOW)["retention"]
        self.assertEqual(retention["d1"]["cohort_installs"], 3)   # A, B, F
        self.assertEqual(retention["d1"]["returned"], 3)
        self.assertEqual(retention["d1"]["rate"], 1.0)
        self.assertEqual(retention["d7"]["cohort_installs"], 3)
        self.assertEqual(retention["d7"]["returned"], 2)          # F returned on day 1 only
        self.assertEqual(retention["d7"]["rate"], round(2 / 3, 4))
        self.assertEqual(retention["d30"]["cohort_installs"], 2)  # A, B
        self.assertEqual(retention["d30"]["returned"], 1)         # B only; A stopped at day 15
        self.assertEqual(retention["d30"]["rate"], 0.5)

    def test_a_brand_new_install_is_absent_from_every_cohort(self):
        """The classic way this chart lies: growth drags the rate down because
        yesterday's installs cannot have returned on day 30 yet."""
        usage_stats.record_seen(self.db, install_id="iid-new", now=NOW)
        retention = usage_stats.summary(self.db, now=NOW)["retention"]
        self.assertEqual(retention["d30"]["cohort_installs"], 2)

    def test_sessions_count_device_days_not_requests(self):
        metrics = usage_stats.summary(self.db, now=NOW, window_days=30)["metrics"]
        # Aged-out writes (A at -35d, B at -40d) sit outside the 30-day window;
        # inside it: A(-20d), B(-5d), F(-10d), F(-9d), E, C, D = 7.
        self.assertEqual(metrics["session"], 7.0)
        # Every write is one `account_request`, but A's install day (-35) and B's
        # (-40) sit outside a 30-day window, so 7 of the 9 are in the report.
        self.assertEqual(metrics["account_request"], 7.0)

    def test_a_window_narrows_metric_days_without_narrowing_installs(self):
        one_day = usage_stats.summary(self.db, now=NOW, window_days=1)
        self.assertEqual(one_day["installs"]["distinct_devices"], 6)
        self.assertEqual(one_day["metrics"]["session"], 3.0)   # C, E(-40min), D
        self.assertNotIn("playback_start", one_day["metrics"])

    def test_per_dimension_counts_are_distinct_installs_per_value(self):
        report = usage_stats.summary(self.db, now=NOW)
        self.assertEqual(report["per_dimension_installed"]["geo"],
                         {"PK": 2, usage_stats.UNKNOWN_VALUE: 4})
        self.assertEqual(report["per_dimension_installed"]["app_version"],
                         {"1.4.2": 2, usage_stats.UNKNOWN_VALUE: 4})
        self.assertEqual(report["per_dimension_installed"]["device_class"],
                         {"phone": 2, usage_stats.UNKNOWN_VALUE: 4})
        active = report["per_dimension_active"]["geo"]
        self.assertEqual(active, {"PK": 2, usage_stats.UNKNOWN_VALUE: 1})

    def test_accounts_come_from_the_same_ledger_as_devices(self):
        accounts.create_account(self.db, key=sync_key("one"))
        report = usage_stats.summary(self.db, now=NOW)["accounts"]
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["revoked"], 0)
        self.assertEqual(report["vip_active"], 0)


class AccountsCounterTests(TempLedger):
    def test_vip_and_revoked_are_read_at_report_time(self):
        accounts.create_account(self.db, key=sync_key("vip"))
        accounts.create_account(self.db, key=sync_key("gone"))
        with self.conn() as conn:
            conn.execute("UPDATE user_accounts SET vip_until = ? WHERE id = 1",
                         (NOW + DAY,))
            conn.execute("UPDATE user_accounts SET revoked_at = ? WHERE id = 2",
                         (NOW,))
            conn.commit()
        report = usage_stats.summary(self.db, now=NOW)["accounts"]
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["revoked"], 1)
        self.assertEqual(report["vip_active"], 1)
        # …and a VIP that has lapsed by the time the operator reads it is not
        # counted as active, even though the row still carries the old expiry.
        lapsed = usage_stats.summary(self.db, now=NOW + 2 * DAY)["accounts"]
        self.assertEqual(lapsed["vip_active"], 0)


class PaymentsCounterTests(TempLedger):
    """Pass purchases by tier, straight from the approval queue that already
    exists — `usage_stats` does not keep a second money ledger."""

    def setUp(self):
        super().setUp()
        self.ledger = accounts.connect(self.db)
        self.addCleanup(self.ledger.close)

    def file(self, plan, label):
        created = accounts.create_account(self.ledger, key=sync_key(label))
        return payments.submit_payment(self.ledger, created["account_id"],
                                       plan=plan, method="jazzcash",
                                       tid="12345678%02d" % (len(label) + 10),
                                       now=NOW)

    def test_approved_purchases_split_by_tier_and_sum_the_money(self):
        """`amount_pkr` is an `INTEGER` column (`accounts.py:462`), PKR is priced in
        whole rupees, and every other reader of this queue casts it with `int()`
        (`payments.payment_detail`). The aggregate therefore leaves this module an
        `int` too: a `float` here is a whole rupee count that has been put through a
        binary fraction on the way to being printed as money."""
        approved = self.file("vip_yearly", "a")
        month = self.file("vip_monthly", "b")
        self.file("vip_yearly", "c")           # left pending
        payments.approve_payment(self.ledger, approved["payment_id"],
                                 reviewer="op", now=NOW)
        payments.approve_payment(self.ledger, month["payment_id"], reviewer="op",
                                 now=NOW)
        report = usage_stats.summary(self.db, now=NOW)["payments"]
        self.assertEqual(report["by_tier"],
                         {"vip_yearly": {"purchases": 1, "amount_pkr": 1500},
                          "vip_monthly": {"purchases": 1, "amount_pkr": 200}})
        for tier in report["by_tier"].values():
            self.assertIs(type(tier["amount_pkr"]), int,
                          "money in this projection is whole rupees, never a float")
        self.assertIs(type(report["total_pkr"]), int)
        self.assertEqual(report["purchases"], 2)      # approved claims, not the queue
        self.assertEqual(report["pending"], 1)
        self.assertEqual(report["total_pkr"],
                         payments.default_price("vip_yearly")
                         + payments.default_price("vip_monthly"))

    def test_a_rejected_claim_is_never_counted_as_money(self):
        claim = self.file("vip_monthly", "d")
        payments.reject_payment(self.ledger, claim["payment_id"], reviewer="op",
                                note="no such transaction", now=NOW)
        report = usage_stats.summary(self.db, now=NOW)["payments"]
        self.assertEqual(report["purchases"], 0)
        self.assertEqual(report["total_pkr"], 0)
        self.assertEqual(report["pending"], 0)
        self.assertEqual(report["by_tier"], {})

    def test_an_empty_queue_is_zeros_not_a_missing_key(self):
        report = usage_stats.summary(self.db, now=NOW)["payments"]
        self.assertEqual(report["purchases"], 0)
        self.assertEqual(report["total_pkr"], 0)
        self.assertEqual(report["by_tier"], {})


class HonestyTests(TempLedger):
    """A count the client has never sent is an absence, and the payload says so."""

    def test_an_empty_ledger_is_not_presented_as_a_measurement(self):
        report = usage_stats.summary(self.db, now=NOW)
        self.assertFalse(report["available"])
        self.assertTrue(report["no_usage_data_yet"])

    def test_reported_only_families_are_listed_as_pending_until_they_arrive(self):
        report = usage_stats.summary(self.db, now=NOW)
        self.assertEqual(set(report["sources"]["reported_by_client"]),
                         set(usage_stats.REPORTED_ONLY))
        self.assertEqual(set(report["sources"]["observed_by_server"]),
                         set(usage_stats.METRICS) - set(usage_stats.REPORTED_ONLY))
        self.assertEqual(set(report["sources"]["reported_by_client_pending"]),
                         set(usage_stats.REPORTED_ONLY))
        usage_stats.record_client_usage(self.db, {"usage": {"crashes": 1}}, now=NOW)
        after = usage_stats.summary(self.db, now=NOW)
        self.assertNotIn("crash", after["sources"]["reported_by_client_pending"])
        self.assertIn("ad_click", after["sources"]["reported_by_client_pending"])

    def test_the_payload_states_the_identity_and_the_fallback(self):
        identity = usage_stats.summary(self.db, now=NOW)["identity"]
        self.assertIs(identity["ip_stored"], False)
        self.assertIs(identity["per_person_timeline"], False)
        self.assertIn("salted sha256", identity["device_key"])
        self.assertIn("X-Install-Id", identity["note"])


# ── rule 1 and rule 3, proven against the schema rather than the numbers ────

class AggregateOnlySchemaTests(TempLedger):
    #: One row per device, and nothing that could assemble a device's history.
    DEVICE_COLUMNS = {"device_hash", "install_day", "first_seen_at",
                      "last_seen_at", "geo", "locale", "app_version",
                      "device_class", "retained_1", "retained_7", "retained_30"}
    #: An address, a name, or a per-device day would each break rule 1. `day` is
    #: legal in the *metric* tables (that is the aggregation) and forbidden in the
    #: device table (that would be the timeline), so the two are checked apart.
    NEVER = ("ip", "ip_address", "remote_addr", "x_real_ip", "email", "phone",
             "name", "username", "user_id", "account_id", "uid")

    def setUp(self):
        super().setUp()
        # The three tables appear on the first write, which is the point: an unused
        # ledger has no usage schema yet, so a schema assertion must install one by
        # counting something first rather than reading an empty database.
        usage_stats.record_seen(self.db, install_id="iid-schema", now=NOW)
        usage_stats.record_event(self.db, metric="ad_request", dims={"geo": "PK"},
                                 now=NOW)

    def test_no_table_holds_a_device_day_pair(self):
        """A per-device set of days *is* a timeline, however aggregated the read."""
        names = set(self.columns("usage_device"))
        self.assertEqual(names, self.DEVICE_COLUMNS)
        self.assertNotIn("day", names)
        self.assertNotIn("last_seen_day", names)

    def test_device_rows_are_one_per_bucket(self):
        for offset in range(6):
            usage_stats.record_seen(self.db, install_id="iid-same",
                                    now=NOW + offset * 500)
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM usage_device WHERE device_hash = ?",
            usage_stats.device_token("iid-same"))[0][0], 1)

    def test_no_column_names_a_person_an_address_or_a_device_in_metric_tables(self):
        """The metric tables may key on a day because they never key on a device;
        the device table may hold one day because it never holds a set of them."""
        tables = {row[0] for row in
                  self.rows("SELECT name FROM sqlite_master WHERE type='table'"
                            " AND name LIKE 'usage_%'")}
        self.assertEqual(tables, {"usage_device", "usage_metric",
                                  "usage_dim_metric"})
        for table in sorted(tables):
            for column in self.columns(table):
                self.assertNotIn(column.lower(), self.NEVER,
                                 "%s.%s" % (table, column))
        for table in ("usage_metric", "usage_dim_metric"):
            self.assertNotIn("device_hash", self.columns(table), table)
            self.assertNotIn("device_class", self.columns(table), table)

    def test_metric_rows_are_bounded_by_days_not_by_requests(self):
        """The counters are keyed by (day, metric), so the table cannot grow with
        traffic — that is what makes rule 3 true instead of merely intended."""
        for _ in range(50):
            usage_stats.record_event(self.db, metric="ad_fill", count=1, now=NOW)
        self.assertEqual(self.rows(
            "SELECT COUNT(*) FROM usage_metric WHERE metric = 'ad_fill'")[0][0], 1)
        self.assertEqual(self.rows(
            "SELECT total FROM usage_metric WHERE metric = 'ad_fill'")[0][0], 50)

    def test_the_report_needs_no_catalog_tables(self):
        """A ledger file with only the accounts schema still answers, because
        nothing in `summary()` reaches for `posts`/`releases`/`links`."""
        for table in ("posts", "media_ledger", "releases", "download_sources"):
            self.assertEqual(self.rows(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                table), [], table)
        usage_stats.record_event(self.db, metric="playback_start", count=4, now=NOW)
        report = usage_stats.summary(self.db, now=NOW)
        self.assertEqual(report["metrics"]["playback_start"], 4.0)
        self.assertTrue(Path(self.db).exists())


class PanelWiringTests(TempLedger):
    """The screen is reachable only behind the operator gate, and only as
    aggregates — the panel must not become a way to export a device list."""

    def setUp(self):
        super().setUp()
        self.old_token = os.environ.get(TOKEN_ENV)
        os.environ[TOKEN_ENV] = "q3-panel-token"
        self.addCleanup(self._restore_token)

    def _restore_token(self):
        if self.old_token is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = self.old_token

    def screen(self, path="/admin/usage", query="", cookie=""):
        return admin_panel.route_get(path, urllib.parse.parse_qs(query),
                                     db_path=str(Path(self.tmp.name) / "catalog.db"),
                                     peer_address="127.0.0.1",
                                     token_header="Bearer q3-panel-token",
                                     state_db_path=self.db, cookie_header=cookie)

    def test_the_usage_screen_answers_on_the_operator_peer(self):
        usage_stats.record_seen(self.db, install_id="iid-1", headers=PK_HEADERS,
                                now=NOW)
        status, content_type, body = self.screen()
        self.assertEqual(status, 200)
        self.assertIn("html", content_type)
        self.assertIn(b"distinct installs", body)
        self.assertIn(b"Devices", body)
        self.assertIn(b"Aggregates only", body)
        text = body.decode("utf-8")
        self.assertIn("1.4.2", text)                       # the version it counted
        self.assertNotIn(usage_stats.device_token("iid-1"), text)   # not the bucket

    def test_the_json_screen_carries_the_same_aggregates(self):
        usage_stats.record_seen(self.db, install_id="iid-1", now=NOW)
        status, content_type, body = self.screen("/admin/api/usage")
        self.assertEqual((status, content_type), (200, admin_panel.CONTENT_JSON))
        payload = json.loads(body)
        self.assertEqual(payload["installs"]["distinct_devices"], 1)
        self.assertIs(payload["identity"]["ip_stored"], False)

    def test_a_window_query_is_clamped(self):
        status, _, body = self.screen("/admin/api/usage", query="window=99999")
        self.assertLessEqual(json.loads(body)["window_days"],
                             admin_panel.USAGE_WINDOW_DAYS)
        self.assertEqual(status, 200)

    def test_the_page_escapes_dimension_text(self):
        usage_stats.record_seen(
            self.db, install_id="iid-1",
            headers={"X-Device-Class": "<img src=x onerror=alert(1)>"}, now=NOW)
        # `clean_value` refuses the shape, so the raw tag never reaches storage:
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device WHERE"
                                   " device_class = 'unknown'")[0][0], 1)
        _, _, body = self.screen()
        self.assertNotIn(b"<img src=x", body)

    def test_a_non_loopback_peer_is_refused_the_screen_entirely(self):
        refusal = admin_panel.route_get(
            "/admin/usage", {}, db_path="catalog.db",
            peer_address="203.0.113.9", token_header="Bearer q3-panel-token",
            state_db_path=self.db)
        self.assertEqual(refusal[0], 403)   # refused before any SQL, off loopback

    def test_a_missing_token_is_refused_the_usage_screen(self):
        for token_header in ("", "Bearer wrong"):
            answered = admin_panel.route_get(
                "/admin/usage", {}, db_path="catalog.db",
                peer_address="127.0.0.1", token_header=token_header,
                state_db_path=self.db)
            self.assertEqual(answered[0], 401, token_header)
            self.assertNotIn(b"distinct_devices", answered[2])

    def test_a_minted_session_cookie_opens_the_usage_screen(self):
        """Minted against the wall clock, because the gate validates against the
        wall clock: `NOW` is a fixture instant, and a session expired *relative to
        a fixture* is not expired for the code under test."""
        jar = admin_panel.operator_session_cookie("q3-panel-token")
        value = jar.split(";")[0]
        answered = admin_panel.route_get(
            "/admin/usage", {}, db_path="catalog.db",
            peer_address="127.0.0.1", token_header="",
            state_db_path=self.db, cookie_header=value)
        self.assertEqual(answered[0], 200)
        stale = admin_panel.route_get(
            "/admin/usage", {}, db_path="catalog.db",
            peer_address="127.0.0.1", token_header="",
            state_db_path=self.db,
            cookie_header=admin_panel.operator_session_cookie(
                "q3-panel-token",
                now=time.time() - 9 * 3600).split(";")[0])
        self.assertEqual(stale[0], 401)


class GateTests(TempLedger):
    """Item B: the token is the boundary of the operator port, not a lock on one
    page of it. A missing or bogus credential is refused before any route is
    consulted, and a minted session survives its own issue second."""

    TOKEN = "q3-gate-token"

    def setUp(self):
        super().setUp()
        self.old_token = os.environ.get(TOKEN_ENV)
        os.environ[TOKEN_ENV] = self.TOKEN
        self.addCleanup(self._restore)

    def _restore(self):
        if self.old_token is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = self.old_token

    def gate(self, *, authorization="", cookie="", query_token="",
             peer="127.0.0.1"):
        """The refusal *status*, or ``None`` when the gate let the caller pass —
        so a passing assertion never indexes into ``None``."""
        refusal = admin_panel.gate_operator_port(
            peer, authorization=authorization, cookie=cookie,
            query_token=query_token)[0]
        return None if refusal is None else refusal[0]

    def test_no_credential_at_all_is_refused(self):
        self.assertEqual(self.gate(), 401)

    def test_a_bogus_token_is_refused(self):
        self.assertEqual(self.gate(authorization="Bearer not-the-token"), 401)

    def test_the_real_token_is_accepted(self):
        self.assertIsNone(self.gate(authorization="Bearer " + self.TOKEN))

    def test_a_query_token_opens_the_port_once(self):
        """The dashboard's own entry link carries `?token=`, which is how an
        operator who has no cookie yet gets in; it is still the same secret."""
        self.assertIsNone(self.gate(query_token=self.TOKEN))

    def test_a_session_minted_by_the_gate_opens_every_later_request(self):
        refused, jar = admin_panel.gate_operator_port(
            "127.0.0.1", authorization="Bearer " + self.TOKEN)
        self.assertIsNone(refused)
        self.assertTrue(jar)
        value = jar.split(";")[0]
        self.assertIsNone(self.gate(cookie=value))

    def test_a_session_still_valid_one_second_later(self):
        """The bug this catches: re-deriving the expiry at validation time signs
        a *new* value, so the cookie only ever matched inside its own second."""
        value = admin_panel.mint_operator_session(self.TOKEN, now=NOW)
        self.assertTrue(admin_panel.operator_session_valid(value, self.TOKEN,
                                                           now=NOW + 1))
        self.assertTrue(admin_panel.operator_session_valid(
            value, self.TOKEN, now=NOW + admin_panel.OPERATOR_SESSION_TTL - 1))

    def test_expiry_and_signature_are_both_enforced(self):
        minted = admin_panel.mint_operator_session(self.TOKEN, now=NOW)
        self.assertFalse(admin_panel.operator_session_valid(
            minted, self.TOKEN, now=NOW + admin_panel.OPERATOR_SESSION_TTL + 1))
        expired = admin_panel.mint_operator_session(self.TOKEN,
                                                   now=NOW - 9 * 3600)
        self.assertFalse(admin_panel.operator_session_valid(expired, self.TOKEN,
                                                            now=NOW))
        forged = minted.rsplit(".", 1)[0] + "." + "0" * 32
        self.assertFalse(admin_panel.operator_session_valid(forged, self.TOKEN,
                                                            now=NOW))
        self.assertFalse(admin_panel.operator_session_valid(
            admin_panel.mint_operator_session("a-different-token"), self.TOKEN,
            now=NOW))

    def test_malformed_cookie_values_fail_closed(self):
        for value in ("", ".", "abc", "notanumber.sig", "123.",
                      "no-dot-here", "%s.%s" % (NOW + 99999, "z" * 64)):
            self.assertFalse(admin_panel.operator_session_valid(value, self.TOKEN,
                                                               now=NOW), value)

    def test_a_short_token_in_the_header_cannot_be_a_prefix_match(self):
        """`Bearer q3-gate` is a prefix of the real token; equality or nothing."""
        self.assertEqual(self.gate(authorization="Bearer " + self.TOKEN[:8]), 401)

    def test_a_non_loopback_peer_is_refused_even_with_the_token(self):
        self.assertEqual(self.gate(authorization="Bearer " + self.TOKEN,
                                   peer="203.0.113.9"), 403)

    def test_the_session_cookie_is_http_only_and_scoped_to_the_path(self):
        jar = admin_panel.operator_session_cookie(self.TOKEN, now=NOW)
        self.assertIn("HttpOnly", jar)
        self.assertIn("Path=/", jar)
        self.assertIn("SameSite=Strict", jar)
        self.assertNotIn("Secure", jar)      # loopback plain HTTP: Secure = unusable

    def test_cookie_parsing_survives_a_malformed_header(self):
        """`SimpleCookie` rejects the whole header for one bad pair, which would
        log an operator out over an unrelated cookie."""
        minted = admin_panel.mint_operator_session(self.TOKEN, now=NOW)
        header = ("other=1; unquoted junk; broken=%; "
                  + admin_panel.OPERATOR_COOKIE + "=" + minted + "; trailing")
        self.assertTrue(admin_panel.operator_session_valid(
            admin_panel.cookie_value(header, admin_panel.OPERATOR_COOKIE),
            self.TOKEN, now=NOW))
        self.assertEqual(admin_panel.cookie_value("", admin_panel.OPERATOR_COOKIE),
                         "")
        self.assertEqual(admin_panel.cookie_value(None, admin_panel.OPERATOR_COOKIE),
                         "")
        self.assertEqual(admin_panel.cookie_value(
            "radd_admin_session=deadbeef; other=1", admin_panel.OPERATOR_COOKIE),
            "deadbeef")


class AccountSurfaceHookTests(TempLedger):
    """The counters are earned where a caller already identified itself, so no new
    public route appears and the reads that cannot authenticate buy no writes.

    These run the real `accounts_api.route_post` against a one-row catalog, so
    what is proved is the wiring and not only the counter: a `work_ref` the server
    minted, a visible non-adult work, and the progress write the app already makes.
    """

    SECRET = "q3-hook-secret"
    WORK_KEY = "series:q3 example work"

    def setUp(self):
        super().setUp()
        self.api = accounts_api
        self.key = sync_key("hook")
        accounts.create_account(self.db, key=self.key)
        # A catalog with the projection schema and exactly one visible work — not
        # the 150k-post file, which is the whole point of rule 3.
        self.catalog = str(Path(self.tmp.name) / "catalog.db")
        with sqlite3.connect(self.catalog) as conn:
            catalog_v2.ensure_schema(conn)
            conn.execute("INSERT INTO cat_works(work_key, title, updated_at,"
                         " is_18_plus) VALUES(?,?,?,0)",
                         (self.WORK_KEY, "Q3 Example Work", NOW))
            conn.commit()
        self.handle = accounts_api._Minter(self.SECRET)(self.WORK_KEY)

    def post(self, path, payload, key=None, headers=None):
        sent = {"Authorization": "Bearer " + (self.key if key is None else key)}
        sent.update(headers or {})
        return self.api.route_post(path, payload, db_path=self.db,
                                   catalog_path=self.catalog, secret=self.SECRET,
                                   headers=sent)

    def progress(self, *, position=10, usage=None, key=None, headers=None):
        body = {"work_ref": self.handle, "position_seconds": position,
                "duration_seconds": 100}
        if usage is not None:
            body["usage"] = usage
        return self.post("/api/v2/account/progress", body, key=key, headers=headers)

    def test_an_authenticated_progress_write_marks_the_device_live(self):
        answered = self.progress(headers={"X-Install-Id": "iid-hook"})
        self.assertEqual(answered[0], 201)
        rows = self.rows("SELECT device_hash FROM usage_device")
        self.assertEqual([row[0] for row in rows],
                         [usage_stats.device_token("iid-hook")])
        report = usage_stats.summary(self.db)
        self.assertEqual(report["metrics"]["account_request"], 1.0)
        self.assertEqual(report["metrics"]["session"], 1.0)

    def test_the_sync_key_is_never_written_to_the_usage_ledger(self):
        self.progress()
        self.assertNotIn(self.key.encode(), self.stored_bytes())

    def test_the_usage_block_rides_the_same_progress_write(self):
        answered = self.progress(usage={"ad_requests": 7, "crashes": 1,
                                       "playback_attempts": 3},
                                 headers={"X-Device-Class": "tv"})
        self.assertEqual(answered[0], 201)
        report = usage_stats.summary(self.db)
        self.assertEqual(report["metrics"]["ad_request"], 7.0)
        self.assertEqual(report["metrics"]["crash"], 1.0)
        self.assertEqual(report["metrics"]["playback_attempt"], 3.0)
        self.assertEqual(report["crash_by_class"], {"tv": 1.0})

    def test_a_progress_write_with_no_usage_block_counts_the_device_only(self):
        self.progress()
        metrics = usage_stats.summary(self.db)["metrics"]
        self.assertEqual(set(metrics), {"account_request", "session"})

    def test_a_request_with_no_credential_marks_no_device(self):
        answered = self.post("/api/v2/account/progress",
                             {"work_ref": self.handle, "position_seconds": 1},
                             key="")
        self.assertEqual(answered[0], 401)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 0)

    def test_a_read_of_the_account_surface_counts_the_device_it_authenticates(self):
        answered = self.api.route_get("/api/v2/account", {}, db_path=self.db,
                                      catalog_path=self.catalog,
                                      secret=self.SECRET,
                                      headers={"Authorization": "Bearer " + self.key,
                                               "Accept-Language": "en-PK"})
        self.assertEqual(answered[0], 200)
        report = usage_stats.summary(self.db)
        self.assertEqual(report["installs"]["distinct_devices"], 1)
        self.assertEqual(report["per_dimension_installed"]["geo"], {"PK": 1})

    def test_a_guessed_key_on_a_get_creates_no_device(self):
        """The route answers 404 for a key it never issued, and the counter does
        not turn that guess into an install."""
        answered = self.api.route_get("/api/v2/account", {}, db_path=self.db,
                                      catalog_path=self.catalog, secret=self.SECRET,
                                      headers={"Authorization": "Bearer "
                                               + sync_key("not-issued")})
        self.assertIn(answered[0], (401, 404), answered[0])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 0)

    def test_a_get_with_no_key_at_all_buys_no_write(self):
        answered = self.api.route_get("/api/v2/account", {}, db_path=self.db,
                                      catalog_path=self.catalog, secret=self.SECRET,
                                      headers={})
        self.assertIn(answered[0], (401, 404), answered[0])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_device")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM usage_metric")[0][0], 0)

    def test_an_exploding_analytics_hook_never_breaks_the_users_save(self):
        """The gate that matters operationally: the counter is a passenger on the
        account surface, so even a hook that raises cannot stop the save."""
        from unittest import mock
        with mock.patch.object(usage_stats, "record_seen",
                               side_effect=RuntimeError("analytics is on fire")):
            answered = self.progress(position=42)
        self.assertEqual(answered[0], 201)
        with accounts.connect(self.db) as conn:
            stored = conn.execute(
                "SELECT position_seconds FROM user_progress LIMIT 1").fetchone()
        self.assertEqual(int(stored[0]), 42)

    def test_a_hook_that_raises_about_the_usage_block_still_saves(self):
        from unittest import mock
        with mock.patch.object(usage_stats, "record_client_usage",
                               side_effect=RuntimeError("no counters today")):
            answered = self.progress(usage={"crashes": 1})
        self.assertEqual(answered[0], 201)
        metrics = usage_stats.summary(self.db)["metrics"]
        self.assertNotIn("crash", metrics)
        self.assertEqual(metrics["account_request"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
