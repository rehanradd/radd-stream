"""Offline tests for the Stage-2 strict gate (resolver-stage2-strict-gate).

Every network step is a fake: no real host is contacted, no real link,
code or token appears anywhere in this file.

Rules protected here:
- a cached address is probed before it is served, on EVERY backend;
- an HTML page/shell/landing page, a dead file, a challenge page, or a
  transport failure is never a stream and never a download;
- a playlist plays but never downloads (segments are not a file);
- a resumable file and a non-resumable file both pass the gate (ranking
  below resumable is a ranking rule, not a gate rule);
- when one copy fails, the next copy in the same release wins; when a
  whole release fails, another release of the same post, same quality
  first, wins; when everything fails, both contracts answer
  no_playable_source — never a page;
- a freshly unwrapped address is probed before it is persisted or served;
- a probe size is never stored as a file size.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import current_hosts as ch
import fast_fetch as ff


def playlist_pass(renditions=((1920, 1080), (1280, 720))):
    return {"ok": True, "kind": "playlist",
            "mime": "application/vnd.apple.mpegurl", "size": None,
            "resumable": False, "renditions": list(renditions),
            "failure": None}


def file_pass(resumable=True):
    return {"ok": True, "kind": "file", "mime": "video/mp4",
            "size": 513, "resumable": resumable, "renditions": [],
            "failure": None}


def _fail(failure):
    return {"ok": False, "kind": None, "mime": None, "size": None,
            "resumable": False, "renditions": [], "failure": failure}


class FakeProbe:
    """URL -> verdict dict, recording every probe."""

    def __init__(self, mapping, default=None):
        self.mapping = mapping
        self.default = default or _fail("unverified")
        self.calls = []

    def __call__(self, url, referer, kind_hint):
        self.calls.append((url, referer, kind_hint))
        return dict(self.mapping.get(url, self.default))


class BlockedThenPass:
    """First probe (no referer) says blocked; the referer retry passes."""

    def __init__(self, passing):
        self.passing = passing
        self.calls = []

    def __call__(self, url, referer, kind_hint):
        self.calls.append((url, referer, kind_hint))
        if referer is None:
            return _fail("blocked")
        return dict(self.passing)


class GateAcceptTests(unittest.TestCase):
    def test_playlist_passes_watch_and_either_not_download(self):
        self.assertTrue(ff._stage2_accept(playlist_pass(), "watch"))
        self.assertTrue(ff._stage2_accept(playlist_pass(), "either"))
        self.assertFalse(ff._stage2_accept(playlist_pass(), "download"))

    def test_file_passes_every_caller(self):
        for want in ("watch", "download", "either"):
            self.assertTrue(ff._stage2_accept(file_pass(), want))
            self.assertTrue(ff._stage2_accept(file_pass(False), want))

    def test_every_failure_class_is_refused(self):
        for failure in ("html_shell", "dead_file", "challenge", "blocked",
                        "transport", "signed_gated", "rate_limited",
                        "empty_playlist", "unverified", "probe_error"):
            for want in ("watch", "download", "either"):
                self.assertFalse(ff._stage2_accept(_fail(failure), want),
                                 (failure, want))

    def test_non_dict_and_not_ok_are_refused(self):
        self.assertFalse(ff._stage2_accept(None, "watch"))
        self.assertFalse(ff._stage2_accept({"ok": False}, "download"))


class GateProbeTests(unittest.TestCase):
    def setUp(self):
        self._orig = ch.probe_media

    def tearDown(self):
        ch.probe_media = self._orig

    def test_pass_through_without_retry(self):
        probe = FakeProbe({"https://media.example.test/a.m3u8": playlist_pass()})
        ch.probe_media = probe
        verdict = ff._stage2_probe("https://media.example.test/a.m3u8")
        self.assertTrue(verdict["ok"])
        self.assertEqual(len(probe.calls), 1)

    def test_blocked_gets_one_referer_retry(self):
        probe = BlockedThenPass(playlist_pass())
        ch.probe_media = probe
        verdict = ff._stage2_probe("https://media.example.test/b.m3u8")
        self.assertTrue(verdict["ok"])
        self.assertEqual(len(probe.calls), 2)
        self.assertIsNone(probe.calls[0][1])
        self.assertEqual(probe.calls[1][1], ff._STAGE2_REFERER_RETRY)

    def test_non_blocked_failure_gets_no_retry(self):
        probe = FakeProbe({"https://media.example.test/c": _fail("html_shell")})
        ch.probe_media = probe
        verdict = ff._stage2_probe("https://media.example.test/c")
        self.assertFalse(verdict["ok"])
        self.assertEqual(len(probe.calls), 1)

    def test_hint_is_playlist_for_m3u8_else_file(self):
        self.assertEqual(ff._stage2_hint("https://h.test/x.m3u8?q=1"), "playlist")
        self.assertEqual(ff._stage2_hint("https://h.test/x.mkv"), "file")


PAGE = "https://media.example.test/page"
FILE = "https://media.example.test/file.mkv"
FILE2 = "https://media.example.test/file2.mkv"
PLAYLIST = "https://media.example.test/master.m3u8"


class ResolverGateTests(unittest.TestCase):
    def setUp(self):
        self._orig_probe = ch.probe_media
        self._orig_db = ff.DB_PATH
        self._orig_unwrap = ff.unwrap_fastdl
        self._orig_ttl = ff.probe_url_ttl
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "stage2.db")
        ff.DB_PATH = Path(self.db)
        ff.init_db()
        self.probe = FakeProbe({})
        ch.probe_media = self.probe
        with ff.get_db() as conn:
            conn.execute(
                "INSERT INTO posts (id, url, is_18_plus) VALUES (1, ?, 0)",
                ("https://site.example.test/post-1",))
            conn.execute(
                "INSERT INTO releases (id, post_id, quality) VALUES (10, 1, ?)",
                ("720p",))
            conn.execute(
                "INSERT INTO releases (id, post_id, quality) VALUES (11, 1, ?)",
                ("720p",))
            conn.execute(
                "INSERT INTO releases (id, post_id, quality) VALUES (12, 1, ?)",
                ("1080p",))

    def tearDown(self):
        ch.probe_media = self._orig_probe
        ff.unwrap_fastdl = self._orig_unwrap
        ff.probe_url_ttl = self._orig_ttl
        ff.DB_PATH = self._orig_db
        self._tmp.cleanup()

    def _row(self, rid, release, source_url, final_url, service="unknown-svc",
             is_temporary=0, last_checked=None, file_size=999999):
        with ff.get_db() as conn:
            conn.execute(
                "INSERT INTO download_sources (id, release_id, source_name, "
                "service, source_url, final_url, is_temporary, status, "
                "is_resumable, mime_type, file_size_bytes, last_checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, NULL, ?, ?)",
                (rid, release, "copy", service, source_url, final_url,
                 is_temporary, file_size, last_checked))

    def _resolve(self, rid, **kw):
        return ff.resolve_live_source(rid, **kw)

    def test_cached_html_page_refused_on_both_contracts(self):
        self._row(10, 10, PAGE, PAGE)
        self.probe.mapping[PAGE] = _fail("html_shell")
        for kw in ({"want": "watch"}, {"v2": True, "want": "download"}):
            res = self._resolve(10, **kw)
            self.assertFalse(res.get("success"), kw)
            self.assertEqual(res.get("code"), "no_playable_source", kw)
            self.assertNotEqual(res.get("url"), PAGE, kw)

    def test_cached_dead_file_refused(self):
        self._row(10, 10, FILE, FILE)
        self.probe.mapping[FILE] = _fail("dead_file")
        res = self._resolve(10, want="watch")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("code"), "no_playable_source")

    def test_cached_file_passes_and_keeps_stored_size(self):
        self._row(10, 10, FILE, FILE)
        self.probe.mapping[FILE] = file_pass(resumable=True)
        res = self._resolve(10, want="watch")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("url"), FILE)
        self.assertTrue(res.get("cached"))
        self.assertTrue(res.get("is_resumable"))
        self.assertEqual(res.get("mime_type"), "video/mp4")
        # The probe's Range byte count (513) is not a file size: the
        # stored value must survive untouched.
        self.assertEqual(res.get("file_size_bytes"), 999999)

    def test_cached_playlist_plays_but_never_downloads(self):
        self._row(10, 10, PLAYLIST, PLAYLIST)
        self.probe.mapping[PLAYLIST] = playlist_pass()
        watch = self._resolve(10, want="watch")
        self.assertTrue(watch.get("success"))
        self.assertEqual(watch.get("url"), PLAYLIST)
        refused = self._resolve(10, want="download")
        self.assertFalse(refused.get("success"))
        self.assertEqual(refused.get("code"), "no_playable_source")

    def test_non_resumable_file_passes_the_gate(self):
        self._row(10, 10, FILE, FILE)
        self.probe.mapping[FILE] = file_pass(resumable=False)
        for want in ("watch", "download"):
            res = self._resolve(10, want=want)
            self.assertTrue(res.get("success"), want)
            self.assertFalse(res.get("is_resumable"), want)

    def test_backup_wins_after_failure_in_same_release(self):
        self._row(10, 10, PAGE, PAGE)
        self._row(11, 10, FILE, FILE)
        self.probe.mapping[PAGE] = _fail("html_shell")
        self.probe.mapping[FILE] = file_pass(resumable=True)
        res = self._resolve(10, want="watch")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("url"), FILE)
        self.assertTrue(res.get("failover"))
        self.assertEqual(res.get("failover_row_id"), 11)

    def test_all_copies_fail_in_one_release(self):
        self._row(10, 10, PAGE, PAGE)
        self._row(11, 10, PAGE, PAGE)
        self.probe.mapping[PAGE] = _fail("html_shell")
        res = self._resolve(10, want="watch")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("code"), "no_playable_source")

    def test_cross_release_prefers_same_quality(self):
        # Release 10 fails; release 12 (1080p) has the smaller row id but
        # release 11 (720p, same quality) must win.
        self._row(10, 10, PAGE, PAGE)
        self._row(30, 12, FILE2, FILE2)
        self._row(31, 11, FILE, FILE)
        self.probe.mapping[PAGE] = _fail("html_shell")
        self.probe.mapping[FILE] = file_pass(resumable=True)
        self.probe.mapping[FILE2] = file_pass(resumable=True)
        res = self._resolve(10, want="watch")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("url"), FILE)
        self.assertEqual(res.get("failover_row_id"), 31)

    def test_fresh_unwrap_page_is_discarded(self):
        self._row(10, 10, "https://fastdl.example.test/embed/abc", PAGE,
                 service="fastdl", is_temporary=1,
                 last_checked="2020-01-01 00:00:00")
        ff.unwrap_fastdl = lambda url: (PAGE, "res", 1)
        self.probe.mapping[PAGE] = _fail("html_shell")
        res = self._resolve(10, want="watch")
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("code"), "no_playable_source")

    def test_fresh_unwrap_file_is_served(self):
        self._row(10, 10, "https://fastdl.example.test/embed/abc", PAGE,
                 service="fastdl", is_temporary=1,
                 last_checked="2020-01-01 00:00:00")
        ff.unwrap_fastdl = lambda url: (FILE, "res", 1)
        ff.probe_url_ttl = lambda url: (None, {"reason": "no_directive"})
        self.probe.mapping[FILE] = file_pass(resumable=False)
        res = self._resolve(10, want="watch")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("url"), FILE)

    def test_stale_pass_keeps_stale_flag_stale_fail_refuses(self):
        # A temporary row whose last check is old must re-resolve; with
        # no unwrap branch and no siblings, the stale address itself is
        # probed last.
        self._row(10, 10, PAGE, FILE, is_temporary=1,
                 last_checked="2020-01-01 00:00:00")
        self.probe.mapping[FILE] = file_pass(resumable=True)
        res = self._resolve(10, want="watch")
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("stale"))
        self.assertEqual(res.get("url"), FILE)
        self.probe.mapping[FILE] = _fail("dead_file")
        res2 = self._resolve(10, want="watch")
        self.assertFalse(res2.get("success"))
        self.assertEqual(res2.get("code"), "no_playable_source")
        self.assertEqual(res2.get("reason"), "stale_probe_failed")


if __name__ == "__main__":
    unittest.main()
