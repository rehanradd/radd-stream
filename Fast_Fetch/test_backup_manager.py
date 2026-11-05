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


class DiskGrowthTests(unittest.TestCase):
    """The nightly job filled the disk and then lied about it. Each test owns one of the four fixes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.db = self.data / "one.db"
        self.db.write_bytes(b"\x00" * 4096)
        self.out = self.root / "out"
        self.out.mkdir()
        self.staging = self.root / "staging"

    def tearDown(self):
        self.tmp.cleanup()

    def test_preflight_refuses_before_writing_anything(self):
        from backup_manager import BackupSpaceError
        with patch("backup_manager.free_bytes", return_value=1024):
            with self.assertRaises(BackupSpaceError):
                create_backup_archive([self.db], self.out, prefix="unit-test")
        self.assertEqual(list(self.out.glob("*.tar.gz")), [])

    def test_staging_honours_the_env_directory(self):
        seen = {}
        from backup_manager import safe_vacuum_sqlite as real

        def spy(source, target):
            seen["parent"] = Path(target).parent
            return real(source, target)

        with patch.dict(os.environ, {"RADD_BACKUP_STAGING": str(self.staging)}), patch(
            "backup_manager.safe_vacuum_sqlite", side_effect=spy
        ):
            create_backup_archive([self.db], self.out, prefix="unit-test")
        self.assertEqual(seen["parent"].parent, self.staging)

    def test_a_raised_exception_leaves_no_staging_behind(self):
        from backup_manager import safe_vacuum_sqlite as real

        def explode(source, target):
            Path(target).write_bytes(b"half-written snapshot")
            raise RuntimeError("vacuum died mid-run")

        with patch.dict(os.environ, {"RADD_BACKUP_STAGING": str(self.staging)}), patch(
            "backup_manager.safe_vacuum_sqlite", side_effect=explode
        ):
            with self.assertRaises(RuntimeError):
                create_backup_archive([self.db], self.out, prefix="unit-test")
        self.assertEqual(list(self.staging.iterdir()), [])

    def _archives(self, names):
        made = {}
        for i, name in enumerate(names, start=1):
            path = self.out / name
            path.write_bytes(b"%d" % i * (100 + i))
            made[name] = path.stat().st_size
        return made

    def test_prune_forgets_only_what_the_dataset_confirms(self):
        from backup_manager import prune_local_archives

        days = ["202610%02d" % d for d in range(1, 9)]
        sizes = self._archives([f"radd-stream-backup_{d}_010101.tar.gz" for d in days])
        # The second-newest upload failed on its own night, so it is not off-site; the rest are.
        unconfirmed = "radd-stream-backup_20261007_010101.tar.gz"
        offsite = {n: s for n, s in sizes.items() if n != unconfirmed}
        removed = prune_local_archives(self.out, keep=2, offsite=offsite)

        self.assertEqual(removed, 6)
        surviving = sorted(p.name for p in self.out.glob("radd-stream-backup_*.tar.gz"))
        self.assertEqual(surviving, [unconfirmed, "radd-stream-backup_20261008_010101.tar.gz"])

    def test_prune_deletes_nothing_without_a_listing(self):
        from backup_manager import prune_local_archives

        sizes = self._archives([f"radd-stream-backup_2026100{i}_010101.tar.gz" for i in range(1, 7)])
        with patch("backup_manager.hf_remote_listing", return_value=None):
            self.assertEqual(prune_local_archives(self.out, keep=2), 0)
        # An empty listing is a confirmed "nothing is stored", not a transport failure.
        self.assertEqual(prune_local_archives(self.out, keep=2, offsite={}), 0)
        self.assertEqual(len(list(self.out.glob("*.tar.gz"))), len(sizes))

    def test_hf_remote_listing_parses_sizes_and_refuses_on_no_token(self):
        import json as _json
        from backup_manager import hf_remote_listing

        payload = _json.dumps([
            {"type": "file", "path": "a.tar.gz", "size": 111},
            {"type": "directory", "path": "d"},
            {"type": "file", "path": "b.tar.gz", "size": None},
        ]).encode()
        with patch("backup_manager.urllib.request.urlopen") as urlopen, patch.dict(
            os.environ, {"HF_TOKEN": "t", "HF_DATASET_REPO": "x/y"}
        ):
            urlopen.return_value.__enter__ = lambda s: s
            urlopen.return_value.read = lambda: payload
            self.assertEqual(hf_remote_listing(), {"a.tar.gz": 111, "b.tar.gz": 0})
        with patch.dict(os.environ, {"HF_TOKEN": "", "HF_DATASET_REPO": "x/y"}):
            self.assertIsNone(hf_remote_listing())

    def test_the_clone_never_downloads_the_stored_archives(self):
        env = _hf_git_env(self.root)
        self.assertEqual(env["GIT_LFS_SKIP_SMUDGE"], "1")

    def _main_args(self):
        return ["--dir", str(self.data), "--out", str(self.out), "--hf", "--no-code"]

    def test_main_exits_nonzero_when_the_requested_upload_fails(self):
        from backup_manager import main

        archive = self.out / "radd-stream-backup_20261105_010101.tar.gz"
        archive.write_bytes(b"x")
        manifest = {"archive": {"filename": archive.name, "size_mb": 1, "sha256": "0" * 64},
                    "databases": {"one.db": {}}}
        with patch("backup_manager.create_backup_archive", return_value=(archive, manifest)), patch(
            "backup_manager.upload_to_huggingface", return_value=False
        ), patch("backup_manager.prune_local_archives") as pruned:
            code = main(self._main_args())
        self.assertEqual(code, 1)
        pruned.assert_not_called()
        self.assertTrue(archive.exists())

    def test_main_prunes_after_a_successful_upload_and_exits_zero(self):
        from backup_manager import main

        archive = self.out / "radd-stream-backup_20261105_010101.tar.gz"
        archive.write_bytes(b"x")
        manifest = {"archive": {"filename": archive.name, "size_mb": 1, "sha256": "0" * 64},
                    "databases": {"one.db": {}}}
        with patch("backup_manager.create_backup_archive", return_value=(archive, manifest)), patch(
            "backup_manager.upload_to_huggingface", return_value=True
        ), patch("backup_manager.prune_local_archives", return_value=3) as pruned:
            code = main(self._main_args())
        self.assertEqual(code, 0)
        pruned.assert_called_once()


if __name__ == "__main__":
    unittest.main()

