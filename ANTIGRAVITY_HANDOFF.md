# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor active background crawlers on Oracle VM (Bolly4u, World4uFree, MoviezGuru, KatMovieHD), run Master-Disciple dual-tier local AI workflow (Ollama Qwen 2.5 Coder 1.5B via `/usr/local/bin/disciple`), enrich scrapers with 100% metadata (director, cast, genres, languages, synopsis), maintain staging DB isolation, and expand streaming database catalog.
- **Current state:** Active Oracle VM crawlers & tools:
  1. 10xflix: Completed 100% (13,738 posts, 76,716 releases, 227,000 direct sources in `/home/ubuntu/radd-stream-data/10xflix.db`).
  2. 9xmovies: Completed 100% (11,560 posts, 29,663 releases, 323,565 direct sources in `/home/ubuntu/radd-stream-data/9xmovies.db`).
  3. DesiCinemas: Completed 100% (5,270 titles, 5,270 releases, 4,325 streaming sources with rich metadata in `/home/ubuntu/radd-stream-data/desicinemas.db`).
  4. Bolly4u: Actively crawling (PID 161377, 6 workers, >26,300 titles processed, >35,500 releases, 21,875 sources, 12,677 Google CDN 10Gbps direct streams).
  5. World4uFree: Actively re-crawling (PID 249172, 6 workers, multi-domain parser for `fastilinks.beauty`, `wlinksi.site`, `cloud.mail.ru`, and fallback gateways; >10,500 processed, >55,700 releases, >63,500 sources).
  6. MoviezGuru: Actively crawling (PID 277265, 4 workers, 3,391 titles, mzgserver bridge unwrapper yielding 10Gbps Google CDN streams; >600 processed, >1,290 releases).
  7. KatMovieHD: OVERHAULED & actively crawling (PID 302661, 4 workers, 47,215 titles re-queued, BBUpload AJAX direct download unwrap + GoFile direct cloud + 1XPlayer streams, full rich metadata extraction; dedicated DB `/home/ubuntu/radd-stream-data/katmoviehd.db`).
  - Fleet metrics: 17 staging databases, 129,697 posts, 1,121,719 releases, 2,945,395 sources (~3.1 GB).
  - Local AI Disciple: `disciple` CLI tool (`/usr/local/bin/disciple` -> `Fast_Fetch/disciple.py`) wired to local Ollama (`qwen2.5-coder:1.5b`) on CPU (0 cloud tokens) for boilerplate code, regex, and unit test generation.
  - Real-Time Chat Sync: `auto_chat_sync.py` running in background daemon (PID 210724), continuously saving message turns into `Fast_Fetch/CHAT_HISTORY.md`.
  - Master unit test suite: 65/65 offline unit tests passing (`test_database.py`, `test_vidout.py`, `test_9xmovies.py`, `test_moviezguru.py`, `test_desicinemas.py`, `test_katmoviehd.py`).
  - Strict staging DB isolation maintained across all sites. Zero merges into production `fast_fetch.db`.
- **Next step:** Enrich metadata (cast, director, synopsis) in remaining scrapers (`import_9xmovies.py`, `import_10xflix.py`, `import_hdhub4u.py`), backup staging databases to Hugging Face, and analyze next media source.

Do not put passwords, API keys, login tokens, or other credentials here.
