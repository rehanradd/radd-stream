"""Offline tests for the Hindilinks4u retry / park / fuse / lock-tolerance fix.

Fully offline: a temp SQLite file via tempfile, a stub client, no sockets and no
real site. Proves the behaviour the 2026-10-23 diagnosis said was missing:

  (a) a parked -1 row with a *transient* cause is re-queued while an -1 row whose
      cause is genuinely permanent (http_404_gone) is not;
  (b) a row that has spent its whole budget (attempts == MAX_CRAWL_ATTEMPTS) is
      never retried again;
  (c) the site's PERMANENT_CAUSES does not contradict the shared core in
      fast_fetch, and no name is in both the permanent and the transient set;
  (d) with a client that always fails on transport, the site-dark fuse stops the
      pass after exactly `threshold` failures instead of grinding the queue;
  (e) the init_staging_db attempts/last_attempt/last_cause migration is
      idempotent and safe against an old 6-column database.

Style follows the existing test_hindilinks4u.py.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fast_fetch
import import_hindilinks4u as hl


def _old_schema_db(db_path: Path):
    """Creates a database with the OLD 6-column sitemap_cache schema (no retry cols)."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE sitemap_cache (
                loc TEXT PRIMARY KEY,
                lastmod TEXT,
                slug TEXT,
                scraped INTEGER DEFAULT 0,
                site TEXT DEFAULT 'hindilinks4u',
                raw_json TEXT
            );
            """
        )
        conn.commit()


def _sm_columns(db_path: Path):
    with sqlite3.connect(str(db_path)) as conn:
        return {c[1] for c in conn.execute("PRAGMA table_info(sitemap_cache);").fetchall()}


def _seed(conn, loc, scraped, attempts=None, cause=None):
    conn.execute(
        "INSERT INTO sitemap_cache (loc, slug, scraped, site, attempts, last_cause)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (loc, loc.rstrip("/").split("/")[-1], scraped, hl.SITE_NAME, attempts, cause),
    )


def _queue_locs(db_path):
    return {row[0] for row in hl.crawl_queue(db_path)}


class TransientVsParkedQueueTests(unittest.TestCase):
    """(a) the queue re-selects a transient -1 but never a parked -1."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "hindilinks4u.db"
        hl.init_staging_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _book(self, loc, cause_name):
        """Seeds a fresh page then books one failed attempt exactly the way the
        crawler does: park-vs-retry delegated to fast_fetch.crawl_attempt_state()."""
        with sqlite3.connect(self.db) as conn:
            _seed(conn, loc, 0)
            conn.commit()
        scraped, attempts = fast_fetch.crawl_attempt_state(
            cause_name, prior_attempts=0, permanent=hl.PERMANENT_CAUSES)
        hl.record_cause(self.db, loc, scraped, hl._cause(cause_name), attempts=attempts)
        return scraped, attempts

    def test_transient_parked_row_is_requeued_but_404_is_not(self):
        transient_loc = "https://www.hindilinks4u.zip/sarphira-1992/"
        gone_loc = "https://www.hindilinks4u.zip/deleted-post/"

        _s, t_attempts = self._book(transient_loc, "no_sources_on_page")
        _s, g_attempts = self._book(gone_loc, "http_404_gone")

        # A transient cause spends ONE unit of the budget and stays selectable.
        self.assertLess(t_attempts, fast_fetch.MAX_CRAWL_ATTEMPTS)
        # A permanent cause parks immediately (attempts pushed to the max).
        self.assertEqual(g_attempts, fast_fetch.MAX_CRAWL_ATTEMPTS)

        locs = _queue_locs(self.db)
        self.assertIn(transient_loc, locs)
        self.assertNotIn(gone_loc, locs)


class RetryBudgetTests(unittest.TestCase):
    """(b) attempts at/over the cap are never re-selected; fresh pages are."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "hindilinks4u.db"
        hl.init_staging_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_row_at_max_attempts_is_not_retried(self):
        exhausted = "https://www.hindilinks4u.zip/always-timeout/"
        fresh = "https://www.hindilinks4u.zip/never-tried/"
        with sqlite3.connect(self.db) as conn:
            # A transient cause that has already burned its whole budget.
            _seed(conn, exhausted, -1, attempts=fast_fetch.MAX_CRAWL_ATTEMPTS,
                  cause="transport_error")
            _seed(conn, fresh, 0, attempts=0, cause=None)
            conn.commit()
        locs = _queue_locs(self.db)
        self.assertNotIn(exhausted, locs)
        self.assertIn(fresh, locs)

    def test_limit_is_honoured_by_the_queue(self):
        with sqlite3.connect(self.db) as conn:
            for i in range(5):
                _seed(conn, f"https://www.hindilinks4u.zip/post{i}/", 0, attempts=0)
            conn.commit()
        self.assertEqual(len(hl.crawl_queue(self.db, limit=3)), 3)


class VocabularyConsistencyTests(unittest.TestCase):
    """(c) one shared vocabulary — no site/core contradiction, no double-classified name."""

    def test_site_permanent_agrees_with_core_permanent(self):
        # Every shared name that the site calls permanent must not be a name the
        # core treats as transient (that would be a direct contradiction).
        self.assertFalse(hl.PERMANENT_CAUSES & fast_fetch.TRANSIENT_CRAWL_CAUSES)
        # The core's genuinely-permanent names survive in the site set.
        self.assertTrue(fast_fetch.PERMANENT_CRAWL_CAUSES <= hl.PERMANENT_CAUSES)

    def test_no_name_is_both_permanent_and_transient(self):
        self.assertFalse(hl.PERMANENT_CAUSES & hl.TRANSIENT_CAUSES)

    def test_diagnosed_names_were_moved_to_transient(self):
        for name in ("no_sources_on_page", "parse_no_title",
                     "http_403_forbidden", "blocked: challenge"):
            self.assertNotIn(name, hl.PERMANENT_CAUSES, name)
            self.assertIn(name, hl.TRANSIENT_CAUSES, name)

    def test_genuinely_permanent_names_stay_permanent(self):
        for name in ("http_404_gone", "http_410_gone", "skipped: not_a_post"):
            self.assertIn(name, hl.PERMANENT_CAUSES, name)

    def test_lock_is_never_permanent(self):
        # A lock says nothing about the page: sqlite_locked must be retryable.
        self.assertNotIn("sqlite_locked", hl.PERMANENT_CAUSES)
        self.assertIn("sqlite_locked", hl.TRANSIENT_CAUSES)

    def test_cause_flag_follows_reconciled_sets(self):
        self.assertFalse(hl._cause("no_sources_on_page")["permanent"])
        self.assertFalse(hl._cause("blocked: challenge")["permanent"])
        self.assertFalse(hl._cause("http_403_forbidden")["permanent"])
        self.assertTrue(hl._cause("http_404_gone")["permanent"])
        self.assertFalse(hl._cause("ok")["permanent"])


class AlwaysFailClient:
    """Stub whose get_text always returns the (0, url, '') empty-transport tuple."""
    base_url = hl.DEFAULT_BASE_URL

    def get_text(self, url, **kwargs):
        return 0, url, ""


class SiteDarkFuseTests(unittest.TestCase):
    """(d) a run of transport failures trips the fuse at exactly the threshold."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "hindilinks4u.db"
        hl.init_staging_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pass_stops_at_fuse_threshold(self):
        threshold = 4
        total = 10
        with sqlite3.connect(self.db) as conn:
            for i in range(total):
                _seed(conn, f"https://www.hindilinks4u.zip/post{i}/", 0, attempts=0)
            conn.commit()

        hl.run_crawler(
            self.db, hl.DEFAULT_BASE_URL,
            workers=1, delay=0, client=AlwaysFailClient(), dark_threshold=threshold)

        with sqlite3.connect(self.db) as conn:
            failed = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1").fetchone()[0]
            untouched = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0").fetchone()[0]
        # The pass must stop having booked exactly `threshold` failures, leaving
        # the rest of the queue untouched rather than manufacturing fresh -1s.
        self.assertEqual(failed, threshold)
        self.assertEqual(untouched, total - threshold)


class LockTolerantBookingTests(unittest.TestCase):
    """(support for #4) a hard (non-lock) booking error is not raised; it defers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "hindilinks4u.db"
        hl.init_staging_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_booking_write_survives_and_returns_true(self):
        loc = "https://www.hindilinks4u.zip/heal-me/"
        with sqlite3.connect(self.db) as conn:
            _seed(conn, loc, 0, attempts=0)
            conn.commit()
        self.assertTrue(hl.record_cause(
            self.db, loc, -1, hl._cause("transport_error"), attempts=1))
        with sqlite3.connect(self.db) as conn:
            scraped, attempts, last_cause = conn.execute(
                "SELECT scraped, attempts, last_cause FROM sitemap_cache WHERE loc = ?",
                (loc,)).fetchone()
        self.assertEqual((scraped, attempts, last_cause), (-1, 1, "transport_error"))

    def test_save_wrapper_defers_without_raising(self):
        # save_post_to_staging_db must return a falsey signal (never raise) when
        # it cannot book, leaving the caller's crawl alive.
        self.assertFalse(hl.save_post_to_staging_db(self.db, {}))
        self.assertFalse(hl.save_post_to_staging_db(self.db, {"releases": []}))


class MigrationIdempotencyTests(unittest.TestCase):
    """(e) init_staging_db migrates an old 6-column DB, safely, more than once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "hindilinks4u.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_adds_columns_and_is_idempotent(self):
        _old_schema_db(self.db)
        self.assertEqual(_sm_columns(self.db),
                         {"loc", "lastmod", "slug", "scraped", "site", "raw_json"})

        # First run migrates; a second run must be a no-op and never raise.
        hl.init_staging_db(self.db)
        first = _sm_columns(self.db)
        hl.init_staging_db(self.db)
        second = _sm_columns(self.db)

        for col in ("attempts", "last_attempt", "last_cause"):
            self.assertIn(col, first, col)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
