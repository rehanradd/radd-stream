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
import time
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

import catalog_v2
import fast_fetch
import link_health
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


    def test_counts_are_the_links_that_exist_including_a_print_with_none(self):
        """The roll-up is a grouped pass over `cat_links`, not a per-print subquery.

        Two things that rewrite could silently break: a print with no links keeps its
        NOT NULL DEFAULT 0 instead of being left unstamped, and the streamable /
        downloadable partition is exactly what the link rows say (a `both` link counts
        in each, a `resolve_required` only in downloadable).
        """
        self.add_post("site-a", "https://a.test/counted-film/", clean_title="Counted Film",
                      year=2022, releases=[
                          {"release_title": "Counted Film 1080p", "quality": "1080p",
                           "sources": [self.src("cdn", "https://video-downloads.googleusercontent.com/S1"),
                                       self.src("cdn", "https://video-downloads.googleusercontent.com/S2"),
                                       self.src("dl", "https://download.test/f.bin")]},
                          {"release_title": "Counted Film 480p", "quality": "480p",
                           "sources": []},
                      ])
        self.project()
        for rel in self.releases(self.works("Counted Film", 2022)[0]["id"]):
            rows = self.conn.execute(
                "SELECT playability FROM cat_links WHERE release_id = ?",
                (rel["id"],)).fetchall()
            playable = [r[0] for r in rows]
            self.assertEqual(
                rel["link_count"], len(playable),
                f"{rel['label']}: link_count must be the links that exist")
            self.assertEqual(
                rel["streamable_count"],
                sum(1 for p in playable if p in ("stream", "both")))
            self.assertEqual(
                rel["downloadable_count"],
                sum(1 for p in playable if p in ("download", "both", "resolve_required")))
        labels = {rel["label"]: rel for rel in self.releases(self.works("Counted Film", 2022)[0]["id"])}
        bare = [rel for rel in labels.values() if rel["link_count"] == 0]
        self.assertTrue(bare, "the source-less 480p print must exist with zero links")
        self.assertEqual(bare[0]["streamable_count"], 0)
        self.assertEqual(bare[0]["downloadable_count"], 0)


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


class EvidenceWriteBackTests(ProjectionTestCase):
    """`apply_evidence()` folds measured probes onto `cat_links` (§6.2, gap G-7).

    Every case here is about the honest direction of travel: a link's row must
    carry what a probe actually saw — never what the projector guessed — and must
    never disappear because the measurement came back bad.
    """

    CDN = "https://video-downloads.googleusercontent.com/"

    def src(self, url, **kw):
        return {"source_name": "g", "service": kw.get("service", "google_cdn"),
                "resource_id": "x", "source_url": url,
                "final_url": kw.get("final_url", url),
                "playback_type": kw.get("playback_type", "direct"),
                "is_temporary": kw.get("is_temporary", 0), "status": "active"}

    def film(self, title, urls, **kw):
        """Project one movie whose print has exactly `urls` links, in order."""
        year = kw.pop("year", 2024)
        self.add_post("site-a", f"https://a.test/{title.lower().replace(' ', '-')}/",
                      clean_title=title, year=year, releases=[
                          {"release_title": f"{title} 1080p", "quality": "1080p",
                           "sources": [self.src(url) for url in urls]}], **kw)
        self.project()
        return self.conn.execute(
            "SELECT * FROM cat_links WHERE work_id = (SELECT id FROM cat_works WHERE title = ?)"
            " ORDER BY id", (title,)).fetchall()

    def probe(self, url, **kw):
        ok = kw.pop("ok", True)
        kw.setdefault("protocol", "progressive" if ok else "unusable")
        kw.setdefault("http_status", 206 if ok else 404)
        if ok:
            kw.setdefault("content_type", "video/mp4")
            kw.setdefault("size_bytes", 750000000)
            kw.setdefault("streamable", True)
            kw.setdefault("downloadable", True)
        else:
            kw.setdefault("error", f"http_{kw['http_status']}")
        return link_health.ProbeResult(
            url=url, ok=ok, latency_ms=kw.pop("latency_ms", 100),
            download_speed_mbps=kw.pop("speed", 12.0),
            accepts_ranges=kw.pop("accepts_ranges", True),
            resumable=kw.pop("resumable", ok),
            cors_open=kw.pop("cors_open", True),
            checked_at=kw.pop("checked_at", 1000.0), **kw)

    def link_row(self, link_id):
        return _row(self.conn, "SELECT * FROM cat_links WHERE id = ?", link_id)

    def meta(self, key):
        row = self.conn.execute("SELECT value FROM cat_projection_meta WHERE key = ?",
                                 (key,)).fetchone()
        return row["value"] if row else None

    # ---- the prior, and what measurement replaces --------------------------- #
    def test_no_evidence_leaves_the_structural_prior_untouched(self):
        links = self.film("Prior Film", [self.CDN + "P"])
        before = dict(self.link_row(links[0]["id"]))
        summary = catalog_v2.apply_evidence(self.conn)
        self.assertEqual(summary["links_scanned"], 0)
        self.assertEqual(summary["links_updated"], 0)
        self.assertEqual(dict(self.link_row(links[0]["id"])), before)
        self.assertIsNone(before["latency_ms"])
        self.assertIsNone(before["last_evidence_at"])
        self.assertEqual(before["state"], "unchecked")
        self.assertEqual(self.meta("health"), "0")   # rev exists, and says "nothing measured"

    def test_one_good_probe_makes_the_link_measured_and_outrank_its_prior(self):
        links = self.film("Live Film", [self.CDN + "G"])
        link_id = links[0]["id"]
        prior = links[0]["rank_score"]
        probe = self.probe(self.CDN + "G", latency_ms=100, speed=12.0, checked_at=1500.0)
        summary = catalog_v2.apply_evidence(self.conn, [probe])
        row = self.link_row(link_id)
        self.assertEqual(summary["links_updated"], 1)
        self.assertEqual(summary["measured_links"], 1)
        self.assertEqual(summary["evidence_added"], 1)
        self.assertGreater(row["rank_score"], prior)
        self.assertEqual(row["rank_score"], link_health.score_link(
            probe, service_tier=row["tier"], is_temporary=row["ephemeral"]))
        self.assertEqual(row["state"], "active")
        self.assertEqual((row["latency_ms"], row["speed_mbps"]), (100, 12.0))
        self.assertEqual((row["accepts_ranges"], row["resumable"], row["cors_open"]),
                         (1, 1, 1))
        self.assertEqual(row["http_status"], 206)
        self.assertEqual(row["content_type"], "video/mp4")
        self.assertEqual(row["size_bytes"], 750000000)
        self.assertEqual(row["last_evidence_at"], 1500.0)
        self.assertEqual(self.meta("health"), "1")   # §16.2: the health group moved
        self.assertEqual(json.loads(self.meta("links_by_state")), {"active": 1})

    def test_measured_dead_link_sinks_below_a_live_peer_and_survives(self):
        links = self.film("Pair Film", [self.CDN + "LIVE", self.CDN + "DEAD"])
        good, bad = links[0]["id"], links[1]["id"]
        catalog_v2.apply_evidence(self.conn, [
            self.probe(self.CDN + "LIVE", checked_at=1000.0),
            self.probe(self.CDN + "DEAD", ok=False, http_status=503, latency_ms=0,
                       speed=0.0, accepts_ranges=False, resumable=False, cors_open=False,
                       checked_at=1000.0),
        ])
        live, dead = self.link_row(good), self.link_row(bad)
        self.assertEqual((live["state"], dead["state"]), ("active", "dead"))
        self.assertEqual(dead["rank_score"], 0)
        self.assertGreater(live["rank_score"], dead["rank_score"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_links").fetchone()[0], 2)   # never dropped
        self.assertEqual(self.link_row(bad)["http_status"], 503)

    def test_403_is_token_rot_not_death(self):
        links = self.film("Rot Film", [self.CDN + "ROT"])
        catalog_v2.apply_evidence(self.conn, [
            self.probe(self.CDN + "ROT", ok=False, http_status=403, latency_ms=90,
                       speed=0.0, accepts_ranges=False, resumable=False)])
        row = self.link_row(links[0]["id"])
        self.assertEqual(row["state"], "expired")
        self.assertEqual(row["rank_score"], 0)
        self.assertEqual(row["http_status"], 403)

    def test_aged_evidence_never_marks_a_link_dead(self):
        """Years old is stale, not dead: only a measured failure changes state."""
        links = self.film("Old Film", [self.CDN + "A", self.CDN + "B"])
        old, fresh = links[0]["id"], links[1]["id"]
        catalog_v2.apply_evidence(self.conn, [
            self.probe(self.CDN + "A", checked_at=1000.0),           # 1970
            self.probe(self.CDN + "B", checked_at=time.time()),
        ])
        self.assertEqual(self.link_row(old)["state"], "active")
        self.assertEqual(self.link_row(fresh)["state"], "active")
        self.assertGreater(self.link_row(old)["rank_score"], 0)
        self.assertEqual(self.link_row(old)["last_evidence_at"], 1000.0)

    def test_refused_probe_is_not_a_verdict(self):
        links = self.film("Guard Film", [self.CDN + "SEC"])
        before = dict(self.link_row(links[0]["id"]))
        summary = catalog_v2.apply_evidence(self.conn, [self.probe(
            self.CDN + "SEC", ok=False, http_status=0, protocol="unusable",
            error="blocked_target", latency_ms=0, speed=0.0, accepts_ranges=False,
            resumable=False, cors_open=False)])
        row = self.link_row(links[0]["id"])
        self.assertEqual(summary["links_updated"], 0)
        self.assertEqual(row["state"], before["state"])
        self.assertEqual(row["rank_score"], before["rank_score"])
        self.assertIsNone(row["last_evidence_at"])
        self.assertEqual(summary["evidence_added"], 1)   # journaled, just not a verdict

    def test_client_report_without_a_probe_keeps_the_prior_scale(self):
        links = self.film("Played Film", [self.CDN + "RPT"])
        self.conn.execute(
            "INSERT INTO cat_link_evidence (link_id, probed_at, ok, latency_ms, error)"
            " VALUES (?, ?, 1, 55, NULL)", (links[0]["id"], 2000.0))
        summary = catalog_v2.apply_evidence(self.conn)
        row = self.link_row(links[0]["id"])
        self.assertEqual(summary["measured_links"], 0)
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["latency_ms"], 55)
        self.assertEqual(row["last_evidence_at"], 2000.0)
        # the prior ladder, with the state the report just earned: 500+150+100+100
        self.assertEqual(row["rank_score"], 850)
        self.assertNotEqual(row["rank_score"], links[0]["rank_score"])

    # ---- the rolling blend -------------------------------------------------- #
    def test_ewma_blends_two_samples_the_documented_way(self):
        links = self.film("Flap Film", [self.CDN + "EW"])
        link_id = links[0]["id"]
        catalog_v2.apply_evidence(self.conn, [self.probe(
            self.CDN + "EW", latency_ms=100, speed=12.0, checked_at=1000.0)])
        first = self.link_row(link_id)
        catalog_v2.apply_evidence(self.conn, [self.probe(
            self.CDN + "EW", latency_ms=300, speed=4.0, checked_at=2000.0)])
        second = self.link_row(link_id)
        self.assertEqual(first["latency_ms"], 100)                 # seeds the record
        self.assertEqual(second["latency_ms"], 180)                # 100*.6 + 300*.4
        self.assertAlmostEqual(second["speed_mbps"], 8.8, places=4)  # 12*.6 + 4*.4
        self.assertEqual(second["last_evidence_at"], 2000.0)
        # a timeout measures no timing at all, so the blend must not average a fake 0 in
        catalog_v2.apply_evidence(self.conn, [self.probe(
            self.CDN + "EW", ok=False, http_status=0, error="timeout", latency_ms=0,
            speed=0.0, accepts_ranges=False, resumable=False, cors_open=False,
            checked_at=3000.0)])
        third = self.link_row(link_id)
        self.assertEqual(third["latency_ms"], 180)
        self.assertAlmostEqual(third["speed_mbps"], 8.8, places=4)
        self.assertEqual(third["state"], "dead")
        self.assertEqual(third["rank_score"], 0)

    def test_rolling_state_follows_the_newest_verdict_not_the_majority(self):
        links = self.film("Recover Film", [self.CDN + "RC"])
        link_id = links[0]["id"]
        for checked, ok in ((1000.0, True), (2000.0, False), (3000.0, True)):
            catalog_v2.apply_evidence(self.conn, [self.probe(
                self.CDN + "RC", ok=ok, http_status=206 if ok else 500,
                latency_ms=100, checked_at=checked)])
            state = self.link_row(link_id)["state"]
            self.assertEqual(state, "active" if ok else "dead")
        # and a replay of the whole journal from scratch lands on the same answer
        catalog_v2.ensure_schema(self.conn)
        rebuilt = catalog_v2.apply_evidence(self.conn, link_ids=[link_id])
        self.assertEqual(rebuilt["links_updated"], 0)

    # ---- idempotency -------------------------------------------------------- #
    def test_re_running_the_write_back_is_a_no_op(self):
        links = self.film("Steady Film", [self.CDN + "ST", self.CDN + "ST2"])
        catalog_v2.apply_evidence(self.conn, [
            self.probe(self.CDN + "ST", checked_at=1000.0),
            self.probe(self.CDN + "ST2", ok=False, http_status=410, latency_ms=0,
                       speed=0.0, accepts_ranges=False, resumable=False,
                       cors_open=False, checked_at=1000.0)])
        snapshot = [dict(row) for row in self.conn.execute(
            "SELECT * FROM cat_links ORDER BY id")]
        health, health_at, journal = (self.meta("health"), self.meta("health_at"),
                                      self.conn.execute(
                                          "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0])
        for _ in range(2):
            again = catalog_v2.apply_evidence(self.conn)
            self.assertEqual(again["links_updated"], 0)
            self.assertEqual(again["evidence_added"], 0)
            self.assertFalse(again["health_bumped"])
        self.assertEqual([dict(row) for row in self.conn.execute(
            "SELECT * FROM cat_links ORDER BY id")], snapshot)
        self.assertEqual(self.meta("health"), health)
        self.assertEqual(self.meta("health_at"), health_at)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_link_evidence").fetchone()[0], journal)

    def test_replaying_the_same_probe_does_not_double_the_journal(self):
        links = self.film("Replay Film", [self.CDN + "RP"])
        probe = self.probe(self.CDN + "RP", checked_at=1000.0)
        catalog_v2.apply_evidence(self.conn, [probe])
        second = catalog_v2.apply_evidence(self.conn, [probe])
        self.assertEqual(second["evidence_added"], 0)
        self.assertEqual(second["evidence_rows"], 1)
        self.assertEqual(second["links_updated"], 0)

    # ---- association -------------------------------------------------------- #
    def test_evidence_is_reattached_to_the_link_its_url_names(self):
        """A rebuild renumbers `cat_links`; the URL in the sample is the durable half."""
        links = self.film("Moved Film", [self.CDN + "M1", self.CDN + "M2"])
        right, wrong = links[0]["id"], links[1]["id"]
        self.conn.execute(
            "INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, http_status,"
            " content_type, size_bytes, latency_ms, speed_mbps, accepts_ranges, error, url)"
            " VALUES (?, ?, 1, 'progressive', 200, 'video/mp4', 1200, 140, 6.5, 1, NULL, ?)",
            (wrong, 4000.0, self.CDN + "M1"))
        summary = catalog_v2.apply_evidence(self.conn)
        self.assertEqual(summary["evidence_repointed"], 1)
        healed = self.link_row(right)
        self.assertEqual((healed["state"], healed["latency_ms"], healed["last_evidence_at"]),
                         ("active", 140, 4000.0))
        untouched = self.link_row(wrong)
        self.assertEqual(untouched["state"], "unchecked")
        self.assertIsNone(untouched["last_evidence_at"])
        self.assertEqual(self.conn.execute(
            "SELECT link_id FROM cat_link_evidence WHERE url = ?",
            (self.CDN + "M1",)).fetchone()[0], right)

    def test_sample_of_an_unknown_url_is_reported_not_applied(self):
        links = self.film("Ghost Film", [self.CDN + "GHOST"])
        self.conn.execute(
            "INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, latency_ms, url)"
            " VALUES (?, ?, 0, 'unusable', 0, 'https://gone.test/nothing')",
            (links[0]["id"], 5000.0))
        summary = catalog_v2.apply_evidence(self.conn)
        self.assertEqual(summary["evidence_orphaned"], 1)
        self.assertEqual(summary["links_updated"], 0)
        self.assertEqual(self.link_row(links[0]["id"])["state"], "unchecked")

    def test_link_ids_scope_and_limit_reach_every_link(self):
        links = self.film("Many Film", [self.CDN + str(i) for i in range(6)])
        probes = [self.probe(link["url"], checked_at=1000.0 + index)
                  for index, link in enumerate(links)]
        catalog_v2.apply_evidence(self.conn, probes)
        for index in (0, 3, 5):
            self.assertEqual(self.link_row(links[index]["id"])["state"], "active")
        only = catalog_v2.apply_evidence(self.conn, link_ids=[links[2]["id"]])
        self.assertEqual(only["links_scanned"], 1)
        limited = catalog_v2.apply_evidence(self.conn, limit=2)
        self.assertLessEqual(limited["links_scanned"], 2)

    def test_write_back_opens_no_socket_and_needs_no_ledger_helpers(self):
        links = self.film("Offline Film", [self.CDN + "OFF"])
        link_id = links[0]["id"]
        self.conn.execute(
            "INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, http_status,"
            " latency_ms, speed_mbps, accepts_ranges) VALUES (?, ?, 1, 'progressive', 200,"
            " 80, 3.0, 1)", (link_id, 6000.0))

        def boom(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("apply_evidence() must not probe the network")

        with unittest.mock.patch.object(link_health, "probe", boom), \
                unittest.mock.patch.object(link_health, "probe_many", boom):
            summary = catalog_v2.apply_evidence(self.conn)
        self.assertEqual(summary["links_updated"], 1)
        self.assertEqual(self.link_row(link_id)["state"], "active")

    def test_works_on_a_projection_written_by_an_older_schema(self):
        """No `ledger_link_id`, no `url` on the journal, default tuple rows: still applies.

        Also pins the migration hazard: the extra column is added by its own ALTER
        and never indexed inside the DDL script that created the table.
        """
        conn = sqlite3.connect(":memory:")   # deliberately not sqlite3.Row
        try:
            conn.executescript("""
            CREATE TABLE cat_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT, release_id INTEGER NOT NULL,
                work_id INTEGER NOT NULL, url TEXT, final_url TEXT,
                kind TEXT, playability TEXT, state TEXT NOT NULL DEFAULT 'unchecked',
                resumable INTEGER NOT NULL DEFAULT 0, accepts_ranges INTEGER NOT NULL DEFAULT 0,
                cors_open INTEGER NOT NULL DEFAULT 0, ephemeral INTEGER NOT NULL DEFAULT 0,
                expires_at REAL, protocol TEXT, content_type TEXT, size_bytes INTEGER,
                latency_ms INTEGER, speed_mbps REAL, http_status INTEGER,
                last_evidence_at REAL, rank_score INTEGER NOT NULL DEFAULT 0,
                tier INTEGER NOT NULL DEFAULT 2);
            CREATE TABLE cat_link_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT, link_id INTEGER NOT NULL,
                probed_at REAL NOT NULL, ok INTEGER NOT NULL, protocol TEXT,
                http_status INTEGER, content_type TEXT, size_bytes INTEGER,
                latency_ms INTEGER, speed_mbps REAL, accepts_ranges INTEGER, error TEXT);
            CREATE TABLE cat_projection_meta (key TEXT PRIMARY KEY, value TEXT);
            """)
            conn.execute("INSERT INTO cat_links (id, release_id, work_id, url, final_url,"
                         " kind, playability, rank_score, tier)"
                         " VALUES (7, 1, 1, 'https://cdn.test/old.mp4',"
                         " 'https://cdn.test/old.mp4', 'cdn_direct', 'stream', 750, 1)")
            conn.execute("INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol,"
                         " http_status, content_type, size_bytes, latency_ms, speed_mbps,"
                         " accepts_ranges) VALUES (7, 7000.0, 1, 'progressive', 206,"
                         " 'video/mp4', 4000, 60, 20.0, 1)")
            summary = catalog_v2.apply_evidence(conn, commit=True)
            self.assertEqual(summary["links_updated"], 1)
            row = conn.execute("SELECT state, rank_score, latency_ms, speed_mbps,"
                               " last_evidence_at, cors_open FROM cat_links"
                               " WHERE id = 7").fetchone()
            self.assertEqual(row[0], "active")
            # 300 stream + 150 download + 100 ranges + 0 CORS + 100 speed + 100 latency
            # + 100 tier1 = 850: the measured formula, minus the 80 we refuse to invent.
            self.assertEqual(row[1], 850)
            self.assertEqual((row[2], row[3], row[4]), (60, 20.0, 7000.0))
            self.assertEqual(row[5], 0)            # no CORS fact in the journal: not invented
            columns = {r[1] for r in conn.execute("PRAGMA table_info(cat_link_evidence)")}
            self.assertIn("url", columns)          # migrated in, and not indexed
            health = conn.execute("SELECT value FROM cat_projection_meta"
                                  " WHERE key = 'health'").fetchone()[0]
            self.assertEqual(health, "1")
            # a CORS fact from a live probe is the only thing that lifts it further
            conn.execute("INSERT INTO cat_links (id, release_id, work_id, url, final_url,"
                         " kind, playability, rank_score, tier)"
                         " VALUES (8, 1, 1, 'https://cdn.test/cors.mp4',"
                         " 'https://cdn.test/cors.mp4', 'cdn_direct', 'stream', 750, 1)")
            catalog_v2.apply_evidence(conn, [link_health.ProbeResult(
                url="https://cdn.test/cors.mp4", ok=True, protocol="progressive",
                http_status=206, content_type="video/mp4", size_bytes=4000,
                streamable=True, downloadable=True, accepts_ranges=True, resumable=True,
                cors_open=True, latency_ms=60, download_speed_mbps=20.0, checked_at=7000.0)])
            self.assertEqual(conn.execute(
                "SELECT rank_score, cors_open FROM cat_links WHERE id = 8").fetchone(),
                (930, 1))                          # score_link's documented practical ceiling
        finally:
            conn.close()

    def test_needs_a_projected_database(self):
        conn = sqlite3.connect(":memory:")
        try:
            with self.assertRaises(ValueError):
                catalog_v2.apply_evidence(conn)
        finally:
            conn.close()

    # ---- adult and provenance posture -------------------------------------- #
    def test_adult_links_are_healed_like_any_other_and_no_provenance_leaks(self):
        adult = self.film("Adult Title", [self.CDN + "ADT"], is_18_plus=1)
        public = self.film("Public Title", [self.CDN + "PUB"])
        link_ids = [adult[0]["id"], public[0]["id"]]
        summary = catalog_v2.apply_evidence(self.conn, [
            self.probe(self.CDN + "ADT", checked_at=1000.0),
            self.probe(self.CDN + "PUB", checked_at=1000.0)])
        for link_id in link_ids:
            self.assertEqual(self.link_row(link_id)["state"], "active")
        # the flag and the row are untouched: measurement changes state, never visibility
        self.assertEqual(self.conn.execute(
            "SELECT is_18_plus FROM cat_works WHERE title = 'Adult Title'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM cat_links").fetchone()[0], 2)
        text = json.dumps(summary, sort_keys=True)
        for leak in ("site-a", "google_cdn", "a.test", "video-downloads", "source_site",
                     "service", "url", "final_url", "Adult"):
            self.assertNotIn(leak, text)


class RevisionVectorTests(ProjectionTestCase):
    """§16.2: four monotonic version groups, each moved only by its own writer."""

    CDN = "https://video-downloads.googleusercontent.com/"

    def src(self, url):
        return {"source_name": "g", "service": "google_cdn", "resource_id": "x",
                "source_url": url, "final_url": url, "playback_type": "direct",
                "is_temporary": 0, "status": "active"}

    def batch_series(self, title="Sync Beats"):
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=2020, content_type="series", releases=[
                          {"release_title": f"{title} S01E1-E2", "season": "1",
                           "episode": "1-2", "quality": "720p",
                           "sources": [self.src(self.CDN + title.replace(' ', '-'))]}])
        self.project()
        return self.works(title, 2020)[0]

    def test_projection_versions_has_every_key_zero_before_any_projection(self):
        versions = catalog_v2.projection_versions(self.conn)
        self.assertEqual(set(versions), set(catalog_v2.REVISION_KEYS))
        self.assertEqual(versions, {"catalog_rev": 0, "health_rev": 0,
                                    "offsets_rev": 0, "entitlements_rev": 0})

    def test_unchanged_rebuild_bumps_catalog_rev_and_nothing_else(self):
        self.batch_series()
        first = catalog_v2.projection_versions(self.conn)
        self.assertEqual(first["catalog_rev"], 1)
        summary = catalog_v2.project(self.conn, rev=1, verbose=False)
        second = catalog_v2.projection_versions(self.conn)
        self.assertEqual(second["catalog_rev"], first["catalog_rev"] + 1)
        self.assertEqual(summary["catalog_rev"], second["catalog_rev"])
        for key in ("health_rev", "offsets_rev", "entitlements_rev"):
            self.assertEqual(second[key], first[key])

    def test_offset_report_bumps_offsets_rev_and_nothing_else(self):
        work = self.batch_series("Offset Beats")
        before = catalog_v2.projection_versions(self.conn)
        catalog_v2.record_offset(self.conn, work_key=work["work_key"], season_number=1,
                                 episode_number=1, offset_seconds=800)
        after = catalog_v2.projection_versions(self.conn)
        self.assertEqual(after["offsets_rev"], before["offsets_rev"] + 1)
        for key in ("catalog_rev", "health_rev", "entitlements_rev"):
            self.assertEqual(after[key], before[key])

    def test_entitlement_edit_bumps_entitlements_rev_and_nothing_else(self):
        work = self.batch_series("Paid Beats")
        before = catalog_v2.projection_versions(self.conn)
        catalog_v2.set_entitlement(self.conn, work_key=work["work_key"],
                                   model="rental", price_minor=1500)
        after = catalog_v2.projection_versions(self.conn)
        self.assertEqual(after["entitlements_rev"], before["entitlements_rev"] + 1)
        for key in ("catalog_rev", "health_rev", "offsets_rev"):
            self.assertEqual(after[key], before[key])

    def test_evidence_apply_bumps_health_rev_and_nothing_else(self):
        work = self.batch_series("Measured Beats")
        link = self.conn.execute(
            "SELECT id, url FROM cat_links WHERE work_id = ?", (work["id"],)).fetchone()
        before = catalog_v2.projection_versions(self.conn)
        probe = link_health.ProbeResult(url=link["url"], ok=True, protocol="progressive",
                                        http_status=206, content_type="video/mp4",
                                        size_bytes=500000000, latency_ms=80,
                                        download_speed_mbps=9.0, accepts_ranges=True,
                                        resumable=True, cors_open=True, checked_at=1000.0)
        catalog_v2.apply_evidence(self.conn, [probe])
        after = catalog_v2.projection_versions(self.conn)
        self.assertEqual(after["health_rev"], 1)
        for key in ("catalog_rev", "offsets_rev", "entitlements_rev"):
            self.assertEqual(after[key], before[key])


class IdMapTests(ProjectionTestCase):
    """§3/A2: ids still churn on rebuild, but every renumbering is journalled."""

    CDN = "https://video-downloads.googleusercontent.com/"

    def src(self, tag):
        return {"source_name": "g", "service": "google_cdn", "resource_id": tag,
                "source_url": f"{self.CDN}{tag}", "final_url": f"{self.CDN}{tag}",
                "playback_type": "direct", "is_temporary": 0, "status": "active"}

    def test_rebuild_journals_renumbered_release_and_link_ids(self):
        self.add_post("site-a", "https://a.test/first-film/", clean_title="First Film",
                      year=2020, releases=[
                          {"release_title": "First Film 1080p", "quality": "1080p",
                           "sources": [self.src("F1")]}])
        self.add_post("site-a", "https://a.test/second-film/", clean_title="Second Film",
                      year=2021, releases=[
                          {"release_title": "Second Film 1080p", "quality": "1080p",
                           "sources": [self.src("S1")]}])
        self.project()
        old_release = self.conn.execute(
            "SELECT r.id FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
            " WHERE w.title = 'Second Film'").fetchone()[0]
        old_link = self.conn.execute(
            "SELECT l.id FROM cat_links l JOIN cat_releases r ON r.id = l.release_id"
            " JOIN cat_works w ON w.id = r.work_id WHERE w.title = 'Second Film'").fetchone()[0]
        # a second print on the FIRST work shifts every later row's id by one
        self.add_post("site-b", "https://b.test/first-film-4k/", clean_title="First Film",
                      year=2020, releases=[
                          {"release_title": "First Film 4K", "quality": "2160p",
                           "sources": [self.src("F2")]}])
        summary = catalog_v2.project(self.conn, rev=2, verbose=False)
        new_release = self.conn.execute(
            "SELECT r.id FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
            " WHERE w.title = 'Second Film'").fetchone()[0]
        new_link = self.conn.execute(
            "SELECT l.id FROM cat_links l JOIN cat_releases r ON r.id = l.release_id"
            " JOIN cat_works w ON w.id = r.work_id WHERE w.title = 'Second Film'").fetchone()[0]
        self.assertNotEqual(old_release, new_release)
        self.assertNotEqual(old_link, new_link)
        for kind, old, new in (("release", old_release, new_release),
                               ("link", old_link, new_link)):
            row = _row(self.conn,
                       "SELECT * FROM cat_id_map WHERE kind = ? AND old_id = ?", kind, old)
            self.assertIsNotNone(row, f"{kind} id churn not journalled")
            self.assertEqual(row["new_id"], new)
            self.assertEqual(row["rev"], summary["catalog_rev"])
        # works kept their order — nothing journalled that did not move
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_id_map WHERE kind = 'work'").fetchone()[0], 0)
        self.assertEqual(summary["id_mapped"], 2)


class SeasonPackExpansionTests(ProjectionTestCase):
    """A3/G-2: a pack is enumerable exactly when the ledger says how long it is."""

    CDN = "https://video-downloads.googleusercontent.com/"

    def src(self, tag):
        return {"source_name": "g", "service": "google_cdn", "resource_id": tag,
                "source_url": f"{self.CDN}{tag}", "final_url": f"{self.CDN}{tag}",
                "playback_type": "direct", "is_temporary": 0, "status": "active"}

    def pack_post(self, title, label, extra_releases=(), tag="PACK"):
        releases = [{"release_title": label, "season": "1", "episode": "Batch",
                     "quality": "720p", "sources": [self.src(tag)]}]
        releases += list(extra_releases)
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=2021, content_type="series",
                      releases=releases)

    def test_pack_with_episode_count_hint_becomes_enumerable(self):
        self.pack_post("Harbor Lights", "Harbor Lights S01 Complete 12EP 720p")
        summary = self.project()
        work = self.works("Harbor Lights", 2021)[0]
        numbers = [e["number"] for e in self.conn.execute(
            "SELECT number FROM cat_episodes WHERE work_id = ? ORDER BY number",
            (work["id"],)).fetchall()]
        self.assertEqual(numbers, list(range(1, 13)))
        self.assertEqual(summary["episodes"], 12)
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["coverage_type"], "season_pack")
        linked = self.conn.execute(
            "SELECT COUNT(*) FROM cat_release_episodes WHERE release_id = ?",
            (rel["id"],)).fetchone()[0]
        self.assertEqual(linked, 12)
        # the pack is a streamable covering print, so it can be the best print
        best = self.conn.execute(
            "SELECT COUNT(*) FROM cat_episodes WHERE work_id = ? AND best_release_id = ?",
            (work["id"], rel["id"])).fetchone()[0]
        self.assertEqual(best, 12)

    def test_pack_without_any_span_data_stays_empty_and_queued(self):
        self.pack_post("Silent Waters", "Silent Waters S01 Complete 720p")
        self.project()
        work = self.works("Silent Waters", 2021)[0]
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_episodes WHERE work_id = ?",
            (work["id"],)).fetchone()[0], 0, "an unknowable span must not be invented")
        row = _row(self.conn,
                   "SELECT * FROM cat_review_queue WHERE kind = 'season_pack_span_unresolved'")
        self.assertIsNotNone(row)
        self.assertEqual(row["work_id"], work["id"])
        self.assertIsNotNone(row["release_id"], "the queue row must name the pack print")

    def test_pack_expands_only_beyond_the_episodes_already_projected(self):
        episodes = [{"release_title": f"Grid Runners S01E{n}", "season": "1",
                     "episode": str(n), "quality": "720p",
                     "sources": [self.src(f"GR{n}")]} for n in (1, 2, 3)]
        self.pack_post("Grid Runners", "Grid Runners S01 Complete 12EP 720p",
                       extra_releases=episodes, tag="GRP")
        self.project()
        work = self.works("Grid Runners", 2021)[0]
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_episodes WHERE work_id = ?",
            (work["id"],)).fetchone()[0], 12)
        pack = self.conn.execute(
            "SELECT id FROM cat_releases WHERE work_id = ? AND coverage_type = 'season_pack'",
            (work["id"],)).fetchone()[0]
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_release_episodes WHERE release_id = ?",
            (pack,)).fetchone()[0], 12)
        covering = self.conn.execute(
            """
            SELECT COUNT(DISTINCT re.release_id) FROM cat_release_episodes re
            JOIN cat_episodes e ON e.id = re.episode_id
            WHERE e.work_id = ? AND e.number = 1
            """, (work["id"],)).fetchone()[0]
        self.assertEqual(covering, 2, "episode 1 must be covered by its own print AND the pack")


class RepackTieBreakTests(ProjectionTestCase):
    """A7/§5.2: on a quality tie the fresher print wins — print_version DESC, id DESC."""

    CDN = "https://video-downloads.googleusercontent.com/"

    def src(self, tag):
        return {"source_name": "g", "service": "google_cdn", "resource_id": tag,
                "source_url": f"{self.CDN}{tag}", "final_url": f"{self.CDN}{tag}",
                "playback_type": "direct", "is_temporary": 0, "status": "active"}

    def test_equal_quality_newer_print_wins_best_release(self):
        self.add_post("site-a", "https://a.test/tide-line/", clean_title="Tide Line",
                      year=2022, content_type="series", releases=[
                          {"release_title": "Tide Line S01E01 720p WEB-DL x264 v1",
                           "season": "S01", "episode": "01", "quality": "720p",
                           "codec": "x264", "sources": [self.src("TIDE-V1")]},
                          {"release_title": "Tide Line S01E01 720p WEB-DL x264 v2",
                           "season": "S01", "episode": "01", "quality": "720p",
                           "codec": "x264", "sources": [self.src("TIDE-V2")]},
                      ])
        self.project()
        work = self.works("Tide Line", 2022)[0]
        first, second = self.releases(work["id"])
        self.assertEqual(first["quality_score"], second["quality_score"],
                         "fixture lost its tie — scores must be equal to prove the rule")
        self.assertGreater(second["print_version"], first["print_version"])
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertEqual(episode["best_release_id"], second["id"],
                         "the older v1 print won the tie (id ASC is reverted behaviour)")

    def test_full_print_tie_prefers_the_later_id_at_work_and_episode_level(self):
        self.add_post("site-a", "https://a.test/parity-line/", clean_title="Parity Line",
                      year=2022, content_type="series", releases=[
                          {"release_title": "Parity Line S01E01 720p WEBRip x265",
                           "season": "S01", "episode": "01", "quality": "720p",
                           "codec": "x265", "size": "800MB",
                           "sources": [self.src("PAR-A")]},
                          {"release_title": "Parity Line S01E01 480p BluRay x265 ESubs",
                           "season": "S01", "episode": "01", "quality": "480p",
                           "codec": "x265", "size": "800MB",
                           "sources": [self.src("PAR-B")]},
                      ])
        self.project()
        work = self.works("Parity Line", 2022)[0]
        first, second = self.releases(work["id"])
        self.assertEqual(first["quality_score"], second["quality_score"])
        self.assertEqual(first["print_version"], second["print_version"])
        self.assertLess(first["id"], second["id"])
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertEqual(episode["best_release_id"], second["id"],
                         "episode tie did not go id DESC")
        self.assertEqual(work["max_resolution"], second["resolution"],
                         "work max_resolution did not agree with the episode tiebreak")


class OffsetMajorityTests(ProjectionTestCase):
    """A8/§4.3: offsets publish by vote, so one wrong report cannot move playback."""

    def series(self, title="Late Beats"):
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=2021, content_type="series", releases=[
                          {"release_title": f"{title} S01E1-E2", "season": "1",
                           "episode": "1-2", "quality": "720p"}])
        self.project()
        return self.works(title, 2021)[0]["work_key"]

    def report(self, key, seconds):
        return catalog_v2.record_offset(self.conn, work_key=key, season_number=1,
                                        episode_number=1, offset_seconds=seconds)

    def published(self, key):
        return _row(self.conn,
                    "SELECT * FROM cat_offsets WHERE work_key = ?", key)

    def test_quorate_offset_survives_a_single_wrong_report(self):
        key = self.series("Quorum Beats")
        for _ in range(3):
            result = self.report(key, 900)
        self.assertEqual(result["confirmed_by"], 3)
        self.assertEqual(result["quorum"], catalog_v2.OFFSET_QUORUM)
        wrong = self.report(key, -200)
        self.assertEqual(wrong["offset_seconds"], 900,
                         "one dissent outvoted a quorate offset")
        row = self.published(key)
        self.assertEqual(row["offset_seconds"], 900)

    def test_strict_majority_flips_the_published_offset(self):
        key = self.flip_setup = self.series("Flip Beats")
        for _ in range(3):
            self.report(key, 900)
        for _ in range(3):
            self.assertEqual(self.report(key, -200)["offset_seconds"], 900)
        flipped = self.report(key, -200)
        self.assertEqual(flipped["offset_seconds"], -200, "4-3 majority did not flip")
        self.assertEqual(self.published(key)["offset_seconds"], -200)

    def test_equal_votes_keep_the_incumbent_instead_of_the_last_writer(self):
        key = self.series("Steady Beats")
        self.report(key, 900)
        tied = self.report(key, -200)
        self.assertEqual(tied["offset_seconds"], 900, "a 1-1 tie followed the last writer")
        self.report(key, 900)
        self.assertEqual(self.published(key)["offset_seconds"], 900)

    def test_legacy_confirmations_are_seeded_into_the_vote_ledger(self):
        key = self.series("Legacy Beats")
        self.conn.execute(
            "INSERT INTO cat_offsets (work_key, season_number, episode_number,"
            " release_label, offset_seconds, confirmed_by, updated_at)"
            " VALUES (?, 1, 1, '', 900, 3, ?)", (key, time.time()))
        self.conn.commit()
        result = self.report(key, -200)
        self.assertEqual(result["offset_seconds"], 900,
                         "pre-majority confirmations were not seeded as votes")

    def test_confirmation_only_report_does_not_bump_offsets_rev(self):
        key = self.series("Quiet Beats")
        self.report(key, 900)
        rev = catalog_v2.projection_versions(self.conn)["offsets_rev"]
        self.report(key, 900)
        self.assertEqual(catalog_v2.projection_versions(self.conn)["offsets_rev"], rev)


class ReviewQueueTests(ProjectionTestCase):
    """A9/S13: year and external-id conflicts queue for a human; resolutions stick."""

    CDN = "https://video-downloads.googleusercontent.com/"

    def src(self, tag):
        return {"source_name": "g", "service": "google_cdn", "resource_id": tag,
                "source_url": f"{self.CDN}{tag}", "final_url": f"{self.CDN}{tag}",
                "playback_type": "direct", "is_temporary": 0, "status": "active"}

    def test_close_years_without_external_ids_are_queued_as_year_conflict(self):
        self.add_post("site-a", "https://a.test/echo-falls-2023/",
                      clean_title="Echo Falls", year=2023)
        self.add_post("site-b", "https://b.test/echo-falls-2025/",
                      clean_title="Echo Falls", year=2025)
        self.project()
        rows = self.conn.execute(
            "SELECT * FROM cat_review_queue WHERE kind = 'year_conflict'").fetchall()
        self.assertEqual(len(rows), 2, "both sides of the conflict must be queued")
        for work in self.conn.execute(
                "SELECT * FROM cat_works WHERE title = 'Echo Falls'").fetchall():
            self.assertEqual(work["identity_suspect"], 1)

    def test_distant_years_are_not_a_year_conflict(self):
        self.add_post("site-a", "https://a.test/far-apart-2011/",
                      clean_title="Far Apart", year=2011)
        self.add_post("site-b", "https://b.test/far-apart-2024/",
                      clean_title="Far Apart", year=2024)
        self.project()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_review_queue WHERE kind = 'year_conflict'"
            " AND detail LIKE '%Far Apart%'").fetchone()[0], 0)

    def test_merged_alias_sharing_no_words_raises_external_id_conflict(self):
        self.add_post("site-a", "https://a.test/quantum-heist/",
                      clean_title="Quantum Heist", year=2023, imdb_id="tt9990001",
                      releases=[{"release_title": "Quantum Heist 1080p", "quality": "1080p"}])
        self.add_post("site-b", "https://b.test/desi-detective/",
                      clean_title="Desi Detective", year=2023, imdb_id="tt9990001",
                      releases=[{"release_title": "Desi Detective 1080p", "quality": "1080p"}])
        self.project()
        self.assertEqual(len(self.works("Quantum Heist", 2023)), 1)
        row = _row(self.conn,
                   "SELECT * FROM cat_review_queue WHERE kind = 'external_id_conflict'")
        self.assertIsNotNone(row, "an imdb merge with zero shared words must be reviewed")

    def test_ordinary_alias_does_not_raise_external_id_conflict(self):
        self.add_post("site-a", "https://a.test/quantum-heist/",
                      clean_title="Quantum Heist", year=2023, imdb_id="tt9990002",
                      releases=[{"release_title": "Quantum Heist 1080p", "quality": "1080p"}])
        self.add_post("site-b", "https://b.test/quantum-heist-hindi/",
                      clean_title="Quantum Heist", year=2023, imdb_id="tt9990002",
                      releases=[{"release_title": "Quantum Heist Hindi 1080p",
                                 "quality": "1080p"}])
        self.project()
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_review_queue WHERE kind = 'external_id_conflict'"
        ).fetchone()[0], 0)

    def test_suspect_print_is_excluded_until_a_cli_resolution_restores_it(self):
        self.add_post("site-a", "https://a.test/mystery-drops/",
                      clean_title="Mystery Drops", year=2022, content_type="series",
                      releases=[{"release_title": "Mystery Drops E02 720p", "season": "",
                                 "episode": "2", "quality": "720p",
                                 "sources": [self.src("MYST-E2")]}])
        self.project()
        work = self.works("Mystery Drops", 2022)[0]
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["identity_suspect"], 1)
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertIsNone(episode["best_release_id"],
                          "an unresolved suspect print must not serve anyone")
        queue = _row(self.conn,
                     "SELECT * FROM cat_review_queue WHERE kind = 'season_unresolved'"
                     " AND release_id = ?", rel["id"])
        self.assertIsNotNone(queue)
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            catalog_v2.main([str(self.db_path), "--resolve-review", str(queue["id"])])
        self.assertIsNotNone(self.conn.execute(
            "SELECT resolved_at FROM cat_review_queue WHERE id = ?",
            (queue["id"],)).fetchone()[0])
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertEqual(episode["best_release_id"], rel["id"],
                         "resolving the review must let the print win its episode back")
        # the decision sticks through a full rebuild — no re-suspecting, no re-queueing
        catalog_v2.project(self.conn, rev=2, verbose=False)
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["identity_suspect"], 0)
        queue = _row(self.conn,
                     "SELECT * FROM cat_review_queue WHERE kind = 'season_unresolved'"
                     " AND release_id = ?", rel["id"])
        self.assertIsNotNone(queue["resolved_at"],
                             "a resolved review re-opened itself on rebuild")
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertEqual(episode["best_release_id"], rel["id"])


class UnpopulatedColumnsTests(ProjectionTestCase):
    """A11/§4.2: episode/season/work columns carry exactly what the ledger says."""

    def series(self, title, releases, year=2020):
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=year, content_type="series",
                      releases=releases)
        self.project()
        return self.works(title, year)[0]

    def test_label_named_episode_facts_are_populated(self):
        work = self.series("Campus Beats", [
            {"release_title": "Campus Beats S01E02 Midterm Blues 2020-05-10 45min 1080p WEB-DL",
             "season": "S01", "episode": "02", "quality": "1080p"}])
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertEqual(episode["title"], "Midterm Blues")
        self.assertEqual(episode["air_date"], "2020-05-10")
        self.assertEqual(episode["runtime_minutes"], 45)

    def test_bare_label_leaves_the_columns_null(self):
        work = self.series("Quiet Beats", [
            {"release_title": "Quiet Beats S01E01 720p", "season": "1",
             "episode": "1", "quality": "720p"}])
        episode = _row(self.conn, "SELECT * FROM cat_episodes WHERE work_id = ?", work["id"])
        self.assertIsNone(episode["title"])
        self.assertIsNone(episode["air_date"])
        self.assertIsNone(episode["runtime_minutes"])

    def test_season_title_is_taken_from_the_label_that_names_one(self):
        work = self.series("Exam Beats", [
            {"release_title": "Exam Beats Season 2: Exams 720p", "season": "2",
             "episode": "Batch", "quality": "720p"}])
        season = _row(self.conn, "SELECT * FROM cat_seasons WHERE work_id = ? AND number = 2",
                      work["id"])
        self.assertEqual(season["title"], "Exams")

    def test_s00_print_is_a_special_season_not_an_unresolved_zero(self):
        work = self.series("Holiday Beats", [
            {"release_title": "Holiday Beats S00E01 Holiday Special 720p",
             "season": "S00", "episode": "1", "quality": "720p"}])
        season = _row(self.conn, "SELECT * FROM cat_seasons WHERE work_id = ? AND number = 0",
                      work["id"])
        self.assertEqual(season["season_type"], "special")
        rel = self.releases(work["id"])[0]
        self.assertEqual(rel["identity_suspect"], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_review_queue WHERE kind = 'season_unresolved'"
        ).fetchone()[0], 0)

    def test_work_runtime_only_when_a_label_states_it(self):
        self.add_post("site-a", "https://a.test/long-says-film/",
                      clean_title="Long Says Film", year=2019, releases=[
                          {"release_title": "Long Says Film 1080p 120min WEB-DL",
                           "quality": "1080p"}])
        self.add_post("site-a", "https://a.test/quiet-film/",
                      clean_title="Quiet Film", year=2019, releases=[
                          {"release_title": "Quiet Film 1080p WEB-DL", "quality": "1080p"}])
        self.project()
        self.assertEqual(self.works("Long Says Film", 2019)[0]["runtime_minutes"], 120)
        self.assertIsNone(self.works("Quiet Film", 2019)[0]["runtime_minutes"],
                          "runtime nobody stated must stay NULL, not be invented")


class PartsTests(ProjectionTestCase):
    """A4/S4: cat_parts exists only where one work really splits into parts."""

    def film(self, title, labels, year=2024):
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=year, releases=[
                          {"release_title": label, "quality": "1080p"}
                          for label in labels])
        self.project()
        return self.works(title, year)[0]

    def test_parts_and_chapters_materialize_and_link_their_prints(self):
        work = self.film("Dusk Saga", ["Dusk Saga Part 1 1080p",
                                       "Dusk Saga Chapter 2 1080p",
                                       "Dusk Saga Disc 3 1080p"])
        parts = self.conn.execute(
            "SELECT number, title FROM cat_parts WHERE work_id = ? ORDER BY number",
            (work["id"],)).fetchall()
        self.assertEqual([p["number"] for p in parts], [1, 2, 3])
        self.assertTrue(all(p["title"] for p in parts))
        by_label = {r["label"]: r["part_number"] for r in self.releases(work["id"])}
        self.assertEqual(by_label["Dusk Saga Part 1 1080p"], 1)
        self.assertEqual(by_label["Dusk Saga Chapter 2 1080p"], 2)
        self.assertEqual(by_label["Dusk Saga Disc 3 1080p"], 3)

    def test_a_single_part_label_does_not_fabricate_structure(self):
        work = self.film("Lone Part Film", ["Lone Part Film Part 2 1080p"])
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM cat_parts WHERE work_id = ?",
            (work["id"],)).fetchone()[0], 0)


class EntitlementTests(ProjectionTestCase):
    """A12/§11.2: paid offers are writable, survive rebuilds, and order by priority."""

    def film(self, title="Vault Film", year=2023, label=None):
        self.add_post("site-a", f"https://a.test/{title.casefold().replace(' ', '-')}/",
                      clean_title=title, year=year, releases=[
                          {"release_title": label or f"{title} 1080p WEB-DL",
                           "quality": "1080p"}])
        self.project()
        return self.works(title, year)[0]

    def offers(self, work_id):
        return self.conn.execute(
            "SELECT * FROM cat_entitlements WHERE work_id = ? ORDER BY display_priority",
            (work_id,)).fetchall()

    def test_display_priority_matches_the_documented_ladder(self):
        self.assertEqual(
            [catalog_v2.derive_display_priority(m) for m in
             ("free", "ads", "flatrate", "rental", "purchase")],
            [10, 20, 30, 40, 50])

    def test_work_level_paid_offer_replaces_the_free_default(self):
        work = self.film("Flatrate Film")
        result = catalog_v2.set_entitlement(self.conn, work_key=work["work_key"],
                                            model="flatrate", price_minor=4900,
                                            currency="INR")
        self.assertTrue(result["applied"])
        rows = self.offers(work["id"])
        self.assertEqual([r["model"] for r in rows], ["flatrate"])
        self.assertEqual(rows[0]["display_priority"], 30)
        self.assertEqual(rows[0]["price_minor"], 4900)
        self.assertEqual(self.works("Flatrate Film", 2023)[0]["entitlement_model"], "flatrate")

    def test_unknown_model_is_refused(self):
        work = self.film("Guarded Film")
        with self.assertRaises(ValueError):
            catalog_v2.set_entitlement(self.conn, work_key=work["work_key"], model="barter")

    def test_offer_survives_a_full_rebuild(self):
        work = self.film("Rented Film")
        catalog_v2.set_entitlement(self.conn, work_key=work["work_key"], model="rental",
                                   price_minor=1900, rental_hours=48, ownership="timered")
        catalog_v2.project(self.conn, rev=2, verbose=False)
        rows = self.offers(work["id"])
        self.assertEqual([r["model"] for r in rows], ["rental"])
        self.assertEqual(rows[0]["rental_hours"], 48)
        self.assertEqual(rows[0]["display_priority"], 40)

    def test_per_print_offer_sits_alongside_the_work_default(self):
        work = self.film("Dual Offer Film", label="Dual Offer Film 4K HDR")
        catalog_v2.set_entitlement(self.conn, work_key=work["work_key"], model="purchase",
                                   release_label="Dual Offer Film 4K HDR", price_minor=9900)
        rows = self.offers(work["id"])
        models = sorted(r["model"] for r in rows)
        self.assertEqual(models, ["free", "purchase"])
        purchase = next(r for r in rows if r["model"] == "purchase")
        self.assertIsNotNone(purchase["release_id"])
        self.assertEqual(purchase["display_priority"], 50)

    def test_rule_for_an_unprojected_print_is_applied_by_the_next_projection(self):
        work = self.film("Future Print Film")
        result = catalog_v2.set_entitlement(self.conn, work_key=work["work_key"],
                                            model="ads", release_label="Future Print Film 2160p")
        self.assertFalse(result["applied"])
        self.add_post("site-b", "https://b.test/future-print-film-uhd/",
                      clean_title="Future Print Film", year=2023, releases=[
                          {"release_title": "Future Print Film 2160p", "quality": "2160p"}])
        catalog_v2.project(self.conn, rev=2, verbose=False)
        rows = self.offers(self.works("Future Print Film", 2023)[0]["id"])
        self.assertIn("ads", [r["model"] for r in rows])
        ads = next(r for r in rows if r["model"] == "ads")
        self.assertIsNotNone(ads["release_id"])

    def test_cli_writes_an_entitlement(self):
        import contextlib
        import io
        work = self.film("Cli Priced Film")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            catalog_v2.main([str(self.db_path), "--set-entitlement", work["work_key"],
                             "--model", "rental", "--price", "1500",
                             "--rental-hours", "24"])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["model"], "rental")
        rows = self.offers(work["id"])
        self.assertEqual([r["model"] for r in rows], ["rental"])
        self.assertEqual(rows[0]["rental_hours"], 24)
        self.assertEqual(rows[0]["requires_account"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
