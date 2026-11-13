"""The data-directory probe must be total, and the import must survive an unreadable path.

Written against the failure the supervisor measured on hosted backend CI at q2's `eb4c0ee`:
`PermissionError: '/home/ubuntu/radd-stream-data'` at 0.2 s, before a single test ran, with every
later step skipped. `Path.exists()` swallows ENOENT/ENOTDIR/EBADF/ELOOP and re-raises EACCES, so the
one line in `config.py` that asks a question about a mount it does not own can end a whole run — and
cannot be reproduced locally, because this box owns that directory and can read it.

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


def _unpermissioned(self, *args, **kwargs):
    """`Path.exists()` that raises PermissionError for the data directory and is honest elsewhere.

    Selective, because `config` asks the same question of `BRAND_FILE` while it imports: a blanket
    raise would fail the reload for the wrong reason and the test would prove nothing about the line
    it targets.
    """
    if Path(self) == _ORACLE:
        raise PermissionError(13, "Permission denied", str(self))
    return _REAL_EXISTS(self, *args, **kwargs)


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
        try:
            oracle_exists = _REAL_EXISTS(_ORACLE)
        except OSError:
            # The guard must be total like the probe it tests: on a runner where
            # /home/ubuntu exists but is unreadable, exists() raises PermissionError
            # instead of answering False, and the skip check itself would fail the run.
            self.skipTest("%s cannot be stat'ed on this machine; nothing to re-measure" % _ORACLE)
        if not oracle_exists:
            self.skipTest("%s does not exist on this machine; nothing to re-measure" % _ORACLE)
        self.assertEqual(config.DATA_DIR, _ORACLE)
        self.assertEqual(sys.modules["config"], config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
