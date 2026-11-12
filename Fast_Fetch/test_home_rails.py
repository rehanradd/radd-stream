#!/usr/bin/env python3
"""Offline tests for the Home rails — GET /api/v1/trending, /api/v1/related,
GET /api/v1/facets, and the two filter extensions they stand on.

What had to be proven, in this order:

1. **Trending is the same order the rail already had.** `/api/v1/trending`
   delegates to `api_v1_get_posts(sort="trending")`, so the test pins that
   the two answers are identical — same order, same envelope — and that an
   adult row never tops the list however many prints it holds.
2. **Related scores what the seed says, and nothing else.** A shared cast
   member outranks a shared genre, the (release+source) tiebreak orders
   equal scores, and a seed with no neighbours — or a missing or adult
   seed — answers an empty page, never an error and never the catalog.
3. **A facet count is what its tap delivers.** Every genre, industry,
   language and type count is asserted equal to the total the matching
   filter returns, so a chip cannot promise a count its tap cannot keep.
   The genre filter covers all 10 panel categories now, and `language=`
   is a real filter, so every facet group is actionable.
4. **The edge.** The three routes answer 200 with the right shape over
   real HTTP, a missing or non-integer `work_id` is a 400, and an adult
   row is indistinguishable from an absent one on every new surface.

    python3 -S Fast_Fetch/test_home_rails.py
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

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import catalog_v2          # noqa: E402
import fast_fetch          # noqa: E402
import panel_feed          # noqa: E402
import redact              # noqa: E402
import viewer              # noqa: E402

_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


class Fixture(unittest.TestCase):
    """A small ledger with known scores, counts and facets.

    The seed is Dune (2021): Action/Sci-Fi/Adventure, Chalamet+Zendaya,
    Hollywood, movie, 2021. The other rows are placed so the related
    scores, the trending order and every facet count are all pinned:

    * Dune: Part Two — score 18 (both genres + both cast + industry + type)
    * Wonka — score 8, 4 prints+mirrors (cast + industry + type + year)
    * Interstellar — score 8, 2 prints+mirrors (two genres + industry + type)
    * Squid Game — score 1, year only (a weak signal still counts)
    * Humsafar — score 0, so it never appears in related (a complete
      season whose genres, cast, industry, type and year are all its own)
    * Adult Film — score 11 on paper, but adult, so it appears nowhere
    """

    def setUp(self):
        redact.set_needles(_BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.addCleanup(redact.set_needles, _BASELINE_NEEDLES,
                        _BASELINE_TEXT_NEEDLES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        catalog_v2.ensure_schema(self.conn)
        self.conn.commit()
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        os.environ["RADD_STREAM_SECRET"] = "test-secret-for-home-rails"
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.addCleanup(setattr, viewer, "_SIGNING_SECRET", None)
        self.addCleanup(lambda: redact.limiter._buckets.clear())
        self.seed_id = self.ingest(
            title="Dune", year=2021, content_type="movie",
            genres=["Action", "Sci-Fi", "Adventure"],
            cast=["Timothee Chalamet", "Zendaya"],
            industry="Hollywood", language="English",
            n_releases=2, n_sources=2)
        self.part_two_id = self.ingest(
            title="Dune: Part Two", year=2024, content_type="movie",
            genres=["Action", "Sci-Fi"],
            cast=["Timothee Chalamet", "Zendaya"],
            industry="Hollywood", language="English",
            n_releases=3, n_sources=2)
        self.interstellar_id = self.ingest(
            title="Interstellar", year=2014, content_type="movie",
            genres=["Sci-Fi", "Adventure", "Drama"],
            cast=["Matthew McConaughey"],
            industry="Hollywood", language="English",
            n_releases=1, n_sources=1)
        self.wonka_id = self.ingest(
            title="Wonka", year=2023, content_type="movie",
            genres=["Comedy", "Family"],
            cast=["Timothee Chalamet"],
            industry="Hollywood", language="English",
            n_releases=2, n_sources=1)
        self.humsafar_id = self.ingest(
            title="Humsafar", year=2011, content_type="complete_season",
            genres=["Romance", "Biography"],
            cast=["Fawad Khan"],
            industry="Pakistani", language="Urdu",
            n_releases=1, n_sources=2)
        self.adult_id = self.ingest(
            title="Adult Film", year=2020, content_type="movie",
            genres=["Action"], cast=["Timothee Chalamet"],
            industry="Hollywood", language="English", is_18_plus=1,
            n_releases=5, n_sources=5)
        self.squid_id = self.ingest(
            title="Squid Game", year=2021, content_type="series",
            genres=["Thriller", "Drama"],
            cast=["Lee Jung-jae"],
            industry="Korean", language="Korean",
            n_releases=2, n_sources=3)

    def ingest(self, *, title, year, content_type, genres, cast,
               industry, language, is_18_plus=0, n_releases=1, n_sources=1):
        slug = title.lower().replace(" ", "-").replace(":", "")
        # Distinct release titles, qualities and source URLs per row, so
        # no two releases or sources collapse into one in the ledger.
        qualities = ["720p", "1080p", "2160p", "480p", "360p"]
        releases = []
        for i in range(n_releases):
            quality = qualities[i % len(qualities)]
            releases.append({
                "release_title": "%s %s part%d" % (title, quality, i),
                "quality": quality, "codec": "x264", "size": "1.5GB",
                "languages": json.dumps([language]),
                "season": "", "episode": "", "intermediate_url": "",
                "origin_url": "", "source_site": "somecdn.site",
                "sources": [{
                    "source_url": "https://cdn.example/%s-%d-%d.mp4"
                                  % (slug, i, j),
                    "quality": quality, "status": "active"}
                    for j in range(n_sources)],
            })
        data = {
            "url": "https://somecdn.site/movie/%s/" % slug,
            "slug": slug,
            "title": "%s (%d)" % (title, year),
            "clean_title": title,
            "year": year,
            "content_type": content_type,
            "poster_url": "https://cdn/poster.jpg",
            "genres": json.dumps(genres),
            "cast_names": json.dumps(cast),
            "synopsis": "%s synopsis" % title,
            "is_18_plus": is_18_plus,
            "source_site": "somecdn.site",
            "industry": industry,
            "country": "India",
            "language": language,
            "canonical_key": fast_fetch.generate_canonical_key(title, year),
            "releases": releases,
        }
        post_id = fast_fetch.save_scraped_data(
            data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()
        return post_id

    def ids(self, resp):
        return [int(item["id"]) for item in resp["results"]]


class TrendingTests(Fixture):
    def test_order_is_release_plus_source_count(self):
        resp = viewer.api_v1_get_trending(limit=20)
        # Part Two 9, Squid Game 8, Dune 6, Wonka 4, Humsafar 3,
        # Interstellar 2. The adult row holds 10 and still never appears.
        self.assertEqual(self.ids(resp), [
            self.part_two_id, self.squid_id, self.seed_id,
            self.wonka_id, self.humsafar_id, self.interstellar_id])
        self.assertEqual(resp["total"], 6)
        self.assertNotIn(self.adult_id, self.ids(resp))

    def test_trending_is_the_posts_trending_sort(self):
        trending = viewer.api_v1_get_trending(limit=20)
        posts = viewer.api_v1_get_posts(sort="trending", limit=20)
        self.assertEqual(self.ids(trending), self.ids(posts))
        self.assertEqual(trending["total"], posts["total"])

    def test_type_filter_and_limit_clamp(self):
        series = viewer.api_v1_get_trending(limit=20, content_type="series")
        self.assertEqual(self.ids(series), [self.squid_id])
        seasons = viewer.api_v1_get_trending(
            limit=20, content_type="complete_season")
        self.assertEqual(self.ids(seasons), [self.humsafar_id])
        self.assertEqual(viewer.api_v1_get_trending(limit=500)["limit"], 100)
        self.assertEqual(viewer.api_v1_get_trending(limit=0)["limit"], 1)

    def test_envelope_is_a_posts_page(self):
        resp = viewer.api_v1_get_trending(limit=3)
        self.assertEqual(resp["page"], 1)
        self.assertEqual(resp["limit"], 3)
        self.assertEqual(resp["total_pages"], 2)
        item = resp["results"][0]
        self.assertIn("poster_url", item)
        self.assertIn("work_ref", item)
        self.assertIn("subtitled", item)
        self.assertNotIn("source_site", item)

    def test_second_hit_serves_the_cached_order(self):
        first = viewer.api_v1_get_trending(limit=20)
        self.assertTrue(viewer._TRENDING_ORDER_CACHE,
                        "the first trending hit must populate the order cache")
        second = viewer.api_v1_get_trending(limit=20)
        self.assertEqual(self.ids(second), self.ids(first))
        self.assertEqual(second["total"], first["total"])
        self.addCleanup(viewer._TRENDING_ORDER_CACHE.clear)

    def test_paging_comes_from_the_cached_order(self):
        first = viewer.api_v1_get_trending(page=1, limit=2)
        second = viewer.api_v1_get_trending(page=2, limit=2)
        self.assertEqual(self.ids(first), [self.part_two_id, self.squid_id])
        self.assertEqual(self.ids(second), [self.seed_id, self.wonka_id])
        self.assertEqual(second["total"], 6)
        self.addCleanup(viewer._TRENDING_ORDER_CACHE.clear)

    def test_page_past_the_end_is_empty_not_an_error(self):
        resp = viewer.api_v1_get_trending(page=99, limit=20)
        self.assertEqual(resp["results"], [])
        self.assertEqual(resp["total"], 6)
        self.addCleanup(viewer._TRENDING_ORDER_CACHE.clear)

    def test_newly_flagged_row_hides_on_the_next_hit(self):
        # The cache holds the ORDER, never the verdict on what may be
        # listed: flag the top row after the first hit and the very
        # next hit must hide it (backfilled, so the page stays full),
        # even though the order itself is still cached — the frozen
        # fingerprint forces the cache-hit path, so a rebuild cannot
        # stand in for the per-request re-check. `total` is the cached
        # COUNT(*) and may lag the same window; it is a number, never
        # a listing.
        with mock.patch.object(viewer, "_trending_db_fingerprint",
                               return_value=("test",)):
            first = viewer.api_v1_get_trending(limit=3)
            self.assertEqual(self.ids(first), [
                self.part_two_id, self.squid_id, self.seed_id])
            self.conn.execute(
                "UPDATE posts SET is_18_plus=1 WHERE id=?",
                (self.part_two_id,))
            self.conn.commit()
            second = viewer.api_v1_get_trending(limit=3)
            self.assertNotIn(self.part_two_id, self.ids(second))
            self.assertEqual(self.ids(second), [
                self.squid_id, self.seed_id, self.wonka_id])
            self.assertEqual(second["total"], 6)
        self.addCleanup(viewer._TRENDING_ORDER_CACHE.clear)


class RelatedTests(Fixture):
    def test_scores_order_and_tiebreak(self):
        resp = viewer.api_v1_get_related(self.seed_id, limit=20)
        # Part Two 18, then Wonka and Interstellar tied at 8 — Wonka
        # first on the (release+source) tiebreak (4 vs 2) — then Squid
        # Game on the year alone (1). Humsafar (0) and the adult row
        # never appear, and neither does the seed itself.
        self.assertEqual(self.ids(resp), [
            self.part_two_id, self.wonka_id,
            self.interstellar_id, self.squid_id])
        self.assertEqual(resp["total"], 4)
        self.assertNotIn(self.seed_id, self.ids(resp))
        self.assertNotIn(self.adult_id, self.ids(resp))
        self.assertNotIn(self.humsafar_id, self.ids(resp))

    def test_paging(self):
        first = viewer.api_v1_get_related(self.seed_id, page=1, limit=2)
        second = viewer.api_v1_get_related(self.seed_id, page=2, limit=2)
        self.assertEqual(self.ids(first), [self.part_two_id, self.wonka_id])
        self.assertEqual(self.ids(second),
                         [self.interstellar_id, self.squid_id])
        self.assertEqual(first["total"], 4)
        self.assertEqual(first["total_pages"], 2)

    def test_missing_seed_is_an_empty_page_not_an_error(self):
        resp = viewer.api_v1_get_related(999999, limit=10)
        self.assertEqual(resp["total"], 0)
        self.assertEqual(resp["results"], [])

    def test_adult_seed_is_an_empty_page(self):
        resp = viewer.api_v1_get_related(self.adult_id, limit=10)
        self.assertEqual(resp["total"], 0)
        self.assertEqual(resp["results"], [])

    def test_seed_with_no_neighbours_is_empty(self):
        # Humsafar shares nothing with any other public row on any axis
        # (its genres, cast, industry, type and year are all its own).
        resp = viewer.api_v1_get_related(self.humsafar_id, limit=10)
        self.assertEqual(resp["total"], 0)
        self.assertEqual(resp["results"], [])

    def test_non_integer_work_id_raises(self):
        for bad in ("abc", "1.5", "", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                viewer.api_v1_get_related(bad)

    def test_envelope_is_a_posts_page(self):
        resp = viewer.api_v1_get_related(self.seed_id, limit=2)
        item = resp["results"][0]
        self.assertIn("poster_url", item)
        self.assertIn("work_ref", item)
        self.assertNotIn("source_site", item)


class FacetsTests(Fixture):
    def _facet(self, facets, group, key):
        for entry in facets[group]:
            if entry["key"] == key:
                return entry
        self.fail("no %s facet %r in %r" % (group, key, facets[group]))

    def test_shape(self):
        facets = viewer.api_v1_get_facets()
        self.assertEqual(set(facets), {"genres", "languages",
                                       "industries", "types"})
        for group in facets.values():
            for entry in group:
                self.assertEqual(set(entry), {"key", "label", "count"})
                self.assertIsInstance(entry["count"], int)
                self.assertGreaterEqual(entry["count"], 0)

    def test_genre_counts(self):
        facets = viewer.api_v1_get_facets()
        expected = {"action": 2, "adventure": 2, "animation": 0,
                    "comedy": 1, "crime": 0, "drama": 2, "horror": 0,
                    "romance": 1, "sci-fi": 3, "thriller": 1}
        self.assertEqual(
            [e["key"] for e in facets["genres"]], list(viewer.GENRE_KEYS))
        for key, count in expected.items():
            self.assertEqual(self._facet(facets, "genres", key)["count"],
                             count, key)

    def test_language_and_industry_and_type_counts(self):
        facets = viewer.api_v1_get_facets()
        self.assertEqual(self._facet(facets, "languages", "english")["count"], 4)
        self.assertEqual(self._facet(facets, "languages", "urdu")["count"], 1)
        self.assertEqual(self._facet(facets, "languages", "korean")["count"], 1)
        self.assertEqual(
            self._facet(facets, "industries", "hollywood")["count"], 4)
        self.assertEqual(
            self._facet(facets, "industries", "pakistani")["count"], 1)
        self.assertEqual(
            self._facet(facets, "industries", "bollywood")["count"], 0)
        self.assertEqual(self._facet(facets, "types", "movie")["count"], 4)
        self.assertEqual(self._facet(facets, "types", "series")["count"], 1)
        self.assertEqual(
            self._facet(facets, "types", "complete_season")["count"], 1)

    def test_facet_count_is_what_the_filter_returns(self):
        facets = viewer.api_v1_get_facets()
        for entry in facets["genres"]:
            total = viewer.api_v1_get_posts(genre=entry["key"])["total"]
            self.assertEqual(total, entry["count"],
                             "genre %s" % entry["key"])
        for entry in facets["industries"]:
            total = viewer.api_v1_get_posts(industry=entry["key"])["total"]
            self.assertEqual(total, entry["count"],
                             "industry %s" % entry["key"])
        for entry in facets["languages"]:
            total = viewer.api_v1_get_posts(language=entry["key"])["total"]
            self.assertEqual(total, entry["count"],
                             "language %s" % entry["key"])
        for entry in facets["types"]:
            total = viewer.api_v1_get_posts(
                content_type=entry["key"])["total"]
            self.assertEqual(total, entry["count"],
                             "type %s" % entry["key"])


class GenreFilterTests(Fixture):
    def test_all_ten_categories_filter(self):
        expected = {"action": {self.seed_id, self.part_two_id},
                    "adventure": {self.seed_id, self.interstellar_id},
                    "animation": set(),
                    "comedy": {self.wonka_id},
                    "crime": set(),
                    "drama": {self.interstellar_id, self.squid_id},
                    "horror": set(),
                    "romance": {self.humsafar_id},
                    "sci-fi": {self.seed_id, self.part_two_id,
                               self.interstellar_id},
                    "thriller": {self.squid_id}}
        for key, ids in expected.items():
            resp = viewer.api_v1_get_posts(genre=key, limit=20)
            self.assertEqual({int(i["id"]) for i in resp["results"]}, ids,
                             key)
            self.assertNotIn(self.adult_id,
                             {int(i["id"]) for i in resp["results"]})

    def test_unknown_genre_is_ignored_not_guessed(self):
        resp = viewer.api_v1_get_posts(genre="no-such-genre", limit=20)
        self.assertEqual(resp["total"], 6)


class LanguageFilterTests(Fixture):
    def test_language_filter(self):
        english = viewer.api_v1_get_posts(language="english", limit=20)
        self.assertEqual({int(i["id"]) for i in english["results"]}, {
            self.seed_id, self.part_two_id, self.interstellar_id,
            self.wonka_id})
        urdu = viewer.api_v1_get_posts(language="urdu", limit=20)
        self.assertEqual([int(i["id"]) for i in urdu["results"]],
                         [self.humsafar_id])

    def test_language_like_pattern_is_escaped(self):
        # A `%` in the value must not match every row.
        resp = viewer.api_v1_get_posts(language="%", limit=20)
        self.assertEqual(resp["total"], 0)


class HiddenTests(Fixture):
    def _build_panel(self):
        panel_path = Path(self.tmp.name) / "admin_v2.db"
        conn = sqlite3.connect(panel_path)
        conn.execute(
            "CREATE TABLE content_visibility (id INTEGER PRIMARY KEY, "
            "scope TEXT, scope_id TEXT, is_hidden INTEGER, reason TEXT, "
            "note TEXT, expires_at INTEGER, restored_at INTEGER)")
        conn.execute(
            "INSERT INTO content_visibility VALUES (1, 'work', ?, 1, "
            "'takedown', NULL, NULL, NULL)", (str(self.part_two_id),))
        conn.commit()
        conn.close()
        return panel_path

    def test_hidden_work_is_absent_from_all_three(self):
        panel_path = self._build_panel()
        with mock.patch.dict(os.environ,
                             {"RADD_ADMIN_V2_DB": str(panel_path)}):
            self.assertNotIn(self.part_two_id,
                             self.ids(viewer.api_v1_get_trending(limit=20)))
            self.assertNotIn(
                self.part_two_id,
                self.ids(viewer.api_v1_get_related(self.seed_id, limit=20)))
            facets = viewer.api_v1_get_facets()
            action = [e for e in facets["genres"] if e["key"] == "action"][0]
            self.assertEqual(action["count"], 1)


class HttpTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.public_server = viewer.make_server("127.0.0.1", 0, operator=False)
        threading.Thread(target=cls.public_server.serve_forever,
                         daemon=True).start()
        cls.public_port = cls.public_server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.public_server.shutdown()
        cls.public_server.server_close()

    def get(self, path):
        redact.limiter._buckets.clear()
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.public_port, path))
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_trending_route(self):
        status, data = self.get("/api/v1/trending?limit=20")
        self.assertEqual(status, 200, data)
        self.assertEqual([int(i["id"]) for i in data["results"]], [
            self.part_two_id, self.squid_id, self.seed_id,
            self.wonka_id, self.humsafar_id, self.interstellar_id])
        self.assertEqual(data["total"], 6)

    def test_related_route(self):
        status, data = self.get(
            "/api/v1/related?work_id=%d&limit=20" % self.seed_id)
        self.assertEqual(status, 200, data)
        self.assertEqual([int(i["id"]) for i in data["results"]], [
            self.part_two_id, self.wonka_id,
            self.interstellar_id, self.squid_id])

    def test_related_route_missing_seed_is_empty_not_404(self):
        status, data = self.get("/api/v1/related?work_id=999999")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["results"], [])

    def test_related_route_bad_work_id_is_400(self):
        for path in ("/api/v1/related",
                     "/api/v1/related?work_id=abc",
                     "/api/v1/related?work_id=1.5"):
            status, data = self.get(path)
            self.assertEqual(status, 400, path)
            self.assertEqual(data["error"], "invalid work_id")

    def test_facets_route(self):
        status, data = self.get("/api/v1/facets")
        self.assertEqual(status, 200, data)
        self.assertEqual(set(data), {"genres", "languages",
                                    "industries", "types"})
        genres = {e["key"]: e["count"] for e in data["genres"]}
        self.assertEqual(genres["action"], 2)
        self.assertEqual(genres["sci-fi"], 3)
        self.assertEqual(genres["animation"], 0)


class LadderGatingTests(unittest.TestCase):
    """Audit #1/#32: the ladder Play follows — gated tiers last, audio first.

    `_option_groups` is tested directly with projected link dicts, no DB:
    the 1080p tier is premium, so a free viewer must never start on it.
    """

    def _link(self, stream_id, kind="direct"):
        return {"stream_id": stream_id, "kind": kind, "playable": True,
                "status": "active", "is_resumable": True,
                "is_temporary": False, "file_size_bytes": 2_000_000_000,
                "mime_type": "video/mp4"}

    def _release(self, quality, languages, stream_id):
        return ({"season": "", "episode": "", "quality": quality,
                 "codec": "x264", "size": "1.5GB",
                 "release_title": "Dune %s" % quality,
                 "languages": languages},
                {"season": "", "episode": "", "quality": quality,
                 "codec": "x264", "size": "1.5GB",
                 "release_title": "Dune %s" % quality,
                 "languages": languages,
                 "sources": [self._link(stream_id)]})

    def _groups(self, **kwargs):
        rels, projected = zip(*[
            self._release("1080p", "Telugu", "h1080"),
            self._release("720p", "Hindi", "h720"),
            self._release("480p", "Telugu", "h480"),
        ])
        return viewer._option_groups(list(rels), list(projected), **kwargs)

    def test_free_user_starts_on_720p_not_1080p(self):
        groups = self._groups()
        tiers_out = groups[0]["tiers"]
        self.assertEqual([t["band"] for t in tiers_out],
                         ["720p", "480p", "1080p"])
        self.assertTrue(tiers_out[-1]["gated"])
        self.assertFalse(tiers_out[0]["gated"])
        self.assertEqual(groups[0]["auto"]["band"], "720p")
        self.assertEqual(groups[0]["auto"]["stream_id"], "h720")

    def test_vip_user_starts_on_1080p(self):
        groups = self._groups(vip=True)
        self.assertEqual([t["band"] for t in groups[0]["tiers"]],
                         ["1080p", "720p", "480p"])
        self.assertFalse(any(t["gated"] for t in groups[0]["tiers"]))
        self.assertEqual(groups[0]["auto"]["band"], "1080p")

    def test_preferred_audio_wins_within_free_tiers(self):
        groups = self._groups(audio_languages=("Hindi",))
        tiers_out = groups[0]["tiers"]
        self.assertEqual(groups[0]["auto"]["band"], "720p")
        self.assertTrue(tiers_out[0]["preferred_audio"])
        self.assertFalse(tiers_out[1]["preferred_audio"])

    def test_preferred_audio_wins_for_vip_too(self):
        groups = self._groups(vip=True, audio_languages=("Hindi",))
        self.assertEqual(groups[0]["auto"]["band"], "720p")
        self.assertEqual([t["band"] for t in groups[0]["tiers"]],
                         ["720p", "1080p", "480p"])

    def test_audio_languages_travel_on_the_tier(self):
        groups = self._groups()
        by_band = {t["band"]: t for t in groups[0]["tiers"]}
        self.assertEqual(by_band["720p"]["audio_languages"], ["Hindi"])
        self.assertEqual(by_band["1080p"]["audio_languages"], ["Telugu"])


class DetailWarmTests(Fixture):
    """Audit #1: `?warm=1` reports warm/warming without slowing detail."""

    def test_warm_reports_warming_and_starts_the_resolve(self):
        with (mock.patch.object(viewer, "_preresolve_is_warm",
                                return_value=False),
              mock.patch.object(viewer, "_start_preresolve") as start):
            detail = viewer.api_v1_get_post_detail(self.seed_id, warm=True)
        self.assertEqual(detail["preresolve"]["status"], "warming")
        self.assertEqual(detail["preresolve"]["band"], "720p")
        start.assert_called_once()

    def test_warm_reports_warm_when_the_cache_has_it(self):
        with (mock.patch.object(viewer, "_preresolve_is_warm",
                                return_value=True),
              mock.patch.object(viewer, "_start_preresolve") as start):
            detail = viewer.api_v1_get_post_detail(self.seed_id, warm=True)
        self.assertEqual(detail["preresolve"]["status"], "warm")
        start.assert_not_called()

    def test_no_warm_flag_means_no_preresolve_key(self):
        detail = viewer.api_v1_get_post_detail(self.seed_id)
        self.assertNotIn("preresolve", detail)

    def test_preresolve_thread_calls_the_resolver(self):
        calls = []
        with mock.patch.object(viewer, "_resolve_and_bank",
                               side_effect=calls.append):
            thread = viewer._start_preresolve(4242)
            thread.join(timeout=5)
        self.assertEqual(calls, [4242])

    def test_stream_errors_carry_plain_language(self):
        self.assertEqual(
            viewer._plain_stream_error("no_playable_source")["message"],
            "That copy didn't play. Try another quality.")
        self.assertIn(
            "VIP",
            viewer._plain_stream_error(
                "premium_quality_requires_vip")["message"])


class RailDedupeTests(Fixture):
    """Audit #17: a rail shows each film once, even filed by two sites."""

    def setUp(self):
        super().setUp()
        self.salaar_a_id = self.ingest(
            title="Salaar Cease Fire", year=2023, content_type="movie",
            genres=["Action"], cast=["Prabhas"], industry="Bollywood",
            language="Hindi", n_releases=5, n_sources=3)
        self.salaar_b_id = self.ingest(
            title="Salaar: Part 1 – Ceasefire", year=2023,
            content_type="movie", genres=["Action"], cast=["Prabhas"],
            industry="Bollywood", language="Hindi",
            n_releases=4, n_sources=2)
        # A legacy twin row for Wonka, filed under a per-site key the
        # way the live catalog holds twins: `save_scraped_data` would
        # merge a second "Wonka" 2023 ingest into the first (title+year
        # identity), so the twin is written directly.
        cur = self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year,"
            " content_type, poster_url, genres, cast_names, industry,"
            " country, language, is_18_plus, canonical_key)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("https://othersite.example/movie/wonka/", "wonka-legacy",
             "Wonka (2023)", "Wonka", 2023, "movie",
             "https://cdn/poster.jpg", '["Comedy", "Family"]',
             '["Timothee Chalamet"]', "Hollywood", "India", "English", 0,
             "wonka-2023-legacy"))
        self.wonka_twin_id = cur.lastrowid
        cur = self.conn.execute(
            "INSERT INTO releases (post_id, release_title, quality, codec,"
            " languages) VALUES (?,?,?,?,?)",
            (self.wonka_twin_id, "Wonka 720p part0", "720p", "x264",
             '["English"]'))
        self.conn.execute(
            "INSERT INTO download_sources (release_id, source_url, status)"
            " VALUES (?,?,?)",
            (cur.lastrowid, "https://cdn.example/wonka-twin-0-0.mp4",
             "active"))
        self.conn.commit()

    def _titles(self, resp):
        return [(item.get("clean_title") or item.get("title") or "")
                for item in resp["results"]]

    def test_trending_shows_one_salaar(self):
        resp = viewer.api_v1_get_trending(limit=20)
        salaar = [t for t in self._titles(resp) if "Salaar" in t]
        self.assertEqual(len(salaar), 1)
        wonka = [t for t in self._titles(resp) if t == "Wonka"]
        self.assertEqual(len(wonka), 1)
        # Total still counts rows (9: the six public fixture rows plus
        # the two Salaar filings plus the Wonka twin); the page shows
        # works, so it is two shorter — one Salaar filing and the twin
        # both folded into their work.
        self.assertEqual(resp["total"], 9)
        self.assertEqual(len(resp["results"]), 7)

    def test_related_shows_one_wonka(self):
        resp = viewer.api_v1_get_related(self.seed_id, limit=20)
        wonka = [t for t in self._titles(resp) if t == "Wonka"]
        self.assertEqual(len(wonka), 1)
        self.assertIn(self.wonka_id, self.ids(resp))


if __name__ == "__main__":
    unittest.main()
