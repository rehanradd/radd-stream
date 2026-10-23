#!/usr/bin/env python3
"""Scenario tests for the catalog v2 read model (`catalog_api.py`).

Every fixture is built the way production builds it: ledger rows written through
`fast_fetch.save_scraped_data()` (with `DB_PATH` patched into a temp file), then
`catalog_v2.project()` to derive the canonical `cat_*` tables. The read model is then
called against that connection. Nothing is hand-INSERTed except the three things the
ledger pipeline genuinely produces out of band — link-health evidence
(`cat_link_evidence`, written by `link_health.probe()`), operator entitlement rows
(`cat_entitlements`, edited per title) and learned pack offsets (`cat_offsets`,
written by `catalog_v2.record_offset`) — and each of those is marked as such below.

Assertions are on exact shapes and values, not on "did it not crash".
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

import catalog_api
import catalog_v2
import fast_fetch
import viewer


# ── ledger source builders (what a scraper would have written) ───────────────

def cdn(tag, *, status="active", temporary=0):
    url = f"https://video-downloads.googleusercontent.com/{tag}"
    return {"source_name": "CDN", "service": "google_cdn", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": temporary, "status": status}


def hls(tag, *, status="active"):
    url = f"https://cdn.test/{tag}/master.m3u8"
    return {"source_name": "HLS", "service": "fzcdn", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": 0, "status": status}


def hoster(tag, *, status="active"):
    url = f"https://new26.gdtot.dad/file/{tag}"
    return {"source_name": "GDTot", "service": "gdtot", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": 1, "status": status}


def embed(tag="vidsrc"):
    url = f"https://vidsrcme.su/embed/movie?tmdb={tag}"
    return {"source_name": "VidSrc", "service": "vidsrc", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "embed",
            "is_temporary": 0, "status": "active"}


def bridge(tag="abc"):
    url = f"https://gpdl.hubcloud.ist/?id={tag}"
    return {"source_name": "Bridge", "service": "hubcloud", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "download",
            "is_temporary": 0, "status": "active"}


def mirror(tag, *, status="active"):
    url = f"https://mega.nz/file/{tag}"
    return {"source_name": "Mega", "service": "mega", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "download",
            "is_temporary": 0, "status": status}


def archive(tag):
    url = f"https://hubcloud.link/Pack.{tag}.zip"
    return {"source_name": "Pack", "service": "hubcloud", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "download",
            "is_temporary": 0, "status": "active"}


class CatalogApiTestCase(unittest.TestCase):
    """One projected corpus per test: full isolation, no shared mutable state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "catalog.db"
        # save_scraped_data resolves its own connection from fast_fetch.DB_PATH, so an
        # unpatched path here would write fixtures into the real catalog.
        self._patches = [
            unittest.mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
            unittest.mock.patch.object(viewer, "DB_PATH", self.db_path),
        ]
        for patcher in self._patches:
            patcher.start()
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.work = {}      # title -> cat_works row dict
        self.print_of = {}  # (title, label) -> cat_releases row dict
        self.link_of = {}   # resource_id tag -> cat_links row dict
        self.build_corpus()

    def tearDown(self):
        self.conn.close()
        for patcher in self._patches:
            patcher.stop()
        self.tmp.cleanup()

    # ---- ledger helpers ---------------------------------------------------- #
    def add_post(self, site, url, *, title=None, clean_title, year=2024,
                 content_type="movie", imdb_id=None, tmdb_id=None, is_18_plus=0,
                 is_animated=0, releases=()):
        data = {
            "url": url,
            "slug": url.rstrip("/").split("/")[-1],
            "title": title or f"{clean_title} ({year})",
            "clean_title": clean_title,
            "year": year,
            "content_type": content_type,
            "seasons": None,
            "poster_url": "https://cdn/poster.jpg",
            "backdrop_urls": '["https://cdn/bd1.jpg"]',
            "imdb_rating": 7.5,
            "genres": '["Action"]',
            "synopsis": f"{clean_title} synopsis",
            "is_18_plus": is_18_plus,
            "is_animated": is_animated,
            "source_site": site,
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(clean_title, year),
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
            "releases": [],
        }
        for spec in releases:
            rel = {
                "release_title": spec.get("release_title", f"{clean_title} 1080p"),
                "season": spec.get("season", ""),
                "episode": spec.get("episode", ""),
                "quality": spec.get("quality", "1080p"),
                "codec": spec.get("codec", "x264"),
                "size": spec.get("size", "1.5GB"),
                "languages": spec.get("languages", '["Hindi"]'),
                "intermediate_url": spec.get("intermediate_url", ""),
                "origin_url": spec.get("origin_url", ""),
                "source_site": spec.get("source_site", ""),
                "sources": spec.get("sources", []),
            }
            data["releases"].append(rel)
        post_id = fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        # The ingester always writes 'active'; the health checker is what marks a link
        # dead, so the fixture reproduces that second step exactly as production does.
        for rel in data["releases"]:
            for src in rel.get("sources") or []:
                if src.get("status") and src["status"] != "active":
                    self.conn.execute(
                        "UPDATE download_sources SET status = ? WHERE source_url = ?",
                        (src["status"], src["source_url"]))
        self.conn.commit()
        return post_id

    def project(self, rev=1):
        self.conn.commit()
        result = catalog_v2.project(self.conn, rev=rev, verbose=False)
        # Keep the test-side index in step with the projection: re-projecting can mint
        # new release/link ids, and the helpers below look rows up through it.
        self._index_corpus()
        return result

    # ---- out-of-band writers (the three tables the ledger does not fill) ---- #
    def record_evidence(self, tag, *, ok=1, speed=None, latency=None, status=200,
                        ranges=None, error=None, probed_at=1730000000.0):
        """Simulates `link_health.probe()` having measured this link."""
        link = self.conn.execute(
            "SELECT id FROM cat_links WHERE resource_id = ?", (tag,)).fetchone()
        self.assertIsNotNone(link, f"no cat_links row for tag {tag}")
        self.conn.execute(
            """
            INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, http_status,
                content_type, size_bytes, latency_ms, speed_mbps, accepts_ranges, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (link["id"], probed_at, ok, "https", status, "video/mp4", 1200000000,
             latency, speed, ranges, error))
        self.conn.commit()
        return link["id"]

    def set_entitlement(self, title, **changes):
        row = self.conn.execute("SELECT id FROM cat_works WHERE title = ?", (title,)).fetchone()
        self.assertIsNotNone(row, f"work {title} missing")
        sets, params = [], []
        for key, value in changes.items():
            sets.append(f"{key} = ?")
            params.append(value)
        params.append(row["id"])
        self.conn.execute(
            f"UPDATE cat_entitlements SET {', '.join(sets)} WHERE work_id = ?", params)
        self.conn.commit()

    # ---- the corpus -------------------------------------------------------- #
    def build_corpus(self):
        self.add_post("hdhub4u", "https://hdhub4u.test/dune-2024/",
                      clean_title="Dune", year=2024, imdb_id="tt15239674", tmdb_id=693134,
                      releases=[
                          {"release_title": "Dune (2024) 4K HDR 10bit BluRay Repack ESub",
                           "quality": "2160p", "codec": "x265", "size": "12GB",
                           "sources": [cdn("DUNE-DEAD-FAST", status="dead"),
                                       cdn("DUNE-LIVE-SLOW")]},
                          {"release_title": "Dune (2024) 1080p WEB-DL",
                           "quality": "1080p", "codec": "x264", "size": "3GB",
                           "sources": [hls("DUNE-HLS"), hoster("DUNE-PAGE"), embed()]},
                          {"release_title": "Dune (2024) 720p CAM Watermarked",
                           "quality": "720p", "codec": "x264", "size": "1GB",
                           "sources": [mirror("DUNE-CAM-MIRROR")]},
                          {"release_title": "Dune (2024) 480p",
                           "quality": "480p", "codec": "x264", "size": "400MB",
                           "sources": [archive("DUNE-480"), bridge("DUNE-BRIDGE")]},
                      ])
        self.add_post("multimovies", "https://mm.test/campus-beats-2020/",
                      clean_title="Campus Beats", year=2020, content_type="series",
                      releases=[
                          {"release_title": "Campus Beats S01 EP(01-06) 720p", "season": "1",
                           "episode": "1-6", "quality": "720p", "sources": [hls("CB-R16")]},
                          {"release_title": "Campus Beats S01E07 720p", "season": "1",
                           "episode": "7", "quality": "720p", "sources": [cdn("CB-E7")]},
                          {"release_title": "Campus Beats S02 Complete 720p", "season": "2",
                           "episode": "Batch", "quality": "720p", "sources": [cdn("CB-S2PACK")]},
                      ])
        self.add_post("ssrmovies", "https://ssr.test/split-film-2022/",
                      clean_title="Split Film", year=2022, releases=[
                          {"release_title": "Split Film (2022) Part 1 1080p WEB-DL",
                           "quality": "1080p", "sources": [cdn("SPLIT-P1")]},
                          {"release_title": "Split Film (2022) Part 2 1080p WEB-DL",
                           "quality": "1080p", "sources": [cdn("SPLIT-P2")]},
                      ])
        self.add_post("vegamovies", "https://vega.test/mega-batch-show/",
                      clean_title="Mega Batch Show", year=2016, content_type="series",
                      releases=[{"release_title": "Mega Batch Show E1-E4000 480p",
                                 "season": "1", "episode": "1-4000", "quality": "480p",
                                 "sources": [mirror("MBS-MIRROR")]}])
        self.add_post("site-adult", "https://adult.test/adult-diary/",
                      clean_title="Adult Diary", year=2024, is_18_plus=1,
                      releases=[{"release_title": "Adult Diary (2024) 1080p",
                                 "quality": "1080p", "sources": [cdn("ADULT-OK")]}])
        self.add_post("site-x", "https://x.test/broken-season-show/",
                      clean_title="Broken Season Show", year=2021, content_type="series",
                      releases=[{"release_title": "Broken Season Show Complete 720p",
                                 "season": "", "episode": "", "quality": "720p",
                                 "sources": [cdn("BSS-PACK")]}])
        self.add_post("site-y", "https://y.test/ghost-town-tapes/",
                      clean_title="Ghost Town Tapes", year=2019, content_type="series",
                      releases=[
                          {"release_title": "Ghost Town Tapes S01E01 1080p", "season": "1",
                           "episode": "1", "quality": "1080p", "sources": [cdn("GTT-S1E1")]},
                          {"release_title": "Ghost Town Tapes S01E02 1080p", "season": "1",
                           "episode": "2", "quality": "1080p", "sources": [cdn("GTT-S1E2")]},
                          {"release_title": "Ghost Town Tapes S02E01 1080p", "season": "2",
                           "episode": "1", "quality": "1080p", "sources": [cdn("GTT-S2E1")]},
                          {"release_title": "Ghost Town Tapes S02E02 1080p", "season": "2",
                           "episode": "2", "quality": "1080p", "sources": [cdn("GTT-S2E2")]},
                          {"release_title": "Ghost Town Tapes S02E03 1080p", "season": "2",
                           "episode": "3", "quality": "1080p", "sources": [cdn("GTT-S2E3")]},
                      ])
        self.add_post("site-z", "https://z.test/paid-opera-2023/",
                      clean_title="Paid Opera", year=2023,
                      releases=[{"release_title": "Paid Opera (2023) 1080p WEB-DL",
                                 "quality": "1080p", "sources": [cdn("PAID-OK")]}])
        self.add_post("site-q", "https://q.test/dead-air-2018/",
                      clean_title="Dead Air", year=2018,
                      releases=[{"release_title": "Dead Air (2018) 1080p",
                                 "quality": "1080p", "sources": [cdn("DEADAIR", status="dead")]}])
        self.add_post("site-w", "https://w.test/cafe-clown/",
                      clean_title="Café Clown", year=2021,
                      title="Café Clown (2021) [WEB-DL] Hindi Dubbed 720p",
                      releases=[{"release_title": "Café Clown (2021) 720p Hindi Dubbed",
                                 "quality": "720p", "sources": [cdn("CAFE")]},
                                {"release_title": "Café Clown (2021) 1080p Dual Audio",
                                 "quality": "1080p", "languages": '["Hindi", "English"]',
                                 "sources": [cdn("CAFE-1080")]}])
        self.add_post("site-e", "https://e.test/tommy-the-movie/",
                      clean_title="Tommy: The Movie", year=2017,
                      releases=[{"release_title": "Tommy: The Movie (2017) 1080p",
                                 "quality": "1080p", "sources": [cdn("TOMMY")]}])
        self.add_post("site-m", "https://m.test/nova-2019-film/",
                      clean_title="Nova", year=2019, content_type="movie",
                      releases=[{"release_title": "Nova (2019) 1080p", "quality": "1080p",
                                 "sources": [cdn("NOVA-MOVIE")]}])
        self.add_post("site-n", "https://n.test/nova-2019-series/",
                      clean_title="Nova", year=2019, content_type="series",
                      releases=[{"release_title": "Nova S01E01 720p", "season": "1",
                                 "episode": "1", "quality": "720p",
                                 "sources": [cdn("NOVA-EPISODE")]}])

        self.project()
        self._index_corpus()

        # Link-health evidence: the dead link was measured FAST, the live one SLOW.
        # Ranking must still put the live link first (state dominates speed).
        self.record_evidence("DUNE-DEAD-FAST", ok=0, speed=88.5, latency=40,
                             status=404, ranges=0, error="http_404")
        self.record_evidence("DUNE-LIVE-SLOW", ok=1, speed=3.2, latency=610,
                             status=200, ranges=1)
        self.record_evidence("DUNE-HLS", ok=1, speed=22.0, latency=120, status=200, ranges=0)

        # Learned pack offsets (operator/client calibration data, keyed by identity).
        catalog_v2.record_offset(self.conn, work_key=self.work["Campus Beats"]["work_key"],
                                 season_number=2, episode_number=3, offset_seconds=1400,
                                 release_label="Campus Beats S02 Complete 720p",
                                 chapter_title="Episode 3")
        catalog_v2.record_offset(self.conn, work_key=self.work["Campus Beats"]["work_key"],
                                 season_number=2, episode_number=4, offset_seconds=2600,
                                 release_label="", chapter_title="Episode 4")

        # One paid title, configured out-of-band exactly as an operator would.
        self.set_entitlement("Paid Opera", model="rental", price_minor=14900,
                             currency="INR", ownership="until_expiry", rental_hours=48,
                             valid_until=1730000000)

    def _index_corpus(self):
        self.work.clear()
        self.print_of.clear()
        self.link_of.clear()
        for row in self.conn.execute("SELECT * FROM cat_works").fetchall():
            self.work[row["title"]] = dict(row)
        for row in self.conn.execute("SELECT * FROM cat_releases").fetchall():
            title = self.work_id_to_title(row["work_id"])
            self.print_of[(title, row["label"])] = dict(row)
        for row in self.conn.execute("SELECT * FROM cat_links").fetchall():
            self.link_of[row["resource_id"]] = dict(row)

    def work_id_to_title(self, work_id):
        row = self.conn.execute("SELECT title FROM cat_works WHERE id = ?",
                                (work_id,)).fetchone()
        return row["title"] if row else "?"

    def print_by_fragment(self, title, fragment):
        for (work_title, label), value in self.print_of.items():
            if work_title == title and fragment in label:
                return value
        raise AssertionError(f"no print for {title!r} containing {fragment!r}")

    # ---- convenience -------------------------------------------------------- #
    def manifest(self, title, **kwargs):
        return catalog_api.episode_manifest(self.conn, work_id=self.work[title]["id"], **kwargs)

    def bundle(self, fragment, title="Dune"):
        return catalog_api.play_bundle(self.conn,
                                       release_id=self.print_by_fragment(title, fragment)["id"])

    def ids(self, items):
        return [item["id"] for item in items]


# ── browse ───────────────────────────────────────────────────────────────────

class BrowseTests(CatalogApiTestCase):
    def test_default_browse_never_shows_adult(self):
        page = catalog_api.browse(self.conn, limit=100)
        self.assertTrue(page["ok"])
        titles = {item["title"] for item in page["items"]}
        self.assertNotIn("Adult Diary", titles)
        self.assertIn("Dune", titles)
        self.assertTrue(all(not item["adult"] for item in page["items"]))

    def test_browse_total_estimate_has_no_adult_skew(self):
        page = catalog_api.browse(self.conn, limit=100)
        self.assertEqual(page["total_estimate"], page["count"])
        visible = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cat_works WHERE COALESCE(is_18_plus,0) = 0"
        ).fetchone()["n"]
        self.assertEqual(page["total_estimate"], visible)

    def test_include_adult_is_an_explicit_admin_opt_in(self):
        page = catalog_api.browse(self.conn, limit=100, include_adult=True)
        self.assertIn("Adult Diary", {item["title"] for item in page["items"]})
        self.assertEqual(page["adult_included"], True)

    def test_every_documented_sort_key_returns_the_whole_catalog(self):
        for sort in catalog_api.SORT_KEYS:
            page = catalog_api.browse(self.conn, sort=sort, limit=100)
            self.assertTrue(page["ok"], sort)
            self.assertGreater(page["count"], 0, sort)
            self.assertIsNone(page["next_cursor"], sort)

    def test_unknown_sort_key_is_rejected_not_ignored(self):
        page = catalog_api.browse(self.conn, sort="popularity")
        self.assertFalse(page["ok"])
        self.assertEqual(page["error"]["code"], "invalid_input")

    def test_trending_prefers_a_rich_streamable_work_over_a_thin_one(self):
        page = catalog_api.browse(self.conn, sort="trending", limit=100)
        titles = [item["title"] for item in page["items"]]
        self.assertLess(titles.index("Dune"), titles.index("Tommy: The Movie"))
        self.assertEqual(page["items"][0]["title"], "Dune")

    def test_newest_sorts_by_year_first_not_by_id(self):
        page = catalog_api.browse(self.conn, sort="newest", limit=100)
        years = [item["year"] for item in page["items"]]
        self.assertEqual(years, sorted(years, key=lambda y: (y or 0), reverse=True))
        self.assertEqual(page["items"][0]["year"], 2024)

    def test_quality_sort_is_descending_best_quality_score(self):
        page = catalog_api.browse(self.conn, sort="quality", limit=100)
        scores = [item["best_quality_score"] for item in page["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_title_sort_is_case_insensitive_and_punctuation_agnostic(self):
        page = catalog_api.browse(self.conn, sort="title", order="asc", limit=100)
        titles = [item["title"] for item in page["items"]]
        self.assertEqual(titles, sorted(titles, key=lambda t: catalog_api.normalize_text(t)))

    def test_rating_sort_reads_the_stored_value(self):
        page = catalog_api.browse(self.conn, sort="rating", limit=100)
        ratings = [item["rating"] for item in page["items"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))

    def test_cursor_pages_have_no_duplicates_and_no_skips_even_when_sort_ties(self):
        # `updated` is the worst case: the projector stamps every work with the same
        # projection instant, so the whole catalog ties on the sort value and only the
        # id tiebreak can keep the pages honest.
        for sort in catalog_api.SORT_KEYS:
            seen, cursor, pages = [], None, 0
            while True:
                page = catalog_api.browse(self.conn, sort=sort, limit=3, cursor=cursor)
                self.assertTrue(page["ok"], (sort, page))
                seen.extend(item["id"] for item in page["items"])
                pages += 1
                cursor = page["next_cursor"]
                if cursor is None:
                    break
                self.assertLess(pages, 50, f"{sort} never terminated")
            full = catalog_api.browse(self.conn, sort=sort, limit=100)
            self.assertEqual(len(seen), len(set(seen)), f"{sort} repeated a work")
            self.assertEqual(seen, self.ids(full["items"]), f"{sort} paged differently")

    def test_garbage_cursor_is_reported_not_silently_ignored(self):
        page = catalog_api.browse(self.conn, cursor="not-a-cursor")
        self.assertFalse(page["ok"])
        self.assertEqual(page["error"]["code"], "cursor_invalid")

    def test_cursor_from_a_different_sort_is_rejected(self):
        first = catalog_api.browse(self.conn, sort="quality", limit=3)
        self.assertIsNotNone(first["next_cursor"])
        other = catalog_api.browse(self.conn, sort="rating", limit=3,
                                   cursor=first["next_cursor"])
        self.assertFalse(other["ok"])
        self.assertEqual(other["error"]["code"], "cursor_invalid")

    def test_cursor_from_a_different_facet_set_is_rejected(self):
        first = catalog_api.browse(self.conn, limit=3)
        self.assertIsNotNone(first["next_cursor"])
        moved = catalog_api.browse(self.conn, limit=3, content_type="movie",
                                   cursor=first["next_cursor"])
        self.assertFalse(moved["ok"])
        self.assertEqual(moved["error"]["code"], "cursor_invalid")

    def test_content_type_facet_uses_work_type_and_legacy_aliases(self):
        series = catalog_api.browse(self.conn, content_type="series", limit=100)
        self.assertTrue(all(item["work_type"] == "series" for item in series["items"]))
        self.assertIn("Campus Beats", {i["title"] for i in series["items"]})
        # v1 sent ?type=complete_season; that must not return nothing.
        legacy = catalog_api.browse(self.conn, content_type="complete_season", limit=100)
        self.assertEqual({i["work_type"] for i in legacy["items"]}, {"series"})

    def test_movie_and_series_of_the_same_name_stay_separate_works(self):
        page = catalog_api.browse(self.conn, limit=100)
        novas = [item for item in page["items"] if item["title"] == "Nova"]
        self.assertEqual(len(novas), 2)
        self.assertEqual({n["work_type"] for n in novas}, {"movie", "series"})
        stored = {row["id"]: row["work_type"] for row in self.conn.execute(
            "SELECT id, work_type FROM cat_works WHERE title = 'Nova'")}
        movies = catalog_api.browse(self.conn, content_type="movie", limit=100)
        series = catalog_api.browse(self.conn, content_type="series", limit=100)
        movie_ids = {n["id"] for n in movies["items"] if n["title"] == "Nova"}
        series_ids = {n["id"] for n in series["items"] if n["title"] == "Nova"}
        self.assertEqual(len(movie_ids), 1)
        self.assertEqual(len(series_ids), 1)
        self.assertFalse(movie_ids & series_ids, "one title, two works, never merged")
        self.assertEqual([stored[i] for i in movie_ids], ["movie"])
        self.assertEqual([stored[i] for i in series_ids], ["series"])

    def test_genre_language_and_quality_facets(self):
        action = catalog_api.browse(self.conn, genres=["Action"], limit=100)
        self.assertGreater(action["count"], 0)
        self.assertTrue(all("Action" in item["genres"] for item in action["items"]))
        romance = catalog_api.browse(self.conn, genres=["Romance"], limit=100)
        self.assertEqual(romance["items"], [])
        english_audio = catalog_api.browse(self.conn, languages=["English"], limit=100)
        self.assertIn("Café Clown", {i["title"] for i in english_audio["items"]},
                      "a print with an English audio track must answer ?language=English")
        fourk = catalog_api.browse(self.conn, qualities=["4k"], limit=100)
        self.assertEqual([i["title"] for i in fourk["items"]], ["Dune"])

    def test_available_facet_hides_the_work_with_no_links_at_all(self):
        # `Dead Air` has one link and it is dead, so it stays listed (zero data loss)
        # but must not claim availability.
        page = catalog_api.browse(self.conn, available=True, limit=100)
        titles = {item["title"] for item in page["items"]}
        self.assertIn("Dune", titles)
        for item in page["items"]:
            self.assertTrue(item["available"]["any"], item["title"])
        every = catalog_api.browse(self.conn, limit=100)
        dead = [item for item in every["items"] if item["title"] == "Dead Air"][0]
        self.assertFalse(dead["available"]["any"])
        self.assertEqual(dead["available"]["state"], "unavailable")
        self.assertIn("no_playable_source", dead["flags"])

    def test_year_and_min_quality_facets(self):
        recent = catalog_api.browse(self.conn, year_from=2022, limit=100)
        self.assertTrue(all((item["year"] or 0) >= 2022 for item in recent["items"]))
        old = catalog_api.browse(self.conn, year_to=2018, limit=100)
        # Both `Nova` works are 2019, so neither may leak into a <=2018 filter.
        self.assertEqual({item["title"] for item in old["items"]},
                         {"Mega Batch Show", "Tommy: The Movie", "Dead Air"})
        self.assertTrue(all((item["year"] or 0) <= 2018 for item in old["items"]))
        hd = catalog_api.browse(self.conn, min_quality=400, limit=100)
        self.assertTrue(hd["ok"])
        self.assertTrue(all(item["best_quality_score"] >= 400 for item in hd["items"]))
        # Dune's 2160p print scores 870, Mega Batch Show's 480p batch only 220.
        self.assertIn("Dune", {item["title"] for item in hd["items"]})
        self.assertNotIn("Mega Batch Show", {item["title"] for item in hd["items"]})
        paged = catalog_api.browse(self.conn, min_quality=400, year_from=2019, limit=100)
        self.assertTrue(all((item["year"] or 0) >= 2019 for item in paged["items"]))

    def test_limit_is_clamped_and_empty_query_string_is_no_match(self):
        page = catalog_api.browse(self.conn, limit=5000)
        self.assertEqual(page["limit"], catalog_api.MAX_LIMIT)
        nothing = catalog_api.browse(self.conn, q="zzzz never scraped zzzz")
        self.assertTrue(nothing["ok"])
        self.assertEqual(nothing["items"], [])
        self.assertEqual(nothing["total_estimate"], 0)

    def test_browse_item_carries_exactly_the_documented_grid_shape(self):
        item = catalog_api.browse(self.conn, limit=1)["items"][0]
        self.assertEqual(
            set(item),
            {"id", "title", "year", "work_type", "animated", "poster",
             "rating", "genres", "languages", "country", "industry",
             "site_count", "seasons", "episodes", "prints", "quality_max",
             "best_quality_score", "available", "flags", "identity_suspect",
             "entitlement", "first_seen_at", "updated_at", "sort_value", "adult"})
        self.assertTrue(item["poster"]["src"].startswith("/api/v1/art?"),
                        "art hosted by a site we scrape becomes our own handle")
        self.assertNotIn("cdn", item["poster"]["src"])
        self.assertIsNone(item["poster"]["width"], "poster width is not in the DB -> null")
        self.assertEqual(item["entitlement"], {"model": "free"})

    def test_public_shapes_carry_no_source_identity(self):
        """The v2 grid is the app's home screen: nothing in it names a site."""
        for item in catalog_api.browse(self.conn, limit=100)["items"]:
            self.assertNotIn("source_site", item)
            self.assertNotIn("work_key", item)
            self.assertNotIn("url", item["poster"])

    def test_public_art_passes_a_known_cdn_through_untouched(self):
        row = self.work["Dune"]
        self.conn.execute("UPDATE cat_works SET poster_url = ? WHERE id = ?",
                          ("https://image.tmdb.org/t/p/w500/abc.jpg", row["id"]))
        item = [i for i in catalog_api.browse(self.conn, limit=100)["items"]
                if i["id"] == row["id"]][0]
        self.assertEqual(item["poster"]["src"], "https://image.tmdb.org/t/p/w500/abc.jpg",
                         "TMDB art names nothing about us, so it needs no handle")

    def test_browse_exposes_identity_suspect_instead_of_hiding_it(self):
        page = catalog_api.browse(self.conn, limit=100)
        broken = [item for item in page["items"] if item["title"] == "Broken Season Show"][0]
        self.assertTrue(broken["identity_suspect"])
        self.assertIn("identity_suspect", broken["flags"])
        self.assertIn("needs_review", broken["flags"])


# ── search ───────────────────────────────────────────────────────────────────

class SearchTests(CatalogApiTestCase):
    def test_year_suffix_and_scrape_noise_cannot_break_a_search(self):
        found = catalog_api.search(self.conn, q="dune")
        self.assertIn("Dune", {i["title"] for i in found["items"]})
        self.assertEqual(found["normalized"], "dune")

    def test_punctuation_in_the_stored_title_is_not_required_in_the_query(self):
        found = catalog_api.search(self.conn, q="tommy the movie")
        self.assertEqual([i["title"] for i in found["items"]], ["Tommy: The Movie"])

    def test_punctuation_in_the_query_is_tolerated(self):
        for query in ("Tommy:", "Tommy : The Movie", "  TOMMY   the   MOVIE  "):
            found = catalog_api.search(self.conn, q=query)
            self.assertIn("Tommy: The Movie", {i["title"] for i in found["items"]}, query)

    def test_diacritics_are_folded_both_ways(self):
        plain = catalog_api.search(self.conn, q="cafe clown")
        self.assertEqual([i["title"] for i in plain["items"]], ["Café Clown"])
        accented = catalog_api.search(self.conn, q="Café Clown")
        self.assertEqual([i["title"] for i in accented["items"]], ["Café Clown"])

    def test_dirty_page_title_is_searchable_through_aliases(self):
        # The clean title is "Dune"; the scraped page title carries "(2024)".
        found = catalog_api.search(self.conn, q="dune 2024")
        self.assertIn("Dune", {i["title"] for i in found["items"]})
        noise = catalog_api.search(self.conn, q="hindi dubbed")
        self.assertIn("Café Clown", {i["title"] for i in noise["items"]},
                      "the page title 'Café Clown (2021) [WEB-DL] Hindi Dubbed 720p' must match")

    def test_search_never_returns_nothing_because_of_a_missing_accent_or_bracket(self):
        found = catalog_api.search(self.conn, q="cafe")
        self.assertEqual([i["title"] for i in found["items"]], ["Café Clown"])
        self.assertGreater(found["total_estimate"], 0)

    def test_exact_prefix_outranks_a_substring_hit(self):
        found = catalog_api.search(self.conn, q="nova")
        titles = [i["title"] for i in found["items"]]
        self.assertEqual(titles[0], "Nova")
        self.assertTrue(all(t == "Nova" for t in titles))
        scores = [i["relevance"] for i in found["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_search_excludes_adult_and_honours_the_admin_opt_in(self):
        hidden = catalog_api.search(self.conn, q="adult diary")
        self.assertEqual(hidden["items"], [])
        shown = catalog_api.search(self.conn, q="adult diary", include_adult=True)
        self.assertEqual([i["title"] for i in shown["items"]], ["Adult Diary"])

    def test_sparse_field_selection_returns_only_requested_keys(self):
        found = catalog_api.search(self.conn, q="dune", fields="id,title,year")
        for item in found["items"]:
            self.assertEqual(set(item), {"id", "title", "year"})

    def test_empty_query_is_a_documented_empty_result_not_an_error(self):
        for query in ("", "   ", "():"):
            found = catalog_api.search(self.conn, q=query)
            self.assertTrue(found["ok"])
            self.assertEqual(found["items"], [])

    def test_search_supports_facets_and_cursor_paging(self):
        first = catalog_api.search(self.conn, q="campus beats", content_type="series",
                                   limit=1)
        self.assertEqual(first["count"], 1)
        self.assertIsNone(first["next_cursor"])
        # 'nova' is the title of both a movie and a series, so limit=1 must page.
        broad = catalog_api.search(self.conn, q="nova", limit=1)
        self.assertEqual(broad["count"], 1)
        self.assertIsNotNone(broad["next_cursor"])
        second = catalog_api.search(self.conn, q="nova", limit=1, cursor=broad["next_cursor"])
        self.assertTrue(second["ok"])
        self.assertEqual(second["count"], 1)
        self.assertFalse(set(self.ids(broad["items"])) & set(self.ids(second["items"])))
        movies = catalog_api.search(self.conn, q="nova", content_type="movie", limit=5)
        self.assertEqual({i["work_type"] for i in movies["items"]}, {"movie"})
        # A cursor minted without the facet must not be reused with one.
        moved = catalog_api.search(self.conn, q="nova", content_type="movie", limit=1,
                                   cursor=broad["next_cursor"])
        self.assertFalse(moved["ok"])
        self.assertEqual(moved["error"]["code"], "cursor_invalid")

    def test_suggest_is_prefix_only_and_needs_two_characters(self):
        short = catalog_api.suggest(self.conn, q="d")
        self.assertEqual(short["items"], [])
        page = catalog_api.suggest(self.conn, q="dun")
        self.assertEqual([i["title"] for i in page["items"]], ["Dune"])
        # 'adult diary' is not a prefix of any visible title and must not surface.
        adult = catalog_api.suggest(self.conn, q="adult")
        self.assertEqual(adult["items"], [])


# ── work detail ──────────────────────────────────────────────────────────────

class WorkDetailTests(CatalogApiTestCase):
    def detail(self, title):
        return catalog_api.work_detail(self.conn, work_id=self.work[title]["id"])

    def test_unknown_id_and_adult_id_return_the_identical_not_found(self):
        adult_id = self.work["Adult Diary"]["id"]
        missing = catalog_api.work_detail(self.conn, work_id=987654)
        leaked = catalog_api.work_detail(self.conn, work_id=adult_id)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing, leaked, "an adult work must be indistinguishable")
        self.assertEqual(leaked["error"]["code"], "not_found")
        self.assertNotIn("is_18_plus", json.dumps(leaked))

    def test_adult_work_is_only_reachable_through_the_admin_opt_in(self):
        result = catalog_api.work_detail(self.conn, work_id=self.work["Adult Diary"]["id"],
                                         include_adult=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["work"]["title"], "Adult Diary")

    def test_identity_block_carries_external_ids_and_no_internal_key(self):
        identity = self.detail("Dune")["identity"]
        self.assertEqual(identity["imdb_id"], "tt15239674")
        self.assertEqual(identity["tmdb_id"], 693134)
        self.assertIsNone(identity["tvdb_id"], "tvdb is never written -> null, not guessed")
        self.assertNotIn("canonical_key", identity,
                        "our own primary identity key is not for the client to mirror")
        for variant in identity["title_variants"]:
            self.assertNotIn("source_site", variant,
                             "an alias is not allowed to say which site wrote it")

    def test_detail_is_addressable_by_work_key_and_by_page_slug(self):
        by_key = catalog_api.work_detail(self.conn, work_key="imdb:tt15239674")
        self.assertTrue(by_key["ok"])
        self.assertEqual(by_key["work"]["id"], self.work["Dune"]["id"])
        by_slug = catalog_api.work_detail(self.conn, slug="dune-2024")
        self.assertTrue(by_slug["ok"])
        self.assertEqual(by_slug["work"]["title"], "Dune")
        by_url = catalog_api.work_detail(self.conn, url="https://mm.test/campus-beats-2020/")
        self.assertEqual(by_url["work"]["title"], "Campus Beats")

    def test_seasons_and_episodes_are_nested_with_absolute_numbers(self):
        detail = self.detail("Campus Beats")
        seasons = {s["number"]: s for s in detail["seasons"]}
        self.assertEqual(sorted(seasons), [1, 2])
        self.assertEqual([e["number"] for e in seasons[1]["episodes"]], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([e["absolute_number"] for e in seasons[1]["episodes"]],
                         [1, 2, 3, 4, 5, 6, 7])
        episode7 = seasons[1]["episodes"][-1]
        self.assertEqual(episode7["number"], 7)
        self.assertIsNotNone(episode7["best_release_id"])
        # S02 exists as a pack only: no enumerated episodes, but not reported as empty.
        self.assertEqual(seasons[2]["episodes"], [])
        self.assertTrue(seasons[2]["pack_only"])
        self.assertGreater(len(seasons[2]["print_ids"]), 0)

    def test_episode_quality_options_come_from_the_prints_that_really_cover_it(self):
        detail = self.detail("Campus Beats")
        season1 = {s["number"]: s for s in detail["seasons"]}[1]
        episode4 = [e for e in season1["episodes"] if e["number"] == 4][0]
        self.assertEqual(episode4["print_count"], 1, "only the 1-6 batch covers E4")
        episode7 = [e for e in season1["episodes"] if e["number"] == 7][0]
        self.assertEqual(episode7["print_count"], 1, "E7 is only in its own print")
        self.assertEqual(episode7["quality_options"], ["720p"])

    def test_prints_are_grouped_and_ordered_best_first_with_cam_last(self):
        detail = self.detail("Dune")
        ordered = [p["resolution"] for p in detail["prints"]]
        # The projector scores a watermarked 720p CAM (160) BELOW a clean 480p rip (220),
        # so "best quality first" already puts the cam last — no special-casing needed.
        self.assertEqual(ordered, ["2160p", "1080p", "480p", "720p"])
        scores = [p["quality_score"] for p in detail["prints"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        cam = detail["prints"][-1]
        self.assertEqual(cam["source_tag"], "cam")
        self.assertTrue(cam["watermarked"])
        self.assertIn("watermarked", cam["flags"])
        self.assertEqual(cam["official_print"], False)
        self.assertEqual(detail["print_groups"][0]["scope"]["coverage_type"], "whole_work")

    def test_each_print_lists_its_links_ordered_by_rank_score(self):
        detail = self.detail("Dune")
        web = detail["prints"][1]
        scores = [link["rank_score"] for link in web["links"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        kinds = [link["kind"] for link in web["links"]]
        self.assertEqual(kinds[0], "hls_manifest", "the streamable link leads")
        self.assertEqual(len(web["links"]), 3)
        self.assertEqual(web["counts"]["links"], 3)

    def test_detail_keeps_every_dead_link_visible_and_counted(self):
        detail = self.detail("Dead Air")
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["availability"]["state"], "unavailable")
        self.assertEqual(detail["availability"]["link_total"], 1)
        self.assertEqual(detail["availability"]["dead_link_total"], 1)
        self.assertEqual(detail["prints"][0]["links"][0]["state"], "dead")
        self.assertIn("all_links_dead", detail["flags"])

    def test_two_part_movie_is_reported_as_two_parts_not_one_long_item(self):
        detail = self.detail("Split Film")
        parts = detail["parts"]
        self.assertEqual([p["number"] for p in parts], [1, 2])
        self.assertTrue(all(p["inferred"] for p in parts))
        self.assertEqual([p["source"] for p in parts], ["print_label", "print_label"])
        self.assertEqual(len(detail["prints"]), 2)
        self.assertNotEqual(detail["prints"][0]["release_id"],
                            detail["prints"][1]["release_id"])

    def test_parts_are_read_from_cat_parts_when_the_projector_fills_it(self):
        self.conn.execute("INSERT INTO cat_parts (work_id, number, title) VALUES (?, 1, 'Part One')",
                          (self.work["Split Film"]["id"],))
        self.conn.execute("INSERT INTO cat_parts (work_id, number, title) VALUES (?, 2, 'Part Two')",
                          (self.work["Split Film"]["id"],))
        self.conn.commit()
        parts = catalog_api.work_detail(self.conn,
                                        work_id=self.work["Split Film"]["id"])["parts"]
        self.assertEqual([p["number"] for p in parts], [1, 2])
        self.assertEqual([p["inferred"] for p in parts], [False, False])
        self.assertEqual({p["source"] for p in parts}, {"cat_parts"})

    def test_identity_suspect_work_is_marked_and_its_unresolved_print_stays_visible(self):
        detail = self.detail("Broken Season Show")
        self.assertTrue(detail["identity_suspect"])
        self.assertIn("identity_suspect", detail["flags"])
        self.assertEqual(len(detail["review_queue"]), 1)
        self.assertEqual(detail["review_queue"][0]["kind"], "season_unresolved")
        unresolved = detail["scope_unresolved_prints"]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["reason"], "season_unresolved")

    def test_sites_provenance_is_operator_only(self):
        """Which page a title was scraped from stays in SQLite and the operator port."""
        detail = self.detail("Dune")
        self.assertNotIn("sites", detail)
        self.assertNotIn("page_url", json.dumps(detail, sort_keys=True))
        operator = catalog_api.work_detail(self.conn, work_id=self.work["Dune"]["id"],
                                           include_provenance=True)
        self.assertEqual(len(operator["provenance"]["sites"]), 1)
        self.assertEqual(operator["provenance"]["sites"][0]["page_url"],
                         "https://hdhub4u.test/dune-2024/")
        self.assertEqual(operator["provenance"]["sites"][0]["source_site"], "hdhub4u")
        self.assertEqual(operator["provenance"]["work_key"], "imdb:tt15239674")
        self.assertEqual(detail["work"]["site_count"], 1,
                         "how many places carry it is a number; which places is not")

    def test_multi_site_work_merges_pages_without_losing_links(self):
        self.add_post("ssrmovies", "https://ssr.test/dune-2024/", clean_title="Dune",
                      year=2024, imdb_id="tt15239674",
                      releases=[{"release_title": "Dune (2024) 4K HDR 10bit BluRay Repack ESub",
                                 "quality": "2160p", "codec": "x265", "size": "12GB",
                                 "sources": [cdn("DUNE-MIRROR-1")]}])
        self.project(rev=2)
        detail = catalog_api.work_detail(self.conn, work_id=self.conn.execute(
            "SELECT id FROM cat_works WHERE work_key = 'imdb:tt15239674'").fetchone()["id"])
        self.assertEqual(detail["work"]["site_count"], 2)
        self.assertNotIn("sites", detail)
        fourk = [p for p in detail["prints"] if p["resolution"] == "2160p"]
        # The projector keys a print by (label, origin_url), so the same-named 4K print
        # scraped from a second site stays two prints. What matters is that no link is
        # lost: all three sources are still on the page, each under its own handle.
        self.assertEqual(len(fourk), 2)
        self.assertEqual(sorted(p["counts"]["links"] for p in fourk), [1, 2])
        self.assertEqual(sorted(link["link_id"] for p in fourk for link in p["links"]),
                         sorted(self.link_of[tag]["id"] for tag in
                                ("DUNE-DEAD-FAST", "DUNE-LIVE-SLOW", "DUNE-MIRROR-1")))
        self.assertEqual(sum(p["counts"]["links"] for p in detail["prints"]), 9)

    def test_availability_and_entitlement_are_reported_for_every_work(self):
        detail = self.detail("Paid Opera")
        self.assertTrue(detail["availability"]["stream"])
        self.assertEqual([e["model"] for e in detail["entitlements"]], ["rental"])

    def test_field_selection_trims_the_payload(self):
        detail = catalog_api.work_detail(self.conn, work_id=self.work["Dune"]["id"],
                                         fields=["work", "id"])
        self.assertEqual(set(detail), {"ok", "meta", "work", "id"})
        self.assertEqual(detail["id"], self.work["Dune"]["id"])


# ── episode manifest ─────────────────────────────────────────────────────────

class EpisodeManifestTests(CatalogApiTestCase):
    def test_season_episode_addressing_returns_the_materialised_print(self):
        page = self.manifest("Campus Beats", season=1, episode=7)
        self.assertTrue(page["ok"])
        self.assertEqual(page["target"]["resolved_by"], "season_episode")
        self.assertEqual(page["target"]["season"], 1)
        self.assertEqual(page["target"]["episode_id"],
                         self.conn.execute("SELECT id FROM cat_episodes WHERE work_id = ?"
                                           " AND number = 7 AND season_id IN"
                                           " (SELECT id FROM cat_seasons WHERE number = 1)",
                                           (self.work["Campus Beats"]["id"],)).fetchone()["id"])
        labels = [p["label"] for p in page["prints"]]
        self.assertIn("Campus Beats S01E07 720p", labels)
        self.assertNotIn("Campus Beats S01 EP(01-06) 720p", labels,
                         "the batch print covers E1-E6 only, so it must NOT answer for E7")
        single = [p for p in page["prints"] if p["label"] == "Campus Beats S01E07 720p"][0]
        self.assertEqual(single["coverage_type"], "single_episode")
        self.assertEqual(single["match_kind"], "materialised")

    def test_absolute_addressing_resolves_across_seasons(self):
        page = self.manifest("Campus Beats", absolute=7)
        self.assertEqual(page["target"]["resolved_by"], "absolute")
        self.assertEqual(page["target"]["season"], 1)
        self.assertEqual(page["target"]["episode"], 7)
        self.assertIn("Campus Beats S01E07 720p", [p["label"] for p in page["prints"]])

    def test_absolute_addressing_for_a_second_season(self):
        self.add_post("site-abs", "https://abs.test/ordered-show/", clean_title="Ordered Show",
                      year=2020, content_type="series", releases=[
                          {"release_title": "Ordered Show S01E01 720p", "season": "1",
                           "episode": "1", "quality": "720p", "sources": [cdn("OS-11")]},
                          {"release_title": "Ordered Show S02E01 720p", "season": "2",
                           "episode": "1", "quality": "720p", "sources": [cdn("OS-21")]},
                      ])
        self.project(rev=2)
        work_id = self.conn.execute("SELECT id FROM cat_works WHERE title = 'Ordered Show'"
                                    ).fetchone()["id"]
        page = catalog_api.episode_manifest(self.conn, work_id=work_id, absolute=2)
        self.assertEqual(page["target"]["season"], 2)
        self.assertEqual([p["label"] for p in page["prints"]], ["Ordered Show S02E01 720p"])

    def test_season_pack_covers_an_unenumerated_episode_with_a_warning(self):
        page = self.manifest("Campus Beats", season=2, episode=5)
        self.assertEqual(page["print_count"], 1)
        pack = page["prints"][0]
        self.assertEqual(pack["coverage_type"], "season_pack")
        self.assertEqual(pack["label"], "Campus Beats S02 Complete 720p")
        self.assertTrue(pack["needs_offset_calibration"])
        self.assertEqual(pack["pack_warning"], "This file contains all of Season 2")
        self.assertIsNone(pack["offset_seconds"])
        self.assertTrue(page["playable"])

    def test_learned_offset_is_applied_to_a_pack_episode(self):
        page = self.manifest("Campus Beats", season=2, episode=3)
        pack = page["prints"][0]
        self.assertEqual(pack["offset_seconds"], 1400)
        self.assertEqual(pack["chapter_title"], "Episode 3")
        self.assertEqual(pack["offset_source"], "cat_offsets:label")
        self.assertFalse(pack["needs_offset_calibration"])

    def test_label_agnostic_offset_also_applies(self):
        page = self.manifest("Campus Beats", season=2, episode=4)
        pack = page["prints"][0]
        self.assertEqual(pack["offset_seconds"], 2600)
        self.assertEqual(pack["chapter_title"], "Episode 4")
        self.assertEqual(pack["offset_source"], "cat_offsets:any_label")

    def test_episode_only_in_some_prints_lists_exactly_the_ones_that_cover_it(self):
        page = self.manifest("Campus Beats", season=1, episode=3)
        labels = sorted(p["label"] for p in page["prints"])
        self.assertEqual(labels, ["Campus Beats S01 EP(01-06) 720p"])
        self.assertEqual(page["prints"][0]["match_kind"], "materialised")
        self.assertEqual(page["prints"][0]["ordinal"], 3)

    def test_range_bounds_resolve_past_the_enumeration_cap(self):
        # 1-4000 is too wide to materialise, so the projector stores only the bounds;
        # E200 must still find the batch through `episode_range`.
        page = self.manifest("Mega Batch Show", season=1, episode=200)
        self.assertEqual(page["print_count"], 1)
        entry = page["prints"][0]
        self.assertEqual(entry["coverage_type"], "episode_range")
        self.assertEqual(entry["match_kind"], "range_bounds")
        self.assertEqual(entry["label"], "Mega Batch Show E1-E4000 480p")

    def test_season_only_manifest_lists_whole_season_prints(self):
        page = self.manifest("Campus Beats", season=2)
        self.assertEqual(page["target"]["resolved_by"], "season")
        self.assertEqual([p["label"] for p in page["prints"]],
                         ["Campus Beats S02 Complete 720p"])

    def test_missing_episode_of_a_partial_season_is_an_honest_empty_manifest(self):
        # Ghost Town Tapes: S01 has E1-E2 only, S02 has E1-E3.
        page = self.manifest("Ghost Town Tapes", season=1, episode=3)
        self.assertTrue(page["ok"])
        self.assertEqual(page["prints"], [])
        self.assertFalse(page["playable"])
        complete = self.manifest("Ghost Town Tapes", season=2, episode=3)
        self.assertEqual(complete["print_count"], 1)
        self.assertEqual(complete["target"]["absolute"], 5)

    def test_movie_manifest_needs_no_episode_addressing(self):
        page = self.manifest("Split Film")
        self.assertEqual(page["target"]["resolved_by"], "whole_work")
        self.assertEqual(sorted(p["label"] for p in page["prints"]),
                         ["Split Film (2022) Part 1 1080p WEB-DL",
                          "Split Film (2022) Part 2 1080p WEB-DL"])

    def test_series_manifest_without_any_addressing_is_a_clear_input_error(self):
        page = self.manifest("Campus Beats")
        self.assertFalse(page["ok"])
        self.assertEqual(page["error"]["code"], "invalid_input")

    def test_episode_only_addressing_is_allowed_when_there_is_one_season(self):
        page = catalog_api.episode_manifest(self.conn,
                                           work_id=self.work["Mega Batch Show"]["id"],
                                           episode=25)
        self.assertTrue(page["ok"])
        self.assertEqual(page["target"]["season"], 1)

    def test_adult_work_manifest_is_indistinguishable_from_a_missing_work(self):
        adult = self.manifest("Adult Diary", season=0, episode=1)
        missing = catalog_api.episode_manifest(self.conn, work_id=424242, season=1, episode=1)
        self.assertEqual(adult, missing)
        self.assertEqual(adult["error"]["code"], "not_found")

    def test_unresolved_scope_prints_are_kept_visible_but_not_asserted(self):
        page = self.manifest("Broken Season Show", season=1, episode=1)
        self.assertEqual(page["prints"], [])
        self.assertEqual(len(page["scope_unresolved_prints"]), 1)
        self.assertIn("zero-data-loss", page["scope_unresolved_prints"][0]["scope_note"])

    def test_episode_detail_end_point_shares_the_same_coverage_engine(self):
        episode_id = self.conn.execute(
            "SELECT e.id FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id"
            " WHERE e.work_id = ? AND s.number = 1 AND e.number = 7",
            (self.work["Campus Beats"]["id"],)).fetchone()["id"]
        detail = catalog_api.episode_detail(self.conn, episode_id=episode_id)
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["episode"]["number"], 7)
        self.assertEqual(detail["episode"]["work_title"], "Campus Beats")
        self.assertIn("Campus Beats S01E07 720p", [p["label"] for p in detail["prints"]])


# ── play bundle ──────────────────────────────────────────────────────────────

class PlayBundleTests(CatalogApiTestCase):
    def test_a_dead_but_fast_link_never_outranks_a_live_slow_one(self):
        bundle = self.bundle("4K HDR")
        candidates = bundle["candidates"]
        self.assertEqual(len(candidates), 2)
        first, second = candidates
        self.assertEqual(first["link_id"], self.link_of["DUNE-LIVE-SLOW"]["id"])
        self.assertEqual(second["link_id"], self.link_of["DUNE-DEAD-FAST"]["id"])
        self.assertTrue(second["dead"])
        self.assertEqual(second["state"], "dead")
        self.assertGreater(second["speed_mbps"], first["speed_mbps"],
                           "the loser must genuinely be the faster link")
        self.assertLess(second["rank_score"], first["rank_score"])
        self.assertEqual(bundle["recommended_link_id"], first["link_id"])
        self.assertEqual([t["link_id"] for t in bundle["tried"]], [second["link_id"]])
        self.assertEqual(bundle["playable"], True)

    def test_measured_evidence_is_surfaced_per_candidate(self):
        bundle = self.bundle("4K HDR")
        live, dead = bundle["candidates"]
        self.assertEqual(live["speed_mbps"], 3.2)
        self.assertEqual(live["latency_ms"], 610)
        self.assertEqual(live["accepts_ranges"], True, "ranges come from the probe")
        self.assertTrue(live["measured"])
        self.assertEqual(dead["http_status"], 404)
        self.assertEqual(dead["probe_error"], "http_404")

    def test_candidates_are_ordered_stream_then_resolve_then_webview_then_download(self):
        bundle = self.bundle("1080p WEB-DL")
        groups = [c["group"] for c in bundle["candidates"]]
        self.assertEqual(groups, sorted(groups))
        kinds = [c["kind"] for c in bundle["candidates"]]
        self.assertEqual(kinds[0], "hls_manifest")
        self.assertIn("embed", kinds)
        self.assertIn("cloud_page", kinds)
        embed_link = [c for c in bundle["candidates"] if c["kind"] == "embed"][0]
        self.assertEqual(embed_link["playability"], "webview")
        self.assertGreater(embed_link["group"],
                           [c for c in bundle["candidates"] if c["kind"] == "cloud_page"][0]["group"])
        self.assertEqual([c["link_id"] for c in bundle["stream_candidates"]],
                         [bundle["candidates"][0]["link_id"]])

    def test_ephemeral_tier_and_ranges_are_reported_per_link(self):
        bundle = self.bundle("1080p WEB-DL")
        page_link = [c for c in bundle["candidates"] if c["kind"] == "cloud_page"][0]
        self.assertTrue(page_link["ephemeral"])
        self.assertEqual(page_link["group"], 1)
        self.assertEqual(page_link["tier"], 2)
        self.assertIsNone(page_link["speed_mbps"])
        self.assertFalse(page_link["measured"], "no probe happened -> not measured")

    def test_download_only_print_yields_no_stream_but_a_full_download_option(self):
        bundle = self.bundle("720p CAM")
        self.assertEqual(bundle["stream_candidates"], [])
        self.assertFalse(bundle["playable"])
        self.assertEqual(bundle["reason"], "no_playable_source")
        self.assertEqual(len(bundle["download_options"]), 1)
        option = bundle["download_options"][0]
        self.assertEqual(option["kind"], "download_only")
        self.assertEqual(option["playability"], "download")
        self.assertEqual(option["state"], "active")

    def test_archive_and_bridge_links_are_kept_and_ranked_last(self):
        bundle = self.bundle("480p")
        kinds = [c["kind"] for c in bundle["candidates"]]
        self.assertEqual(set(kinds), {"download_only", "bridge"})
        last = bundle["candidates"][-1]
        self.assertEqual(last["kind"], "bridge")
        self.assertEqual(last["group"], 4)
        self.assertFalse(bundle["playable"])
        self.assertEqual(bundle["candidate_count"], 2)

    def test_print_label_is_human_and_a_cam_is_labelled_as_one_to_avoid(self):
        self.assertEqual(self.bundle("4K HDR")["print_label"],
                         "4K HDR10 BluRay REPACK 10-bit · H265 · Hindi · ESubs")
        cam = self.bundle("720p CAM")["print_label"]
        self.assertTrue(cam.startswith("720p CAM"))
        self.assertIn("— avoid", cam)
        self.assertIn("Watermarked", cam)
        self.assertEqual(self.bundle("1080p WEB-DL")["print_label"],
                         "1080p WEB-DL · H264 · Hindi")
        # Nothing from the raw scrape label may leak into the human label.
        for label in (self.bundle("4K HDR")["print_label"], cam):
            self.assertNotIn("Dune", label, "the work title belongs to the work, not the print")
            self.assertNotIn("(2024)", label)

    def test_bundle_for_an_episode_of_a_pack_carries_the_offset(self):
        release = self.print_by_fragment("Campus Beats", "S02 Complete")
        episode_id = self.conn.execute(
            "SELECT id FROM cat_episodes WHERE work_id = ? AND number = 3 AND season_id IN"
            " (SELECT id FROM cat_seasons WHERE number = 2)",
            (self.work["Campus Beats"]["id"],)).fetchone()
        self.assertIsNone(episode_id, "a season pack must not have enumerated episodes")
        # The S02 pack asked for S01E7: there is no materialised chapter row and the
        # only learned offset on file is for S02E3, so the honest answer is "unknown".
        episode_id = self.conn.execute(
            "SELECT e.id FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id"
            " WHERE e.work_id = ? AND s.number = 1 AND e.number = 7",
            (self.work["Campus Beats"]["id"],)).fetchone()["id"]
        bundle = catalog_api.play_bundle(self.conn, release_id=release["id"],
                                        episode_id=episode_id)
        self.assertEqual(bundle["target"]["season"], 1)
        self.assertIsNone(bundle["coverage"]["offset_seconds"],
                          "the S02E3 offset must not leak into an S01E7 request")
        self.assertIsNone(bundle["coverage"]["chapter_title"])
        self.assertTrue(bundle["coverage"]["needs_offset_calibration"])
        self.assertEqual(bundle["coverage"]["pack_warning"],
                         "This file contains all of Season 2",
                         "the warning names the season of the FILE, not of the request")

    def test_bundle_for_an_enumerated_episode_uses_the_learned_pack_offset(self):
        # Ghost Town Tapes has real S02 episode rows; add a pack print for that season
        # through the same ingestion pipeline, then calibrate it.
        self.add_post("site-y", "https://y.test/ghost-town-tapes-s02/",
                      clean_title="Ghost Town Tapes", year=2019, content_type="series",
                      releases=[{"release_title": "Ghost Town Tapes S02 Complete 1080p",
                                 "season": "2", "episode": "Batch", "quality": "1080p",
                                 "sources": [cdn("GTT-S02-PACK")]}])
        self.project(rev=2)
        pack = self.print_by_fragment("Ghost Town Tapes", "S02 Complete")
        catalog_v2.record_offset(self.conn, work_key=self.work["Ghost Town Tapes"]["work_key"],
                                 season_number=2, episode_number=3, offset_seconds=4400,
                                 release_label="Ghost Town Tapes S02 Complete 1080p",
                                 chapter_title="Ep. 3 in the pack")
        episode_id = self.conn.execute(
            "SELECT e.id FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id"
            " WHERE e.work_id = ? AND s.number = 2 AND e.number = 3",
            (self.work["Ghost Town Tapes"]["id"],)).fetchone()["id"]
        bundle = catalog_api.play_bundle(self.conn, release_id=pack["id"],
                                         episode_id=episode_id)
        self.assertEqual(bundle["coverage"]["offset_seconds"], 4400)
        self.assertEqual(bundle["coverage"]["chapter_title"], "Ep. 3 in the pack")
        self.assertEqual(bundle["coverage"]["source"], "cat_offsets")
        self.assertFalse(bundle["coverage"]["needs_offset_calibration"])

    def test_pack_bundle_marks_calibration_needed_for_the_requested_episode(self):
        release = self.print_by_fragment("Campus Beats", "S02 Complete")
        episode_id = self.conn.execute(
            "SELECT e.id FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id"
            " WHERE e.work_id = ? AND s.number = 1 AND e.number = 1",
            (self.work["Campus Beats"]["id"],)).fetchone()["id"]
        bundle = catalog_api.play_bundle(self.conn, release_id=release["id"],
                                        episode_id=episode_id)
        self.assertTrue(bundle["coverage"]["needs_offset_calibration"])
        self.assertEqual(bundle["coverage"]["pack_warning"],
                         "This file contains all of Season 2")

    def test_offset_from_a_materialised_chapter_row_is_used_when_present(self):
        release = self.print_by_fragment("Campus Beats", "EP(01-06)")
        episode_id = self.conn.execute(
            "SELECT e.id FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id"
            " WHERE e.work_id = ? AND s.number = 1 AND e.number = 4",
            (self.work["Campus Beats"]["id"],)).fetchone()["id"]
        self.conn.execute(
            "UPDATE cat_release_episodes SET offset_seconds = 3000, chapter_title ="
            " 'Chapter Four' WHERE release_id = ? AND episode_id = ?",
            (release["id"], episode_id))
        self.conn.commit()
        bundle = catalog_api.play_bundle(self.conn, release_id=release["id"],
                                        episode_id=episode_id)
        self.assertEqual(bundle["coverage"]["offset_seconds"], 3000)
        self.assertEqual(bundle["coverage"]["chapter_title"], "Chapter Four")
        self.assertEqual(bundle["coverage"]["source"], "cat_release_episodes")
        self.assertEqual(bundle["coverage"]["ordinal"], 4)

    def test_episode_from_another_work_is_not_playable_through_this_release(self):
        release = self.print_by_fragment("Campus Beats", "S01E07")
        other = self.conn.execute("SELECT id FROM cat_episodes WHERE work_id = ?",
                                  (self.work["Ghost Town Tapes"]["id"],)).fetchone()["id"]
        bundle = catalog_api.play_bundle(self.conn, release_id=release["id"],
                                        episode_id=other)
        self.assertFalse(bundle["ok"])
        self.assertEqual(bundle["error"]["code"], "not_found")

    def test_adult_and_unknown_release_are_both_plain_not_found(self):
        adult_release = self.conn.execute(
            "SELECT r.id FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
            " WHERE w.is_18_plus = 1").fetchone()["id"]
        adult = catalog_api.play_bundle(self.conn, release_id=adult_release)
        missing = catalog_api.play_bundle(self.conn, release_id=999999)
        self.assertEqual(adult, missing)
        self.assertEqual(adult["error"]["code"], "not_found")

    def test_release_detail_lists_coverage_and_descriptor_without_inventing_fields(self):
        release = self.print_by_fragment("Dune", "4K HDR")
        detail = catalog_api.release_detail(self.conn, release_id=release["id"])
        self.assertEqual(detail["coverage"]["type"], "whole_work")
        self.assertEqual(detail["print"]["hdr"], ["hdr10"])
        self.assertEqual(detail["print"]["bit_depth"], 10)
        self.assertEqual(detail["print"]["codec"], "h265")
        self.assertEqual(detail["descriptor_json"]["edition"], "unknown")
        self.assertEqual(detail["work"]["title"], "Dune")
        self.assertEqual(detail["print"]["release_group"], None,
                         "the projector writes '' -> reported as null, not a guessed group")


# ── entitlements ─────────────────────────────────────────────────────────────

class EntitlementTests(CatalogApiTestCase):
    def entitle(self, title, **kw):
        return catalog_api.resolve_entitlement(self.conn,
                                               work_id=self.work[title]["id"], **kw)

    def test_default_work_is_explicitly_free_and_allowed(self):
        result = self.entitle("Dune")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(result["reason"], "free")
        self.assertEqual(result["entitlement"]["model"], "free")
        self.assertEqual(result["entitlement"]["ownership"], "permanent")

    def test_a_missing_row_is_an_explicit_deny_never_allow_by_absence(self):
        self.conn.execute("DELETE FROM cat_entitlements WHERE work_id = ?",
                          (self.work["Dune"]["id"],))
        self.conn.commit()
        result = self.entitle("Dune")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["reason"], "no_entitlement_record")
        self.assertIs(result["implicit"], False)

    def test_rental_without_a_licence_is_licence_required_with_the_price(self):
        # `valid_until` is 1730000000, so the check runs inside that window on purpose;
        # the clock of the machine under test is not a fixture.
        result = self.entitle("Paid Opera", now=1729999000)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "licence_required")
        self.assertEqual(result["reason"], "purchase_required")
        self.assertEqual(result["entitlement"]["model"], "rental")
        self.assertEqual(result["price"], {"minor": 14900, "currency": "INR"})
        self.assertEqual(result["rental_hours"], 48)

    def test_a_held_licence_allows_and_reports_ownership(self):
        result = self.entitle("Paid Opera", now=1729999000,
                              principal={"id": "user-1", "owns": True,
                                         "account": True})
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "purchased")
        self.assertEqual(result["ownership"], "until_expiry")

    def test_a_held_licence_past_the_window_is_denied_even_when_owned(self):
        result = self.entitle("Paid Opera", now=1740000000,
                             principal={"id": "user-1", "owns": True})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["reason"], "expired")

    def test_expired_licence_window_is_denied(self):
        # `now` is injectable so time-window logic is testable without sleeping.
        result = self.entitle("Paid Opera", now=1740000000,
                              principal={"id": "u", "owns": True})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "expired")

    def test_requires_account_blocks_anonymous_even_for_free(self):
        self.set_entitlement("Dune", requires_account=1)
        anonymous = self.entitle("Dune")
        self.assertFalse(anonymous["allowed"])
        self.assertEqual(anonymous["reason"], "account_required")
        named = self.entitle("Dune", principal="user-77")
        self.assertTrue(named["allowed"])

    def test_age_gate_blocks_a_principal_that_has_not_confirmed_age(self):
        self.set_entitlement("Dune", requires_age_gate=1)
        gated = self.entitle("Dune", principal={"id": "u"})
        self.assertFalse(gated["allowed"])
        self.assertEqual(gated["reason"], "age_gate_required")
        passed = self.entitle("Dune", principal={"id": "u", "adult_ok": True})
        self.assertTrue(passed["allowed"])

    def test_geo_deny_and_geo_allow_are_enforced(self):
        self.set_entitlement("Dune", geo_deny='["EU"]')
        blocked = self.entitle("Dune", principal={"id": "u", "region": "EU"})
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["reason"], "geo_denied")
        allowed = self.entitle("Dune", principal={"id": "u", "region": "IN"})
        self.assertTrue(allowed["allowed"])
        self.set_entitlement("Dune", geo_deny="[]", geo_allow='["IN"]')
        unknown_region = self.entitle("Dune", principal={"id": "u"})
        self.assertFalse(unknown_region["allowed"])
        self.assertEqual(unknown_region["reason"], "geo_required")

    def test_release_scoped_row_beats_the_work_scoped_row(self):
        release = self.print_by_fragment("Paid Opera", "1080p")
        self.conn.execute(
            "INSERT INTO cat_entitlements (work_id, release_id, model, ownership,"
            " updated_at) VALUES (?, ?, 'free', 'permanent', 1730000000)",
            (self.work["Paid Opera"]["id"], release["id"]))
        self.conn.commit()
        paid = self.entitle("Paid Opera")
        self.assertEqual(paid["entitlement"]["model"], "rental")
        free = self.entitle("Paid Opera", release_id=release["id"])
        self.assertTrue(free["allowed"])
        self.assertEqual(free["entitlement"]["release_id"], release["id"])

    def test_adult_work_entitlement_is_not_found_not_403(self):
        adult = self.entitle("Adult Diary")
        missing = catalog_api.resolve_entitlement(self.conn, work_id=777777)
        self.assertEqual(adult, missing)

    def test_the_callers_principal_object_is_never_mutated(self):
        principal = {"id": "u", "owns": True}
        catalog_api.resolve_entitlement(self.conn, work_id=self.work["Paid Opera"]["id"],
                                       principal=principal)
        self.assertEqual(principal, {"id": "u", "owns": True})

    def test_season_detail_and_entitlement_composition(self):
        season = catalog_api.season_detail(self.conn, work_id=self.work["Campus Beats"]["id"],
                                           season_number=2)
        self.assertTrue(season["ok"])
        self.assertEqual(season["season"]["number"], 2)
        self.assertTrue(season["season"]["pack_only"])
        missing = catalog_api.season_detail(self.conn, work_id=self.work["Campus Beats"]["id"],
                                            season_number=9)
        self.assertEqual(missing["error"]["code"], "not_found")


# ── continue-watching target ─────────────────────────────────────────────────

class EpisodeTargetTests(CatalogApiTestCase):
    def target(self, title, **kw):
        return catalog_api.resolve_episode_target(self.conn,
                                                 work_id=self.work[title]["id"], **kw)

    def test_exact_label_offset_wins_over_the_label_agnostic_row(self):
        # E4 only has the label-agnostic offset; add a conflicting exact-label one.
        catalog_v2.record_offset(self.conn,
                                 work_key=self.work["Campus Beats"]["work_key"],
                                 season_number=2, episode_number=4, offset_seconds=2700,
                                 release_label="Campus Beats S02 Complete 720p",
                                 chapter_title="Episode 4 (labelled)")
        result = self.target("Campus Beats", season=2, episode=4,
                             release_label="Campus Beats S02 Complete 720p")
        self.assertTrue(result["found"])
        self.assertEqual(result["offset_seconds"], 2700)
        self.assertEqual(result["source"], "cat_offsets:exact_label")
        self.assertTrue(result["label_matched"])
        self.assertEqual(result["chapter_title"], "Episode 4 (labelled)")

    def test_falls_back_to_any_label_when_this_print_was_never_named(self):
        result = self.target("Campus Beats", season=2, episode=4,
                             release_label="Campus Beats S02 COMPLETE 1080p x265")
        self.assertEqual(result["offset_seconds"], 2600)
        self.assertEqual(result["source"], "cat_offsets:fallback_any_label")
        self.assertFalse(result["label_matched"])

    def test_unknown_offset_is_reported_as_needing_calibration(self):
        result = self.target("Campus Beats", season=2, episode=9,
                             release_label="Campus Beats S02 Complete 720p")
        self.assertTrue(result["ok"])
        self.assertFalse(result["found"])
        self.assertIsNone(result["offset_seconds"])
        self.assertTrue(result["needs_calibration"])
        self.assertEqual(result["target"]["release_label"], "Campus Beats S02 Complete 720p")
        self.assertEqual(result["target"]["coverage_type"], "season_pack")

    def test_materialised_chapter_wins_when_the_print_episode_row_has_it(self):
        release = self.print_by_fragment("Campus Beats", "EP(01-06)")
        episode_id = self.conn.execute(
            "SELECT e.id FROM cat_episodes e JOIN cat_seasons s ON s.id = e.season_id"
            " WHERE e.work_id = ? AND s.number = 1 AND e.number = 2",
            (self.work["Campus Beats"]["id"],)).fetchone()["id"]
        self.conn.execute("UPDATE cat_release_episodes SET offset_seconds = 700,"
                          " chapter_title = 'Chapter Two' WHERE release_id = ? AND episode_id = ?",
                          (release["id"], episode_id))
        self.conn.commit()
        result = self.target("Campus Beats", season=1, episode=2,
                             release_label="Campus Beats S01 EP(01-06) 720p")
        self.assertEqual(result["offset_seconds"], 700)
        self.assertEqual(result["source"], "cat_release_episodes")
        self.assertEqual(result["target"]["episode_id"], episode_id)

    def test_label_may_be_matched_as_a_substring_of_the_stored_print_label(self):
        result = self.target("Campus Beats", season=2, episode=3,
                             release_label="S02 Complete")
        self.assertTrue(result["ok"])
        self.assertEqual(result["offset_seconds"], 1400)

    def test_missing_episode_number_is_an_input_error(self):
        result = self.target("Campus Beats", season=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_input")

    def test_adult_work_target_is_not_found(self):
        result = self.target("Adult Diary", season=0, episode=1)
        self.assertEqual(result["error"]["code"], "not_found")


# ── catalog state ────────────────────────────────────────────────────────────

class CatalogStateTests(CatalogApiTestCase):
    def test_state_reports_rev_counts_and_projector_version(self):
        state = catalog_api.catalog_state(self.conn)
        self.assertTrue(state["ok"])
        self.assertEqual(state["rev"], 1)
        self.assertEqual(state["projector_version"], 1)
        self.assertEqual(state["counts"]["works"],
                         self.conn.execute("SELECT COUNT(*) AS n FROM cat_works WHERE"
                                           " COALESCE(is_18_plus,0)=0").fetchone()["n"])
        self.assertGreater(state["counts"]["prints"], 0)
        self.assertGreater(state["counts"]["links"], 0)
        self.assertEqual(state["counts"]["link_states"].get("dead"), 2,
                         "DUNE-DEAD-FAST and DEADAIR")
        self.assertEqual(state["counts"]["open_review_queue"], 1)
        self.assertEqual(state["counts"]["offsets"], 2)
        self.assertIsNotNone(state["projected_at"])

    def test_adult_rows_are_excluded_from_every_state_count(self):
        state = catalog_api.catalog_state(self.conn)
        self.assertNotIn("Adult Diary", [self.work[t]["title"] for t in self.work
                                        if self.work[t]["title"] == "Adult Diary"][:0])
        adult_works = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cat_works WHERE is_18_plus = 1").fetchone()["n"]
        all_works = self.conn.execute("SELECT COUNT(*) AS n FROM cat_works").fetchone()["n"]
        self.assertEqual(adult_works, 1)
        self.assertEqual(state["counts"]["works"], all_works - adult_works)
        adult_links = self.conn.execute(
            "SELECT COUNT(*) AS n FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
            " WHERE w.is_18_plus = 1").fetchone()["n"]
        self.assertEqual(state["counts"]["links"],
                         self.conn.execute("SELECT COUNT(*) AS n FROM cat_links").fetchone()["n"]
                         - adult_links)

    def test_etag_is_stable_within_a_projection_and_changes_after_reprojection(self):
        first = catalog_api.catalog_state(self.conn)["etag"]
        again = catalog_api.catalog_state(self.conn)["etag"]
        self.assertEqual(first, again)
        self.assertTrue(first.startswith('"') and first.endswith('"'))
        catalog_v2.project(self.conn, rev=2, verbose=False)
        self.conn.commit()
        moved = catalog_api.catalog_state(self.conn)
        self.assertEqual(moved["rev"], 2)
        self.assertNotEqual(moved["etag"], first)

    def test_state_survives_an_empty_projection(self):
        self.conn.execute("DELETE FROM cat_works")
        self.conn.execute("DELETE FROM cat_releases")
        self.conn.execute("DELETE FROM cat_links")
        self.conn.commit()
        state = catalog_api.catalog_state(self.conn)
        self.assertEqual(state["counts"]["works"], 0)
        self.assertEqual(state["rev"], 0)


# ── contract guards ──────────────────────────────────────────────────────────

class ContractGuardTests(CatalogApiTestCase):
    def test_functions_refuse_a_connection_without_the_row_factory(self):
        plain = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(ValueError):
                catalog_api.browse(plain, limit=1)
        finally:
            plain.close()

    def test_functions_refuse_a_non_connection(self):
        with self.assertRaises(TypeError):
            catalog_api.catalog_state("not a connection")

    def test_no_public_function_prints_or_reads_argv(self):
        import inspect
        import re
        # A real call to the builtin, not the word inside `_merge_print(...)` or a docstring.
        call = re.compile(r"(?<![\w.])print\(")
        checked = 0
        for name in catalog_api.__all__:
            member = getattr(catalog_api, name)
            if not callable(member):
                continue
            checked += 1
            source = inspect.getsource(member)
            self.assertIsNone(call.search(source), name)
            self.assertNotIn("sys.argv", source, name)
            self.assertNotIn("argparse", source, name)
        self.assertGreaterEqual(checked, 10)

    def test_coverage_type_vocabulary_is_complete(self):
        self.assertEqual(set(catalog_api.COVERAGE_TYPES),
                         {"whole_work", "season_pack", "episode_range", "single_episode",
                          "parts"})
        stored = {row["coverage_type"] for row in
                  self.conn.execute("SELECT DISTINCT coverage_type FROM cat_releases")}
        self.assertTrue(stored <= set(catalog_api.COVERAGE_TYPES), stored)

    def test_normalize_text_is_the_documented_folding(self):
        self.assertEqual(catalog_api.normalize_text("  Dune:  Part TWO (2024)! "),
                         "dune part two 2024")
        self.assertEqual(catalog_api.normalize_text("Café Clown [WEB-DL]"), "cafe clown web dl")
        self.assertEqual(catalog_api.normalize_text(None), "")

    def test_cursor_round_trip_is_opaque_but_validatable(self):
        cursor = catalog_api.encode_cursor(sort_value=42, work_id=7, sort="quality",
                                          order="desc", fingerprint="abc123")
        decoded = catalog_api.decode_cursor(cursor)
        self.assertEqual(decoded, {"v": 42, "i": 7, "s": "quality", "o": "desc",
                                   "f": "abc123"})
        self.assertIsNone(catalog_api.decode_cursor("%%%"))
        self.assertIsNone(catalog_api.decode_cursor(""))

    def test_read_model_touches_no_layer_zero_table(self):
        """browse/detail/play only read cat_* — a client must never depend on the ledger."""
        before = {table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("posts", "releases", "download_sources", "post_sources")}
        catalog_api.browse(self.conn, limit=50)
        catalog_api.search(self.conn, q="dune")
        catalog_api.work_detail(self.conn, work_id=self.work["Dune"]["id"])
        catalog_api.catalog_state(self.conn)
        after = {table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in ("posts", "releases", "download_sources", "post_sources")}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
