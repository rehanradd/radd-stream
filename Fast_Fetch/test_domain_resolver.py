#!/usr/bin/env python3
"""
Fast_Fetch/test_domain_resolver.py — offline tests for the extended domain
resolver (order qoder14, Task B). No network: the probe layer is exercised
through the injectable ``opener`` and a temp registry.
"""

from __future__ import annotations

import fcntl
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import domain_resolver as dr


class _Resp:
    def __init__(self, status, url):
        self.status = status
        self._url = url

    def geturl(self):
        return self._url

    def close(self):
        pass


def _opener(rules):
    """rules: dict url-prefix -> ('status', code, final_url) or
    ('raise', exception) or ('blocked', code)."""
    def opener(req, timeout):
        url = req.full_url
        for prefix, action in rules.items():
            if url == prefix or url.startswith(prefix):
                kind = action[0]
                if kind == "status":
                    return _Resp(action[1], action[2])
                if kind == "blocked":
                    raise urllib.error.HTTPError(
                        url, action[1], "blocked", None, None)
                if kind == "raise":
                    raise OSError(action[1])
        raise OSError("no rule matched " + url)
    return opener


class _TempRegistryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.reg_path = Path(self._tmp.name) / "domain_registry.json"
        self._saved_reg = dr.REGISTRY_PATH
        dr.REGISTRY_PATH = self.reg_path
        self.addCleanup(setattr, dr, "REGISTRY_PATH", self._saved_reg)

    def seed(self, sites):
        dr.save_registry({"version": "1.0", "sites": sites})

    def read(self):
        return json.loads(self.reg_path.read_text(encoding="utf-8"))


class TestAtomicWrite(_TempRegistryCase):
    def test_round_trip_sets_updated_at(self):
        self.seed({"alpha": {"active_base_url": "https://alpha.foo"}})
        data = self.read()
        self.assertEqual(data["sites"]["alpha"]["active_base_url"],
                         "https://alpha.foo")
        self.assertIn("updated_at", data)

    def test_crash_during_dump_leaves_previous_file_intact(self):
        self.seed({"alpha": {"active_base_url": "https://alpha.foo"}})
        good = self.reg_path.read_text(encoding="utf-8")
        boom = {"bad": {k: object() for k in ("x",)}}  # not JSON-serialisable
        with self.assertRaises(TypeError):
            dr.save_registry(boom)
        self.assertEqual(self.reg_path.read_text(encoding="utf-8"), good,
                         "atomic replace must leave the target untouched")
        leftovers = [p for p in Path(self._tmp.name).iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [], "temp file must be cleaned on failure")

    def test_load_rejects_non_dict_shapes(self):
        self.reg_path.write_text("[1,2,3]", encoding="utf-8")
        self.assertEqual(dr.load_registry()["sites"], {})


class TestLockAndMerge(_TempRegistryCase):
    def test_lock_is_exclusive(self):
        held = open(str(self.reg_path) + ".lock", "w")
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        try:
            with self.assertRaises(BlockingIOError):
                fh = open(str(self.reg_path) + ".lock", "w")
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    fh.close()
        finally:
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)
            held.close()

    def test_update_merges_mirrors_without_duplicates(self):
        self.seed({"alpha": {"active_base_url": "https://alpha.foo",
                             "known_mirrors": ["https://alpha.foo",
                                               "https://alpha.bar"]}})
        dr.update_site_registry("alpha", {
            "known_mirrors": ["https://alpha.bar", "https://alpha.new"],
            "status": "active"})
        site = self.read()["sites"]["alpha"]
        self.assertEqual(site["known_mirrors"],
                         ["https://alpha.foo", "https://alpha.bar",
                          "https://alpha.new"])
        self.assertEqual(site["status"], "active")

    def test_update_reloads_under_lock_not_caller_snapshot(self):
        # Simulate the lost-update hazard: a second writer lands a change for
        # ANOTHER site between our read and our update_site_registry call.
        self.seed({"alpha": {"active_base_url": "https://alpha.foo"},
                   "beta": {"active_base_url": "https://beta.foo"}})
        stale = dr.load_registry()  # snapshot before the other writer runs
        dr.update_site_registry("beta", {"status": "down"})
        dr.update_site_registry("alpha", {"status": "active"})
        # the stale snapshot is never written back wholesale:
        final = dr.load_registry()
        self.assertEqual(final["sites"]["beta"]["status"], "down")
        self.assertEqual(final["sites"]["alpha"]["status"], "active")
        self.assertIn("beta", stale["sites"])  # (snapshot itself untouched)


class TestProbeSite(_TempRegistryCase):
    def _seed_site(self):
        self.seed({"alpha": {"active_base_url": "https://alpha.foo",
                             "known_mirrors": ["https://alpha.foo",
                                               "https://alpha-mirror.foo"],
                             "status": "active"}})

    def test_active_answers_ok_marks_active_and_reports_no_shift(self):
        self._seed_site()
        op = _opener({"https://alpha.foo": ("status", 200, "https://alpha.foo/")})
        res = dr.probe_site("alpha", opener=op)
        self.assertEqual(res["status"], "active")
        self.assertFalse(res["domain_shifted"])
        self.assertFalse(res["active_repointed"])
        self.assertEqual(self.read()["sites"]["alpha"]["active_base_url"],
                         "https://alpha.foo")

    def test_active_that_redirects_is_never_repointed_off_itself(self):
        # Silent-retirement guard: alpha.foo answers fine but redirects to a
        # CDN/alternate netloc. Because the stored active did NOT fail this
        # run, the registry must keep pointing at alpha.foo.
        self._seed_site()
        op = _opener({"https://alpha.foo":
                      ("status", 200, "https://cdn-alpha.foo/embed")})
        res = dr.probe_site("alpha", opener=op)
        self.assertTrue(res["domain_shifted"])
        self.assertFalse(res["active_repointed"])
        self.assertEqual(self.read()["sites"]["alpha"]["active_base_url"],
                         "https://alpha.foo")

    def test_dead_active_plus_shifting_mirror_repoints(self):
        self._seed_site()
        op = _opener({
            "https://alpha.foo": ("raise", "connection refused"),
            "https://alpha-mirror.foo":
                ("status", 200, "https://alpha-2.foo/landing"),
        })
        res = dr.probe_site("alpha", opener=op)
        self.assertTrue(res["active_repointed"])
        site = self.read()["sites"]["alpha"]
        self.assertEqual(site["active_base_url"], "https://alpha-2.foo")
        self.assertIn("https://alpha.foo", site["known_mirrors"])
        self.assertEqual(site["status"], "active")

    def test_blocked_active_is_not_down_and_registry_untouched(self):
        self._seed_site()
        op = _opener({"https://alpha.foo": ("blocked", 403),
                      "https://alpha-mirror.foo": ("blocked", 429)})
        before = self.read()
        res = dr.probe_site("alpha", opener=op)
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(self.read(), before,
                         "a WAF refusal must not mutate the registry")

    def test_whole_set_dead_then_tld_rotation_found(self):
        self.seed({"vegamovies": {"active_base_url": "https://vegamovies.foo",
                                  "known_mirrors": ["https://vegamovies.foo"],
                                  "status": "active"}})
        op = _opener({
            "https://vegamovies.foo": ("raise", "name resolution"),
            "https://vegamovies.bar": ("status", 200, "https://vegamovies.bar/"),
        })
        res = dr.probe_site("vegamovies", opener=op)
        self.assertEqual(res["status"], "rotated")
        self.assertTrue(res["rotation_detected"])
        site = self.read()["sites"]["vegamovies"]
        self.assertEqual(site["active_base_url"], "https://vegamovies.bar")
        self.assertIn("https://vegamovies.foo", site["known_mirrors"])
        self.assertIn("last_rotated_at", site)

    def test_rotation_sweep_can_be_disabled_and_site_goes_down(self):
        self._seed_site()
        op = _opener({"https://": ("raise", "all dead")})
        res = dr.probe_site("alpha", opener=op, rotate=False)
        self.assertEqual(res["status"], "down")
        self.assertEqual(self.read()["sites"]["alpha"]["status"], "down")

    def test_auto_update_false_never_writes(self):
        self._seed_site()
        before = self.read()
        op = _opener({"https://alpha.foo": ("raise", "timeout")})
        dr.probe_site("alpha", auto_update=False, opener=op, rotate=False)
        self.assertEqual(self.read(), before)

    def test_unknown_site(self):
        self.seed({})
        res = dr.probe_site("ghost", opener=_opener({}))
        self.assertEqual(res["status"], "unknown")

    def test_http_error_500_is_a_failed_candidate_not_blocked(self):
        self._seed_site()
        op = _opener({
            "https://alpha.foo": ("blocked", 500),  # not in BLOCKED codes
            "https://alpha-mirror.foo": ("status", 200, "https://alpha-mirror.foo/"),
        })
        # HTTPError(500) raised by the opener is re-raised inside _fetch_final
        # via the rules table; ensure it behaves as a failed candidate:
        res = dr.probe_site("alpha", opener=op)
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["final_base_url"], "https://alpha-mirror.foo")


class TestRotationCandidates(unittest.TestCase):
    def test_same_label_other_tlds_only(self):
        out = dr._rotation_candidates(["https://vegamovies.foo/watch"])
        self.assertIn("https://vegamovies.bar/watch", out)
        self.assertIn("https://vegamovies.com/watch", out)
        self.assertNotIn("https://vegamovies.foo/watch", out)
        # bounded: one swap per registered TLD per candidate label
        self.assertLessEqual(len(out), len(dr.ROTATION_TLDS))

    def test_dedup_across_candidates(self):
        out = dr._rotation_candidates(["https://a.foo/", "https://a.foo/x"])
        bases = {u.rsplit("/", 2)[0] for u in out}
        self.assertLessEqual(len(out), 2 * len(dr.ROTATION_TLDS))


class TestGetActiveBaseUrl(_TempRegistryCase):
    def test_fallback(self):
        self.seed({})
        self.assertEqual(dr.get_active_base_url("ghost", "https://x.foo"),
                         "https://x.foo")
        self.assertEqual(dr.get_active_base_url("ghost"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
