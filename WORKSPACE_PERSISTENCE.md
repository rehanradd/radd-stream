# Workspace persistence

Replit stores project files and chat history with the project, including across
closing the browser tab, idle periods, and Repl restarts. Shell commands and
one-off `export` statements are different: their environment changes last only
for that shell session.

## Antigravity CLI

The CLI is installed at `.tools/antigravity/bin/agy` inside the workspace, not
under the runtime home directory or a temporary cache. `.replit` adds that
directory to `PATH` for Shell sessions. After the project configuration reloads,
run `agy --version` or `agy` in Shell.

The 211 MB executable is excluded from Git and deployment bundles. If it is ever
missing (for example, after cloning the project elsewhere), restore it with:

```sh
bash install-antigravity.sh
```

The installer verifies the downloaded binary against the release manifest's
SHA-512 checksum.

## Project data and notes

Keep durable project data under the workspace, not `/tmp` or `$HOME/.cache`.
The MultiMovies SQLite database and its existing `Fast_Fetch/CHAT_HISTORY.md`
are already under `radd-stream/` in this workspace. Replit also retains this
Agent conversation with the project; the history file is the portable project
handoff record.
