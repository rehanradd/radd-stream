# Spec Fast Fetch Todo

> Moved **verbatim** out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `Fast_Fetch/AGENTS.md`
> carried at this sha. Law stayed in `Fast_Fetch/AGENTS.md`; this is the reference prose it now links to.
### from `Fast_Fetch/AGENTS.md` lines 266-283

### High Priority
- [ ] Add `watch-movies.com.pk` — Cloudflare JS challenge, needs special User-Agent + cookie headers
- [ ] Add `hdmoviesbd.xyz` — NXDOMAIN, find current mirror domain
- [ ] Add paginated HDHub4u category crawl (has `/category/` pages with 100s of posts each)
- [ ] Implement `greenmotors.cc` JS resolver (headless or regex-based decode of base64 payload)
- [ ] Implement `10moviesz.mom` resolver (follow redirect chain to final HubCloud/PixelDrain)

### Medium Priority
- [ ] Add more sites: filmywap, filmyhit, mp4moviez, world4ufree, bolly4u
- [ ] Build simple HTTP API server (stdlib `http.server`) over SQLite — `/api/search?q=...`, `/api/movie/<id>`
- [ ] Add auto-crawl scheduler (run `crawl` on a cron via `schedule` stdlib or external cron)
- [ ] Implement `heal --all` to batch re-resolve all expired/dead sources

### Low Priority
- [ ] Add M3U playlist export (`python fast_fetch.py export m3u`)
- [ ] Add Stremio addon interface (CORS-enabled HTTP server on port 7000)
- [ ] Add poster download/cache to local `posters/` folder
- [ ] Build a Telegram bot frontend for search/fetch commands
