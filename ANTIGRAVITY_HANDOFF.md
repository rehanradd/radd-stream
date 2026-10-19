# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor 4 concurrent background crawlers on Oracle VM (10xflix, World4uFree, Bolly4u, KatMovieHD) and maintain persistent Oracle VM web workspace with unlimited local AI and Antigravity CLI.
- **Current state:** Active Oracle VM crawlers & tools:
  1. 10xflix: Actively crawling (PID 146221/146852, 12,170+ catalog posts, 43,637+ releases, 151,865+ direct sources extracted, 0 failures).
  2. World4uFree: Actively crawling (PID 152560/153724, 24,240 catalog titles synced, 5,149+ releases, 49,367+ direct sources, 1,138 direct 10Gbps Cloudflare Worker .mkv streams).
  3. Bolly4u: Actively crawling (PID 156129/161377, 36,016 catalog titles synced, 6-worker crawler with photojin Google CDN 10Gbps direct streams, bolly4u.db: 190MB).
  4. KatMovieHD: Actively crawling (PID 157374/173352, unconstrained SvelteKit API sync completed, 5-worker crawler actively parsing DandnDn/Cloudflare R2/PixelDrain streams, katmoviehd.db: 35MB).
  5. FilmyZilla: Completed (4,149 scraped, 13,114 releases, 13,516 direct sources, 402 Google CDN 302 streams).
  - Web Workspace: code-server on port 8443, Cloudflare HTTPS quick tunnel, direct static IP (`92.4.95.252`).
  - Local Unlimited AI: Ollama with `qwen2.5-coder:1.5b` installed; accessible via `ai` CLI tool.
  - Antigravity CLI: Fully authenticated on Oracle VM with `gemini-3.8-flash-high`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`. Accessible via `agy-session` in persistent tmux.
  - One-Command Tools: `sync-github` (pre-push tests + commit + GitHub push), `backup-hf` (database snapshot + Git LFS push to HF dataset), `workspace-url` (prints active URLs).
  - Strict staging DB isolation maintained across all sites. Zero merges into fast_fetch.db.
- **Next step:** Monitor all 4 live crawlers and access workspace from Android Chrome.

The Antigravity CLI's local recovery files preserve only selected settings and the last-conversation index, not full transcripts or login credentials. Replit project files and this handoff preserve project context, but cannot restore lost Antigravity account history or authentication.

Do not put passwords, API keys, login tokens, or other credentials here.
