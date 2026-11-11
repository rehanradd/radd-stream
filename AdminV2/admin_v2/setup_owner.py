"""First-run owner setup — VM-terminal command ONLY (OD-16).

Usage on the VM terminal (never in chat, never in a file, never in git):
    python3 -m admin_v2.setup_owner --base-dir /path/to/admin-data

The command prompts for a username and password with getpass (the
password is never echoed, never printed, and never stored except as
a PBKDF2 hash). It refuses if any admin user already exists.
A one-time credential, if the operator chooses to use one, is shown
once on that terminal only by the operator's own action — this
script invents and prints no credential.
"""
import argparse
import getpass
import sys

from .services import Service


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create the first owner account.")
    parser.add_argument("--base-dir", required=True)
    args = parser.parse_args(argv)
    svc = Service(args.base_dir)
    username = input("Owner username (3-32 chars): ").strip().lower()
    password = getpass.getpass("Owner password (12-128 chars, not echoed): ")
    confirm = getpass.getpass("Repeat password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    try:
        svc.create_owner(username, password)
    except Exception as exc:
        print("Setup failed: %s" % exc, file=sys.stderr)
        return 1
    print("Owner account created. Log in over HTTPS only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
