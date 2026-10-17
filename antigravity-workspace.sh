#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLI="$ROOT/.tools/antigravity/bin/agy"
STATE_DIR="${HOME}/.gemini/antigravity-cli"
CACHE_DIR="$STATE_DIR/cache"
RECOVERY_DIR="$ROOT/.antigravity-recovery"
CACHE_FILE="$CACHE_DIR/last_conversations.json"
BACKUP_CACHE="$RECOVERY_DIR/last_conversations.json"

if [[ ! -x "$CLI" ]]; then
  echo "Antigravity CLI is missing. Restore it with: bash install-antigravity.sh" >&2
  exit 1
fi

mkdir -p "$CACHE_DIR" "$RECOVERY_DIR"
chmod 700 "$RECOVERY_DIR"

valid_json() {
  python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        json.load(source)
except (OSError, ValueError):
    raise SystemExit(1)
PY
}

valid_cache() {
  python3 - "$1" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        value = json.load(source)
except (OSError, ValueError):
    raise SystemExit(1)

if not isinstance(value, dict) or any(
    not isinstance(path, str) or not isinstance(session, str)
    for path, session in value.items()
):
    raise SystemExit(1)
PY
}

restore_preference() {
  local name="$1"
  local backup="$RECOVERY_DIR/$name"
  local destination="$STATE_DIR/$name"
  local temporary

  if [[ ! -e "$destination" && -f "$backup" ]] && valid_json "$backup"; then
    temporary="$(mktemp "$STATE_DIR/.${name}.XXXXXX")"
    cp -- "$backup" "$temporary"
    chmod 600 "$temporary"
    mv -f -- "$temporary" "$destination"
    echo "Restored Antigravity $name from the workspace backup."
  fi
}

restore_cache() {
  local temporary

  [[ -f "$BACKUP_CACHE" ]] || return 0
  valid_cache "$BACKUP_CACHE" || {
    echo "Ignoring invalid Antigravity conversation-index backup." >&2
    return 0
  }

  if [[ -f "$CACHE_FILE" ]] && valid_cache "$CACHE_FILE"; then
    temporary="$(mktemp "$CACHE_DIR/.last_conversations.XXXXXX")"
    python3 - "$BACKUP_CACHE" "$CACHE_FILE" > "$temporary" <<'PY'
import json
import sys

merged = {}
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as source:
        merged.update(json.load(source))
json.dump(merged, sys.stdout, indent=2)
sys.stdout.write("\n")
PY
    chmod 600 "$temporary"
    mv -f -- "$temporary" "$CACHE_FILE"
  else
    temporary="$(mktemp "$CACHE_DIR/.last_conversations.XXXXXX")"
    cp -- "$BACKUP_CACHE" "$temporary"
    chmod 600 "$temporary"
    mv -f -- "$temporary" "$CACHE_FILE"
  fi
}

snapshot_file() {
  local source="$1"
  local destination="$2"
  local temporary

  [[ -f "$source" ]] || return 0
  valid_json "$source" || return 0
  if [[ "$source" == "$CACHE_FILE" ]]; then
    valid_cache "$source" || return 0
  fi

  temporary="$(mktemp "$RECOVERY_DIR/.snapshot.XXXXXX")"
  cp -- "$source" "$temporary"
  chmod 600 "$temporary"
  mv -f -- "$temporary" "$destination"
}

snapshot_state() {
  snapshot_file "$STATE_DIR/settings.json" "$RECOVERY_DIR/settings.json"
  snapshot_file "$STATE_DIR/keybindings.json" "$RECOVERY_DIR/keybindings.json"
  snapshot_file "$CACHE_FILE" "$BACKUP_CACHE"
}

restore_preference settings.json
restore_preference keybindings.json
restore_cache

# Keep the CLI's workspace key stable so --continue finds the same thread.
cd "$ROOT"
if [[ "$#" -eq 0 ]]; then
  set -- --continue
fi

"$CLI" "$@" <&0 &
CLI_PID=$!

(
  while kill -0 "$CLI_PID" 2>/dev/null; do
    sleep 5
    snapshot_state
  done
) &
WATCHER_PID=$!

set +e
wait "$CLI_PID"
CLI_STATUS=$?
set -e

kill "$WATCHER_PID" 2>/dev/null || true
wait "$WATCHER_PID" 2>/dev/null || true
snapshot_state
exit "$CLI_STATUS"
