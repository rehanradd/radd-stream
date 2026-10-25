#!/usr/bin/env python3
"""
backup_manager.py — Atomic SQLite Database Snapshots and Multi-Tier Cloud Backup

Features:
- Safe online SQLite snapshots using VACUUM INTO (never corrupts live WAL databases).
- Gzip compression and SHA-256 integrity verification.
- Direct API backup uploaders using 100% Python standard library (no pip packages):
    1. GitHub Releases API (using GITHUB_TOKEN)
    2. Telegram Bot Document API (using TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID)
    3. Backblaze B2 / Cloudflare S3 uploaders
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()



def calculate_sha256(filepath: str | Path) -> str:
    """Calculate SHA-256 hash of a file in chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _db_row_counts(db_path: Path) -> dict:
    """Row counts for a catalog database, tolerant of the per-site schema families."""
    counts: dict[str, int] = {}
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        return counts
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("posts", "releases", "download_sources", "sources", "post_sources", "sitemap_cache"):
            if table in tables:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if "posts" in tables and any(
            r[1] == "is_18_plus" for r in conn.execute("PRAGMA table_info(posts)")
        ):
            counts["posts_adult"] = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE is_18_plus = 1"
            ).fetchone()[0]
        if "sitemap_cache" in tables:
            counts["sitemap_pending"] = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0"
            ).fetchone()[0]
            counts["sitemap_failed"] = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1"
            ).fetchone()[0]
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return counts


def safe_vacuum_sqlite(source_db: str | Path, target_db: str | Path) -> bool:
    """
    Creates a clean, consistent snapshot of a live SQLite database.
    Does NOT disrupt active crawler processes writing to WAL.
    """
    source = Path(source_db)
    target = Path(target_db)
    if not source.exists():
        return False

    if target.exists():
        target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(source))
        conn.execute(f"VACUUM INTO '{target.as_posix()}'")
        conn.close()
        return True
    except Exception as e:
        print(f"[!] Safe vacuum failed for {source.name}: {e}", file=sys.stderr)
        return False


def _git_head_sha() -> str:
    """Short HEAD SHA of the checkout that produced this backup, empty if unavailable."""
    try:
        res = subprocess.run(
            ["git", "-C", str(BASE_DIR.parent), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return res.stdout.strip() if res.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def create_backup_archive(
    db_paths: list[Path],
    output_dir: Path,
    prefix: str = "radd-stream-backup",
) -> tuple[Path, dict]:
    """
    Creates a compressed tar.gz containing safe snapshots and a manifest.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    archive_name = f"{prefix}_{timestamp}.tar.gz"
    archive_path = output_dir / archive_name

    manifest = {
        "timestamp": timestamp,
        "created_utc": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "source_commit": _git_head_sha(),
        "databases": {},
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        valid_files = []

        for db in db_paths:
            if not db.exists():
                continue
            snap_path = tmp_path / db.name
            print(f"[*] Safely vacuuming {db.name}...", flush=True)
            if safe_vacuum_sqlite(db, snap_path):
                sha = calculate_sha256(snap_path)
                size_mb = snap_path.stat().st_size / (1024 * 1024)
                manifest["databases"][db.name] = {
                    "sha256": sha,
                    "size_mb": round(size_mb, 2),
                    "counts": _db_row_counts(db),
                }
                valid_files.append(snap_path)

        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2))
        valid_files.append(manifest_file)

        print(f"[*] Creating compressed archive {archive_name}...", flush=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for f in valid_files:
                tar.add(f, arcname=f.name)

    manifest["archive"] = {
        "filename": archive_name,
        "size_mb": round(archive_path.stat().st_size / (1024 * 1024), 2),
        "sha256": calculate_sha256(archive_path),
    }

    return archive_path, manifest


def upload_to_github_release(
    archive_path: Path,
    repo: str = "radddao/radd-stream",
    tag_prefix: str = "backup",
    token: str | None = None,
) -> str | None:
    """
    Uploads backup archive to GitHub Releases via REST API.
    Returns the release HTML URL on success.
    """
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("[!] GITHUB_TOKEN not set. Skipping GitHub release upload.", file=sys.stderr)
        return None

    tag_name = f"{tag_prefix}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    release_name = f"Database Backup {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Radd-Stream-Backup/1.0",
    }

    create_payload = json.dumps({
        "tag_name": tag_name,
        "name": release_name,
        "body": f"Automated database snapshot backup containing compressed SQLite catalogs.\n\nSHA-256: `{calculate_sha256(archive_path)}`",
        "draft": False,
        "prerelease": True,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases",
            data=create_payload,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            rel_data = json.loads(resp.read().decode("utf-8"))

        upload_url_raw = rel_data.get("upload_url", "")
        upload_url = upload_url_raw.split("{")[0] + f"?name={archive_path.name}"
        html_url = rel_data.get("html_url", "")

        with open(archive_path, "rb") as f:
            file_data = f.read()

        up_headers = {
            "Authorization": f"token {token}",
            "Content-Type": "application/gzip",
            "Content-Length": str(len(file_data)),
            "User-Agent": "Radd-Stream-Backup/1.0",
        }
        up_req = urllib.request.Request(upload_url, data=file_data, headers=up_headers, method="POST")
        with urllib.request.urlopen(up_req) as up_resp:
            if up_resp.status in (200, 201):
                print(f"[✓] Uploaded backup to GitHub Release: {html_url}", flush=True)
                return html_url
    except Exception as e:
        print(f"[!] GitHub release upload failed: {e}", file=sys.stderr)
        return None


def upload_to_telegram(
    archive_path: Path,
    bot_token: str | None = None,
    chat_id: str | None = None,
    caption: str = "",
) -> bool:
    """
    Uploads backup archive to a private Telegram channel via Bot API.
    Zero 3rd-party dependencies (pure standard library multipart encoder).
    """
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        print("[*] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.", flush=True)
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    boundary = f"----WebKitFormBoundary{os.urandom(16).hex()}"

    body_parts = []
    # chat_id field
    body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode("utf-8"))
    # caption field
    if caption:
        body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode("utf-8"))
    # document field
    filename = archive_path.name
    header = f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\nContent-Type: application/gzip\r\n\r\n".encode("utf-8")
    body_parts.append(header)

    with open(archive_path, "rb") as f:
        file_bytes = f.read()
    body_parts.append(file_bytes)
    body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    full_body = b"".join(body_parts)
    req = urllib.request.Request(
        url,
        data=full_body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(full_body)),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            if res_json.get("ok"):
                print(f"[✓] Uploaded backup document to Telegram chat {chat_id}!", flush=True)
                return True
            else:
                print(f"[!] Telegram API returned error: {res_json}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"[!] Telegram upload error: {e}", file=sys.stderr)
        return False


def _sign_aws4(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_aws4_signing_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = _sign_aws4(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region_name.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service_name.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, "aws4_request".encode("utf-8"), hashlib.sha256).digest()


def upload_to_cloudflare_r2(
    archive_path: Path,
    account_id: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    bucket_name: str | None = None,
    object_name: str | None = None,
) -> bool:
    """
    Uploads backup archive directly to Cloudflare R2 using AWS SigV4.
    100% Python standard library (no pip packages or boto3 required).
    """
    account_id = account_id or os.environ.get("R2_ACCOUNT_ID", "")
    access_key = access_key or os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = secret_key or os.environ.get("R2_SECRET_ACCESS_KEY", "")
    bucket_name = bucket_name or os.environ.get("R2_BUCKET_NAME", "radd-stream-backups")
    object_name = object_name or archive_path.name

    if not account_id or not access_key or not secret_key:
        print("[*] R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, or R2_SECRET_ACCESS_KEY not configured. Skipping R2 upload.", file=sys.stderr)
        return False

    with open(archive_path, "rb") as f:
        payload_bytes = f.read()

    host = f"{account_id}.r2.cloudflarestorage.com"
    endpoint_url = f"https://{host}/{bucket_name}/{object_name}"
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()

    canonical_uri = f"/{bucket_name}/{object_name}"
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = f"PUT\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    credential_scope = f"{date_stamp}/auto/s3/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

    signing_key = _get_aws4_signing_key(secret_key, date_stamp, "auto", "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    auth_header = f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

    headers = {
        "Host": host,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": auth_header,
        "Content-Type": "application/gzip",
        "Content-Length": str(len(payload_bytes)),
        "User-Agent": "Radd-Stream-Backup/1.0",
    }

    req = urllib.request.Request(endpoint_url, data=payload_bytes, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            if resp.status in (200, 201):
                print(f"[✓] Uploaded backup to Cloudflare R2: s3://{bucket_name}/{object_name}", flush=True)
                return True
            else:
                print(f"[!] R2 returned status {resp.status}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"[!] Cloudflare R2 upload error: {e}", file=sys.stderr)
        return False


def _run_git(args: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    """Git with no credential helper and no token on the command line."""
    return subprocess.run(
        ["git", "-c", "credential.helper=", *args],
        cwd=str(cwd), capture_output=True, text=True, env=env,
    )


def _hf_git_env(tmp_dir: Path) -> dict:
    """Git environment that authenticates to Hugging Face through an askpass helper.

    The token stays in the environment: it never enters a remote URL, a process
    argument, .git/config, or any log.
    """
    helper = tmp_dir / "askpass.sh"
    helper.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  *Username*) printf '%s\\n' 'oauth' ;;\n"
        '  *) printf \'%s\\n\' "${HF_TOKEN:?HF_TOKEN is missing}" ;;\n'
        "esac\n"
    )
    helper.chmod(0o700)
    home = tmp_dir / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update(
        GIT_ASKPASS=str(helper),
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_NOSYSTEM="1",
        HOME=str(home),
        XDG_CONFIG_HOME=str(home),
    )
    return env


def upload_to_huggingface(
    archive_path: Path,
    manifest: dict | None = None,
    repo_id: str | None = None,
    extra_files: list[Path] | None = None,
) -> bool:
    """
    Uploads a backup archive plus its manifest to a Hugging Face dataset via Git LFS.
    100% Python standard library (no pip packages or huggingface_hub required).
    """
    repo_id = repo_id or os.environ.get("HF_DATASET_REPO", "")
    if not repo_id or not os.environ.get("HF_TOKEN"):
        print("[*] HF_DATASET_REPO or HF_TOKEN not configured. Skipping Hugging Face upload.", file=sys.stderr)
        return False

    remote_url = f"https://huggingface.co/datasets/{repo_id}"
    print(f"[*] Uploading {archive_path.name} to Hugging Face dataset {repo_id}...", flush=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        env = _hf_git_env(tmp_path)
        repo_dir = tmp_path / "hf_repo"

        clone = _run_git(["clone", "--depth", "1", remote_url, str(repo_dir)], tmp_path, env)
        if clone.returncode != 0:
            head = _run_git(["-c", "init.defaultBranch=main", "init", str(repo_dir)], tmp_path, env)
            if head.returncode != 0:
                print(f"[!] Hugging Face clone and init both failed: {head.stderr.strip()}", file=sys.stderr)
                return False
            _run_git(["remote", "add", "origin", remote_url], repo_dir, env)
            _run_git(["checkout", "-b", "main"], repo_dir, env)
            branch = "main"
        else:
            shown = _run_git(["symbolic-ref", "--short", "HEAD"], repo_dir, env)
            branch = shown.stdout.strip() or "main"

        repo_dir.mkdir(parents=True, exist_ok=True)

        _run_git(["lfs", "install"], repo_dir, env)
        for pattern in ("*.tar.gz", "*.db", "*.zip"):
            _run_git(["lfs", "track", pattern], repo_dir, env)

        shutil.copy2(archive_path, repo_dir / archive_path.name)
        for extra in extra_files or []:
            shutil.copy2(extra, repo_dir / extra.name)
        if manifest:
            (repo_dir / "LATEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        added = _run_git(["add", "-A"], repo_dir, env)
        if added.returncode != 0:
            print(f"[!] git add failed: {added.stderr.strip()}", file=sys.stderr)
            return False

        stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        committed = _run_git(
            [
                "-c", "user.name=radd-stream-backup",
                "-c", "user.email=backup@radd-stream.local",
                "commit",
                "-m", f"chore(backup): snapshot {stamp} ({archive_path.name})",
            ],
            repo_dir, env,
        )
        if committed.returncode != 0 and "nothing to commit" not in committed.stdout + committed.stderr:
            print(f"[!] git commit failed: {(committed.stderr or committed.stdout).strip()}", file=sys.stderr)
            return False

        pushed = _run_git(["push", "origin", branch], repo_dir, env)
        if pushed.returncode != 0:
            print(f"[!] Hugging Face push failed: {(pushed.stderr or pushed.stdout).strip()}", file=sys.stderr)
            return False

        print(f"[✓] Uploaded backup to Hugging Face dataset: https://huggingface.co/datasets/{repo_id}", flush=True)
        return True


def snapshot_code(output_dir: Path) -> Path | None:
    """Packs the tracked source tree at HEAD so the code rides along with the data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    sha = _git_head_sha() or "unknown"
    target = output_dir / f"radd-stream-code_{sha}.tar.gz"
    if target.exists():
        return target
    res = subprocess.run(
        ["git", "-C", str(BASE_DIR.parent), "archive", "--format=tar.gz", "-o", str(target), "HEAD"],
        capture_output=True, text=True, timeout=300,
    )
    if res.returncode != 0 or not target.exists():
        print(f"[!] Code snapshot failed: {res.stderr.strip()}", file=sys.stderr)
        return None
    return target


def main():
    parser = argparse.ArgumentParser(description="radd-stream Cloud Backup Manager")
    parser.add_argument("--dir", default="/home/ubuntu/radd-stream-data", help="Directory containing SQLite DBs")
    parser.add_argument("--out", default="/home/ubuntu/radd-stream-backups",
                        help="Directory to save backup archives. Not /tmp: this is the only "
                             "copy that exists before an upload finishes, and a cleaner or a "
                             "reboot takes /tmp with it.")
    parser.add_argument("--github", action="store_true", help="Upload to GitHub Releases")
    parser.add_argument("--telegram", action="store_true", help="Upload to Telegram channel")
    parser.add_argument("--r2", action="store_true", help="Upload to Cloudflare R2 bucket")
    parser.add_argument("--hf", action="store_true", help="Upload to Hugging Face dataset")
    parser.add_argument("--all", action="store_true", help="Upload to all configured services (GitHub + HF + Telegram + R2)")
    parser.add_argument("--dry-run", action="store_true", help="Snapshot & compress only, do not upload")
    parser.add_argument("--no-code", action="store_true", help="Do not pack the tracked source tree alongside the databases")
    args = parser.parse_args()

    data_dir = Path(args.dir)
    if not data_dir.exists():
        # Fallback to local workspace if running locally
        data_dir = Path("/home/runner/workspace/radd-stream/Fast_Fetch")

    dbs = sorted(data_dir.glob("*.db"))
    if not dbs:
        print(f"[!] No .db files found in {data_dir}", file=sys.stderr)
        return

    print(f"[*] Found {len(dbs)} databases: {[d.name for d in dbs]}", flush=True)
    out_dir = Path(args.out)
    archive, manifest = create_backup_archive(dbs, out_dir)
    print(f"[✓] Created backup archive: {archive} ({manifest['archive']['size_mb']} MB)", flush=True)
    print(f"[*] Archive SHA-256: {manifest['archive']['sha256']}", flush=True)

    if args.dry_run:
        print("[*] Dry run complete. No off-site uploads requested.", flush=True)
        return

    # 1. GitHub Releases
    if args.github or args.all or (not args.telegram and not args.r2 and not args.hf and os.environ.get("GITHUB_TOKEN")):
        upload_to_github_release(archive)

    # 2. Hugging Face Datasets
    if args.hf or args.all or os.environ.get("HF_TOKEN"):
        extras = []
        if not args.no_code:
            code = snapshot_code(out_dir)
            if code:
                extras.append(code)
        upload_to_huggingface(archive, manifest=manifest, extra_files=extras)

    # 3. Telegram
    if args.telegram or args.all:
        caption = f"🚀 Radd-Stream DB Backup ({manifest['archive']['size_mb']} MB)\nDatabases: {', '.join(manifest['databases'].keys())}"
        upload_to_telegram(archive, caption=caption)

    # 4. Cloudflare R2
    if args.r2 or args.all or os.environ.get("R2_ACCOUNT_ID"):
        upload_to_cloudflare_r2(archive)


if __name__ == "__main__":
    main()

