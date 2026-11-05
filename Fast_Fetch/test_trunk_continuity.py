#!/usr/bin/env python3
"""A port from a stale base must fail loudly, not quietly revert trunk.

Measured 2026-11-06: trunk's `fast_fetch.py` is +159 lines over `b99814e`, and a lane cut at
`b99814e` carried a modified `fast_fetch.py` whose `grep -c` for the hubcdn gate symbols was **0**.
Copying that file into a trunk lane — which is how several lanes port, because `git checkout <sha> --
<path>` is easy and `git diff | git apply` is not — reverts the gate, and every suite in CI stays
green, because those suites test the code that is still there rather than the code that vanished.
GitHub allows agents to push verified milestones straight to `main`, so a revert can reach trunk with
a green check on it.

This module is the tripwire. Each test asserts that a landed protection **exists in the tree under
test**, by symbol, with a count. It is offline and reads files only: no network, no catalog, no
import of the heavy modules, so it costs a fraction of a second and cannot be skipped into greenness
by a missing dependency.

    python3 -S Fast_Fetch/test_trunk_continuity.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()


def _text(name: str) -> str:
    return (BASE_DIR / name).read_text(encoding="utf-8")


def _count(name: str, pattern: str) -> int:
    return len(re.findall(pattern, _text(name), flags=re.MULTILINE))


class LandedProtectionsStillPresentTests(unittest.TestCase):
    """One test per protection that a whole-file port from a pre-2026-11-05 base silently deletes."""

    def test_hubcdn_redirect_gate_is_still_in_the_engine(self):
        self.assertGreaterEqual(
            _count("fast_fetch.py", r"_HubcdnNoRedirect"), 1,
            "the hubcdn no-redirect guard was reverted out of fast_fetch.py")
        self.assertGreaterEqual(
            _count("fast_fetch.py", r"hubcdn_asset_role"), 1,
            "the embed-host role check was reverted out of fast_fetch.py")

    def test_host_classifier_still_owns_the_asset_role(self):
        self.assertTrue((BASE_DIR / "host_classifier.py").is_file(),
                        "host_classifier.py vanished; the redirect trust has no owner")
        self.assertGreaterEqual(_count("host_classifier.py", r"def hubcdn_asset_role"), 1)

    def test_posts_paging_window_is_still_bounded(self):
        self.assertGreaterEqual(_count("viewer.py", r"POSTS_MAX_OFFSET"), 1,
                                "the offset-window cap was reverted; a caller can ask for OFFSET 99,999,900")
        self.assertIn("page_beyond_range", _text("viewer.py"))

    def test_page_and_limit_still_come_from_bounded_int(self):
        self.assertGreaterEqual(_count("viewer.py", r"def bounded_int"), 1,
                                "bounded_int is gone; `?page=abc` raises through the handler again")
        self.assertGreaterEqual(_count("viewer.py", r"bounded_int\(query_params"), 2,
                                "page and limit are no longer both read through the clamp")

    def test_neutral_image_hosts_are_still_judged_before_being_shown(self):
        redact = _text("redact.py")
        self.assertIn("NEUTRAL_UPLOAD_HOSTS", redact)
        self.assertIn("def _url_names_source", redact,
                      "the token scan is gone; a neutral bucket would serve a URL naming the source")

    def test_the_backup_never_downloads_the_dataset_it_is_uploading_to(self):
        backup = _text("backup_manager.py")
        self.assertIn('GIT_LFS_SKIP_SMUDGE="1"', backup,
                      "LFS smudging is back on: every nightly clone pulls the whole dataset to disk")
        self.assertIn("def prune_local_archives", backup,
                      "retention left the path systemd actually runs; the archives grow until the disk dies")
        self.assertIn("def _check_space", backup,
                      "the free-space preflight is gone and a full disk fails half-way through each database")


class StaleBaseIsDetectableTests(unittest.TestCase):
    """The port that a reviewer would have to catch by hand is also assertable."""

    def test_the_engine_is_not_the_pre_hubcdn_revision(self):
        # `b99814e`'s fast_fetch.py had neither symbol. A count of the word is the cheap
        # discriminator between "trunk + my edit" and "my old base + my edit", which no
        # other suite checks, because the suites test behaviour that survives the revert.
        self.assertGreaterEqual(_count("fast_fetch.py", r"hubcdn"), 3,
                                "fewer than three hubcdn mentions means this is a pre-gate engine")


if __name__ == "__main__":
    unittest.main(verbosity=2)
