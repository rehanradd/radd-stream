# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Monitor concurrent live crawling for Vegamovies, 7StarHD, HDHub4u, and RareAnimes on Oracle VM, uphold staging database isolation, and track completion progress.
- **Current state:** Four active Oracle crawlers running concurrently in background:
  1. Vegamovies (PID 76635, 5 workers, 0.3s delay; ~88%, 12,555+ / 14,316 scraped, 106,991+ releases, 332,762+ direct sources, 71k+ Google CDN direct streams).
  2. 7StarHD (PID 120570, 6 workers, 0.3s delay; ~20%, 4,635+ / 23,446 scraped, 10,395+ releases, 39,791+ direct sources).
  3. HDHub4u (PID 121847, 5 workers, 0.3s delay; 14,504 titles indexed via Typesense API into hdhub4u.db, actively unwrapping releases and 10Gbps R2 streams).
  4. RareAnimes (PID 123020, 5 workers, 0.3s delay; 2,624 titles indexed via WP REST API + Master Index into rareanimes.db, unwrapping PixelDrain CDN direct streams and Cloudflare R2).
  - Finished 100% staging catalogs: SSRMovies (27,000 / 27,000), Rogmovies (7,868 / 7,868), HDTVB (5,692 / 5,692), and MultiMovies (10,488 / 10,488).
  - All 122 unit tests passing (36 database, 6 vidout, 20 vegamovies/rogmovies, 16 ssrmovies, 5 7starhd, 25 hdhub4u, 14 rareanimes). Strict staging DB isolation maintained with zero merges.
- **Next step:** Monitor all four crawlers (`python3 check_vegamovies.py`, `python3 check_7starhd.py`, `python3 check_hdhub4u.py`, `python3 check_rareanimes.py`).

The Antigravity CLI's local recovery files preserve only selected settings and the last-conversation index, not full transcripts or login credentials. Replit project files and this handoff preserve project context, but cannot restore lost Antigravity account history or authentication.

Do not put passwords, API keys, login tokens, or other credentials here.
