import os
import subprocess
import sys
import unittest


class TestOrphanAudit(unittest.TestCase):
    def test_orphan_audit_passes(self):
        tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "orphan_audit.py")
        res = subprocess.run([sys.executable, tool], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("0 orphans", res.stdout)


if __name__ == "__main__":
    unittest.main()
