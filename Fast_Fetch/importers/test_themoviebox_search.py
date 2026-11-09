#!/usr/bin/env python3
"""
test_themoviebox_search.py — offline unit tests for the MovieBox search flow.

No test touches the network: ``urllib.request.urlopen`` is replaced with a
fake, every DB is a temp file, and no real Bearer token is ever printed or
stored — the token fixtures below are the literal string "tok", never a
value minted against the live site. The rules this suite keeps, and the
measured fact each one exists because of:

* the search token is minted client-side: ``<unix-seconds>,<md5(reversed
  seconds)>`` (the site's own YC() from its JS bundle, measured 2026-11-09).
* ``/subject/search`` takes ``Authorization: Bearer <token>`` ALONE — sending
  Bearer and ``X-Client-Token`` together answers 400 'invalid token'.
* a search hit is picked by exact title match among accepted subject types
  (1 movie, 2 series); type 6 music mixes, type 7 concert mixes and type 9
  sports clips are never works, however well they match the words.
* a no-subject slug stem is the search keyword: the trailing 12-char
  mixed-case id is not part of the title, the dub marker (``hindi``) is.
* ``recover`` queues what search finds and writes no posts itself — the
  crawl fetches the detail API and exports the full record, the same
  two-step shape as sync-then-crawl. A target search finds nothing for is
  counted in ``not_found`` with its keyword, never silently dropped.
* a 400 'invalid token' mints once more and retries the same keyword.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_themoviebox as mb  # noqa: E402

AQUAMAN = {
    "subjectId": "9083306165420838488",
    "subjectType": 1,
    "title": "Aquaman",
    "releaseDate": "2018-12-07",
    "detailPath": "aquaman-SnujlNADZOa",
}
BLACK_ADAM = {
    "subjectId": "5531044087626875944",
    "subjectType": 1,
    "title": "Black Adam",
    "releaseDate": "2022-10-19",
    "detailPath": "black-adam-kOM94SUeAA6",
}
MUSIC_MIX = {
    "subjectId": "777",
    "subjectType": 6,
    "title": "Aquaman",
    "releaseDate": "2024-01-01",
    "detailPath": "aquaman-mix-x1",
}


def silenced():
    return contextlib.redirect_stdout(io.StringIO())


class FakeResponse:
    """A urlopen answer: status, headers mapping, body, context manager."""

    def __init__(self, status=200, body="", headers=None):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def search_body(items):
    return json.dumps({"code": 0, "data": {"items": items,
                                           "pager": {"hasMore": False}}})


class ClientTokenTests(unittest.TestCase):
    def test_shape_is_seconds_comma_md5_of_reversed_seconds(self):
        token = mb.client_token(now=1700000000)
        self.assertRegex(token, r"^\d+,[0-9a-f]{32}$")
        seconds, digest = token.split(",")
        self.assertEqual(seconds, "1700000000")
        self.assertEqual(digest, hashlib.md5(b"0000000071").hexdigest())

    def test_seconds_part_is_the_clock(self):
        before = int(__import__("time").time())
        token = mb.client_token()
        after = int(__import__("time").time())
        seconds = int(token.split(",")[0])
        self.assertTrue(before <= seconds <= after)


class TokenRequestTests(unittest.TestCase):
    def _urlopen(self, response):
        calls = {"requests": []}

        def fake(request, timeout=None):
            calls["requests"].append(request)
            return response

        return calls, fake

    def test_token_comes_from_the_x_user_header(self):
        payload = json.dumps({"appType": 1, "token": "tok",
                              "userId": "9", "userType": 1})
        calls, fake = self._urlopen(
            FakeResponse(200, "{}", {"x-user": payload}))
        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen", fake):
            status, parsed = mb._token_request(delay=0)
        self.assertEqual(status, 200)
        self.assertEqual(parsed, json.loads(payload))
        request = calls["requests"][0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertRegex(request.get_header("X-client-token") or "",
                         r"^\d+,[0-9a-f]{32}$")

    def test_missing_x_user_header_means_no_token(self):
        calls, fake = self._urlopen(FakeResponse(200, "{}"))
        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen", fake):
            status, parsed = mb._token_request(delay=0)
        self.assertEqual((status, parsed), (200, None))

    def test_http_error_returns_its_code_without_a_token(self):
        error = urllib.error.HTTPError("https://x.test/", 400, "Bad",
                                       {}, io.BytesIO(b"bad"))
        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen",
                                  mock.Mock(side_effect=error)):
            self.assertEqual(mb._token_request(delay=0), (400, None))

    def test_transport_failure_is_retried_then_answered(self):
        calls = {"n": 0}

        def flaky(request, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("reset")
            return FakeResponse(200, "{}", {"x-user": "{\"token\": \"tok\"}"})

        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen", flaky), \
                mock.patch.object(mb.time, "sleep"):
            status, parsed = mb._token_request(delay=0)
        self.assertEqual((status, parsed, calls["n"]),
                         (200, {"token": "tok"}, 3))


class FetchBearerTokenTests(unittest.TestCase):
    def test_returns_the_token_from_the_header_json(self):
        with mock.patch.object(mb, "_token_request",
                               return_value=(200, {"token": "tok"})):
            self.assertEqual(mb.fetch_bearer_token(), "tok")

    def test_no_token_when_the_header_is_absent_or_the_call_failed(self):
        for answer in ((200, None), (0, None), (400, None)):
            with mock.patch.object(mb, "_token_request", return_value=answer):
                self.assertIsNone(mb.fetch_bearer_token(), answer)


class SearchSubjectsTests(unittest.TestCase):
    def test_bearer_alone_no_client_token_header(self):
        calls = {"requests": []}

        def fake(request, timeout=None):
            calls["requests"].append(request)
            return FakeResponse(200, search_body([AQUAMAN, BLACK_ADAM]))

        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen", fake):
            status, items = mb.search_subjects("aquaman", "tok", delay=0)
        self.assertEqual(status, 200)
        self.assertEqual([it["title"] for it in items],
                         ["Aquaman", "Black Adam"])
        request = calls["requests"][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer tok")
        self.assertIsNone(request.get_header("X-client-token"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["keyword"], "aquaman")

    def test_http_400_means_invalid_token_not_an_empty_catalog(self):
        error = urllib.error.HTTPError("https://x.test/", 400, "Bad",
                                       {}, io.BytesIO(b"invalid token"))
        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen",
                                  mock.Mock(side_effect=error)):
            self.assertEqual(mb.search_subjects("aquaman", "tok", delay=0),
                             (400, []))

    def test_transport_failure_is_retried_like_the_filter_call(self):
        calls = {"n": 0}

        def flaky(request, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("reset")
            return FakeResponse(200, search_body([AQUAMAN]))

        with mock.patch.object(mb, "_throttle", lambda delay: None), \
                mock.patch.object(urllib.request, "urlopen", flaky), \
                mock.patch.object(mb.time, "sleep"):
            status, items = mb.search_subjects("aquaman", "tok", delay=0)
        self.assertEqual((status, [it["title"] for it in items], calls["n"]),
                         (200, ["Aquaman"], 3))


class KeywordAndPickTests(unittest.TestCase):
    def test_slug_id_is_dropped_but_the_dub_marker_stays(self):
        self.assertEqual(mb._keyword_from_slug("aquaman-GpwinCWTWw3"),
                         "aquaman")
        self.assertEqual(
            mb._keyword_from_slug("a-shop-for-killers-hindi-GLJXzEty46a"),
            "a shop for killers hindi")
        self.assertEqual(mb._keyword_from_slug("plain-slug"), "plain slug")
        self.assertEqual(mb._keyword_from_slug(None), "")

    def test_exact_title_match_wins_over_first_hit(self):
        items = [BLACK_ADAM, AQUAMAN]
        self.assertEqual(mb.pick_search_hit(items, "aquaman")["subjectId"],
                         AQUAMAN["subjectId"])

    def test_non_works_are_never_picked(self):
        self.assertIsNone(mb.pick_search_hit([MUSIC_MIX], "aquaman"))

    def test_year_breaks_a_title_tie(self):
        # Neither title is an exact match for the keyword, so the year
        # decides between the two accepted hits.
        newer = dict(BLACK_ADAM, title="Aquaman Returns",
                     releaseDate="2022-10-19")
        older = dict(AQUAMAN, title="Aquaman and the Lost Kingdom",
                     releaseDate="2018-12-07")
        hit = mb.pick_search_hit([newer, older], "aquaman", year=2018)
        self.assertEqual(hit["subjectId"], older["subjectId"])

    def test_no_accepted_hit_is_none(self):
        self.assertIsNone(mb.pick_search_hit([], "aquaman"))


class RecoverTests(unittest.TestCase):
    def _source_db(self, path):
        conn = sqlite3.connect(path, timeout=60)
        conn.row_factory = sqlite3.Row
        mb.ensure_schema(conn)

        def queue(loc, slug, kind):
            ledger = {"failures": [{"kind": kind, "http_status": 200}]}
            conn.execute(
                "INSERT INTO sitemap_cache (loc, lastmod, slug, scraped,"
                " raw_json, error_count) VALUES (?, NULL, ?, 2, ?, 2)",
                (loc, slug, json.dumps(ledger)))

        queue("https://themoviebox.xyz/detail/aquaman-GpwinCWTWw3",
              "aquaman-GpwinCWTWw3", "no-subject")
        queue("https://themoviebox.xyz/detail/alpha-hindi-EwwJ7rcnnL9",
              "alpha-hindi-EwwJ7rcnnL9", "no-subject")
        queue("https://themoviebox.xyz/detail/gone-404-x1",
              "gone-404-x1", "http-404")
        conn.execute(
            "INSERT INTO posts (canonical_key, title, clean_title, year,"
            " media_type, url, slug) VALUES (?, ?, ?, ?, 'movie', ?, ?)",
            ("28-days-later_2003", "28 Days Later", "28 Days Later", 2003,
             "https://themoviebox.xyz/detail/28-days-later-x1",
             "28-days-later-x1"))
        conn.commit()
        conn.close()

    def test_recover_queues_search_hits_and_counts_the_miss(self):
        hits = {
            "aquaman": [BLACK_ADAM, AQUAMAN],
            "alpha hindi": [],
            "28 Days Later": [dict(AQUAMAN, subjectId="111", title="28 Days Later",
                                   detailPath="28-days-later-x1")],
        }

        def fake_search(keyword, token, page=1, per_page=10, delay=0.3):
            return 200, hits[keyword]

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            target = Path(tmp) / "followup.db"
            self._source_db(source)
            with silenced(), \
                    mock.patch.object(mb, "memory_ok",
                                      return_value=(True, "ok")), \
                    mock.patch.object(mb, "fetch_bearer_token",
                                      return_value="tok"), \
                    mock.patch.object(mb, "search_subjects",
                                      side_effect=fake_search):
                totals = mb.recover_missing(target, source_db=source, delay=0)
            self.assertEqual(totals["targets"], 3, totals)
            self.assertEqual(totals["found"], 2, totals)
            self.assertEqual(totals["queued"], 2, totals)
            self.assertEqual(totals["not_found"], 1, totals)
            self.assertEqual(totals["not_found_keywords"], ["alpha hindi"])
            conn = sqlite3.connect(target)
            conn.row_factory = sqlite3.Row
            queued = conn.execute(
                "SELECT loc, raw_json FROM sitemap_cache"
                " ORDER BY loc").fetchall()
            conn.close()
            self.assertEqual(len(queued), 2)
            self.assertEqual(
                [json.loads(row["raw_json"])["subjectId"] for row in queued],
                ["111", "9083306165420838488"])

    def test_recover_refetches_the_token_once_on_a_400(self):
        calls = {"search": 0}

        def flaky_search(keyword, token, page=1, per_page=10, delay=0.3):
            calls["search"] += 1
            if calls["search"] == 1:
                return 400, []
            return 200, [AQUAMAN]

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            target = Path(tmp) / "followup.db"
            self._source_db(source)
            with silenced(), \
                    mock.patch.object(mb, "memory_ok",
                                      return_value=(True, "ok")), \
                    mock.patch.object(mb, "fetch_bearer_token",
                                      return_value="tok"), \
                    mock.patch.object(mb, "search_subjects",
                                      side_effect=flaky_search):
                totals = mb.recover_missing(target, source_db=source,
                                            limit=1, delay=0)
            self.assertEqual(totals["queued"], 1, totals)
            self.assertEqual(calls["search"], 2)

    def test_recover_without_a_token_reports_and_queues_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.db"
            target = Path(tmp) / "followup.db"
            self._source_db(source)
            with silenced(), \
                    mock.patch.object(mb, "fetch_bearer_token",
                                      return_value=None):
                totals = mb.recover_missing(target, source_db=source, delay=0)
            self.assertEqual(totals["token"], False, totals)
            self.assertEqual(totals["queued"], 0, totals)
            self.assertFalse(target.exists() and
                             sqlite3.connect(target).execute(
                                 "SELECT COUNT(*) FROM sitemap_cache"
                             ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
