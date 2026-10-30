# moved verbatim out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

## 8. Domain Self-Healing Mechanism

When a site changes domain (happens every 1-3 months):

1. `http_get()` follows 301/302 redirects — `final_url` captures the new domain
2. `normalize_url()` rewrites stored old-domain URLs to current before fetch
3. `harvest_sister_domains()` scrapes nav links — captures new domains from cross-links
4. `probe_candidate_domains()` tries known TLD variants if site goes dark
5. Manual override: `python fast_fetch.py set-domain vegamovies https://vegamovies.newdomain.com`
6. Batch migration: `python fast_fetch.py domain migrate oldhost.com newhost.com`

**TLD rotation patterns (known):**
- Vegamovies: `.gallery` → `.yt` → `.one` → `.im` → `.vip` → `.beer`
- RogMovies: `.wtf` → `.one` → `.vip` → `.club`
- SSRMovies: `.games` → `.gripe` → `.monster` → `.club`
- FilmyZilla: `71` → `73` → `74` → `75`... (numeric increment)
- HDHub4u: `new1` → `new2` → `new3`... (numeric `new#` prefix)

---

