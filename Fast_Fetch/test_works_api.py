#!/usr/bin/env python3
"""Offline tests for the work-centric API (`/api/v1/works`).

One movie/series is one work; the ledger stores one post per site
copy. The fixture rebuilds the Salaar case from the brief (three
posts for one film, plus a sequel that must stay separate, plus a
flagged twin whose flag does not corroborate — the live shape) and
the series case (mixed `S01`/`1` season formats, a gap, a pack),
then pins:

1. **Grouping.** `Salaar` / `Salaar Part 1 Ceasefire` (2023) /
   `Salaar - 1 - Ceasefire` (2024) are ONE work; `Salaar 2`,
   `Dune` vs `Dune: Part Two`, `John Wick` vs `Chapter 2` stay
   separate (the sequel guard + the year rule). A flagged twin
   hides the whole work on the works surface only when its flag is
   corroborated (`fast_fetch.adult_rule_agrees`); an
   uncorroborated flagged twin is excluded from the work but does
   not hide it — while `/api/v1/posts` still serves the unflagged
   twin per row. The stricter surface, documented in the design
   note.
2. **Normalisation.** Season/episode parse to one format (`S01` /
   `E01`); the episode guide marks gaps `missing` and pack-covered
   gaps `in_pack`, never `missing`.
3. **Filters.** Language buckets (`dual`, `unknown`, `hindi`), region
   keys (`chinese`, `korean`, `turkish`) on both `industry=` and
   `region=`, `sort=most_copies` == `sort=trending`, and the trending
   route's honest `basis`/`label`.
4. **Search.** The typo with hits (`salar` → `did_you_mean:
   salaar`, Salary Man still served), the nonsense query (empty +
   `suggestions`), the stopword (`the` matches whole words only).
5. **The edge.** The two routes answer 200 with the works shape over
   real HTTP, a missing or non-integer work id is a 404/400, and no
   `Origin` is ever reflected (CORS stays closed).

    python3 -S Fast_Fetch/test_works_api.py
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
import works               # noqa: E402

_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


class WorksPureTests(unittest.TestCase):
    """The grouping / normalisation / bucket helpers, no database."""

    def row(self, post_id, title, year=2023, content_type="movie",
            flagged=0, imdb_id="", tmdb_id=None):
        return {"id": post_id, "clean_title": title, "title": title,
                "year": year, "content_type": content_type,
                "is_animated": 0, "imdb_id": imdb_id, "tmdb_id": tmdb_id,
                "is_18_plus": flagged}

    def test_salaar_variants_share_one_key(self):
        keys = {works.work_key_for_post(self.row(i, title, year))
                for i, (title, year) in enumerate((
                    ("Salaar", 2023),
                    ("Salaar Part 1 Ceasefire", 2023),
                    ("Salaar - Part 1 (2023) Multi Audios [Tel + Tam + Mal + Kan] NF WeB-DL", 2023),
                    ("Salaar \u2013 1 \u2013 Ceasefire", 2024),
                    ("Salaar Cease Fire", 2023),
                ))}
        self.assertEqual(len(keys), 5)  # tier-1 keys still differ …
        groups = works.group_posts([
            self.row(1, "Salaar", 2023),
            self.row(2, "Salaar Part 1 Ceasefire", 2023),
            self.row(3, "Salaar - Part 1 (2023) Multi Audios [Tel + Tam + Mal + Kan] NF WeB-DL", 2023),
            self.row(4, "Salaar \u2013 1 \u2013 Ceasefire", 2024),
            self.row(5, "Salaar Cease Fire", 2023),
        ])
        self.assertEqual(len(groups), 1)  # … but tier-2 folds them all
        self.assertEqual(groups[0]["post_ids"], [1, 2, 3, 4, 5])
        self.assertEqual(groups[0]["work_id"], 1)

    def test_id_keyed_member_merges_with_id_less_twins(self):
        # Live Salaar: 1 of 9 posts carries an id, the other 8 do
        # not. The id-keyed tier-1 group must still fold with its
        # title-keyed twins — tier-2 compares the rows' own titles,
        # never the key text (`imdb:tt13927994` carries no title).
        groups = works.group_posts([
            self.row(1, "Salaar", 2023),
            self.row(2, "Salaar Part 1 Ceasefire", 2023),
            self.row(3, "Salaar \u2013 1 \u2013 Ceasefire", 2024,
                     imdb_id="tt13927994"),
        ])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["post_ids"], [1, 2, 3])

    def test_sequels_never_merge(self):
        groups = works.group_posts([
            self.row(1, "Dune", 2021),
            self.row(2, "Dune: Part Two", 2024),
            self.row(3, "John Wick", 2014),
            self.row(4, "John Wick: Chapter 2", 2017),
            self.row(5, "Salaar", 2023),
            self.row(6, "Salaar 2", 2026),
            self.row(7, "The Dark Knight", 2008),
            self.row(8, "The Dark Knight Rises", 2012),
        ])
        self.assertEqual(len(groups), 8)

    def test_movie_and_series_with_one_title_are_two_works(self):
        groups = works.group_posts([
            self.row(1, "It", 2017, content_type="movie"),
            self.row(2, "It", 2017, content_type="series"),
        ])
        self.assertEqual(len(groups), 2)

    def test_ids_win_over_titles(self):
        self.assertEqual(
            works.work_key_for_post(self.row(1, "Salaar", 2023, imdb_id="tt13927994")),
            "imdb:tt13927994")
        self.assertEqual(
            works.work_key_for_post(self.row(1, "Salaar", 2023, tmdb_id=100)),
            "tmdb:100")

    def test_first_token_is_never_stripped(self):
        # "Hindi Medium" keeps its first word; only later edition
        # tokens are dropped.
        self.assertEqual(works.work_title_tokens("Hindi Medium"),
                         ["hindi", "medium"])
        self.assertEqual(works.work_title_tokens("Salaar (2023) Hindi Dubbed"),
                         ["salaar"])

    def test_ongoing_title_normalises_to_the_base_title(self):
        self.assertEqual(
            works.work_title_tokens("One Piece [S01E08 Added]"),
            ["one", "piece"])

    def test_flagged_member_marks_the_group(self):
        groups = works.group_posts([
            self.row(1, "Kanguva", 2024),
            self.row(2, "Kanguva", 2024, flagged=1),
        ])
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["flagged"])

    def test_corroboration_gate_decides_whether_a_flag_hides_the_work(self):
        # The fold's gate, not a raw MAX: a flagged member hides the
        # work only when the checker re-derives the flag from the
        # row's own text. A flagged twin that does not corroborate is
        # excluded from the work but does not hide it.
        def agrees(row):
            return "ullu" in (row["clean_title"] or "").lower()

        groups = works.group_posts([
            self.row(1, "Salaar", 2023),
            self.row(2, "Salaar", 2023, flagged=1),
        ], adult_agrees=agrees)
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0]["flagged"])
        self.assertEqual(groups[0]["post_ids"], [1])
        self.assertEqual(groups[0]["flagged_ids"], [2])

        groups = works.group_posts([
            self.row(1, "Kanguva", 2024),
            self.row(2, "Kanguva Ullu Original", 2024, flagged=1),
        ], adult_agrees=agrees)
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0]["flagged"])
        self.assertEqual(groups[0]["post_ids"], [1])
        self.assertEqual(groups[0]["flagged_ids"], [2])

    def test_batch_episode_is_a_pack_not_an_episode(self):
        # 10,525 releases carry the literal `Batch` (data baseline
        # 2026-11-12): it names a pack, never an episode number.
        self.assertIsNone(works.parse_episode("Batch"))
        self.assertIsNone(works.parse_episode("batch"))
        self.assertIsNone(works.parse_episode("Complete"))
        seasons, _latest = works.build_seasons([
            {"season": "S01", "episode": "E01",
             "created_at": "2026-01-01 00:00:00"},
            {"season": "S01", "episode": "E03",
             "created_at": "2026-01-02 00:00:00"},
            {"season": "S01", "episode": "Batch",
             "created_at": "2026-01-03 00:00:00"},
        ])
        # E02 is named by no release, but the season has a pack: it
        # may be inside it, so it reads `in_pack`, never `missing`.
        self.assertEqual(seasons, [
            {"season": "S01", "episodes": [
                {"episode": "E01", "status": "available"},
                {"episode": "E02", "status": "in_pack"},
                {"episode": "E03", "status": "available"}]},
        ])

    def test_season_and_episode_parsing(self):
        self.assertEqual(works.parse_season("S01"), 1)
        self.assertEqual(works.parse_season("1"), 1)
        self.assertEqual(works.parse_season("Season 2"), 2)
        self.assertEqual(works.parse_season("S12"), 12)
        self.assertIsNone(works.parse_season(None))
        self.assertIsNone(works.parse_season(""))
        self.assertIsNone(works.parse_season("Season Two"))
        self.assertEqual(works.parse_episode("E01"), 1)
        self.assertEqual(works.parse_episode("1"), 1)
        self.assertEqual(works.parse_episode("Episode 12"), 12)
        self.assertIsNone(works.parse_episode(None))
        self.assertEqual(works.format_season(2), "S02")
        self.assertEqual(works.format_episode(12), "E12")

    def test_episode_guide_marks_gaps_and_packs(self):
        seasons, latest = works.build_seasons([
            {"season": "S01", "episode": "E01", "created_at": "2026-01-01 00:00:00"},
            {"season": "1", "episode": "2", "created_at": "2026-01-02 00:00:00"},
            {"season": "S01", "episode": "E04", "created_at": "2026-01-03 00:00:00"},
            {"season": "S02", "episode": "E01", "created_at": "2026-01-04 00:00:00"},
            {"season": "S02", "episode": "E03", "created_at": "2026-01-05 00:00:00"},
            {"season": "S02", "episode": None, "created_at": "2026-01-06 00:00:00"},
        ])
        self.assertEqual(seasons, [
            {"season": "S01", "episodes": [
                {"episode": "E01", "status": "available"},
                {"episode": "E02", "status": "available"},
                {"episode": "E03", "status": "missing"},
                {"episode": "E04", "status": "available"}]},
            {"season": "S02", "episodes": [
                {"episode": "E01", "status": "available"},
                {"episode": "E02", "status": "in_pack"},
                {"episode": "E03", "status": "available"}]},
        ])
        self.assertEqual(latest, "2026-01-06 00:00:00")
        seasons, latest = works.build_seasons([])
        self.assertEqual((seasons, latest), ([], None))

    def test_language_buckets(self):
        self.assertEqual(works.language_buckets("Hindi"), {"hindi"})
        self.assertEqual(works.language_buckets('["Hindi"]'), {"hindi"})
        self.assertEqual(works.language_buckets("hindi"), {"hindi"})
        self.assertEqual(works.language_buckets("Hindi + English"),
                         {"hindi", "english", "dual"})
        self.assertEqual(works.language_buckets("Tel + Tam"),
                         {"telugu", "tamil", "dual"})
        self.assertEqual(works.language_buckets("Hindi, Urdu"),
                         {"hindi", "urdu", "dual"})
        self.assertEqual(works.language_buckets("Unknown"), {"unknown"})
        self.assertEqual(works.language_buckets("[]"), {"unknown"})
        self.assertEqual(works.language_buckets(None), {"unknown"})
        self.assertEqual(works.language_buckets("Original Audio"), {"unknown"})
        self.assertEqual(works.language_buckets("Hindi + English + Tamil"),
                         {"hindi", "english", "tamil", "dual", "multi"})

    def test_language_sql(self):
        self.assertIsNotNone(works.language_sql("hindi"))
        self.assertIsNotNone(works.language_sql("dual"))
        self.assertIsNotNone(works.language_sql("unknown"))
        # Not a bucket: the caller falls back to the substring LIKE.
        self.assertIsNone(works.language_sql("original audio"))
        self.assertIsNone(works.language_sql("%"))

    def test_poor_match_and_whole_word_queries(self):
        self.assertTrue(works.is_poor_match("salar", ["Salary Man"]))
        self.assertFalse(works.is_poor_match("dune", ["Dune: Part Two"]))
        self.assertFalse(works.is_poor_match("salaar", ["Salaar"]))
        self.assertTrue(works.is_whole_word_query("the"))
        self.assertTrue(works.is_whole_word_query("it"))
        self.assertFalse(works.is_whole_word_query("salaar"))
        self.assertFalse(works.is_whole_word_query("the godfather"))
        clause, params = works.whole_word_title_clause("the")
        self.assertIn("clean_title", clause)
        self.assertEqual(len(params), 12)


class Fixture(unittest.TestCase):
    """The Salaar / One Piece / region ledger, built the way production
    builds it: `save_scraped_data` for every post except the flagged
    Kanguva twin, which is inserted directly — production carries its
    flagged twins under a *different* key (the cross-key residual),
    and `save_scraped_data` would fold a same-key twin at write time.
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
        self.addCleanup(viewer._WORKS_LIST_CACHE.clear)
        os.environ["RADD_STREAM_SECRET"] = "test-secret-for-works-api"
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.addCleanup(setattr, viewer, "_SIGNING_SECRET", None)
        self.addCleanup(lambda: redact.limiter._buckets.clear())
        self.salaar_a = self.ingest(
            title="Salaar", year=2023, content_type="movie",
            genres=["Action"], cast=["Prabhas"],
            industry="Bollywood", language="Hindi",
            releases=[self.release("720p"), self.release("1080p")])
        self.salaar_b = self.ingest(
            title="Salaar Part 1 Ceasefire", year=2023, content_type="movie",
            genres=["Action"], cast=["Prabhas"],
            industry="Bollywood", language="Hindi",
            releases=[self.release("720p")])
        self.salaar_c = self.ingest(
            title="Salaar \u2013 1 \u2013 Ceasefire", year=2024,
            content_type="movie", genres=["Action"], cast=["Prabhas"],
            industry="Bollywood", language="Hindi",
            releases=[self.release("1080p")])
        # Only one Salaar copy carries external ids (live: 1 of 9) —
        # and it is NOT the representative (the bare title is), so the
        # work must surface the member's ids anyway.
        self.conn.execute(
            "UPDATE posts SET imdb_id = ?, tmdb_id = ? WHERE id = ?",
            ("tt13927994", 770906, self.salaar_c))
        self.conn.commit()
        # A flagged Salaar twin whose flag the shared rule cannot
        # re-derive — its title carries no adult evidence, the live
        # shape (post 9388, "Salaar Part 1 Ceasefire" 2024). It is
        # excluded from the work but must NOT hide it.
        self.salaar_flagged = self.insert_post_direct(
            title="Salaar Part 1 Ceasefire", year=2024,
            content_type="movie", industry="Bollywood", language="Hindi",
            canonical_key="salaar_2024_flagged", is_18_plus=1,
            releases=[self.release("720p")])
        self.salaar_2 = self.ingest(
            title="Salaar 2", year=2026, content_type="movie",
            genres=["Action"], cast=["Prabhas"],
            industry="Bollywood", language="Hindi",
            releases=[self.release("720p")])
        self.dune = self.ingest(
            title="Dune", year=2021, content_type="movie",
            genres=["Sci-Fi"], cast=["Timothee Chalamet"],
            industry="Hollywood", language="English",
            releases=[self.release("1080p")])
        self.dune_2 = self.ingest(
            title="Dune: Part Two", year=2024, content_type="movie",
            genres=["Sci-Fi"], cast=["Timothee Chalamet"],
            industry="Hollywood", language="English",
            releases=[self.release("1080p")])
        self.one_piece_a = self.ingest(
            title="One Piece", year=1999, content_type="series",
            genres=["Adventure"], cast=["Mayumi Tanaka"],
            industry="Anime", language="Japanese",
            releases=[self.release("720p", season="S01", episode="E01"),
                      self.release("720p", season="1", episode="2"),
                      self.release("720p", season="S01", episode="E04")])
        # Direct insert, not `save_scraped_data`: the write path would
        # fold this into the post above (same canonical key, series ≡
        # ongoing_season for matching) — which is exactly the
        # re-scrape-creates-a-new-post defect the works API exists to
        # heal. Production files these as two posts; so does the fixture.
        self.one_piece_b = self.insert_post_direct(
            title="One Piece [S01E08 Added]", year=1999,
            content_type="ongoing_season",
            industry="Anime", language="Japanese",
            canonical_key="one-piece_1999_b",
            releases=[self.release("720p", season="S02", episode="E01"),
                      self.release("720p", season="S02", episode="E03"),
                      self.release("720p", season="S02", episode=None)])
        self.kanguva = self.ingest(
            title="Kanguva", year=2024, content_type="movie",
            genres=["Action"], cast=["Suriya"],
            industry="Bollywood", language="Tamil",
            releases=[self.release("720p")])
        self.kanguva_flagged = self.insert_flagged_twin()
        self.salary = self.ingest(
            title="Salary Man", year=2023, content_type="movie",
            genres=["Comedy"], cast=["Someone"],
            industry="Hollywood", language="English",
            releases=[self.release("720p")])
        self.godfather = self.ingest(
            title="The Godfather", year=1972, content_type="movie",
            genres=["Crime"], cast=["Marlon Brando"],
            industry="Hollywood", language="English",
            releases=[self.release("720p")])
        self.other = self.ingest(
            title="Other Title", year=2020, content_type="movie",
            genres=["Drama"], cast=["Someone"],
            industry="Hollywood", language="English",
            releases=[self.release("720p")])
        self.together = self.ingest(
            title="Together", year=2024, content_type="movie",
            genres=["Drama"], cast=["Someone"],
            industry="Hollywood", language="English",
            releases=[self.release("720p")])
        self.squid = self.ingest(
            title="Squid Game", year=2021, content_type="series",
            genres=["Thriller"], cast=["Lee Jung-jae"],
            industry="Korean", language="Korean",
            releases=[self.release("1080p")])
        self.wandering = self.ingest(
            title="The Wandering Earth", year=2019, content_type="movie",
            genres=["Sci-Fi"], cast=["Wu Jing"],
            industry="Chinese", language="Chinese", country="China",
            releases=[self.release("1080p")])
        self.ankara = self.ingest(
            title="Ankara Nights", year=2022, content_type="movie",
            genres=["Drama"], cast=["Someone"],
            industry="Turkish", language="Turkish", country="Turkey",
            releases=[self.release("720p")])
        self.jawan = self.ingest(
            title="Jawan", year=2023, content_type="movie",
            genres=["Action"], cast=["Shah Rukh Khan"],
            industry="Bollywood", language="Hindi + English",
            releases=[self.release("720p")])
        self.mystery = self.ingest(
            title="Mystery Film", year=2022, content_type="movie",
            genres=["Mystery"], cast=["Someone"],
            industry="Hollywood", language="Unknown",
            releases=[self.release("720p")])

    def release(self, quality, season="", episode=""):
        # One source per print: the option-group tests need a ladder
        # to merge, and a print with no source has no tier at all.
        self._source_counter = getattr(self, "_source_counter", 0) + 1
        return {"release_title": "print %s %s%s" % (quality, season, episode or ""),
                "quality": quality, "codec": "x264", "size": "1.5GB",
                "languages": json.dumps(["Hindi"]),
                "season": season, "episode": episode or "",
                "intermediate_url": "", "origin_url": "",
                "source_site": "somecdn.site",
                "sources": [{
                    "source_url": "https://cdn.example/%d-%s.mp4"
                                  % (self._source_counter, quality),
                    "quality": quality, "status": "active"}]}

    def ingest(self, *, title, year, content_type, genres, cast,
               industry, language, releases, country="India"):
        slug = title.lower().replace(" ", "-").replace(":", "").replace("[", "")
        slug = slug.replace("]", "").replace("\u2013", "-")
        data = {
            "url": "https://somecdn.site/movie/%s-%d/" % (slug, year),
            "slug": slug,
            "title": "%s (%d)" % (title, year),
            "clean_title": title,
            "year": year,
            "content_type": content_type,
            "poster_url": "https://cdn/poster.jpg",
            "genres": json.dumps(genres),
            "cast_names": json.dumps(cast),
            "synopsis": "%s synopsis" % title,
            "is_18_plus": 0,
            "source_site": "somecdn.site",
            "industry": industry,
            "country": country,
            "language": language,
            "canonical_key": fast_fetch.generate_canonical_key(title, year),
            "releases": releases,
        }
        post_id = fast_fetch.save_scraped_data(
            data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()
        return post_id

    def insert_post_direct(self, *, title, year, content_type, industry,
                           language, canonical_key, releases,
                           is_18_plus=0, country="India"):
        """Direct INSERT, bypassing `save_scraped_data`: production
        files some twins as two posts (same title+year, different
        key) and the write path would fold them back into one. The
        fixture files them the way production does — the same columns
        the ingest path writes, including one `download_sources` row
        per source the release carries."""
        slug = title.lower().replace(" ", "-").replace(":", "")
        slug = slug.replace("[", "").replace("]", "").replace("\u2013", "-")
        cursor = self.conn.execute(
            "INSERT INTO posts (url, slug, title, clean_title, year,"
            " content_type, source_site, is_18_plus, canonical_key,"
            " industry, country, language)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("https://othercdn.site/movie/%s-%d/" % (slug, year),
             slug, "%s (%d)" % (title, year), title, year,
             content_type, "othercdn.site", is_18_plus, canonical_key,
             industry, country, language))
        post_id = cursor.lastrowid
        for rel in releases:
            rel_cur = self.conn.execute(
                "INSERT INTO releases (post_id, release_title, season,"
                " episode, quality, codec, size, languages,"
                " intermediate_url, source_site, origin_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (post_id, rel.get("release_title") or title,
                 rel.get("season"), rel.get("episode"),
                 rel.get("quality"), rel.get("codec"), rel.get("size"),
                 rel.get("languages"), rel.get("intermediate_url"),
                 rel.get("source_site", "othercdn.site"),
                 rel.get("origin_url")))
            rel_id = rel_cur.lastrowid
            for src in rel.get("sources") or []:
                self.conn.execute(
                    "INSERT INTO download_sources (release_id,"
                    " source_name, service, resource_id, source_url,"
                    " final_url, playback_type, is_temporary, status)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rel_id, src.get("source_name"),
                     src.get("service"), src.get("resource_id"),
                     src.get("source_url"), src.get("final_url"),
                     src.get("playback_type", "url"),
                     src.get("is_temporary", 0),
                     src.get("status") or "unverified"))
        self.conn.commit()
        return post_id

    def insert_flagged_twin(self):
        """A flagged twin under a different key, the way production
        actually files them — same work, so the works grouping still
        folds it in, and the work-level adult rule must hide it. Its
        title carries the corroborating evidence (`ullu`, a strong
        adult token): a flagged twin whose title carries no such
        evidence must NOT hide the work — see the Salaar twin in
        setUp, which is the live shape (post 9388)."""
        return self.insert_post_direct(
            title="Kanguva Ullu Original", year=2024,
            content_type="movie", industry="Bollywood", language="Tamil",
            canonical_key="kanguva_2024_b", is_18_plus=1,
            releases=[self.release("720p")])

    def work_ids(self, resp):
        return [int(item["id"]) for item in resp["results"]]

    def work_by_id(self, resp, work_id):
        for item in resp["results"]:
            if int(item["id"]) == work_id:
                return item
        self.fail("no work %r in %r" % (work_id, resp["results"]))


class WorksListTests(Fixture):
    def test_salaar_is_one_work_not_three_posts(self):
        resp = viewer.api_v1_get_works(query="salaar", limit=20)
        # Two works answer: the Salaar work and its sequel, separate.
        self.assertEqual(resp["total"], 2)
        work = self.work_by_id(resp, self.salaar_a)
        self.assertEqual(int(work["id"]), self.salaar_a)
        self.assertEqual(work["post_ids"],
                         [self.salaar_a, self.salaar_b, self.salaar_c])
        self.assertEqual(work["post_count"], 3)
        self.assertEqual(work["release_count"], 4)
        self.assertEqual(work["clean_title"], "Salaar")
        # The ids live on salaar_c, not on the representative — the
        # work still carries its best-known member's ids.
        self.assertEqual(work["imdb_id"], "tt13927994")
        self.assertEqual(work["tmdb_id"], 770906)
        self.assertNotIn("work_key", work)

    def test_unfiltered_list_counts_works_not_posts(self):
        resp = viewer.api_v1_get_works(limit=50)
        # 19 servable posts collapse into 14 works; the flagged
        # Kanguva twin hides its work entirely, the flagged Salaar
        # twin does not (its flag does not corroborate).
        self.assertEqual(resp["total"], 14)
        self.assertEqual(len(resp["results"]), 14)

    def test_sequel_stays_its_own_work(self):
        resp = viewer.api_v1_get_works(query="salaar", limit=20)
        # Both answer, as two works — the sequel is not folded into
        # the original and the original's members exclude it.
        self.assertEqual({int(i["id"]) for i in resp["results"]},
                         {self.salaar_a, self.salaar_2})
        salaar = self.work_by_id(resp, self.salaar_a)
        self.assertNotIn(self.salaar_2, salaar["post_ids"])
        resp = viewer.api_v1_get_works(query="dune", limit=20)
        self.assertEqual({int(i["id"]) for i in resp["results"]},
                         {self.dune, self.dune_2})

    def test_list_shape_matches_posts_shape(self):
        posts = viewer.api_v1_get_posts(limit=50)
        works = viewer.api_v1_get_works(limit=50)
        post_keys = set(posts["results"][0])
        for item in works["results"]:
            for key in ("id", "clean_title", "title", "year",
                        "content_type", "imdb_rating", "genres",
                        "poster_url", "work_ref", "release_count",
                        "source_count"):
                self.assertIn(key, item, key)
            self.assertTrue(post_keys <= set(item), item)
            self.assertIn("post_ids", item)
            self.assertIn("post_count", item)
            self.assertIn("languages", item)

    def test_flagged_twin_hides_the_work_but_not_the_post(self):
        works = viewer.api_v1_get_works(query="kanguva", limit=20)
        self.assertEqual(works["total"], 0)
        posts = viewer.api_v1_get_posts(query="kanguva", limit=20)
        self.assertEqual([int(i["id"]) for i in posts["results"]],
                         [self.kanguva])

    def test_uncorroborated_flagged_twin_does_not_hide_the_work(self):
        # The live Salaar shape: one twin flagged on no evidence the
        # rule can re-derive. The work still answers, and the twin's
        # id is absent from post_ids. (The sequel answers too, as its
        # own work, so the total is 2.)
        resp = viewer.api_v1_get_works(query="salaar", limit=20)
        self.assertEqual(resp["total"], 2)
        work = self.work_by_id(resp, self.salaar_a)
        self.assertEqual(work["post_ids"],
                         [self.salaar_a, self.salaar_b, self.salaar_c])
        self.assertNotIn(self.salaar_flagged, work["post_ids"])
        self.assertEqual(work["post_count"], 3)

    def test_language_buckets(self):
        dual = viewer.api_v1_get_works(language="dual", limit=50)
        self.assertEqual({int(i["id"]) for i in dual["results"]},
                         {self.jawan})
        unknown = viewer.api_v1_get_works(language="unknown", limit=50)
        self.assertEqual({int(i["id"]) for i in unknown["results"]},
                         {self.mystery})
        hindi = viewer.api_v1_get_works(language="hindi", limit=50)
        self.assertIn(self.salaar_a, {int(i["id"]) for i in hindi["results"]})
        self.assertIn(self.jawan, {int(i["id"]) for i in hindi["results"]})

    def test_region_filters(self):
        for key, work_id in (("chinese", self.wandering),
                             ("korean", self.squid),
                             ("turkish", self.ankara)):
            for param in ("industry", "region"):
                resp = viewer.api_v1_get_works(limit=50, **{param: key})
                self.assertEqual({int(i["id"]) for i in resp["results"]},
                                 {work_id}, (param, key))
                posts = viewer.api_v1_get_posts(limit=50, **{param: key})
                self.assertEqual({int(i["id"]) for i in posts["results"]},
                                 {work_id}, ("posts", param, key))

    def test_most_copies_is_trending_under_its_honest_name(self):
        trending = viewer.api_v1_get_posts(sort="trending", limit=50)
        copies = viewer.api_v1_get_posts(sort="most_copies", limit=50)
        self.assertEqual([i["id"] for i in trending["results"]],
                         [i["id"] for i in copies["results"]])
        rail = viewer.api_v1_get_trending(limit=50)
        self.assertEqual(rail["basis"], "most_copies")
        self.assertEqual(rail["label"], "Most copies")

    def test_typo_with_hits_surfaces_did_you_mean(self):
        resp = viewer.api_v1_get_posts(query="salar", limit=20)
        self.assertEqual([int(i["id"]) for i in resp["results"]],
                         [self.salary])
        self.assertEqual(resp["did_you_mean"], "salaar")
        works = viewer.api_v1_get_works(query="salar", limit=20)
        self.assertEqual([int(i["id"]) for i in works["results"]],
                         [self.salary])
        self.assertEqual(works["did_you_mean"], "salaar")

    def test_good_match_gets_no_correction(self):
        resp = viewer.api_v1_get_posts(query="dune", limit=20)
        self.assertIsNone(resp["did_you_mean"])
        works = viewer.api_v1_get_works(query="dune", limit=20)
        self.assertIsNone(works["did_you_mean"])

    def test_nonsense_query_gets_suggestions_not_a_bare_zero(self):
        resp = viewer.api_v1_get_posts(query="asdfghjkl", limit=20)
        self.assertEqual(resp["total"], 0)
        self.assertEqual(resp["results"], [])
        self.assertIn("suggestions", resp)
        self.assertEqual(len(resp["suggestions"]), 5)
        self.assertIsNone(resp["did_you_mean"])
        works = viewer.api_v1_get_works(query="asdfghjkl", limit=20)
        self.assertEqual(works["total"], 0)
        self.assertIn("suggestions", works)
        self.assertEqual(len(works["suggestions"]), 5)

    def test_stopword_matches_whole_words_only(self):
        resp = viewer.api_v1_get_posts(query="the", limit=50)
        ids = {int(i["id"]) for i in resp["results"]}
        self.assertIn(self.godfather, ids)
        self.assertIn(self.wandering, ids)
        self.assertNotIn(self.other, ids)
        self.assertNotIn(self.together, ids)
        works = viewer.api_v1_get_works(query="the", limit=50)
        wids = {int(i["id"]) for i in works["results"]}
        self.assertIn(self.godfather, wids)
        self.assertNotIn(self.other, wids)
        self.assertNotIn(self.together, wids)

    def test_paging(self):
        first = viewer.api_v1_get_works(limit=5, page=1)
        second = viewer.api_v1_get_works(limit=5, page=2)
        self.assertEqual(len(first["results"]), 5)
        self.assertEqual(len(second["results"]), 5)
        self.assertFalse({i["id"] for i in first["results"]}
                         & {i["id"] for i in second["results"]})
        self.assertEqual(first["total_pages"], 3)


class WorksDetailTests(Fixture):
    def test_salaar_detail_merges_every_copy(self):
        detail = viewer.api_v1_get_work_detail(self.salaar_a)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["id"], self.salaar_a)
        self.assertEqual(detail["post_ids"],
                         [self.salaar_a, self.salaar_b, self.salaar_c])
        self.assertEqual(detail["post_count"], 3)
        self.assertEqual(detail["release_count"], 4)
        self.assertEqual(detail["clean_title"], "Salaar")
        self.assertEqual(detail["imdb_id"], "tt13927994")
        self.assertEqual(detail["tmdb_id"], 770906)
        self.assertEqual(detail["languages"], ["hindi"])
        self.assertEqual(detail["episode_guide"], [])
        self.assertFalse(detail["is_ongoing"])
        self.assertIsNone(detail["latest_episode_added_at"])

    def test_detail_by_any_member_post_resolves_the_same_work(self):
        for member in (self.salaar_a, self.salaar_b, self.salaar_c):
            detail = viewer.api_v1_get_work_detail(member)
            self.assertIsNotNone(detail, member)
            self.assertEqual(detail["id"], self.salaar_a, member)

    def test_series_detail_has_episode_guide_with_gaps(self):
        detail = viewer.api_v1_get_work_detail(self.one_piece_a)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["post_ids"],
                         [self.one_piece_a, self.one_piece_b])
        self.assertEqual(detail["episode_guide"], [
            {"season": "S01", "episodes": [
                {"episode": "E01", "status": "available"},
                {"episode": "E02", "status": "available"},
                {"episode": "E03", "status": "missing"},
                {"episode": "E04", "status": "available"}]},
            {"season": "S02", "episodes": [
                {"episode": "E01", "status": "available"},
                {"episode": "E02", "status": "in_pack"},
                {"episode": "E03", "status": "available"}]},
        ])
        self.assertTrue(detail["is_ongoing"])
        self.assertIsNotNone(detail["latest_episode_added_at"])
        # Every release row carries the normalised season/episode.
        scopes = {(r["season"], r["episode"]) for r in detail["releases"]}
        self.assertIn(("S01", "E01"), scopes)
        self.assertIn(("S01", "E02"), scopes)
        self.assertIn(("S01", "E04"), scopes)
        self.assertIn(("S02", "E01"), scopes)
        self.assertIn(("S02", "E03"), scopes)
        # … and the option groups fold `1` and `S01` into one scope.
        group_scopes = {(g["season"], g["episode"])
                        for g in detail["option_groups"]}
        self.assertIn(("S01", "E02"), group_scopes)
        self.assertNotIn(("1", "2"), group_scopes)

    def test_missing_and_flagged_work_are_both_none(self):
        self.assertIsNone(viewer.api_v1_get_work_detail(999999))
        self.assertIsNone(viewer.api_v1_get_work_detail(self.kanguva_flagged))
        # The unflagged twin is listed by /posts but hidden on /works.
        self.assertIsNone(viewer.api_v1_get_work_detail(self.kanguva))
        # The uncorroborated Salaar twin is not a work either — the
        # seed is flagged, so the detail answers None even though the
        # work itself is public under its unflagged members.
        self.assertIsNone(viewer.api_v1_get_work_detail(self.salaar_flagged))

    def test_non_integer_work_id_is_none(self):
        self.assertIsNone(viewer.api_v1_get_work_detail("abc"))

    def test_trigram_candidates_cover_the_like_matches(self):
        # The trigram candidate pass is a SUPERSET of the LIKE scan:
        # every Salaar-titled post shares the token's grams. Other
        # titles may share a single gram too (the exact LIKE check
        # still runs in the caller), so this asserts containment, not
        # equality.
        import fts_posts
        fts_posts.rebuild_fts(self.conn)
        ids = viewer._works_title_candidate_ids(self.conn, "salaar")
        self.assertIsNotNone(ids)
        self.assertTrue({self.salaar_a, self.salaar_b,
                         self.salaar_c, self.salaar_flagged} <= set(ids))

    def test_trigram_candidates_return_none_without_the_index(self):
        # No fts_posts_tri (pre-migration database): fall back to the
        # full LIKE scan rather than guessing.
        self.assertIsNone(
            viewer._works_title_candidate_ids(self.conn, "salaar"))

    def test_trigram_candidates_empty_when_no_row_shares_a_gram(self):
        # A real answer, not a fallback: no row shares a gram with a
        # nonsense token, so the candidate set is empty (the caller
        # turns that into `1 = 0`, never `IN ()`).
        import fts_posts
        fts_posts.rebuild_fts(self.conn)
        self.assertEqual(
            viewer._works_title_candidate_ids(self.conn, "zzzqqq"), [])

    def test_detail_group_is_the_same_with_and_without_the_trigram_index(self):
        # The candidate pass must not change the group: the same three
        # members, the same release count, before (full LIKE scan) and
        # after (trigram candidates). The flagged twin stays out both
        # ways.
        import fts_posts
        before = viewer.api_v1_get_work_detail(self.salaar_a)
        self.assertIsNotNone(before)
        fts_posts.rebuild_fts(self.conn)
        after = viewer.api_v1_get_work_detail(self.salaar_a)
        self.assertIsNotNone(after)
        self.assertEqual(after["post_ids"], before["post_ids"])
        self.assertEqual(after["post_count"], before["post_count"])
        self.assertEqual(after["release_count"], before["release_count"])


class WorksHttpTests(Fixture):
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

    def get(self, path, origin=None):
        redact.limiter._buckets.clear()
        headers = {}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.public_port, path),
            headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, dict(resp.headers), json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read())

    def test_works_list_route(self):
        status, _headers, data = self.get("/api/v1/works?q=salaar&limit=20")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["total"], 2)
        salaar = self.work_by_id(data, self.salaar_a)
        self.assertEqual(salaar["post_count"], 3)

    def test_works_detail_route(self):
        status, _headers, data = self.get(
            "/api/v1/works/%d" % self.salaar_a)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["post_count"], 3)
        self.assertEqual(data["data"]["episode_guide"], [])

    def test_works_detail_missing_is_404(self):
        status, _headers, data = self.get("/api/v1/works/999999")
        self.assertEqual(status, 404, data)
        self.assertEqual(data["error"], "Work not found")

    def test_works_detail_bad_id_is_400(self):
        status, _headers, data = self.get("/api/v1/works/abc")
        self.assertEqual(status, 400, data)

    def test_posts_route_still_works(self):
        status, _headers, data = self.get("/api/v1/posts?q=salar&limit=20")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["did_you_mean"], "salaar")

    def test_no_origin_is_ever_reflected(self):
        # CORS stays closed: a browser origin gets no
        # Access-Control-Allow-Origin back, on either list route.
        for path in ("/api/v1/works?limit=5", "/api/v1/posts?limit=5"):
            _status, headers, _data = self.get(
                path, origin="https://evil.example")
            self.assertNotIn("Access-Control-Allow-Origin", headers, path)


if __name__ == "__main__":
    unittest.main()
