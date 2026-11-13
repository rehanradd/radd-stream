#!/usr/bin/env python3
"""
test_iptv_org_import.py — offline unit tests for the iptv-org Live TV importer.

No live network: every fetch goes through a fake opener serving fixture
bytes, every probe through a fake probe_many returning canned ProbeResults.
A real socket attempt would fail the run (no opener/probe is ever real).
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import import_iptv_org as iptv  # noqa: E402
import live_tv  # noqa: E402
from link_health import ProbeResult  # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────

M3U_FIXTURE = """#EXTM3U
#EXTINF:-1 tvg-id="7News.pk@SD" tvg-logo="https://i.imgur.com/7news.png" group-title="News",7 News (720p)
https://sscsott.com/7news/live/index.m3u8
#EXTINF:-1 tvg-id="ARYMusik.pk@SD" tvg-logo="https://example.com/arymusik.png" http-referrer="https://live.arydigital.tv/" group-title="Music",ARY Musik (1080p)
#EXTVLCOPT:http-referrer=https://live.arydigital.tv/
https://arymusik.aryzap.com/main.m3u8
#EXTINF:-1 tvg-id="HumNews.pk@SD" tvg-logo="https://example.com/humnews.png" group-title="News",Hum News
http://103.86.135.164:9981/stream/channelid/1522598263?profile=pass&ticket=8F210F02E7EF3471D45EFD9B293E0E07CE3532BF
#EXTINF:-1 tvg-id="GeoTV.pk@SD" tvg-logo="https://example.com/geotv.png" group-title="Entertainment",Geo TV [Geo-blocked]
https://geo.example.com/live.m3u8
#EXTINF:-1 tvg-id="DeadChannel.pk@SD" tvg-logo="https://example.com/dead.png" group-title="News",Dead Channel
https://dead.example.com/live.m3u8
#EXTINF:-1 tvg-id="HttpChannel.pk@SD" tvg-logo="https://example.com/http.png" group-title="News",HTTP Channel
http://http.example.com/live/playlist.m3u8
#EXTINF:-1 tvg-id="BareIP.pk@SD" tvg-logo="https://example.com/bareip.png" group-title="News",Bare IP Channel
http://115.42.65.142:9981/stream/channelid/113328724
#EXTINF:-1 tvg-id="Mystery.pk@SD" tvg-logo="https://example.com/mystery.png" group-title="Undefined",Mystery Channel
https://mystery.example.com/live.m3u8
#EXTINF:-1 tvg-id="MovieChannel.pk@SD" tvg-logo="https://example.com/movie.png" group-title="Movies",Movie Channel
https://movie.example.com/live.m3u8
#EXTINF:-1 tvg-id="NoLogo.pk@SD" group-title="News",No Logo Channel
https://nologo.example.com/live.m3u8
#EXTINF:-1 tvg-id="LateNight.pk@SD" tvg-logo="https://example.com/late.png" group-title="Entertainment",Late Night [Not 24/7]
https://late.example.com/live.m3u8
#EXTINF:-1 tvg-id="NoUrl.pk@SD" tvg-logo="https://example.com/nourl.png" group-title="News",No URL Channel
#EXTINF:-1 tvg-id="AfterNoUrl.pk@SD" tvg-logo="https://example.com/after.png" group-title="News",After No URL
https://after.example.com/live.m3u8
"""

API_STREAMS = [
    {"channel": "DunyaNews.pk", "feed": "SD", "title": "Dunya News",
     "url": "https://dunya.example.com/live.m3u8", "quality": "720p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "GodStandsTV.pk", "feed": "Urdu", "title": "God Stands TV",
     "url": "https://godstands.example.com/ur.m3u8", "quality": "576p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "GodStandsTV.pk", "feed": "Arabic", "title": "God Stands TV",
     "url": "https://godstands.example.com/ar.m3u8", "quality": "576p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "ARYMusik.pk", "feed": "SD", "title": "ARY Musik",
     "url": "https://arymusik.aryzap.com/main.m3u8", "quality": "1080p",
     "labels": [], "user_agent": None,
     "referrer": "https://live.arydigital.tv/"},
    {"channel": "HumNews.pk", "feed": "SD", "title": "Hum News",
     "url": "http://103.86.135.164:9981/stream/x?profile=pass&ticket=ABCDEF",
     "quality": None, "labels": [], "user_agent": None, "referrer": None},
    {"channel": "LateNight.pk", "feed": "SD", "title": "Late Night (720p)",
     "url": "https://late.example.com/live.m3u8", "quality": None,
     "labels": ["Not 24/7"], "user_agent": None, "referrer": None},
    {"channel": "NsfwChannel.pk", "feed": "SD", "title": "NSFW Channel",
     "url": "https://nsfw.example.com/live.m3u8", "quality": "720p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "ClosedChannel.pk", "feed": "SD", "title": "Closed Channel",
     "url": "https://closed.example.com/live.m3u8", "quality": "720p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": None, "feed": None, "title": "Orphan Stream",
     "url": "https://orphan.example.com/live.m3u8", "quality": "720p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "NoCat.pk", "feed": "SD", "title": "No Cat Channel",
     "url": "https://nocat.example.com/live.m3u8", "quality": "720p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "NoLogo.pk", "feed": "SD", "title": "No Logo Channel",
     "url": "https://nologo2.example.com/live.m3u8", "quality": "720p",
     "labels": [], "user_agent": None, "referrer": None},
    {"channel": "GeoTV.pk", "feed": "SD", "title": "Geo TV",
     "url": "https://geo.example.com/live.m3u8", "quality": "1080p",
     "labels": ["Geo-blocked"], "user_agent": None, "referrer": None},
]

API_CHANNELS = [
    {"id": "DunyaNews.pk", "name": "Dunya News", "country": "PK",
     "categories": ["news"], "is_nsfw": False, "closed": None},
    {"id": "GodStandsTV.pk", "name": "God Stands TV", "country": "PK",
     "categories": ["religious"], "is_nsfw": False, "closed": None},
    {"id": "ARYMusik.pk", "name": "ARY Musik", "country": "PK",
     "categories": ["music"], "is_nsfw": False, "closed": None},
    {"id": "HumNews.pk", "name": "Hum News", "country": "PK",
     "categories": ["news"], "is_nsfw": False, "closed": None},
    {"id": "LateNight.pk", "name": "Late Night", "country": "PK",
     "categories": ["entertainment"], "is_nsfw": False, "closed": None},
    {"id": "NsfwChannel.pk", "name": "NSFW Channel", "country": "PK",
     "categories": ["entertainment"], "is_nsfw": True, "closed": None},
    {"id": "ClosedChannel.pk", "name": "Closed Channel", "country": "PK",
     "categories": ["news"], "is_nsfw": False, "closed": "2020-01-01"},
    {"id": "NoCat.pk", "name": "No Cat Channel", "country": "PK",
     "categories": [], "is_nsfw": False, "closed": None},
    {"id": "NoLogo.pk", "name": "No Logo Channel", "country": "PK",
     "categories": ["news"], "is_nsfw": False, "closed": None},
    {"id": "GeoTV.pk", "name": "Geo TV", "country": "PK",
     "categories": ["entertainment"], "is_nsfw": False, "closed": None},
]

API_FEEDS = [
    {"channel": "DunyaNews.pk", "id": "SD", "languages": ["urd"]},
    {"channel": "GodStandsTV.pk", "id": "Urdu", "languages": ["urd"]},
    {"channel": "GodStandsTV.pk", "id": "Arabic", "languages": ["ara"]},
    {"channel": "ARYMusik.pk", "id": "SD", "languages": ["urd"]},
    {"channel": "LateNight.pk", "id": "SD", "languages": ["urd", "eng"]},
    {"channel": "NoCat.pk", "id": "SD", "languages": ["urd"]},
    {"channel": "NoLogo.pk", "id": "SD", "languages": ["urd"]},
    {"channel": "GeoTV.pk", "id": "SD", "languages": ["urd"]},
]

API_LOGOS = [
    {"channel": "DunyaNews.pk", "feed": "SD", "in_use": True,
     "url": "https://example.com/dunya.png"},
    {"channel": "GodStandsTV.pk", "feed": "Urdu", "in_use": True,
     "url": "https://example.com/god-ur.png"},
    {"channel": "GodStandsTV.pk", "feed": "Arabic", "in_use": True,
     "url": "https://example.com/god-ar.png"},
    {"channel": "ARYMusik.pk", "feed": "SD", "in_use": True,
     "url": "https://example.com/arymusik.png"},
    {"channel": "HumNews.pk", "feed": "SD", "in_use": True,
     "url": "https://example.com/humnews.png"},
    {"channel": "LateNight.pk", "feed": "SD", "in_use": True,
     "url": "https://example.com/late.png"},
    {"channel": "GeoTV.pk", "feed": "SD", "in_use": True,
     "url": "https://example.com/geotv.png"},
    {"channel": "NoCat.pk", "feed": "SD", "in_use": True,
     "url": "https://example.com/nocat.png"},
]

M3U_INDEX_FIXTURE = {
    "NoCat.pk": {"category": "religious", "logo_url": "https://example.com/nocat.png"},
    "NoLogo.pk": {"category": "news", "logo_url": "https://example.com/nologo-m3u.png"},
}


def _registry_fixture():
    return {
        "version": "1.0",
        "updated_at": "2026-11-11T15:11:30Z",
        "source": "fixture",
        "note": "fixture registry",
        "channels": [
            {"id": 1, "name": "Dunya News", "category": "news",
             "country": "PK", "language": "ur",
             "logo_url": "https://example.com/dunya.png",
             "stream_url": "https://dunya.example.com/live.m3u8",
             "source": "official", "verified_at": "2026-11-11T00:00:00Z",
             "enabled": True, "disabled_reason": ""},
            {"id": 2, "name": "Old Channel", "category": "news",
             "country": "PK", "language": "ur",
             "logo_url": "https://example.com/old.png",
             "stream_url": "https://old.example.com/live.m3u8",
             "source": "iptv-org", "verified_at": "2026-11-11T00:00:00Z",
             "enabled": True, "disabled_reason": ""},
        ],
    }


def _result(url, ok=False, status=0, protocol="unusable", error="",
            redirects_to=""):
    return ProbeResult(url=url, ok=ok, http_status=status,
                       protocol=protocol, error=error,
                       redirects_to=redirects_to)


def _alive(url):
    return _result(url, ok=True, status=200, protocol="hls")


def _dead(url):
    return _result(url, ok=False, status=404, protocol="unusable",
                   error="http_404")


def _unknown(url, error="timeout"):
    return _result(url, ok=False, status=0, protocol="unusable", error=error)


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    """Serves fixture bytes by URL suffix. Any other URL raises."""

    def __init__(self, routes):
        self.routes = routes

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                return _FakeResponse(payload)
        raise AssertionError("unexpected fetch: %s" % url)


def _api_opener():
    routes = {
        "streams.json": json.dumps(API_STREAMS).encode(),
        "channels.json": json.dumps(API_CHANNELS).encode(),
        "feeds.json": json.dumps(API_FEEDS).encode(),
        "logos.json": json.dumps(API_LOGOS).encode(),
        "pk.m3u": M3U_FIXTURE.encode(),
        "in.m3u": b"#EXTM3U\n",
    }
    return _FakeOpener(routes)


class _FakeProbe:
    """Canned ProbeResults by URL; anything unlisted is unknown/timeout."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, links, **kwargs):
        self.calls.append([link["url"] for link in links])
        out = []
        for link in links:
            url = link["url"]
            out.append(self.mapping.get(url, _unknown(url)))
        return out


# ── M3U parsing ───────────────────────────────────────────────────────────

class ParseM3uTests(unittest.TestCase):
    def setUp(self):
        self.entries, self.excluded = iptv.parse_m3u(M3U_FIXTURE, "PK")
        self.by_name = {e.name: e for e in self.entries}

    def test_parses_the_usable_entries(self):
        names = sorted(self.by_name)
        self.assertEqual(names, [
            "7 News", "ARY Musik", "After No URL", "Bare IP Channel",
            "Dead Channel", "Geo TV", "HTTP Channel", "Late Night",
            "Movie Channel",
        ])

    def test_quality_suffix_moves_off_the_name(self):
        news = self.by_name["7 News"]
        self.assertEqual(news.quality, "720p")
        self.assertEqual(news.category, "news")
        self.assertEqual(news.language, "ur")

    def test_referrer_from_attr_and_vlcopt(self):
        musik = self.by_name["ARY Musik"]
        self.assertEqual(musik.referrer, "https://live.arydigital.tv/")
        self.assertEqual(musik.quality, "1080p")

    def test_ticketed_url_excluded(self):
        reasons = {e["name"]: e["reason"] for e in self.excluded}
        self.assertIn("Hum News", reasons)
        self.assertTrue(reasons["Hum News"].startswith("ticketed"))

    def test_geo_blocked_label_kept_on_the_entry(self):
        geo = self.by_name["Geo TV"]
        self.assertEqual(geo.labels, ["Geo-blocked"])
        self.assertEqual(geo.name, "Geo TV")

    def test_not_247_label_kept(self):
        self.assertEqual(self.by_name["Late Night"].labels, ["Not 24/7"])

    def test_undefined_group_excluded_not_guessed(self):
        reasons = {e["name"]: e["reason"] for e in self.excluded}
        self.assertIn("Mystery Channel", reasons)
        self.assertTrue(reasons["Mystery Channel"].startswith("no_category"))

    def test_movies_group_maps_to_movies(self):
        self.assertEqual(self.by_name["Movie Channel"].category, "movies")

    def test_no_logo_excluded(self):
        reasons = {e["name"]: e["reason"] for e in self.excluded}
        self.assertIn("No Logo Channel", reasons)
        self.assertTrue(reasons["No Logo Channel"].startswith("no_logo"))

    def test_entry_without_url_is_dropped_but_next_entry_survives(self):
        self.assertNotIn("No URL Channel", self.by_name)
        self.assertIn("After No URL", self.by_name)


# ── API parsing ───────────────────────────────────────────────────────────

class ParseApiTests(unittest.TestCase):
    def setUp(self):
        data = {"streams": copy.deepcopy(API_STREAMS),
                "channels": copy.deepcopy(API_CHANNELS),
                "feeds": copy.deepcopy(API_FEEDS),
                "logos": copy.deepcopy(API_LOGOS)}
        self.entries, self.excluded, self.counts = iptv.parse_api(
            data, ("PK",), M3U_INDEX_FIXTURE)
        self.by_name = {e.name: e for e in self.entries}

    def test_joins_country_category_language_logo(self):
        dunya = self.by_name["Dunya News"]
        self.assertEqual((dunya.country, dunya.category, dunya.language),
                         ("PK", "news", "ur"))
        self.assertEqual(dunya.logo_url, "https://example.com/dunya.png")
        self.assertEqual(dunya.quality, "720p")

    def test_multi_feed_channels_get_distinct_display_names(self):
        self.assertIn("God Stands TV (Urdu)", self.by_name)
        self.assertIn("God Stands TV (Arabic)", self.by_name)
        self.assertEqual(self.by_name["God Stands TV (Urdu)"].language, "ur")
        self.assertEqual(self.by_name["God Stands TV (Arabic)"].language, "ar")

    def test_referrer_kept_on_the_entry(self):
        self.assertEqual(self.by_name["ARY Musik"].referrer,
                         "https://live.arydigital.tv/")

    def test_ticketed_nsfw_closed_and_orphan_excluded(self):
        names = {e["name"] for e in self.excluded}
        self.assertIn("Hum News", names)
        self.assertIn("NSFW Channel", names)
        self.assertIn("Closed Channel", names)
        self.assertEqual(self.counts["no_channel"], 1)
        self.assertEqual(self.counts["ticketed"], 1)
        self.assertEqual(self.counts["nsfw"], 1)
        self.assertEqual(self.counts["closed"], 1)

    def test_no_category_rescued_by_m3u_index(self):
        self.assertIn("No Cat Channel", self.by_name)
        self.assertEqual(self.by_name["No Cat Channel"].category, "religious")

    def test_no_logo_rescued_by_m3u_index(self):
        self.assertIn("No Logo Channel", self.by_name)
        self.assertEqual(self.by_name["No Logo Channel"].logo_url,
                         "https://example.com/nologo-m3u.png")

    def test_quality_from_title_suffix_when_field_empty(self):
        self.assertEqual(self.by_name["Late Night"].quality, "720p")
        self.assertEqual(self.by_name["Late Night"].labels, ["Not 24/7"])

    def test_geo_blocked_label_kept(self):
        self.assertEqual(self.by_name["Geo TV"].labels, ["Geo-blocked"])

    def test_unrescuable_no_category_is_excluded(self):
        data = {"streams": copy.deepcopy(API_STREAMS),
                "channels": copy.deepcopy(API_CHANNELS),
                "feeds": copy.deepcopy(API_FEEDS),
                "logos": copy.deepcopy(API_LOGOS)}
        entries, excluded, _ = iptv.parse_api(data, ("PK",), None)
        names = {e.name for e in entries}
        self.assertNotIn("No Cat Channel", names)
        self.assertNotIn("No Logo Channel", names)


# ── verdicts ──────────────────────────────────────────────────────────────

class VerdictTests(unittest.TestCase):
    def test_alive_needs_ok_and_hls(self):
        self.assertEqual(iptv.classify_verdict(_alive("https://x/y.m3u8")),
                         "alive")
        self.assertEqual(
            iptv.classify_verdict(
                _result("https://x/y.m3u8", ok=True, status=200,
                        protocol="progressive")),
            "unknown")

    def test_dead_is_404_410_or_dns_only(self):
        self.assertEqual(iptv.classify_verdict(_dead("https://x/y.m3u8")),
                         "dead")
        self.assertEqual(iptv.classify_verdict(
            _result("https://x/y.m3u8", status=410, error="http_410")), "dead")
        self.assertEqual(iptv.classify_verdict(
            _result("https://x/y.m3u8", error="dns")), "dead")

    def test_expired_only_with_signature_params(self):
        ticketed = "https://x/y.m3u8?ticket=ABCDEF"
        self.assertEqual(iptv.classify_verdict(
            _result(ticketed, status=403, error="http_403"), ticketed),
            "expired")
        self.assertEqual(iptv.classify_verdict(
            _result("https://x/y.m3u8", status=403, error="http_403")),
            "unknown")

    def test_unknown_covers_timeout_429_5xx_and_blocklist(self):
        for error, status in (("timeout", 0), ("http_429", 429),
                              ("http_500", 500), ("blocklisted", 0),
                              ("blocked_target", 0)):
            self.assertEqual(iptv.classify_verdict(
                _result("https://x/y.m3u8", status=status, error=error)),
                "unknown")

    def test_has_session_params(self):
        self.assertTrue(iptv.has_session_params(
            "https://x/y?profile=pass&ticket=ABC"))
        self.assertTrue(iptv.has_session_params(
            "https://x/y?signature=ABC&expires=123"))
        self.assertTrue(iptv.has_session_params(
            "https://x/y?token=ABC&expires=123"))
        self.assertFalse(iptv.has_session_params("https://x/y?token=ABC"))
        self.assertFalse(iptv.has_session_params("https://x/y.m3u8"))

    def test_storable_url(self):
        entry_url = "https://x/y.m3u8"
        self.assertEqual(iptv.storable_url(entry_url, _alive(entry_url)),
                         entry_url)
        # Plain http entry: the probe's https .m3u8 landing URL is stored.
        landing = _alive("http://x/y.m3u8")
        landing = ProbeResult(url=landing.url, ok=True, http_status=200,
                              protocol="hls",
                              redirects_to="https://cdn.example.com/y.m3u8")
        self.assertEqual(iptv.storable_url("http://x/y.m3u8", landing),
                         "https://cdn.example.com/y.m3u8")
        # A landing URL with session params is never stored.
        ticketed = ProbeResult(url="http://x/y.m3u8", ok=True,
                               http_status=200, protocol="hls",
                               redirects_to="https://cdn.example.com/y.m3u8"
                               "?ticket=ABC")
        self.assertEqual(iptv.storable_url("http://x/y.m3u8", ticketed), "")
        # No .m3u8 anywhere: nothing storable.
        self.assertEqual(
            iptv.storable_url("http://115.42.65.142:9981/stream/1",
                              _alive("http://115.42.65.142:9981/stream/1")),
            "")

    def test_category_mapping(self):
        self.assertEqual(iptv.map_category(["General"]), "entertainment")
        self.assertEqual(iptv.map_category(["Business"]), "news")
        self.assertEqual(iptv.map_category(["Movies"]), "movies")
        self.assertEqual(iptv.map_category(["Kids;Religious"]), "kids")
        self.assertEqual(iptv.map_category(["Undefined"]), "")
        self.assertEqual(iptv.map_category([]), "")
        # Second-pass mappings from the live data (2026-11-13): education
        # is its own allowed category; classic films are movies; parliament
        # and weather are news; science is education; teleshopping, motoring
        # and outdoor fall under entertainment.
        self.assertEqual(iptv.map_category(["Classic"]), "movies")
        self.assertEqual(iptv.map_category(["Legislative"]), "news")
        self.assertEqual(iptv.map_category(["Weather"]), "news")
        self.assertEqual(iptv.map_category(["Education"]), "education")
        self.assertEqual(iptv.map_category(["Education", "Outdoor"]),
                         "education")
        self.assertEqual(iptv.map_category(["Science"]), "education")
        self.assertEqual(iptv.map_category(["Shop"]), "entertainment")
        self.assertEqual(iptv.map_category(["Auto"]), "entertainment")
        self.assertEqual(iptv.map_category(["Outdoor"]), "entertainment")


# ── dedupe + probing ──────────────────────────────────────────────────────

def _entry(name, url, referrer="", quality="720p"):
    return iptv.IptvEntry(name=name, country="PK", category="news",
                          language="ur",
                          logo_url="https://example.com/logo.png",
                          stream_url=url, quality=quality,
                          referrer=referrer)


class ProbeCandidatesTests(unittest.TestCase):
    def test_best_mirror_first(self):
        grouped = iptv.group_candidates([
            _entry("Ch", "http://a.example.com/x", quality="576p"),
            _entry("Ch", "https://b.example.com/x.m3u8", quality="1080p"),
            _entry("Ch", "https://c.example.com/x.m3u8", quality="720p",
                   referrer="https://ref.example.com/"),
        ])
        urls = [e.stream_url for e in grouped[("ch", "PK")]]
        # Clean mirrors first (only they can resolve the key in v1), then
        # https/.m3u8/quality among them; the Referer-gated mirror is last.
        self.assertEqual(urls, ["https://b.example.com/x.m3u8",
                                "http://a.example.com/x",
                                "https://c.example.com/x.m3u8"])

    def test_dead_best_mirror_falls_through_to_next(self):
        grouped = iptv.group_candidates([
            _entry("Ch", "https://a.example.com/x.m3u8", quality="1080p"),
            _entry("Ch", "https://b.example.com/x.m3u8", quality="720p"),
        ])
        probe = _FakeProbe({
            "https://a.example.com/x.m3u8": _dead("https://a.example.com/x.m3u8"),
            "https://b.example.com/x.m3u8": _alive("https://b.example.com/x.m3u8"),
        })
        resolved, report = iptv.probe_candidates(grouped, probe)
        self.assertEqual(resolved[("ch", "PK")][1],
                         "https://b.example.com/x.m3u8")
        self.assertEqual(len(probe.calls), 2)
        self.assertEqual(probe.calls[0],
                         ["https://a.example.com/x.m3u8"])
        self.assertEqual(probe.calls[1],
                         ["https://b.example.com/x.m3u8"])

    def test_referer_gated_excluded_but_would_play_recorded(self):
        grouped = iptv.group_candidates([
            _entry("Ch", "https://a.example.com/x.m3u8",
                   referrer="https://ref.example.com/"),
        ])
        probe = _FakeProbe({
            "https://a.example.com/x.m3u8": _alive("https://a.example.com/x.m3u8"),
        })
        resolved, report = iptv.probe_candidates(grouped, probe)
        self.assertEqual(resolved, {})
        self.assertEqual(report["referer_would_play"], 1)
        self.assertEqual(len(report["excluded"]), 1)
        self.assertTrue(report["excluded"][0]["reason"].startswith(
            "referrer required"))

    def test_referer_best_does_not_hide_a_clean_mirror(self):
        grouped = iptv.group_candidates([
            _entry("Ch", "https://a.example.com/x.m3u8",
                   referrer="https://ref.example.com/", quality="1080p"),
            _entry("Ch", "https://b.example.com/x.m3u8", quality="720p"),
        ])
        probe = _FakeProbe({
            "https://a.example.com/x.m3u8": _alive("https://a.example.com/x.m3u8"),
            "https://b.example.com/x.m3u8": _alive("https://b.example.com/x.m3u8"),
        })
        resolved, report = iptv.probe_candidates(grouped, probe)
        # The clean mirror wins and resolves the key, so the Referer-gated
        # mirror is never probed at all: nothing to exclude, nothing to
        # record as would-play.
        self.assertEqual(resolved[("ch", "PK")][1],
                         "https://b.example.com/x.m3u8")
        self.assertEqual(report["referer_would_play"], 0)
        self.assertEqual(report["excluded"], [])

    def test_alive_but_no_storable_url_tries_next_mirror(self):
        grouped = iptv.group_candidates([
            _entry("Ch", "http://115.42.65.142:9981/stream/1", quality="1080p"),
            _entry("Ch", "https://b.example.com/x.m3u8", quality="720p"),
        ])
        probe = _FakeProbe({
            "http://115.42.65.142:9981/stream/1":
                _alive("http://115.42.65.142:9981/stream/1"),
            "https://b.example.com/x.m3u8": _alive("https://b.example.com/x.m3u8"),
        })
        resolved, report = iptv.probe_candidates(grouped, probe)
        self.assertEqual(resolved[("ch", "PK")][1],
                         "https://b.example.com/x.m3u8")

    def test_limit_caps_the_keys_probed(self):
        grouped = iptv.group_candidates([
            _entry("One", "https://one.example.com/x.m3u8"),
            _entry("Two", "https://two.example.com/x.m3u8"),
        ])
        probe = _FakeProbe({
            "https://one.example.com/x.m3u8": _alive("https://one.example.com/x.m3u8"),
            "https://two.example.com/x.m3u8": _alive("https://two.example.com/x.m3u8"),
        })
        resolved, _ = iptv.probe_candidates(grouped, probe, limit=1)
        self.assertEqual(sorted(resolved), [("one", "PK")])
        self.assertEqual(probe.calls, [["https://one.example.com/x.m3u8"]])


# ── registry merge ────────────────────────────────────────────────────────

class MergeTests(unittest.TestCase):
    def setUp(self):
        self.now = "2026-11-13T22:00:00Z"

    def _merge(self, registry, resolved, existing_results):
        return iptv.merge_into_registry(registry, resolved,
                                        existing_results, self.now)

    def test_adds_new_channels_with_next_ids(self):
        registry = _registry_fixture()
        entry = _entry("New Channel", "https://new.example.com/x.m3u8")
        entry.category = "movies"
        summary = self._merge(registry, {("new channel", "PK"): (
            entry, "https://new.example.com/x.m3u8",
            _alive("https://new.example.com/x.m3u8"))}, {})
        self.assertEqual(summary["added"], 1)
        added = registry["channels"][-1]
        self.assertEqual(added["id"], 3)
        self.assertEqual(added["source"], "iptv-org")
        self.assertTrue(added["enabled"])
        self.assertEqual(added["verified_at"], self.now)
        self.assertEqual(added["category"], "movies")
        live_tv.validate_registry(registry)  # raises on failure

    def test_matched_channel_is_refreshed_not_duplicated(self):
        registry = _registry_fixture()
        entry = _entry("Dunya News", "https://dunya.example.com/live.m3u8")
        summary = self._merge(registry, {("dunya news", "PK"): (
            entry, "https://dunya.example.com/live.m3u8",
            _alive("https://dunya.example.com/live.m3u8"))},
            {"https://dunya.example.com/live.m3u8":
                _alive("https://dunya.example.com/live.m3u8")})
        self.assertEqual(len(registry["channels"]), 2)
        self.assertEqual(summary["existing_kept"], 1)
        self.assertEqual(registry["channels"][0]["verified_at"], self.now)

    def test_dead_stored_url_is_repaired_from_candidate(self):
        registry = _registry_fixture()
        entry = _entry("Old Channel", "https://new-old.example.com/x.m3u8")
        summary = self._merge(registry, {("old channel", "PK"): (
            entry, "https://new-old.example.com/x.m3u8",
            _alive("https://new-old.example.com/x.m3u8"))},
            {"https://old.example.com/live.m3u8":
                _dead("https://old.example.com/live.m3u8")})
        self.assertEqual(summary["existing_repaired"], 1)
        self.assertEqual(registry["channels"][1]["stream_url"],
                         "https://new-old.example.com/x.m3u8")
        self.assertEqual(len(registry["channels"]), 2)

    def test_merge_summary_lists_rows_that_did_not_refresh(self):
        registry = _registry_fixture()
        summary = self._merge(registry, {}, {
            "https://dunya.example.com/live.m3u8":
                _alive("https://dunya.example.com/live.m3u8"),
            "https://old.example.com/live.m3u8":
                _dead("https://old.example.com/live.m3u8")})
        self.assertEqual(summary["existing_refreshed"], 1)
        not_refreshed = summary["existing_not_refreshed"]
        self.assertEqual(len(not_refreshed), 1)
        self.assertEqual(not_refreshed[0]["name"], "Old Channel")
        self.assertEqual(not_refreshed[0]["verdict"], "dead")

    def test_two_strikes_disable_an_iptv_org_row(self):
        registry = _registry_fixture()
        dead = {"https://old.example.com/live.m3u8":
                _dead("https://old.example.com/live.m3u8")}
        self._merge(registry, {}, dead)
        row = registry["channels"][1]
        self.assertTrue(row["enabled"])
        self.assertEqual(row["consecutive_failures"], 1)
        self._merge(registry, {}, dead)
        self.assertFalse(row["enabled"])
        self.assertEqual(row["consecutive_failures"], 2)
        self.assertTrue(row["disabled_reason"].startswith("unreachable: dead"))
        self.assertEqual(len(registry["channels"]), 2)

    def test_operator_row_is_never_disabled(self):
        registry = _registry_fixture()
        dead = {"https://dunya.example.com/live.m3u8":
                _dead("https://dunya.example.com/live.m3u8")}
        self._merge(registry, {}, dead)
        self._merge(registry, {}, dead)
        row = registry["channels"][0]
        self.assertTrue(row["enabled"])
        self.assertNotIn("consecutive_failures", row)

    def test_alive_probe_resets_strikes(self):
        registry = _registry_fixture()
        row = registry["channels"][1]
        row["consecutive_failures"] = 1
        self._merge(registry, {}, {"https://old.example.com/live.m3u8":
                                   _alive("https://old.example.com/live.m3u8")})
        self.assertNotIn("consecutive_failures", row)
        self.assertEqual(row["verified_at"], self.now)

    def test_repair_reenables_a_strike_disabled_row(self):
        registry = _registry_fixture()
        row = registry["channels"][1]
        row["enabled"] = False
        row["disabled_reason"] = "unreachable: dead (2 consecutive failed probes)"
        row["consecutive_failures"] = 2
        entry = _entry("Old Channel", "https://new-old.example.com/x.m3u8")
        self._merge(registry, {("old channel", "PK"): (
            entry, "https://new-old.example.com/x.m3u8",
            _alive("https://new-old.example.com/x.m3u8"))},
            {"https://old.example.com/live.m3u8":
                _dead("https://old.example.com/live.m3u8")})
        self.assertTrue(row["enabled"])
        self.assertEqual(row["disabled_reason"], "")

    def test_repair_never_reenables_an_operator_disabled_row(self):
        registry = _registry_fixture()
        row = registry["channels"][1]
        row["enabled"] = False
        row["disabled_reason"] = "disabled from panel"
        entry = _entry("Old Channel", "https://new-old.example.com/x.m3u8")
        self._merge(registry, {("old channel", "PK"): (
            entry, "https://new-old.example.com/x.m3u8",
            _alive("https://new-old.example.com/x.m3u8"))},
            {"https://old.example.com/live.m3u8":
                _dead("https://old.example.com/live.m3u8")})
        self.assertFalse(row["enabled"])
        self.assertEqual(row["disabled_reason"], "disabled from panel")
        self.assertEqual(row["stream_url"],
                         "https://new-old.example.com/x.m3u8")

    def test_merged_registry_validates(self):
        registry = _registry_fixture()
        entry = _entry("Geo TV", "https://geo.example.com/live.m3u8")
        entry.category = "entertainment"
        entry.labels = ["Geo-blocked"]
        entry.quality = "1080p"
        self._merge(registry, {("geo tv", "PK"): (
            entry, "https://geo.example.com/live.m3u8",
            _alive("https://geo.example.com/live.m3u8"))}, {})
        live_tv.validate_registry(registry)  # raises on failure
        added = registry["channels"][-1]
        self.assertEqual(added["labels"], ["Geo-blocked"])
        self.assertEqual(added["quality"], "1080p")


# ── end-to-end sync (fake network) ────────────────────────────────────────

class SyncTests(unittest.TestCase):
    def _write_registry(self, tmpdir):
        path = Path(tmpdir) / "live_tv_registry.json"
        path.write_text(json.dumps(_registry_fixture()), encoding="utf-8")
        return str(path)

    def _probe(self):
        mapping = {
            "https://dunya.example.com/live.m3u8":
                _alive("https://dunya.example.com/live.m3u8"),
            "https://old.example.com/live.m3u8":
                _dead("https://old.example.com/live.m3u8"),
            "https://godstands.example.com/ur.m3u8":
                _alive("https://godstands.example.com/ur.m3u8"),
            "https://godstands.example.com/ar.m3u8":
                _alive("https://godstands.example.com/ar.m3u8"),
            "https://arymusik.aryzap.com/main.m3u8":
                _alive("https://arymusik.aryzap.com/main.m3u8"),
            "https://late.example.com/live.m3u8":
                _alive("https://late.example.com/live.m3u8"),
            "https://geo.example.com/live.m3u8":
                _alive("https://geo.example.com/live.m3u8"),
            "https://nocat.example.com/live.m3u8":
                _alive("https://nocat.example.com/live.m3u8"),
            "https://nologo2.example.com/live.m3u8":
                _alive("https://nologo2.example.com/live.m3u8"),
        }
        return _FakeProbe(mapping)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_registry(tmpdir)
            before = Path(path).read_text(encoding="utf-8")
            summary = iptv.run_sync(path, source="api", countries=("PK",),
                                    dry_run=True, opener=_api_opener(),
                                    probe_fn=self._probe())
            self.assertFalse(summary["written"])
            self.assertEqual(Path(path).read_text(encoding="utf-8"), before)
            self.assertGreater(summary["resolved"], 0)

    def test_sync_writes_a_valid_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_registry(tmpdir)
            summary = iptv.run_sync(path, source="api", countries=("PK",),
                                    dry_run=False, opener=_api_opener(),
                                    probe_fn=self._probe())
            self.assertTrue(summary["written"])
            self.assertEqual(summary["used_source"], "api")
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            live_tv.validate_registry(data)  # raises on failure
            names = {c["name"] for c in data["channels"]}
            # Dunya News matched, not duplicated; God Stands feeds added.
            self.assertIn("God Stands TV (Urdu)", names)
            self.assertIn("God Stands TV (Arabic)", names)
            self.assertIn("Geo TV", names)
            self.assertEqual(len([c for c in data["channels"]
                                  if c["name"] == "Dunya News"]), 1)
            # ARY Musik is Referer-gated: never stored.
            self.assertNotIn("ARY Musik", names)
            # Hum News is ticketed: never stored.
            self.assertNotIn("Hum News", names)
            # The dead iptv-org row took one strike, still enabled.
            old = [c for c in data["channels"]
                   if c["name"] == "Old Channel"][0]
            self.assertTrue(old["enabled"])
            self.assertEqual(old["consecutive_failures"], 1)

    def test_sync_falls_back_to_m3u_when_the_api_fails(self):
        def failing_opener(req, timeout=None):
            if "api" in req.full_url:
                raise urllib.error.URLError("boom")
            return _FakeOpener(
                {"pk.m3u": M3U_FIXTURE.encode(),
                 "in.m3u": b"#EXTM3U\n"})(req, timeout)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_registry(tmpdir)
            mapping = {
                "https://sscsott.com/7news/live/index.m3u8":
                    _alive("https://sscsott.com/7news/live/index.m3u8"),
                "https://geo.example.com/live.m3u8":
                    _alive("https://geo.example.com/live.m3u8"),
                "https://movie.example.com/live.m3u8":
                    _alive("https://movie.example.com/live.m3u8"),
                "https://late.example.com/live.m3u8":
                    _alive("https://late.example.com/live.m3u8"),
                "https://after.example.com/live.m3u8":
                    _alive("https://after.example.com/live.m3u8"),
                "https://dunya.example.com/live.m3u8":
                    _alive("https://dunya.example.com/live.m3u8"),
                "https://old.example.com/live.m3u8":
                    _dead("https://old.example.com/live.m3u8"),
            }
            summary = iptv.run_sync(path, source="auto", countries=("PK",),
                                    dry_run=True, opener=failing_opener,
                                    probe_fn=_FakeProbe(mapping))
            self.assertEqual(summary["used_source"], "m3u")
            self.assertIn("api_error", summary)
            self.assertGreater(summary["resolved"], 0)

    def test_verify_and_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_registry(tmpdir)
            result = iptv.run_verify(path)
            self.assertEqual(result["channels"], 2)
            self.assertEqual(result["enabled"], 2)
            self.assertEqual(result["by_country"], {"PK": 2})
            self.assertEqual(result["by_source"],
                             {"official": 1, "iptv-org": 1})


if __name__ == "__main__":
    unittest.main()
