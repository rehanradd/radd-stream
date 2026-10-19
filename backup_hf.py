#!/usr/bin/env python3
"""
backup-hf — Oracle VM Direct Hugging Face Backup Tool.
Compresses all active staging and production SQLite databases from /home/ubuntu/radd-stream-data
and uploads them securely to https://huggingface.co/datasets/radddao/radd-stream-backups using Git LFS.
"""
import os
import subprocess
import sys
from pathlib import Path

BACKUP_SCRIPT = Path("/opt/radd-stream/Fast_Fetch/backup_manager.py")
DATA_DIR = Path("/home/ubuntu/radd-stream-data")

def main():
    if not os.environ.get("HF_TOKEN"):
        print("[!] HF_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    print("=" * 65)
    print(" 🚀 RADD-STREAM DATABASE BACKUP TO HUGGING FACE")
    print(f" Source Directory: {DATA_DIR}")
    print(f" Target Dataset:   https://huggingface.co/datasets/{os.environ.get('HF_DATASET_REPO', 'radddao/radd-stream-backups')}")
    print("=" * 65)

    cmd = [
        sys.executable,
        str(BACKUP_SCRIPT),
        "--dir", str(DATA_DIR),
        "--hf"
    ]
    res = subprocess.run(cmd)
    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
