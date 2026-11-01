"""The import-time filesystem probes in `config.py` must be total.

Written against the failure the supervisor measured on hosted backend CI at q2's `eb4c0ee`:
`PermissionError: '/home/ubuntu/radd-stream-data'` at 0.2 s, before a single test ran, with every
later step skipped. `Path.exists()` swallows ENOENT/ENOTDIR/EBADF/ELOOP and re-raises EACCES, so the
one line in `config.py` that asks a question about a mount it does not own can end a whole run — and
cannot be reproduced locally, because this box owns that directory and can read it.

The same class was found in two sibling probes and is covered here too: `_read_brand` asking whether
`BRAND_FILE` is there (a *file*, so the naive fix would have been to write a second helper nobody
greps for), and the `RADD_DB_PATH` branch asking whether the parent of a caller-supplied database path
exists — the branch that decides where every write in the fleet lands.

No chmod, no real paths written, nothing outside `tempfile`: the OSError is forced through
`unittest.mock`, which is the only way a permission-denied mount can be tested on a machine that has
one it can read.
"""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config

#: The path the probe asks about on a deployment. Named here so the fake below can be selective
#: without hard-coding a second copy of a production path into a test.
_ORACLE = Path("/home/ubuntu/radd-stream-data")

_REAL_EXISTS = Path.exists
_REAL_MKDIR = Path.mkdir


def _unpermissioned_for(*blocked):
    """A `Path.exists()` that raises PermissionError for `blocked` and is honest elsewhere.

    Selective, because `config` asks the same question of several paths while it imports: a blanket
    raise would fail the reload for the wrong reason and the test would prove nothing about the line
    it targets.
    """
    denied = {Path(p) for p in blocked}

    def fake(self, *args, **kwargs):
        if Path(self) in denied:
            raise PermissionError(13, "Permission denied", str(self))
        return _REAL_EXISTS(self, *args, **kwargs)

    return fake


def _mkdir_denied(*blocked):
    """`Path.mkdir()` that refuses for `blocked`, so an absent-parent fallback cannot touch the disk.

    The `RADD_DB_PATH` branch answers an unstatable parent by trying to create it; without this the
    test would really create directories and then assert the wrong branch was taken.
    """
    denied = {Path(p) for p in blocked}

    def fake(self, *args, **kwargs):
        if Path(self) in denied:
            raise PermissionError(13, "Permission denied", str(self))
        return _REAL_MKDIR(self, *args, **kwargs)

    return fake


#: The original selective fake, pinned to the data directory, kept by name because the
#: data-directory tests below read as a story about that one path.
_unpermissioned = _unpermissioned_for(_ORACLE)


class DataDirProbeTests(unittest.TestCase):
    def test_an_unreadable_data_dir_is_answered_as_absent_and_raises_nothing(self):
        """The crash site, one function down from where it happened."""
        with patch.object(Path, "exists", _unpermissioned):
            self.assertFalse(config._probe_dir(_ORACLE))

    def test_the_probe_still_answers_for_a_directory_it_can_read(self):
        """The fix must not become a constant False: a readable directory is still found.

        A `try/except OSError: return False` written as `return False` alone would pass the test
        above and silently move every deployment onto the checkout fallback, so this is the half
        that keeps the probe answering.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(config._probe_dir(Path(tmp)))
            self.assertFalse(config._probe_dir(Path(tmp) / "not-there.db"))

    def test_the_import_survives_a_data_directory_it_cannot_stat(self):
        """The property the runner actually needed: importing config cannot end the run.

        Reloaded rather than re-implemented, because the decision lives in a module-level
        assignment; a test that rebuilds the expression would not notice the `try` being removed.
        """
        clean = dict(os.environ)
        try:
            with patch.dict(os.environ, clear=True):
                self.assertNotIn("RADD_DATA_DIR", os.environ)
                with patch.object(Path, "exists", _unpermissioned):
                    try:
                        importlib.reload(config)
                    except OSError as exc:
                        self.fail("importing config raised %r — that is the crash being fixed" % exc)
            self.assertEqual(config.DATA_DIR, config.BASE_DIR)
            self.assertEqual(config.staging_db_path("katmoviehd"),
                             config.BASE_DIR / "katmoviehd.db")
        finally:
            os.environ.clear()
            os.environ.update(clean)
            importlib.reload(config)

    def test_this_box_resolves_the_data_directory_it_can_read(self):
        """No behaviour change where the directory is real: the unpatched module still picks it.

        Skipped, not failed, on a machine with no data disk — including the hosted runner, where
        `/home/ubuntu/radd-stream-data` does not exist at all and `BASE_DIR` is the correct answer.
        """
        if "RADD_DATA_DIR" in os.environ:
            self.skipTest("RADD_DATA_DIR is set here, so DATA_DIR is not this probe's decision")
        if not _REAL_EXISTS(_ORACLE):
            self.skipTest("%s does not exist on this machine; nothing to re-measure" % _ORACLE)
        self.assertEqual(config.DATA_DIR, _ORACLE)
        self.assertEqual(sys.modules["config"], config)


class BrandFileProbeTests(unittest.TestCase):
    """`_read_brand` asks the same non-total question of a *file* (`config.py:64`)."""

    def test_an_unstatable_brand_file_answers_as_absent_and_raises_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "brand.properties"
            with patch.object(Path, "exists", _unpermissioned_for(blocked)):
                try:
                    merged = config._read_brand(blocked)
                except OSError as exc:
                    self.fail("_read_brand raised %r — the crash being fixed" % exc)
            self.assertEqual(merged, {})

    def test_the_brand_reader_still_parses_a_file_it_can_read(self):
        """The other half: the fix must not become a permanent empty brand."""
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "brand.properties"
            real.write_text("[brand]\nidentity.name = Probe Test Brand\n", encoding="utf-8")
            merged = config._read_brand(real)
            self.assertEqual(merged.get("identity.name"), "Probe Test Brand")

    def test_the_import_survives_a_brand_file_it_cannot_stat(self):
        """A mount that cannot be read must not be able to end a run at line 1 of the suite."""
        clean = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                blocked = Path(tmp) / "brand.properties"
                with patch.dict(os.environ, {"RADD_BRAND_FILE": str(blocked)}, clear=True):
                    with patch.object(Path, "exists", _unpermissioned_for(blocked)):
                        try:
                            importlib.reload(config)
                        except OSError as exc:
                            self.fail("importing config raised %r" % exc)
                self.assertEqual(config.BRAND, {})
                self.assertEqual(config.BRAND_APP_NAME, "RADD Stream")
        finally:
            os.environ.clear()
            os.environ.update(clean)
            importlib.reload(config)


class DbPathProbeTests(unittest.TestCase):
    """The `RADD_DB_PATH` branch asks it of a caller-supplied parent (`config.py:146`)."""

    def test_an_unstatable_db_parent_falls_back_to_the_checkout_and_raises_nothing(self):
        clean = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                parent = Path(tmp) / "mount-that-refuses"
                target = parent / "catalog.db"
                with patch.dict(os.environ, {"RADD_DB_PATH": str(target)}, clear=True):
                    with patch.object(Path, "exists", _unpermissioned_for(parent)):
                        with patch.object(Path, "mkdir", _mkdir_denied(parent)):
                            try:
                                importlib.reload(config)
                            except OSError as exc:
                                self.fail("importing config raised %r" % exc)
                self.assertEqual(config.DB_PATH, config.BASE_DIR / config._DB_FILENAME)
                self.assertFalse(parent.exists(), "the test created a directory it should not have")
        finally:
            os.environ.clear()
            os.environ.update(clean)
            importlib.reload(config)

    def test_an_env_override_with_a_readable_parent_is_still_honoured(self):
        """No behaviour change where the path can be statted: the override wins over BASE_DIR."""
        clean = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "elsewhere.db"
                with patch.dict(os.environ, {"RADD_DB_PATH": str(target)}, clear=True):
                    importlib.reload(config)
                self.assertEqual(config.DB_PATH, target)
                self.assertFalse(target.exists(), "resolving a path must not create the database")
        finally:
            os.environ.clear()
            os.environ.update(clean)
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
