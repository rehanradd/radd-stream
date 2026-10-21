import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backup_manager import (
    _db_row_counts,
    _hf_git_env,
    calculate_sha256,
    safe_vacuum_sqlite,
    create_backup_archive,
    upload_to_huggingface,
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

    def test_r2_sigv4_signing(self):
        from backup_manager import _get_aws4_signing_key, _sign_aws4
        key = _get_aws4_signing_key("testsecret", "20261018", "auto", "s3")
        self.assertIsInstance(key, bytes)
        self.assertEqual(len(key), 32)


class StagingCountsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "site.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, is_18_plus INTEGER DEFAULT 0)")
        conn.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY, post_id INTEGER)")
        conn.execute("CREATE TABLE download_sources (id INTEGER PRIMARY KEY, release_id INTEGER)")
        conn.execute("CREATE TABLE sitemap_cache (loc TEXT, site TEXT, scraped INTEGER)")
        conn.executemany("INSERT INTO posts (is_18_plus) VALUES (?)", [(0,), (1,), (1,)])
        conn.executemany("INSERT INTO releases (post_id) VALUES (?)", [(1,), (1,)])
        conn.execute("INSERT INTO download_sources (release_id) VALUES (1)")
        conn.executemany(
            "INSERT INTO sitemap_cache (loc, site, scraped) VALUES (?, 'site', ?)",
            [("a", 0), ("b", 1), ("c", -1)],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_include_catalog_and_queue_totals(self):
        counts = _db_row_counts(self.db)
        self.assertEqual(counts["posts"], 3)
        self.assertEqual(counts["posts_adult"], 2)
        self.assertEqual(counts["releases"], 2)
        self.assertEqual(counts["download_sources"], 1)
        self.assertEqual(counts["sitemap_pending"], 1)
        self.assertEqual(counts["sitemap_failed"], 1)

    def test_missing_columns_are_tolerated(self):
        other = Path(self.db.parent) / "bare.db"
        conn = sqlite3.connect(other)
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()
        counts = _db_row_counts(other)
        self.assertEqual(counts["posts"], 0)
        self.assertNotIn("posts_adult", counts)

    def test_manifest_records_counts_and_commit(self):
        out_dir = Path(self.tmp.name) / "out"
        _archive, manifest = create_backup_archive([self.db], out_dir, prefix="unit-test")
        entry = manifest["databases"][self.db.name]
        self.assertEqual(entry["counts"]["posts_adult"], 2)
        self.assertIn("source_commit", manifest)


class HuggingFaceUploadTests(unittest.TestCase):
    """The token must never leave the environment: no URL, no argv, no git config."""

    TOKEN = "hf_supersecrettoken1234567890"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / "backup.tar.gz"
        self.archive.write_bytes(b"not really a tarball")
        self.calls: list[list[str]] = []
        self.repo_listing: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_run_git(self, args, cwd, env):
        self.calls.append([str(a) for a in args])
        if args[0] == "add":
            self.repo_listing = sorted(p.name for p in Path(cwd).rglob("*") if p.is_file() and ".git" not in p.parts)
        stdout = "main\n" if args[:2] == ["symbolic-ref", "--short"] else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    def _upload(self, clone_ok: bool = True):
        def run_git(args, cwd, env):
            if args[:2] == ["clone", "--depth"] and not clone_ok:
                return subprocess.CompletedProcess(args, 128, stdout="", stderr="not found")
            return self._fake_run_git(args, cwd, env)

        with patch("backup_manager._run_git", side_effect=run_git), patch.dict(
            os.environ, {"HF_TOKEN": self.TOKEN, "HF_DATASET_REPO": "radddao/radd-stream-backups"}
        ):
            return upload_to_huggingface(self.archive, manifest={"timestamp": "20261021"})

    def test_upload_succeeds_and_pushes_detected_branch(self):
        self.assertTrue(self._upload())
        flat = " ".join(" ".join(c) for c in self.calls)
        self.assertIn("push origin main", flat)
        self.assertTrue(any(c[:2] == ["lfs", "track"] for c in self.calls))

    def test_token_never_appears_in_any_command_line(self):
        self._upload()
        for call in self.calls:
            joined = " ".join(call)
            self.assertNotIn(self.TOKEN, joined)
            self.assertNotIn("@huggingface.co", joined)
        clone = next(c for c in self.calls if c[:2] == ["clone", "--depth"])
        self.assertEqual(clone[-2], "https://huggingface.co/datasets/radddao/radd-stream-backups")

    def test_archive_and_manifest_both_land_in_the_repo(self):
        self._upload()
        self.assertIn("backup.tar.gz", self.repo_listing)
        self.assertIn("LATEST.json", self.repo_listing)

    def test_fresh_repo_falls_back_to_init_on_main(self):
        self.assertTrue(self._upload(clone_ok=False))
        flat = " ".join(" ".join(c) for c in self.calls)
        self.assertIn("checkout -b main", flat)
        self.assertIn("push origin main", flat)

    def test_push_failure_is_reported(self):
        def run_git(args, cwd, env):
            if args[0] == "push":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="remote: access denied")
            return self._fake_run_git(args, cwd, env)

        with patch("backup_manager._run_git", side_effect=run_git), patch.dict(
            os.environ, {"HF_TOKEN": self.TOKEN, "HF_DATASET_REPO": "radddao/radd-stream-backups"}
        ):
            self.assertFalse(upload_to_huggingface(self.archive))

    def test_missing_token_skips_upload(self):
        with patch("backup_manager._run_git", side_effect=self._fake_run_git), patch.dict(
            os.environ, {"HF_TOKEN": "", "HF_DATASET_REPO": "radddao/radd-stream-backups"}
        ):
            self.assertFalse(upload_to_huggingface(self.archive))
        self.assertEqual(self.calls, [])

    def test_askpass_helper_supplies_credentials_over_ssh_channel(self):
        env_dir = Path(self.tmp.name) / "env"
        env_dir.mkdir()
        env = _hf_git_env(env_dir)
        helper = env["GIT_ASKPASS"]
        user = subprocess.run(["/bin/sh", helper, "Username for 'https://huggingface.co': "],
                              capture_output=True, text=True, env=env).stdout.strip()
        pw_env = dict(env, HF_TOKEN=self.TOKEN)
        pw = subprocess.run(["/bin/sh", helper, "Password for 'https://huggingface.co': "],
                            capture_output=True, text=True, env=pw_env).stdout.strip()
        self.assertEqual(user, "oauth")
        self.assertEqual(pw, self.TOKEN)
        self.assertEqual(os.stat(helper).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()

