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
import sys
import tarfile
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path



def calculate_sha256(filepath: str | Path) -> str:
    """Calculate SHA-256 hash of a file in chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


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


def upload_to_huggingface(
    archive_path: Path,
    repo_id: str | None = None,
    token: str | None = None,
) -> bool:
    """
    Uploads backup archive to a private Hugging Face dataset repository using Git LFS.
    100% Python standard library (no pip packages or huggingface_hub required).
    """
    repo_id = repo_id or os.environ.get("HF_DATASET_REPO", "")
    token = token or os.environ.get("HF_TOKEN", "")
    if not repo_id or not token:
        print("[*] HF_DATASET_REPO or HF_TOKEN not configured. Skipping Hugging Face upload.", file=sys.stderr)
        return False

    print(f"[*] Uploading {archive_path.name} to Hugging Face dataset {repo_id}...", flush=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        clone_url = f"https://user:{token}@huggingface.co/datasets/{repo_id}"
        repo_dir = Path(tmp_dir) / "hf_repo"

        # Clone repository or initialize if empty
        res = subprocess.run(["git", "clone", "--depth", "1", clone_url, str(repo_dir)], capture_output=True, text=True)
        if res.returncode != 0:
            repo_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", clone_url], cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "main"], cwd=repo_dir, capture_output=True)

        # Setup git-lfs tracking for large archives and databases
        subprocess.run(["git", "lfs", "install"], cwd=repo_dir, capture_output=True)
        subprocess.run(["git", "lfs", "track", "*.tar.gz", "*.db"], cwd=repo_dir, capture_output=True)

        # Copy archive into repo
        dest = repo_dir / archive_path.name
        shutil.copy2(archive_path, dest)

        # Git commit and push
        subprocess.run(["git", "add", ".gitattributes", archive_path.name], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"chore(backup): snapshot {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"],
            cwd=repo_dir,
            capture_output=True,
        )
        push_res = subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, capture_output=True, text=True)
        if push_res.returncode == 0:
            print(f"[✓] Uploaded backup to Hugging Face dataset: https://huggingface.co/datasets/{repo_id}", flush=True)
            return True
        else:
            print(f"[!] Hugging Face push failed: {push_res.stderr.strip()}", file=sys.stderr)
            return False


def main():
    parser = argparse.ArgumentParser(description="radd-stream Cloud Backup Manager")
    parser.add_argument("--dir", default="/home/ubuntu/radd-stream-data", help="Directory containing SQLite DBs")
    parser.add_argument("--out", default="/tmp/radd-stream-backups", help="Directory to save backup archives")
    parser.add_argument("--github", action="store_true", help="Upload to GitHub Releases")
    parser.add_argument("--telegram", action="store_true", help="Upload to Telegram channel")
    parser.add_argument("--r2", action="store_true", help="Upload to Cloudflare R2 bucket")
    parser.add_argument("--hf", action="store_true", help="Upload to Hugging Face dataset")
    parser.add_argument("--all", action="store_true", help="Upload to all configured services (GitHub + HF + Telegram + R2)")
    parser.add_argument("--dry-run", action="store_true", help="Snapshot & compress only, do not upload")
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
        upload_to_huggingface(archive)

    # 3. Telegram
    if args.telegram or args.all:
        caption = f"🚀 Radd-Stream DB Backup ({manifest['archive']['size_mb']} MB)\nDatabases: {', '.join(manifest['databases'].keys())}"
        upload_to_telegram(archive, caption=caption)

    # 4. Cloudflare R2
    if args.r2 or args.all or os.environ.get("R2_ACCOUNT_ID"):
        upload_to_cloudflare_r2(archive)


if __name__ == "__main__":
    main()

