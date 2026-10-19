# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor 4 concurrent background crawlers on Oracle VM (10xflix, World4uFree, Bolly4u, KatMovieHD) and maintain strict staging database isolation.
- **Current state:** Active Oracle VM crawlers & deployments:
  1. 10xflix: Actively crawling (PID 146221/146852, 12,170+ catalog posts, 43,637+ releases, 151,865+ direct sources extracted, 0 failures).
  2. World4uFree: Actively crawling (PID 152560/153724, 24,240 catalog titles synced, 5,149+ releases, 49,367+ direct sources, 1,138 direct 10Gbps Cloudflare Worker .mkv streams).
  3. Bolly4u: Actively running (PID 156129/156130, syncing 36.7k catalog titles via WP REST API into bolly4u.db, then launching 6-worker crawler with photojin Google CDN 10Gbps direct streams).
  4. KatMovieHD: Actively running (PID 156329/156330, unconstrained full catalog sync of 5,000+ pages / 60k titles via SvelteKit API into katmoviehd.db, followed by 5-worker crawler with DandnDn API & Cloudflare R2 / PixelDrain CDN).
  5. FilmyZilla: Completed (4,149 scraped, 13,114 releases, 13,516 direct sources, 402 Google CDN 302 streams).
  - Finished 100% staging catalogs: SSRMovies (27,000 / 27,000), Rogmovies (7,868 / 7,868), HDTVB (5,692 / 5,692), Vegamovies (13,978 / 14,316), MultiMovies (10,488 / 10,488), 7StarHD (23,446 / 23,446), RareAnimes (2,624 / 2,624), HDHub4u (14,504 / 14,504).
  - Master unit test suite: 145/145 unit tests passing (100% OK) across 14 modules.
  - Strict staging DB isolation maintained across all sites (`10xflix.db`, `world4ufree.db`, `bolly4u.db`, `katmoviehd.db`, `filmyzilla.db`). Zero merges into production fast_fetch.db.
- **Next step:** Monitor all 4 live crawlers (`check_10xflix.py`, `check_world4ufree.py`, `check_bolly4u.py`, `check_katmoviehd.py`) and keep Oracle VM running cleanly.

The Antigravity CLI's local recovery files preserve only selected settings and the last-conversation index, not full transcripts or login credentials. Replit project files and this handoff preserve project context, but cannot restore lost Antigravity account history or authentication.

Do not put passwords, API keys, login tokens, or other credentials here.
