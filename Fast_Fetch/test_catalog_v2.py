#!/usr/bin/env python3
"""Real scenario tests for the catalog v2 projector.

Every case feeds the ingest ledger through `fast_fetch.save_scraped_data` (the same
path a scraper uses), rebuilds the canonical layer with `catalog_v2.project`, and then
asserts on the rows the API would serve. Nothing is mocked: if the projector drops a
print, merges two different works or invents an episode, one of these tests fails.
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

import catalog_v2
import fast_fetch
import release_descriptor
import viewer


def _row(conn, sql, *args):
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, args).fetchone()


class ProjectionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "catalog.db"
        # save_scraped_data resolves its own connection from fast_fetch.DB_PATH, so an
        # unpatched path here would write fixtures into the developer's real catalog.
        self._patches = [
            unittest.mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
            unittest.mock.patch.object(viewer, "DB_PATH", self.db_path),
        ]
        for patcher in self._patches:
            patcher.start()
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.summary = None

    def tearDown(self):
        self.conn.close()
        for patcher in self._patches:
            patcher.stop()
        self.tmp.cleanup()

    # ---- ledger builders -------------------------------------------------- #
    def add_post(self, site, url, *, title=None, clean_title="Example Film", year=2024,
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
            "backdrop_urls": None,
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
            "releases": [dict(r) for r in releases],
        }
        data["releases"] = [self._release(data, r) for r in releases]
        post_id = fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        # The ingester always writes 'active'; the health checker is what marks a link
        # dead, so the fixture reproduces that second step the same way production does.
        for rel in data["releases"]:
            for src in rel.get("sources") or []:
                if src.get("status") and src["status"] != "active":
                    self.conn.execute(
                        "UPDATE download_sources SET status = ? WHERE source_url = ?",
                        (src["status"], src["source_url"]))
        self.conn.commit()
        return post_id

    @staticmethod
    def _release(post, spec):
        rel = {
            "release_title": spec.get("release_title", f"{post['clean_title']} 1080p"),
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
        return rel

    def project(self):
        self.conn.commit()
        self.summary = catalog_v2.project(self.conn, rev=1, verbose=False)
        return self.summary

    # ---- assertions helpers ----------------------------------------------- #
    def works(self, title, year=None):
        if year is None:
            return self.conn.execute(
                "SELECT * FROM cat_works WHERE title = ?", (title,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM cat_works WHERE title = ? AND year = ?", (title, year)).fetchall()

    def releases(self, work_id):
        return self.conn.execute(
            "SELECT * FROM cat_releases WHERE work_id = ? ORDER BY quality_score DESC, id",
            (work_id,)).fetchall()

    def links(self, release_id):
        return self.conn.execute(
            "SELECT * FROM cat_links WHERE release_id = ?", (release_id,)).fetchall()


class WorkIdentityTests(ProjectionTestCase):
    """One real work must be exactly one catalog row, whatever sites claim."""

    def add_two_source_release(self, site, url, **kw):
        return self.add_post(site, url, releases=[
            {"release_title": f"{kw.get('clean_title', 'Example Film')} 1080p WEB-DL",
             "quality": "1080p", "sources": [self.cdn_link(f"{site}-a")]},
            {"release_title": f"{kw.get('clean_title', 'Example Film')} 480p",
             "quality": "480p", "sources": [self.cdn_link(f"{site}-b")]},
        ], **kw)

    @staticmethod
    def cdn_link(tag):
        return {"source_name": "CDN", "service": "google_cdn", "resource_id": tag,
                "source_url": f"https://video-downloads.googleusercontent.com/{tag}",
                "final_url": f"https://video-downloads.googleusercontent.com/{tag}",
                "playback_type": "direct", "is_temporary": 0, "status": "active"}

    def test_same_title_year_from_two_sites_is_one_work(self):
        self.add_two_source_release("hdhub4u", "https://hdhub4u.test/example-film/",
                                    clean_title="Example Film", year=2024)
        self.add_two_source_release("ssrmovies", "https://ssrmovies.test/example-film-2024/",
                                    clean_title="Example Film", year=2024)
        summary = self.project()
        works = self.works("Example Film", 2024)
        self.assertEqual(len(works), 1, "two sites produced sibling works")
        work = works[0]
        self.assertEqual(work["site_count"], 2)
        self.assertEqual(work["release_count"], 4)
        pages = self.conn.execute(
            "SELECT page_url FROM cat_work_sites WHERE work_id = ? ORDER BY page_url",
            (work["id"],)).fetchall()
        self.assertEqual(len(pages), 2)
        # every link from both sites survived
        links = self.conn.execute(
            "SELECT COUNT(*) FROM cat_links WHERE work_id = ?", (work["id"],)).fetchone()[0]
        self.assertEqual(links, 4)
        self.assertEqual(summary["links"], 4)

    def test_imdb_id_merges_even_when_titles_differ(self):
        self.add_post("vegamovies", "https://vega.test/movie/baby-2020/",
                      clean_title="Baby", year=2020, imdb_id="tt13044378",
                      releases=[{"release_title": "Baby (2020) Hindi 720p", "quality": "720p"}])
        self.add_post("multimovies", "https://mm.test/movie/baby/",
                      clean_title="Baby", year=2020, imdb_id="tt13044378",
                      releases=[{"release_title": "Baby (2020) 1080p", "quality": "1080p"}])
        self.project()
        works = self.conn.execute(
            "SELECT * FROM cat_works WHERE imdb_id = 'tt13044378'").fetchall()
        self.assertEqual(len(works), 1)
        self.assertEqual(works[0]["release_count"], 2)

    def test_movie_and_series_never_collapse_together(self):
        self.add_post("site-a", "https://a.test/nova-2019/",
                      clean_title="Nova", year=2019, content_type="movie")
        self.add_post("site-b", "https://b.test/nova-series/",
                      clean_title="Nova", year=2019, content_type="series",
                      releases=[{"release_title": "Nova S01E01", "season": "1", "episode": "1"}])
        self.project()
        works = self.works("Nova", 2019)
        self.assertEqual(len(works), 2)
        self.assertEqual({w["work_type"] for w in works}, {"movie", "series"})

    def test_sequel_with_same_slug_but_different_year_stays_separate(self):
        self.add_post("site-a", "https://a.test/alone-2015/", clean_title="Alone", year=2015)
        self.add_post("site-a", "https://a.test/alone-4-2024/", clean_title="Alone 4", year=2024)
        self.project()
        self.assertEqual(len(self.works("Alone", 2015)), 1)
        self.assertEqual(len(self.works("Alone 4", 2024)), 1)

    def test_part_number_is_not_folded_into_the_parent_title(self):
        self.add_post("site-a", "https://a.test/krrish-3/",
                      clean_title="Krrish Part 3", year=2013)
        self.add_post("site-a", "https://a.test/krrish-4/",
                      clean_title="Krrish Part 4", year=2023)
        self.project()
        keys = [w["work_key"] for w in self.conn.execute(
            "SELECT work_key FROM cat_works ORDER BY year").fetchall()]
        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])

    def test_dirty_season_and_episode_values_do_not_abort_projection(self):
        """Real rows carry 'S01', 'Batch', '150MB/E', '' in the same columns."""
        self.add_post("site-a", "https://a.test/series-one/", clean_title="Series One",
                      year=2022, content_type="series", releases=[
                          {"release_title": "Series One S01 Batch", "season": "S01",
                           "episode": "Batch", "size": "150MB/E", "quality": "unknown"},
                          {"release_title": "Series One E5", "season": "", "episode": "E5",
                           "quality": "720p"},
                      ])
        summary = self.project()
        self.assertEqual(summary["releases"], 2)


class PrintRankingTests(ProjectionTestCase):
    """Prints are ordered by measured quality, never by insertion order."""

    def add_prints(self):
        self.add_post("site-a", "https://a.test/dune-2/", clean_title="Dune", year=2024,
                      releases=[
                          {"release_title": "Dune (2024) 4K HDR 10bit BluRay ESub",
                           "quality": "2160p", "codec": "x265", "size": "12GB"},
                          {"release_title": "Dune (2024) 1080p WEB-DL",
                           "quality": "1080p", "codec": "x264", "size": "3GB"},
                          {"release_title": "Dune (2024) 720p CAM Watermarked",
                           "quality": "720p", "codec": "x264", "size": "1GB"},
                          {"release_title": "Dune (2024) 480p",
                           "quality": "480p", "codec": "x264", "size": "400MB"},
                      ])
        self.project()
        return self.releases(self.works("Dune", 2024)[0]["id"])

    def test_better_print_scores_higher(self):
        rels = self.add_prints()
        scores = [r["quality_score"] for r in rels]
        self.assertEqual(scores, sorted(scores, reverse=True))
        by_label = {r["resolution"]: r for r in rels}
        self.assertGreater(by_label["2160p"]["quality_score"], by_label["480p"]["quality_score"])

    def test_cam_never_outranks_a_clean_web_dl(self):
        rels = self.add_prints()
        cam = next(r for r in rels if r["source_tag"] == "cam")
        web = next(r for r in rels if r["source_tag"] == "web_dl")
        self.assertLess(cam["quality_score"], web["quality_score"])
        self.assertEqual(cam["official_print"], 0)
        self.assertEqual(cam["watermarked"], 1)
        self.assertIn("watermarked", json.loads(cam["flags"]))

    def test_resolution_and_source_tag_are_structured_not_free_text(self):
        rels = self.add_prints()
        hdr = next(r for r in rels if r["resolution"] == "2160p")
        self.assertEqual(json.loads(hdr["hdr"]), ["hdr10"])
        self.assertEqual(hdr["bit_depth"], 10)
        self.assertEqual(hdr["codec"], "h265")
        self.assertEqual(hdr["subtitle_mode"], "external")

    def test_repack_version_is_per_print_not_per_work(self):
        self.add_post("site-b", "https://b.test/repack-film/", clean_title="Repack Film",
                      year=2021, releases=[
                          {"release_title": "Repack Film (2021) 1080p WEB-DL v1",
                           "quality": "1080p"},
                          {"release_title": "Repack Film (2021) 1080p WEB-DL Repack",
                           "quality": "1080p"},
                      ])
        self.project()
        rels = self.releases(self.works("Repack Film", 2021)[0]["id"])
        self.assertEqual(len(rels), 2)
        versions = sorted(int(r["print_version"]) for r in rels)
        self.assertTrue(any(v > 0 for v in versions), f"no v1/repack parsed from {versions}")


class CoverageTests(ProjectionTestCase):
    """Packs, per-episode files and ranges are three different facts."""

    def series_releases(self, releases, title="Campus Beats", year=2020):
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=year, content_type="series",
                      releases=releases)
        self.project()
        return self.works(title, year)[0]

    def test_season_pack_is_one_release_covering_the_season(self):
        work = self.series_releases([
            {"release_title": "Campus Beats S01 Complete 720p", "season": "1",
             "episode": "Batch", "quality": "720p"},
        ])
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["coverage_type"], "season_pack")
        self.assertEqual(rel["season_number"], 1)
        eps = self.conn.execute(
            "SELECT COUNT(*) FROM cat_release_episodes WHERE release_id = ?",
            (rel["id"],)).fetchone()[0]
        self.assertEqual(eps, 0, "a pack must not fabricate episode rows")

    def test_per_episode_releases_create_one_episode_each(self):
        work = self.series_releases([
            {"release_title": f"Campus Beats S01E{n}", "season": "1", "episode": str(n),
             "quality": "720p"} for n in (1, 2, 3)
        ])
        eps = self.conn.execute(
            "SELECT number FROM cat_episodes WHERE work_id = ? ORDER BY number",
            (work["id"],)).fetchall()
        self.assertEqual([e["number"] for e in eps], [1, 2, 3])
        for rel in self.releases(work["id"]):
            self.assertEqual(rel["coverage_type"], "single_episode")
            linked = self.conn.execute(
                "SELECT COUNT(*) FROM cat_release_episodes WHERE release_id = ?",
                (rel["id"],)).fetchone()[0]
            self.assertEqual(linked, 1)

    def test_episode_range_expands_within_the_cap(self):
        work = self.series_releases([
            {"release_title": "Campus Beats E4-E7 720p", "season": "1",
             "episode": "4-7", "quality": "720p"},
        ])
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["coverage_type"], "episode_range")
        ords = [r["ordinal"] for r in self.conn.execute(
            "SELECT ordinal FROM cat_release_episodes WHERE release_id = ? ORDER BY ordinal",
            (rel["id"],)).fetchall()]
        self.assertEqual(ords, [4, 5, 6, 7])

    def test_giant_batch_range_does_not_fabricate_thousands_of_episodes(self):
        work = self.series_releases([
            {"release_title": "Campus Beats E1-E4000", "season": "1",
             "episode": "1-4000", "quality": "480p"},
        ])
        created = self.conn.execute(
            "SELECT COUNT(*) FROM cat_episodes WHERE work_id = ?", (work["id"],)).fetchone()[0]
        self.assertLessEqual(created, catalog_v2.MAX_ENUMERATED_EPISODES)

    def test_season_number_survives_the_S01_spelling(self):
        work = self.series_releases([
            {"release_title": "Campus Beats S02E05", "season": "S02", "episode": "05",
             "quality": "720p"},
        ])
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["season_number"], 2)

    def test_multi_season_series_keeps_seasons_apart(self):
        work = self.series_releases([
            {"release_title": "Campus Beats S01E01", "season": "1", "episode": "1"},
            {"release_title": "Campus Beats S02E01", "season": "2", "episode": "1"},
        ])
        seasons = self.conn.execute(
            "SELECT number FROM cat_seasons WHERE work_id = ? ORDER BY number",
            (work["id"],)).fetchall()
        self.assertEqual([s["number"] for s in seasons], [1, 2])

    def test_movie_is_whole_work(self):
        self.add_post("site-a", "https://a.test/solo-film/", clean_title="Solo Film",
                      year=2018, releases=[{"release_title": "Solo Film 1080p"}])
        self.project()
        rel = self.releases(self.works("Solo Film", 2018)[0]["id"])[0]
        self.assertEqual(rel["coverage_type"], "whole_work")


class LinkTruthTests(ProjectionTestCase):
    """A link's kind and playability come from the URL, not from what a scraper hoped."""

    def one_work_with(self, sources):
        self.add_post("site-a", "https://a.test/link-film/", clean_title="Link Film",
                      year=2022, releases=[{
                          "release_title": "Link Film 1080p", "quality": "1080p",
                          "sources": sources}])
        self.project()
        return self.conn.execute(
            "SELECT * FROM cat_links WHERE work_id = (SELECT id FROM cat_works WHERE title='Link Film')"
            " ORDER BY url").fetchall()

    def src(self, service, url, **kw):
        return {"source_name": service, "service": service, "resource_id": kw.get("rid", "x"),
                "source_url": url, "final_url": kw.get("final_url", url),
                "playback_type": kw.get("playback_type", "direct"),
                "is_temporary": kw.get("is_temporary", 0), "status": kw.get("status", "active")}

    def test_direct_file_is_streamable(self):
        links = self.one_work_with([self.src("google_cdn", "https://video-downloads.googleusercontent.com/AAA")])
        self.assertEqual(links[0]["kind"], "cdn_direct")
        self.assertIn(links[0]["playability"], ("stream", "both"))

    def test_hls_manifest_is_stream(self):
        links = self.one_work_with([self.src("cdn", "https://cdn.test/master.m3u8")])
        self.assertEqual(links[0]["kind"], "hls_manifest")
        self.assertEqual(links[0]["playability"], "stream")

    def test_hoster_page_is_resolve_required_not_stream(self):
        links = self.one_work_with([self.src("gdtot", "https://new26.gdtot.dad/file/330578949")])
        self.assertEqual(links[0]["playability"], "resolve_required")
        self.assertNotEqual(links[0]["kind"], "cdn_direct")

    def test_embed_player_is_webview_only(self):
        links = self.one_work_with([self.src("vidsrc", "https://vidsrcme.su/embed/movie?tmdb=1")])
        self.assertEqual(links[0]["kind"], "embed")
        self.assertEqual(links[0]["playability"], "webview")

    def test_bridge_redirect_is_not_promised_to_the_player(self):
        links = self.one_work_with([self.src("hubcloud", "https://gpdl.hubcloud.ist/?id=abc")])
        self.assertEqual(links[0]["kind"], "bridge")
        self.assertEqual(links[0]["playability"], "none")

    def test_archive_link_is_download_only(self):
        links = self.one_work_with([self.src("hubcloud", "https://hubcloud.link/Show.S01.zip")])
        self.assertEqual(links[0]["playability"], "download")

    def test_empty_target_is_recorded_not_dropped(self):
        links = self.one_work_with([self.src("dead", "", final_url="")])
        self.assertEqual(links[0]["kind"], "dead_end")
        self.assertEqual(links[0]["playability"], "none")

    def test_dead_status_is_preserved(self):
        links = self.one_work_with([self.src("google_cdn",
                                             "https://video-downloads.googleusercontent.com/DEAD",
                                             status="dead")])
        self.assertEqual(links[0]["state"], "dead")
        self.assertLess(links[0]["rank_score"], 500)

    def test_ephemeral_links_rank_below_stable_ones(self):
        links = self.one_work_with([
            self.src("google_cdn", "https://video-downloads.googleusercontent.com/EPH",
                     is_temporary=1),
            self.src("google_cdn", "https://video-downloads.googleusercontent.com/KEEP"),
        ])
        by_final = {l["final_url"].rsplit("/", 1)[-1]: l for l in links}
        self.assertLess(by_final["EPH"]["rank_score"], by_final["KEEP"]["rank_score"])

    def test_duplicate_url_is_collapsed_but_release_keeps_every_distinct_link(self):
        self.add_post("site-a", "https://a.test/dup-film/", clean_title="Dup Film", year=2021,
                      releases=[
                          {"release_title": "Dup Film 1080p", "quality": "1080p",
                           "sources": [self.src("g", "https://video-downloads.googleusercontent.com/ONE"),
                                       self.src("g", "https://video-downloads.googleusercontent.com/ONE"),
                                       self.src("g", "https://video-downloads.googleusercontent.com/TWO")]},
                      ])
        self.project()
        rel = self.releases(self.works("Dup Film", 2021)[0]["id"])[0]
        self.assertEqual(rel["link_count"], 2)


class RollupAndSafetyTests(ProjectionTestCase):
    def test_projection_is_idempotent_and_rebuildable(self):
        self.add_post("site-a", "https://a.test/steady-film/", clean_title="Steady Film",
                      year=2019, releases=[
                          {"release_title": "Steady Film 1080p", "quality": "1080p",
                           "sources": [LinkTruthTests.src(
                               LinkTruthTests, "cdn", "https://video-downloads.googleusercontent.com/S")]}])
        first = self.project()
        before = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("cat_works", "cat_releases", "cat_links", "cat_seasons")}
        second = catalog_v2.project(self.conn, rev=2, verbose=False)
        after = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("cat_works", "cat_releases", "cat_links", "cat_seasons")}
        self.assertEqual(before, after)
        self.assertEqual(first["releases"], second["releases"])
        self.assertEqual(first["links"], second["links"])

    def test_identical_release_rows_collapse_but_links_survive(self):
        self.add_post("site-a", "https://a.test/mirror-film/", clean_title="Mirror Film",
                      year=2020, releases=[
                          {"release_title": "Mirror Film 720p", "quality": "720p",
                           "sources": [LinkTruthTests.src(
                               LinkTruthTests, "a", "https://video-downloads.googleusercontent.com/A")]},
                          {"release_title": "Mirror Film 720p", "quality": "720p",
                           "sources": [LinkTruthTests.src(
                               LinkTruthTests, "b", "https://video-downloads.googleusercontent.com/B")]},
                      ])
        summary = self.project()
        rels = self.releases(self.works("Mirror Film", 2020)[0]["id"])
        self.assertEqual(len(rels), 1)
        self.assertEqual(summary["release_dups"], 1)
        self.assertEqual(rels[0]["link_count"], 2)

    def test_adult_work_is_flagged_for_display_filtering(self):
        self.add_post("site-a", "https://a.test/adult-film/", clean_title="Adult Film",
                      year=2024, is_18_plus=1)
        self.project()
        self.assertEqual(self.works("Adult Film", 2024)[0]["is_18_plus"], 1)

    def test_animated_is_typed_as_anime(self):
        self.add_post("site-a", "https://a.test/toon-show/", clean_title="Toon Show",
                      year=2024, content_type="series", is_animated=1)
        self.project()
        self.assertEqual(self.works("Toon Show", 2024)[0]["work_type"], "anime")

    def test_every_work_gets_a_default_free_entitlement(self):
        self.add_post("site-a", "https://a.test/free-film/", clean_title="Free Film", year=2023)
        self.project()
        row = _row(self.conn,
                   "SELECT model, ownership FROM cat_entitlements WHERE work_id = (SELECT id FROM cat_works WHERE title='Free Film')")
        self.assertEqual((row["model"], row["ownership"]), ("free", "permanent"))

    def test_best_release_is_chosen_from_streamable_prints_only(self):
        self.add_post("site-a", "https://a.test/one-show/", clean_title="One Show",
                      year=2021, content_type="series", releases=[
                          {"release_title": "One Show S01E01 4K BluRay", "season": "1",
                           "episode": "1", "quality": "2160p",
                           "sources": [LinkTruthTests.src(
                               LinkTruthTests, "c", "https://video-downloads.googleusercontent.com/HQ")]},
                          {"release_title": "One Show S01E01 CAM", "season": "1", "episode": "1",
                           "quality": "480p",
                           "sources": [LinkTruthTests.src(
                               LinkTruthTests, "c", "https://video-downloads.googleusercontent.com/LQ")]},
                      ])
        self.project()
        work = self.works("One Show", 2021)[0]
        episode = _row(self.conn,
                       "SELECT * FROM cat_episodes WHERE work_id = ? AND number = 1", work["id"])
        best = self.conn.execute("SELECT label FROM cat_releases WHERE id = ?",
                                 (episode["best_release_id"],)).fetchone()[0]
        self.assertIn("4K", best)
        self.assertEqual(episode["absolute_number"], 1)

    def test_offset_ledger_survives_a_rebuild(self):
        """Learned pack offsets are operator data: re-projecting must not lose them."""
        self.add_post("site-a", "https://a.test/batch-show/", clean_title="Batch Show",
                      year=2019, content_type="series", releases=[
                          {"release_title": "Batch Show E1-E3", "season": "1",
                           "episode": "1-3", "quality": "720p"}])
        self.project()
        work = self.works("Batch Show", 2019)[0]
        work_key = work["work_key"]
        catalog_v2.record_offset(self.conn, work_key=work_key, season_number=1,
                                 episode_number=2, offset_seconds=1400,
                                 release_label="", chapter_title="Episode 2")
        catalog_v2.project(self.conn, rev=2, verbose=False)
        rows = self.conn.execute(
            """
            SELECT re.offset_seconds, re.chapter_title FROM cat_release_episodes re
            JOIN cat_releases r ON r.id = re.release_id
            JOIN cat_episodes e ON e.id = re.episode_id
            WHERE r.work_id = (SELECT id FROM cat_works WHERE work_key = ?) AND e.number = 2
            """, (work_key,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["offset_seconds"], 1400)
        self.assertEqual(rows[0]["chapter_title"], "Episode 2")

    def test_repeated_offset_report_confirms_instead_of_multiplying(self):
        self.add_post("site-a", "https://a.test/twice-show/", clean_title="Twice Show",
                      year=2019, content_type="series", releases=[
                          {"release_title": "Twice Show E1-E2", "season": "1",
                           "episode": "1-2", "quality": "720p"}])
        self.project()
        key = self.works("Twice Show", 2019)[0]["work_key"]
        for _ in range(3):
            catalog_v2.record_offset(self.conn, work_key=key, season_number=1,
                                     episode_number=1, offset_seconds=900)
        row = _row(self.conn,
                   "SELECT offset_seconds, confirmed_by FROM cat_offsets WHERE work_key = ?", key)
        self.assertEqual(row["offset_seconds"], 900)
        self.assertEqual(row["confirmed_by"], 3)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_offsets WHERE work_key = ?", (key,)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
