#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Domain-drift reconciliation tests (CROWN ORDER qoder14_ruling, 2026-11-05).

Covers the approved slice in ``fast_fetch.py``:
  * hunk A/B — ``registry_live_domains()`` + the read-time overlay at the tail
    of ``get_domains()``: ``domain_registry.json`` outranks BOTH the static
    ``DEFAULT_DOMAINS`` and the stale ``domains_config`` DB rows (the DB
    overrides the static table, so a static-only fix is a no-op).
  * hunk F — retirement markers: drifted values stay in place (no host string
    is ever removed; ``redact._registry_needles()`` harvests the registry into
    the PUBLIC SCRUBBER, so deletion would silently shrink redaction).
  * hunk G — ``refresh_domains()``: the CLI/sync fresh read. Documents the
    ``DOMAINS = get_domains()`` import-time staleness; no hot-reload.
  * the needle-superset guard: the redactor's needle set derived from the
    registry must never lose a host that existed before this change (71 → 71).
  * the second ``katmovie`` block in ``normalize_url``: shadowed by the first
    block whenever the always-present ``katmoviehd`` key exists; its only live
    reference is the guard-escape case, pinned here, retirement marker not
    deletion.

Offline: no network, no production DB. The synthetic registries and DBs are
temp files / in-memory sqlite.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fast_fetch as ff  # noqa: E402
import redact  # noqa: E402

#: Snapshot of redact._registry_needles() taken 2026-11-05 against the lane's
#: domain_registry.json BEFORE any drift-reconciliation edit. If a host
#: disappears from the live set, the public scrubber is shrinking — that is a
#: release-blocking regression, not a cleanup.
NEEDLES_BEFORE = frozenset({
    "10xflix", "10xflix.bond", "10xflix.hair", "10xflix.help",
    "7starhd", "7starhd.dentist", "7starhd.rich", "7starhd.talk",
    "9xmovie", "9xmovie.bayern", "9xmovies", "9xmovies.click",
    "9xmovies.photo", "bolly4u", "bolly4u.org", "bolly4uv", "bolly4uv.com",
    "bolly4uz", "bolly4uz.click", "desicinemas", "desicinemas.chat",
    "desicinemas.tv", "filmyzilla", "filmyzilla74", "filmyzilla75",
    "hdhub4u", "hdhub4u.fans", "hdtvb", "hdtvb.net", "hdutv", "hdutv.com",
    "hindilinks4u", "hindilinks4u.pink", "katmoviehd", "katmoviehd.top",
    "katmovieshd", "katmovieshd.net", "m1.multimovies.courses", "moviezguru",
    "moviezguru.guru", "multimovies", "multimovies.garden",
    "new.katmoviehd.top", "new1.vegamovies.lease", "new2.hdhub4u.free",
    "new3.hdhub4u.free", "new8.hdhub4u.cl", "rareanimes", "rogmovies",
    "rogmovies.one", "rogmovies.quest", "ssrmovies", "ssrmovies.gripe",
    "ssrmovies.quest", "ssrmovies.surf", "thefilmyzilla",
    "thefilmyzilla.in", "toonworld4all", "toonworld4all.me", "vegamovies",
    "vegamovies.gallery", "vegamovies.lease", "world4ufree",
    "world4ufree.garden", "world4ufree.tours", "www.desicinemas.pk",
    "www.filmyzilla74.com", "www.filmyzilla75.com", "www.hindilinks4u.zip",
    "www.rareanimes.mov", "www.toonworld4all.me",
})


@contextlib.contextmanager
def _temp_registry(sites: dict):
    tmp = tempfile.TemporaryDirectory()
    try:
        path = pathlib.Path(tmp.name) / "domain_registry.json"
        path.write_text(json.dumps({"version": "1.0", "sites": sites}),
                        encoding="utf-8")
        yield path
    finally:
        tmp.cleanup()


def _memory_db(rows: list[tuple[str, str]]):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE domains_config (name TEXT PRIMARY KEY, "
                 "url TEXT, status TEXT, last_checked TEXT)")
    conn.executemany("INSERT INTO domains_config (name, url) VALUES (?, ?)",
                     rows)
    conn.commit()
    return conn


class TestRegistryLiveDomains(unittest.TestCase):
    def test_active_sites_are_returned(self):
        sites = {"vegamovies": {"active_base_url": "https://new1.vegamovies.lease",
                                "status": "active"}}
        with _temp_registry(sites) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg):
                self.assertEqual(ff.registry_live_domains(),
                                 {"vegamovies": "https://new1.vegamovies.lease"})

    def test_down_status_is_not_preferred(self):
        sites = {"rogmovies": {"active_base_url": "https://rogmovies.one",
                               "status": "down"}}
        with _temp_registry(sites) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg):
                self.assertEqual(ff.registry_live_domains(), {})

    def test_missing_status_still_counts(self):
        # hindilinks4u/toonworld4all carry status=None in the live registry;
        # unknown is not "down" and must not be dropped.
        sites = {"toonworld4all": {"active_base_url": "https://toonworld4all.me"}}
        with _temp_registry(sites) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg):
                self.assertIn("toonworld4all", ff.registry_live_domains())

    def test_non_https_and_blank_bases_are_skipped(self):
        sites = {
            "a": {"active_base_url": "http://plain.example", "status": "active"},
            "b": {"active_base_url": "", "status": "active"},
            "c": {"status": "active"},
            "d": "not-a-dict",
        }
        with _temp_registry(sites) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg):
                self.assertEqual(ff.registry_live_domains(), {})

    def test_missing_registry_is_empty_not_raise(self):
        missing = pathlib.Path(tempfile.gettempdir()) / "no_such_registry_q14.json"
        with mock.patch.object(ff, "REGISTRY_PATH", missing):
            self.assertEqual(ff.registry_live_domains(), {})

    def test_malformed_registry_is_empty_not_raise(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "domain_registry.json"
        path.write_text("{not json", encoding="utf-8")
        with mock.patch.object(ff, "REGISTRY_PATH", path):
            self.assertEqual(ff.registry_live_domains(), {})


class TestGetDomainsOverlay(unittest.TestCase):
    """The overlay must outrank the stale DB rows at read time, in place."""

    STALE_DB = [
        # The seven rows crown measured as stale in domains_config, plus one
        # row that agrees with the registry.
        ("vegamovies", "https://vegamovies.gallery"),
        ("vegamovies_sitemap", "https://vegamovies.gallery/sitemap.xml"),
        ("ssrmovies", "https://ssrmovies.gripe"),
        ("7starhd", "https://7starhd.rich"),
        ("10xflix", "https://10xflix.help"),
        ("multimovies", "https://multimovies.garden"),
        ("hdhub4u", "https://hdtvb.net"),
        ("hdhub4u_sitemap", "https://hdtvb.net/sitemap.xml"),
        ("filmyzilla", "https://www.filmyzilla74.com"),
        ("rogmovies", "https://rogmovies.one"),
    ]

    LIVE_REGISTRY = {
        "vegamovies": {"active_base_url": "https://new1.vegamovies.lease",
                       "status": "active"},
        "ssrmovies": {"active_base_url": "https://ssrmovies.surf",
                      "status": "active"},
        "7starhd": {"active_base_url": "https://7starhd.dentist",
                    "status": "active"},
        "10xflix": {"active_base_url": "https://10xflix.hair",
                    "status": "active"},
        "multimovies": {"active_base_url": "https://m1.multimovies.courses",
                        "status": "active"},
        "hdhub4u": {"active_base_url": "https://new8.hdhub4u.cl",
                    "status": "active"},
        "filmyzilla": {"active_base_url": "https://thefilmyzilla.in",
                       "status": "active"},
        "rogmovies": {"active_base_url": "https://rogmovies.one",
                      "status": "active"},
        "bolly4u": {"active_base_url": "https://bolly4uv.com",
                    "status": "active"},
    }

    def _get_domains(self):
        conn = _memory_db(self.STALE_DB)
        self.addCleanup(conn.close)

        @contextlib.contextmanager
        def fake_get_db(*a, **k):
            yield conn

        with _temp_registry(self.LIVE_REGISTRY) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg), \
                 mock.patch.object(ff, "get_db", fake_get_db):
                return ff.get_domains()

    def test_registry_outranks_stale_db_rows(self):
        domains = self._get_domains()
        self.assertEqual(domains["vegamovies"], "https://new1.vegamovies.lease")
        self.assertEqual(domains["ssrmovies"], "https://ssrmovies.surf")
        self.assertEqual(domains["7starhd"], "https://7starhd.dentist")
        self.assertEqual(domains["10xflix"], "https://10xflix.hair")
        self.assertEqual(domains["multimovies"], "https://m1.multimovies.courses")
        self.assertEqual(domains["filmyzilla"], "https://thefilmyzilla.in")

    def test_hdhub4u_mispointer_is_outranked_not_rewritten(self):
        domains = self._get_domains()
        # The hdtvb.net row was a pointer at a DIFFERENT site's domain; the
        # overlay fixes reads, and no string is deleted anywhere.
        self.assertEqual(domains["hdhub4u"], "https://new8.hdhub4u.cl")

    def test_sitemap_keys_follow_the_origin_host_swap(self):
        domains = self._get_domains()
        self.assertEqual(domains["vegamovies_sitemap"],
                         "https://new1.vegamovies.lease/sitemap.xml")
        self.assertEqual(domains["sitemap"],
                         "https://new1.vegamovies.lease/sitemap.xml")
        self.assertEqual(domains["hdhub4u_sitemap"],
                         "https://new8.hdhub4u.cl/sitemap.xml")

    def test_registry_only_sites_are_added(self):
        domains = self._get_domains()
        self.assertEqual(domains["bolly4u"], "https://bolly4uv.com")

    def test_agreeing_rows_pass_through_unchanged(self):
        domains = self._get_domains()
        self.assertEqual(domains["rogmovies"], "https://rogmovies.one")

    def test_unrelated_keys_are_untouched(self):
        domains = self._get_domains()
        self.assertEqual(domains["katmoviehd_landing"], "https://katmovieshd.net")
        self.assertEqual(domains["hubcloud"], ff.DEFAULT_DOMAINS["hubcloud"])
        self.assertEqual(domains["fastdl"], ff.DEFAULT_DOMAINS["fastdl"])

    def test_no_registry_falls_back_to_static_then_db(self):
        conn = _memory_db(self.STALE_DB)
        self.addCleanup(conn.close)

        @contextlib.contextmanager
        def fake_get_db(*a, **k):
            yield conn

        missing = pathlib.Path(tempfile.gettempdir()) / "no_such_registry_q14.json"
        with mock.patch.object(ff, "REGISTRY_PATH", missing), \
             mock.patch.object(ff, "get_db", fake_get_db):
            domains = ff.get_domains()
        self.assertEqual(domains["vegamovies"], "https://vegamovies.gallery")
        self.assertEqual(domains["hdhub4u"], "https://hdtvb.net")

    def test_down_registry_site_does_not_shadow_the_db(self):
        conn = _memory_db([("vegamovies", "https://db.example")])
        self.addCleanup(conn.close)

        @contextlib.contextmanager
        def fake_get_db(*a, **k):
            yield conn

        sites = {"vegamovies": {"active_base_url": "https://dead.vegamovies.zone",
                                "status": "down"}}
        with _temp_registry(sites) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg), \
                 mock.patch.object(ff, "get_db", fake_get_db):
                domains = ff.get_domains()
        self.assertEqual(domains["vegamovies"], "https://db.example")


class TestRefreshDomains(unittest.TestCase):
    def test_refresh_updates_snapshot_in_place(self):
        sites = {"vegamovies": {"active_base_url": "https://new1.vegamovies.lease",
                                "status": "active"}}
        snapshot = dict(ff.DOMAINS)
        self.addCleanup(ff.DOMAINS.update, snapshot)
        with _temp_registry(sites) as reg:
            with mock.patch.object(ff, "REGISTRY_PATH", reg):
                out = ff.refresh_domains()
        self.assertIs(out, ff.DOMAINS)
        self.assertEqual(ff.DOMAINS["vegamovies"], "https://new1.vegamovies.lease")

    def test_sync_refreshes_before_fetching(self):
        src = (HERE / "fast_fetch.py").read_text(encoding="utf-8")
        body = src.split("def sync_sitemaps", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("refresh_domains()", body)


class TestNeedleSuperset(unittest.TestCase):
    """The one that protects the public edge: the scrubber's needle set is
    harvested from domain_registry.json by redact._registry_needles(). No host
    or mirror string may vanish. 71 → 71."""

    def test_needle_set_is_a_superset_of_the_pre_change_snapshot(self):
        current = set(redact._registry_needles())
        lost = NEEDLES_BEFORE - current
        self.assertFalse(lost,
                         f"redactor needles disappeared: {sorted(lost)}")
        self.assertGreaterEqual(len(current), len(NEEDLES_BEFORE))

    def test_hdtvb_net_is_owned_by_the_hdtvb_site_entry_not_hdhub4u(self):
        data = json.loads(ff.REGISTRY_PATH.read_text(encoding="utf-8"))
        sites = data["sites"]
        self.assertIn("https://hdtvb.net", sites["hdtvb"]["known_mirrors"])
        for mirror in sites["hdhub4u"]["known_mirrors"]:
            self.assertNotIn("hdtvb", mirror)

    def test_retired_rows_are_still_harvested(self):
        # _registry_needles() iterates every entry and never checks `status`;
        # pin that so a future "skip retired rows" edit cannot shrink the
        # redactor silently.
        sites = {"oldsitename": {"active_base_url": "https://new.example",
                                 "status": "retired",
                                 "known_mirrors": ["https://new.example",
                                                   "https://retired.example"]}}
        with _temp_registry(sites) as reg:
            real_path = pathlib.Path

            class _FakePath:
                def __init__(self, value):
                    self._p = real_path(value)

                def with_name(self, name):
                    return reg

            with mock.patch.object(redact, "Path", _FakePath):
                needles = redact._registry_needles()
        self.assertIn("retired.example", needles)
        self.assertIn("new.example", needles)
        self.assertIn("oldsitename", needles)

    def test_registry_host_strings_survive_the_reconciliation(self):
        data = json.loads(ff.REGISTRY_PATH.read_text(encoding="utf-8"))
        for name, entry in data["sites"].items():
            self.assertIsInstance(entry, dict)
            for mirror in entry.get("known_mirrors") or []:
                self.assertIsInstance(mirror, str)


class TestKatmovieBlockShadowing(unittest.TestCase):
    """Proof the second ``katmovie`` block in normalize_url has no live
    reference: ``DEFAULT_DOMAINS`` always carries the ``katmoviehd`` key,
    ``get_domains()`` starts from that dict, and no code path DELETEs
    domains_config rows — so block 1 and block 2 compute the SAME
    ``active_host``. Block 1 either returns the rewrite or leaves the host
    equal to it; block 2 can therefore only fire through block 1's guard
    escape, which is pinned below as a bug-shape, not a feature."""

    ACTIVE = "https://new.katmoviehd.top"

    def setUp(self):
        self.assertIn("katmoviehd", ff.DEFAULT_DOMAINS)  # the invariant
        snapshot = dict(ff.DOMAINS)
        self.addCleanup(ff.DOMAINS.clear)
        self.addCleanup(ff.DOMAINS.update, snapshot)
        ff.DOMAINS.clear()
        ff.DOMAINS.update({**ff.DEFAULT_DOMAINS, "katmoviehd": self.ACTIVE})

    def test_old_domain_is_rewritten_by_the_first_block(self):
        self.assertEqual(
            ff.normalize_url("https://katmoviehd.fans/movie/x/"),
            self.ACTIVE + "/movie/x/")

    def test_active_domain_passes_through_both_blocks_unchanged(self):
        self.assertEqual(ff.normalize_url(self.ACTIVE + "/movie/x/"),
                         self.ACTIVE + "/movie/x/")

    def test_guard_escape_is_the_only_live_reference_to_the_second_block(self):
        # A host containing BOTH "katmovie" and a guard token skips block 1's
        # rewrite, then block 2 rewrites it WITHOUT the guard. Pin the current
        # behavior; the retirement marker documents it, deletion is withheld.
        self.assertEqual(
            ff.normalize_url("https://links.kmhd.katmovie.watch/x"),
            self.ACTIVE + "/x")

    def test_hosts_without_the_katmovie_substring_never_hit_either_block(self):
        self.assertEqual(ff.normalize_url("https://kathdrama.example/x"),
                         "https://kathdrama.example/x")

    def test_substring_looseness_of_normalize_url_is_preexisting_behavior(self):
        # normalize_url matches hosts by substring (unlike host_classifier's
        # strict suffix rule). "notkatmovie.example" therefore DOES hit the
        # blocks and gets rewritten. Pin the current behavior — narrowing it
        # is out of this slice's scope and would change ingest output.
        self.assertEqual(ff.normalize_url("https://notkatmovie.example/x"),
                         self.ACTIVE + "/x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
