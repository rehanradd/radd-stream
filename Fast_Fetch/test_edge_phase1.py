#!/usr/bin/env python3
"""Registered suite for the public edge: the list offset window and the neutral
image-host allowlist. Offline — a temp ledger, loopback servers, no catalog read.

    python3 -S Fast_Fetch/test_edge_phase1.py

Two guarantees, one per area:

* **The offset window.** `bounded_int` (viewer.py) already floors and ceilings each
  number, and its own docstring is the `?page=abc` 502 fix — so a page of
  `?page=1000000&limit=100` is two legal values whose *product* is the exposure:
  SQLite walks `OFFSET 99,999,900`. That product, not either number, is what
  `POSTS_MAX_OFFSET` bounds, and the refusal must be a `page_beyond_range` body
  rather than a silently shortened page.
* **The art host rule.** A work's poster leaves this box direct only when its host
  is a third-party CDN we name. A neutral upload bucket names nothing in its host
  but everything in its *filename*, so those URLs are additionally scanned against
  the same token set `is_clean` uses. A scraper's own domain never goes direct.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redact              # noqa: E402
import test_redact as tr   # noqa: E402  (fixture harness only, not its assertions)
import viewer              # noqa: E402

SECRET = "unit-test-secret"
#: The ceiling `bounded_int` enforces on this route today; asserted here so that a
#: change to it is a decision, not a side effect.
ROUTE_LIMIT_CEILING = 100


class OffsetWindowHttpTests(tr.FixtureMixin):
    """`/api/v1/posts` paging, over real HTTP on loopback."""

    @classmethod
    def setUpClass(cls):
        cls.public_server = viewer.make_server("127.0.0.1", 0, operator=False)
        threading.Thread(target=cls.public_server.serve_forever, daemon=True).start()
        cls.public_port = cls.public_server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.public_server.shutdown()
        cls.public_server.server_close()

    def setUp(self):
        self.make_ledger()
        redact.limiter._buckets.clear()

    def tearDown(self):
        super().tearDown()
        redact.limiter._buckets.clear()

    def get(self, path):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.public_port}{path}", timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def test_first_page_still_answers(self):
        status, body = self.get("/api/v1/posts?limit=20&page=1")
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual((payload["page"], payload["limit"]), (1, 20))

    def test_last_page_inside_the_window_is_served(self):
        last = viewer.POSTS_MAX_OFFSET // ROUTE_LIMIT_CEILING + 1
        status, body = self.get(f"/api/v1/posts?limit={ROUTE_LIMIT_CEILING}&page={last}")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["page"], last)

    def test_one_page_past_the_window_is_a_refusal_not_a_short_page(self):
        over = viewer.POSTS_MAX_OFFSET // ROUTE_LIMIT_CEILING + 2
        status, body = self.get(f"/api/v1/posts?limit={ROUTE_LIMIT_CEILING}&page={over}")
        self.assertEqual(status, 400, body)
        payload = json.loads(body)
        self.assertEqual(payload["error"], "page_beyond_range")
        self.assertEqual(payload["max_offset"], viewer.POSTS_MAX_OFFSET)
        self.assertIs(payload["success"], False)

    def test_the_pair_that_motivated_the_cap(self):
        # Both numbers are legal under bounded_int; only the product is the problem.
        status, body = self.get("/api/v1/posts?page=1000000&limit=100")
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["error"], "page_beyond_range")

    def test_limit_one_does_not_get_a_wider_window(self):
        # The bound is on rows skipped, so a smaller page must not skip more.
        inside = self.get(f"/api/v1/posts?limit=1&page={viewer.POSTS_MAX_OFFSET + 1}")
        outside = self.get(f"/api/v1/posts?limit=1&page={viewer.POSTS_MAX_OFFSET + 2}")
        self.assertEqual(inside[0], 200, inside[1])
        self.assertEqual(outside[0], 400, outside[1])

    def test_non_integer_and_out_of_range_values_keep_the_shipped_fallbacks(self):
        # Regression pins for `bounded_int`, which had no suite referencing it.
        status, body = self.get("/api/v1/posts?page=abc&limit=abc")
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual((payload["page"], payload["limit"]), (1, 20), body)
        status, body = self.get("/api/v1/posts?page=0&limit=0")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["page"], 1, body)
        status, body = self.get(f"/api/v1/posts?limit={ROUTE_LIMIT_CEILING * 50}")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["limit"], ROUTE_LIMIT_CEILING, body)


class NeutralImageHostTests(unittest.TestCase):
    """Which stored artwork URL may be named in public, and which becomes a handle."""

    def test_named_cdn_is_still_direct(self):
        url = "https://image.tmdb.org/t/p/w500/abc.jpg"
        self.assertEqual(redact.public_image_value(url), url)
        self.assertEqual(redact.public_art_value(url, 5, SECRET, "", "poster"), url)

    def test_neutral_upload_host_goes_direct(self):
        for url in ("https://i.imgur.com/pdrmC8P.jpeg",
                    "https://iili.io/AbCdEf.png",
                    "https://catimages.org/images/2026-09-16/The-Fixie-2017.jpg",
                    "https://i.imageflix.cam/images/2026-06-10/7b2c82.jpg",
                    "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsE.jpg",
                    "https://lh3.googleusercontent.com/foo/bar.jpg"):
            self.assertEqual(redact.public_image_value(url), url, url)

    def test_neutral_host_with_a_source_named_in_the_path_stays_handled(self):
        # The crown's 22:47 ruling: the substring scan is conservative on purpose,
        # so a site name merged inside one word still costs the caller a redirect.
        for url in ("https://catimages.org/images/vegamovies-poster.jpg",
                    "https://blogger.googleusercontent.com/img/hdhub4u/x.jpg",
                    "https://i.imgur.com/vegamovieshd.jpg",
                    "https://iili.io/pixeldrain.png"):
            self.assertIsNone(redact.public_image_value(url), url)
            handle = redact.public_art_value(url, 5, SECRET, "", "poster")
            self.assertTrue(handle.startswith("/api/v1/art?id="), handle)

    def test_scraper_host_is_never_direct_however_clean_its_path(self):
        for url in ("https://www.moviesmela.com/wp-content/uploads/a.jpg",
                    "https://thefilmyzilla.in/upload/a.webp",
                    "https://www.pagalmovies.fit/files/images/a.jpg",
                    "https://www.hindilinks4u.zip/wp-content/uploads/a.jpg",
                    "https://img.hdhub4u.example/poster.jpg"):
            self.assertIsNone(redact.public_image_value(url), url)

    def test_no_neutral_host_is_itself_a_source(self):
        # A scraper domain added to the neutral sets would defeat the whole rule.
        for host in redact.NEUTRAL_UPLOAD_HOSTS:
            self.assertFalse(redact._url_names_source(host), host)
        self.assertFalse(redact._url_names_source("googleusercontent.com"))

    def test_every_loaded_token_is_caught_in_a_url(self):
        for token in sorted(redact.needles()):
            if len(token) < 4:
                continue
            for host in redact.NEUTRAL_UPLOAD_HOSTS:
                url = f"https://{host}/2026/{token}/x.jpg"
                self.assertIsNone(redact.public_image_value(url), url)

    def test_empty_and_malformed(self):
        for value in (None, "", "   ", "not a url"):
            self.assertIsNone(redact.public_image_value(value))

    def test_token_cache_follows_a_reloaded_registry(self):
        # set_needles() rebinds the live registry at startup; the compiled scan must
        # rebuild with it rather than keep answering on the import-time set.
        try:
            redact.set_needles({"totallynewhoster"})
            self.assertIsNone(
                redact.public_image_value("https://catimages.org/totallynewhoster/x.jpg"))
            self.assertEqual(  # the import-time token is no longer loaded
                redact.public_image_value("https://catimages.org/vegamovies/x.jpg"),
                "https://catimages.org/vegamovies/x.jpg")
        finally:
            redact.set_needles(redact.BASE_NEEDLES)
        self.assertIsNone(
            redact.public_image_value("https://catimages.org/vegamovies/x.jpg"))


class ArtHandleStillResolvesTests(tr.FixtureMixin):
    """Widening the direct set must not break the redirector for everything else."""

    def setUp(self):
        self.make_ledger()
        redact.limiter._buckets.clear()

    def test_scraper_poster_is_still_a_resolvable_handle(self):
        # The fixture's second post stores an hdhub4u-hosted poster. Minted with the
        # service's own secret, because the redirector parses with that one.
        secret = viewer.signing_secret()
        handle = redact.public_art_value("https://img.hdhub4u.example/poster.jpg",
                                         self.second_id, secret, "", "poster")
        self.assertTrue(handle.startswith("/api/v1/art?id="), handle)
        self.assertNotIn("hdhub4u", handle)
        token = handle.split("id=")[1].split("&")[0]
        self.assertEqual(redact.parse_token(token, secret), int(self.second_id))
        self.assertEqual(redact.art_url_for(int(self.second_id), "poster", 0,
                                            str(viewer.DB_PATH)),
                         "https://img.hdhub4u.example/poster.jpg")


if __name__ == "__main__":
    unittest.main(verbosity=2)
