"""Phase 2 real-data tests. Every live integration runs against TEMP
COPIES built from the real DDL (posts / user_accounts /
payment_transactions / app_remote_config / admin_fleet_audit /
cat_*, domain_registry.json, <site>_status.json). No test ever touches
a live DB, spawns a real crawler, or prints a credential, token, or
transaction id."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import good_checker, make_service  # noqa: E402
from admin_v2 import fixture_app, templates  # noqa: E402
from admin_v2.live_stores import LiveStores, account_hint, fleet_command  # noqa: E402
from admin_v2.server import AdminApp  # noqa: E402

CATALOG_DDL = """
CREATE TABLE posts (id INTEGER PRIMARY KEY, url TEXT UNIQUE, slug TEXT,
  title TEXT, clean_title TEXT, year INTEGER, content_type TEXT, seasons INTEGER,
  poster_url TEXT, backdrop_urls TEXT, imdb_rating REAL, genres TEXT,
  synopsis TEXT, is_18_plus INTEGER, is_animated INTEGER, lastmod TEXT,
  created_at TEXT, updated_at TEXT, source_site TEXT, industry TEXT,
  country TEXT, language TEXT, canonical_key TEXT, tmdb_id INTEGER, imdb_id TEXT);
CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER,
  release_title TEXT, season INTEGER, episode INTEGER, quality TEXT,
  codec TEXT, size TEXT, languages TEXT, intermediate_url TEXT,
  source_site TEXT, origin_url TEXT, created_at TEXT);
CREATE TABLE download_sources (id INTEGER PRIMARY KEY, release_id INTEGER,
  source_name TEXT, service TEXT, resource_id TEXT, source_url TEXT,
  final_url TEXT, playback_type TEXT, is_temporary INTEGER,
  status TEXT DEFAULT 'active', is_resumable INTEGER, http_status INTEGER,
  file_size_bytes INTEGER, mime_type TEXT, last_checked_at TEXT,
  created_at TEXT, updated_at TEXT, expires_at TEXT, ttl_source TEXT,
  last_failed_at REAL, failure_class TEXT);
CREATE TABLE cat_works (id INTEGER PRIMARY KEY, work_key TEXT, title TEXT,
  original_title TEXT, year INTEGER, work_type TEXT, is_animated INTEGER,
  is_18_plus INTEGER, synopsis TEXT, genres TEXT, languages TEXT,
  country TEXT, industry TEXT, imdb_rating REAL, imdb_id TEXT, tmdb_id INTEGER,
  tvdb_id INTEGER, runtime_minutes INTEGER, poster_url TEXT, backdrop_urls TEXT,
  site_count INTEGER, release_count INTEGER, episode_count INTEGER,
  max_resolution INTEGER, best_quality_score REAL, available_stream INTEGER,
  available_download INTEGER, identity_suspect INTEGER, entitlement_model TEXT,
  first_seen_at TEXT, updated_at TEXT, source_rev INTEGER);
CREATE TABLE cat_links (id INTEGER PRIMARY KEY, release_id INTEGER,
  work_id INTEGER, state TEXT DEFAULT 'unchecked', resumable INTEGER DEFAULT 0,
  accepts_ranges INTEGER DEFAULT 0, protocol TEXT, content_type TEXT);
CREATE TABLE cat_link_evidence (id INTEGER PRIMARY KEY, link_id INTEGER,
  probed_at REAL, ok INTEGER, protocol TEXT, http_status INTEGER,
  content_type TEXT, size_bytes INTEGER, latency_ms INTEGER,
  speed_mbps REAL, accepts_ranges INTEGER, error TEXT, url TEXT);
CREATE TABLE cat_review_queue (id INTEGER PRIMARY KEY, kind TEXT,
  work_id INTEGER, release_id INTEGER, page_url TEXT, detail TEXT,
  raised_at REAL, resolved_at REAL);
CREATE TABLE cat_projection_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE app_remote_config (id INTEGER PRIMARY KEY CHECK (id = 1),
  pak_till_id TEXT NOT NULL DEFAULT '', pak_jazzcash_number TEXT NOT NULL DEFAULT '',
  pak_easypaisa_number TEXT NOT NULL DEFAULT '', pak_raast_id TEXT NOT NULL DEFAULT '',
  vip_monthly_pkr INTEGER NOT NULL DEFAULT 200, vip_yearly_pkr INTEGER NOT NULL DEFAULT 1500,
  monetag_zone_id TEXT NOT NULL DEFAULT '', adsterra_tag_id TEXT NOT NULL DEFAULT '',
  shrinkme_api_token TEXT NOT NULL DEFAULT '', droplink_api_token TEXT NOT NULL DEFAULT '',
  updated_at INTEGER NOT NULL DEFAULT 0, maintenance_mode INTEGER NOT NULL DEFAULT 0,
  apk_update_url TEXT NOT NULL DEFAULT '', feature_downloads INTEGER NOT NULL DEFAULT 1,
  feature_pure_cinema INTEGER NOT NULL DEFAULT 1, feature_chromecast INTEGER NOT NULL DEFAULT 1,
  feature_quality_gate INTEGER NOT NULL DEFAULT 0,
  coin_redeem_day INTEGER NOT NULL DEFAULT 500, coin_redeem_weekend INTEGER NOT NULL DEFAULT 1200,
  coin_redeem_monthly INTEGER NOT NULL DEFAULT 5000, coin_redeem_download INTEGER NOT NULL DEFAULT 100,
  coin_redeem_request INTEGER NOT NULL DEFAULT 300, coin_redeem_theme INTEGER NOT NULL DEFAULT 250);
CREATE TABLE admin_fleet_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,
  crawler_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL,
  started_at INTEGER NOT NULL, finished_at INTEGER, pid INTEGER,
  exit_code INTEGER, detail TEXT NOT NULL DEFAULT '');
"""
LEDGER_DDL = """
CREATE TABLE user_accounts (id INTEGER PRIMARY KEY, key_hash TEXT UNIQUE,
  created_at REAL, last_seen_at REAL, revoked_at REAL, vip_until REAL DEFAULT 0,
  profile_name TEXT NOT NULL DEFAULT '');
CREATE TABLE user_favorites (id INTEGER PRIMARY KEY, account_id INTEGER,
  work_key TEXT, season_number INTEGER, episode_number INTEGER, added_at REAL);
CREATE TABLE user_progress (id INTEGER PRIMARY KEY, account_id INTEGER,
  work_key TEXT, season_number INTEGER, episode_number INTEGER,
  position_seconds REAL, duration_seconds REAL, client_updated_at REAL,
  updated_at REAL);
CREATE TABLE movie_requests (id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
  title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL);
CREATE TABLE coin_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
  delta INTEGER NOT NULL, reason TEXT NOT NULL, ref TEXT,
  idempotency_key TEXT UNIQUE, source TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE payment_transactions (id INTEGER PRIMARY KEY, account_id INTEGER,
  plan TEXT, amount_pkr INTEGER, method TEXT, tid TEXT,
  status TEXT DEFAULT 'pending', submitted_at REAL, reviewed_at REAL,
  reviewer_note TEXT);
CREATE TABLE payment_review_audit (id INTEGER PRIMARY KEY, payment_id INTEGER,
  account_id INTEGER, action TEXT, prior_vip_until REAL, new_vip_until REAL,
  reviewer TEXT, note TEXT, acted_at REAL);
CREATE TABLE usage_device (device_hash TEXT PRIMARY KEY,
  install_day INTEGER NOT NULL, first_seen_at REAL NOT NULL,
  last_seen_at REAL NOT NULL, geo TEXT NOT NULL DEFAULT 'unknown',
  locale TEXT NOT NULL DEFAULT 'unknown', app_version TEXT NOT NULL DEFAULT 'unknown',
  device_class TEXT NOT NULL DEFAULT 'unknown', region TEXT NOT NULL DEFAULT 'unknown',
  audio_lang TEXT NOT NULL DEFAULT 'unknown', subtitle_lang TEXT NOT NULL DEFAULT 'unknown',
  retained_1 INTEGER NOT NULL DEFAULT 0, retained_7 INTEGER NOT NULL DEFAULT 0,
  retained_30 INTEGER NOT NULL DEFAULT 0);
CREATE TABLE usage_metric (day INTEGER NOT NULL, metric TEXT NOT NULL,
  total REAL NOT NULL DEFAULT 0, PRIMARY KEY (day, metric));
CREATE TABLE usage_dim_metric (day INTEGER NOT NULL, dim TEXT NOT NULL,
  value TEXT NOT NULL, metric TEXT NOT NULL, total REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (day, dim, value, metric));
"""


def _make_cert(path):
    """Self-signed cert for the cert-file read test (openssl, temp only)."""
    res = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout",
         path + ".key", "-out", path, "-days", "365", "-nodes",
         "-subj", "/CN=example.test"],
        capture_output=True, text=True)
    return res.returncode == 0


class LiveBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="adminv2-live-")
        self.now = time.time()
        # --- temp catalog copy (real DDL, real-shaped rows) ---
        self.catalog_path = os.path.join(self.tmp, "catalog.db")
        conn = sqlite3.connect(self.catalog_path)
        conn.executescript(CATALOG_DDL)
        conn.execute("INSERT INTO app_remote_config (id) VALUES (1)")
        conn.executemany(
            "INSERT INTO posts (id, title, clean_title, year, content_type, poster_url, "
            "genres, imdb_rating, is_18_plus, language, canonical_key, source_site, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(1, "Real Movie One", "Real Movie One", 2024, "movie",
              "https://cdn.example.test/p1.jpg", "action,drama", 8.1, 0,
              "hindi", "real-movie-one", "multimovies", "2026-10-20"),
             (2, "Real Series One", "Real Series One", 2023, "series",
              "https://cdn.example.test/p2.jpg", "drama", 7.5, 0,
              "urdu", "real-series-one", "vegamovies", "2026-10-21"),
             (3, "Real Adult Work", "Real Adult Work", 2022, "movie",
              "https://cdn.example.test/p3.jpg", "drama", 6.0, 1,
              "english", "real-adult-work", "vegamovies", "2026-10-19"),
             (4, "Real Movie Two", "Real Movie Two", 2025, "movie", None,
              "comedy", 7.0, 0, "hindi", "real-movie-two", "hdhub4u", "2026-10-22")])
        conn.executemany(
            "INSERT INTO cat_works (id, work_key, title, year, work_type, is_18_plus, "
            "genres, best_quality_score, release_count, poster_url) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(1, "real-movie-one", "Real Movie One", 2024, "movie", 0,
              "action", 9.5, 12, "https://cdn.example.test/p1.jpg"),
             (2, "real-series-one", "Real Series One", 2023, "series", 0,
              "drama", 4.0, 3, "https://cdn.example.test/p2.jpg"),
             (4, "real-movie-two", "Real Movie Two", 2025, "movie", 0,
              "comedy", 7.0, 5, None)])
        conn.execute("INSERT INTO releases (id, post_id, release_title, quality) VALUES (1, 1, 'R1', '720p')")
        conn.execute("INSERT INTO download_sources (id, release_id, status, is_resumable) "
                     "VALUES (1, 1, 'active', 1)")
        conn.execute("INSERT INTO download_sources (id, release_id, status, is_resumable) "
                     "VALUES (2, 1, 'dead', 0)")
        # Negative cache: two failed rows, one per failure class.
        conn.execute("INSERT INTO download_sources (id, release_id, status, service, "
                     "last_failed_at, failure_class) VALUES (3, 1, 'dead', 'gofile', ?, 'no_unwrapper')",
                     (self.now - 100,))
        conn.execute("INSERT INTO download_sources (id, release_id, status, service, "
                     "last_failed_at, failure_class) VALUES (4, 1, 'dead', 'mixdrop', ?, 'unwrap_failed')",
                     (self.now - 200,))
        conn.execute("INSERT INTO cat_links (id, release_id, work_id, state) VALUES (1, 1, 1, 'unchecked')")
        conn.execute("INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, "
                     "http_status, accepts_ranges) VALUES (1, ?, 1, 'https', 200, 1)",
                     (self.now - 60,))
        conn.execute("INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, "
                     "http_status, accepts_ranges) VALUES (1, ?, 0, 'https', 404, 0)",
                     (self.now - 3600,))
        conn.execute("INSERT INTO cat_projection_meta VALUES ('catalog_rev', '3')")
        conn.execute("INSERT INTO cat_projection_meta VALUES ('projected_at', ?)",
                     (str(self.now - 5 * 3600),))
        conn.execute("INSERT INTO cat_projection_meta VALUES ('health_rev', '7')")
        conn.execute("INSERT INTO cat_projection_meta VALUES ('link_coverage', '0.0')")
        conn.execute("INSERT INTO cat_projection_meta VALUES ('identity_suspect', '41432')")
        conn.execute("INSERT INTO cat_projection_meta VALUES ('release_dups', '295711')")
        conn.execute("INSERT INTO cat_projection_meta VALUES ('id_map_rows', '4735950')")
        conn.execute("INSERT INTO cat_review_queue (id, kind, work_id, detail, raised_at) "
                     "VALUES (1, 'adult_proof', 3, 'flag check', ?)", (self.now - 100,))
        conn.commit()
        conn.close()
        # --- temp ledger copy ---
        self.ledger_path = os.path.join(self.tmp, "ledger.db")
        conn = sqlite3.connect(self.ledger_path)
        conn.executescript(LEDGER_DDL)
        self.key1 = "sha256:aaa111"
        self.key2 = "sha256:bbb222"
        conn.executemany(
            "INSERT INTO user_accounts (id, key_hash, created_at, vip_until, profile_name) VALUES (?,?,?,?,?)",
            [(1, self.key1, self.now - 86400, 0, "First Viewer"),
             (2, self.key2, self.now - 86400, self.now + 30 * 86400, "")])
        # Same TID on two accounts: the cross-account rule must refuse
        # the second approval. TIDs here are test-only values.
        conn.executemany(
            "INSERT INTO payment_transactions (id, account_id, plan, amount_pkr, method, tid, "
            "status, submitted_at) VALUES (?,?,?,?,?,?,?,?)",
            [(1, 1, "vip_monthly", 200, "jazzcash", "1111111111", "pending", self.now - 500),
             (2, 2, "vip_yearly", 1500, "jazzcash", "1111111111", "pending", self.now - 400),
             (3, 1, "vip_yearly", 1500, "raast", "RAASTTEST1234", "pending", self.now - 300)])
        # Movie-request queue (D2.6): two open, one already indexed; the
        # indexed title carries a URL in its notes, which the edge must strip.
        conn.executemany(
            "INSERT INTO movie_requests (id, account_id, title, notes, status, created_at) "
            "VALUES (?,?,?,?,?,?)",
            [(1, 1, "Old Requested Title", "please find it", "open", self.now - 900),
             (2, 2, "New Requested Title", "", "open", self.now - 100),
             (3, 1, "Indexed Title", "see https://example.test/trailer", "indexed", self.now - 800)])
        conn.executemany(
            "INSERT INTO coin_ledger (id, account_id, delta, reason, source, created_at) "
            "VALUES (?,?,?,?,?,?)",
            [(1, 1, 500, "grant", "server", self.now - 800),
             (2, 1, -300, "redeem_request", "server", self.now - 700),
             (3, 2, 100, "grant", "server", self.now - 600)])
        conn.commit()
        conn.close()
        # --- temp registry + status files ---
        self.registry_path = os.path.join(self.tmp, "domain_registry.json")
        with open(self.registry_path, "w") as fh:
            json.dump({"version": "1.0", "sites": {
                "multimovies": {"active_base_url": "https://multimovies.example.test",
                                "known_mirrors": ["https://multimovies.example.test"],
                                "api_type": "wp_rest_api", "status": "active"},
                "vegamovies": {"active_base_url": "https://vegamovies.example.test",
                               "known_mirrors": [], "api_type": "wp_rest_api",
                               "status": "active"},
            }}, fh)
        self.status_dir = os.path.join(self.tmp, "status")
        os.makedirs(self.status_dir)
        with open(os.path.join(self.status_dir, "vegamovies_status.json"), "w") as fh:
            json.dump({"completed": 2, "total": 10, "failed": 1,
                       "updated_at": "2026-10-23T19:36:40Z"}, fh)
        # --- temp cert ---
        self.cert_path = os.path.join(self.tmp, "fullchain.pem")
        self.cert_ok = _make_cert(self.cert_path)
        # --- fake fleet runner (records, never spawns) ---
        self.spawned = []

        def _fake_runner(cmd, cwd, log_path):
            self.spawned.append({"cmd": cmd, "cwd": cwd, "log": log_path})
            return 4242

        from admin_v2.services import Service
        self.live = LiveStores(
            catalog_path=self.catalog_path, ledger_path=self.ledger_path,
            registry_path=self.registry_path, status_dir=self.status_dir,
            cert_path=self.cert_path if self.cert_ok else None,
            fleet_base_dir="/opt/radd-stream/Fast_Fetch",
            fleet_runner=_fake_runner)
        self.admin_dir = os.path.join(self.tmp, "admin")
        self.svc = Service(self.admin_dir, live=self.live)
        self.owner_id = self.svc.create_owner("owner", "correct horse battery staple")
        self.owner = {"id": self.owner_id, "username": "owner", "role": "owner"}
        self.auditor = {"id": 999, "username": "auditor", "role": "auditor"}

    def _ledger(self):
        conn = sqlite3.connect(self.ledger_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _catalog(self):
        conn = sqlite3.connect(self.catalog_path)
        conn.row_factory = sqlite3.Row
        return conn


class TestLiveCatalog(LiveBase):
    def test_search_and_get_real_works(self):
        res = self.svc.search_works(self.owner, q="Real Movie")
        titles = [w["title"] for w in res["items"]]
        self.assertIn("Real Movie One", titles)
        self.assertNotIn("MOCK Movie One", titles)
        w = self.svc.get_work(self.owner, 1)
        self.assertEqual(w["poster_state"], "real")
        self.assertEqual(w["adult_flag"], 0)
        self.assertEqual(w["work_key"], "real-movie-one")
        adult = self.svc.get_work(self.owner, 3)
        self.assertEqual(adult["adult_flag"], 1)

    def test_section_source_rules_execute_on_real_catalog(self):
        # Seed now gives the movie rail the category rule; pin the
        # starting rule here so the test does not depend on the seed.
        self.svc.update_section(self.owner, "movie", {"source_rule": "latest"})
        prev = self.svc.resolve_section_preview(self.owner, "movie")
        self.assertEqual(prev["source_rule"], "latest")
        self.assertTrue(any(w["id"] == 4 for w in prev["items"]))  # newest first
        self.assertFalse(any(w["id"] == 3 for w in prev["items"]))  # adult excluded
        self.svc.update_section(self.owner, "movie", {"source_rule": "trending"})
        prev = self.svc.resolve_section_preview(self.owner, "movie")
        self.assertEqual(prev["items"][0]["id"], 1)  # best_quality_score 9.5
        self.svc.update_section(self.owner, "movie",
                                {"source_rule": "category", "category_key": "comedy"})
        prev = self.svc.resolve_section_preview(self.owner, "movie")
        self.assertEqual([w["id"] for w in prev["items"]], [4])

    def test_home_layout_fills_from_source_rule_and_adult_fail_closed(self):
        layout = fixture_app.home_layout(self.svc)
        movies = [s for s in layout if s["key"] == "movie"][0]
        self.assertTrue(len(movies["cards"]) > 0)
        self.assertFalse(any(c["work_id"] == 3 for s in layout for c in s["cards"]))

    def test_catalog_counts_and_projection_age_real(self):
        counts = self.live.catalog_counts()
        self.assertEqual(counts["posts"], 4)
        self.assertEqual(counts["releases"], 1)
        self.assertEqual(counts["sources"], 4)
        self.assertEqual(counts["active_sources"], 1)
        self.assertEqual(counts["resumable_sources"], 1)
        # Works are not posts: 4 posts, 3 works (fixture ids 1, 2, 4).
        self.assertEqual(counts["works"], 3)
        self.assertEqual(counts["adult_posts"], 1)
        self.assertEqual(counts["adult_works"], 0)
        # Projection truth, not just its age.
        self.assertEqual(counts["link_coverage"], 0.0)
        self.assertEqual(counts["identity_suspect"], 41432)
        self.assertEqual(counts["release_dups"], 295711)
        self.assertEqual(counts["id_map_rows"], 4735950)
        self.assertIsNotNone(counts["projection_age_h"])
        self.assertAlmostEqual(counts["projection_age_h"], 5.0, delta=0.2)

    # Session 107, Phase D item 11: projection drift. The fixture is a
    # 5-hour-old rev-3 projection with no `posts` key in its meta, so the
    # post drift is unknown and only the age can judge it: fresh.
    def test_projection_drift_fresh_is_not_stale(self):
        drift = self.live.projection_drift()
        self.assertFalse(drift["stale"])
        self.assertEqual(drift["reasons"], [])
        self.assertEqual(drift["ledger_posts"], 4)
        self.assertIsNone(drift["projected_posts"])
        self.assertIsNone(drift["drift_posts"])

    def test_projection_drift_old_age_is_stale(self):
        conn = sqlite3.connect(self.catalog_path)
        conn.execute("UPDATE cat_projection_meta SET value = ? WHERE key = 'projected_at'",
                     (str(self.now - 100 * 3600),))
        conn.commit()
        conn.close()
        drift = self.live.projection_drift()
        self.assertTrue(drift["stale"])
        self.assertTrue(any("100.0 h old" in r for r in drift["reasons"]),
                        drift["reasons"])

    def test_projection_drift_many_new_posts_is_stale(self):
        conn = sqlite3.connect(self.catalog_path)
        conn.executemany(
            "INSERT INTO posts (url, slug, title) VALUES (?, ?, ?)",
            [(f"https://example.test/new-{i}/", f"new-{i}", f"New {i}")
             for i in range(1001)])
        conn.execute("INSERT INTO cat_projection_meta VALUES ('posts', '4')")
        conn.commit()
        conn.close()
        drift = self.live.projection_drift()
        self.assertTrue(drift["stale"])
        self.assertEqual(drift["ledger_posts"], 1005)
        self.assertEqual(drift["projected_posts"], 4)
        self.assertEqual(drift["drift_posts"], 1001)
        self.assertTrue(any("1,001 posts arrived" in r for r in drift["reasons"]),
                        drift["reasons"])

    def test_projection_drift_no_projection_is_stale(self):
        conn = sqlite3.connect(self.catalog_path)
        conn.execute("DELETE FROM cat_projection_meta")
        conn.commit()
        conn.close()
        drift = self.live.projection_drift()
        self.assertTrue(drift["stale"])
        self.assertEqual(drift["reasons"], ["no projection has ever been built"])

    def test_review_queue_read_only(self):
        q = self.live.review_queue()
        self.assertEqual(q["count"], 1)
        self.assertEqual(q["items"][0]["kind"], "adult_proof")
        self.assertFalse(hasattr(self.live, "resolve_review_queue"))

    def test_evidence_refold_rederives_from_journal(self):
        res = self.svc.refold_evidence(self.owner, 1)
        self.assertTrue(res["refolded"])
        self.assertEqual(res["state"], "active")  # latest sample ok=1
        self.assertEqual(res["samples"], 2)
        conn = self._catalog()
        row = conn.execute("SELECT state, resumable FROM cat_links WHERE id=1").fetchone()
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["resumable"], 1)
        meta = conn.execute("SELECT value FROM cat_projection_meta WHERE key='health_rev'").fetchone()
        self.assertEqual(meta["value"], "8")
        conn.close()
        # No evidence -> honest no-op, nothing invented.
        res = self.svc.refold_evidence(self.owner, 99)
        self.assertFalse(res["refolded"])


class TestLiveUsersPayments(LiveBase):
    def test_account_hint_matches_v1_formula(self):
        expected = "acct-" + hashlib.sha256(
            ("radd-payment-hint:v1:" + self.key1).encode()).hexdigest()[:8]
        self.assertEqual(account_hint(self.key1), expected)
        res = self.svc.search_users(self.owner, q=expected)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["items"][0]["tier"], "free")
        self.assertNotIn("key_hash", res["items"][0])
        self.assertNotIn(self.key1, json.dumps(res))

    def test_approve_credits_once_and_replay_is_noop(self):
        res = self.svc.approve_payment(self.owner, 3, {"confirm": True, "note": "checked sms"})
        self.assertTrue(res["changed"])
        self.assertEqual(res["days"], 365)
        conn = self._ledger()
        vip = conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"]
        self.assertAlmostEqual(vip, res["vip_until"], delta=1)
        audit = conn.execute("SELECT COUNT(*) AS n FROM payment_review_audit").fetchone()["n"]
        self.assertEqual(audit, 1)
        # Replay: v1 idempotent answer, no second credit, no second audit row.
        res2 = self.svc.approve_payment(self.owner, 3, {"confirm": True})
        self.assertFalse(res2["changed"])
        vip2 = conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"]
        self.assertEqual(vip, vip2)
        audit2 = conn.execute("SELECT COUNT(*) AS n FROM payment_review_audit").fetchone()["n"]
        self.assertEqual(audit2, 1)
        conn.close()

    def test_reject_leaves_vip_untouched(self):
        conn = self._ledger()
        before = conn.execute("SELECT vip_until FROM user_accounts WHERE id=2").fetchone()["vip_until"]
        conn.close()
        res = self.svc.reject_payment(self.owner, 2, {"confirm": True, "note": "not found"})
        self.assertEqual(res["status"], "rejected")
        conn = self._ledger()
        after = conn.execute("SELECT vip_until FROM user_accounts WHERE id=2").fetchone()["vip_until"]
        self.assertEqual(before, after)
        conn.close()

    def test_cross_account_tid_rule_blocks_second_approval(self):
        # Payments 1 and 2 share one TID across two accounts. Approving
        # either while the other is still pending/approved is refused.
        from admin_v2.errors import ApiError
        with self.assertRaises(ApiError) as ctx:
            self.svc.approve_payment(self.owner, 1, {"confirm": True})
        self.assertEqual(ctx.exception.status, 409)
        conn = self._ledger()
        self.assertEqual(conn.execute("SELECT status FROM payment_transactions WHERE id=1").fetchone()["status"], "pending")
        vip1 = conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"]
        self.assertEqual(vip1, 0)
        conn.close()
        # Once the other claim is rejected it no longer blocks.
        self.svc.reject_payment(self.owner, 2, {"confirm": True, "note": "duplicate tid"})
        res = self.svc.approve_payment(self.owner, 1, {"confirm": True})
        self.assertTrue(res["changed"])
        # And now the approved TID blocks any later duplicate approve.
        conn = self._ledger()
        conn.execute("INSERT INTO payment_transactions (id, account_id, plan, amount_pkr, "
                     "method, tid, status, submitted_at) VALUES (9, 2, 'vip_monthly', 200, "
                     "'jazzcash', '1111111111', 'pending', ?)", (self.now,))
        conn.commit()
        conn.close()
        with self.assertRaises(ApiError):
            self.svc.approve_payment(self.owner, 9, {"confirm": True})

    def test_manual_vip_grant_audited_no_fake_payment(self):
        hint = account_hint(self.key1)
        res = self.svc.vip_grant(self.owner, hint, {"months": 2, "reason": "goodwill"})
        self.assertGreater(res["vip_until"], self.now)
        conn = self._ledger()
        n_pay = conn.execute("SELECT COUNT(*) AS n FROM payment_transactions").fetchone()["n"]
        self.assertEqual(n_pay, 3)  # no fake payment row
        audit = conn.execute(
            "SELECT action FROM payment_review_audit WHERE account_id=1").fetchall()
        self.assertEqual([r["action"] for r in audit], ["manual_grant"])
        conn.close()
        # Compensating rollback restores the ledger exactly.
        conn = self._ledger()
        prior = conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"]
        conn.close()
        result, audit_id = self.live.vip_grant_manual(1, 1, note="test")
        self.live.rollback_manual_grant(1, prior, audit_id)
        conn = self._ledger()
        self.assertEqual(conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"], prior)
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) AS n FROM payment_review_audit WHERE id=?", (audit_id,)).fetchone()["n"], 0)
        conn.close()

    def test_refund_note_changes_nothing_but_the_audit(self):
        conn = self._ledger()
        before = conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"]
        conn.close()
        res = self.svc.add_refund_note(self.owner, 1, {"note": "partial refund agreed"})
        self.assertEqual(res["status"], "pending")
        conn = self._ledger()
        self.assertEqual(conn.execute("SELECT vip_until FROM user_accounts WHERE id=1").fetchone()["vip_until"], before)
        self.assertEqual(conn.execute("SELECT status FROM payment_transactions WHERE id=1").fetchone()["status"], "pending")
        audit = conn.execute(
            "SELECT action, note FROM payment_review_audit WHERE payment_id=1").fetchall()
        self.assertEqual([(r["action"], r["note"]) for r in audit],
                         [("adjustment_note", "partial refund agreed")])
        conn.close()

    def test_per_user_payment_history_and_tid_search_never_renders_tid(self):
        hint = account_hint(self.key1)
        hist = self.svc.user_payment_history(self.owner, hint)
        self.assertEqual(hist["count"], 2)
        found = self.svc.search_payment_by_tid(self.owner, "1111111111")
        self.assertEqual(found["count"], 2)
        self.assertNotIn("1111111111", json.dumps(found))

    def test_payment_list_date_and_amount_filters(self):
        res = self.svc.list_payments(self.owner, min_amount=1500)
        self.assertTrue(all(p["amount_pkr"] >= 1500 for p in res["items"]))
        self.assertEqual(len(res["items"]), 2)
        res = self.svc.list_payments(self.owner, from_ts=self.now - 350)
        self.assertEqual([p["id"] for p in res["items"]], [3])


class TestLiveRemoteConfigDomainsFleet(LiveBase):
    def test_remote_config_reads_and_writes_real_row(self):
        mon = self.svc.get_monetization(self.owner)
        self.assertEqual(mon["vip_monthly_pkr"], 200)
        self.assertFalse(mon["shrinkme_configured"])
        self.assertNotIn("shrinkme_api_token", mon)
        after = self.svc.put_monetization(self.owner, {"vip_yearly_pkr": 1600})
        self.assertEqual(after["vip_yearly_pkr"], 1600)
        conn = self._catalog()
        row = conn.execute("SELECT vip_yearly_pkr, updated_at FROM app_remote_config WHERE id=1").fetchone()
        self.assertEqual(row["vip_yearly_pkr"], 1600)
        self.assertGreater(row["updated_at"], 0)
        conn.close()
        # v2-only fields stay panel-only and are labelled app-side pending.
        cfg = self.svc.get_remote_config(self.owner)
        self.assertEqual(cfg["vip_yearly_pkr"], 1600)
        self.assertIn("live_source", cfg)

    def test_domains_seeded_from_registry_file(self):
        doms = self.svc.list_domains(self.owner)["items"]
        keys = [d["site_key"] for d in doms]
        self.assertIn("multimovies", keys)
        self.assertIn("vegamovies", keys)
        mm = [d for d in doms if d["site_key"] == "multimovies"][0]
        self.assertEqual(mm["active_domain"], "multimovies.example.test")

    def test_domain_apply_writes_registry_file_with_backup(self):
        self.svc.validate_domain(self.owner, "multimovies",
                                 {"domain": "multimovies2.example.test"}, checker=good_checker)
        res = self.svc.apply_domain(self.owner, "multimovies",
                                    {"domain": "multimovies2.example.test", "confirm": True})
        self.assertIn("registry_backup", res)
        self.assertTrue(os.path.exists(res["registry_backup"]))
        with open(self.registry_path) as fh:
            data = json.load(fh)
        self.assertEqual(data["sites"]["multimovies"]["active_base_url"],
                         "https://multimovies2.example.test")
        self.assertIn("https://multimovies2.example.test",
                      data["sites"]["multimovies"]["known_mirrors"])

    def test_fleet_command_construction_matches_v1(self):
        self.assertEqual(
            fleet_command("vegamovies", "sync", 25),
            ["python3", "/opt/radd-stream/Fast_Fetch/fast_fetch.py", "sync", "--site", "vegamovies"])
        self.assertEqual(
            fleet_command("9xmovies", "sync", 25),
            ["python3", "/opt/radd-stream/Fast_Fetch/import_9xmovies.py", "--sync-api"])
        self.assertEqual(
            fleet_command("multimovies", "crawl", 10),
            ["python3", "/opt/radd-stream/Fast_Fetch/import_multimovies.py", "--limit-roots", "10"])
        self.assertEqual(
            fleet_command("desicinemas", "crawl", 25),
            ["python3", "/opt/radd-stream/Fast_Fetch/import_desicinemas.py", "--limit", "25"])

    def test_fleet_run_writes_audit_and_spawns_mock_only(self):
        res = self.svc.run_fleet(self.owner, {"crawler": "vegamovies", "mode": "sync", "limit": 25})
        self.assertEqual(res["status"], "running")
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.spawned[0]["cmd"][0:3],
                         ["python3", "/opt/radd-stream/Fast_Fetch/fast_fetch.py", "sync"])
        conn = self._catalog()
        row = conn.execute("SELECT * FROM admin_fleet_audit ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["crawler_id"], "vegamovies")
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["pid"], 4242)
        conn.close()

    def test_fleet_list_merges_real_status_and_domain(self):
        fleet = self.svc.list_fleet(self.owner)["items"]
        vega = [f for f in fleet if f["site_key"] == "vegamovies"][0]
        self.assertEqual(vega["progress"], 20)
        self.assertEqual(vega["failure_reason"], "failed: 1")
        self.assertEqual(vega["last_good_domain"], "vegamovies.example.test")
        # The merge must carry ever_ran: vegamovies has a status file,
        # multimovies has none — the Fleet page says "Never ran" for it.
        self.assertTrue(vega["ever_ran"])
        multi = [f for f in fleet if f["site_key"] == "multimovies"][0]
        self.assertFalse(multi["ever_ran"])

    def test_source_pause_blocks_fleet_run(self):
        self.svc.pause(self.owner, {"target_type": "source", "target_id": "vegamovies",
                                    "reason": "test"})
        from admin_v2.errors import ApiError
        with self.assertRaises(ApiError):
            self.svc.run_fleet(self.owner, {"crawler": "vegamovies", "mode": "sync", "limit": 25})
        self.assertEqual(self.spawned, [])


class TestLiveDashboardAnalyticsPolish(LiveBase):
    def test_dashboard_real_counts_cert_and_stale_report_rule(self):
        # One open report older than 24h.
        self.svc.admin.execute(
            "INSERT INTO reports (source, work_id, reason, status, created_at) "
            "VALUES ('app_report', 1, 'broken', 'open', ?)", (int(self.now) - 30 * 3600,))
        self.svc.admin.commit()
        d = self.svc.dashboard(self.owner)
        self.assertEqual(d["pending_payments"], 3)
        self.assertEqual(d["catalog_posts"], 4)
        self.assertEqual(d["active_sources"], 1)
        self.assertEqual(d["resumable_sources"], 1)
        self.assertIsNotNone(d["projection_age_h"])
        self.assertLessEqual(len(d["needs_you_now"]), 5)
        self.assertTrue(any("over 24 hours" in n for n in d["needs_you_now"]))
        self.assertTrue(all(not n.startswith("pending payments:") for n in d["needs_you_now"]))
        if self.cert_ok:
            self.assertNotEqual(d["cert_expiry"], "2027-01-31")
            self.assertRegex(d["cert_expiry"], r"\d{2} [A-Z][a-z]{2} \d{4}")
        self.assertIsNotNone(d["disk_free_gb"])

    def test_dashboard_money_analytics_agree_on_pending_count(self):
        # The 23:00 PKT live defect: Dashboard said 2, Money said none,
        # Analytics said 0 — because the Dashboard served a stale cache
        # row. All three must read the same live ledger count.
        d = self.svc.dashboard(self.owner)
        pays = self.svc.list_payments(self.owner, status="pending")["items"]
        out = self.svc.compute_analytics_day(self.owner, "2026-11-05")
        rows = self.svc.get_analytics(self.owner)["items"]
        self.assertEqual(d["pending_payments"], 3)
        self.assertEqual(len(pays), 3)
        self.assertEqual(out["pending_payments"], 3)
        self.assertEqual(rows[0]["pending_payments"], 3)
        self.assertLessEqual(len(d["needs_you_now"]), 5)
        self.assertTrue(all(
            not n.startswith("pending payments:") for n in d["needs_you_now"]))

    def test_expired_dashboard_cache_is_never_served(self):
        # Seed the exact fixture-era row found live at 23:00 PKT:
        # pending 99, hardcoded cert date, lowercase needs text, expired
        # but still inside its old stale window. The dashboard must
        # recompute from the live stores and heal the row.
        now = int(self.now)
        stale = {"pending_payments": 99, "open_reports": 0, "failed_domains": 0,
                 "active_broadcasts": 0, "maintenance_mode": False, "config_version": 1,
                 "cert_expiry": "2027-01-31",
                 "cert_warning": "Certificate renews outside the panel. Warn before expiry.",
                 "paused": [], "needs_you_now": ["pending payments: 99"],
                 "refresh_note": "visible on next app refresh"}
        self.svc.admin.execute(
            "INSERT OR REPLACE INTO dashboard_cache VALUES ('dashboard', ?, ?, ?, ?)",
            (json.dumps(stale), now - 10, now + 3600, now - 1000))
        self.svc.admin.commit()
        d = self.svc.dashboard(self.owner)
        self.assertEqual(d["pending_payments"], 3)
        self.assertNotEqual(d["cert_expiry"], "2027-01-31")
        self.assertTrue(all(
            not n.startswith("pending payments:") for n in d["needs_you_now"]))
        row = self.svc.admin.execute(
            "SELECT value_json FROM dashboard_cache WHERE cache_key='dashboard'").fetchone()
        self.assertEqual(json.loads(row["value_json"])["pending_payments"], 3)
        self.assertNotEqual(
            json.loads(row["value_json"])["cert_expiry"], "2027-01-31")

    def test_load_1m_rounded_to_two_decimals(self):
        # Settings showed "Load (1m): 6.09619140625" — raw float.
        load = self.live.system_health(self.tmp)["load_1m"]
        if load is not None:
            self.assertEqual(load, round(load, 2))
        s = self.svc.panel_settings(self.owner)
        if s["load_1m"] is not None:
            self.assertEqual(s["load_1m"], round(s["load_1m"], 2))
        d = self.svc.dashboard(self.owner)
        if d.get("load_1m") is not None:
            self.assertEqual(d["load_1m"], round(d["load_1m"], 2))

    def test_analytics_real_projection_age_and_csv(self):
        out = self.svc.compute_analytics_day(self.owner, "2026-11-05")
        # Fixture: 4 posts but only 3 works — the old code stored posts
        # (4) in catalog_works; the fix stores real works (3).
        self.assertEqual(out["catalog_works"], 3)
        self.assertEqual(out["catalog_posts"], 4)
        self.assertEqual(out["pending_payments"], 3)
        self.assertIsNotNone(out["projection_age_h"])
        self.assertAlmostEqual(out["projection_age_h"], 5.0, delta=0.5)
        csv = self.svc.export_analytics_csv(self.owner)
        self.assertTrue(csv.startswith("day,catalog_works,projection_age_h"))
        self.assertIn("2026-11-05,3,", csv)

    def test_tuning_consumers_labelled_honest(self):
        consumers = self.svc.tuning_consumers(self.owner)
        self.assertEqual(consumers["resolver_concurrency"],
                         "stored, not yet applied by the backend")
        self.assertIn("remote-config", consumers["free_quality_cap"])
        self.assertIn("remote-config", consumers["theme_mode"])
        self.assertIn("remote-config", consumers["hero_max"])
        tuning = self.svc.get_tuning(self.owner)
        self.assertIn("consumers", tuning)

    def test_feature_pause_enforced_in_public_config(self):
        cfg = fixture_app.public_remote_config(self.svc)
        self.assertTrue(cfg["feature_flags"]["downloads"])
        self.svc.pause(self.owner, {"target_type": "feature", "target_id": "downloads",
                                    "reason": "test"})
        cfg = fixture_app.public_remote_config(self.svc)
        self.assertFalse(cfg["feature_flags"]["downloads"])

    def test_category_pause_omits_section_from_home(self):
        self.svc.create_section(self.owner, {"key": "comedy-rail", "title": "Comedy",
                                             "position": 9, "source_rule": "category",
                                             "category_key": "comedy"})
        self.svc.publish_remote_config(self.owner, {"confirm": True})
        self.assertIn("comedy-rail", [s["key"] for s in fixture_app.home_layout(self.svc)])
        self.svc.pause(self.owner, {"target_type": "category", "target_id": "comedy",
                                    "reason": "test"})
        self.assertNotIn("comedy-rail", [s["key"] for s in fixture_app.home_layout(self.svc)])

    def test_polish_no_duplicate_tagline_and_white_inputs(self):
        page = templates.layout("Test", "<p>Hi</p>", active="home")
        self.assertEqual(page.count("Visible on next app refresh. Never instant."), 1)
        self.assertIn("background:var(--card)", templates.CSS)
        self.assertRegex(templates.fmt_datetime(1796436747), r"\d{2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2}")
        self.assertEqual(templates.fmt_datetime(None), "—")

    def test_report_sla_clock(self):
        self.svc.create_report(self.owner, {"reason": "broken", "work_id": 1, "detail": "x"})
        reps = self.svc.list_reports(self.owner)["items"]
        self.assertEqual(len(reps), 1)
        self.assertAlmostEqual(reps[0]["sla_hours_left"], 48.0, delta=0.1)
        self.assertFalse(reps[0]["sla_breached"])


class TestDataHealthViews(LiveBase):
    """Data health (admin-panel audit §Missing views): the server
    already knows all of this — the panel just never showed it."""

    def test_link_health_real(self):
        lh = self.live.link_health()
        self.assertEqual(lh["failed_total"], 2)
        self.assertEqual(lh["by_failure_class"],
                         {"no_unwrapper": 1, "unwrap_failed": 1})
        self.assertEqual({r["service"]: r["failed"] for r in lh["by_service"]},
                         {"gofile": 1, "mixdrop": 1})

    def test_review_queue_count_real(self):
        self.assertEqual(self.live.review_queue_count(), 1)

    def test_coin_summary_real(self):
        coins = self.live.coin_summary()
        self.assertTrue(coins["available"])
        self.assertEqual(coins["rows"], 3)
        self.assertEqual(coins["granted"], 600)
        self.assertEqual(coins["spent"], -300)
        self.assertEqual(coins["by_reason"]["grant"], {"rows": 2, "total": 600})
        self.assertEqual(coins["by_reason"]["redeem_request"],
                         {"rows": 1, "total": -300})

    def test_search_users_has_coin_balance(self):
        res = self.svc.search_users(self.owner)
        by_id = {u["id"]: u for u in res["items"]}
        self.assertEqual(by_id[1]["balance"], 200)
        self.assertEqual(by_id[2]["balance"], 100)

    def test_catalog_overview_real(self):
        ov = self.svc.catalog_overview(self.owner)
        self.assertTrue(ov["available"])
        self.assertEqual(ov["works"], 3)
        self.assertEqual(ov["posts"], 4)
        self.assertEqual(ov["adult_posts"], 1)
        self.assertEqual(ov["adult_works"], 0)

    def test_data_health_real(self):
        d = self.svc.data_health(self.owner)
        self.assertTrue(d["available"])
        self.assertEqual(d["link_health"]["failed_total"], 2)
        self.assertEqual(d["review_queue_count"], 1)
        self.assertEqual(len(d["review_queue"]), 1)
        self.assertEqual(d["projection"]["rev"], "3")
        self.assertAlmostEqual(d["projection"]["age_h"], 5.0, delta=0.5)
        self.assertEqual(d["projection"]["link_coverage"], 0.0)
        self.assertEqual(d["projection"]["identity_suspect"], 41432)
        self.assertEqual(d["projection"]["release_dups"], 295711)
        self.assertEqual(d["projection"]["id_map_rows"], 4735950)
        self.assertEqual(d["projection"]["unchecked_links"], 1)
        self.assertEqual(d["adult"], {"posts": 1, "works": 0})
        self.assertEqual(d["coins"]["rows"], 3)
        self.assertEqual(len(d["fleet"]), 25)
        # Session 107: drift rides along — the fixture projection is
        # 5 h old with no `posts` key, so it is fresh and the drift is unknown.
        self.assertFalse(d["drift"]["stale"])
        self.assertEqual(d["drift"]["reasons"], [])
        self.assertEqual(d["drift"]["ledger_posts"], 4)
        self.assertIsNone(d["drift"]["projected_posts"])

    def test_fleet_ever_ran_and_mostly_skipped(self):
        # vegamovies has a status file: it ran.
        vega = self.live.fleet_status("vegamovies")
        self.assertTrue(vega["ever_ran"])
        # multimovies has no status file and no audit row: never ran.
        multi = self.live.fleet_status("multimovies")
        self.assertFalse(multi["ever_ran"])
        self.assertIsNone(multi["last_sync_at"])
        # A crawl that skipped almost everything is a failure reason,
        # not a pass (live vegamovies: completed 2, failed 5, skipped 324).
        with open(os.path.join(self.status_dir, "multimovies_status.json"), "w") as fh:
            json.dump({"completed": 2, "total": 331, "failed": 5,
                       "skipped": 324, "updated_at": "2026-10-23T19:36:40Z"}, fh)
        multi = self.live.fleet_status("multimovies")
        self.assertTrue(multi["ever_ran"])
        self.assertIn("mostly skipped: 324 of 331", multi["failure_reason"])

    def test_cert_sudo_fallback_parses_openssl(self):
        from admin_v2.live_stores import _parse_openssl_not_after, _read_cert_via_sudo
        parsed = _parse_openssl_not_after("notAfter=Jan 31 11:04:00 2027 GMT")
        self.assertEqual(parsed, {"date": "31 Jan 2027", "iso": "2027-01-31",
                                  "unix": 1801393440})
        self.assertIsNone(_parse_openssl_not_after("garbage"))
        self.assertIsNone(_parse_openssl_not_after(""))
        # _read_cert_via_sudo with a mocked sudo that succeeds.
        from unittest.mock import patch
        with patch("admin_v2.live_stores.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "notAfter=Jan 31 11:04:00 2027 GMT\n"
            out = _read_cert_via_sudo("/etc/letsencrypt/live/x/fullchain.pem")
            self.assertEqual(out["iso"], "2027-01-31")
            args = run.call_args[0][0]
            self.assertEqual(args[:5], ["sudo", "-n", "openssl", "x509", "-enddate"])
            self.assertNotIn("shell", run.call_args[1])
        # A sudo failure (no sudoers line) returns None, never raises.
        with patch("admin_v2.live_stores.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            self.assertIsNone(_read_cert_via_sudo("/etc/letsencrypt/live/x/fullchain.pem"))

    def test_cert_expiry_uses_sudo_when_direct_read_fails(self):
        from unittest.mock import patch
        with patch("admin_v2.live_stores.ssl._ssl._test_decode_cert",
                   side_effect=OSError("Permission denied")), \
             patch("admin_v2.live_stores._read_cert_via_sudo",
                   return_value={"date": "31 Jan 2027", "iso": "2027-01-31",
                                 "unix": 1801393440}):
            self.assertEqual(self.live.cert_expiry()["iso"], "2027-01-31")

    def test_system_health_service_probe(self):
        # Nothing listens on 59999 here: down, not unknown.
        health = self.live.system_health(".", service_port=59999)
        self.assertEqual(health["service_state"], "down")
        # No port given: the old "unknown" stays.
        self.assertEqual(self.live.system_health(".")["service_state"], "unknown")

    def test_data_health_page_renders_real_numbers(self):
        from admin_v2.server import AdminApp
        app = AdminApp(self.svc)
        import json as _json
        status, _c, payload, cookie, _l = app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            _json.dumps({"username": "owner",
                         "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        headers = {"Cookie": cookie.split(";")[0]}
        status, _c, payload, _k, _l = app.handle(
            "GET", "/admin/data-health", {}, headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Failed links", html)
        self.assertIn("Projection truth", html)
        self.assertIn("Review queue (1 items)", html)
        self.assertIn("Coin ledger", html)
        self.assertIn("Never ran", html)

    def test_data_health_page_shows_drift_alert_when_stale(self):
        # Session 107: age the fixture projection past the 48 h line —
        # the page must say so first, in plain words.
        conn = sqlite3.connect(self.catalog_path)
        conn.execute("UPDATE cat_projection_meta SET value = ? WHERE key = 'projected_at'",
                     (str(self.now - 100 * 3600),))
        conn.commit()
        conn.close()
        from admin_v2.server import AdminApp
        app = AdminApp(self.svc)
        import json as _json
        status, _c, payload, cookie, _l = app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            _json.dumps({"username": "owner",
                         "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        headers = {"Cookie": cookie.split(";")[0]}
        status, _c, payload, _k, _l = app.handle(
            "GET", "/admin/data-health", {}, headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Projection drift", html)
        self.assertIn("100.0 h old", html)
        self.assertIn("Ledger posts:", html)

    def test_dashboard_shows_works_not_just_posts(self):
        from admin_v2.server import AdminApp
        app = AdminApp(self.svc)
        import json as _json
        status, _c, payload, cookie, _l = app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            _json.dumps({"username": "owner",
                         "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200)
        headers = {"Cookie": cookie.split(";")[0]}
        status, _c, payload, _k, _l = app.handle(
            "GET", "/admin", {}, headers, b"")
        self.assertEqual(status, 200)
        html = payload.decode()
        self.assertIn("Catalog: 4 posts, 3 works", html)
        self.assertIn("Review queue: 1 items", html)


class TestLiveRoutesAndRecovery(LiveBase):
    def _app(self):
        app = AdminApp(self.svc)
        res = self.svc.login("owner", "correct horse battery staple", ip="127.0.0.1")
        self.cookie = "admin_session=%s" % res["session_token"]
        self.csrf = res["csrf_token"]
        return app

    def _post(self, app, path, body):
        import json as _json
        return app.handle("POST", path, {},
                          {"Cookie": self.cookie, "Content-Type": "application/json",
                           "X-CSRF-Token": self.csrf},
                          _json.dumps(body).encode())

    def _get(self, app, path):
        return app.handle("GET", path, {}, {"Cookie": self.cookie}, b"")

    def test_contact_and_report_intake_routes(self):
        app = self._app()
        st, _ct, payload, _k, _l = self._post(
            app, "/admin/api/v2/contact",
            {"category": "bug", "subject": "Play fails", "body": "tap play, nothing"})
        self.assertEqual(st, 200)
        st, _ct, payload, _k, _l = self._post(
            app, "/admin/api/v2/reports",
            {"reason": "broken", "work_id": 1, "detail": "link dead"})
        self.assertEqual(st, 200)
        self.assertEqual(len(self.svc.list_contact(self.owner)["items"]), 1)
        self.assertEqual(len(self.svc.list_reports(self.owner)["items"]), 1)

    def test_broadcast_update_route_and_user_payments_route(self):
        app = self._app()
        bc = self.svc.create_broadcast(self.owner, {"title": "Old", "body": "Hi"})
        updated = self.svc.update_broadcast(self.owner, bc["id"], {"title": "New title"})
        self.assertEqual(updated["title"], "New title")
        st, _ct, payload, _k, _l = app.handle(
            "PUT", "/admin/api/v2/broadcasts/%d" % bc["id"], {},
            {"Cookie": self.cookie, "Content-Type": "application/json",
             "X-CSRF-Token": self.csrf},
            b'{"title": "Newer title"}')
        self.assertEqual(st, 200)
        hint = account_hint(self.key1)
        import urllib.parse
        st, _ct, payload, _k, _l = self._get(
            app, "/admin/api/v2/users/%s/payments" % urllib.parse.quote(hint, safe=""))
        self.assertEqual(st, 200)
        self.assertIn(b'"count": 2', payload)

    def test_section_preview_and_review_queue_routes(self):
        app = self._app()
        st, _ct, payload, _k, _l = self._get(app, "/admin/api/v2/sections/movie/preview")
        self.assertEqual(st, 200)
        self.assertIn(b"Real Movie Two", payload)
        st, _ct, payload, _k, _l = self._get(app, "/admin/api/v2/review-queue")
        self.assertEqual(st, 200)
        self.assertIn(b"adult_proof", payload)

    def test_money_page_has_submitted_date_and_settings_has_login_times(self):
        app = self._app()
        st, _ct, payload, _k, _l = self._get(app, "/admin/money")
        html = payload.decode()
        self.assertIn("Submitted", html)
        st, _ct, payload, _k, _l = self._get(app, "/admin/settings")
        html = payload.decode()
        self.assertIn("Recent login attempts", html)
        self.assertIn("When", html)
        self.assertNotIn("2027-01-31", html)

    def test_money_page_renders_real_submitted_dates(self):
        # The Submitted column must show a real formatted date when live
        # rows exist (the live ledger was empty, so the browser could
        # only see the honest empty state). Seeded rows carry
        # submitted_at = now-500/400/300.
        app = self._app()
        st, _ct, payload, _k, _l = self._get(app, "/admin/money")
        self.assertEqual(st, 200)
        html = payload.decode()
        self.assertNotIn("No pending payments", html)
        self.assertIn(templates.fmt_date(int(self.now) - 300), html)
        self.assertIn("PKR 1,500", html)
        self.assertIn("PKR 200", html)

    def test_recovery_token_single_use_vm_local_only(self):
        from admin_v2 import recovery
        token = recovery.enable_recovery(self.admin_dir)
        self.assertTrue(recovery.verify_recovery(self.admin_dir, token))
        self.assertFalse(recovery.verify_recovery(self.admin_dir, token))
        self.assertFalse(recovery.verify_recovery(self.admin_dir, "wrong-token"))
        # No HTTP route exposes recovery.
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "admin_v2", "server.py")) as fh:
            src = fh.read()
        self.assertNotIn("recovery", src)


class TestLiveRequests(LiveBase):
    """D2.6: the v1 /admin/requests page ported to v2 (Session 78)."""

    def test_list_requests_open_oldest_first_with_hints_and_balances(self):
        res = self.svc.list_requests(self.owner)
        self.assertTrue(res["available"])
        self.assertEqual(res["open_count"], 2)
        self.assertEqual([r["id"] for r in res["open"]], [1, 2])
        self.assertEqual([r["id"] for r in res["recent"]], [2, 3, 1])
        first = res["open"][0]
        self.assertEqual(first["hint"], account_hint(self.key1))
        self.assertEqual(first["profile"], "First Viewer")
        self.assertEqual(first["balance"], 200)  # 500 grant - 300 request
        self.assertEqual(res["open"][1]["balance"], 100)
        self.assertEqual(res["open"][1]["profile"], "")

    def test_list_requests_scrubs_urls_from_notes(self):
        res = self.svc.list_requests(self.owner)
        indexed = [r for r in res["recent"] if r["id"] == 3][0]
        self.assertNotIn("https://example.test/trailer", indexed["notes"])
        self.assertIn("[link removed]", indexed["notes"])

    def test_review_marks_indexed_and_replay_is_noop(self):
        res = self.svc.review_request(self.owner, 1, "indexed",
                                      {"confirm": True})
        self.assertEqual(res, {"id": 1, "status": "indexed", "changed": True})
        again = self.svc.review_request(self.owner, 1, "indexed",
                                        {"confirm": True})
        self.assertEqual(again["changed"], False)
        self.assertEqual(again["status"], "indexed")
        self.assertEqual(self.svc.list_requests(self.owner)["open_count"], 1)

    def test_review_unknown_id_bad_status_and_no_confirm_refused(self):
        from admin_v2.errors import ApiError
        with self.assertRaises(ApiError):
            self.svc.review_request(self.owner, 99, "indexed",
                                    {"confirm": True})
        with self.assertRaises(ApiError):
            self.svc.review_request(self.owner, 1, "open",
                                    {"confirm": True})
        with self.assertRaises(ApiError):
            self.svc.review_request(self.owner, 1, "indexed", {})
        with self.assertRaises(ApiError):
            self.svc.review_request(self.auditor, 1, "indexed",
                                    {"confirm": True})

    def test_trigger_queues_fleet_run_and_keeps_request_open(self):
        res = self.svc.trigger_request_crawl(self.owner, {
            "request_id": 2, "crawler": "multimovies",
            "mode": "sync", "limit": 25})
        self.assertEqual(res["status"], "running")
        self.assertEqual(res["site_key"], "multimovies")
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("multimovies", " ".join(self.spawned[0]["cmd"]))
        row = self.svc.admin.execute(
            "SELECT status FROM fleet_runs WHERE site_key='multimovies'"
            ).fetchone()
        self.assertEqual(row["status"], "running")
        # The request stays open until the operator has seen the title.
        self.assertEqual(self.svc.list_requests(self.owner)["open_count"], 2)

    def test_trigger_closed_request_unknown_site_and_auditor_refused(self):
        from admin_v2.errors import ApiError
        with self.assertRaises(ApiError):
            self.svc.trigger_request_crawl(self.owner, {
                "request_id": 3, "crawler": "multimovies",
                "mode": "sync", "limit": 25})
        with self.assertRaises(ApiError):
            self.svc.trigger_request_crawl(self.owner, {
                "request_id": 1, "crawler": "not-a-site",
                "mode": "sync", "limit": 25})
        with self.assertRaises(ApiError):
            self.svc.trigger_request_crawl(self.auditor, {
                "request_id": 1, "crawler": "multimovies",
                "mode": "sync", "limit": 25})

    def test_requests_page_renders_queue_and_actions(self):
        app = AdminApp(self.svc)
        status, _ctype, payload, cookie, _loc = app.handle(
            "POST", "/admin/login", {},
            {"Content-Type": "application/json"},
            json.dumps({"username": "owner",
                        "password": "correct horse battery staple"}).encode())
        self.assertEqual(status, 200, payload.decode())
        status, _ctype, payload, _ck, _loc = app.handle(
            "GET", "/admin/requests", {},
            {"Cookie": cookie.split(";")[0]}, b"")
        self.assertEqual(status, 200, payload.decode())
        html = payload.decode()
        self.assertIn("Old Requested Title", html)
        self.assertIn("New Requested Title", html)
        self.assertIn("/admin/api/v2/requests/1/indexed", html)
        self.assertIn("/admin/api/v2/requests/2/declined", html)
        self.assertIn("/admin/api/v2/requests/trigger", html)
        self.assertIn("First Viewer", html)
        self.assertIn("200 coins", html)


class TestLiveUsage(LiveBase):
    """Tracking A (Session 97): the Usage page reads the usage_* tables
    the server writes — the same numbers `usage_stats.summary()` returns,
    re-read here read-only. Fixture rows are keyed to `self.now` so the
    windows are exact, and one metric row sits outside the 30-day window
    on purpose: it must never count."""

    def _seed_usage(self):
        today = int(self.now // 86400)
        conn = self._ledger()
        conn.executemany(
            "INSERT INTO usage_device (device_hash, install_day, first_seen_at,"
            " last_seen_at, geo, locale, app_version, device_class, region,"
            " audio_lang, subtitle_lang, retained_1, retained_7, retained_30)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [("dev-aaa", today, self.now - 3600, self.now - 60,
              "pk", "ur-PK", "1.0.4", "high", "desi_dubs", "hi", "en", 0, 0, 0),
             ("dev-bbb", today - 10, self.now - 10 * 86400, self.now - 3600,
              "in", "en-IN", "1.0.4", "mid", "desi_dubs", "ur", "en", 1, 1, 0),
             ("dev-ccc", today - 40, self.now - 40 * 86400, self.now - 40 * 86400,
              "unknown", "unknown", "1.0.3", "low", "international", "en", "unknown", 1, 1, 1)])
        conn.executemany(
            "INSERT INTO usage_metric (day, metric, total) VALUES (?,?,?)",
            [(today, "playback_start", 10),
             (today, "playback_attempt", 8),
             (today, "playback_buffer_failure", 2),
             (today, "crash", 1),
             (today, "ad_impression", 2000),
             (today, "ad_click", 20),
             (today, "rewarded_completion", 5),
             (today, "account_request", 50),
             (today, "session", 30),
             (today - 40, "playback_start", 999)])
        conn.executemany(
            "INSERT INTO usage_dim_metric (day, dim, value, metric, total)"
            " VALUES (?,?,?,?,?)",
            [(today, "device_class", "high", "crash", 1),
             (today, "device_class", "mid", "playback_buffer_failure", 2),
             (today, "device_class", "low", "error", 3)])
        conn.executemany(
            "INSERT INTO payment_transactions (id, account_id, plan, amount_pkr,"
            " method, tid, status, submitted_at) VALUES (?,?,?,?,?,?,?,?)",
            [(4, 1, "vip_monthly", 200, "jazzcash", "USAGETEST4", "approved",
              self.now - 200),
             (5, 2, "vip_yearly", 1500, "easypaisa", "USAGETEST5", "approved",
              self.now - 100)])
        conn.commit()
        conn.close()

    def _app(self):
        app = AdminApp(self.svc)
        res = self.svc.login("owner", "correct horse battery staple", ip="127.0.0.1")
        self.cookie = "admin_session=%s" % res["session_token"]
        self.csrf = res["csrf_token"]
        return app

    def _get(self, app, path):
        return app.handle("GET", path, {}, {"Cookie": self.cookie}, b"")

    def test_usage_summary_numbers(self):
        self._seed_usage()
        data = self.live.usage_summary(now=self.now)
        self.assertTrue(data["available"])
        self.assertEqual(data["window_days"], 30)
        installs = data["installs"]
        self.assertEqual(installs["distinct_devices"], 3)
        self.assertEqual(installs["new_today"], 1)
        self.assertEqual(installs["new_this_window"], 2)
        live = data["live_sessions"]
        self.assertEqual(live, {"5m": 1, "30m": 1, "60m": 2})
        active = data["active_users"]
        self.assertEqual(active, {"dau": 2, "wau": 2, "mau": 2})
        retention = data["retention"]
        self.assertEqual(retention["d1"], {"cohort_installs": 2, "returned": 2, "rate": 1.0})
        self.assertEqual(retention["d7"], {"cohort_installs": 2, "returned": 2, "rate": 1.0})
        self.assertEqual(retention["d30"], {"cohort_installs": 1, "returned": 1, "rate": 1.0})
        dims = data["per_dimension_installed"]
        self.assertEqual(dims["geo"], {"pk": 1, "in": 1, "unknown": 1})
        self.assertEqual(dims["region"], {"desi_dubs": 2, "international": 1})
        self.assertEqual(dims["audio_lang"], {"hi": 1, "ur": 1, "en": 1})
        self.assertEqual(dims["subtitle_lang"], {"en": 2, "unknown": 1})
        self.assertEqual(dims["device_class"], {"high": 1, "mid": 1, "low": 1})
        self.assertEqual(dims["app_version"], {"1.0.4": 2, "1.0.3": 1})
        active_dims = data["per_dimension_active"]
        self.assertEqual(active_dims["region"], {"desi_dubs": 2})
        self.assertNotIn("international", active_dims["region"])
        metrics = data["metrics"]
        self.assertEqual(metrics["playback_start"], 10.0)
        self.assertNotEqual(metrics["playback_start"], 1009.0)
        self.assertEqual(data["crash_by_class"], {"high": 1.0})
        self.assertEqual(data["error_by_class"], {"low": 3.0})
        self.assertEqual(data["buffer_failure_by_class"], {"mid": 2.0})
        payments = data["payments"]
        self.assertEqual(payments["by_tier"]["vip_monthly"],
                         {"purchases": 1, "amount_pkr": 200})
        self.assertEqual(payments["by_tier"]["vip_yearly"],
                         {"purchases": 1, "amount_pkr": 1500})
        self.assertEqual(payments["total_pkr"], 1700)
        self.assertEqual(payments["purchases"], 2)
        self.assertEqual(payments["pending"], 3)
        playback = data["playback"]
        self.assertEqual(playback["server_stream_starts"], 10.0)
        self.assertEqual(playback["client_playback_attempts"], 8.0)
        self.assertEqual(playback["buffer_failures"], 2.0)
        self.assertEqual(playback["buffer_failure_rate"], 0.25)
        self.assertEqual(playback["rate_denominator"], "client_attempts")
        self.assertEqual(playback["starts_per_device"], 2.67)
        estimate = data["revenue_estimate"]
        self.assertEqual(estimate["ad_usd_in_window"], 1.8)
        self.assertEqual(estimate["ad_usd_per_1000_users"], 900.0)
        self.assertEqual(estimate["ad_usd_per_1000_users_per_day"], 30.0)
        self.assertEqual(estimate["ctr"], 0.01)
        self.assertEqual(estimate["rewarded_per_1000_users"], 2500.0)
        self.assertTrue(estimate["estimate"])
        pending = data["sources"]["reported_by_client_pending"]
        self.assertEqual(pending, ["ad_fill", "ad_request", "coin_granted",
                                   "error", "playback_error"])
        self.assertFalse(data["identity"]["ip_stored"])
        self.assertFalse(data["identity"]["per_person_timeline"])

    def test_usage_summary_empty_tables_is_honest_not_zero(self):
        data = self.live.usage_summary(now=self.now)
        self.assertFalse(data["available"])
        self.assertTrue(data["no_usage_data_yet"])
        self.assertEqual(data["installs"]["distinct_devices"], 0)

    def test_usage_summary_missing_table_is_honest_not_an_error(self):
        import sqlite3 as _sqlite3
        bare = os.path.join(self.tmp, "bare-ledger.db")
        conn = _sqlite3.connect(bare)
        conn.execute("CREATE TABLE user_accounts (id INTEGER PRIMARY KEY,"
                     " key_hash TEXT UNIQUE, created_at REAL, last_seen_at REAL,"
                     " revoked_at REAL, vip_until REAL DEFAULT 0,"
                     " profile_name TEXT NOT NULL DEFAULT '')")
        conn.commit()
        conn.close()
        bare_live = LiveStores(ledger_path=bare)
        data = bare_live.usage_summary(now=self.now)
        self.assertFalse(data["available"])
        self.assertEqual(data["detail"], "no_usage_data_yet")

    def test_search_users_device_count_is_unknown_not_zero(self):
        res = self.live.search_users()
        self.assertEqual(len(res["items"]), 2)
        for item in res["items"]:
            self.assertIsNone(item["device_count"])
            self.assertEqual(item["devices"], "unknown")

    def test_usage_page_and_api_render_real_numbers(self):
        self._seed_usage()
        app = self._app()
        st, _ct, payload, _k, _l = self._get(app, "/admin/usage")
        self.assertEqual(st, 200)
        html = payload.decode()
        self.assertIn("Distinct installs", html)
        self.assertIn("desi_dubs", html)
        self.assertIn("audio_lang", html)
        self.assertIn("Revenue estimate", html)
        self.assertIn("Client-reported families still pending", html)
        self.assertIn("coin_granted", html)
        st, _ct, payload, _k, _l = self._get(app, "/admin/api/v2/usage")
        self.assertEqual(st, 200)
        import json as _json
        data = _json.loads(payload.decode())["data"]
        self.assertTrue(data["available"])
        self.assertEqual(data["installs"]["distinct_devices"], 3)
        self.assertEqual(data["per_dimension_installed"]["region"]["desi_dubs"], 2)
        st, _ct, payload, _k, _l = self._get(app, "/admin/users")
        self.assertEqual(st, 200)
        self.assertIn("unknown", payload.decode())

    def test_usage_page_empty_state_is_honest(self):
        app = self._app()
        st, _ct, payload, _k, _l = self._get(app, "/admin/usage")
        self.assertEqual(st, 200)
        self.assertIn("nothing has been counted yet", payload.decode())


if __name__ == "__main__":
    unittest.main()
