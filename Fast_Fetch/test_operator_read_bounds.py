#!/usr/bin/env python3
"""The operator's own reads are bounded, they say so, and they need the credential.

Two separate failures are being closed here, and they are easy to confuse:

  * **Volume.** `/api/data` is the dashboard's feed over a ledger measured at
    6.4 GB / 150k posts / 1.38 M releases / 3.8 M links, on a box with ONE vCPU and
    11.9 GB of RAM. `radd-stream` was OOM-killed at 19:14:31 on this host; an
    unbounded admin read is the same class of self-inflicted denial of service,
    arriving from the person who owns the box rather than from an attacker. The
    rows are therefore capped (`_LEDGER_PAGE_CEILING`) and `/api/sitemap` — the one
    sibling that still passed a caller's number straight into SQL — is capped too.
    A cap the operator cannot see is a cap that gets mistaken for the whole table,
    so the answer now carries `page.truncated` (rows remain behind this page) and
    `page.clamped` (the requested page size was reduced to the ceiling).

  * **Credential.** Measured 2026-10-29 05:47 on this host, one process listened on
    both 127.0.0.1:8080 and 127.0.0.1:8081, nginx forwarded neither, and on the
    operator port `/`, `/api/v1/stats` and `/api/v1/rules` answered whoever reached
    the socket — the last two of them for a *bogus* bearer token, because the token
    was only consulted on `/admin`. That is what `admin_panel.gate_operator_port`
    and `viewer._operator_gate` close: the credential now runs before any SQL, on
    every route of that port.

Said plainly, because the two facts are not in tension and a future reader must not
infer otherwise: **loopback is the reachability boundary — nginx forwards neither
port and this suite proves the process, not the edge — and the bearer token is the
credential the operator port additionally requires.** Nothing here makes the
dashboard "token-gated" in the sense of reachable-by-anyone-holding-a-password:
it is bound to loopback first and the token is checked second, and with
`RADD_ADMIN_TOKEN` unset the whole port fails closed.

Every test names a socket, not nginx: these two servers are real `HTTPServer`s on
127.0.0.1 with port 0, so a green run means the *code* refuses, whatever the edge
happens to be doing. Every database is a `tempfile.TemporaryDirectory`; nothing
reads the production catalog, a credential, or the live service.

    python3 -S Fast_Fetch/test_operator_read_bounds.py
"""
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

TOKEN = "operator-read-bounds-suite-credential"
BOGUS = "obviously-not-the-operator-token"

#: The routes that exist on the operator port and are invisible on the public one.
#: A snapshot, deliberately: widening this set is a public-surface change and must
#: fail a test rather than pass a review.
OPERATOR_ONLY = ["/api/data", "/api/sitemap", "/api/fetch", "/api/heal",
                 "/api/health-check", "/api/v1/rules", "/admin", "/admin/anything"]

#: The documented public reads. `test_the_public_allow_list_is_unchanged` proves the
#: process still answers each of these with no credential at all — the boundary this
#: lane was told not to disturb.
PUBLIC_READS = ["/api/v1/posts?page=1", "/api/v1/stats", "/api/v1/app/remote-config"]

PAGE_KEYS = {"limit", "page", "offset", "returned", "has_more", "truncated",
             "clamped", "ceiling"}


def _media(site, slug, *, title=None, year=2024):
    title = title or f"Film {slug}"
    return {
        "url": f"https://{site}.example/{slug}/",
        "slug": slug,
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
        "is_18_plus": 0,
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


def _payload(limit=None, page=1, **kwargs):
    """`fetch_database_payload` with defaults filled, so a test states only what it varies."""
    kwargs.setdefault("full", True)
    return viewer.fetch_database_payload("", limit=limit, page=page, **kwargs)


class BoundedLedgerFunctionTests(unittest.TestCase):
    """The function contract: the cap holds, and the answer admits it was capped."""

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

    def seed(self, count):
        for n in range(count):
            fast_fetch.save_scraped_data(_media("site_a", f"post-{n}"))

    def test_an_oversized_page_is_clamped_and_says_so(self):
        self.seed(3)
        page = _payload(limit=100000)["page"]
        self.assertEqual(page["limit"], viewer._LEDGER_PAGE_CEILING)
        self.assertTrue(page["clamped"],
                        "a caller that asked for 100000 rows must be told it got 200")

    def test_an_honest_page_size_is_not_reported_as_clamped(self):
        self.seed(3)
        for asked in (1, 50, viewer._LEDGER_PAGE_CEILING):
            page = _payload(limit=asked)["page"]
            self.assertEqual(page["limit"], asked)
            self.assertFalse(page["clamped"], f"limit={asked} was never refused")

    def test_a_nonsense_limit_is_the_default_and_not_a_crash(self):
        self.seed(2)
        for asked in ("abc", "", None, [], {}):
            page = _payload(limit=asked)["page"]
            self.assertEqual(page["limit"], viewer._LEDGER_PAGE_DEFAULT, repr(asked))
            self.assertFalse(page["clamped"], repr(asked))

    def test_a_zero_or_negative_page_size_is_lifted_and_marked(self):
        self.seed(2)
        for asked in (0, -1):
            page = _payload(limit=asked)["page"]
            self.assertEqual(page["limit"], 1)
            self.assertTrue(page["clamped"], f"limit={asked} is not what was asked")

    def test_truncated_names_the_rows_that_stay_behind(self):
        self.seed(7)
        first = _payload(limit=3, page=1)["page"]
        self.assertEqual(first["returned"], 3)
        self.assertTrue(first["truncated"])
        self.assertTrue(first["has_more"])
        last = _payload(limit=3, page=3)["page"]
        self.assertEqual(last["returned"], 1)
        self.assertFalse(last["truncated"],
                         "the end of the ledger must not be reported as a truncation")
        self.assertFalse(last["has_more"])

    def test_truncated_and_has_more_are_the_same_fact_under_both_names(self):
        self.seed(5)
        for page_no in (1, 2):
            page = _payload(limit=2, page=page_no)["page"]
            self.assertEqual(page["truncated"], page["has_more"])

    def test_the_page_contract_survives_an_absent_database(self):
        """A caller that cannot see the difference between "empty" and "not read"
        is one `if not rows:` away from concluding the ledger is empty."""
        missing = Path(self.tmp.name) / "never-written.db"
        with mock.patch.object(viewer, "DB_PATH", missing):
            page = _payload(limit=99999)["page"]
        self.assertTrue(PAGE_KEYS <= set(page), sorted(PAGE_KEYS - set(page)))
        self.assertEqual(page["returned"], 0)
        self.assertFalse(page["truncated"])
        self.assertTrue(page["clamped"])

    def test_the_page_always_carries_every_key_the_dashboard_reads(self):
        self.seed(1)
        for asked in (None, 25, 100000):
            page = _payload(limit=asked)["page"]
            self.assertEqual(set(page), PAGE_KEYS, json.dumps(page))


class BoundedSitemapTests(unittest.TestCase):
    """`/api/sitemap`'s reader used to hand a caller's number straight to SQL."""

    @classmethod
    def setUpClass(cls):
        cls.servers = _TwoPorts()
        cls.servers.start()
        cls.public_url = cls.servers.public_url
        cls.operator_url = cls.servers.operator_url
        # Seeded into the same temp catalog the two servers are serving, so the
        # route test and the function test read one shared, known row count.
        with sqlite3.connect(cls.servers.db_path) as conn:
            conn.executemany(
                "INSERT INTO sitemap_cache (loc, slug, lastmod, scraped, site)"
                " VALUES (?, ?, ?, 0, 'vegamovies')",
                [(f"https://vegamovies.example/t-{n}/", f"t-{n}", "2026-01-01")
                 for n in range(viewer._SITEMAP_ROW_CEILING + 120)])
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        cls.servers.stop()

    def test_the_row_count_is_capped_at_the_ceiling(self):
        rows = viewer.search_sitemap_api("", site="all", limit=99_999_999)
        self.assertLessEqual(len(rows), viewer._SITEMAP_ROW_CEILING,
                             "the sitemap read must not answer more than the ceiling")
        self.assertEqual(len(rows), viewer._SITEMAP_ROW_CEILING,
                         "with 620 rows seeded, the cap must actually bite")

    def test_the_route_clamps_and_answers_200_instead_of_500(self):
        """`int(query_params)` raised on `?limit=abc` out of the handler; a 500 from
        an operator page is how a diagnostic gets turned off and a hole stays open."""
        for asked in ("abc", "", "-3", "99999999"):
            status, body = _fetch(self.operator_url, f"/api/sitemap?limit={asked}",
                                  TOKEN)
            self.assertEqual(status, 200, asked)
            self.assertLessEqual(len(json.loads(body)), viewer._SITEMAP_ROW_CEILING,
                                 asked)

    def test_the_public_port_still_never_answers_the_sitemap(self):
        status, _ = _fetch(self.public_url, "/api/sitemap?limit=5", None)
        self.assertEqual(status, 404)


class OperatorPortCredentialTests(unittest.TestCase):
    """Over a real socket: the operator port answers the token, not the interface.

    Named for the process, not for nginx — nginx forwards neither port, so a green
    run here says the code refuses a stranger. It says nothing about the edge, and
    is not supposed to.
    """

    @classmethod
    def setUpClass(cls):
        cls.servers = _TwoPorts()
        cls.servers.start()

    @classmethod
    def tearDownClass(cls):
        cls.servers.stop()

    def test_a_bogus_bearer_token_is_refused_on_the_operator_reads(self):
        for path in ("/api/v1/stats", "/api/v1/rules", "/api/data", "/api/sitemap",
                     "/", "/client"):
            status, body = _fetch(self.servers.operator_url, path, BOGUS)
            self.assertIn(status, (401, 403), f"{path} answered {status} to nonsense")
            self.assertNotIn("posts_count", body.decode("utf-8", "replace"), path)

    def test_no_credential_at_all_is_the_same_answer_as_nonsense(self):
        for path in ("/api/v1/stats", "/api/v1/rules", "/"):
            anonymous = _fetch(self.servers.operator_url, path, None)
            bogus = _fetch(self.servers.operator_url, path, BOGUS)
            self.assertEqual(anonymous[0], bogus[0], path)
            self.assertEqual(anonymous[1], bogus[1],
                             f"{path}: a refusal must not leak whether a token exists")

    def test_the_real_token_serves_the_reads_it_used_to_hand_out_freely(self):
        for path in ("/api/v1/stats", "/api/data?limit=5"):
            status, body = _fetch(self.servers.operator_url, path, TOKEN)
            self.assertEqual(status, 200, f"{path}: {status} {body[:120]!r}")

    def test_the_wire_reports_the_clamp_on_the_dashboard_feed(self):
        status, body = _fetch(self.servers.operator_url, "/api/data?limit=100000",
                              TOKEN)
        self.assertEqual(status, 200)
        page = json.loads(body)["page"]
        self.assertEqual(page["limit"], viewer._LEDGER_PAGE_CEILING)
        self.assertTrue(page["clamped"])
        self.assertIn("truncated", page)

    def test_an_unset_token_failcloses_the_whole_operator_port(self):
        """No token configured is not an open door: the port denies everything."""
        with mock.patch.dict("os.environ"):
            os.environ.pop("RADD_ADMIN_TOKEN", None)
            for path in ("/api/v1/stats", "/api/data", "/"):
                status, _ = _fetch(self.servers.operator_url, path, TOKEN)
                self.assertIn(status, (401, 403),
                              f"{path} answered with no credential configured")

    def test_the_public_allow_list_is_unchanged(self):
        """Nothing in this lane widened the public surface, and nothing narrowed it.

        The public port answers these with no credential because that is what a
        client has; it 404s every operator route because a stranger must not learn
        they exist.
        """
        for path in PUBLIC_READS:
            status, _ = _fetch(self.servers.public_url, path, None)
            self.assertEqual(status, 200, f"{path} -> {status}")
        for path in OPERATOR_ONLY:
            status, _ = _fetch(self.servers.public_url, path, TOKEN)
            self.assertEqual(status, 404, f"{path} is visible on the public port")

    def test_the_operator_only_route_set_is_the_snapshot_it_was_reviewed_as(self):
        self.assertEqual(
            set(viewer.OPERATOR_ONLY_ROUTES),
            {"/api/sitemap", "/api/fetch", "/api/heal", "/api/health-check",
             "/api/v1/rules", "/api/data"})
        self.assertEqual(tuple(viewer.OPERATOR_ONLY_PREFIXES), ("/admin",))


class _TwoPorts:
    """Two real loopback servers, built once per class — the socket is the test.

    `viewer.make_server(..., operator=True)` is the same code path the unit runs on
    127.0.0.1:8081; `operator=False` is the :8080 face. A request here goes through
    the handler, the route table, the credential gate and the JSON writer.
    """

    def __init__(self):
        self.tmp = None
        self.db_path = None
        self.public = None
        self.operator = None
        self.env = None
        self.patchers = []

    def start(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "catalog.db"
        db_path = self.db_path
        self.env = mock.patch.dict("os.environ", {
            "RADD_ADMIN_TOKEN": TOKEN,
            "RADD_USER_STATE_DB": str(Path(self.tmp.name) / "user_state.db"),
        })
        self.env.start()
        self.patchers = [mock.patch.object(t, "DB_PATH", db_path)
                         for t in (fast_fetch, viewer)]
        self.patchers.append(mock.patch.object(fast_fetch, "fetch_cinemeta_metadata",
                                               return_value=None))
        for patcher in self.patchers:
            patcher.start()
        fast_fetch.init_db()
        fast_fetch.save_scraped_data(_media("site_a", "one"))
        self.public = viewer.make_server("127.0.0.1", 0, operator=False)
        self.operator = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (self.public, self.operator):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.public_url = f"http://127.0.0.1:{self.public.server_address[1]}"
        self.operator_url = f"http://127.0.0.1:{self.operator.server_address[1]}"

    def stop(self):
        for server in (self.public, self.operator):
            if server is not None:
                server.shutdown()
                server.server_close()
        for patcher in self.patchers:
            patcher.stop()
        if self.env is not None:
            self.env.stop()
        if self.tmp is not None:
            self.tmp.cleanup()


def _fetch(base, path, token):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    request = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


if __name__ == "__main__":
    print("fixture: %s (offline — temp SQLite + loopback sockets, no network, "
          "no production catalog)" % Path(__file__).name)
    unittest.main(verbosity=2)
