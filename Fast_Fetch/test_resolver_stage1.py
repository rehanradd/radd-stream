"""Offline tests for the Stage-1 resolver (resolver-stage1-current-hosts).

Every network step is a fake: no real host is contacted, no real link,
code or token appears anywhere in this file. The fakes only prove the
shape of the chain — embed page, API answer, helper answer, player page —
and the ranking rules that sit on top of it.

Rules protected here:
- rank by BACKEND, never by front-end label (a front-end is not a backup);
- only a passing capped probe can win; a stamped-dead copy that passes
  fresh heals, a stamped-active copy that fails never wins;
- failure classes are honest: 429 is rate-limited, transport is not death,
  only a 404/410 on the media itself is a dead file;
- an HTML shell, a landing page or a spinner is never a video file;
- download names come from mime, and a known video suffix still earns
  its real extension instead of `.bin` when the mime is unknown.
"""

import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import current_hosts as ch
import viewer


def _result(status, body=b""):
    if isinstance(body, str):
        body = body.encode()
    return ch.FetchResult(status=status, body=body)


class FakeFetch:
    """URL -> FetchResult, recording every call for the assertions."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, url, referer=None, method="GET", range_bytes=None,
                 data=None, **_kw):
        self.calls.append((url, method))
        if url in self.mapping:
            return self.mapping[url]
        return _result(404, b"not found")


class FakeProbe:
    """URL -> verdict dict, recording probed URLs."""

    def __init__(self, mapping, default=None):
        self.mapping = mapping
        self.default = default or {"ok": False, "failure": "unverified"}
        self.urls = []

    def __call__(self, url, referer, kind_hint):
        self.urls.append(url)
        return dict(self.mapping.get(url, self.default))


def playlist_pass(renditions=((1920, 1080), (1280, 720))):
    return {"ok": True, "kind": "playlist", "mime": "application/vnd.apple.mpegurl",
            "size": None, "resumable": False, "renditions": list(renditions),
            "failure": None}


def file_pass(resumable=True):
    return {"ok": True, "kind": "file", "mime": "video/mp4",
            "size": 123456, "resumable": resumable, "renditions": [],
            "failure": None}


class BackendClassificationTests(unittest.TestCase):
    def test_label_is_never_the_backend(self):
        # A front-end label on the row must not decide the backend: the
        # saved link's real host does.
        self.assertEqual(
            ch.classify_backend(
                "https://streams.iqsmartgames.com/embed/movie/1", "gd-mirror"),
            "streamhg")

    def test_modiplay_is_a_front_end_not_a_backend(self):
        self.assertEqual(
            ch.classify_backend("https://example-modiplay.example/embed/1"),
            "modiplay")

    def test_vidbolt_and_filmu_share_one_independence_group(self):
        self.assertEqual(ch.independence_group("vidbolt"),
                         ch.independence_group("vidly"))
        self.assertEqual(ch.independence_group("vidbolt"), "rousav")

    def test_iqsmart_and_modiplay_streamhg_are_not_independent(self):
        self.assertEqual(ch.independence_group("streamhg"), "streamhg")

    def test_filesforever_is_not_a_stage1_backend(self):
        self.assertEqual(ch.classify_backend("https://filesforever.link/embed/x"),
                         "filesforever")
        result = ch.resolve_copy("https://filesforever.link/embed/x",
                                 fetch=FakeFetch({}), probe=FakeProbe({}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"], "unknown_backend")


class ProbeClassificationTests(unittest.TestCase):
    def _verdict(self, status, ctype, body, headers=None, url=""):
        if isinstance(body, str):
            body = body.encode()
        result = ch.FetchResult(status=status, content_type=ctype,
                                body=body, headers=headers or {})
        return ch.classify_probe(result, url)

    def test_html_shell_is_never_a_file(self):
        verdict = self._verdict(
            200, "text/html", b"<html><body>landing page</body></html>")
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["failure"], "html_shell")

    def test_playlist_with_renditions_passes(self):
        verdict = self._verdict(
            200, "application/vnd.apple.mpegurl",
            b"#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1920x1080\nseg.m3u8\n")
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["renditions"], [(1920, 1080)])

    def test_segment_only_playlist_passes_without_renditions(self):
        verdict = self._verdict(
            200, "application/vnd.apple.mpegurl",
            b"#EXTM3U\n#EXTINF:10,\nseg0.ts\n")
        self.assertTrue(verdict["ok"])

    def test_206_with_ranges_is_resumable(self):
        verdict = self._verdict(206, "video/mp4", b"\x00\x00\x00\x18",
                                headers={"accept-ranges": "bytes"})
        self.assertTrue(verdict["ok"])
        self.assertTrue(verdict["resumable"])

    def test_200_video_without_ranges_is_playable_not_resumable(self):
        verdict = self._verdict(200, "video/x-matroska", b"\x1a\x45\xdf\xa3")
        self.assertTrue(verdict["ok"])
        self.assertFalse(verdict["resumable"])

    def test_429_is_rate_limited_not_dead(self):
        verdict = self._verdict(429, "text/html", b"slow down")
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["failure"], "rate_limited")

    def test_transport_failure_is_not_death(self):
        verdict = self._verdict(0, "", b"")
        self.assertEqual(verdict["failure"], "transport")

    def test_404_on_media_is_a_dead_file(self):
        verdict = self._verdict(404, "text/html", b"not found")
        self.assertEqual(verdict["failure"], "dead_file")

    def test_403_challenge_marker_is_not_death(self):
        verdict = self._verdict(
            403, "text/html", b"Attention Required! | Cloudflare")
        self.assertEqual(verdict["failure"], "challenge")

    def test_403_missing_key_is_signed_gated_not_dead(self):
        verdict = self._verdict(
            403, "application/xml",
            b"<Error><Code>MissingKey</Code></Error>")
        self.assertEqual(verdict["failure"], "signed_gated")

    def test_cached_playlist_404_is_dead_not_stale(self):
        verdict = self._verdict(404, "text/html", b"gone")
        self.assertEqual(verdict["failure"], "dead_file")


class PackerTests(unittest.TestCase):
    def test_unpack_substitutes_words(self):
        packed = ("eval(function(p,a,c,k,e,d){return p}"
                  "('0',36,1,'hello'.split('|'),0,{}))")
        self.assertEqual(ch.unpack_packer(packed), "hello")

    def test_plain_page_has_no_packer(self):
        self.assertEqual(ch.unpack_packer("<html>no player here</html>"), "")


class UnwrapTests(unittest.TestCase):
    def test_vidrift_direct_streams_become_candidates(self):
        page = json.dumps({"orionStreams": [
            {"url": "/api/orion/abc/master.m3u8"},
            {"url": "https://cdn.example/file.mp4"}]})
        fetch = FakeFetch({
            "https://embed.vidrift.net/embed/movie/1": _result(200, page)})
        probe = FakeProbe({
            "https://embed.vidrift.net/api/orion/abc/master.m3u8":
                playlist_pass()})
        result = ch.resolve_copy("https://embed.vidrift.net/embed/movie/1",
                                 fetch=fetch, probe=probe)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "vidrift")
        self.assertEqual(result["kind"], "playlist")

    def test_vidrift_null_streams_is_no_streams_not_an_error(self):
        fetch = FakeFetch({
            "https://embed.vidrift.net/embed/movie/1":
                _result(200, '{"orionStreams":null}')})
        result = ch.resolve_copy("https://embed.vidrift.net/embed/movie/1",
                                 fetch=fetch, probe=FakeProbe({}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"], "no_streams")

    def test_vidbolt_resolve_answer_becomes_candidate(self):
        fetch = FakeFetch({
            "https://vidbolt.xyz/movie/1":
                _result(200, 'var q="type=movie&id=42"'),
            "https://vidbolt.xyz/api/resolve?type=movie&id=42":
                _result(200, json.dumps({"stream": {"server": "orion",
                    "sources": [{"url": "https://cdn.example/master.m3u8"}]}}))})
        probe = FakeProbe({"https://cdn.example/master.m3u8": playlist_pass()})
        result = ch.resolve_copy("https://vidbolt.xyz/movie/1",
                                 fetch=fetch, probe=probe)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "vidbolt")

    def test_filmu_movie_resolves_but_series_is_refused(self):
        movie_fetch = FakeFetch({
            "https://embed.filmu.in/movie/1":
                _result(200, "https://cdn.example/media/abc/index.m3u8")})
        probe = FakeProbe({
            "https://cdn.example/media/abc/index.m3u8": playlist_pass()})
        movie = ch.resolve_copy("https://embed.filmu.in/movie/1",
                                fetch=movie_fetch, probe=probe)
        self.assertTrue(movie["ok"])
        self.assertEqual(movie["backend"], "vidly")
        series = ch.resolve_copy("https://embed.filmu.in/tv/1/1/1",
                                 fetch=FakeFetch({}), probe=FakeProbe({}))
        self.assertFalse(series["ok"])
        self.assertEqual(series["failure"], "series_server_unverified")

    def test_vibuxer_whitespace_in_saved_url_is_trimmed(self):
        fetch = FakeFetch({
            "https://vibuxer.com/e/abc":
                _result(200, 'links = {"hls4": "https://cdn.example/m.m3u8"}')})
        probe = FakeProbe({"https://cdn.example/m.m3u8": playlist_pass()})
        result = ch.resolve_copy("https://vibuxer.com/e/ abc ",
                                 fetch=fetch, probe=probe)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "vibuxer")

    def test_pixeldrain_is_a_resumable_file(self):
        probe = FakeProbe({
            "https://pixeldrain.com/api/file/abc": file_pass(resumable=True)})
        result = ch.resolve_copy("https://pixeldrain.com/u/abc",
                                 fetch=FakeFetch({}), probe=probe)
        self.assertTrue(result["ok"])
        self.assertTrue(result["resumable"])
        self.assertFalse(result["temporary"])

    def test_fastdl_probes_the_decoded_file_not_the_page(self):
        fetch = FakeFetch({
            "https://fastdl.beer/embed.php?download=abc":
                _result(200, 'var reurl = "https://fastdl.beer/dl.php?'
                            'link=https%3A%2F%2Fcdn.example%2Ff.mkv";')})
        probe = FakeProbe({"https://cdn.example/f.mkv":
                           file_pass(resumable=False)})
        result = ch.resolve_copy("https://fastdl.beer/embed.php?download=abc",
                                 fetch=fetch, probe=probe)
        self.assertTrue(result["ok"])
        self.assertFalse(result["resumable"])
        self.assertEqual(probe.urls, ["https://cdn.example/f.mkv"])

    def test_modiplay_streamhg_backend_is_streamhg(self):
        embed = "https://example-modiplay.example/embed/movie/1"
        proxy = ("https://example-modiplay.example/proxy.php?p=streamhg"
                 "&c=abc123&title=x&site_ref=&noredirect=1")
        fetch = FakeFetch({
            embed: _result(200, '<a href="/proxy.php?p=streamhg&amp;c=abc123">'),
            proxy: _result(200, "/stream_proxy.php?url="
                           "https://cdn.example/master.m3u8")})
        probe = FakeProbe({
            "https://example-modiplay.example/stream_proxy.php?url="
            "https://cdn.example/master.m3u8": playlist_pass()})
        result = ch.resolve_copy(embed, fetch=fetch, probe=probe)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "streamhg")
        self.assertEqual(result["group"], "streamhg")

    def test_iqsmart_chain_reaches_a_hanerix_master(self):
        embed = "https://streams.iqsmartgames.com/embed/movie/1?key=TESTKEY"
        api = "https://streams.iqsmartgames.com/mymovieapi?tmdb=42&key=TESTKEY"
        helper_body = json.dumps({
            "sources": {"sh": {"siteUrl": "https://hanerix.com/e/"}},
            "mresult": base64.b64encode(
                json.dumps({"sh": "MASTERCODE"}).encode()).decode()})
        fetch = FakeFetch({
            embed: _result(200, 'let FinalID = "42"; let idType = "tmdb";'),
            api: _result(200, json.dumps(
                {"success": True,
                 "data": [{"filename": "t", "fileslug": "SLUG1"}]})),
            "https://pro.iqsmartgames.com/evid/SLUG1":
                _result(200, 'const sid = "SID1";'),
            "https://pro.iqsmartgames.com/embedhelper2.php":
                _result(200, helper_body),
            "https://hanerix.com/e/MASTERCODE":
                _result(200, 'links = {"hls4": "https://cdn.example/m.m3u8"}')})
        probe = FakeProbe({"https://cdn.example/m.m3u8": playlist_pass()})
        result = ch.resolve_copy(embed, fetch=fetch, probe=probe)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backend"], "streamhg")


class RankingTests(unittest.TestCase):
    def _copy(self, backend, group, kind="playlist", resumable=False,
              renditions=((1920, 1080),)):
        return {"ok": True, "backend": backend, "group": group, "kind": kind,
                "url": "https://cdn.example/" + backend, "mime": "video/mp4",
                "size": None, "resumable": resumable,
                "renditions": list(renditions), "failure": None,
                "failure_dead": False, "temporary": True}

    def test_failed_copies_are_never_ranked(self):
        dead = {"ok": False, "backend": "pixeldrain", "group": "pixeldrain",
                "kind": None, "url": None, "mime": None, "size": None,
                "resumable": False, "renditions": [], "failure": "dead_file",
                "failure_dead": True, "temporary": False}
        live = self._copy("fastdl-beer", "fastdl-beer", kind="file")
        winner, _backups = ch.select_download([dead, live])
        self.assertEqual(winner["backend"], "fastdl-beer")

    def test_stamped_dead_copy_that_passes_fresh_can_win(self):
        rows = [{"id": 5, "release_id": 9, "source_url":
                 "https://embed.vidrift.net/embed/movie/1",
                 "final_url": "https://embed.vidrift.net/embed/movie/1",
                 "service": "vidrift", "status": "dead"}]
        fetch = FakeFetch({
            "https://embed.vidrift.net/embed/movie/1": _result(
                200, json.dumps({"orionStreams": [
                    {"url": "/api/orion/abc/master.m3u8"}]}))})
        probe = FakeProbe({
            "https://embed.vidrift.net/api/orion/abc/master.m3u8":
                playlist_pass()})
        rel = ch.resolve_release(rows, fetch=fetch, probe=probe)
        self.assertIsNotNone(rel["watch_winner"])
        self.assertEqual(rel["watch_winner"]["backend"], "vidrift")

    def test_watch_keeps_one_copy_per_independence_group(self):
        a = self._copy("streamhg", "streamhg")
        b = self._copy("vidrift", "vidrift")
        c = self._copy("vidbolt", "rousav")
        d = self._copy("vidly", "rousav", renditions=((1280, 720),))
        winner, backups = ch.select_watch([a, b, c, d])
        groups = [winner["group"]] + [x["group"] for x in backups]
        self.assertEqual(len(groups), len(set(groups)))
        # vidbolt and filmu share the rousav group: at most one survives.
        self.assertEqual(groups.count("rousav"), 1)

    def test_release_failover_skips_a_failed_winner(self):
        rows = [
            {"id": 1, "release_id": 9,
             "source_url": "https://embed.vidrift.net/embed/movie/1",
             "final_url": "https://embed.vidrift.net/embed/movie/1",
             "service": "vidrift", "status": "active"},
            {"id": 2, "release_id": 9, "source_url": "https://vidbolt.xyz/movie/1",
             "final_url": "https://vidbolt.xyz/movie/1",
             "service": "vidbolt", "status": "active"},
        ]
        fetch = FakeFetch({
            "https://embed.vidrift.net/embed/movie/1":
                _result(200, '{"orionStreams":null}'),
            "https://vidbolt.xyz/movie/1":
                _result(200, 'var q="type=movie&id=42"'),
            "https://vidbolt.xyz/api/resolve?type=movie&id=42":
                _result(200, json.dumps({"stream": {"server": "orion",
                    "sources": [{"url": "https://cdn.example/m.m3u8"}]}}))})
        probe = FakeProbe({"https://cdn.example/m.m3u8": playlist_pass()})
        rel = ch.resolve_release(rows, fetch=fetch, probe=probe)
        self.assertEqual(rel["watch_winner"]["backend"], "vidbolt")
        self.assertEqual(len(rel["failures"]), 1)

    def test_all_copies_failed_means_no_winner(self):
        rows = [{"id": 1, "release_id": 9,
                 "source_url": "https://embed.vidrift.net/embed/movie/1",
                 "final_url": "https://embed.vidrift.net/embed/movie/1",
                 "service": "vidrift", "status": "active"}]
        fetch = FakeFetch({
            "https://embed.vidrift.net/embed/movie/1":
                _result(200, '{"orionStreams":null}')})
        rel = ch.resolve_release(rows, fetch=fetch, probe=FakeProbe({}))
        self.assertIsNone(rel["watch_winner"])
        self.assertIsNone(rel["download_winner"])

    def test_download_prefers_resumable_and_excludes_vidrift_files(self):
        pd = self._copy("pixeldrain", "pixeldrain", kind="file", resumable=True,
                        renditions=[])
        fd = self._copy("fastdl-beer", "fastdl-beer", kind="file",
                        resumable=False, renditions=[])
        vf = self._copy("vidrift", "vidrift", kind="file", resumable=True,
                        renditions=[])
        winner, backups = ch.select_download([fd, vf, pd])
        self.assertEqual(winner["backend"], "pixeldrain")
        self.assertEqual([b["backend"] for b in backups], ["fastdl-beer"])


class DownloadNameTests(unittest.TestCase):
    def test_known_mime_keeps_its_extension(self):
        self.assertTrue(viewer.download_filename("tok123", "video/x-matroska")
                        .endswith(".mkv"))
        self.assertTrue(viewer.download_filename("tok123", "video/mp4")
                        .endswith(".mp4"))

    def test_unknown_mime_with_mkv_suffix_is_not_bin(self):
        name = viewer.download_filename("tok123", "application/octet-stream",
                                        "https://cdn.example/f.mkv")
        self.assertTrue(name.endswith(".mkv"), name)

    def test_unknown_mime_without_suffix_stays_bin(self):
        name = viewer.download_filename("tok123", "text/plain")
        self.assertTrue(name.endswith(".bin"), name)


if __name__ == "__main__":
    unittest.main()
