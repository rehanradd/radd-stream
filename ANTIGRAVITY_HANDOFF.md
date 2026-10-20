# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor active background crawlers on Oracle VM (Bolly4u, World4uFree, 9xmovies), run the Master-Disciple dual-tier local AI workflow (Ollama Qwen 2.5 Coder 1.5B via `/usr/local/bin/disciple`), and maintain persistent real-time chat sync.
- **Current state:** Active Oracle VM crawlers & tools:
  1. 10xflix: Completed 100% (13,738 posts, 76,716 releases, 227,000 direct sources in `/home/ubuntu/radd-stream-data/10xflix.db`).
  2. Bolly4u: Actively crawling (PID 161377, 6 workers, 0.2s delay, 20,880+ titles processed, 30,000+ releases, Google CDN 10Gbps direct streams).
  3. World4uFree: Repaired & actively re-crawling (PID 249172, 6 workers, 0.2s delay, multi-domain parser for `fastilinks.beauty`, `wlinksi.site`, `cloud.mail.ru`, and fallback gateways; 16,758 posts re-queued).
  4. 9xmovies: CONQUERED & actively crawling (PID 250953, 5 workers, 0.2s delay, 20,347 titles synced, session-cookie CSRF unwrapping for `linksddr.com` yielding direct 10Gbps Google CDN, HubCloud, HubDrive, FilePress, GoFile, StreamTape, 1Fichier, MultiUp, MegaUp; dedicated DB `/home/ubuntu/radd-stream-data/9xmovies.db`).
  - Finished 100% staging catalogs: 10xflix (13.7k), SSRMovies (27k), Rogmovies (7.8k), HDTVB (5.6k), Vegamovies (14k), MultiMovies (10.4k), 7StarHD (23.4k), RareAnimes (2.6k), HDHub4u (14.5k), FilmyZilla (4.1k).
  - Local AI Disciple: `disciple` CLI tool (`/usr/local/bin/disciple` -> `Fast_Fetch/disciple.py`) wired to local Ollama (`qwen2.5-coder:1.5b`) on CPU (0 cloud tokens) for boilerplate code, regex, and unit test generation.
  - Real-Time Chat Sync: `auto_chat_sync.py` running in background daemon (PID 210724), continuously saving message turns into `Fast_Fetch/CHAT_HISTORY.md`.
  - Master unit test suite: 47/47 offline unit tests passing (`test_database.py`, `test_vidout.py`, `test_9xmovies.py`).
  - Strict staging DB isolation maintained across all sites. Zero merges into production `fast_fetch.db`.
- **Next step:** Monitor active crawlers, resolve next batch of sites, and review Qwen-generated modules.

Do not put passwords, API keys, login tokens, or other credentials here.
