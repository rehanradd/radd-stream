#!/usr/bin/env bash
# Retired helper. Use reviewed Git commits plus the temporary askpass flow in
# ORACLE_DEPLOYMENT.md instead.
#
# What this script used to do, line by line in its former self:
#   `git add -u` + a loop that staged EVERY untracked file          -> a blanket stage,
#       which is exactly how SQLite catalogs, status dumps and unreviewed agent notes
#       end up in a commit. AGENTS.md requires `git add <reviewed paths>`.
#   an auto-generated commit message with no test run               -> WIP on the branch
#       that CI then builds and the owner then trusts.
#   `git push -u origin "$CURRENT_BRANCH"`                          -> this remote's URL
#       still carries the leaked credential the owner has not revoked yet, so the one
#       script named "safe" was the one that re-exposed it on every run.
# Kept as a stub so the habit fails loudly instead of half-working.

echo "Disabled: safe_push.sh staged every path it found, committed without a test gate, and pushed through the credential-bearing 'origin' remote."
echo "Nothing was staged, committed, or pushed."
echo "Stage reviewed paths, run the tests, then push with the askpass flow in ORACLE_DEPLOYMENT.md."
exit 2
