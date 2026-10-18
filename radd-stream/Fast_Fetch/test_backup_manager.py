import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from backup_manager import (
    calculate_sha256,
    safe_vacuum_sqlite,
    create_backup_archive,
)


class TestBackupManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.tmp_dir.name)

        # Create a sample SQLite db with WAL mode enabled
        self.db1 = self.test_dir / "test1.db"
        conn = sqlite3.connect(str(self.db1))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO items (name) VALUES ('Interstellar'), ('Inception');")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_safe_vacuum_sqlite(self):
        target = self.test_dir / "test1_backup.db"
        res = safe_vacuum_sqlite(self.db1, target)
        self.assertTrue(res)
        self.assertTrue(target.exists())

        # Verify data integrity in backup
        conn = sqlite3.connect(str(target))
        c = conn.cursor()
        c.execute("SELECT count(*) FROM items;")
        count = c.fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_calculate_sha256(self):
        sha = calculate_sha256(self.db1)
        self.assertIsInstance(sha, str)
        self.assertEqual(len(sha), 64)

    def test_create_backup_archive(self):
        out_dir = self.test_dir / "out"
        archive_path, manifest = create_backup_archive([self.db1], out_dir, prefix="unit-test")
        self.assertTrue(archive_path.exists())
        self.assertIn("databases", manifest)
        self.assertIn("test1.db", manifest["databases"])
        self.assertIn("archive", manifest)
        self.assertGreater(archive_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
