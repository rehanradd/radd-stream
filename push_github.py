#!/usr/bin/env python3
"""Retired uploader. Use reviewed Git commits with the askpass flow instead.

The previous version staged the entire working tree (`git add .`), embedded
GITHUB_TOKEN inside a remote URL, and pushed straight to `main`. That is what
put a live token into this VM's .git/config, and a blanket stage would also
have committed the SQLite catalogs and any unreviewed file. Kept as a stub so
old habits fail loudly instead of half-working.
"""

if __name__ == "__main__":
    print("Disabled: this legacy uploader staged everything, embedded a token in a URL and pushed to main.")
    print("No files were scanned, no credentials were read, and nothing was pushed.")
    print("Follow ORACLE_DEPLOYMENT.md for the safe Git workflow (reviewed paths + temporary askpass).")
    raise SystemExit(2)
