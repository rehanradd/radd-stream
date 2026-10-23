#!/usr/bin/env python3
"""
Fast_Fetch Database Viewer & Site Explorer v2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Modern, responsive local web dashboard to:
1. Explore all saved database releases with season/episode filters & direct CDN copy.
2. Search through all 14,025 site posts with 1-click on-demand scraping & link unwrapping.
3. Export VLC / M3U streaming playlists for any series or movie.

Usage:
  python viewer.py [PORT]     (Default: http://localhost:8080)
"""

from __future__ import annotations
import sys
import json
import sqlite3
import urllib.parse
from contextlib import contextmanager
import os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import redact

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent.resolve()
_env_db = os.environ.get("RADD_DB_PATH")
DB_PATH = Path(_env_db) if _env_db else BASE_DIR / "fast_fetch.db"
_SCHEMA_READY_FOR = None

#: Where our own absolute URLs (stream/art handles, playlist entries) are
#: rooted. Empty means "whatever the request came in on", which is correct
#: behind the reverse proxy and wrong only for a bare `curl localhost`.
PUBLIC_BASE_URL = os.environ.get("RADD_PUBLIC_BASE_URL", "").rstrip("/")
#: The operator-only dashboard needs the full rows; the public port never has
#: them. Set per server instance in start_server(), never from a request.
OPERATOR_PORT = int(os.environ.get("RADD_INTERNAL_PORT", "8081"))

#: The public port answers 404 for these; they name or drive upstreams.
OPERATOR_ONLY_ROUTES = frozenset({
    "/api/sitemap",      # upstream page URLs, by site
    "/api/fetch",        # scrape any caller-supplied URL (also an SSRF)
    "/api/heal",         # re-resolve a post's links against upstreams
    "/api/health-check", # probe upstreams
    "/api/v1/rules",     # client-side bridge-unwrapping recipes
    # The whole catalog in one response, releases and links included. Even fully
    # projected it is a bulk clone of our collection and, at 109k posts, a
    # self-inflicted denial of service on this box. It is the dashboard's feed
    # only — ANDROID_INTEGRATION.md lists it as "not a client integration point"
    # — and clients use the paginated /api/v1/posts.
    "/api/data",
})

_SIGNING_SECRET = None


def signing_secret() -> str:
    global _SIGNING_SECRET
    if _SIGNING_SECRET is None:
        _SIGNING_SECRET = redact.stream_secret(DB_PATH)
    return _SIGNING_SECRET


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema():
    global _SCHEMA_READY_FOR
    if _SCHEMA_READY_FOR == DB_PATH:
        return
    import fast_fetch
    fast_fetch.init_db(DB_PATH)
    redact.set_needles(redact.site_needles(DB_PATH), redact.site_text_needles(DB_PATH))
    _SCHEMA_READY_FOR = DB_PATH


def _public_base(handler=None) -> str:
    """Absolute root for URLs we hand out. Our own Host header, never an
    upstream's — this is the only host a client is ever told about."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    if handler is not None:
        host = str(handler.headers.get("Host") or "").strip()
        if host:
            return f"http://{host}"
    return ""


def link_view(row, base_url: str = "") -> dict:
    """One `download_sources` row as the public may see it: our own opaque
    handle, our own classification, and nothing that names a hoster."""
    link = redact.project(row, "link")
    link["stream_id"] = redact.mint_token(row["id"], signing_secret())
    # The only honest thing a user may be told about *which* server plays: how it
    # behaves, not who runs it. Phase 2 of the app builds "1080p · Fast server"
    # from this plus the print's quality.
    resumable = bool(link.get("is_resumable"))
    link["label"] = "Fast direct" if resumable else "Standard"
    if base_url:
        link["play_url"] = (f"{base_url.rstrip('/')}/api/v1/stream"
                            f"?id={link['stream_id']}")
    return link


def _art_pair(row, base_url: str) -> dict:
    """Poster + backdrops as our own handles, unless the art already sits on a
    public CDN (TMDB and friends name nothing about us).

    The v1 wire keys stay, so the shipped app and the PWA render art exactly as
    before — only the value changes. Empty when the row has no artwork at all."""
    keys = set(row.keys())

    def column(name, default=None):
        return row[name] if name in keys else default

    secret = signing_secret()
    pid = row["id"]
    poster = redact.public_art_value(column("poster_url"), pid, secret, base_url, "poster")
    raw = column("backdrop_urls")
    try:
        items = json.loads(raw) if raw else []
        if isinstance(items, str):
            items = [items]
    except Exception:
        items = [u.strip() for u in str(raw or "").split(",") if u.strip()]
    backdrops = [
        redact.public_art_value(item, pid, secret, base_url, "backdrop", i)
        for i, item in enumerate(items if isinstance(items, list) else [])
        if str(item or "").strip()
    ]
    return {
        "poster_url": poster,
        # TEXT holding a JSON array of URL strings, exactly as stored — the
        # client's parser is unchanged, only the hosts inside it are ours.
        "backdrop_urls": json.dumps(backdrops) if backdrops else None,
    }


def fetch_database_payload(search_query: str = "", full: bool = False,
                           base_url: str = "") -> dict:
    """The dashboard/API catalog panel.

    `full` is the operator-only mode (loopback port): raw ledger rows, exactly as
    stored, for healing and audit. Public callers get `redact` views instead —
    and the difference is one flag at the edge, never two copies of the query."""
    if not DB_PATH.exists():
        return {"stats": {}, "posts": []}
    _ensure_schema()

    with get_db() as conn:
        s_count = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
        s_vega = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE site = 'vegamovies'").fetchone()[0]
        s_rog = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE site = 'rogmovies'").fetchone()[0]

        p_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        page_counts = {
            row["source_site"]: row["post_count"]
            for row in conn.execute(
                """
                SELECT source_site, COUNT(DISTINCT post_id) AS post_count
                FROM (
                    SELECT source_site, post_id FROM post_sources
                    UNION
                    SELECT source_site, post_id FROM releases
                    WHERE source_site IS NOT NULL AND source_site != ''
                )
                GROUP BY source_site
                """
            ).fetchall()
        }
        p_vega = page_counts.get("vegamovies", 0)
        p_rog = page_counts.get("rogmovies", 0)
        p_ssr = page_counts.get("ssrmovies", 0)
        p_kat = page_counts.get("katmoviehd", 0)
        p_7star = page_counts.get("7starhd", 0)
        p_holly = conn.execute("SELECT COUNT(*) FROM posts WHERE industry LIKE '%Hollywood%'").fetchone()[0]
        p_bolly = conn.execute("SELECT COUNT(*) FROM posts WHERE industry LIKE '%Bollywood%' OR country = 'India'").fetchone()[0]
        p_anime = conn.execute("SELECT COUNT(*) FROM posts WHERE is_animated = 1 OR industry = 'Anime'").fetchone()[0]

        r_count = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        src_count = conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0]
        active_count = conn.execute("SELECT COUNT(*) FROM download_sources WHERE status = 'active'").fetchone()[0]
        resumable_count = conn.execute("SELECT COUNT(*) FROM download_sources WHERE is_resumable = 1").fetchone()[0]
        dead_count = conn.execute("SELECT COUNT(*) FROM download_sources WHERE status IN ('dead', 'expired')").fetchone()[0]

        stats = {
            "sitemap_cached": s_count,
            "sitemap_vega": s_vega,
            "sitemap_rog": s_rog,
            "posts_count": p_count,
            "vega_posts": p_vega,
            "rog_posts": p_rog,
            "ssr_posts": p_ssr,
            "kat_posts": p_kat,
            "star7_posts": p_7star,
            "hollywood_count": p_holly,
            "bollywood_count": p_bolly,
            "anime_count": p_anime,
            "releases_count": r_count,
            "sources_count": src_count,
            "active_sources": active_count,
            "resumable_sources": resumable_count,
            "dead_sources": dead_count,
        }

        sql = f"SELECT * FROM posts WHERE {redact.adult_clause('posts')}"
        params = []
        if search_query:
            sql += " AND (clean_title LIKE ? OR title LIKE ? OR slug LIKE ? OR industry LIKE ? OR country LIKE ? OR language LIKE ?)"
            p = f"%{search_query}%"
            params = [p, p, p, p, p, p]
        sql += " ORDER BY id DESC"
        post_rows = conn.execute(sql, params).fetchall()

        posts = []
        for p in post_rows:
            pid = p["id"]
            rel_rows = conn.execute(
                "SELECT * FROM releases WHERE post_id = ? ORDER BY season ASC, episode ASC, quality DESC, id ASC",
                (pid,),
            ).fetchall()

            releases = []
            for r in rel_rows:
                rid = r["id"]
                src_rows = conn.execute(
                    "SELECT * FROM download_sources WHERE release_id = ? ORDER BY id ASC",
                    (rid,),
                ).fetchall()
                sources = ([dict(s) for s in src_rows] if full else
                           [link_view(s, base_url) for s in src_rows])

                if full:
                    r_dict = dict(r)
                else:
                    r_dict = redact.project(r, "release")
                    r_dict["label"] = redact.public_label(r)
                r_dict["sources"] = sources
                releases.append(r_dict)

            if full:
                p_dict = dict(p)
                p_dict["source_pages"] = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT source_site, url, source_title, source_slug, first_seen_at, last_seen_at "
                        "FROM post_sources WHERE post_id = ? ORDER BY source_site, url",
                        (pid,),
                    ).fetchall()
                ]
            else:
                p_dict = redact.project(p, "post_detail")
                p_dict.update(_art_pair(p, base_url))
            p_dict["releases"] = releases
            posts.append(p_dict)

        if not full:
            stats = redact.project(stats, "dashboard_stats")
        return {"stats": stats, "posts": posts}


def search_sitemap_api(query: str, site: str = "", limit: int = 50) -> list[dict]:
    """Operator-only: the upstream sitemap index, with its page URLs and sites.

    Served on the loopback port and nowhere else — there is no public reading of
    it that would not be a list of upstream pages."""
    words = [w.strip().lower() for w in query.split() if w.strip()]
    with get_db() as conn:
        conditions = []
        params = []
        if words:
            conditions.extend(["slug LIKE ?" for _ in words])
            params.extend([f"%{w}%" for w in words])
        if site and site != "all":
            conditions.append("site = ?")
            params.append(site)

        sql = "SELECT loc, slug, lastmod, scraped, site FROM sitemap_cache"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY lastmod DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def generate_m3u_playlist(post_id: int, full: bool = False,
                          base_url: str = "") -> str:
    """VLC / Kodi playlist for one work.

    Public entries are our own ``/api/v1/stream`` handles, so a playlist file
    handed to a friend names no site and no hoster; the player still follows the
    redirect and gets bytes. `full` (loopback port only) keeps today's operator
    listing: hoster name in the title and the raw upstream URL, which is what a
    healer needs to see."""
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post or post["is_18_plus"]:
            return ""

        releases = conn.execute("SELECT * FROM releases WHERE post_id = ? ORDER BY season ASC, episode ASC, quality DESC, id ASC", (post_id,)).fetchall()
        lines = ["#EXTM3U", f"#PLAYLIST:{redact.scrub_text(post['clean_title'])} ({post['year'] or ''})"]

        for r in releases:
            sources = conn.execute("""
                SELECT * FROM download_sources
                WHERE release_id = ? AND status != 'dead'
                ORDER BY is_resumable DESC, id ASC
            """, (r["id"],)).fetchall()
            for s in sources:
                dur = "-1"
                res_tag = " [⚡Resumable]" if s["is_resumable"] else ""
                if full:
                    title = f"{post['clean_title']} - {r['release_title']} [{s['source_name']}]{res_tag}"
                    target = s["final_url"]
                else:
                    label = redact.public_label(r) or ""
                    title = f"{redact.scrub_text(post['clean_title'])} - {label}{res_tag}"
                    handle = redact.mint_token(s["id"], signing_secret())
                    root = (base_url or "").rstrip("/") or "http://localhost:8080"
                    target = f"{root}/api/v1/stream?id={handle}"
                lines.append(f"#EXTINF:{dur},{title}")
                lines.append(target)

        return "\n".join(lines)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Fast_Fetch — Database & Site Explorer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #111827;
      --card-border: #1f2937;
      --card-hover: #1e293b;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --accent-glow: rgba(59, 130, 246, 0.25);
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.2);
      --warning: #f59e0b;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      padding: 24px 20px 60px;
    }
    .container { max-width: 1320px; margin: 0 auto; }

    /* Header */
    header {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
    }
    .logo-area { display: flex; align-items: center; gap: 12px; }
    .logo-badge {
      background: linear-gradient(135deg, #3b82f6, #10b981);
      color: #fff;
      font-weight: 800;
      font-size: 18px;
      padding: 8px 14px;
      border-radius: 10px;
      letter-spacing: 0.5px;
      box-shadow: 0 4px 15px var(--accent-glow);
    }
    .logo-title h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .logo-title p { font-size: 13px; color: var(--text-muted); }

    /* Navigation Tabs */
    .nav-tabs {
      display: flex;
      gap: 10px;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 12px;
    }
    .tab-btn {
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      font-size: 14px;
      font-weight: 700;
      padding: 10px 20px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.15s;
    }
    .tab-btn:hover { color: #fff; background: var(--card-bg); }
    .tab-btn.active {
      background: var(--card-bg);
      border-color: var(--card-border);
      color: var(--accent);
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }

    /* Stats Grid */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .stat-card:hover { border-color: #374151; transform: translateY(-2px); }
    .stat-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
    .stat-val { font-size: 26px; font-weight: 800; color: #fff; }

    /* Controls Bar */
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 24px;
      align-items: center;
    }
    .search-input {
      flex: 1;
      min-width: 280px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text);
      font-size: 15px;
      padding: 12px 18px;
      border-radius: 10px;
      outline: none;
      font-family: inherit;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .search-input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .filter-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 10px 16px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    .filter-btn:hover { color: #fff; border-color: #4b5563; }
    .filter-btn.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      box-shadow: 0 4px 12px var(--accent-glow);
    }

    /* Media Cards */
    .media-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      margin-bottom: 20px;
      overflow: hidden;
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
      transition: border-color 0.2s;
    }
    .media-card:hover { border-color: #374151; }
    .media-header {
      padding: 18px 22px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      background: rgba(255, 255, 255, 0.02);
      border-bottom: 1px solid var(--card-border);
    }
    .media-title-group { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .media-title { font-size: 18px; font-weight: 700; color: #fff; }
    .media-badge {
      font-size: 11px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .badge-movie { background: #3730a3; color: #c7d2fe; }
    .badge-series { background: #065f46; color: #a7f3d0; }
    .badge-ongoing { background: #854d0e; color: #fef08a; }
    .badge-year { background: #1f2937; color: var(--text-muted); }
    .badge-season { background: #1e3a8a; color: #bfdbfe; font-weight: 700; }
    .badge-18 { background: #7f1d1d; color: #fecaca; border: 1px solid #ef4444; box-shadow: 0 0 10px rgba(239,68,68,0.3); font-weight: 800; }
    .badge-anim { background: #581c87; color: #e9d5ff; border: 1px solid #a855f7; font-weight: 800; }
    .badge-imdb { background: #78350f; color: #fde047; font-weight: 800; border: 1px solid #d97706; }
    .badge-vega { background: #1e1b4b; color: #a5b4fc; border: 1px solid #4f46e5; font-weight: 700; }
    .badge-rog { background: #451a03; color: #fdba74; border: 1px solid #ea580c; font-weight: 700; }
    .badge-ssr { background: #3b0764; color: #d8b4fe; border: 1px solid #9333ea; font-weight: 700; }
    .badge-kat { background: #14532d; color: #86efac; border: 1px solid #22c55e; font-weight: 700; }
    .badge-7star { background: #701a75; color: #f472b6; border: 1px solid #db2777; font-weight: 700; }
    .badge-mm { background: #7c2d12; color: #ffedd5; border: 1px solid #ea580c; font-weight: 700; }
    .badge-10x { background: #831843; color: #fce7f3; border: 1px solid #ec4899; font-weight: 700; }
    .badge-industry { background: #082f49; color: #7dd3fc; border: 1px solid #0284c7; font-weight: 700; }
    .badge-country { background: #052e16; color: #86efac; border: 1px solid #16a34a; font-weight: 700; }
    .badge-lang { background: #2e1065; color: #d8b4fe; border: 1px solid #7e22ce; font-weight: 600; }
    .pill-genre { background: #1e293b; color: #94a3b8; border: 1px solid #334155; font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 600; }
    .pill-resumable { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 700; }
    .source-dead { opacity: 0.7; border-color: #7f1d1d !important; }
    .poster-thumb { width: 50px; height: 72px; object-fit: cover; border-radius: 6px; border: 1px solid #334155; flex-shrink: 0; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
    .btn-check { background: #1e3a8a; color: #dbeafe; border: 1px solid #3b82f6; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
    .btn-check:hover { background: #2563eb; color: #fff; }
    .btn-heal { background: #9a3412; color: #ffedd5; border: 1px solid #ea580c; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
    .btn-heal:hover { background: #c2410c; color: #fff; }

    .media-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .btn-m3u {
      background: #4338ca;
      color: #e0e7ff;
      border: 1px solid #6366f1;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.15s;
    }
    .btn-m3u:hover { background: #4f46e5; color: #fff; }

    .post-link {
      color: var(--text-dim);
      font-size: 12px;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 4px;
      transition: color 0.15s;
    }
    .post-link:hover { color: var(--accent); }

    /* Media Body */
    .media-body { padding: 20px 22px; }

    /* Season Section */
    .season-section { margin-bottom: 24px; }
    .season-section:last-child { margin-bottom: 0; }
    .season-heading {
      font-size: 14px;
      font-weight: 700;
      color: #93c5fd;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .season-heading::after {
      content: '';
      flex: 1;
      height: 1px;
      background: #1f2937;
    }

    /* Release Grid */
    .releases-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 14px;
    }
    .release-box {
      background: #161f30;
      border: 1px solid #233148;
      border-radius: 10px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transition: border-color 0.15s, background 0.15s;
    }
    .release-box:hover { border-color: #3b82f6; background: #1a253a; }
    .release-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
    }
    .release-title {
      font-size: 13px;
      font-weight: 600;
      color: #e2e8f0;
      line-height: 1.4;
      flex: 1;
    }
    .pill {
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 5px;
      white-space: nowrap;
    }
    .pill-480p { background: #334155; color: #94a3b8; }
    .pill-720p { background: #1e3a5f; color: #60a5fa; }
    .pill-1080p { background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; }
    .pill-2160p, .pill-4k { background: #581c87; color: #e9d5ff; border: 1px solid #9333ea; }
    .pill-batch { background: #065f46; color: #6ee7b7; font-weight: 700; }

    .release-meta {
      display: flex;
      gap: 10px;
      font-size: 12px;
      color: var(--text-muted);
      font-weight: 500;
    }

    /* Source Links List */
    .sources-list {
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding-top: 8px;
      border-top: 1px solid #233148;
    }
    .source-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #0f172a;
      border: 1px solid #1e293b;
      padding: 8px 12px;
      border-radius: 6px;
      gap: 8px;
      font-size: 12px;
    }
    .source-name {
      font-weight: 600;
      color: #94a3b8;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .source-actions { display: flex; align-items: center; gap: 6px; }
    .btn-action {
      background: #1e293b;
      border: 1px solid #334155;
      color: #cbd5e1;
      padding: 4px 10px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.15s;
    }
    .btn-action:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
    .btn-open { background: #064e3b; border-color: #059669; color: #a7f3d0; }
    .btn-open:hover { background: #059669; color: #fff; }

    /* Sitemap Explorer List */
    .sitemap-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .sitemap-row {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 14px 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      transition: border-color 0.15s;
    }
    .sitemap-row:hover { border-color: #3b82f6; }
    .sitemap-info { flex: 1; }
    .sitemap-title { font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 4px; }
    .sitemap-meta { font-size: 12px; color: var(--text-dim); display: flex; gap: 12px; }
    .btn-fetch {
      background: linear-gradient(135deg, #2563eb, #10b981);
      border: none;
      color: #fff;
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      box-shadow: 0 4px 12px var(--accent-glow);
      transition: transform 0.15s, opacity 0.15s;
    }
    .btn-fetch:hover { transform: scale(1.03); }
    .btn-fetch:disabled { opacity: 0.6; cursor: wait; }

    /* Toast */
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #10b981;
      color: #fff;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4);
      display: none;
      animation: fadeIn 0.2s;
      z-index: 9999;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

    /* Video Player Modal */
    .modal-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 99999;
      display: flex; align-items: center; justify-content: center; padding: 16px;
    }
    .modal-content {
      background: #0f172a; border: 1px solid #334155; border-radius: 14px;
      width: 100%; max-width: 840px; padding: 20px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.7);
    }
    .modal-header {
      display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;
    }
    .modal-close {
      background: none; border: none; color: #94a3b8; font-size: 22px; cursor: pointer; padding: 4px 8px; line-height: 1;
    }
    .modal-close:hover { color: #fff; }

    /* Empty state */
    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: var(--text-dim);
    }
    .empty-state h3 { font-size: 18px; color: var(--text-muted); margin-bottom: 8px; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-area">
        <div class="logo-badge">⚡ FAST_FETCH</div>
        <div class="logo-title">
          <h1>Direct Link Database Explorer</h1>
          <p>Instant sitemap search, season & episode manager, and direct CDN resolver</p>
        </div>
      </div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <a href="/client" class="filter-btn" style="text-decoration:none; display:inline-flex; align-items:center; gap:6px; background:#2563eb; color:white; border-color:#3b82f6;">📱 Mobile App</a>
        <button class="filter-btn" id="btn-global-check" onclick="runGlobalHealthCheck()">🩺 Check All Links</button>
        <button class="filter-btn" onclick="fetchData()">🔄 Refresh</button>
      </div>
    </header>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Sitemap URLs Cached</div>
        <div class="stat-val" id="stat-sitemap" style="color: #60a5fa;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);" id="stat-sitemap-sub">Vegamovies &amp; RogMovies</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Indexed Media Posts</div>
        <div class="stat-val" id="stat-posts">0</div>
        <div style="font-size: 11px; color: var(--text-dim);" id="stat-posts-sub">Hollywood &amp; Bollywood</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Release Variants</div>
        <div class="stat-val" id="stat-releases">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">480p, 720p, 1080p, 4K &amp; Batches</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Resolved Direct Links</div>
        <div class="stat-val" id="stat-sources" style="color: #38bdf8;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">CDN, FastDL, Pixeldrain, HubCloud</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">🟢 Verified Active</div>
        <div class="stat-val" id="stat-active" style="color: #10b981;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">Live 200 OK CDN streams</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">⚡ Resumable (Range 206)</div>
        <div class="stat-val" id="stat-resumable" style="color: #a7f3d0;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">Fast seek &amp; multi-part DL</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">🔴 Dead / Expired</div>
        <div class="stat-val" id="stat-dead" style="color: #f87171;">0</div>
        <div style="font-size: 11px; color: var(--text-dim);">Self-healing candidates</div>
      </div>
    </div>

    <div class="nav-tabs">
      <button class="tab-btn active" id="tab-db-btn" onclick="switchMainTab('db')">
        💾 Indexed Database Releases
      </button>
      <button class="tab-btn" id="tab-site-btn" onclick="switchMainTab('site')">
        🌐 Multi-Site Catalog Explorer (16,000+ Titles)
      </button>
    </div>

    <!-- TAB 1: DB RELEASES -->
    <div id="section-db">
      <div class="controls">
        <input type="text" id="search-box" class="search-input" placeholder="🔍 Search saved titles, qualities (1080p, 4K), audio, episodes, Hollywood, Bollywood..." oninput="handleSearch()">
        <button class="filter-btn active" onclick="setFilter('all', this)">All</button>
        <button class="filter-btn" onclick="setFilter('multimovies', this)">🍿 MultiMovies</button>
        <button class="filter-btn" onclick="setFilter('10xflix', this)">💥 10xflix / WWE</button>
        <button class="filter-btn" onclick="setFilter('katmoviehd', this)">🟢 KatMovieHD</button>
        <button class="filter-btn" onclick="setFilter('ssrmovies', this)">🟣 SSRMovies</button>
        <button class="filter-btn" onclick="setFilter('7starhd', this)">⭐ 7StarHD</button>
        <button class="filter-btn" onclick="setFilter('vegamovies', this)">🔵 Vegamovies</button>
        <button class="filter-btn" onclick="setFilter('rogmovies', this)">🟠 RogMovies</button>
        <button class="filter-btn" onclick="setFilter('hollywood', this)">🎬 Hollywood</button>
        <button class="filter-btn" onclick="setFilter('bollywood', this)">🇮🇳 Bollywood</button>
        <button class="filter-btn" onclick="setFilter('anime', this)">🎨 Anime</button>
        <button class="filter-btn" onclick="setFilter('movie', this)">🍿 Movies</button>
        <button class="filter-btn" onclick="setFilter('series', this)">📺 Series</button>
      </div>
      <div id="posts-container">
        <div class="empty-state">
          <h3>Loading database records...</h3>
        </div>
      </div>
    </div>

    <!-- TAB 2: SITEMAP EXPLORER -->
    <div id="section-site" style="display: none;">
      <div class="controls">
        <input type="text" id="sitemap-search-box" class="search-input" placeholder="🔍 Search any movie, anime, or series across all 16,000+ sitemapped posts..." oninput="handleSitemapSearch()">
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button class="filter-btn active" id="btn-sitemap-site-all" onclick="setSitemapSite('all', this)">🌐 All Sites</button>
          <button class="filter-btn" id="btn-sitemap-site-mm" onclick="setSitemapSite('multimovies', this)">🍿 MultiMovies</button>
          <button class="filter-btn" id="btn-sitemap-site-10x" onclick="setSitemapSite('10xflix', this)">💥 10xflix</button>
          <button class="filter-btn" id="btn-sitemap-site-kat" onclick="setSitemapSite('katmoviehd', this)">🟢 KatMovieHD</button>
          <button class="filter-btn" id="btn-sitemap-site-ssr" onclick="setSitemapSite('ssrmovies', this)">🟣 SSRMovies</button>
          <button class="filter-btn" id="btn-sitemap-site-7star" onclick="setSitemapSite('7starhd', this)">⭐ 7StarHD</button>
          <button class="filter-btn" id="btn-sitemap-site-vega" onclick="setSitemapSite('vegamovies', this)">🔵 Vegamovies</button>
          <button class="filter-btn" id="btn-sitemap-site-rog" onclick="setSitemapSite('rogmovies', this)">🟠 RogMovies</button>
        </div>
        <span style="font-size: 13px; color: var(--text-dim);" id="sitemap-count-indicator">Showing latest posts</span>
      </div>
      <div id="sitemap-container">
        <div class="empty-state">
          <h3>Search the entire site catalog...</h3>
        </div>
      </div>
    </div>
  </div>

  <div id="toast" class="toast">Link copied to clipboard!</div>

  <script>
    let dbData = { stats: {}, posts: [] };
    let currentFilter = 'all';
    let currentMainTab = 'db';
    let currentSitemapSite = 'all';
    let sitemapSearchTimer = null;

    function switchMainTab(tab) {
      currentMainTab = tab;
      document.getElementById('tab-db-btn').classList.toggle('active', tab === 'db');
      document.getElementById('tab-site-btn').classList.toggle('active', tab === 'site');
      document.getElementById('section-db').style.display = tab === 'db' ? 'block' : 'none';
      document.getElementById('section-site').style.display = tab === 'site' ? 'block' : 'none';
      if (tab === 'site') {
        fetchSitemapList();
      }
    }

    function setSitemapSite(site, el) {
      currentSitemapSite = site;
      document.querySelectorAll('#section-site .filter-btn').forEach(b => b.classList.remove('active'));
      el.classList.add('active');
      const q = document.getElementById('sitemap-search-box').value.trim();
      fetchSitemapList(q);
    }

    async function fetchData(query = '') {
      try {
        const url = '/api/data' + (query ? '?q=' + encodeURIComponent(query) : '');
        const res = await fetch(url);
        dbData = await res.json();
        renderStats();
        renderPosts();
      } catch (err) {
        console.error(err);
      }
    }

    async function runGlobalHealthCheck() {
      const btn = document.getElementById('btn-global-check');
      if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Probing All Links...';
      }
      showToast('🩺 Running health diagnostic on all links in database...');
      try {
        const res = await fetch('/api/health-check');
        const data = await res.json();
        if (data.success) {
          showToast('✓ Probed ' + data.count + ' links across database!');
          await fetchData(document.getElementById('search-box').value.trim());
        } else {
          alert('Health check error: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Health check error: ' + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerText = '🩺 Check All Links';
        }
      }
    }

    async function fetchSitemapList(query = '') {
      const container = document.getElementById('sitemap-container');
      container.innerHTML = `<div class="empty-state"><h3>Searching site catalog...</h3></div>`;
      try {
        const url = `/api/sitemap?q=${encodeURIComponent(query)}&site=${encodeURIComponent(currentSitemapSite)}`;
        const res = await fetch(url);
        const rows = await res.json();
        renderSitemapRows(rows);
      } catch (err) {
        container.innerHTML = `<div class="empty-state"><h3>Error searching sitemap</h3></div>`;
      }
    }

    function renderSitemapRows(rows) {
      const container = document.getElementById('sitemap-container');
      document.getElementById('sitemap-count-indicator').innerText = `Found ${rows.length} posts`;

      if (!rows || rows.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <h3>No matching titles found in sitemap</h3>
          </div>
        `;
        return;
      }

      let html = '<div class="sitemap-list">';
      for (const r of rows) {
        const isScraped = r.scraped === 1;
        let siteTag = `<span class="media-badge badge-vega" style="margin-right: 8px;">VEGAMOVIES</span>`;
        if (r.site === 'rogmovies') siteTag = `<span class="media-badge badge-rog" style="margin-right: 8px;">ROGMOVIES</span>`;
        else if (r.site === 'ssrmovies') siteTag = `<span class="media-badge badge-ssr" style="margin-right: 8px;">SSRMOVIES</span>`;
        else if (r.site === 'katmoviehd') siteTag = `<span class="media-badge badge-kat" style="margin-right: 8px;">KATMOVIEHD</span>`;
        else if (r.site === '7starhd') siteTag = `<span class="media-badge badge-7star" style="margin-right: 8px;">7STARHD</span>`;
        else if (r.site === 'multimovies') siteTag = `<span class="media-badge badge-mm" style="margin-right: 8px;">MULTIMOVIES</span>`;
        else if (r.site === '10xflix') siteTag = `<span class="media-badge badge-10x" style="margin-right: 8px;">10XFLIX</span>`;
        const btnHtml = isScraped
          ? `<button class="btn-action" onclick="viewInDb('${r.slug}')">✓ View in DB</button>`
          : `<button class="btn-fetch" id="btn-fetch-${r.slug}" onclick="fetchPostOnDemand('${r.loc}', '${r.slug}')">⚡ Resolve Direct Links</button>`;

        html += `
          <div class="sitemap-row">
            <div class="sitemap-info">
              <div class="sitemap-title">${siteTag}${r.slug}</div>
              <div class="sitemap-meta">
                <span>📅 ${r.lastmod.split('T')[0] || r.lastmod}</span>
                <a href="${r.loc}" target="_blank" class="post-link">Original Page ↗</a>
              </div>
            </div>
            <div>${btnHtml}</div>
          </div>
        `;
      }
      html += '</div>';
      container.innerHTML = html;
    }

    async function fetchPostOnDemand(url, slug) {
      const btn = document.getElementById(`btn-fetch-${slug}`);
      if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Resolving Links...';
      }
      try {
        const res = await fetch('/api/fetch?url=' + encodeURIComponent(url));
        const resData = await res.json();
        if (resData.success) {
          showToast('✓ Successfully resolved and saved to database!');
          await fetchData();
          switchMainTab('db');
          document.getElementById('search-box').value = resData.clean_title || slug;
          handleSearch();
        } else {
          alert('Failed to resolve: ' + (resData.error || 'Unknown error'));
          if (btn) { btn.disabled = false; btn.innerText = '⚡ Resolve Direct Links'; }
        }
      } catch (err) {
        alert('Error: ' + err.message);
        if (btn) { btn.disabled = false; btn.innerText = '⚡ Resolve Direct Links'; }
      }
    }

    function viewInDb(slug) {
      switchMainTab('db');
      document.getElementById('search-box').value = slug;
      handleSearch();
    }

    function handleSitemapSearch() {
      clearTimeout(sitemapSearchTimer);
      const q = document.getElementById('sitemap-search-box').value.trim();
      sitemapSearchTimer = setTimeout(() => {
        fetchSitemapList(q);
      }, 250);
    }

    function renderStats() {
      const s = dbData.stats || {};
      document.getElementById('stat-posts').innerText = (s.posts_count || 0).toLocaleString();
      if (document.getElementById('stat-posts-sub')) {
        document.getElementById('stat-posts-sub').innerText = `🎬 ${s.hollywood_count || 0} Holly · 🇮🇳 ${s.bollywood_count || 0} Bolly · 🎨 ${s.anime_count || 0} Anime`;
      }
      document.getElementById('stat-releases').innerText = (s.releases_count || 0).toLocaleString();
      document.getElementById('stat-sources').innerText = (s.sources_count || 0).toLocaleString();
      document.getElementById('stat-sitemap').innerText = (s.sitemap_cached || 0).toLocaleString();
      if (document.getElementById('stat-sitemap-sub')) {
        document.getElementById('stat-sitemap-sub').innerText = `Vega: ${(s.sitemap_vega || 0).toLocaleString()} · Rog: ${(s.sitemap_rog || 0).toLocaleString()}`;
      }
      if (document.getElementById('stat-active')) {
        document.getElementById('stat-active').innerText = (s.active_sources || 0).toLocaleString();
      }
      if (document.getElementById('stat-resumable')) {
        document.getElementById('stat-resumable').innerText = (s.resumable_sources || 0).toLocaleString();
      }
      if (document.getElementById('stat-dead')) {
        document.getElementById('stat-dead').innerText = (s.dead_sources || 0).toLocaleString();
      }
    }

    function setFilter(type, el) {
      currentFilter = type;
      document.querySelectorAll('#section-db .filter-btn').forEach(b => b.classList.remove('active'));
      el.classList.add('active');
      renderPosts();
    }

    function handleSearch() {
      const q = document.getElementById('search-box').value.trim();
      fetchData(q);
    }

    function copyToClipboard(text) {
      navigator.clipboard.writeText(text).then(() => {
        showToast('Link copied to clipboard!');
      });
    }

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.innerText = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 2200);
    }

    async function checkHealthPost(postId) {
      showToast('🩺 Probing links for post #' + postId + '...');
      try {
        const res = await fetch('/api/health-check?id=' + postId);
        const data = await res.json();
        if (data.success) {
          showToast('✓ Link health probe complete (' + data.count + ' checked)');
          fetchData(document.getElementById('search-box').value.trim());
        } else {
          alert('Health check error: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Health check error: ' + err.message);
      }
    }

    async function healPost(postId) {
      showToast('🔄 Auto-healing links for post #' + postId + '...');
      try {
        const res = await fetch('/api/heal?id=' + postId);
        const data = await res.json();
        if (data.success) {
          showToast('✓ Auto-healed! Refreshed: ' + data.healed + ' link(s)');
          fetchData(document.getElementById('search-box').value.trim());
        } else {
          alert('Auto-heal error: ' + (data.error || 'Unknown error'));
        }
      } catch (err) {
        alert('Auto-heal error: ' + err.message);
      }
    }

    function formatBytes(bytes) {
      if (!bytes || bytes <= 0) return '';
      const gb = bytes / (1024 * 1024 * 1024);
      if (gb >= 1.0) return gb.toFixed(2) + ' GB';
      const mb = bytes / (1024 * 1024);
      return mb.toFixed(1) + ' MB';
    }

    function getCountryFlag(country) {
      if (!country) return '';
      const c = country.toLowerCase();
      if (c.includes('india')) return '🇮🇳 India';
      if (c.includes('usa') || c.includes('united states')) return '🇺🇸 USA';
      if (c.includes('japan')) return '🇯🇵 Japan';
      if (c.includes('korea')) return '🇰🇷 S.Korea';
      if (c.includes('china')) return '🇨🇳 China';
      if (c.includes('uk') || c.includes('united kingdom')) return '🇬🇧 UK';
      return '📍 ' + country;
    }

    function renderPosts() {
      const container = document.getElementById('posts-container');
      let posts = dbData.posts || [];
      const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[ch]));
      const safeHttpUrl = value => {
        try {
          const parsed = new URL(String(value));
          return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : '';
        } catch (_) {
          return '';
        }
      };
      const postHasSite = (post, site) =>
        post.source_site === site ||
        (post.source_pages || []).some(source => source.source_site === site) ||
        (post.releases || []).some(release => release.source_site === site);

      if (currentFilter === 'movie') {
        posts = posts.filter(p => p.content_type === 'movie');
      } else if (currentFilter === 'series') {
        posts = posts.filter(p => p.content_type !== 'movie');
      } else if (currentFilter === 'anime') {
        posts = posts.filter(p => p.is_animated === 1 || (p.industry && p.industry.toLowerCase().includes('anime')));
      } else if (currentFilter === 'katmoviehd') {
        posts = posts.filter(p => postHasSite(p, 'katmoviehd'));
      } else if (currentFilter === 'ssrmovies') {
        posts = posts.filter(p => postHasSite(p, 'ssrmovies'));
      } else if (currentFilter === '7starhd') {
        posts = posts.filter(p => postHasSite(p, '7starhd'));
      } else if (currentFilter === 'multimovies') {
        posts = posts.filter(p => postHasSite(p, 'multimovies'));
      } else if (currentFilter === '10xflix') {
        posts = posts.filter(p => postHasSite(p, '10xflix'));
      } else if (currentFilter === 'vegamovies') {
        posts = posts.filter(p => postHasSite(p, 'vegamovies'));
      } else if (currentFilter === 'rogmovies') {
        posts = posts.filter(p => postHasSite(p, 'rogmovies'));
      } else if (currentFilter === 'hollywood') {
        posts = posts.filter(p => (p.industry && p.industry.toLowerCase().includes('hollywood')));
      } else if (currentFilter === 'bollywood') {
        posts = posts.filter(p => (p.industry && (p.industry.toLowerCase().includes('bollywood') || p.industry.toLowerCase().includes('tollywood') || p.industry.toLowerCase().includes('gujarati') || p.industry.toLowerCase().includes('punjabi') || p.industry.toLowerCase().includes('south'))) || p.country === 'India');
      }

      if (posts.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            <h3>No matching media found in database</h3>
            <p>Use the 'Multi-Site Catalog Explorer' tab to find and index any of the 16,000+ titles.</p>
          </div>
        `;
        return;
      }

      let html = '';
      for (const p of posts) {
        const badgeClass = p.content_type === 'movie' ? 'badge-movie' : (p.content_type === 'ongoing_season' ? 'badge-ongoing' : 'badge-series');
        const typeLabel = (p.content_type || 'series').replace('_', ' ').toUpperCase();

        const siteBadgeClasses = {
          vegamovies: 'badge-vega', rogmovies: 'badge-rog', ssrmovies: 'badge-ssr',
          katmoviehd: 'badge-kat', '7starhd': 'badge-7star', multimovies: 'badge-mm',
          '10xflix': 'badge-10x'
        };
        const sourceSites = [...new Set([
          p.source_site,
          ...(p.source_pages || []).map(source => source.source_site),
          ...(p.releases || []).map(release => release.source_site)
        ].filter(Boolean).map(site => String(site).toLowerCase()))];
        const siteBadges = sourceSites.map(site =>
          `<span class="media-badge ${siteBadgeClasses[site] || 'badge-vega'}">${escapeHtml(site.toUpperCase())}</span>`
        ).join('');
        const sourcePageLinks = (p.source_pages || []).map(source => {
          const href = safeHttpUrl(source.url);
          if (!href) return '';
          return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.source_site || 'Site')} ↗</a>`;
        }).filter(Boolean).join(' <span aria-hidden="true">·</span> ');
        const sourcePagesHtml = sourcePageLinks
          ? `<div style="margin:8px 0 0 58px;font-size:12px;color:var(--text-dim)">Indexed pages: ${sourcePageLinks}</div>`
          : '';
        const originalPageHref = safeHttpUrl(p.url);
        const originalPageLink = originalPageHref
          ? `<a href="${escapeHtml(originalPageHref)}" target="_blank" rel="noopener noreferrer" class="post-link">First-seen page ↗</a>`
          : '';

        const indBadge = p.industry ? `<span class="media-badge badge-industry">${p.industry}</span>` : '';
        const cntBadge = p.country ? `<span class="media-badge badge-country">${getCountryFlag(p.country)}</span>` : '';
        const langBadge = p.language ? `<span class="media-badge badge-lang">🗣️ ${p.language}</span>` : '';

        const seasonsMap = {};
        for (const r of (p.releases || [])) {
          const sKey = r.season || 'Standard Releases';
          if (!seasonsMap[sKey]) seasonsMap[sKey] = [];
          seasonsMap[sKey].push(r);
        }

        let genresList = [];
        if (p.genres) {
          try {
            genresList = JSON.parse(p.genres);
          } catch(e) {
            genresList = [p.genres];
          }
        }
        const genresHtml = genresList.map(g => `<span class="pill-genre">${g}</span>`).join(' ');

        const posterImgHtml = p.poster_url
          ? `<img src="${p.poster_url}" class="poster-thumb" alt="${p.clean_title}" loading="lazy" onerror="this.style.display='none'">`
          : '';

        html += `
          <div class="media-card">
            <div class="media-header">
              <div class="media-title-group">
                ${posterImgHtml}
                <div>
                  <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px;">
                    ${siteBadges}
                    <span class="media-badge ${badgeClass}">${typeLabel}</span>
                    <span class="media-title">${p.clean_title}</span>
                    ${p.year ? `<span class="media-badge badge-year">${p.year}</span>` : ''}
                    ${p.seasons ? `<span class="media-badge badge-season">${p.seasons}</span>` : ''}
                    ${p.is_18_plus ? `<span class="media-badge badge-18">🔞 18+ ADULT</span>` : ''}
                    ${p.is_animated ? `<span class="media-badge badge-anim">🎨 ANIME</span>` : ''}
                    ${indBadge}
                    ${cntBadge}
                    ${langBadge}
                    ${p.imdb_rating ? `<span class="media-badge badge-imdb">⭐ ${p.imdb_rating} IMDb</span>` : ''}
                  </div>
                  ${genresHtml ? `<div style="display: flex; gap: 6px; flex-wrap: wrap;">${genresHtml}</div>` : ''}
                </div>
              </div>
              <div class="media-actions">
                <button class="btn-check" onclick="checkHealthPost(${p.id})">🩺 Probe Links</button>
                <button class="btn-heal" onclick="healPost(${p.id})">🔄 Auto-Heal</button>
                <a href="/api/m3u?id=${p.id}" class="btn-m3u" download="${p.slug}.m3u">📺 VLC Playlist</a>
                ${originalPageLink}
              </div>
            </div>
            ${sourcePagesHtml}
            <div class="media-body">
        `;

        for (const [seasonName, releases] of Object.entries(seasonsMap)) {
          html += `
            <div class="season-section">
              <div class="season-heading">${seasonName} (${releases.length} options)</div>
              <div class="releases-grid">
          `;

          for (const r of releases) {
            const qClass = 'pill-' + (r.quality || '720p').toLowerCase();
            const isBatch = r.episode === 'Batch';
            const epBadge = r.episode ? `<span class="pill ${isBatch ? 'pill-batch' : 'pill-720p'}">${r.episode}</span>` : '';
            const rSiteBadge = r.source_site ? `<span class="pill" style="background:#0f172a; color:#38bdf8; border:1px solid #0284c7; font-size:10px;">${r.source_site.toUpperCase()}</span>` : '';

            html += `
              <div class="release-box">
                <div class="release-top">
                  <span class="release-title">${r.release_title}</span>
                  <div style="display: flex; gap: 4px; align-items: center; flex-wrap: wrap;">
                    ${rSiteBadge}
                    ${epBadge}
                    <span class="pill ${qClass}">${(r.quality || 'HD').toUpperCase()}</span>
                  </div>
                </div>
                <div class="release-meta">
                  ${r.size ? `<span>📦 ${r.size}</span>` : ''}
                  ${r.languages ? `<span>🌐 ${r.languages}</span>` : ''}
                  ${r.codec ? `<span>🎞️ ${r.codec}</span>` : ''}
                </div>
                <div class="sources-list">
            `;

            for (const s of (r.sources || [])) {
              const isTemp = s.is_temporary ? '⏳' : '';
              const isDead = s.status === 'dead' || s.status === 'expired';
              const isActive = s.status === 'active';
              const statusDot = isActive ? '🟢' : (isDead ? '🔴' : '⚪');
              const statusTooltip = s.http_status ? `HTTP ${s.http_status} (${s.status})` : s.status;
              const resumableBadge = s.is_resumable === 1
                ? `<span class="pill-resumable" title="HTTP Range 206 supported: Resume, Fast seek, IDM/aria2 multi-part acceleration">⚡ Resumable</span>`
                : '';
              const sizeStr = s.file_size_bytes ? `<span style="font-size: 11px; color: var(--text-dim);">${formatBytes(s.file_size_bytes)}</span>` : '';

              html += `
                <div class="source-item ${isDead ? 'source-dead' : ''}">
                  <div class="source-name" title="${statusTooltip}">
                    <span>${statusDot}</span>
                    <span>${s.source_name} ${isTemp}</span>
                    ${resumableBadge}
                    ${sizeStr}
                  </div>
                  <div class="source-actions">
                    <button class="btn-action" style="background:#2563eb; color:white; border-color:#3b82f6;" onclick="openStreamPlayer(${s.id}, '${escapeHtml(s.source_name || 'Direct Stream')}', '${escapeHtml(p.clean_title || 'Media Stream')}')">▶ Play JIT</button>
                    <button class="btn-action" onclick="copyToClipboard('${s.final_url}')">📋 Copy Direct URL</button>
                    <a href="/api/v1/stream?id=${s.id}&redirect=1" target="_blank" class="btn-action btn-open" title="Instant Live JIT Stream with 302 Redirect">⚡ Stream / DL</a>
                  </div>
                </div>
              `;
            }

            html += `
                </div>
              </div>
            `;
          }

          html += `
              </div>
            </div>
          `;
        }

        html += `
            </div>
          </div>
        `;
      }

      container.innerHTML = html;
    }

    let currentActiveStreamUrl = '';

    function openStreamPlayer(sourceId, sourceName, postTitle) {
      const streamUrl = `${window.location.origin}/api/v1/stream?id=${sourceId}&redirect=1`;
      currentActiveStreamUrl = streamUrl;
      document.getElementById('player-title').innerText = postTitle || 'Media Stream';
      document.getElementById('player-subtitle').innerText = `${sourceName} · Live JIT Resolver`;
      const video = document.getElementById('html5-video');
      video.src = streamUrl;
      video.load();
      video.play().catch(() => {});

      document.getElementById('player-vlc-btn').href = `vlc://${streamUrl}`;
      document.getElementById('player-mpv-btn').href = `intent:${streamUrl}#Intent;package=is.xyz.mpv;type=video/*;end`;
      document.getElementById('player-raw-btn').href = streamUrl;
      document.getElementById('player-modal').style.display = 'flex';
    }

    function closePlayerModal() {
      const modal = document.getElementById('player-modal');
      const video = document.getElementById('html5-video');
      if (video) {
        video.pause();
        video.src = '';
      }
      if (modal) modal.style.display = 'none';
    }

    function copyCurrentStreamUrl() {
      if (currentActiveStreamUrl) {
        copyToClipboard(currentActiveStreamUrl);
      }
    }

    // Initial load
    fetchData();
  </script>

  <!-- Video Player Modal -->
  <div id="player-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closePlayerModal()">
    <div class="modal-content">
      <div class="modal-header">
        <div>
          <h3 id="player-title" style="margin:0; font-size:16px; color:#fff;">Stream Player</h3>
          <span id="player-subtitle" style="font-size:12px; color:var(--text-dim);">Live JIT Stream</span>
        </div>
        <button class="modal-close" onclick="closePlayerModal()">✕</button>
      </div>
      <div style="background:#000; border-radius:8px; overflow:hidden; margin:12px 0;">
        <video id="html5-video" controls autoplay playsinline style="width:100%; max-height:460px; display:block; background:#000;"></video>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:space-between; align-items:center;">
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          <a id="player-vlc-btn" href="#" class="btn-action" style="background:#ea580c; color:white;">🎬 VLC Player</a>
          <a id="player-mpv-btn" href="#" class="btn-action" style="background:#7c3aed; color:white;">⚡ MPV Player</a>
          <a id="player-raw-btn" href="#" target="_blank" class="btn-action" style="background:#059669; color:white;">↗ Direct Window</a>
        </div>
        <button id="player-copy-btn" class="btn-action" onclick="copyCurrentStreamUrl()">📋 Copy Stream URL</button>
      </div>
    </div>
  </div>
</body>
</html>
"""

MOBILE_CLIENT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <meta name="theme-color" content="#090d16">
  <title>RaddStream · Mobile Web Player & Client</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-border: #1f2937;
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.3);
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #ef4444;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      padding-bottom: 40px;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(9, 13, 22, 0.94);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 12px 14px;
    }
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 16px;
      font-weight: 800;
      color: #fff;
    }
    .brand-badge {
      background: var(--accent);
      color: #fff;
      font-size: 9px;
      font-weight: 900;
      padding: 2px 5px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .header-links {
      display: flex;
      gap: 6px;
    }
    .icon-btn {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 5px 9px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .icon-btn:hover { color: #fff; border-color: var(--accent); }
    .search-row {
      position: relative;
      margin-bottom: 8px;
    }
    .search-input {
      width: 100%;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: #fff;
      font-size: 14px;
      padding: 8px 12px 8px 34px;
      border-radius: 8px;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow); }
    .search-icon {
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-dim);
      font-size: 13px;
      pointer-events: none;
    }
    .filter-chips {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      scrollbar-width: none;
    }
    .filter-chips::-webkit-scrollbar { display: none; }
    .chip {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-muted);
      padding: 4px 10px;
      border-radius: 14px;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
      cursor: pointer;
    }
    .chip.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .container {
      padding: 12px;
      max-width: 800px;
      margin: 0 auto;
    }
    .card-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .media-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 10px;
      display: flex;
      gap: 10px;
      cursor: pointer;
      transition: border-color 0.15s;
    }
    .media-card:hover { border-color: #374151; }
    .poster-box {
      width: 65px;
      height: 95px;
      border-radius: 6px;
      background: #1e293b;
      overflow: hidden;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .poster-img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
    .card-content {
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-width: 0;
    }
    .card-title {
      font-size: 14px;
      font-weight: 700;
      color: #fff;
      line-height: 1.3;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .meta-row {
      display: flex;
      gap: 4px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 4px;
    }
    .pill {
      font-size: 9px;
      font-weight: 700;
      padding: 2px 5px;
      border-radius: 4px;
      text-transform: uppercase;
    }
    .pill-type { background: #312e81; color: #c7d2fe; }
    .pill-year { background: #1f2937; color: var(--text-muted); }
    .pill-imdb { background: #78350f; color: #fde047; border: 1px solid #d97706; }
    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 6px;
      font-size: 11px;
      color: var(--text-dim);
    }
    .btn-detail {
      background: var(--accent);
      color: #fff;
      border: none;
      padding: 4px 10px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
    }

    /* Modal Sheet */
    .modal-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 1000;
      display: flex; align-items: flex-end; justify-content: center;
    }
    .modal-sheet {
      background: #111827; border-top: 1px solid var(--card-border);
      border-radius: 16px 16px 0 0; width: 100%; max-width: 600px;
      max-height: 85vh; display: flex; flex-direction: column; overflow: hidden;
      animation: slideUp 0.2s ease-out;
    }
    @keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }
    .sheet-header {
      padding: 14px; border-bottom: 1px solid var(--card-border);
      display: flex; justify-content: space-between; align-items: center;
    }
    .sheet-body {
      padding: 14px; overflow-y: auto; flex: 1;
    }
    .sheet-title { font-size: 15px; font-weight: 800; color: #fff; }
    .close-btn {
      background: none; border: none; color: var(--text-muted);
      font-size: 20px; cursor: pointer; padding: 4px; line-height: 1;
    }
    .video-wrap {
      background: #000; border-radius: 8px; overflow: hidden; margin-bottom: 12px;
    }
    video { width: 100%; max-height: 240px; display: block; background: #000; }
    .player-actions {
      display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 12px;
    }
    .action-btn {
      padding: 8px 10px; border-radius: 6px; border: none; font-size: 11px;
      font-weight: 700; cursor: pointer; display: flex; align-items: center;
      justify-content: center; gap: 4px; text-decoration: none; text-align: center;
    }
    .btn-vlc { background: #ea580c; color: white; }
    .btn-mpv { background: #7c3aed; color: white; }
    .btn-mx { background: #0284c7; color: white; }
    .btn-copy { background: #374151; color: white; }
    .release-group {
      background: #090d16; border: 1px solid var(--card-border);
      border-radius: 8px; padding: 10px; margin-bottom: 8px;
    }
    .release-hdr {
      font-size: 12px; font-weight: 700; color: #fff; margin-bottom: 6px;
      display: flex; justify-content: space-between; align-items: center;
    }
    .stream-row {
      display: flex; justify-content: space-between; align-items: center;
      background: #111827; padding: 6px 8px; border-radius: 6px;
      margin-top: 5px; border: 1px solid #1f2937;
    }
    .stream-name { font-size: 11px; font-weight: 600; color: #e5e7eb; }
    .btn-play-stream {
      background: #2563eb; color: #fff; border: none; padding: 4px 10px;
      border-radius: 4px; font-size: 11px; font-weight: 700; cursor: pointer;
    }
    .toast {
      position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
      background: #10b981; color: #fff; padding: 6px 14px; border-radius: 6px;
      font-size: 11px; font-weight: 700; display: none; z-index: 9999;
    }
  </style>
</head>
<body>
  <header>
    <div class="top-bar">
      <div class="brand">
        <span>⚡ RADD STREAM</span>
        <span class="brand-badge">CLIENT v1</span>
      </div>
      <div class="header-links">
        __RULES_BUTTON__
        <a href="/" class="icon-btn">🖥️ DB Explorer</a>
      </div>
    </div>
    <div class="search-row">
      <span class="search-icon">🔍</span>
      <input type="text" id="mobile-search" class="search-input" placeholder="Search movies, anime, series..." oninput="handleSearch()">
    </div>
    <div class="filter-chips">
      <button class="chip active" onclick="setChipFilter('', this)">All</button>
      <button class="chip" onclick="setChipFilter('movie', this)">🍿 Movies</button>
      <button class="chip" onclick="setChipFilter('series', this)">📺 Series</button>
      <button class="chip" onclick="setChipFilter('anime', this)">🎨 Anime</button>
    </div>
  </header>

  <div class="container">
    <div id="media-list" class="card-list">
      <div style="text-align:center; padding:40px 10px; color:var(--text-dim); font-size:13px;">
        Loading catalog...
      </div>
    </div>
  </div>

  <!-- Detail & Player Modal Sheet -->
  <div id="sheet-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closeSheetModal()">
    <div class="modal-sheet">
      <div class="sheet-header">
        <div class="sheet-title" id="sheet-title">Media Detail</div>
        <button class="close-btn" onclick="closeSheetModal()">✕</button>
      </div>
      <div class="sheet-body">
        <div id="player-container" style="display:none;">
          <div class="video-wrap">
            <video id="sheet-video" controls playsinline></video>
          </div>
          <div class="player-actions">
            <a id="btn-vlc-action" href="#" class="action-btn btn-vlc">🎬 VLC</a>
            <a id="btn-mpv-action" href="#" class="action-btn btn-mpv">⚡ MPV</a>
            <a id="btn-mx-action" href="#" class="action-btn btn-mx">📱 MX Player</a>
            <button class="action-btn btn-copy" onclick="copySheetStream()">📋 Copy Link</button>
          </div>
        </div>
        <div id="sheet-releases">
          <div style="text-align:center; padding:20px; color:var(--text-dim);">Loading releases...</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Rules & System Modal -->
  <div id="rules-modal" class="modal-overlay" style="display:none;" onclick="if(event.target===this)closeRulesModal()">
    <div class="modal-sheet">
      <div class="sheet-header">
        <div class="sheet-title">⚙️ Client Extraction Rules</div>
        <button class="close-btn" onclick="closeRulesModal()">✕</button>
      </div>
      <div class="sheet-body" id="rules-content" style="font-size:12px; line-height:1.6;">
        Loading rules...
      </div>
    </div>
  </div>

  <div id="mobile-toast" class="toast">Link copied!</div>

  <script>
    let currentType = '';
    let searchTimer = null;
    let activeStreamUrl = '';

    async function loadPosts(query = '', type = '') {
      const container = document.getElementById('media-list');
      try {
        const url = `/api/v1/posts?limit=30&q=${encodeURIComponent(query)}&type=${encodeURIComponent(type)}`;
        const res = await fetch(url);
        const data = await res.json();
        const results = data.results || [];
        if (results.length === 0) {
          container.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-dim); font-size:13px;">No media found.</div>';
          return;
        }
        let html = '';
        for (const p of results) {
          const typeBadge = p.content_type ? `<span class="pill pill-type">${p.content_type}</span>` : '';
          const yearBadge = p.year ? `<span class="pill pill-year">${p.year}</span>` : '';
          const imdbBadge = p.imdb_rating ? `<span class="pill pill-imdb">⭐ ${p.imdb_rating}</span>` : '';
          const poster = p.poster_url
            ? `<img src="${p.poster_url}" class="poster-img" alt="${p.clean_title}" loading="lazy" onerror="this.src='';this.alt='🎬'">`
            : '<span class="poster-placeholder">🎬</span>';

          html += `
            <div class="media-card" onclick="openDetail(${p.id})">
              <div class="poster-box">${poster}</div>
              <div class="card-content">
                <div class="card-header">
                  <div class="card-title">${p.clean_title}</div>
                  <div class="meta-row">
                    ${typeBadge}
                    ${yearBadge}
                    ${imdbBadge}
                  </div>
                </div>
                <div class="card-footer">
                  <span>${p.release_count || 0} releases · ${p.source_count || 0} sources</span>
                  <button class="btn-detail">View & Play ↗</button>
                </div>
              </div>
            </div>
          `;
        }
        container.innerHTML = html;
      } catch (e) {
        container.innerHTML = '<div style="text-align:center; padding:40px; color:var(--rose); font-size:13px;">Failed to load posts.</div>';
      }
    }

    function handleSearch() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        const q = document.getElementById('mobile-search').value.trim();
        loadPosts(q, currentType);
      }, 250);
    }

    function setChipFilter(type, el) {
      currentType = type;
      document.querySelectorAll('.filter-chips .chip').forEach(c => c.classList.remove('active'));
      el.classList.add('active');
      const q = document.getElementById('mobile-search').value.trim();
      loadPosts(q, currentType);
    }

    async function openDetail(postId) {
      const modal = document.getElementById('sheet-modal');
      const titleEl = document.getElementById('sheet-title');
      const container = document.getElementById('sheet-releases');
      document.getElementById('player-container').style.display = 'none';
      const video = document.getElementById('sheet-video');
      video.pause();
      video.src = '';

      modal.style.display = 'flex';
      container.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-dim);">Loading releases & sources...</div>';

      try {
        const res = await fetch(`/api/v1/posts/${postId}`);
        const json = await res.json();
        if (!json.success || !json.data) {
          container.innerHTML = '<div style="color:var(--rose);">Could not load media details.</div>';
          return;
        }
        const p = json.data;
        titleEl.innerText = p.clean_title + (p.year ? ` (${p.year})` : '');

        let html = '';
        for (const r of (p.releases || [])) {
          html += `
            <div class="release-group">
              <div class="release-hdr">
                <span>${escapeHtml(r.label || r.release_title)}</span>
                <span class="pill pill-year">${(r.quality || 'HD').toUpperCase()}</span>
              </div>
              <div style="font-size:11px; color:var(--text-dim); margin-bottom:6px;">
                ${r.size ? '📦 ' + r.size + ' · ' : ''}${r.languages ? '🌐 ' + r.languages : ''}
              </div>
          `;
          for (const s of (r.sources || [])) {
            const isTemp = s.is_temporary ? '⏳' : '';
            // `s.source_name` only ever exists on the operator port's response;
            // the public projection replaces it with our own neutral label.
            const name = escapeHtml(s.label || s.source_name || 'Streaming server');
            const handle = s.stream_id || s.id;
            html += `
              <div class="stream-row">
                <div class="stream-name">⚡ ${name} ${isTemp}</div>
                <button class="btn-play-stream" onclick="playSource('${handle}', '${name}', '${escapeHtml(p.clean_title)}')">▶ Play</button>
              </div>
            `;
          }
          html += '</div>';
        }
        container.innerHTML = html || '<div style="text-align:center; padding:20px; color:var(--text-dim);">No releases found.</div>';
      } catch (err) {
        container.innerHTML = '<div style="color:var(--rose);">Error loading details.</div>';
      }
    }

    function playSource(sourceId, sourceName, postTitle) {
      const streamUrl = `${window.location.origin}/api/v1/stream?id=${sourceId}&redirect=1`;
      activeStreamUrl = streamUrl;
      const playerBox = document.getElementById('player-container');
      playerBox.style.display = 'block';

      const video = document.getElementById('sheet-video');
      video.src = streamUrl;
      video.load();
      video.play().catch(() => {});

      // Configure native android intents
      document.getElementById('btn-vlc-action').href = `intent:${streamUrl}#Intent;package=org.videolan.vlc;type=video/*;end`;
      document.getElementById('btn-mpv-action').href = `intent:${streamUrl}#Intent;package=is.xyz.mpv;type=video/*;end`;
      document.getElementById('btn-mx-action').href = `intent:${streamUrl}#Intent;package=com.mxtech.videoplayer.ad;type=video/*;end`;

      playerBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function closeSheetModal() {
      const video = document.getElementById('sheet-video');
      video.pause();
      video.src = '';
      document.getElementById('sheet-modal').style.display = 'none';
    }

    async function openRulesModal() {
      const modal = document.getElementById('rules-modal');
      const content = document.getElementById('rules-content');
      modal.style.display = 'flex';
      content.innerHTML = 'Loading rules...';

      try {
        const [rRes, sRes] = await Promise.all([fetch('/api/v1/rules'), fetch('/api/v1/stats')]);
        const rules = await rRes.json();
        const stats = await sRes.json();

        let rulesHtml = `
          <div style="background:#090d16; padding:10px; border-radius:8px; margin-bottom:12px; border:1px solid var(--card-border);">
            <div style="font-weight:700; color:#fff; margin-bottom:4px;">📊 Catalog Statistics</div>
            <div>Posts: <b>${stats.posts}</b> · Releases: <b>${stats.releases}</b> · Sources: <b>${stats.sources}</b></div>
            <div>Active Streams: <b>${stats.active_sources}</b> · Resumable: <b>${stats.resumable_sources}</b></div>
          </div>
          <div style="font-weight:700; color:#fff; margin-bottom:6px;">🛠️ Client-Side Unwrapping Rules</div>
          <p style="color:var(--text-dim); margin-bottom:10px;">
            Native Android clients can resolve bridge URLs using user device IP directly using these registered regex patterns:
          </p>
        `;

        for (const [svc, conf] of Object.entries(rules.services || {})) {
          rulesHtml += `
            <div style="background:#090d16; border:1px solid var(--card-border); border-radius:6px; padding:8px; margin-bottom:6px;">
              <span style="font-weight:700; color:var(--accent);">${svc.toUpperCase()}</span> (Tier ${conf.tier || 1})
              <div style="font-family:monospace; color:#a7f3d0; word-break:break-all; font-size:11px; margin-top:2px;">
                ${conf.pattern || conf.regex || conf.type || 'direct'}
              </div>
            </div>
          `;
        }

        content.innerHTML = rulesHtml;
      } catch (e) {
        content.innerHTML = '<div style="color:var(--rose);">Error loading rules.</div>';
      }
    }

    function closeRulesModal() {
      document.getElementById('rules-modal').style.display = 'none';
    }

    function copySheetStream() {
      if (activeStreamUrl) {
        navigator.clipboard.writeText(activeStreamUrl).then(() => {
          showToast('Stream link copied!');
        });
      }
    }

    function showToast(msg) {
      const t = document.getElementById('mobile-toast');
      t.innerText = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 2000);
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Initial load
    loadPosts();
  </script>
</body>
</html>
"""


#: Operator-only affordance in the PWA header. A list of the bridge-unwrapping
#: rules *is* a list of hosters, so on the public port the control is not merely
#: disabled — it never appears in the served HTML at all.
RULES_BUTTON_HTML = '<button class="icon-btn" onclick="openRulesModal()">⚙️ Rules</button>'


def render_mobile_client(operator: bool) -> str:
    return MOBILE_CLIENT_HTML.replace(
        "__RULES_BUTTON__", RULES_BUTTON_HTML if operator else "")


PUBLIC_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__PROJECT_NAME__ — catalog</title>
  <style>
    body { margin:0; padding:40px 20px; background:#0b0e14; color:#e6edf3;
           font:15px/1.6 system-ui, sans-serif; }
    .wrap { max-width:640px; margin:0 auto; }
    h1 { font-size:22px; margin:0 0 4px; }
    .sub { color:#8b98a5; margin-bottom:24px; }
    code { background:#141a24; padding:2px 6px; border-radius:4px; font-size:13px; }
    a { color:#79c0ff; }
    ul { padding-left:18px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>__PROJECT_NAME__</h1>
    <div class="sub">Catalog API. The Android client is the product; this is the
      interface it reads.</div>
    <ul>
      <li><a href="/client">__PROJECT_NAME__ Web client</a></li>
      <li><code>GET /api/v1/posts?q=&amp;type=&amp;page=&amp;limit=</code></li>
      <li><code>GET /api/v1/posts/{id}</code></li>
      <li><code>GET /api/v1/stream?id=&amp;redirect=1</code></li>
      <li><code>GET /api/v1/stats</code></li>
    </ul>
    <p class="sub">Responses carry this service's own identifiers. Server selection
      happens here, not in the client.</p>
  </div>
</body>
</html>
"""


def render_public_landing() -> str:
    import config
    return PUBLIC_LANDING_HTML.replace("__PROJECT_NAME__", config.PROJECT_NAME)


def api_v1_get_posts(query: str = "", content_type: str = "", page: int = 1,
                     limit: int = 20, full: bool = False,
                     base_url: str = "") -> dict:
    _ensure_schema()
    offset = max(0, (page - 1) * limit)
    with get_db() as conn:
        # Adult-flagged posts are stored in the DB but never exposed via the API
        where_clauses = [redact.adult_clause("p")]
        params = []
        if query:
            where_clauses.append("(p.clean_title LIKE ? OR p.title LIKE ? OR p.slug LIKE ?)")
            q_param = f"%{query}%"
            params.extend([q_param, q_param, q_param])
        if content_type:
            where_clauses.append("p.content_type = ?")
            params.append(content_type)

        where_sql = " AND ".join(where_clauses)
        total = conn.execute(f"SELECT COUNT(*) FROM posts p WHERE {where_sql}", params).fetchone()[0]

        # `p.source_site`, `p.url` and `p.slug` used to be selected here: the site
        # it came from and the page we took it off. Both are our bookkeeping, so
        # only the loopback port asks for them (`full`).
        provenance_cols = ", p.source_site, p.url, p.slug" if full else ""
        sql = f"""
            SELECT p.id, p.clean_title, p.title, p.year, p.content_type, p.seasons,
                   p.poster_url, p.backdrop_urls, p.imdb_rating, p.imdb_id, p.tmdb_id,
                   p.genres,
                   p.industry, p.country, p.language{provenance_cols},
                   COUNT(DISTINCT r.id) as release_count,
                   COUNT(DISTINCT s.id) as source_count
            FROM posts p
            LEFT JOIN releases r ON r.post_id = p.id
            LEFT JOIN download_sources s ON s.release_id = r.id
            WHERE {where_sql}
            GROUP BY p.id
            ORDER BY p.id DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(sql, params + [limit, offset]).fetchall()
        results = []
        for r in rows:
            if full:
                results.append(dict(r))
                continue
            item = redact.project(r, "post_brief")
            item.update(_art_pair(r, base_url))
            results.append(item)
        total_pages = max(1, (total + limit - 1) // limit)
        return {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "results": results,
        }


def api_v1_get_post_detail(post_id: int, full: bool = False,
                           base_url: str = "") -> dict | None:
    _ensure_schema()
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post or post["is_18_plus"]:
            return None
        if full:
            p_dict = dict(post)
            p_dict["source_pages"] = [dict(r) for r in conn.execute(
                "SELECT source_site, url, source_title FROM post_sources WHERE post_id = ?",
                (post_id,)
            ).fetchall()]
        else:
            p_dict = redact.project(post, "post_detail")
            p_dict.update(_art_pair(post, base_url))

        releases = conn.execute("SELECT * FROM releases WHERE post_id = ? ORDER BY id ASC", (post_id,)).fetchall()
        rel_list = []
        for rel in releases:
            sources = conn.execute("""
                SELECT * FROM download_sources 
                WHERE release_id = ? 
                ORDER BY 
                    status = 'active' DESC,
                    is_temporary ASC,
                    CASE service
                        WHEN 'pixeldrain' THEN 1
                        WHEN 'vegadrive' THEN 2
                        WHEN 'hubcloud_10g' THEN 3
                        WHEN 'fsl_r2' THEN 4
                        WHEN 'fastdl' THEN 5
                        WHEN 'google_cdn' THEN 6
                        ELSE 99
                    END ASC
            """, (rel["id"],)).fetchall()
            # The ordering above is our own preference between servers; it is a
            # query, not a field. Nothing that names a hoster leaves this box.
            if full:
                r_dict = dict(rel)
                r_dict["sources"] = [dict(s) for s in sources]
            else:
                r_dict = redact.project(rel, "release")
                r_dict["label"] = redact.public_label(rel)
                r_dict["sources"] = [link_view(s, base_url) for s in sources]
            rel_list.append(r_dict)
        p_dict["releases"] = rel_list
        return p_dict


def api_v1_rules() -> dict:
    """**Operator-only, loopback port.** Client-side bridge-unwrapping selectors.

    This map is the recipe for turning a hoster's share page into a file URL.
    While the public port served it, any app could copy the catalog *and* the
    unwrapping with two requests, so unwrapping moved server-side
    (`fast_fetch.resolve_live_source`, reached through `/api/v1/stream`): the
    client asks to play, the server works out what to play. Nothing here is
    deleted — an operator on this machine still needs the rules to diagnose a
    bridge that broke — but it is no longer a public document.
    """
    return {
        "version": "1.0",
        "name": "radd-stream-client-rules",
        "description": "Client-side extraction selectors for Android/Web direct unwrapping",
        "services": {
            "pixeldrain": {
                "pattern": r"https://pixeldrain\.com/u/([A-Za-z0-9_-]+)",
                "endpoint": "https://pixeldrain.com/api/file/{id}",
                "is_temporary": 0,
                "tier": 1
            },
            "vegadrive": {
                "pattern": r"https://(?:one\.)?vegadrive\.(?:me|app)/(?:s|d)/([A-Za-z0-9_-]+)",
                "endpoint": "https://one.vegadrive.me/d/{id}/skyd",
                "is_temporary": 0,
                "tier": 1
            },
            "vcloud": {
                "type": "double_base64_html",
                "regex": r"atob\(\s*atob\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\)",
                "tier": 2
            },
            "hubcloud": {
                "type": "drive_page_gamerxyt",
                "regex": r'href=["\'](https?://gamerxyt\.com/hubcloud\.php\?[^"\']+)["\']',
                "tier": 2
            },
            "direct_cloud": {
                "pattern": r"https://(?:dl\.)?direct-cloud\.(?:top|org)/d/([A-Za-z0-9_-]+)",
                "action_endpoint": "https://storage.direct-cloud.org/action",
                "action_type": "DOWNLOAD_GENERATE",
                "tier": 2,
                "is_temporary": 1
            },
            "greenmotors": {
                "pattern": r"https://greenmotors\.[a-z]+/\?id=([A-Za-z0-9+/=_\-]+)",
                "type": "multi_layer_b64_rot13",
                "tier": 2,
                "is_temporary": 0
            }
        }
    }


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_bytes(self, data: bytes, content_type: str = "text/html; charset=utf-8", status: int = 200, extra_headers: list[tuple[str, str]] | None = None):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            headers = list(extra_headers or [])
            headers.extend(getattr(self, "rate_headers", []))
            if headers:
                for k, v in headers:
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def send_json(self, data: any, status: int = 200,
                  extra_headers: list[tuple[str, str]] | None = None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = [("Access-Control-Allow-Origin", "*")]
        if extra_headers:
            headers.extend(extra_headers)
        self.send_bytes(body, content_type="application/json; charset=utf-8",
                        status=status, extra_headers=headers)

    def _bucket_for(self, path: str) -> str:
        if path in ("/api/v1/stream", "/api/v1/art", "/api/m3u"):
            return "play"
        if path == "/api/v1/stats":
            return "reports"
        return "browse"

    def _serve_art(self, query_params: dict, full: bool = False) -> None:
        """302 to a work's own artwork, addressed by our handle.

        Posters are the one piece of upstream content a user sees directly, and
        a scraped site's own image URL prints that site's domain in the UI's
        image inspector — so art is addressed the same way video is: our host,
        our handle, a redirect, zero bytes through this box."""
        post_id = redact.parse_token(query_params.get("id", [""])[0], signing_secret(),
                                     signed_only=not full)
        kind = (query_params.get("k", ["poster"])[0] or "poster").lower()
        table = (query_params.get("t", ["posts"])[0] or "posts").lower()
        if table not in redact.ART_TABLES:
            table = "posts"
        try:
            index = max(0, int(query_params.get("n", ["0"])[0]))
        except ValueError:
            index = 0
        if not post_id or kind not in ("poster", "backdrop"):
            self.send_json({"error": "Invalid art reference"}, status=400)
            return
        if redact.art_is_adult(int(post_id), DB_PATH, table=table):
            self.send_json({"success": False, "error": "not_found"}, status=404)
            return
        target = redact.art_url_for(int(post_id), kind, index, DB_PATH, table=table)
        if not target:
            self.send_bytes(b"Not Found", content_type="text/plain", status=404)
            return
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)
        # Whether this server may speak provenance at all. Set on the *instance*
        # (see start_server), so it cannot be negotiated by a request header or a
        # query parameter — the whole point of a separate loopback port.
        full = bool(getattr(self.server, "operator", False))
        base_url = "" if full else _public_base(self)
        if not full:
            if path in OPERATOR_ONLY_ROUTES:
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            verdict = redact.limiter.check(self._bucket_for(path),
                                           redact.client_ip(self))
            self.rate_headers = redact.limiter.headers(verdict)
            if not verdict["allowed"]:
                self.send_json({"success": False, "error": "rate_limited"}, status=429,
                               extra_headers=[("Retry-After", str(verdict["retry_after"]))])
                return

        if path == "/api/data":
            search_q = query_params.get("q", [""])[0]
            data = fetch_database_payload(search_q, full=full, base_url=base_url)
            self.send_json(data)

        elif path == "/api/sitemap":
            if not full:
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            search_q = query_params.get("q", [""])[0]
            site = query_params.get("site", [""])[0]
            limit = int(query_params.get("limit", [50])[0])
            rows = search_sitemap_api(search_q, site=site, limit=limit)
            self.send_json(rows)

        elif path == "/api/fetch":
            if not full:
                # Scraping an arbitrary caller-supplied URL is an operator tool,
                # and an open one on the public port is an SSRF.
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return
            target_url = query_params.get("url", [""])[0]
            if not target_url:
                self.send_json({"error": "Missing url"}, status=400)
                return

            try:
                import fast_fetch
                data = fast_fetch.extract_post_data(target_url, verbose=False)
                if data:
                    post_id = fast_fetch.save_scraped_data(data)
                    resp_payload = {"success": True, "post_id": post_id, "clean_title": data["clean_title"]}
                else:
                    resp_payload = {"success": False, "error": "Failed to parse post"}
            except Exception as ex:
                resp_payload = {"success": False, "error": str(ex)}

            self.send_json(resp_payload)

        elif path == "/api/m3u":
            post_id = int(query_params.get("id", [0])[0])
            playlist_content = generate_m3u_playlist(post_id, full=full, base_url=base_url)
            body = playlist_content.encode("utf-8")
            self.send_bytes(
                body,
                content_type="audio/x-mpegurl; charset=utf-8",
                extra_headers=[("Content-Disposition", f'attachment; filename="playlist_{post_id}.m3u"')]
            )

        elif path == "/api/health-check":
            query_params = urllib.parse.parse_qs(parsed.query)
            post_id = int(query_params.get("id", [0])[0]) if query_params.get("id") else None
            try:
                import fast_fetch
                results = fast_fetch.run_health_check(post_id=post_id, verbose=False)
                resp_payload = {"success": True, "count": len(results)}
            except Exception as ex:
                resp_payload = {"success": False, "error": str(ex)}

            self.send_json(resp_payload)

        elif path == "/api/heal":
            query_params = urllib.parse.parse_qs(parsed.query)
            post_id = int(query_params.get("id", [0])[0])
            try:
                import fast_fetch
                res = fast_fetch.heal_post_links(post_id, verbose=False)
                resp_payload = {"success": True, **res}
            except Exception as ex:
                resp_payload = {"success": False, "error": str(ex)}

        elif path == "/api/v1/posts":
            q = query_params.get("q", [""])[0]
            ctype = query_params.get("type", [""])[0]
            page = int(query_params.get("page", [1])[0])
            limit = min(100, max(1, int(query_params.get("limit", [20])[0])))
            data = api_v1_get_posts(query=q, content_type=ctype, page=page, limit=limit,
                                    full=full, base_url=base_url)
            self.send_json(data)

        elif path.startswith("/api/v1/posts/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3].isdigit():
                detail = api_v1_get_post_detail(int(parts[3]), full=full,
                                                base_url=base_url)
                if detail:
                    self.send_json({"success": True, "data": detail})
                else:
                    # Identical to a row that never existed: an adult title must not
                    # be distinguishable from an absent one (API_V2.md §13).
                    self.send_json({"success": False, "error": "Post not found"}, status=404)
            else:
                self.send_json({"error": "Invalid post ID"}, status=400)

        elif path == "/api/v1/stream":
            source_ref = query_params.get("id", [""])[0]
            source_id = redact.parse_token(source_ref, signing_secret(),
                                           signed_only=not full)
            if not source_id:
                self.send_json({"error": "Missing or invalid source id parameter 'id'"}, status=400)
                return

            if not full and redact.link_is_adult(int(source_id), DB_PATH):
                # Same answer as a link that does not exist: hidden, not deleted,
                # and never played by an address we did not hand out.
                self.send_json({"success": False, "error": "not_found"}, status=404)
                return

            import fast_fetch
            res = fast_fetch.resolve_live_source(int(source_id))
            redirect_flag = query_params.get("redirect", ["1"])[0]

            if res.get("success") and res.get("url"):
                if redirect_flag in ("1", "true", "yes"):
                    # The player follows this and gets bytes; the VM moves none of
                    # them. What the user sees is our own URL.
                    self.send_response(302)
                    self.send_header("Location", res["url"])
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                else:
                    if not full:
                        # Used to hand back url + service + source_name, i.e. the
                        # upstream file URL and who hosts it. A caller who wants
                        # bytes follows the 302; nobody needs the hoster's name to
                        # play a video.
                        self.send_json({
                            "success": True,
                            "stream_id": redact.mint_token(int(source_id), signing_secret()),
                            "kind": res.get("playback_type") or "url",
                            "mime_type": res.get("mime_type"),
                            "file_size_bytes": res.get("file_size_bytes"),
                            "resumable": bool(res.get("is_resumable")),
                            "expires_in": 6 * 3600 if res.get("is_temporary") else None,
                        })
                    else:
                        self.send_json(res)
            else:
                self.send_json(res if full else {
                    "success": False, "error": "no_playable_source"}, status=404)

        elif path == "/api/v1/art":
            self._serve_art(query_params, full=full)

        elif path == "/api/v1/rules":
            self.send_json(api_v1_rules())

        elif path == "/api/v1/stats":
            _ensure_schema()
            with get_db() as conn:
                posts_c = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
                rels_c = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
                srcs_c = conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0]
                active_c = conn.execute("SELECT COUNT(*) FROM download_sources WHERE status = 'active'").fetchone()[0]
                resumable_c = conn.execute("SELECT COUNT(*) FROM download_sources WHERE is_resumable = 1").fetchone()[0]
                temp_c = conn.execute("SELECT COUNT(*) FROM download_sources WHERE is_temporary = 1").fetchone()[0]
            self.send_json(redact.project({
                "posts": posts_c,
                "releases": rels_c,
                "sources": srcs_c,
                "active_sources": active_c,
                "resumable_sources": resumable_c,
                "temporary_sources": temp_c,
            }, "stats"))

        elif path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        elif path == "/client" or path == "/mobile":
            self.send_bytes(render_mobile_client(full).encode("utf-8"),
                            content_type="text/html; charset=utf-8")

        elif path == "/" or path == "/index.html":
            # The DB explorer names sites and upstream pages by design — that is
            # what it is for — so it lives on the loopback port only. The public
            # port gets a page that says what the service is.
            page = (DASHBOARD_HTML if full else render_public_landing())
            self.send_bytes(page.encode("utf-8"), content_type="text/html; charset=utf-8")

        else:
            self.send_bytes(b"Not Found", content_type="text/plain", status=404)

    def log_message(self, format, *args):
        pass


def export_standalone_html(output_file: str = "database_view.html") -> str:
    """A self-contained dashboard snapshot for the operator's own machine.

    Always `full`: the badges and copy-the-upstream-URL buttons are the reason to
    open this file, and it never leaves the box — the server has no static route
    that could hand it to a client, and it is gitignored."""
    payload = fetch_database_payload(full=True, base_url=PUBLIC_BASE_URL)
    json_str = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")

    standalone = DASHBOARD_HTML.replace(
        "fetchData();",
        f"dbData = {json_str}; renderStats(); renderPosts();"
    ).replace(
        "async function fetchData(query = '') {",
        "async function fetchData(query = '') { return; "
    )

    out_path = BASE_DIR / output_file
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(standalone)
    return str(out_path)


def make_server(host: str, port: int, operator: bool):
    """One handler class, two policies. The policy lives on the *server object*,
    because anything a request carries (header, query, path prefix) is something
    a request can forge — a port it cannot."""
    server = ThreadedHTTPServer((host, port), DashboardHandler)
    server.operator = operator
    return server


def start_server(port: int = 8080, host: str = "0.0.0.0",
                 operator_port: int | None = None):
    import threading
    _ensure_schema()
    server = make_server(host, port, operator=False)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"

    internal = None
    internal_host = os.environ.get("RADD_INTERNAL_HOST", "127.0.0.1")
    try:
        internal = make_server(internal_host, operator_port or OPERATOR_PORT,
                               operator=True)
    except OSError as ex:
        print(f"[i] operator dashboard unavailable: {ex}")

    print("\n" + "=" * 65)
    print("🚀 Fast_Fetch Database Viewer & Site Explorer Running!")
    print(f"👉 Public API + web client: {url}")
    if internal:
        print(f"🔧 Operator dashboard (full provenance, loopback only): "
              f"http://{internal_host}:{internal.server_address[1]}")
    print(f"📁 Database: {DB_PATH}")
    print(f"⚡ Press Ctrl+C to stop the server")
    print("=" * 65 + "\n", flush=True)

    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    if internal:
        threading.Thread(target=internal.serve_forever, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] Server stopped.")
    finally:
        server.server_close()
        if internal:
            internal.shutdown()
            internal.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
    start_server(port)
