#!/usr/bin/env python3
"""Offline tests for `media_search.py` — the by-media matcher.

Three things had to be proven, in this order:

1. **Honesty.** A hint the ledger cannot answer is reported as `unknown_on`, never
   as agreement. That is the whole design: a score that silently rewarded empty
   rows would rank a blank work above a described one.
2. **The bridge.** Runtime and rungs live in `cat_works`/`cat_releases`, reached
   through `cat_work_sites.post_id`. A fixture built by the real projector (rather
   than hand-drawn `cat_*` rows) is what proves that column is where the v1↔v2 join
   actually lives — `posts.canonical_key` matches nothing there.
3. **The edge.** Nothing this endpoint returns may carry provenance, adult rows may
   not appear, and a request with no title is refused rather than answered with a
   list that would mean nothing.

    python3 -S Fast_Fetch/test_media_search.py
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.resolve()))

import catalog_v2          # noqa: E402
import fast_fetch          # noqa: E402
import media_search        # noqa: E402
import redact              # noqa: E402
import viewer              # noqa: E402

NEEDLE = "clicknupload"     # one of redact's own needles, not an invented word
_BASELINE_NEEDLES = redact.needles()
_BASELINE_TEXT_NEEDLES = redact.text_needles()


class Fixture(unittest.TestCase):
    """Real ledger → real `catalog_v2` projection, so the evidence this module reads
    is evidence the projector actually writes."""

    def setUp(self):
        redact.set_needles(_BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.addCleanup(redact.set_needles, _BASELINE_NEEDLES, _BASELINE_TEXT_NEEDLES)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "catalog.db"
        for patcher in (mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
                        mock.patch.object(viewer, "DB_PATH", self.db_path)):
            patcher.start()
            self.addCleanup(patcher.stop)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)

    def ingest(self, *, title, site="somecdn.site", is_18_plus=0,
               release_title=None, languages='["Hindi"]'):
        label = release_title if release_title is not None else f"{title} 120min 1080p"
        # The projector takes the rung from the release row's `quality` and only
        # falls back to the label, so a fixture that disagrees with itself would
        # test the fallback rather than the bridge. Keep them tolding the same story.
        rung = media_search.normalize_resolution(label)
        slug = title.lower().replace(" ", "-")
        data = {
            "url": f"https://{site}/movie/{slug}/",
            "slug": slug,
            "title": f"{title} ({2024})",
            "clean_title": title,
            "year": 2024,
            "content_type": "movie",
            "poster_url": "https://cdn/poster.jpg",
            "genres": '["Action"]',
            "synopsis": f"{title} synopsis",
            "is_18_plus": is_18_plus,
            "source_site": site,
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(title, 2024),
            "releases": [{"release_title": label, "quality": rung,
                          "codec": "x264", "size": "1.5GB", "languages": languages,
                          "season": "", "episode": "", "intermediate_url": "",
                          "origin_url": "", "source_site": site,
                          "sources": [{"source_url": "https://cdn.example/one.mp4",
                                       "quality": rung, "status": "active"}]}],
        }
        fast_fetch.save_scraped_data(data, enrich_metadata=False, ensure_db=False)
        self.conn.commit()
        catalog_v2.project(self.conn, rev=1, verbose=False)
        self.conn.commit()

    def search(self, **kw):
        return media_search.search_by_media(self.conn, **kw)

    def only(self, result):
        self.assertEqual(result["total"], 1, result)
        return result["results"][0]


class Helpers(unittest.TestCase):
    def test_dimensions_and_words_reduce_to_the_same_rung(self):
        for value in ("1920x1080", "1080p", "FULL HD", "fhd"):
            self.assertEqual(media_search.normalize_resolution(value), "1080p", value)
        for value in ("3840x2160", "2160p", "4K", "UHD"):
            self.assertEqual(media_search.normalize_resolution(value), "2160p", value)
        self.assertEqual(media_search.normalize_resolution("1280x720"), "720p")
        self.assertEqual(media_search.normalize_resolution("SD"), "480p")

    def test_an_unreadable_rung_is_no_rung(self):
        for value in ("", None, "web-dl", "x265", "1920", "taller than wide"):
            self.assertEqual(media_search.normalize_resolution(value), "", repr(value))

    def test_a_height_between_two_rungs_is_labeled_by_the_ladder_not_invented(self):
        self.assertEqual(media_search.normalize_resolution("1440x1080"), "1080p")
        # The 0.9 step is deliberate: a 1000-row print is a re-encoded 1080p, not a
        # 720p, and 1280x720 stays 720p because 720 is under 1080 * 0.9.
        self.assertEqual(media_search.normalize_resolution("1780x1000"), "1080p")
        self.assertEqual(media_search.normalize_resolution("1280x720"), "720p")
        self.assertEqual(media_search.normalize_resolution("640x360"), "")

    def test_duration_agrees_only_within_the_tolerance(self):
        matches = media_search.duration_matches
        self.assertIs(matches(120, 120 * 60), True)
        self.assertIs(matches(120, 135 * 60), True)         # 15% is the window
        self.assertIs(matches(120, 140 * 60), False)
        self.assertIs(matches(120, 90 * 60), False)

    def test_an_unanswerable_duration_is_none_not_false(self):
        matches = media_search.duration_matches
        for runtime in (None, "", 0, -5, "not a number"):
            self.assertIsNone(matches(runtime, 7200), runtime)
        self.assertIsNone(matches(120, None))
        self.assertIsNone(matches(120, 0))


class EvidenceBridge(Fixture):
    def test_the_projector_actually_writes_the_evidence_this_reads(self):
        """If this fails, the bridge below is testing a fixture, not the catalog."""
        self.ingest(title="Bridge Check")
        row = self.conn.execute(
            """
            SELECT w.runtime_minutes AS runtime, r.resolution AS resolution,
                   w.languages AS languages, r.audio_languages AS audio
            FROM cat_work_sites cs
            JOIN cat_works w ON w.id = cs.work_id
            JOIN cat_releases r ON r.work_id = w.id
            """).fetchone()
        self.assertIsNotNone(row, "the projector produced no cat_work_sites row")
        self.assertEqual(row["runtime"], 120)
        self.assertEqual(media_search.normalize_resolution(row["resolution"]), "1080p")
        spoken = " ".join(str(row[k] or "") for k in ("languages", "audio")).lower()
        self.assertIn("hindi", spoken)

    def test_canonical_key_is_not_the_bridge(self):
        """The wrong join is the bug this module exists to avoid: it answers zero rows."""
        self.ingest(title="Bridge Check")
        joined = self.conn.execute(
            "SELECT COUNT(*) FROM cat_works w WHERE w.work_key IN"
            " (SELECT canonical_key FROM posts)").fetchone()[0]
        self.assertEqual(joined, 0)


class Scoring(Fixture):
    def test_a_work_the_hints_agree_with_is_ranked_above_one_that_only_exists(self):
        self.ingest(title="Alpha Film", release_title="Alpha Film 120min 1080p")
        self.ingest(title="Beta Film", release_title="Beta Film 60min 480p")
        result = self.search(title="Film", duration_s=120 * 60, resolution="1080p")
        self.assertEqual([r["clean_title"] for r in result["results"]],
                         ["Alpha Film", "Beta Film"])
        top = result["results"][0]
        self.assertEqual(sorted(top["matched_on"]), ["duration_s", "resolution"])
        self.assertEqual(top["mismatched_on"], [])

    def test_a_contradicted_hint_is_reported_not_silently_dropped(self):
        self.ingest(title="Alpha Film", release_title="Alpha Film 120min 480p")
        item = self.only(self.search(title="Alpha", resolution="1080p"))
        self.assertEqual(item["mismatched_on"], ["resolution"])
        self.assertEqual(item["matched_on"], [])
        self.assertEqual(item["resolutions"], ["480p"])

    def test_a_hint_the_ledger_cannot_answer_is_unknown_never_matched(self):
        """The core honesty rule: an empty row must not be credited with agreement."""
        self.ingest(title="Blank Film", release_title="Blank Film")
        item = self.only(self.search(title="Blank", duration_s=9999, resolution="2160p"))
        self.assertEqual(sorted(item["unknown_on"]), ["duration_s", "resolution"])
        self.assertEqual(item["matched_on"], [])
        self.assertEqual(item["mismatched_on"], [])

    def test_agreement_beats_the_popularity_the_ledger_would_have_shown(self):
        """Beta has three times the mirrors and is the wrong answer; agreement wins."""
        self.ingest(title="Alpha Film", release_title="Alpha Film 120min 1080p")
        self.ingest(title="Beta Film", release_title="Beta Film 300min 480p")
        beta = int(self.conn.execute(
            "SELECT id FROM posts WHERE clean_title = 'Beta Film'").fetchone()["id"])
        beta_release = int(self.conn.execute(
            "SELECT id FROM releases WHERE post_id = ?", (beta,)).fetchone()["id"])
        for n in range(3):
            self.conn.execute(
                "INSERT INTO download_sources (release_id, source_url, service, status)"
                " VALUES (?, ?, 'hubcloud_10g', 'active')",
                (beta_release, f"https://mirror{n}.example/{n}.mp4"))
        self.conn.commit()
        result = self.search(title="Film", duration_s=120 * 60, resolution="1080p")
        self.assertEqual([r["clean_title"] for r in result["results"]],
                         ["Alpha Film", "Beta Film"])
        self.assertEqual(result["results"][1]["mismatched_on"],
                         ["duration_s", "resolution"])

    def test_audio_language_matches_a_substring_of_the_stored_list(self):
        self.ingest(title="Tongue Film", languages='["Hindi", "Tamil"]')
        item = self.only(self.search(title="Tongue", audio_language="tamil"))
        self.assertEqual(item["matched_on"], ["audio_language"])
        miss = self.only(self.search(title="Tongue", audio_language="punjabi"))
        self.assertEqual(miss["mismatched_on"], ["audio_language"])


class EdgeContract(Fixture):
    def test_no_title_is_refused_instead_of_answered_with_noise(self):
        self.ingest(title="Alpha Film")
        for blank in ("", "   ", None):
            result = self.search(title=blank, duration_s=120 * 60)
            self.assertFalse(result["success"])
            self.assertEqual(result["results"], [])
            self.assertIn("title", result["error"].lower())

    def test_an_adult_work_is_absent_not_marked(self):
        self.ingest(title="Hidden Film", is_18_plus=1)
        result = self.search(title="Hidden", duration_s=120 * 60)
        self.assertEqual(result["results"], [])
        self.assertEqual(result["total"], 0)

    def test_a_public_row_carries_no_provenance_key_or_needle(self):
        self.ingest(title="Leaky Film", site=f"{NEEDLE}.site")
        result = self.search(title="Leaky", duration_s=120 * 60, resolution="1080p")
        blob = repr(result).lower()
        self.assertNotIn(NEEDLE, blob)
        for item in result["results"]:
            leaked = set(item) & redact.PROVENANCE
            self.assertEqual(leaked, set(), sorted(leaked))

    def test_full_is_the_only_shape_that_carries_the_upstream(self):
        """Loopback may see where a row came from; the public edge may not."""
        self.ingest(title="Loopback Film", site=f"{NEEDLE}.site")
        public = self.search(title="Loopback")["results"][0]
        for key in ("source_site", "url", "slug"):
            self.assertNotIn(key, public)
        item = self.search(title="Loopback", full=True)["results"][0]
        self.assertEqual(item["source_site"], f"{NEEDLE}.site")
        self.assertNotIn(NEEDLE, str(item["clean_title"]).lower())

    def test_the_answer_names_the_tolerance_and_the_window_it_searched(self):
        self.ingest(title="Meta Film")
        result = self.search(title="Meta", duration_s=120 * 60)
        self.assertEqual(result["duration_tolerance"], media_search.DURATION_TOLERANCE)
        self.assertEqual(result["query"]["duration_s"], 120 * 60)
        self.assertEqual(result["query"]["resolution"], None)
        self.assertGreaterEqual(result["candidates"], 1)

    def test_a_garbage_duration_is_ignored_rather_than_poisoning_the_rank(self):
        self.ingest(title="Robust Film")
        for junk in ("abc", -5, 0, None, ""):
            result = self.search(title="Robust", duration_s=junk)
            self.assertTrue(result["success"], junk)
            self.assertEqual(result["query"]["duration_s"], None, junk)
            self.assertEqual(result["results"][0]["unknown_on"], [])


class RouteShape(Fixture):
    """The part `media_search` cannot own: what `viewer` bolts on around it.

    A by-media row must be the same shape as a `q=` row, or the app needs a second
    renderer for it — and a second renderer is where provenance reappears.
    """

    def call(self, **kw):
        return viewer.api_v1_search_by_media(**kw)

    def test_an_enriched_row_carries_our_own_art_handle_and_a_work_ref(self):
        self.ingest(title="Shaped Film")
        item = self.call(query="Shaped", duration_s=120 * 60)["results"][0]
        self.assertTrue(item["work_ref"], "the account surface needs a handle it minted")
        poster = item["poster_url"]
        self.assertTrue(poster.startswith("/api/v1/art?"), poster)
        self.assertNotIn("cdn/poster.jpg", poster)
        self.assertNotIn("somecdn.site", poster)

    def test_the_row_shape_is_the_shape_a_keyword_search_already_returns(self):
        self.ingest(title="Shaped Film")
        by_media = self.call(query="Shaped", duration_s=120 * 60)["results"][0]
        by_word = viewer.api_v1_get_posts(query="Shaped")["results"][0]
        extra = set(by_media) - set(by_word)
        self.assertEqual(extra, {"runtime_minutes", "resolutions", "matched_on",
                                 "mismatched_on", "unknown_on"})
        self.assertEqual(set(by_word) - set(by_media), set())

    def test_a_request_without_a_title_is_the_refusal_not_a_200_full_of_noise(self):
        self.ingest(title="Shaped Film")
        refused = self.call(duration_s=120 * 60)
        self.assertFalse(refused["success"])
        self.assertEqual(refused["results"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
