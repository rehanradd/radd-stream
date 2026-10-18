# Antigravity project handoff

Use this file for a short, durable summary when you want to continue work in a
new conversation or after signing in again. It supplements Antigravity's
`/resume` history; it is not a full transcript.

- **Current goal:** Safely improve Radd Stream crawler throughput and make every pending or parser-empty URL visible and retryable.
- **Important decisions:** Never merge staging databases unless the user requests that specific merge, then provide source/target/counts/verified backup plan and obtain separate explicit confirmation. Do not interrupt the active Vegamovies crawler. Do not deploy to Oracle until its host identity is independently verified.
- **Current state:** Vegamovies was the only active Oracle crawler at the latest read-only check (PID 76635, 5 workers, ~0.15 titles/sec; 11,471 scraped, 2,615 pending, 230 review rows). Rogmovies stopped with 28 review rows; SSRMovies stopped with 7 pending rows. Crawler changes passed compilation and 20 targeted tests and were pushed to GitHub review branch `agent/staging-merge-approval-gate-20261018` at `d109c37` (not merged to `main`). No Oracle files/services or staging databases were changed.
- **Next step:** Monitor Vegamovies read-only. Never deploy to Oracle until host identity is independently verified, and never merge a staging database without the explicit approval process above.

The Antigravity CLI's local recovery files preserve only selected settings and the last-conversation index, not full transcripts or login credentials. Replit project files and this handoff preserve project context, but cannot restore lost Antigravity account history or authentication.

Do not put passwords, API keys, login tokens, or other credentials here.
