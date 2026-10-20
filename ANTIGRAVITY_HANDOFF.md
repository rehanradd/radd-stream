# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor active background crawlers on Oracle VM (Bolly4u, World4uFree, MoviezGuru, DesiCinemas), run Master-Disciple dual-tier local AI workflow (Ollama Qwen 2.5 Coder 1.5B via `/usr/local/bin/disciple`), maintain staging DB isolation, and expand streaming database catalog.
- **Current state:** Active Oracle VM crawlers & tools:
  1. 10xflix: Completed 100% (13,738 posts, 76,716 releases, 227,000 direct sources in `/home/ubuntu/radd-stream-data/10xflix.db`).
  2. 9xmovies: Completed 100% (11,560 posts, 29,663 releases, 323,565 direct sources in `/home/ubuntu/radd-stream-data/9xmovies.db`).
  3. Bolly4u: Actively crawling (PID 161377, 6 workers, 24,400+ titles processed, 33,500+ releases, Google CDN 10Gbps direct streams).
  4. World4uFree: Actively re-crawling (PID 249172, 6 workers, multi-domain parser for `fastilinks.beauty`, `wlinksi.site`, `cloud.mail.ru`, and fallback gateways; >8,200 processed, >46,600 sources).
  5. MoviezGuru: Actively crawling (PID 277265, 4 workers, 3,391 titles, mzgserver bridge unwrapper yielding 10Gbps Google CDN streams).
  6. DesiCinemas: CONQUERED & actively crawling (PID 286778, 4 workers, 5,299 titles across 7 sitemaps, DooPlay trembed unwrapping + Dean Edwards unpacker for peytonepre direct .m3u8 HLS streams; dedicated DB `/home/ubuntu/radd-stream-data/desicinemas.db`).
  - Finished 100% staging catalogs: 10xflix (13.7k), 9xmovies (11.5k), SSRMovies (27k), Rogmovies (7.8k), HDTVB (5.6k), Vegamovies (14k), MultiMovies (10.4k), 7StarHD (23.4k), RareAnimes (2.6k), HDHub4u (14.5k), FilmyZilla (4.1k).
  - Local AI Disciple: `disciple` CLI tool (`/usr/local/bin/disciple` -> `Fast_Fetch/disciple.py`) wired to local Ollama (`qwen2.5-coder:1.5b`) on CPU (0 cloud tokens) for boilerplate code, regex, and unit test generation.
  - Real-Time Chat Sync: `auto_chat_sync.py` running in background daemon (PID 210724), continuously saving message turns into `Fast_Fetch/CHAT_HISTORY.md`.
  - Master unit test suite: 60/60 offline unit tests passing (`test_database.py`, `test_vidout.py`, `test_9xmovies.py`, `test_moviezguru.py`, `test_desicinemas.py`).
  - Strict staging DB isolation maintained across all sites. Zero merges into production `fast_fetch.db`.
- **Next step:** Monitor active crawlers, sync database snapshot to Hugging Face, and analyze next media source.

Do not put passwords, API keys, login tokens, or other credentials here.
