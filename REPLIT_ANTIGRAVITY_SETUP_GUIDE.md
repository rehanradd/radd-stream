# Replit Antigravity CLI Persistent Setup Guide

This guide explains how to install and permanently maintain Google Antigravity CLI (`agy`) in any Replit workspace (across different Replit accounts or projects) so that it survives container restarts, idle timeouts, and browser reloads.

---

## 💡 Why Normal Installations Disappear in Replit

Replit executes inside a containerized Nix environment:
- **Ephemeral Storage**: Directories outside your workspace (like `/tmp`, `/home/runner/.cache`, or `/usr/local/bin`) can be cleared when the Repl goes to sleep, restarts, or updates its Nix environment.
- **Persistent Storage**: Only files located inside **`/home/runner/workspace`** (the root of your project) are guaranteed to persist across Repl restarts and session disconnects.

By placing the binary inside `.tools/antigravity/bin/` within the workspace and linking it in `.replit`, your installation stays **permanent**.

---

## 🚀 Quick Setup (1-Minute Method)

If you already have a terminal open in your new Replit project, run these 3 quick steps:

### Step 1: Create the installer script

Create a file named `install-antigravity.sh` in your workspace root:

```bash
cat << 'EOF' > install-antigravity.sh
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

echo "Downloading Antigravity installer..."
curl -fsSL https://antigravity.google/cli/install.sh -o "$installer"
bash "$installer" --dir "$TARGET_DIR"

if [[ ! -x "$BINARY" ]]; then
  echo "Installation did not create $BINARY" >&2
  exit 1
fi

echo "Successfully installed Antigravity CLI:"
"$BINARY" --version
EOF
chmod +x install-antigravity.sh
```

### Step 2: Run the installer

Execute the script:

```bash
bash install-antigravity.sh
```

This downloads and places `agy` in `.tools/antigravity/bin/agy`.

### Step 3: Add to PATH via `.replit`

Open or create the `.replit` configuration file in the project root, and add the `[env]` table:

```toml
[env]
PATH = "/home/runner/workspace/.tools/antigravity/bin:$PATH"
```

*(If you already have an `[env]` section or other variables, simply append or add the `PATH` line).*

Open a new Shell tab in Replit, and verify:

```bash
agy --version
```

---

## 🛡️ Step 4: Protect Git & Deployments

The `agy` binary is ~210 MB. You should prevent it from being committed to Git or bundled into web deployments.

1. **In `.gitignore`**, add:
   ```gitignore
   # Antigravity CLI binary (persisted in workspace, excluded from Git)
   .tools/antigravity/
   ```

2. **In `.replitignore`**, add:
   ```replitignore
   # Prevent binary from being packaged in deployments
   .tools/antigravity/
   ```

---

## 🔑 Authentication in a New Replit Account

When using Antigravity in a new Replit account or new container:

1. Run the login command in Shell:
   ```bash
   agy auth login
   ```
2. Follow the URL prompt to authorize with your Google account.
3. If you use an API key instead of interactive OAuth, store it securely in Replit:
   - Go to the **Tools** panel on the left sidebar in Replit.
   - Click **Secrets** (Environment variables).
   - Add your key (e.g. `GEMINI_API_KEY` or `ANTIGRAVITY_API_KEY`).
   - Replit automatically injects Secrets into your shell environment.

---

## 🔄 How to Verify Persistence

To ensure the installation survives a full Replit restart:

1. In the Replit Shell, check the binary location:
   ```bash
   which agy
   # Output should be: /home/runner/workspace/.tools/antigravity/bin/agy
   ```
2. Restart the Repl:
   - In Replit, open the Command Palette (`Ctrl+K` or `Cmd+K`) and select **Restart Repl** (or stop and restart the project).
3. Open a fresh Shell tab and test:
   ```bash
   agy --version
   ```
4. If it returns the version number immediately without re-downloading, your setup is 100% persistent!

---

## 📋 Summary Checklist for Any New Repl

| Step | Action | File / Command |
|---|---|---|
| 1 | Create installer | `install-antigravity.sh` |
| 2 | Execute installation | `bash install-antigravity.sh` |
| 3 | Configure persistent PATH | `.replit` -> `PATH = "/home/runner/workspace/.tools/antigravity/bin:$PATH"` |
| 4 | Ignore binary in Git | `.gitignore` -> `.tools/antigravity/` |
| 5 | Ignore binary in Deploy | `.replitignore` -> `.tools/antigravity/` |
| 6 | Authenticate | `agy auth login` or Replit Secrets |
