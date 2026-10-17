# -*- coding: utf-8 -*-
"""
test_all_sites.py — Real-world live verification of all 10 supported streaming sites.
Runs fast, unbuffered tests verifying:
  1. Base domain HTTP status & redirect target
  2. Catalog Ingestion (sitemap / REST API / SvelteKit / HTML cards)
  3. Live Post HTML & Extract Metadata Verification
"""
import sys
import os
import json
import time
import tempfile
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fast_fetch

# Exercise the real save path without touching a developer's persistent catalog.
LIVE_DB_DIR = tempfile.TemporaryDirectory(prefix="radd-stream-live-db-")
fast_fetch.DB_PATH = Path(LIVE_DB_DIR.name) / "live-audit.db"
fast_fetch.fetch_cinemeta_metadata = lambda *args, **kwargs: None
fast_fetch.init_db()

def p(msg):
    print(msg, flush=True)

p("=" * 75)
p("🔍 10-SITE LIVE REAL-WORLD VERIFICATION AUDIT")
p("=" * 75)

SITE_TEST_CONFIGS = [
    {
        "name": "vegamovies",
        "domain": fast_fetch.DOMAINS.get("vegamovies", "https://vegamovies.gallery"),
        "catalog_type": "sitemap",
        "catalog_url": "https://vegamovies.gallery/sitemap.xml",
        "post_url": "https://vegamovies.gallery/download-the-corrupted-2019-dual-audio-hin-eng/"
    },
    {
        "name": "rogmovies",
        "domain": fast_fetch.DOMAINS.get("rogmovies", "https://rogmovies.one"),
        "catalog_type": "sitemap",
        "catalog_url": "https://rogmovies.one/sitemap.xml",
        "post_url": "https://rogmovies.one/download-bypass-road-2019-hindi-480p-720p/"
    },
    {
        "name": "ssrmovies",
        "domain": fast_fetch.DOMAINS.get("ssrmovies", "https://ssrmovies.gripe"),
        "catalog_type": "wp_api",
        "catalog_url": "https://ssrmovies.gripe/wp-json/wp/v2/posts?per_page=3",
        "post_url": "https://ssrmovies.gripe/wwe-monday-night-raw-2026/"
    },
    {
        "name": "katmoviehd",
        "domain": fast_fetch.DOMAINS.get("katmoviehd", "https://katmoviehd.fans"),
        "catalog_type": "sveltekit",
        "catalog_url": "https://new.katmoviehd.top/",
        "post_url": "https://new.katmoviehd.top/the-trap-s1-hindi"
    },
    {
        "name": "7starhd",
        "domain": fast_fetch.DOMAINS.get("7starhd", "https://7starhd.rich"),
        "catalog_type": "homepage_html",
        "catalog_url": "https://7starhd.rich/",
        "post_url": "https://7starhd.rich/a-love-other-than-yours-2026-hindi-org-s01e01-08-dual-audio-series-hdrip-1080p-720p-480p-esubs/"
    },
    {
        "name": "10xflix",
        "domain": fast_fetch.DOMAINS.get("10xflix", "https://10xflix.help"),
        "catalog_type": "wp_api",
        "catalog_url": "https://10xflix.help/wp-json/wp/v2/posts?per_page=3",
        "post_url": "https://10xflix.help/weapons-2025-hindi-studio-dub-dual-audio-bluray-1080p-720p-480p-esubs/"
    },
    {
        "name": "multimovies",
        "domain": fast_fetch.DOMAINS.get("multimovies", "https://multimovies.garden"),
        "catalog_type": "sitemap",
        "catalog_url": "https://multimovies.garden/sitemap.xml",
        "post_url": "https://multimovies.garden/movie/mirzapur-the-movie-174212"
    },
    {
        "name": "hdhub4u",
        "domain": fast_fetch.DOMAINS.get("hdhub4u", "https://new7.hdhub4u.cl"),
        "catalog_type": "sitemap",
        "catalog_url": "https://new7.hdhub4u.cl/post-sitemap.xml",
        "post_url": "https://new7.hdhub4u.cl/the-fate-of-the-furious-2017-dual-audio-hindi-org-720p-bluray/"
    },
    {
        "name": "bollyshares",
        "domain": fast_fetch.DOMAINS.get("bollyshares", "https://bollyshares.xyz"),
        "catalog_type": "sitemap",
        "catalog_url": "https://bollyshares.xyz/post-sitemap.xml",
        "post_url": "https://bollyshares.xyz/free-bhairadevi-2024-south-hindi-dubbed-movie-hd-esub/"
    },
    {
        "name": "filmyzilla",
        "domain": fast_fetch.DOMAINS.get("filmyzilla", "https://www.filmyzilla74.com"),
        "catalog_type": "sitemap",
        "catalog_url": "https://www.filmyzilla74.com/sitemap.xml",
        "post_url": "https://www.filmyzilla74.com/movie/22361/Ab-tak-chhappan-(2004)-hindi-movie.html"
    }
]

audit_results = []

for cfg in SITE_TEST_CONFIGS:
    name = cfg["name"]
    p(f"\n▶ [{name.upper()}] Testing {cfg['domain']}...")
    res = {
        "site": name,
        "domain_code": 0,
        "final_domain": None,
        "catalog_count": 0,
        "post_title": None,
        "releases_count": 0,
        "sources_count": 0,
        "status": "UNKNOWN",
        "details": ""
    }

    # 1. Base Domain Ping
    try:
        c, f_url, html = fast_fetch.http_get(cfg["domain"], timeout=10, max_retries=1)
        res["domain_code"] = c
        res["final_domain"] = f_url
        if c == 200:
            p(f"   [Domain]  ✓ HTTP 200 (Live: {f_url})")
        else:
            p(f"   [Domain]  ✗ HTTP {c}")
            res["status"] = "FAIL_DOMAIN"
            res["details"] = f"Domain HTTP {c}"
            audit_results.append(res)
            continue
    except Exception as e:
        p(f"   [Domain]  ✗ Error: {e}")
        res["status"] = "FAIL_DOMAIN"
        res["details"] = f"Conn error: {str(e)[:40]}"
        audit_results.append(res)
        continue

    # 2. Catalog Ingestion Ping
    discovered_post = cfg["post_url"]
    try:
        cat_type = cfg["catalog_type"]
        if cat_type == "wp_api":
            c_api, _, api_body = fast_fetch.http_get(cfg["catalog_url"], timeout=10, max_retries=1)
            if c_api == 200:
                posts = json.loads(api_body)
                res["catalog_count"] = len(posts)
                p(f"   [Catalog] ✓ WP REST API returned {len(posts)} posts")
            else:
                p(f"   [Catalog] ✗ WP API HTTP {c_api}")
        elif cat_type == "sitemap":
            c_sm, _, sm_body = fast_fetch.http_get(cfg["catalog_url"], timeout=10, max_retries=1)
            if c_sm == 200:
                count = sm_body.count("<loc>")
                res["catalog_count"] = count
                p(f"   [Catalog] ✓ Sitemap returned {count} entries")
            else:
                p(f"   [Catalog] ✗ Sitemap HTTP {c_sm}")
        elif cat_type == "sveltekit":
            slugs = fast_fetch.re.findall(r'slug:"([^"]+)"', html)
            res["catalog_count"] = len(slugs)
            p(f"   [Catalog] ✓ SvelteKit catalog contains {len(slugs)} items")
        elif cat_type == "homepage_html":
            links = set(fast_fetch.re.findall(r'href=["\'](https?://7starhd\.rich/[a-zA-Z0-9\-_]+/)["\']', html))
            res["catalog_count"] = len(links)
            p(f"   [Catalog] ✓ Homepage contains {len(links)} candidate links")
    except Exception as ex:
        p(f"   [Catalog] ✗ Ingestion error: {ex}")

    # 3. Post Extraction (fast metadata parse)
    if discovered_post:
        p(f"   [Post]    Testing: {discovered_post}")
        try:
            c_p, final_p_url, p_html = fast_fetch.http_get(discovered_post, timeout=12, max_retries=1)
            if c_p == 200:
                post_data = None
                if name == "ssrmovies":
                    post_data = fast_fetch.extract_post_data_ssrmovies(final_p_url, p_html, verbose=False)
                elif name == "katmoviehd":
                    post_data = fast_fetch.extract_post_data_katmoviehd(final_p_url, p_html, verbose=False)
                elif name == "7starhd":
                    post_data = fast_fetch.extract_post_data_7starhd(final_p_url, p_html, verbose=False)
                elif name == "10xflix":
                    post_data = fast_fetch.extract_post_data_10xflix(final_p_url, p_html, verbose=False)
                elif name == "multimovies":
                    post_data = fast_fetch.extract_post_data_multimovies(final_p_url, p_html, verbose=False)
                elif name == "hdhub4u":
                    post_data = fast_fetch.extract_post_data_hdhub4u(final_p_url, p_html, verbose=False)
                elif name == "bollyshares":
                    post_data = fast_fetch.extract_post_data_bollyshares(final_p_url, p_html, verbose=False)
                elif name == "filmyzilla":
                    post_data = fast_fetch.extract_post_data_filmyzilla(final_p_url, p_html, verbose=False)
                else:
                    meta = fast_fetch.parse_post_metadata(final_p_url, p_html)
                    nex_links = set(fast_fetch.re.findall(r'href=[\"\'](https?://nexdrive\.[a-z]+/[^\"\']+)[\"\']', p_html))
                    post_data = {
                        "clean_title": meta["clean_title"],
                        "year": meta["year"],
                        "canonical_key": fast_fetch.generate_canonical_key(meta["clean_title"], meta["year"]),
                    "releases": [{
                        "quality": "720p",
                        "sources": [{
                            "source_name": "nexdrive",
                            "service": "nexdrive",
                            "resource_id": link.rstrip("/").split("/")[-1],
                            "source_url": link,
                        }],
                    } for link in nex_links]
                    }

                if post_data and post_data.get("clean_title"):
                    res["post_title"] = post_data["clean_title"]
                    rels = post_data.get("releases", [])
                    if not isinstance(rels, list):
                        raise ValueError("Extractor returned releases that are not a list")
                    for rel in rels:
                        if not isinstance(rel, dict):
                            raise ValueError("Extractor returned a non-dictionary release")
                        sources = rel.get("sources") or []
                        if not isinstance(sources, list) or any(not isinstance(src, dict) for src in sources):
                            raise ValueError("Extractor returned an invalid release source list")
                    res["releases_count"] = len(rels)
                    res["sources_count"] = sum(len(r.get("sources", [])) for r in rels)
                    p(f"   [Post]    ✓ Title: \"{post_data['clean_title']}\" ({post_data.get('year') or 'N/A'})")
                    p(f"   [Post]    ✓ Releases: {len(rels)} | Sources/Bridges: {res['sources_count']}")
                    save_payload = dict(post_data)
                    save_payload["url"] = final_p_url
                    save_payload["source_site"] = name
                    save_payload.setdefault("title", post_data["clean_title"])
                    save_payload.setdefault("canonical_key", fast_fetch.generate_canonical_key(
                        post_data["clean_title"], post_data.get("year")
                    ))
                    save_payload.setdefault("releases", [])
                    post_id = fast_fetch.save_scraped_data(save_payload)
                    with fast_fetch.get_db() as conn:
                        page = conn.execute(
                            "SELECT 1 FROM post_sources WHERE post_id = ? AND source_site = ? AND url = ?",
                            (post_id, name, final_p_url),
                        ).fetchone()
                        saved_releases = conn.execute(
                            "SELECT COUNT(*) FROM releases WHERE post_id = ? AND source_site = ?",
                            (post_id, name),
                        ).fetchone()[0]
                        saved_sources = conn.execute(
                            "SELECT COUNT(*) FROM download_sources s "
                            "JOIN releases r ON r.id = s.release_id "
                            "WHERE r.post_id = ? AND r.source_site = ?",
                            (post_id, name),
                        ).fetchone()[0]
                    expected_releases = sum(isinstance(rel, dict) for rel in rels)
                    expected_sources = sum(
                        sum(isinstance(src, dict) for src in (rel.get("sources") or []))
                        for rel in rels if isinstance(rel, dict)
                    )
                    if not page or saved_releases != expected_releases or saved_sources != expected_sources:
                        raise ValueError(
                            f"Database persistence mismatch: page={bool(page)}, "
                            f"releases={saved_releases}/{expected_releases}, "
                            f"sources={saved_sources}/{expected_sources}"
                        )
                    res["database_post_id"] = post_id
                    p(f"   [Database] ✓ Saved record {post_id}: 1 source page, {saved_releases} releases, {saved_sources} links")
                    res["status"] = "WORKING"
                else:
                    p(f"   [Post]    ✗ Extracted empty title")
                    res["status"] = "PARTIAL_EXTRACT"
            else:
                p(f"   [Post]    ✗ HTTP {c_p} on post URL")
                res["status"] = "POST_HTTP_ERR"
        except Exception as e_p:
            p(f"   [Post]    ✗ Exception: {e_p}")
            res["status"] = "EXTRACT_ERROR"
            res["details"] = str(e_p)[:50]
    else:
        p("   [Post]    ✗ No test post available")
        res["status"] = "NO_TEST_POST"

    audit_results.append(res)

# Print Summary Table
p("\n" + "=" * 75)
p("📊 COMPREHENSIVE LIVE AUDIT REPORT")
p("=" * 75)

with fast_fetch.get_db() as conn:
    p(
        "[Temporary DB] "
        f"{conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]} master records, "
        f"{conn.execute('SELECT COUNT(*) FROM post_sources').fetchone()[0]} site pages, "
        f"{conn.execute('SELECT COUNT(*) FROM releases').fetchone()[0]} releases, "
        f"{conn.execute('SELECT COUNT(*) FROM download_sources').fetchone()[0]} links"
    )
LIVE_DB_DIR.cleanup()

failed_sites = [
    result for result in audit_results
    if result["status"] != "WORKING"
    or result["catalog_count"] <= 0
    or result["sources_count"] <= 0
    or not result.get("database_post_id")
]
if failed_sites:
    p("[FAIL] Live audit failed for: " + ", ".join(result["site"] for result in failed_sites))
    sys.exit(1)
p("[PASS] All configured sites passed catalog, extraction, and temporary-database ingestion checks.")
p(f"{'Site':<13} | {'Domain':<8} | {'Catalog':<10} | {'Title Extracted':<24} | {'Verdict'}")
p("-" * 75)

for r in audit_results:
    site = r["site"]
    dom = f"✓ {r['domain_code']}" if r["domain_code"] == 200 else f"✗ {r['domain_code']}"
    cat = f"✓ {r['catalog_count']}" if r["catalog_count"] > 0 else "0"
    title = (r["post_title"][:22] + "..") if r["post_title"] and len(r["post_title"]) > 24 else (r["post_title"] or "None")

    if r["status"] == "WORKING" and r["sources_count"] > 0:
        verdict = f"🟢 FULLY OPERATIONAL ({r['sources_count']} links)"
    elif r["status"] == "WORKING":
        verdict = f"🟡 TITLE ONLY (0 links)"
    elif r["catalog_count"] > 0:
        verdict = f"🟡 CATALOG OK (Post Err)"
    else:
        verdict = f"🔴 FAILED ({r['details'] or r['status']})"

    p(f"{site:<13} | {dom:<8} | {cat:<10} | {title:<24} | {verdict}")

p("=" * 75)
