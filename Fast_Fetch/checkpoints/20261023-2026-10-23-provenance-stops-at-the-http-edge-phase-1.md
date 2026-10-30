# 🔒 2026-10-23 — Provenance stops at the HTTP edge (Phase 1)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 🔒 2026-10-23 — Provenance stops at the HTTP edge (Phase 1)

- `Fast_Fetch/redact.py` is now the single place the public shape of the catalog is
  decided: `project(row, view)` allowlists by **output key** (a new ledger column is
  invisible until deliberately published), `scrub()` is a recursive deny-list for
  hand-built trees, `mint_token`/`parse_token` replace stable row ids with opaque signed
  handles, and `assert_clean`/`is_clean` scan for site and hoster names.
- Rewired emitters: `/api/data`, `/api/sitemap`, `/api/m3u`, `/api/v1/posts[/{id}]`,
  `/api/v1/stream`, and the v2 read layer in `catalog_api.py`. **`/api/v1/rules` is gone
  from the public port** — it used to hand clients the hoster endpoints to unwrap, which
  is exactly the "someone rebuilds our catalog in their own app" hole. Unwrapping is
  server-side only now.
- Operator provenance moved to a **second loopback port** (`RADD_INTERNAL_PORT`, default
  8081) rather than an `/internal` path family: a request can forge a header, not a port.
  The public port 404s `OPERATOR_ONLY_ROUTES`; raw row ids 400 on `/api/v1/stream`.
- Sentence-level display cleaning, learned from the real 109k ledger: a release label that
  turns into a server introduction is cut at the marker; a label that is *nothing but* an
  introduction returns empty so the caller uses our own title; an unheard-of domain is
  deleted by shape; a deletion never leaves a dangling connective or an orphan TLD.
- `Fast_Fetch/sweep_public_edge.py` is the committed real-data gate (exit 0 == the public
  port named no site, no hoster and no upstream host across every route and 68 sampled
  posts). On a full-catalog snapshot the only hosts inside public bodies are `127.0.0.1`,
  `image.tmdb.org`, `m.media-amazon.com`. Bulk-checked over all 96,707 public
  `clean_title`s: 604 changed, and the only title that empties is one whose whole title
  *is* a site name. `Ra.One`, `B.Tech Girly Gang`, `C.I.Ape`, `BA.BL`, `Mr.Fang`,
  `U.S.A. Today`, `From`, `Is`, `Kidnapping Inc.` are pinned by tests as must-not-break.
- Tests green: `test_redact.py` 46, `test_catalog_api.py` 113, `test_database.py` 50, plus
  the 29-module offline sweep (live `test_all_sites` still fails on network, as before).
- Honest limits, recorded in `API_V2.md` §16.9 and `ANDROID_INTEGRATION.md`: this is
  metadata suppression, not access control. The 302 stream/art redirects still reveal an
  upstream host in a network capture, and the database and logs keep provenance by design.
  Proxying every byte through this 1-core VM was rejected on load grounds.

