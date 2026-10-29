#!/usr/bin/env python3
"""`/api/data` is paginated, and its counters are stamped — not counted per load.

Measured on 2026-10-30 against the production file (`merged_catalog_20261025.db`,
6.4 GB, ~150k posts / 1.38 M releases / 3.8 M links, opened `mode=ro`):

    COUNT(*) FROM posts                    0.38 s
    COUNT(*) FROM posts WHERE is_18_plus=1 93.04 s
    industry LIKE '%Hollywood%'            5.99 s
    industry LIKE '%Bollywood%' OR India   15.21 s
    COUNT(*) FROM releases                112.61 s
    3.8 M-link `GROUP BY state`           42.2 s (already on record)

The endpoint answered 2,533,437 bytes in 46.6 s because it ran that set on every
load. Two bounds close it:

  * **Rows** — `limit` (default 50) is clamped to `_LEDGER_PAGE_CEILING` (200) and
    `page` to a sane range; `has_more` comes from fetching one extra row, never
    from a `COUNT`.
  * **Counters** — the default answer reads `cat_projection_meta` and publishes
    `null` for anything it did not stamp. `stats=full` is the operator's explicit
    live scan; a typo must not fall into it.

Every database here is a `tempfile.TemporaryDirectory`; nothing reads the
production catalog, a credential, or the live service.

    python3 -S Fast_Fetch/test_bounded_ledger.py
"""
import contextlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fast_fetch       # noqa: E402
import viewer           # noqa: E402

TOKEN = "bounded-ledger-suite-credential"

#: Statements that must never appear on the default path. The page's own
#: `SELECT * FROM posts ... LIMIT` is fine and is not in this list: it reads at
#: most `limit + 1` rows. These are the table scans.
SCAN_MARKERS = (
    "select count(*) from posts",
    "select count(*) from releases",
    "select count(*) from download_sources",
    "count(distinct post_id)",
    "group by state",
)


def _media(site, url, *, title="Example Film", year=2024, adult=0):
    return {
        "url": url,
        "slug": url.rstrip("/").split("/")[-1],
        "title": title,
        "clean_title": title,
        "year": year,
        "content_type": "movie",
        "seasons": None,
        "poster_url": None,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": None,
        "synopsis": None,
        "is_18_plus": adult,
        "is_animated": 0,
        "source_site": site,
        "industry": "Hollywood",
        "country": "USA",
        "language": "English",
        "canonical_key": fast_fetch.generate_canonical_key(title, year),
        "tmdb_id": None,
        "imdb_id": None,
        "releases": [{
            "release_title": f"{title} 1080p",
            "quality": "1080p",
            "codec": "x264",
            "size": "1GB",
            "languages": "English",
            "season": None,
            "episode": None,
            "intermediate_url": f"https://{site}.example/release",
            "sources": [{
                "source_name": "Example CDN",
                "service": "test-service",
                "resource_id": f"{site}-id",
                "source_url": f"https://{site}.example/source",
                "final_url": f"https://cdn.example/{site}",
                "is_temporary": 0,
            }],
        }],
    }


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for target in (fast_fetch, viewer):
            patcher = mock.patch.object(target, "DB_PATH", self.db_path)
            patcher.start()
            self.addCleanup(patcher.stop)
        cinemeta = mock.patch.object(fast_fetch, "fetch_cinemeta_metadata",
                                     return_value=None)
        cinemeta.start()
        self.addCleanup(cinemeta.stop)
        fast_fetch.init_db()

    def add(self, site, slug, **kwargs):
        return fast_fetch.save_scraped_data(
            _media(site, f"https://{site}.example/{slug}/", **kwargs))


class BoundedPayloadTests(Fixture):
    """The function contract: rows bounded, counters stamped unless asked."""

    def test_the_default_answer_runs_no_ledger_scan(self):
        self.add("site_a", "one")
        statements = []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.set_trace_callback(statements.append)

        @contextlib.contextmanager
        def traced():
            yield conn

        with mock.patch.object(viewer, "get_db", traced):
            payload = viewer.fetch_database_payload(full=True)

        joined = " ".join(statements).lower()
        for marker in SCAN_MARKERS:
            self.assertNotIn(marker, joined,
                             f"the default payload ran a scan: {marker}")
        self.assertEqual(payload["stats"]["stats_source"], "stamp")
        self.assertIsNone(payload["stats"]["posts_adult"])
        self.assertIn("posts_adult", payload["stats"]["unavailable"])

    def test_stats_full_is_the_only_mode_that_counts(self):
        post = self.add("site_a", "one")
        self.add("site_b", "two", title="Second Film")
        self.add("site_c", "adult", title="Adult Diary", adult=1)

        fast = viewer.fetch_database_payload(full=True)
        live = viewer.fetch_database_payload(full=True, stats="full")

        self.assertIsNone(fast["stats"]["posts_count"],
                          "no stamp exists, so the default must say so")
        self.assertEqual(live["stats"]["stats_source"], "live")
        self.assertEqual(live["stats"]["posts_count"], 3)
        self.assertEqual(live["stats"]["posts_adult"], 1)
        self.assertEqual(live["stats"]["unavailable"], [])
        self.assertEqual(live["stats"]["rog_posts"], 0)
        ids = [row["id"] for row in live["posts"]]
        self.assertIn(post, ids)

    def test_a_stamp_is_used_without_touching_the_ledger(self):
        self.add("site_a", "one")
        conn = sqlite3.connect(self.db_path)
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE IF NOT EXISTS cat_projection_meta"
                     " (key TEXT PRIMARY KEY, value TEXT)")
        stamps = {
            "posts": "777",
            "releases": "888",
            "links": "999",
            "links_by_state_safe": json.dumps({"active": 5, "dead": 1}),
            "links_resumable_safe": "4",
            "projected_at": "1760000000.0",
        }
        conn.executemany("INSERT OR REPLACE INTO cat_projection_meta"
                         " VALUES(?, ?)", list(stamps.items()))
        conn.commit()

        statements = []
        conn2 = sqlite3.connect(self.db_path)
        conn2.row_factory = sqlite3.Row
        self.addCleanup(conn2.close)
        conn2.set_trace_callback(statements.append)

        @contextlib.contextmanager
        def traced():
            yield conn2

        with mock.patch.object(viewer, "get_db", traced):
            payload = viewer.fetch_database_payload(full=True)

        stats = payload["stats"]
        self.assertEqual(stats["posts_count"], 777)
        self.assertEqual(stats["releases_count"], 888)
        self.assertEqual(stats["sources_count"], 999)
        self.assertEqual(stats["active_sources"], 5)
        self.assertEqual(stats["dead_sources"], 1)
        self.assertEqual(stats["resumable_sources"], 4)
        self.assertNotIn("posts_count", stats["unavailable"])
        joined = " ".join(statements).lower()
        for marker in SCAN_MARKERS:
            self.assertNotIn(marker, joined, f"stamped read scanned: {marker}")

    def test_the_ceiling_holds_for_a_direct_call(self):
        self.add("site_a", "one")
        payload = viewer.fetch_database_payload(full=True, limit=10 ** 6)
        self.assertEqual(payload["page"]["limit"], viewer._LEDGER_PAGE_CEILING)
        self.assertEqual(payload["page"]["ceiling"], 200)

    def test_pages_walk_the_ledger_without_a_count(self):
        for name in ("alpha", "beta", "gamma"):
            self.add("site_a", name, title=f"{name.title()} Film",
                     year=2020 + len(name))
        first = viewer.fetch_database_payload(full=True, limit=2, page=1)
        second = viewer.fetch_database_payload(full=True, limit=2, page=2)
        beyond = viewer.fetch_database_payload(full=True, limit=2, page=9)

        self.assertEqual(len(first["posts"]), 2)
        self.assertTrue(first["page"]["has_more"])
        self.assertEqual(len(second["posts"]), 1)
        self.assertFalse(second["page"]["has_more"])
        self.assertEqual(beyond["posts"], [])
        self.assertFalse(beyond["page"]["has_more"])
        seen = [row["id"] for row in first["posts"] + second["posts"]]
        self.assertEqual(len(set(seen)), 3, "pages must not overlap")

    def test_a_bad_page_or_limit_is_clamped_not_fatal(self):
        payload = viewer.fetch_database_payload(full=True, limit=0, page=0)
        self.assertEqual(payload["page"]["limit"], 1)
        self.assertEqual(payload["page"]["page"], 1)
        payload = viewer.fetch_database_payload(full=True, limit="x", page="y")
        self.assertEqual(payload["page"]["limit"], viewer._LEDGER_PAGE_DEFAULT)


class LedgerRouteTests(unittest.TestCase):
    """The HTTP contract: clamping on the wire, 404 on the public port.

    Deliberately not a `Fixture` subclass: `Fixture.setUp` repoints `DB_PATH` at a
    fresh empty database for each test, and the servers are built once in
    `setUpClass` — the request would then read that empty file and see zero posts.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "catalog.db"
        cls.env = mock.patch.dict("os.environ", {
            "RADD_ADMIN_TOKEN": TOKEN,
            "RADD_USER_STATE_DB": str(Path(cls.tmp.name) / "user_state.db"),
        })
        cls.env.start()
        cls.patchers = [mock.patch.object(t, "DB_PATH", cls.db_path)
                        for t in (fast_fetch, viewer)]
        cls.patchers.append(mock.patch.object(fast_fetch, "fetch_cinemeta_metadata",
                                              return_value=None))
        for patcher in cls.patchers:
            patcher.start()
        fast_fetch.init_db()
        fast_fetch.save_scraped_data(
            _media("site_a", "https://site-a.example/one/"))
        cls.public = viewer.make_server("127.0.0.1", 0, operator=False)
        cls.operator = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (cls.public, cls.operator):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.public_url = f"http://127.0.0.1:{cls.public.server_address[1]}"
        cls.operator_url = f"http://127.0.0.1:{cls.operator.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        for server in (cls.public, cls.operator):
            server.shutdown()
            server.server_close()
        for patcher in cls.patchers:
            patcher.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def fetch(self, base, path):
        request = urllib.request.Request(
            base + path, headers={"Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_the_public_port_never_answers_the_ledger(self):
        for path in ("/api/data", "/api/data?stats=full", "/api/data?limit=999999"):
            status, _ = self.fetch(self.public_url, path)
            self.assertEqual(status, 404, path)

    def test_the_wire_clamps_the_page_size(self):
        status, body = self.fetch(self.operator_url, "/api/data?limit=100000")
        self.assertEqual(status, 200)
        page = json.loads(body)["page"]
        self.assertEqual(page["limit"], 200)
        self.assertLessEqual(page["returned"], 200)

    def test_a_typo_in_stats_falls_back_to_the_stamp(self):
        status, body = self.fetch(self.operator_url, "/api/data?stats=everything")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["stats"]["stats_source"], "stamp")

    def test_stats_full_answers_live_on_the_operator_port(self):
        status, body = self.fetch(self.operator_url, "/api/data?stats=full&limit=5")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["stats"]["stats_source"], "live")
        self.assertEqual(payload["stats"]["posts_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
