#!/usr/bin/env bash
# ==============================================================================
# safe_push.sh — One-command safe Git sync for Radd Stream
# 
# What it does:
# 1. Checks if GITHUB_TOKEN is present in your Replit Configurations.
# 2. Detects any uncommitted work and safely commits it with a timestamp.
# 3. Pushes your current branch to GitHub using secure Git askpass.
# 4. NEVER logs or exposes tokens, and keeps .replit and database files safe.
# ==============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

echo "=================================================="
echo "🚀 Radd Stream — Safe Push & Backup Helper"
echo "=================================================="

# 1. Verify GITHUB_TOKEN exists
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "❌ Error: GITHUB_TOKEN is not set in your Replit Configurations!"
  echo "👉 Please add GITHUB_TOKEN in Replit Configurations and try again."
  exit 1
fi
echo "✅ GitHub token detected in environment."

# 2. Identify current branch
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
  echo "❌ Error: You are in a 'detached HEAD' state. Please switch to a branch first."
  exit 1
fi
echo "📍 Current working branch: $CURRENT_BRANCH"

# 3. Protect sensitive files from accidental staging
if [ -f .replit ]; then
  git reset HEAD .replit 2>/dev/null || true
fi

# 4. Check for uncommitted modified or new files
CHANGES_EXIST=0
if [ -n "$(git status --porcelain)" ]; then
  CHANGES_EXIST=1
  echo "📝 Uncommitted changes detected. Safely staging and committing..."
  
  # Stage tracked modified files
  git add -u
  
  # Stage untracked files, strictly ignoring .replit, *.db, and temporary files
  while IFS= read -r line; do
    file="${line:3}"
    case "$file" in
      .replit*|*.db|*.jks|*.key|*.pem|.env*)
        echo "   🔒 Skipping sensitive or database file: $file"
        ;;
      *)
        if [ -e "$file" ]; then
          git add "$file"
        fi
        ;;
    esac
  done < <(git status --porcelain | grep '^??' || true)

  # Check if anything was staged
  if ! git diff --cached --quiet; then
    TIMESTAMP="$(date -u +'%Y-%m-%d %H:%M UTC')"
    COMMIT_MSG="${1:-chore(checkpoint): safe auto-save before agent handoff ($TIMESTAMP)}"
    git commit -m "$COMMIT_MSG"
    echo "✅ Changes committed successfully."
  else
    echo "ℹ️ No stageable code changes to commit."
  fi
else
  echo "✅ Working tree is clean (no uncommitted edits)."
fi

# 5. Push to GitHub using safe askpass helper
echo "🔄 Pushing branch '$CURRENT_BRANCH' to GitHub..."

AUTH_DIR="$(mktemp -d)"
trap 'rm -rf "$AUTH_DIR"' EXIT
mkdir -p "$AUTH_DIR/home"

cat > "$AUTH_DIR/askpass" <<'ASKPASS'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' 'x-access-token' ;;
  *) printf '%s\n' "${GITHUB_TOKEN:?GITHUB_TOKEN is missing}" ;;
esac
ASKPASS
chmod 700 "$AUTH_DIR/askpass"

GIT_ASKPASS="$AUTH_DIR/askpass" \
GIT_TERMINAL_PROMPT=0 \
GIT_CONFIG_NOSYSTEM=1 \
HOME="$AUTH_DIR/home" \
git -c credential.helper= push -u origin "$CURRENT_BRANCH"

COMMIT_HASH="$(git rev-parse --short HEAD)"
echo ""
echo "=================================================="
echo "🎉 SUCCESS! Your work is safely backed up to GitHub!"
echo "   Branch: $CURRENT_BRANCH"
echo "   Commit: $COMMIT_HASH"
echo "   URL:    https://github.com/radddao/radd-stream/tree/$CURRENT_BRANCH"
echo "=================================================="
