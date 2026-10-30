# moved verbatim out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

## 5. Cinemeta API (Free Metadata Enrichment)

No API key needed. Called automatically in `save_scraped_data()` if rating/poster/genres missing.

```
Movie search:
GET https://v3-cinemeta.strem.io/catalog/movie/top/search=<TITLE>.json
→ { "metas": [{"id": "tt...", "name": "...", "poster": "...", "imdbRating": "7.5", "genres": [...]}] }

Series search:
GET https://v3-cinemeta.strem.io/catalog/series/top/search=<TITLE>.json
→ same structure

By IMDb ID:
GET https://v3-cinemeta.strem.io/meta/movie/tt1234567.json
→ { "meta": {"poster": "...", "background": "...", "description": "...", "genres": [...]} }
```

---

