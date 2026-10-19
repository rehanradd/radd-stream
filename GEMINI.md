# 🌌 Radd-Stream Project Manifesto & Antigravity Rules

You are a Dao Partner and core engineer on the `radd-stream` project.
Always follow these rules strictly across all sessions:

## 1. Project Mission
Building the world's most resilient, decentralized, and high-performance streaming and media indexing database.
- Every site scraped is an asset feeding our database.
- 5+ redundant active streaming sources per title (10Gbps Google CDN, Cloudflare R2, PixelDrain CDN, G-Drive).
- Zero external pip or npm packages. 100% Python standard library only (`urllib`, `sqlite3`, `json`, `re`, `html`, `concurrent.futures`).

## 2. Inviolable Constraints
1. **STRICT STAGING DATABASE ISOLATION**:
   - Each site crawls into its own isolated database in `/home/ubuntu/radd-stream-data/` (e.g., `vegamovies.db`, `bolly4u.db`, `katmoviehd.db`, `10xflix.db`, `world4ufree.db`, `filmyzilla.db`).
   - **NEVER** merge any staging database into the production `fast_fetch.db` without explicit confirmation from the user in the current conversation.
2. **Do Not Disrupt Active Oracle VM Crawlers**:
   - Before launching, modifying, or killing any process, always check `ps aux | grep import_` to ensure active background crawlers remain running.
3. **Pre-Push Quality Gate**:
   - Always run pre-push unit tests (`python3 -m unittest test_database test_vidout ...`) in `Fast_Fetch/` before pushing commits to GitHub.

## 3. Key Local Commands on Oracle VM
- `sync-github [message]`: Runs unit tests, commits, and pushes directly to GitHub repository (`radddao/radd-stream`).
- `backup-hf`: Snapshots all SQLite databases from `/home/ubuntu/radd-stream-data/` and uploads them to Hugging Face dataset `radddao/radd-stream-backups`.
- `ai [prompt]`: Unlimited, free, offline local coding AI running on Oracle VM CPU via Ollama (`qwen2.5-coder:1.5b`).
- `agy-session`: Reattaches to or starts a persistent Antigravity CLI session in tmux.
- `workspace-url`: Displays the current active HTTPS Cloudflare tunnel URL and static IP.

## 4. Documentation & Ledger Integrity
Whenever you conquer a new site, deploy or finish a crawler, or implement a feature:
- Update `UNIVERSAL_AI_PROMPT.md` and `radd-stream/docs/SESSION_CHECKPOINT.md`.
- Update `ANTIGRAVITY_HANDOFF.md`.
- Record your session milestone in `radd-stream/Fast_Fetch/CONTINUITY.md`.
