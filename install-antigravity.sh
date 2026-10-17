#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$ROOT/.tools/antigravity/bin"
BINARY="$TARGET_DIR/agy"

if [[ -x "$BINARY" ]]; then
  echo "Antigravity CLI is already installed in this workspace:"
  "$BINARY" --version
  exit 0
fi

installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT

curl -fsSL https://antigravity.google/cli/install.sh -o "$installer"
bash "$installer" --dir "$TARGET_DIR"

if [[ ! -x "$BINARY" ]]; then
  echo "Installation did not create $BINARY" >&2
  exit 1
fi

"$BINARY" --version
