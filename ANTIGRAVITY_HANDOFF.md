# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor active background scrapers (10xflix & KatMovieHD) on Oracle VM, uphold staging database isolation, and track crawler progress.
- **Current state:** Active Oracle crawlers running concurrently in background:
  1. 10xflix (PID 146221, syncing all 17,606 titles via WP REST API into 10xflix.db, unwrapping MobileJSR to HubCloud 10G & FilePress Google Drive).
  2. KatMovieHD (completed initial 1,200 batch with 293 scraped; HubCloud concurrency diagnosed; standing by).
  - Previous crawler milestones:
    * Vegamovies: Complete run finished (13,978 / 14,316 scraped, 131,654 releases, 397,888 direct sources, 85,138 Google CDN direct streams).
    * 7StarHD: Phase completed (15,508 / 23,446 scraped, 33,197 releases, 98,199 direct sources).
    * HDHub4u: Phase completed (10,893 scraped, 47,361 releases, 103,964 direct sources).
    * RareAnimes: Completed initial pass (1,329 scraped, 17,419 releases, 53,767 sources, 20,283 PixelDrain direct, 4,219 Cloudflare R2).
  - Finished 100% staging catalogs: SSRMovies (27,000 / 27,000), Rogmovies (7,868 / 7,868), HDTVB (5,692 / 5,692), and MultiMovies (10,488 / 10,488).
  - Full test suite passing (125/125 unit tests). Strict staging DB isolation maintained with zero merges.
- **Next step:** Monitor 10xflix (`python3 check_10xflix.py`) and KatMovieHD (`python3 check_katmoviehd.py`).

The Antigravity CLI's local recovery files preserve only selected settings and the last-conversation index, not full transcripts or login credentials. Replit project files and this handoff preserve project context, but cannot restore lost Antigravity account history or authentication.

Do not put passwords, API keys, login tokens, or other credentials here.
