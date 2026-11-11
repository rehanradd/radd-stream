import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import bad_checker, good_checker, make_service  # noqa: E402
from admin_v2 import fixture_app, smart  # noqa: E402
from admin_v2.errors import ApiError  # noqa: E402
from admin_v2.store import _seed  # noqa: E402
from admin_v2.security import check_no_provenance, valid_domain  # noqa: E402


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()

    def test_unknown_field_refused(self):
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"resolver_concurrency": 2, "surprise": 1})

    def test_tuning_out_of_range_refused_and_unchanged(self):
        before = self.svc.get_tuning(self.owner)
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"resolver_concurrency": 99})
        self.assertEqual(self.svc.get_tuning(self.owner), before)

    def test_tuning_zero_rate_limit_refused(self):
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"rate_limit_play_per_min": 0})

    def test_theme_defaults(self):
        tuning = self.svc.get_tuning(self.owner)
        self.assertEqual(tuning["theme_mode"], "dark")
        self.assertEqual(tuning["theme_accent"], "")
        self.assertEqual(tuning["theme_dynamic_color"], 0)
        self.assertEqual(tuning["theme_hero_autoplay"], 1)
        self.assertEqual(tuning["theme_hero_interval_s"], 5)
        self.assertEqual(tuning["hero_max"], 6)

    def test_theme_put_validation(self):
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"theme_mode": "pink"})
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"theme_accent": "red"})
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"theme_accent": "#12345"})
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"hero_max": 7})
        self.svc.put_tuning(self.owner, {"theme_mode": "light",
                                         "theme_accent": "#2BC79A",
                                         "hero_max": 6, "reason": "test"})
        tuning = self.svc.get_tuning(self.owner)
        self.assertEqual(tuning["theme_mode"], "light")
        self.assertEqual(tuning["theme_accent"], "#2BC79A")

    def test_seed_preserves_operator_tuning_on_restart(self):
        # Regression: _seed used to UPDATE every tuning column to defaults
        # on every panel start, wiping operator changes.
        self.svc.put_tuning(self.owner, {"cache_ttl_h": 12, "theme_mode": "light",
                                         "reason": "test"})
        _seed(self.svc.admin)
        tuning = self.svc.get_tuning(self.owner)
        self.assertEqual(tuning["cache_ttl_h"], 12)
        self.assertEqual(tuning["theme_mode"], "light")

    def test_seed_fills_null_new_column_only(self):
        self.svc.put_tuning(self.owner, {"cache_ttl_h": 12, "reason": "test"})
        # Simulate an older database where the theme column was never set.
        self.svc.admin.execute(
            "UPDATE tuning_settings SET theme_mode = NULL WHERE id = 1")
        _seed(self.svc.admin)
        tuning = self.svc.get_tuning(self.owner)
        self.assertEqual(tuning["theme_mode"], "dark")
        self.assertEqual(tuning["cache_ttl_h"], 12)

    def test_adult_switch_on_blocked(self):
        with self.assertRaises(ApiError):
            self.svc.update_content_safety(self.owner, {"adult_content_enabled": True})
        self.assertEqual(self.svc.get_content_safety(self.owner)["adult_content_enabled"], 0)

    def test_adult_card_blocked_in_non_adult_section(self):
        with self.assertRaises(ApiError):
            self.svc.add_card(self.owner, "movie", {"work_id": 3, "position": 0})
        with self.assertRaises(ApiError):
            self.svc.add_card(self.owner, "movie", {"work_id": 4, "position": 0})

    def test_category_delete_blocked_when_in_use(self):
        cat = self.svc.create_category(self.owner, {"key": "comedy", "display_name": "Comedy"})
        self.svc.assign_category_work(self.owner, "comedy", {"work_id": 1, "position": 0})
        with self.assertRaises(ApiError):
            self.svc.delete_category(self.owner, "comedy")

    def test_home_empty_publish_blocked(self):
        for key in ("hero", "trending", "movie", "series"):
            self.svc.delete_section(self.owner, key)
        with self.assertRaises(ApiError):
            self.svc.publish_remote_config(self.owner, {"confirm": True})

    def test_domain_validate_fail_blocks_apply(self):
        self.svc.add_candidate(self.owner, "multimovies", {"domain": "example.org"})
        self.svc.validate_domain(self.owner, "multimovies", {"domain": "example.org"}, checker=bad_checker)
        with self.assertRaises(ApiError):
            self.svc.apply_domain(self.owner, "multimovies", {"domain": "example.org", "confirm": True})

    def test_domain_format_rejects_scheme_and_path(self):
        self.assertFalse(valid_domain("https://example.org/path"))
        self.assertFalse(valid_domain("example.org/path?x=1"))
        self.assertTrue(valid_domain("example.org"))

    def test_visibility_overlay_and_restore(self):
        self.assertFalse(self.svc.is_work_hidden(1))
        vis = self.svc.hide_content(self.owner, {"scope": "work", "scope_id": "1", "reason": "owner"})
        self.assertTrue(self.svc.is_work_hidden(1))
        self.svc.unhide_content(self.owner, vis["id"], {})
        self.assertFalse(self.svc.is_work_hidden(1))

    def test_pause_vs_disable_single_state(self):
        p = self.svc.pause(self.owner, {"target_type": "section", "target_id": "movie", "reason": "test pause"})
        self.assertTrue(self.svc.is_paused("section", "movie"))
        with self.assertRaises(ApiError):
            self.svc.pause(self.owner, {"target_type": "section", "target_id": "movie", "reason": "again"})
        self.svc.resume_pause(self.owner, p["id"])
        self.assertFalse(self.svc.is_paused("section", "movie"))

    def test_config_version_bump_on_publish_only(self):
        v0 = self.svc._config_row()["config_version"]
        self.svc.draft_remote_config(self.owner, {"brand_primary": "#123456"})
        self.assertEqual(self.svc._config_row()["config_version"], v0)
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        self.assertEqual(self.svc._config_row()["config_version"], v0 + 1)

    def test_history_append_only(self):
        v0 = self.svc._config_row()["config_version"]
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        rows = self.svc.admin.execute(
            "SELECT COUNT(*) AS n FROM app_remote_config_history").fetchone()["n"]
        self.assertGreaterEqual(rows, 2)
        # A rollback must create a NEW version, never edit history.
        self.svc.rollback_remote_config(self.owner, {"version": v0, "confirm": True})
        self.assertEqual(self.svc._config_row()["config_version"], v0 + 2)

    def test_redaction_fails_closed(self):
        self.assertFalse(check_no_provenance({"data": {"url": "https://example.org/x"}}))
        self.assertFalse(check_no_provenance({"token": "abc"}))
        self.assertTrue(check_no_provenance({"title": "MOCK Movie One", "id": 1}))

    def test_dashboard_expired_cache_is_recomputed_not_served_stale(self):
        # An expired dashboard row WITHOUT the live marker is never
        # served, even inside its old stale window: a stale row can
        # predate the live wiring (fixture counts, hardcoded cert date,
        # lowercase needs text), so expiry must always recompute from
        # the live stores. (D2.4: rows the live path marked DO serve
        # stale — see the test below.)
        import json as _json, time as _t
        d = self.svc.dashboard(self.owner)
        self.assertEqual(d["quality"], "full")
        now = int(_t.time())
        stale = dict(d)
        stale["pending_payments"] = 999
        stale["cert_expiry"] = "2027-01-31"
        stale["needs_you_now"] = ["pending payments: 999"]
        self.svc.admin.execute(
            "UPDATE dashboard_cache SET value_json=?, expires_at=?, stale_until=? "
            "WHERE cache_key='dashboard'",
            (_json.dumps(stale), now - 10, now + 3600))
        self.svc.admin.commit()
        d2 = self.svc.dashboard(self.owner)
        self.assertEqual(d2["quality"], "full")
        self.assertNotEqual(d2["pending_payments"], 999)
        self.assertNotEqual(d2["cert_expiry"], "2027-01-31")
        self.assertTrue(all(
            not n.startswith("pending payments:") for n in d2["needs_you_now"]))

    def test_dashboard_serves_stale_only_for_live_marked_rows(self):
        # D2.4: an expired row the live path wrote (cache_origin ==
        # "live") serves stale with its age; the same row without the
        # marker recomputes, exactly as before.
        import json as _json, time as _t
        d = self.svc.dashboard(self.owner)
        self.assertEqual(d["quality"], "full")
        now = int(_t.time())
        row = self.svc.admin.execute(
            "SELECT value_json FROM dashboard_cache "
            "WHERE cache_key='dashboard'").fetchone()
        stored = _json.loads(row["value_json"])
        stored["cache_origin"] = "live"
        stored["pending_payments"] = 999
        self.svc.admin.execute(
            "UPDATE dashboard_cache SET value_json=?, expires_at=?, stale_until=? "
            "WHERE cache_key='dashboard'",
            (_json.dumps(stored), now - 10, now + 3600))
        self.svc.admin.commit()
        d2 = self.svc.dashboard(self.owner)
        self.assertEqual(d2["quality"], "stale")
        self.assertEqual(d2["pending_payments"], 999)
        self.assertIn("stale_age_s", d2)
        self.assertGreaterEqual(d2["stale_age_s"], 0)
        self.assertNotIn("cache_origin", d2)
        # Same row without the marker: recompute, never served stale.
        stored.pop("cache_origin", None)
        self.svc.admin.execute(
            "UPDATE dashboard_cache SET value_json=?, expires_at=?, stale_until=? "
            "WHERE cache_key='dashboard'",
            (_json.dumps(stored), now - 10, now + 3600))
        self.svc.admin.commit()
        d3 = self.svc.dashboard(self.owner)
        self.assertEqual(d3["quality"], "full")
        self.assertNotEqual(d3["pending_payments"], 999)

    def test_dashboard_cache_ttl_is_600s(self):
        # D2.4: fresh rows live 10 min, not 60 s.
        self.svc.dashboard(self.owner)
        row = self.svc.admin.execute(
            "SELECT expires_at, stale_until, created_at FROM dashboard_cache "
            "WHERE cache_key='dashboard'").fetchone()
        self.assertEqual(row["expires_at"] - row["created_at"], 600)
        self.assertEqual(row["stale_until"] - row["created_at"], 3600)

    def test_dashboard_refresh_rewrites_expired_row(self):
        # D2.4: the background refresh recomputes an expired row and
        # rewrites it fresh with the live marker; a fresh row is left alone.
        import json as _json, time as _t
        self.svc.dashboard(self.owner)
        now = int(_t.time())
        self.svc.admin.execute(
            "UPDATE dashboard_cache SET expires_at=? WHERE cache_key='dashboard'",
            (now - 10,))
        self.svc.admin.commit()
        self.assertTrue(self.svc.refresh_dashboard_cache())
        row = self.svc.admin.execute(
            "SELECT value_json, expires_at FROM dashboard_cache "
            "WHERE cache_key='dashboard'").fetchone()
        self.assertGreater(row["expires_at"], now)
        self.assertEqual(_json.loads(row["value_json"])["cache_origin"], "live")
        self.assertFalse(self.svc.refresh_dashboard_cache())

    def test_dashboard_refresh_single_flight(self):
        # D2.4: a refresh already in progress makes a second call a
        # no-op instead of a second recompute.
        from admin_v2.services import _DASHBOARD_REFRESH_LOCK
        self.svc.dashboard(self.owner)
        with _DASHBOARD_REFRESH_LOCK:
            self.assertFalse(self.svc.refresh_dashboard_cache())

    def test_cache_swr_and_jitter(self):
        smart.cache_put(self.svc.admin, "k1", "direct_resumable", {"ok": True}, 3600)
        value, quality = smart.cache_get(self.svc.admin, "k1")
        self.assertEqual((value, quality), ({"ok": True}, "full"))
        import time as _t
        self.svc.admin.execute(
            "UPDATE resolved_cache SET expires_at=?, stale_until=? WHERE cache_key='k1'",
            (int(_t.time()) - 10, int(_t.time()) + 3600))
        self.svc.admin.commit()
        value, quality = smart.cache_get(self.svc.admin, "k1")
        self.assertEqual(quality, "stale")

    def test_circuit_transport_does_not_open(self):
        for _ in range(5):
            smart.record_circuit(self.svc.admin, "host-a", False, "transport")
        row = self.svc.admin.execute(
            "SELECT * FROM circuits WHERE backend='host-a'").fetchone()
        self.assertEqual(row["state"], "closed")
        self.assertGreater(row["transport_strikes"], 0)
        for _ in range(3):
            smart.record_circuit(self.svc.admin, "host-b", False, "host")
        row = self.svc.admin.execute(
            "SELECT * FROM circuits WHERE backend='host-b'").fetchone()
        self.assertEqual(row["state"], "open")

    def test_direct_first_early_exit(self):
        cands = [{"backend": "complex", "kind": "complex_bridge"},
                 {"backend": "direct", "kind": "direct_resumable"},
                 {"backend": "simple", "kind": "simple_bridge"}]
        winner, skipped, quality = fixture_app.play_candidates(
            self.svc, cands, lambda c: c["backend"] == "direct")
        self.assertEqual(winner["backend"], "direct")
        self.assertEqual(quality, "full")
        self.assertTrue(any("not probed" in s for s in skipped))

    def test_job_queue_cap_and_dead_letter(self):
        from admin_v2 import smart as _s
        for i in range(3):
            _s.enqueue_job(self.svc.admin, "reprobe", {}, "job-%d" % i, self.owner["id"])
        job = self.svc.admin.execute("SELECT * FROM jobs WHERE idempotency_key='job-0'").fetchone()
        for _ in range(3):
            _s.run_job_once(self.svc.admin, dict(job), lambda j: (_ for _ in ()).throw(RuntimeError("boom")))
            job = self.svc.admin.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        self.assertEqual(job["status"], "dead")


class TestMigrationsV4V5(unittest.TestCase):
    """Migrations v4/v5 (admin-panel audit §Live): the live DB applied
    v1 BEFORE scheduled_publishes was added to v1's SQL, so it never
    got the table and /admin/live 500'd. v4 creates it; v5 adds the
    coin + redirect columns. Never append to an applied migration."""

    def _live_like_db(self):
        """A DB in the live DB's exact pre-fix state: v1 SQL with the
        scheduled_publishes CREATE stripped, then v2+v3 applied."""
        import re
        import sqlite3
        from admin_v2.store import MIGRATIONS
        v1 = MIGRATIONS[0][1]
        stripped = re.sub(
            r"CREATE TABLE IF NOT EXISTS scheduled_publishes \(.*?\);\n",
            "", v1, flags=re.S)
        self.assertNotIn("scheduled_publishes", stripped)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(stripped)
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        for version, sql in MIGRATIONS[1:3]:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)",
                         (version,))
        conn.commit()
        return conn

    def test_v4_creates_scheduled_publishes_on_live_like_db(self):
        from admin_v2.store import migrate
        conn = self._live_like_db()
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                         "AND name='scheduled_publishes'").fetchone()[0], 0)
        migrate(conn)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                         "AND name='scheduled_publishes'").fetchone()[0], 1)
        self.assertEqual(
            [r[0] for r in conn.execute(
                "SELECT version FROM schema_version ORDER BY version")],
            [1, 2, 3, 4, 5])

    def test_v5_columns_and_coin_defaults(self):
        from admin_v2.store import migrate
        conn = self._live_like_db()
        migrate(conn)
        reg_cols = {r[1] for r in conn.execute("PRAGMA table_info(domain_registry)")}
        self.assertIn("last_redirect_to", reg_cols)
        health_cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(domain_health_checks)")}
        self.assertIn("final_domain", health_cols)
        row = conn.execute(
            "SELECT coin_redeem_day, coin_redeem_weekend, coin_redeem_monthly, "
            "coin_redeem_download, coin_redeem_request, coin_redeem_theme "
            "FROM app_remote_config_v2 WHERE id=1").fetchone()
        self.assertEqual(tuple(row), (500, 1200, 5000, 100, 300, 250))

    def test_migrate_is_idempotent(self):
        from admin_v2.store import migrate
        conn = self._live_like_db()
        migrate(conn)
        migrate(conn)  # a re-run adds nothing twice
        self.assertEqual(
            [r[0] for r in conn.execute(
                "SELECT version FROM schema_version ORDER BY version")],
            [1, 2, 3, 4, 5])

    def test_list_scheduled_works_after_v4(self):
        from admin_v2.store import migrate
        conn = self._live_like_db()
        migrate(conn)
        conn.close()
        # Service-level: the Live page's list_scheduled must not 500.
        svc, owner, _aud = make_service()
        self.assertEqual(svc.list_scheduled(owner), {"items": []})

    def test_monetization_empty_token_never_wipes(self):
        svc, owner, _aud = make_service()
        svc.put_monetization(owner, {"shrinkme_api_token": "tok-123"})
        self.assertTrue(svc.get_monetization(owner)["shrinkme_configured"])
        # A blank token field means "keep", not "clear" — and a body of
        # only blank tokens refuses instead of wiping everything.
        with self.assertRaises(ApiError):
            svc.put_monetization(owner, {"shrinkme_api_token": ""})
        self.assertTrue(svc.get_monetization(owner)["shrinkme_configured"])
        svc.put_monetization(owner, {"shrinkme_api_token": "",
                                     "vip_monthly_pkr": 250})
        self.assertTrue(svc.get_monetization(owner)["shrinkme_configured"])
        self.assertEqual(svc.get_monetization(owner)["vip_monthly_pkr"], 250)

    def test_monetization_coin_validation(self):
        svc, owner, _aud = make_service()
        with self.assertRaises(ApiError):
            svc.put_monetization(owner, {"coin_redeem_day": -1})
        with self.assertRaises(ApiError):
            svc.put_monetization(owner, {"coin_redeem_day": 10_000_001})
        svc.put_monetization(owner, {"coin_redeem_day": 600})
        self.assertEqual(svc.get_monetization(owner)["coin_redeem_day"], 600)

    def test_tuning_empty_email_is_unset_not_error(self):
        svc, owner, _aud = make_service()
        svc.put_tuning(owner, {"disclaimer_email": "", "reason": "clear"})
        self.assertEqual(svc.get_tuning(owner)["disclaimer_email"], "")
        with self.assertRaises(ApiError):
            svc.put_tuning(owner, {"disclaimer_email": "not-an-email"})


class TestLiveSchedule(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()

    def test_live_matches_seed_before_first_publish(self):
        # The fixture seeds one published snapshot from the draft, so live
        # already equals the draft before any operator publish.
        live = self.svc.get_live(self.owner)
        self.assertIsNotNone(live["live"])
        self.assertEqual(live["live"]["config_version"], live["draft"]["config_version"])
        self.assertEqual(live["changed_keys"], [])

    def test_live_matches_after_publish_then_differs_on_draft(self):
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        live = self.svc.get_live(self.owner)
        self.assertEqual(live["live"]["config_version"], live["draft"]["config_version"])
        self.assertEqual(live["changed_keys"], [])
        self.svc.draft_remote_config(self.owner, {"brand_primary": "#123456"})
        live = self.svc.get_live(self.owner)
        self.assertIn("brand_primary", live["changed_keys"])

    def test_schedule_requires_future_time(self):
        import time as _t
        with self.assertRaises(ApiError):
            self.svc.schedule_publish(self.owner, {"scheduled_at": int(_t.time()) - 10})
        with self.assertRaises(ApiError):
            self.svc.schedule_publish(self.owner, {"scheduled_at": "soon"})
        row = self.svc.schedule_publish(
            self.owner, {"scheduled_at": int(_t.time()) + 3600, "note": "tonight"})
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["note"], "tonight")

    def test_due_schedule_fires_and_future_one_waits(self):
        import time as _t
        now = int(_t.time())
        v0 = self.svc._config_row()["config_version"]
        self.svc.schedule_publish(self.owner, {"scheduled_at": now + 3600})
        # A due row is one whose moment has passed since scheduling; the
        # service refuses to schedule in the past, so the test plants the
        # row directly, the way time itself would have left it.
        self.svc.admin.execute(
            "INSERT INTO scheduled_publishes (scheduled_at, status, created_by, created_at) "
            "VALUES (?,?,?,?)", (now - 5, "pending", self.owner["id"], now - 5))
        due_id = self.svc.admin.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        self.svc.admin.commit()
        self.assertEqual(self.svc.fire_due_scheduled_publishes(now=now), 1)
        self.assertEqual(self.svc._config_row()["config_version"], v0 + 1)
        fired = self.svc.admin.execute(
            "SELECT * FROM scheduled_publishes WHERE id=?", (due_id,)).fetchone()
        self.assertEqual(fired["status"], "fired")
        self.assertEqual(fired["fired_version"], v0 + 1)
        pending = self.svc.list_scheduled(self.owner)["items"]
        self.assertEqual([p for p in pending if p["status"] == "pending"], pending[:1])
        # A second fire finds nothing due.
        self.assertEqual(self.svc.fire_due_scheduled_publishes(now=now), 0)

    def test_cancelled_schedule_never_fires(self):
        import time as _t
        now = int(_t.time())
        self.svc.admin.execute(
            "INSERT INTO scheduled_publishes (scheduled_at, status, created_by, created_at) "
            "VALUES (?,?,?,?)", (now - 5, "pending", self.owner["id"], now - 5))
        row_id = self.svc.admin.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        self.svc.admin.commit()
        self.svc.cancel_scheduled_publish(self.owner, row_id)
        self.assertEqual(self.svc.fire_due_scheduled_publishes(now=now), 0)
        cancelled = self.svc.admin.execute(
            "SELECT * FROM scheduled_publishes WHERE id=?", (row_id,)).fetchone()
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(ApiError):
            self.svc.cancel_scheduled_publish(self.owner, row_id)

    def test_blocked_schedule_marks_blocked_not_fired(self):
        import time as _t
        now = int(_t.time())
        v0 = self.svc._config_row()["config_version"]
        for key in ("hero", "trending", "movie", "series"):
            self.svc.delete_section(self.owner, key)
        self.svc.admin.execute(
            "INSERT INTO scheduled_publishes (scheduled_at, status, created_by, created_at) "
            "VALUES (?,?,?,?)", (now - 5, "pending", self.owner["id"], now - 5))
        row_id = self.svc.admin.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        self.svc.admin.commit()
        self.assertEqual(self.svc.fire_due_scheduled_publishes(now=now), 0)
        self.assertEqual(self.svc._config_row()["config_version"], v0)
        blocked = self.svc.admin.execute(
            "SELECT * FROM scheduled_publishes WHERE id=?", (row_id,)).fetchone()
        self.assertEqual(blocked["status"], "blocked")

    def test_rollback_requires_confirm(self):
        v0 = self.svc._config_row()["config_version"]
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        with self.assertRaises(ApiError):
            self.svc.rollback_remote_config(self.owner, {"version": v0})
        self.svc.rollback_remote_config(self.owner, {"version": v0, "confirm": True})
        self.assertEqual(self.svc._config_row()["config_version"], v0 + 2)


class TestBroadcastTargeting(unittest.TestCase):
    def setUp(self):
        self.svc, self.owner, self.auditor = make_service()

    def _create(self, **kw):
        body = {"title": "T", "body": "B", "target": "all"}
        body.update(kw)
        return self.svc.create_broadcast(self.owner, body)

    def test_region_target_needs_a_region(self):
        with self.assertRaises(ApiError):
            self._create(target="region")
        with self.assertRaises(ApiError):
            self._create(target="region", target_detail="europe")
        row = self._create(target="region", target_detail="pakistan")
        self.assertEqual(row["target_detail"], "pakistan")

    def test_version_target_needs_one_exact_name(self):
        with self.assertRaises(ApiError):
            self._create(target="version")
        with self.assertRaises(ApiError):
            self._create(target="version", target_detail="1.0.4 or later")
        row = self._create(target="version", target_detail="1.0.4")
        self.assertEqual(row["target_detail"], "1.0.4")

    def test_broad_targets_take_no_detail(self):
        for target in ("all", "free", "vip"):
            with self.assertRaises(ApiError):
                self._create(target=target, target_detail="pakistan")
        self.assertEqual(self._create(target="free")["target"], "free")

    def test_update_validates_merged_target(self):
        # Changing the target without its detail must fail, not half-save:
        # the row would say "region" with no region in it.
        row = self._create(target="all")
        with self.assertRaises(ApiError):
            self.svc.update_broadcast(self.owner, row["id"], {"target": "region"})
        after = self.svc.update_broadcast(
            self.owner, row["id"], {"target": "region", "target_detail": "india"})
        self.assertEqual(after["target_detail"], "india")
        cleared = self.svc.update_broadcast(
            self.owner, row["id"], {"target": "all", "target_detail": ""})
        self.assertIsNone(cleared["target_detail"])

    def test_disclaimer_tuning_keys(self):
        tuning = self.svc.get_tuning(self.owner)
        self.assertEqual(tuning["disclaimer_text"], "")
        self.assertEqual(tuning["disclaimer_version"], 0)
        self.assertEqual(tuning["disclaimer_email"], "radddao1@gmail.com")
        self.svc.put_tuning(self.owner, {
            "disclaimer_text": "Links come from public sites. We host nothing.",
            "disclaimer_version": 1, "reason": "test"})
        tuning = self.svc.get_tuning(self.owner)
        self.assertEqual(tuning["disclaimer_version"], 1)
        self.assertIn("public sites", tuning["disclaimer_text"])
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"disclaimer_version": -1})
        with self.assertRaises(ApiError):
            self.svc.put_tuning(self.owner, {"disclaimer_text": "x" * 4001})
        self.svc.put_tuning(self.owner, {
            "disclaimer_email": "takedown@example.org", "reason": "test"})
        self.assertEqual(
            self.svc.get_tuning(self.owner)["disclaimer_email"],
            "takedown@example.org")
        for bad_email in ("not-an-email", "a@b@c", "a b@c.com", "@x.com",
                          "a@x", "x" * 250 + "@a.com"):
            with self.assertRaises(ApiError, msg=bad_email):
                self.svc.put_tuning(self.owner, {"disclaimer_email": bad_email})
        consumers = self.svc.tuning_consumers(self.owner)
        self.assertEqual(consumers["disclaimer_text"], "remote-config (app reads it)")
        self.assertEqual(consumers["disclaimer_email"], "remote-config (app reads it)")


if __name__ == "__main__":
    unittest.main()
