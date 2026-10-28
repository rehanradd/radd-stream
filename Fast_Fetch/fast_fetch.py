#!/usr/bin/env python3
"""
Fast_Fetch v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ultra-fast, lightweight scraper & direct link resolver for Vegamovies.
Uses sitemap indexing for <1ms searches, extracts clean metadata from
Nexdrive titles, unwraps bridge pages to final direct CDN URLs, and stores
everything in a normalized SQLite database.

CLI Commands:
  python fast_fetch.py sync               # Sync sitemap into local cache
  python fast_fetch.py search "avengers"  # Instant local title/slug search
  python fast_fetch.py fetch <URL|slug>   # Extract & resolve direct links into DB
  python fast_fetch.py view <ID|slug>     # Display saved releases & final URLs
  python fast_fetch.py crawl [LIMIT]      # Auto-crawl latest N posts
  python fast_fetch.py stats              # View database metrics
  python fast_fetch.py export [json|csv]  # Export database to JSON or CSV
"""

from __future__ import annotations
import sys
import os
import re
import json
import time
import base64
import codecs
import http.cookiejar
import sqlite3
import argparse
import threading
import urllib.request
import urllib.parse
import ssl
import html as html_module
from contextlib import contextmanager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure UTF-8 output on Windows consoles
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Permissive SSL context for CDN mirrors and edge gateways with custom certs
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

try:
    from config import DB_PATH, BASE_DIR, PROJECT_NAME
except ImportError:
    BASE_DIR = Path(__file__).parent.resolve()
    DB_PATH = Path(os.environ.get("RADD_DB_PATH", str(BASE_DIR / "fast_fetch.db")))
    PROJECT_NAME = "radd-stream"

## ── Dynamic Domain Mapping & Configuration ─────────────────────────────────────
DEFAULT_DOMAINS = {
    "vegamovies": "https://vegamovies.gallery",
    "vegamovies_sitemap": "https://vegamovies.gallery/sitemap.xml",
    "sitemap": "https://vegamovies.gallery/sitemap.xml",
    "rogmovies": "https://rogmovies.one",
    "rogmovies_sitemap": "https://rogmovies.one/sitemap.xml",
    "ssrmovies": "https://ssrmovies.gripe",
    "ssrmovies_sitemap": "https://ssrmovies.gripe/post-sitemap.xml",
    "7starhd": "https://7starhd.rich",
    "7starhd_sitemap": "https://7starhd.rich/post-sitemap.xml",
    "katmoviehd": "https://new.katmoviehd.top",
    "katmoviehd_landing": "https://katmovieshd.net",
    "multimovies": "https://multimovies.garden",
    "multimovies_sitemap": "https://multimovies.garden/sitemap.xml",
    "10xflix": "https://10xflix.help",
    "10xflix_sitemap": "https://10xflix.help/sitemap.xml",
    "cinemeta": "https://v3-cinemeta.strem.io",
    "gokuhd": "https://gokuhd.com",
    "nexdrive": "https://nexdrive.fit",
    "fastdl": "https://fastdl.beer",
    "vcloud": "https://vcloud.beer",
    "vegadrive": "https://one.vegadrive.me",
    "filepress": "https://new1.filepress.lat",
    "linkszilla": "https://secure.linkszilla.top",
    "hubcloud": "https://hubcloud.ist",
    "directcloud": "https://dl.direct-cloud.top",
    "mobilejsr": "https://mobilejsr.com",
    "hdhub4u": "https://hdtvb.net",
    "hdhub4u_sitemap": "https://hdtvb.net/sitemap.xml",
    "bollyshares": "https://bollyshares.xyz",
    "bollyshares_sitemap": "https://bollyshares.xyz/post-sitemap.xml",
    "filmyzilla": "https://www.filmyzilla74.com",
    "filmyzilla_sitemap": "https://www.filmyzilla74.com/sitemap.xml",
}

SITE_CANDIDATE_TLDS = {
    "vegamovies": ["gallery", "one", "im", "click", "vip", "beer", "wtf", "site", "to", "vet"],
    "rogmovies": ["one", "wtf", "vip", "beer", "club", "site", "fit", "fun", "im"],
    "ssrmovies": ["gripe", "games", "monster", "club", "fit", "vip", "top", "space"],
    "7starhd": ["rich", "run", "skin", "photos", "life", "vet", "com", "surf"],
    "katmoviehd": ["fans", "rodeo", "top", "pictures", "eu", "net"],
    "multimovies": ["garden", "com", "net", "org", "live"],
    "10xflix": ["help", "wiki", "me", "com", "org", "top"],
    "nexdrive": ["fit", "beer", "click", "xyz", "top", "to"],
    "fastdl": ["beer", "xyz", "live", "top"],
    "vcloud": ["beer", "live", "lol", "one"],
}


def get_domains() -> dict[str, str]:
    """Retrieves domains dynamically from database with fallback to defaults."""
    domains = dict(DEFAULT_DOMAINS)
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT name, url FROM domains_config").fetchall()
            for r in rows:
                domains[r["name"]] = r["url"]
                if r["name"] == "vegamovies_sitemap" and "sitemap" not in [x["name"] for x in rows]:
                    domains["sitemap"] = r["url"]
    except Exception:
        pass
    return domains


def set_domain(name: str, url: str) -> None:
    """Updates a domain in the database."""
    init_db()
    clean_url = url.rstrip("/")
    with get_db() as conn:
        conn.execute("""
            INSERT INTO domains_config (name, url, last_checked)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET url = excluded.url, last_checked = CURRENT_TIMESTAMP
        """, (name, clean_url))
    if name in DOMAINS:
        DOMAINS[name] = clean_url


# Module-level domain dictionary
DOMAINS = get_domains()

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


ADULT_TITLE_PATTERNS = [
    r"\b18\+", r"\b18\s*\+", r"\badult\b", r"\berotic\b", r"\bhotshots\b", r"\bullu\b",
    r"\bkooku\b", r"\bprimeplay\b", r"\brabbit\b", r"\bhunters\b",
    r"\bunrated\b", r"\bnsfw\b", r"\bporn\b", r"\bxxx\b", r"\bboldscene\b",
    r"\brealitykings\b", r"\btushy\b", r"\bvixen\b", r"\bblacked\b", r"\bwankz\b",
    r"\blustery\b", r"\bnaughty\b", r"\buncut\b", r"\biuliian\b", r"\bmoodyz\b",
]


def is_adult_title(*texts) -> int:
    """Returns 1 when any title/slug/tag text matches adult patterns."""
    joined = " ".join(t for t in texts if t)
    return 1 if any(re.search(p, joined, re.IGNORECASE) for p in ADULT_TITLE_PATTERNS) else 0


#: The animation vocabulary, in one place. `posts.is_animated` is what the app's
#: Anime filter and the v2 `animated` facet read, so every writer must agree on it.
ANIMATED_TITLE_PATTERNS = (
    r"\banime\b", r"\banimation\b", r"\banimated\b", r"\bcartoon\b",
    r"\bdonghua\b", r"\bcrunchyroll\b", r"\bgokuhd\b",
)


def looks_animated(*texts) -> int:
    """Returns 1 when any title/slug/genre text names animation. Same shape as
    `is_adult_title()`: a flag a caller may assert, never one it can contradict."""
    joined = " ".join(t for t in texts if t)
    return 1 if any(re.search(p, joined, re.IGNORECASE) for p in ANIMATED_TITLE_PATTERNS) else 0


#: Sites whose whole catalog is animation. Their staging schema carries no
#: `is_animated` column at all, so a post that came from one of them is animated by
#: construction. This is ledger-side evidence only: it sets a content flag and is
#: never copied onto a wire field — see `redact.py`.
ANIME_ONLY_SITES = frozenset({"rareanimes", "toonworld4all"})


def site_implies_animation(source_site) -> int:
    return 1 if str(source_site or "").strip().lower() in ANIME_ONLY_SITES else 0


def normalize_url(url: str) -> str:
    """
    Normalizes a URL to point to current live domains if it uses an older/alternate domain.
    E.g. https://rogmovies.wtf/... -> https://rogmovies.one/...
    https://ssrmovies.games/... -> https://ssrmovies.gripe/...
    https://katmovieshd.net/... -> https://katmoviehd.fans/...
    """
    if not url or not url.startswith("http"):
        return url
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower()

    # Check Rogmovies
    if "rogmovies" in host and not host.startswith("img."):
        active_rog = DOMAINS.get("rogmovies", "https://rogmovies.one")
        active_host = urllib.parse.urlparse(active_rog).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check Vegamovies
    if "vegamovies" in host and not host.endswith("-apk.com"):
        active_vega = DOMAINS.get("vegamovies", "https://vegamovies.gallery")
        active_host = urllib.parse.urlparse(active_vega).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check SSRMovies (games -> gripe)
    if "ssrmovies" in host:
        active_ssr = DOMAINS.get("ssrmovies", "https://ssrmovies.gripe")
        active_host = urllib.parse.urlparse(active_ssr).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check KatMovieHD
    if "katmovie" in host:
        active_km = DOMAINS.get("katmoviehd", "https://katmoviehd.fans")
        active_host = urllib.parse.urlparse(active_km).netloc.lower()
        if host != active_host and not any(k in host for k in ["links.kmhd", "api.dandndn"]):
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check 7StarHD
    if "7starhd" in host:
        active_7s = DOMAINS.get("7starhd", "https://7starhd.rich")
        active_host = urllib.parse.urlparse(active_7s).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check 10xflix (wiki -> help)
    if "10xflix" in host:
        active_10x = DOMAINS.get("10xflix", "https://10xflix.help")
        active_host = urllib.parse.urlparse(active_10x).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check MultiMovies
    if "multimovies" in host:
        active_mm = DOMAINS.get("multimovies", "https://multimovies.garden")
        active_host = urllib.parse.urlparse(active_mm).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check Bollywood1 / BollyShares
    if "bollywood1" in host or "bollyshares" in host:
        active_bolly = DOMAINS.get("bollyshares", "https://bollyshares.xyz")
        active_host = urllib.parse.urlparse(active_bolly).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check HDHub4u
    if "hdhub4u" in host:
        active_hub = DOMAINS.get("hdhub4u", "https://new7.hdhub4u.cl")
        active_host = urllib.parse.urlparse(active_hub).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    # Check KatMovieHD
    if "katmovie" in host:
        active_km = DOMAINS.get("katmoviehd", "https://new.katmoviehd.top")
        active_host = urllib.parse.urlparse(active_km).netloc.lower()
        if host != active_host:
            return urllib.parse.urlunparse((p.scheme or "https", active_host, p.path, p.params, p.query, p.fragment))

    return url


def harvest_sister_domains(html: str) -> dict[str, str]:
    """
    Harvests current sister-site URLs linked in navigation bars and banners.
    Sister sites cross-link to each other's live domains!
    """
    harvested = {}
    if not html or "<" not in html:
        return harvested

    links = re.findall(r'href=["\'](https?://[^"\'\s>]+)["\']', html)
    for l in links:
        p = urllib.parse.urlparse(l)
        netloc = p.netloc.lower()
        if "vegamovies" in netloc and not netloc.endswith("-apk.com") and not any(x in netloc for x in ["img.", "wp.", "cdn."]):
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if DOMAINS.get("vegamovies") != base:
                set_domain("vegamovies", base)
                set_domain("vegamovies_sitemap", f"{base}/sitemap.xml")
                DOMAINS["vegamovies"] = base
                DOMAINS["vegamovies_sitemap"] = f"{base}/sitemap.xml"
                harvested["vegamovies"] = base
        elif "rogmovies" in netloc and not any(x in netloc for x in ["img.", "wp.", "cdn."]):
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if DOMAINS.get("rogmovies") != base:
                set_domain("rogmovies", base)
                set_domain("rogmovies_sitemap", f"{base}/sitemap.xml")
                DOMAINS["rogmovies"] = base
                DOMAINS["rogmovies_sitemap"] = f"{base}/sitemap.xml"
                harvested["rogmovies"] = base
        elif "ssrmovies" in netloc and not any(x in netloc for x in ["img.", "wp.", "cdn."]):
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if DOMAINS.get("ssrmovies") != base:
                set_domain("ssrmovies", base)
                set_domain("ssrmovies_sitemap", f"{base}/post-sitemap.xml")
                DOMAINS["ssrmovies"] = base
                DOMAINS["ssrmovies_sitemap"] = f"{base}/post-sitemap.xml"
                harvested["ssrmovies"] = base
        elif "7starhd" in netloc and not any(x in netloc for x in ["img.", "wp.", "cdn."]):
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if DOMAINS.get("7starhd") != base:
                set_domain("7starhd", base)
                set_domain("7starhd_sitemap", f"{base}/post-sitemap.xml")
                DOMAINS["7starhd"] = base
                DOMAINS["7starhd_sitemap"] = f"{base}/post-sitemap.xml"
                harvested["7starhd"] = base
        elif "katmovie" in netloc and not any(x in netloc for x in ["img.", "wp.", "cdn.", "links.", "kmhd."]):
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if DOMAINS.get("katmoviehd") != base:
                set_domain("katmoviehd", base)
                DOMAINS["katmoviehd"] = base
                harvested["katmoviehd"] = base
        elif "gokuhd" in netloc:
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if DOMAINS.get("gokuhd") != base:
                set_domain("gokuhd", base)
                DOMAINS["gokuhd"] = base
                harvested["gokuhd"] = base
    return harvested


def probe_candidate_domains(site_name: str) -> str | None:
    """
    If a domain is unreachable / seized / NXDOMAIN, probes candidate TLDs
    to find the new live mirror.
    """
    candidates = SITE_CANDIDATE_TLDS.get(site_name, [])
    for tld in candidates:
        candidate_url = f"https://{site_name}.{tld}"
        try:
            req = urllib.request.Request(candidate_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=5) as resp:
                final_u = resp.geturl().rstrip("/")
                print(f"[✓] Auto-discovered live mirror for {site_name}: {final_u}")
                set_domain(site_name, final_u)
                if site_name == "vegamovies":
                    set_domain("vegamovies_sitemap", f"{final_u}/sitemap.xml")
                elif site_name == "rogmovies":
                    set_domain("rogmovies_sitemap", f"{final_u}/sitemap.xml")
                elif site_name == "ssrmovies":
                    set_domain("ssrmovies_sitemap", f"{final_u}/post-sitemap.xml")
                elif site_name == "7starhd":
                    set_domain("7starhd_sitemap", f"{final_u}/post-sitemap.xml")
                elif site_name == "katmoviehd":
                    set_domain("katmoviehd", final_u)
                DOMAINS.update(get_domains())
                return final_u
        except Exception:
            continue


# ── Media Classification Engine ───────────────────────────────────────────────

def classify_media(source_site: str, title: str, slug: str, html: str = "") -> dict[str, str]:
    """
    Classifies media into source_site, industry, country, and language.
    """
    title_slug = f"{title or ''} {slug or ''}".lower()

    if not source_site:
        if "rogmovies" in title_slug or "rogmovies" in html.lower():
            source_site = "rogmovies"
        else:
            source_site = "vegamovies"

    is_anime = bool(looks_animated(title_slug))
    is_kdrama = bool(re.search(r"\b(k-drama|kdrama|korean)\b", title_slug))
    is_cdrama = bool(re.search(r"\b(c-drama|cdrama|chinese)\b", title_slug))
    is_japanese_live = bool(re.search(r"\b(japanese|j-drama)\b", title_slug)) and not is_anime

    is_punjabi = bool(re.search(r"\b(punjabi|pollywood)\b", title_slug))
    is_telugu = bool(re.search(r"\b(telugu|tollywood)\b", title_slug))
    is_tamil = bool(re.search(r"\b(tamil|kollywood)\b", title_slug))
    is_malayalam = bool(re.search(r"\b(malayalam|mollywood)\b", title_slug))
    is_kannada = bool(re.search(r"\b(kannada|sandalwood)\b", title_slug))
    is_bengali = bool(re.search(r"\b(bengali)\b", title_slug))
    is_marathi = bool(re.search(r"\b(marathi)\b", title_slug))
    is_gujarati = bool(re.search(r"\b(gujarati)\b", title_slug))
    is_south_dubbed = bool(re.search(r"\b(south\b|south dubbed|hindi dubbed line|org dubbed)\b", title_slug))
    is_indian = source_site == "rogmovies" or any([
        is_punjabi, is_telugu, is_tamil, is_malayalam, is_kannada,
        is_bengali, is_marathi, is_gujarati, is_south_dubbed,
        re.search(r"\b(bollywood|hindi movie|hindi series|ullu|alt balaji|hotstar|jiohotstar|zeecinema|sonyliv)\b", title_slug)
    ])
    is_wwe = bool(re.search(r"\b(wwe|smackdown|raw|nxt|wrestlemania|summerslam|royal rumble|ple|ppv|aew)\b", title_slug))

    if is_wwe:
        industry = "WWE / Wrestling"
        country = "USA"
    elif is_indian:
        country = "India"
        if is_punjabi:
            industry = "Pollywood (Punjabi)"
        elif is_telugu:
            industry = "Tollywood (Telugu)"
        elif is_tamil:
            industry = "Kollywood (Tamil)"
        elif is_malayalam:
            industry = "Mollywood (Malayalam)"
        elif is_kannada:
            industry = "Sandalwood (Kannada)"
        elif is_bengali:
            industry = "Bengali Cinema"
        elif is_marathi:
            industry = "Marathi Cinema"
        elif is_gujarati:
            industry = "Gujarati Cinema"
        elif is_south_dubbed:
            industry = "South Indian (Hindi Dubbed)"
        else:
            industry = "Bollywood"
    elif is_anime:
        industry = "Anime"
        country = "Japan"
    elif is_kdrama:
        industry = "K-Drama"
        country = "South Korea"
    elif is_cdrama:
        industry = "C-Drama"
        country = "China"
    elif is_japanese_live:
        industry = "Japanese Cinema"
        country = "Japan"
    else:
        industry = "Hollywood"
        country = "USA"
        if re.search(r"\b(bbc|british|uk|england)\b", title_slug):
            country = "United Kingdom"

    # Audio Language
    lang_m = re.search(r"\{([^}]+)\}", title or "") or re.search(r"\[([A-Za-z0-9\s\+\-\.,/]+Aud[A-Za-z0-9\s\+\-\.,/]*)\]", title or "", re.IGNORECASE)
    raw_lang = lang_m.group(1).strip() if lang_m else ""

    if not raw_lang:
        found_langs = []
        for l_kw in ["Hindi", "English", "Telugu", "Tamil", "Punjabi", "Malayalam", "Kannada", "Bengali", "Marathi", "Gujarati", "Japanese", "Korean", "Mandarin"]:
            if re.search(rf"\b{l_kw}\b", title or "", re.IGNORECASE):
                found_langs.append(l_kw)
        if len(found_langs) > 1:
            raw_lang = " + ".join(found_langs)
        elif len(found_langs) == 1:
            raw_lang = found_langs[0]

    if not raw_lang:
        if source_site == "rogmovies" or is_indian:
            language = "Hindi"
        elif is_anime:
            language = "Japanese / English"
        elif is_kdrama:
            language = "Korean"
        else:
            language = "English"
    else:
        cleaned = raw_lang.replace("-", " + ").replace("–", " + ").replace("/", " + ")
        cleaned = re.sub(r"\s*\+\s*", " + ", cleaned).strip()
        language = cleaned

    return {
        "source_site": source_site,
        "industry": industry,
        "country": country,
        "language": language,
        # The classification already had to decide whether this is animation to pick
        # the industry; returning that verdict is what lets one rule own the column.
        "animated": 1 if is_anime else 0,
    }


def generate_canonical_key(title: str, year: int | None = None) -> str:
    """
    Produces a normalized canonical key for cross-site media deduplication.
    e.g. 'Dune: Part Two (2024)' -> 'dune-part-two_2024'
    'The Royal Cat aka Jin Ling Yu Mao (2024)' -> 'the-royal-cat_2024'
    'The Silent Planet 2024' -> 'the-silent-planet_2024'
    """
    if not title:
        return "unknown"
    t = title.lower()
    t = re.sub(r"\baka\b.*$", "", t)
    t = re.sub(r"\[.*?\]|\(.*?\)", "", t)
    t = re.sub(
        r"\b(480p|720p|1080p|2160p|4k|bluray|web-dl|hdrip|esubs|dual audio|multi audio|hindi|org|full movie|season\s*\d+|s\d+|complete|download|watch|series)\b",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if year:
        return f"{t}_{year}"
    return t or "unknown"


def get_poster_quality_rank(url: str | None) -> int:
    """
    Returns an artwork quality score to prevent high-res TMDB artwork from
    being overwritten by low-res blog/thumbnail uploads.
    """
    if not url:
        return 0
    u = url.lower()
    if "image.tmdb.org/t/p/original" in u:
        return 10
    if "image.tmdb.org/t/p/w500" in u or "media-amazon.com" in u:
        return 8
    if "image.tmdb.org" in u or "imdb" in u:
        return 7
    if "catimages.org" in u or "imgbb.com" in u or "postimg" in u:
        return 5
    if "wp-content/uploads" in u:
        return 3
    return 2


# ── Database Layer ────────────────────────────────────────────────────────────
_DB_WRITE_LOCK = threading.RLock()

@contextmanager
def get_db(db_path: Path | None = None):
    if db_path is None:
        db_path = DB_PATH
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


#: Season-level artwork lives beside the work, not inside it: a show has one root
#: poster and then one season poster plus one still per episode. Keeping the rows
#: in their own table means `posts.poster_url` stays the single answer for "the
#: work's poster" and a backfill can add or refresh seasons without rewriting it.
#: `kind` is `season_poster` (episode_number 0) or `episode_still`.
POST_ARTWORK_DDL = """
CREATE TABLE IF NOT EXISTS post_artwork (
    post_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    season_number INTEGER NOT NULL DEFAULT 0,
    episode_number INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'tmdb',
    width INTEGER,
    height INTEGER,
    language TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id, kind, season_number, episode_number),
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_post_artwork_post
    ON post_artwork(post_id, kind, season_number);
"""


def init_db(db_path: Path | None = None) -> None:
    with _DB_WRITE_LOCK:
        _init_db(db_path)


def _init_db(db_path: Path | None = None) -> None:
    with get_db(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS domains_config (
            name TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sitemap_cache (
            loc TEXT PRIMARY KEY,
            lastmod TEXT,
            slug TEXT,
            scraped INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0,
            last_attempt REAL DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            slug TEXT,
            title TEXT,
            clean_title TEXT,
            year INTEGER,
            content_type TEXT,
            seasons TEXT,
            poster_url TEXT,
            backdrop_urls TEXT,
            imdb_rating TEXT,
            genres TEXT,
            synopsis TEXT,
            is_18_plus INTEGER DEFAULT 0,
            is_animated INTEGER DEFAULT 0,
            lastmod TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            release_title TEXT,
            season TEXT,
            episode TEXT,
            quality TEXT,
            codec TEXT,
            size TEXT,
            languages TEXT,
            intermediate_url TEXT,
            source_site TEXT DEFAULT NULL,
            origin_url TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_releases_post ON releases(post_id);
        -- idx_releases_origin is created after the migration below: an existing staging
        -- database still holds the old releases table, and indexing a column that table
        -- does not have yet aborts the whole script.

        CREATE TABLE IF NOT EXISTS download_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER NOT NULL,
            source_name TEXT,
            service TEXT,
            resource_id TEXT,
            source_url TEXT,
            final_url TEXT,
            playback_type TEXT DEFAULT 'url',
            is_temporary INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            is_resumable INTEGER DEFAULT 0,
            http_status INTEGER DEFAULT NULL,
            file_size_bytes INTEGER DEFAULT NULL,
            mime_type TEXT DEFAULT NULL,
            last_checked_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (release_id) REFERENCES releases(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sources_rel ON download_sources(release_id);
        CREATE INDEX IF NOT EXISTS idx_sources_res ON download_sources(resource_id);
        CREATE INDEX IF NOT EXISTS idx_sources_status_temp ON download_sources(status, is_temporary);
        CREATE INDEX IF NOT EXISTS idx_sources_rel_status ON download_sources(release_id, status);
        """)
        # Every index on a column a migration can add is created *after* the migration
        # pass below. `CREATE TABLE IF NOT EXISTS` is a no-op on an existing staging
        # database, so indexing a column that old table does not have yet aborts the
        # whole script — which is exactly how `slug` and `origin_url` each took down
        # a site's upgrade.

        # Insert defaults for domains_config if missing
        for k, v in DEFAULT_DOMAINS.items():
            conn.execute("INSERT OR IGNORE INTO domains_config (name, url) VALUES (?, ?)", (k, v))

        # Migrations for existing databases
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(posts)")
        existing_p_cols = {r[1] for r in cursor.fetchall()}
        p_cols = {
            "slug": "TEXT",
            "poster_url": "TEXT",
            "backdrop_urls": "TEXT",
            "imdb_rating": "TEXT",
            "genres": "TEXT",
            "synopsis": "TEXT",
            "is_18_plus": "INTEGER DEFAULT 0",
            "is_animated": "INTEGER DEFAULT 0",
            "source_site": "TEXT DEFAULT 'vegamovies'",
            "industry": "TEXT DEFAULT 'Hollywood'",
            "country": "TEXT DEFAULT 'USA'",
            "language": "TEXT DEFAULT 'English'",
            "canonical_key": "TEXT DEFAULT NULL",
            "tmdb_id": "INTEGER DEFAULT NULL",
            "imdb_id": "TEXT DEFAULT NULL",
        }
        for col, col_t in p_cols.items():
            if col not in existing_p_cols:
                cursor.execute(f"ALTER TABLE posts ADD COLUMN {col} {col_t}")

        cursor.execute("PRAGMA table_info(releases)")
        existing_r_cols = {r[1] for r in cursor.fetchall()}
        if "source_site" not in existing_r_cols:
            cursor.execute("ALTER TABLE releases ADD COLUMN source_site TEXT DEFAULT NULL")
        if "origin_url" not in existing_r_cols:
            # A site can publish one title across several pages (a season page, an
            # episode-pack page, ...). Releases are replaced per page, so each row has
            # to remember which page produced it or a later page would wipe the earlier one.
            cursor.execute("ALTER TABLE releases ADD COLUMN origin_url TEXT DEFAULT NULL")
            cursor.execute(
                "UPDATE releases SET origin_url = ("
                "  SELECT url FROM posts WHERE posts.id = releases.post_id"
                ") WHERE origin_url IS NULL"
            )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_releases_origin"
            " ON releases(post_id, source_site, origin_url)"
        )

        cursor.execute("PRAGMA table_info(sitemap_cache)")
        existing_sm_cols = {r[1] for r in cursor.fetchall()}
        if "slug" not in existing_sm_cols:
            cursor.execute("ALTER TABLE sitemap_cache ADD COLUMN slug TEXT")
        if "site" not in existing_sm_cols:
            cursor.execute("ALTER TABLE sitemap_cache ADD COLUMN site TEXT DEFAULT 'vegamovies'")
        if "attempts" not in existing_sm_cols:
            cursor.execute("ALTER TABLE sitemap_cache ADD COLUMN attempts INTEGER DEFAULT 0")
        if "last_attempt" not in existing_sm_cols:
            cursor.execute("ALTER TABLE sitemap_cache ADD COLUMN last_attempt REAL DEFAULT NULL")
        if "last_cause" not in existing_sm_cols:
            # A bare `scraped = -1` could not tell an operator whether a page was
            # gone upstream or merely unreadable by us — the two need opposite
            # actions (drop it vs fix the parser). `record_crawl_attempt()` writes
            # the reason; nothing indexes it, so the ALTER stays safe on old DBs.
            cursor.execute("ALTER TABLE sitemap_cache ADD COLUMN last_cause TEXT DEFAULT NULL")

        cursor.execute("PRAGMA table_info(download_sources)")
        existing_ds_cols = {r[1] for r in cursor.fetchall()}
        if "expires_at" not in existing_ds_cols:
            # Epoch seconds at which the *observed* URL stops working, learned from
            # the response's own Cache-Control / Expires on the last resolve
            # (HANDOFF_apidocs A5). NULL means "never observed" — it is deliberately
            # not back-filled with a guess.
            cursor.execute("ALTER TABLE download_sources ADD COLUMN expires_at REAL DEFAULT NULL")
        if "ttl_source" not in existing_ds_cols:
            cursor.execute("ALTER TABLE download_sources ADD COLUMN ttl_source TEXT DEFAULT NULL")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_source_ind ON posts(source_site, industry)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_canonical_key ON posts(canonical_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_releases_source_site ON releases(source_site)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_site ON sitemap_cache(site, scraped)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_retry ON sitemap_cache(scraped, attempts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_tmdb ON posts(tmdb_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_imdb ON posts(imdb_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts(slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_slug ON sitemap_cache(slug)")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS post_sources (
            post_id INTEGER NOT NULL,
            source_site TEXT NOT NULL,
            url TEXT NOT NULL,
            source_title TEXT,
            source_slug TEXT,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_site, url),
            FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_post_sources_post ON post_sources(post_id);
        CREATE INDEX IF NOT EXISTS idx_post_sources_site_post ON post_sources(source_site, post_id);
        """)
        conn.executescript(POST_ARTWORK_DDL)

        # Preserve each known post's original source URL when upgrading older DBs.
        conn.execute("""
            INSERT OR IGNORE INTO post_sources
                (post_id, source_site, url, source_title, source_slug)
            SELECT id, COALESCE(NULLIF(source_site, ''), 'unknown'), url, title, slug
            FROM posts
            WHERE url IS NOT NULL AND url != ''
        """)

        cursor.execute("PRAGMA table_info(download_sources)")
        existing_s_cols = {r[1] for r in cursor.fetchall()}
        s_cols = {
            "playback_type": "TEXT DEFAULT 'url'",
            "is_resumable": "INTEGER DEFAULT 0",
            "http_status": "INTEGER DEFAULT NULL",
            "file_size_bytes": "INTEGER DEFAULT NULL",
            "mime_type": "TEXT DEFAULT NULL",
            "last_checked_at": "TIMESTAMP DEFAULT NULL",
        }
        for col, col_t in s_cols.items():
            if col not in existing_s_cols:
                cursor.execute(f"ALTER TABLE download_sources ADD COLUMN {col} {col_t}")

        # Auto-classify any unclassified existing posts
        unclassified = conn.execute("SELECT id, url, title, slug, clean_title, is_animated, genres FROM posts WHERE industry IS NULL OR source_site IS NULL OR industry = ''").fetchall()
        for up in unclassified:
            site = "rogmovies" if "rogmovies" in (up["url"] or "") else "vegamovies"
            meta = classify_media(site, up["title"] or up["clean_title"], up["slug"], "")
            conn.execute("""
                UPDATE posts
                SET source_site = ?, industry = ?, country = ?, language = ?,
                    is_animated = MAX(is_animated, ?)
                WHERE id = ?
            """, (meta["source_site"], meta["industry"], meta["country"], meta["language"],
                  meta["animated"], up["id"]))

        # Backfill canonical_key on existing posts
        missing_ckey = conn.execute("SELECT id, title, clean_title, year FROM posts WHERE canonical_key IS NULL OR canonical_key = ''").fetchall()
        for mc in missing_ckey:
            ck = generate_canonical_key(mc["clean_title"] or mc["title"], mc["year"])
            conn.execute("UPDATE posts SET canonical_key = ? WHERE id = ?", (ck, mc["id"]))

        # Keep legacy release sources unattributed rather than incorrectly
        # assigning them to the post's first-seen site.


# ── HTTP Networking ───────────────────────────────────────────────────────────

def http_get(url: str, timeout: int = 15, max_retries: int = 2, allow_probe: bool = True) -> tuple[int, str, str]:
    """
    Returns (status_code, final_url, html_content).
    Tracks HTTP 301/302 redirects to auto-update domains in SQLite and memory.
    """
    norm_url = normalize_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(norm_url, headers=headers)
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
                final_url = resp.geturl()
                # Auto-detect domain change/redirect
                p_orig = urllib.parse.urlparse(norm_url)
                p_final = urllib.parse.urlparse(final_url)
                if p_orig.netloc and p_final.netloc and p_orig.netloc.lower() != p_final.netloc.lower():
                    new_base = f"{p_final.scheme}://{p_final.netloc}".rstrip("/")
                    if "vegamovies" in p_orig.netloc.lower():
                        set_domain("vegamovies", new_base)
                        set_domain("vegamovies_sitemap", f"{new_base}/sitemap.xml")
                        set_domain("sitemap", f"{new_base}/sitemap.xml")
                        DOMAINS["vegamovies"] = new_base
                        DOMAINS["vegamovies_sitemap"] = f"{new_base}/sitemap.xml"
                        DOMAINS["sitemap"] = f"{new_base}/sitemap.xml"
                        print(f"  [🔀 Domain Redirect] vegamovies: {p_orig.netloc} -> {p_final.netloc} (Saved to DB)")
                    elif "rogmovies" in p_orig.netloc.lower():
                        set_domain("rogmovies", new_base)
                        set_domain("rogmovies_sitemap", f"{new_base}/sitemap.xml")
                        DOMAINS["rogmovies"] = new_base
                        DOMAINS["rogmovies_sitemap"] = f"{new_base}/sitemap.xml"
                        print(f"  [🔀 Domain Redirect] rogmovies: {p_orig.netloc} -> {p_final.netloc} (Saved to DB)")
                    elif "nexdrive" in p_orig.netloc.lower():
                        set_domain("nexdrive", new_base)
                        DOMAINS["nexdrive"] = new_base
                        print(f"  [🔀 Domain Redirect] nexdrive: {p_orig.netloc} -> {p_final.netloc} (Saved to DB)")
                    elif "fastdl" in p_orig.netloc.lower():
                        set_domain("fastdl", new_base)
                        DOMAINS["fastdl"] = new_base
                    elif "vcloud" in p_orig.netloc.lower():
                        set_domain("vcloud", new_base)
                        DOMAINS["vcloud"] = new_base

                charset = resp.headers.get_content_charset() or "utf-8"
                content = resp.read().decode(charset, errors="replace")

                # Check for sister links in content to keep domains updated
                harvest_sister_domains(content)

                return resp.status, final_url, content
        except Exception as e:
            if attempt == max_retries:
                if allow_probe:
                    # If DNS failure or connection error on main site, try candidate TLD probe once
                    p = urllib.parse.urlparse(norm_url)
                    for site in ["vegamovies", "rogmovies", "nexdrive"]:
                        if site in p.netloc.lower():
                            live_mirror = probe_candidate_domains(site)
                            if live_mirror:
                                retry_u = normalize_url(url)
                                return http_get(retry_u, timeout=timeout, max_retries=1, allow_probe=False)
                return 0, norm_url, f"ERROR: {e}"
            time.sleep(1)
    return 0, norm_url, "ERROR: request failed"


# ── Sitemap Indexer ───────────────────────────────────────────────────────────

def extract_xml_tags(xml_text: str, tag: str) -> list[str]:
    return re.findall(rf"<{tag}>(.*?)</{tag}>", xml_text, flags=re.DOTALL | re.IGNORECASE)


def sync_sitemaps(site: str = "all", max_sub_sitemaps: int | None = None, include_categories: bool = False, cat_pages: int = 3, verbose: bool = True) -> int:
    """
    Fetches the main sitemap and post feeds, caching URLs into sitemap_cache.
    Supports site='vegamovies', 'rogmovies', 'ssrmovies', '7starhd', 'katmoviehd', or 'all'.
    """
    init_db()
    total_added_global = 0

    # 1. Standard XML sitemap sites (Vegamovies, RogMovies)
    xml_sites = []
    if site in ("vegamovies", "all"):
        xml_sites.append(("vegamovies", DOMAINS.get("vegamovies_sitemap", "https://vegamovies.gallery/sitemap.xml")))
    if site in ("rogmovies", "all"):
        xml_sites.append(("rogmovies", DOMAINS.get("rogmovies_sitemap", "https://rogmovies.one/sitemap.xml")))

    for site_name, sitemap_url in xml_sites:
        if verbose:
            print(f"\n[i] Fetching main sitemap for {site_name.upper()}: {sitemap_url}")
        code, _, xml = http_get(sitemap_url)
        if code != 200:
            print(f"[!] Failed to fetch sitemap for {site_name}: HTTP {code}")
            continue

        sub_sitemaps = re.findall(r"<loc>(https?://[^<]+/post-sitemap\d*\.xml)</loc>", xml)
        if not sub_sitemaps:
            sub_sitemaps = re.findall(r"<loc>(https?://[^<]+\.xml)</loc>", xml)

        if max_sub_sitemaps:
            sub_sitemaps = sub_sitemaps[:max_sub_sitemaps]

        if verbose:
            print(f"[i] [{site_name.upper()}] Found {len(sub_sitemaps)} post sub-sitemaps to process.")

        records = []

        def fetch_sub(url: str):
            c, _, sub_xml = http_get(url)
            if c != 200:
                return []
            items = []
            urls = re.findall(r"<url>(.*?)</url>", sub_xml, flags=re.DOTALL)
            for u in urls:
                loc_m = re.search(r"<loc>(https?://[^<]+)</loc>", u)
                mod_m = re.search(r"<lastmod>([^<]+)</lastmod>", u)
                if loc_m:
                    loc = loc_m.group(1).strip()
                    lastmod = mod_m.group(1).strip() if mod_m else ""
                    slug = loc.rstrip("/").split("/")[-1]
                    items.append((loc, lastmod, slug, site_name))
            return items

        with ThreadPoolExecutor(max_workers=5) as pool:
            future_map = {pool.submit(fetch_sub, sm): sm for sm in sub_sitemaps}
            for fut in as_completed(future_map):
                sm_url = future_map[fut]
                try:
                    sub_records = fut.result()
                    records.extend(sub_records)
                    if verbose:
                        print(f"  ✓ [{site_name}] Processed {sm_url.split('/')[-1]} ({len(sub_records)} entries)")
                except Exception as ex:
                    if verbose:
                        print(f"  ✗ Error reading {sm_url}: {ex}")

        if records:
            with get_db() as conn:
                conn.executemany(
                    """
                    INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(loc) DO UPDATE SET
                        lastmod = excluded.lastmod,
                        slug = excluded.slug,
                        site = excluded.site
                    """,
                    records,
                )
                total_added_global += len(records)
            if verbose:
                print(f"[✓] [{site_name.upper()}] Cached {len(records)} posts in database.")

    # 2. SSRMovies WP REST API feed
    if site in ("ssrmovies", "all"):
        if verbose:
            print(f"\n[i] Fetching post feed for SSRMOVIES: {DOMAINS.get('ssrmovies')}/wp-json/wp/v2/posts")
        try:
            ssr_api_url = f"{DOMAINS.get('ssrmovies', 'https://ssrmovies.gripe')}/wp-json/wp/v2/posts?per_page=100"
            c, _, resp_body = http_get(ssr_api_url)
            if c == 200:
                posts_data = json.loads(resp_body)
                ssr_records = []
                for p in posts_data:
                    p_link = p.get("link", "").strip()
                    p_slug = p.get("slug", "") or p_link.rstrip("/").split("/")[-1]
                    p_date = p.get("date", "")
                    if p_link:
                        ssr_records.append((p_link, p_date, p_slug, "ssrmovies"))
                if ssr_records:
                    with get_db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(loc) DO UPDATE SET
                                lastmod = excluded.lastmod,
                                slug = excluded.slug,
                                site = excluded.site
                            """,
                            ssr_records,
                        )
                        total_added_global += len(ssr_records)
                    if verbose:
                        print(f"[✓] [SSRMOVIES] Cached {len(ssr_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching SSRMovies feed: {e}")

    # 3. 7StarHD Feed
    if site in ("7starhd", "all"):
        if verbose:
            print(f"\n[i] Fetching post feed for 7STARHD: {DOMAINS.get('7starhd')}")
        try:
            s7_url = DOMAINS.get("7starhd", "https://7starhd.rich")
            c, _, s7_html = http_get(s7_url)
            if c == 200:
                links7 = set(re.findall(r'href=["\'](https?://7starhd\.rich/[a-zA-Z0-9\-_]+/)["\']', s7_html))
                s7_records = []
                for l in links7:
                    if not any(x in l for x in ['/page/', '/category/', '/tag/', '/genre/', '/how-to', '/disclaimer', '/dmca']):
                        slug = l.rstrip("/").split("/")[-1]
                        s7_records.append((l, "", slug, "7starhd"))
                if s7_records:
                    with get_db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(loc) DO UPDATE SET
                                lastmod = excluded.lastmod,
                                slug = excluded.slug,
                                site = excluded.site
                            """,
                            s7_records,
                        )
                        total_added_global += len(s7_records)
                    if verbose:
                        print(f"[✓] [7STARHD] Cached {len(s7_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching 7StarHD feed: {e}")

    # 4. KatMovieHD SvelteKit Feed
    if site in ("katmoviehd", "all"):
        if verbose:
            print(f"\n[i] Fetching catalog feed for KATMOVIEHD: {DOMAINS.get('katmoviehd')}")
        try:
            km_url = DOMAINS.get("katmoviehd", "https://katmoviehd.fans")
            c, _, km_html = http_get(km_url)
            if c == 200:
                slugs = list(dict.fromkeys(re.findall(r'slug:"([^"]+)"', km_html)))
                km_records = []
                for sl in slugs:
                    full_loc = f"{km_url.rstrip('/')}/{sl}"
                    km_records.append((full_loc, "", sl, "katmoviehd"))
                if km_records:
                    with get_db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(loc) DO UPDATE SET
                                lastmod = excluded.lastmod,
                                slug = excluded.slug,
                                site = excluded.site
                            """,
                            km_records,
                        )
                        total_added_global += len(km_records)
                    if verbose:
                        print(f"[✓] [KATMOVIEHD] Cached {len(km_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching KatMovieHD feed: {e}")

    # 5. MultiMovies XML Sitemap
    if site in ("multimovies", "all"):
        if verbose:
            print(f"\n[i] Fetching sitemap for MULTIMOVIES: {DOMAINS.get('multimovies', 'https://multimovies.garden')}/sitemap.xml")
        try:
            mm_sm_url = DOMAINS.get("multimovies_sitemap", "https://multimovies.garden/sitemap.xml")
            c, _, mm_xml = http_get(mm_sm_url)
            if c == 200:
                sub_sm = re.findall(r'<loc>(https?://[^<]+/sitemap-titles-\d+\.xml)</loc>', mm_xml)
                if not sub_sm:
                    sub_sm = re.findall(r'<loc>(https?://[^<]+\.xml)</loc>', mm_xml)
                if max_sub_sitemaps:
                    sub_sm = sub_sm[:max_sub_sitemaps]

                mm_records = []
                for s_url in sub_sm:
                    c_sub, _, sub_content = http_get(s_url)
                    if c_sub == 200:
                        urls = re.findall(r'<loc>(https?://[^<]+)</loc>', sub_content)
                        for u in urls:
                            if any(x in u for x in ['/movie/', '/series/']):
                                slug = u.rstrip("/").split("/")[-1]
                                mm_records.append((u, "", slug, "multimovies"))
                if mm_records:
                    with get_db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(loc) DO UPDATE SET
                                lastmod = excluded.lastmod,
                                slug = excluded.slug,
                                site = excluded.site
                            """,
                            mm_records,
                        )
                        total_added_global += len(mm_records)
                    if verbose:
                        print(f"[✓] [MULTIMOVIES] Cached {len(mm_records)} titles in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching MultiMovies sitemap: {e}")

    # 6. 10xflix WP REST API Feed
    if site in ("10xflix", "all"):
        if verbose:
            print(f"\n[i] Fetching post feed for 10XFLIX: {DOMAINS.get('10xflix', 'https://10xflix.help')}/wp-json/wp/v2/posts")
        try:
            t10_api_url = f"{DOMAINS.get('10xflix', 'https://10xflix.help')}/wp-json/wp/v2/posts?per_page=100"
            c, _, resp_body = http_get(t10_api_url)
            if c == 200:
                posts_data = json.loads(resp_body)
                t10_records = []
                for p in posts_data:
                    p_link = p.get("link", "").strip()
                    p_slug = p.get("slug", "") or p_link.rstrip("/").split("/")[-1]
                    p_date = p.get("date", "")
                    if p_link:
                        t10_records.append((p_link, p_date, p_slug, "10xflix"))
                if t10_records:
                    with get_db() as conn:
                        conn.executemany(
                            """
                            INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                            VALUES (?, ?, ?, 0, ?)
                            ON CONFLICT(loc) DO UPDATE SET
                                lastmod = excluded.lastmod,
                                slug = excluded.slug,
                                site = excluded.site
                            """,
                            t10_records,
                        )
                        total_added_global += len(t10_records)
                    if verbose:
                        print(f"[✓] [10XFLIX] Cached {len(t10_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching 10xflix feed: {e}")

    # 7. HDHub4u — WP post sitemap
    if site in ("hdhub4u", "all"):
        if verbose:
            print(f"\n[i] Fetching post sitemap for HDHUB4U: {DOMAINS.get('hdhub4u', 'https://new3.hdhub4u.free')}/post-sitemap.xml")
        try:
            hub_sm_url = DOMAINS.get("hdhub4u_sitemap", "https://new3.hdhub4u.free/post-sitemap.xml")
            c, _, hub_xml = http_get(hub_sm_url)
            hub_records = []
            if c == 200:
                items = re.findall(r"<url>(.*?)</url>", hub_xml, flags=re.DOTALL)
                for it in items:
                    loc_m = re.search(r"<loc>(https?://[^<]+)</loc>", it)
                    mod_m = re.search(r"<lastmod>([^<]+)</lastmod>", it)
                    if loc_m:
                        loc = loc_m.group(1).strip()
                        lastmod = mod_m.group(1).strip() if mod_m else ""
                        slug = loc.rstrip("/").split("/")[-1]
                        if not any(x in loc for x in ["/category/", "/tag/", "/page/", "/genre/"]):
                            hub_records.append((loc, lastmod, slug, "hdhub4u"))
            if not hub_records:
                # Fallback: scrape homepage for <li class="thumb"> post links
                c2, _, hub_html = http_get(DOMAINS.get("hdhub4u", "https://new3.hdhub4u.free"))
                if c2 == 200:
                    raw_links = re.findall(r'href=["\'](https?://[^"\'>]*hdhub4u[^"\'>]*)["\'"]', hub_html)
                    for l in set(raw_links):
                        if not any(x in l for x in ["/category/", "/tag/", "/page/", "/genre/", "/wp-"]):
                            slug = l.rstrip("/").split("/")[-1]
                            hub_records.append((l, "", slug, "hdhub4u"))
            if hub_records:
                with get_db() as conn:
                    conn.executemany(
                        """
                        INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                        VALUES (?, ?, ?, 0, ?)
                        ON CONFLICT(loc) DO UPDATE SET
                            lastmod = excluded.lastmod,
                            slug = excluded.slug,
                            site = excluded.site
                        """,
                        hub_records,
                    )
                    total_added_global += len(hub_records)
                if verbose:
                    print(f"[✓] [HDHUB4U] Cached {len(hub_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching HDHub4u sitemap: {e}")

    # 8. BollyShares — WP post sitemap
    if site in ("bollyshares", "all"):
        if verbose:
            print(f"\n[i] Fetching post sitemap for BOLLYSHARES: {DOMAINS.get('bollyshares', 'https://bollyshares.xyz')}/post-sitemap.xml")
        try:
            bs_sm_url = DOMAINS.get("bollyshares_sitemap", "https://bollyshares.xyz/post-sitemap.xml")
            c, _, bs_xml = http_get(bs_sm_url)
            bs_records = []
            if c == 200:
                items = re.findall(r"<url>(.*?)</url>", bs_xml, flags=re.DOTALL)
                for it in items:
                    loc_m = re.search(r"<loc>(https?://[^<]+)</loc>", it)
                    mod_m = re.search(r"<lastmod>([^<]+)</lastmod>", it)
                    if loc_m:
                        loc = loc_m.group(1).strip()
                        lastmod = mod_m.group(1).strip() if mod_m else ""
                        slug = loc.rstrip("/").split("/")[-1]
                        if not any(x in loc for x in ["/category/", "/tag/", "/page/"]):
                            bs_records.append((loc, lastmod, slug, "bollyshares"))
            if not bs_records:
                # Fallback: scrape homepage
                c2, _, bs_html = http_get(DOMAINS.get("bollyshares", "https://bollyshares.xyz"))
                if c2 == 200:
                    raw_links = re.findall(r'href=["\'](https?://bollyshares\.xyz/free-[^"\'>]+)["\'"]', bs_html)
                    for l in set(raw_links):
                        slug = l.rstrip("/").split("/")[-1]
                        bs_records.append((l, "", slug, "bollyshares"))
            if bs_records:
                with get_db() as conn:
                    conn.executemany(
                        """
                        INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                        VALUES (?, ?, ?, 0, ?)
                        ON CONFLICT(loc) DO UPDATE SET
                            lastmod = excluded.lastmod,
                            slug = excluded.slug,
                            site = excluded.site
                        """,
                        bs_records,
                    )
                    total_added_global += len(bs_records)
                if verbose:
                    print(f"[✓] [BOLLYSHARES] Cached {len(bs_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching BollyShares sitemap: {e}")

    # 9. FilmyZilla — XML sitemap
    if site in ("filmyzilla", "all"):
        if verbose:
            print(f"\n[i] Fetching sitemap for FILMYZILLA: {DOMAINS.get('filmyzilla', 'https://www.filmyzilla74.com')}/sitemap.xml")
        try:
            fz_sm_url = DOMAINS.get("filmyzilla_sitemap", "https://www.filmyzilla74.com/sitemap.xml")
            c, _, fz_xml = http_get(fz_sm_url)
            fz_records = []
            if c == 200:
                # FilmyZilla main sitemap may contain sub-sitemaps or direct URLs
                sub_sm = re.findall(r"<loc>(https?://[^<]+\.xml)</loc>", fz_xml)
                if sub_sm:
                    if max_sub_sitemaps:
                        sub_sm = sub_sm[:max_sub_sitemaps]
                    for s_url in sub_sm:
                        c_sub, _, sub_content = http_get(s_url)
                        if c_sub == 200:
                            items = re.findall(r"<url>(.*?)</url>", sub_content, flags=re.DOTALL)
                            for it in items:
                                loc_m = re.search(r"<loc>(https?://[^<]+)</loc>", it)
                                mod_m = re.search(r"<lastmod>([^<]+)</lastmod>", it)
                                if loc_m:
                                    loc = loc_m.group(1).strip()
                                    if "/movie/" in loc or "/series/" in loc or "/tvshow/" in loc:
                                        lastmod = mod_m.group(1).strip() if mod_m else ""
                                        slug = loc.rstrip("/").split("/")[-1].replace(".html", "")
                                        fz_records.append((loc, lastmod, slug, "filmyzilla"))
                else:
                    # Flat sitemap
                    items = re.findall(r"<url>(.*?)</url>", fz_xml, flags=re.DOTALL)
                    for it in items:
                        loc_m = re.search(r"<loc>(https?://[^<]+)</loc>", it)
                        mod_m = re.search(r"<lastmod>([^<]+)</lastmod>", it)
                        if loc_m:
                            loc = loc_m.group(1).strip()
                            lastmod = mod_m.group(1).strip() if mod_m else ""
                            slug = loc.rstrip("/").split("/")[-1].replace(".html", "")
                            if not any(x in loc for x in ["/page/", "/category/", "/tag/"]):
                                fz_records.append((loc, lastmod, slug, "filmyzilla"))
            if fz_records:
                with get_db() as conn:
                    conn.executemany(
                        """
                        INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                        VALUES (?, ?, ?, 0, ?)
                        ON CONFLICT(loc) DO UPDATE SET
                            lastmod = excluded.lastmod,
                            slug = excluded.slug,
                            site = excluded.site
                        """,
                        fz_records,
                    )
                    total_added_global += len(fz_records)
                if verbose:
                    print(f"[✓] [FILMYZILLA] Cached {len(fz_records)} posts in database.")
        except Exception as e:
            if verbose:
                print(f"[!] Error fetching FilmyZilla sitemap: {e}")

    # Optional: category archive ingestion (HDHub4u & SSRMovies)
    if include_categories:
        total_added_global += sync_category_archives(site=site, max_pages_per_cat=cat_pages, verbose=verbose)

    if verbose:
        print(f"\n[✓] Global sync complete! Total {total_added_global} posts cached across configured sites.")
    return total_added_global


# ── Category Archive Ingestion (HDHub4u & SSRMovies) ──────────────────────────

DEFAULT_HDHUB4U_CATEGORIES = [
    "bollywood-movies", "hollywood-movies", "hindi-dubbed",
    "south-hindi-movies", "category/web-series", "animated-movies",
    "300mb-movies", "hd-movies", "action-movies", "comedy-movies", "thriller"
]

DEFAULT_SSRMOVIES_CATEGORIES = [
    {"id": 3, "slug": "bollywood-movies", "name": "Bollywood Movies"},
    {"id": 8, "slug": "hollywood-movies-hd", "name": "Hollywood Movies"},
    {"id": 7, "slug": "dual-audio-movies", "name": "Dual Audio Movies"},
    {"id": 6, "slug": "dubbed-movies", "name": "Hindi Dubbed Movies"},
    {"id": 5, "slug": "300mb-movies", "name": "300MB Movies"},
    {"id": 107, "slug": "animated-movies", "name": "Animated Movies"},
    {"id": 118, "slug": "gujarati-movies", "name": "Gujarati Movies"},
    {"id": 111, "slug": "fan-dub-movies", "name": "Fan Dub Movies"},
]


def fetch_categories_hdhub4u(verbose: bool = False) -> list[str]:
    """
    Discovers category archive paths for HDHub4u from homepage or returns verified defaults.
    Filters out adult/restricted categories.
    """
    base_u = DOMAINS.get("hdhub4u", "https://new7.hdhub4u.cl")
    code, _, html = http_get(base_u, timeout=10)
    if code == 200 and html:
        raw_cats = set(re.findall(r'href=["\'](?:https?://[^/]+)?/category/([a-zA-Z0-9\-_]+(?:/[a-zA-Z0-9\-_]+)?)/?["\']', html))
        cleaned = []
        for c in raw_cats:
            c_low = c.lower()
            if any(bad in c_low for bad in ["adult", "18-plus", "18plus", "porn", "erotic"]):
                continue
            cleaned.append(c)
        if cleaned:
            return sorted(cleaned)
    return list(DEFAULT_HDHUB4U_CATEGORIES)


def fetch_category_urls_hdhub4u(category: str, max_pages: int = 3, verbose: bool = True) -> list[tuple[str, str, str, str]]:
    """
    Crawls paginated category archives on HDHub4u (e.g. /category/bollywood-movies/page/2/).
    Returns list of (loc, lastmod, slug, 'hdhub4u').
    """
    base_u = DOMAINS.get("hdhub4u", "https://new7.hdhub4u.cl").rstrip("/")
    records = []
    seen_locs = set()

    clean_cat = category.strip("/")
    if clean_cat.startswith("category/"):
        cat_path = clean_cat
    else:
        cat_path = f"category/{clean_cat}"

    for page in range(1, max_pages + 1):
        if page == 1:
            page_url = f"{base_u}/{cat_path}/"
        else:
            page_url = f"{base_u}/{cat_path}/page/{page}/"

        if verbose:
            print(f"  [i] [HDHUB4U] Ingesting category '{clean_cat}' (page {page}): {page_url}")

        code, _, html = http_get(page_url, timeout=12)
        if code != 200 or not html:
            if verbose and code != 200:
                print(f"  [!] [HDHUB4U] Page {page} returned HTTP {code}, stopping pagination for '{clean_cat}'.")
            break

        raw_links = set(re.findall(r'href=["\'](https?://[^/\"\'#]+/[a-zA-Z0-9\-_]+/|/[a-zA-Z0-9\-_]+/)["\']', html))
        page_records = []
        for l in raw_links:
            if any(x in l for x in ['/category/', '/tag/', '/page/', '/genre/', '/how-to', '/disclaimer', '/dmca', '/request', '/join', '/wp-']):
                continue
            loc = urllib.parse.urljoin(base_u + "/", l).rstrip("/") + "/"
            if loc in seen_locs:
                continue
            seen_locs.add(loc)
            slug = loc.rstrip("/").split("/")[-1]
            if slug:
                page_records.append((loc, "", slug, "hdhub4u"))

        if not page_records:
            if verbose:
                print(f"  [i] [HDHUB4U] No further post links found on page {page} for '{clean_cat}'.")
            break

        records.extend(page_records)
        if verbose:
            print(f"  ✓ [HDHUB4U] Page {page} yielded {len(page_records)} posts.")

    return records


def fetch_categories_ssrmovies(verbose: bool = False) -> list[dict]:
    """
    Discovers category list and post counts from SSRMovies WordPress REST API.
    Filters out adult/restricted categories.
    """
    base_u = DOMAINS.get("ssrmovies", "https://ssrmovies.gripe").rstrip("/")
    api_url = f"{base_u}/wp-json/wp/v2/categories?per_page=100"
    code, _, resp_body = http_get(api_url, timeout=10)
    if code == 200 and resp_body:
        try:
            cats = json.loads(resp_body)
            results = []
            for c in cats:
                slug = c.get("slug", "")
                name = c.get("name", "")
                if any(bad in slug.lower() or bad in name.lower() for bad in ["18-", "18+", "adult", "erotic"]):
                    continue
                results.append({
                    "id": c.get("id"),
                    "slug": slug,
                    "name": name,
                    "count": c.get("count", 0),
                })
            if results:
                return results
        except Exception as e:
            if verbose:
                print(f"[!] Error parsing SSRMovies categories JSON: {e}")
    return list(DEFAULT_SSRMOVIES_CATEGORIES)


def fetch_category_urls_ssrmovies(category: str | int, max_pages: int = 3, verbose: bool = True) -> list[tuple[str, str, str, str]]:
    """
    Crawls paginated category archives on SSRMovies using WP REST API with HTML fallback.
    Returns list of (loc, lastmod, slug, 'ssrmovies').
    """
    base_u = DOMAINS.get("ssrmovies", "https://ssrmovies.gripe").rstrip("/")
    records = []
    seen_locs = set()

    cat_id = None
    cat_slug = str(category).strip("/")
    if isinstance(category, int) or (isinstance(category, str) and category.isdigit()):
        cat_id = int(category)
    else:
        for c in DEFAULT_SSRMOVIES_CATEGORIES:
            if c["slug"] == cat_slug or str(c["id"]) == cat_slug:
                cat_id = c["id"]
                break

    api_success = False
    if cat_id is not None:
        for page in range(1, max_pages + 1):
            api_url = f"{base_u}/wp-json/wp/v2/posts?categories={cat_id}&per_page=100&page={page}"
            if verbose:
                print(f"  [i] [SSRMOVIES] Ingesting category ID {cat_id} ({cat_slug}) via REST API (page {page})")
            code, _, body = http_get(api_url, timeout=10)
            if code == 200 and body:
                try:
                    posts = json.loads(body)
                    if not posts or not isinstance(posts, list):
                        break
                    page_records = []
                    for p in posts:
                        p_link = p.get("link", "").strip()
                        p_slug = p.get("slug", "") or p_link.rstrip("/").split("/")[-1]
                        p_date = p.get("date", "")
                        if p_link and p_link not in seen_locs:
                            seen_locs.add(p_link)
                            page_records.append((p_link, p_date, p_slug, "ssrmovies"))
                    if not page_records:
                        break
                    records.extend(page_records)
                    api_success = True
                    if verbose:
                        print(f"  ✓ [SSRMOVIES] REST page {page} yielded {len(page_records)} posts.")
                except Exception:
                    break
            else:
                break

    if not api_success:
        for page in range(1, max_pages + 1):
            if page == 1:
                html_url = f"{base_u}/category/{cat_slug}/"
            else:
                html_url = f"{base_u}/category/{cat_slug}/page/{page}/"

            if verbose:
                print(f"  [i] [SSRMOVIES] Ingesting category '{cat_slug}' via HTML archive (page {page}): {html_url}")
            code, _, html = http_get(html_url, timeout=10)
            if code != 200 or not html:
                break

            raw_links = set(re.findall(r'href=["\'](https?://[^/\"\'#]+/[a-zA-Z0-9\-_]+/?)["\']', html))
            page_records = []
            for l in raw_links:
                if any(x in l for x in ['/category/', '/tag/', '/page/', '/genre/', '/how-to', '/disclaimer', '/dmca', '/wp-']):
                    continue
                loc = l.rstrip("/") + "/"
                if loc in seen_locs:
                    continue
                seen_locs.add(loc)
                slug = loc.rstrip("/").split("/")[-1]
                if slug:
                    page_records.append((loc, "", slug, "ssrmovies"))

            if not page_records:
                break
            records.extend(page_records)
            if verbose:
                print(f"  ✓ [SSRMOVIES] HTML page {page} yielded {len(page_records)} posts.")

    return records


def sync_category_archives(site: str = "all", max_pages_per_cat: int = 3, category: str | None = None, verbose: bool = True) -> int:
    """
    Ingests paginated category archives for HDHub4u and/or SSRMovies into sitemap_cache.
    Supports site='hdhub4u', 'ssrmovies', or 'all'.
    """
    init_db()
    total_added = 0
    all_records = []

    if site in ("hdhub4u", "all"):
        if verbose:
            print(f"\n[i] ══════════ HDHUB4U Category Archive Ingestion (Max {max_pages_per_cat} pages/cat) ══════════")
        cats_to_fetch = [category] if category and site == "hdhub4u" else fetch_categories_hdhub4u(verbose=verbose)
        for cat in cats_to_fetch:
            records = fetch_category_urls_hdhub4u(cat, max_pages=max_pages_per_cat, verbose=verbose)
            all_records.extend(records)

    if site in ("ssrmovies", "all"):
        if verbose:
            print(f"\n[i] ══════════ SSRMOVIES Category Archive Ingestion (Max {max_pages_per_cat} pages/cat) ══════════")
        if category and site == "ssrmovies":
            cats_to_fetch = [category]
        else:
            cat_objs = fetch_categories_ssrmovies(verbose=verbose)
            cats_to_fetch = [c["slug"] for c in cat_objs]
        for cat in cats_to_fetch:
            records = fetch_category_urls_ssrmovies(cat, max_pages=max_pages_per_cat, verbose=verbose)
            all_records.extend(records)

    if all_records:
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO sitemap_cache (loc, lastmod, slug, scraped, site)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(loc) DO UPDATE SET
                    lastmod = CASE WHEN excluded.lastmod != '' THEN excluded.lastmod ELSE sitemap_cache.lastmod END,
                    slug = excluded.slug,
                    site = excluded.site
                """,
                all_records,
            )
            total_added = len(all_records)
        if verbose:
            print(f"\n[✓] Successfully ingested {total_added} category post links into sitemap cache.")
    else:
        if verbose:
            print(f"\n[i] No new category post links ingested.")

    return total_added


def search_sitemap(query: str, site: str | None = None, limit: int = 25) -> list[dict]:
    """
    Blazing fast offline search over cached sitemap slugs.
    Supports filtering by site ('vegamovies' or 'rogmovies').
    """
    init_db()
    words = [w.strip().lower() for w in query.split() if w.strip()]
    if not words:
        return []

    sql = "SELECT loc, slug, lastmod, scraped, site FROM sitemap_cache WHERE "
    conditions = ["slug LIKE ?" for _ in words]
    params = [f"%{w}%" for w in words]

    if site and site != "all":
        conditions.append("site = ?")
        params.append(site)

    sql += " AND ".join(conditions) + " ORDER BY lastmod DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def search_multimovies(query: str, limit: int = 20) -> list[dict]:
    """Search MultiMovies via their JSON API. Returns structured results with TMDB metadata."""
    mm_base = DOMAINS.get("multimovies", "https://multimovies.garden")
    search_url = f"{mm_base}/api/search?q={urllib.parse.quote(query)}"
    code, _, body = http_get(search_url)
    if code != 200:
        print(f"  [!] MultiMovies search failed: HTTP {code}")
        return []
    try:
        data = json.loads(body)
    except Exception:
        print(f"  [!] MultiMovies search: invalid JSON response")
        return []
    results = []
    for item in data.get("results", [])[:limit]:
        results.append({
            "id": item.get("id"),
            "title": item.get("title", ""),
            "type": item.get("type", "movie"),
            "year": item.get("year"),
            "rating": item.get("rating"),
            "quality": item.get("quality", ""),
            "poster": item.get("poster", ""),
            "url": item.get("url", ""),
        })
    # Also include categorized results
    for item in data.get("movies", []):
        if not any(r["id"] == item.get("id") for r in results):
            results.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "type": "movie",
                "year": item.get("year"),
                "rating": item.get("rating"),
                "quality": item.get("quality", ""),
                "poster": item.get("poster", ""),
                "url": item.get("url", ""),
            })
    for item in data.get("tv_shows", []):
        if not any(r["id"] == item.get("id") for r in results):
            results.append({
                "id": item.get("id"),
                "title": item.get("title", ""),
                "type": "tv",
                "year": item.get("year"),
                "rating": item.get("rating"),
                "quality": item.get("quality", ""),
                "poster": item.get("poster", ""),
                "url": item.get("url", ""),
            })
    return results


def fetch_multimovies_discover() -> list[dict]:
    """Fetch trending/popular content from MultiMovies discover API."""
    mm_base = DOMAINS.get("multimovies", "https://multimovies.garden")
    disc_url = f"{mm_base}/api/discover"
    code, _, body = http_get(disc_url)
    if code != 200:
        print(f"  [!] MultiMovies discover failed: HTTP {code}")
        return []
    try:
        data = json.loads(body)
    except Exception:
        print(f"  [!] MultiMovies discover: invalid JSON response")
        return []
    items = []
    for item in data.get("items", []):
        items.append({
            "id": item.get("id"),
            "title": item.get("title", ""),
            "type": item.get("type", "movie"),
            "slug": item.get("slug", ""),
            "url": item.get("url", ""),
            "year": item.get("year"),
            "rating": item.get("rating"),
            "quality": item.get("quality", ""),
            "poster": item.get("poster", ""),
            "backdrop": item.get("backdrop", ""),
            "views": item.get("views", 0),
        })
    return items


# ── Metadata Parser Helpers ───────────────────────────────────────────────────

def parse_post_metadata(page_url: str, html: str) -> dict:
    slug = page_url.rstrip("/").split("/")[-1]
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_match.group(1).strip() if title_match else slug

    # Detect year
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    # Detect content type & seasons
    is_series = bool(re.search(r"\b(season|s\d+|episode|series)\b", raw_title, re.IGNORECASE))
    season_m = re.search(r"\b(Season\s*\d+(?:\s*(?:&|-)\s*\d+)?)\b", raw_title, re.IGNORECASE)
    seasons = season_m.group(1) if season_m else None

    if is_series:
        if re.search(r"\b(complete|batch|zip)\b", raw_title, re.IGNORECASE):
            content_type = "complete_season"
        elif re.search(r"\b(s\d+\s*e\d+|episode)\b", raw_title, re.IGNORECASE):
            content_type = "ongoing_season"
        else:
            content_type = "series"
    else:
        content_type = "movie"

    # Clean title
    clean_title = raw_title
    for prefix in ["Download ", "Watch "]:
        if clean_title.startswith(prefix):
            clean_title = clean_title[len(prefix):]
    clean_title = re.sub(r"\s*\|\s*Rogmovies\s+Official.*$", "", clean_title, flags=re.IGNORECASE)
    clean_title = re.sub(r"\s*\|\s*Vegamovies.*$", "", clean_title, flags=re.IGNORECASE)
    clean_title = re.split(r"[:\|{]|\b(480p|720p|1080p|2160p|4K|BluRay|WEB-DL|HDRip)\b", clean_title)[0].strip()

    # 1. Poster URL: Check og:image with base64 encoded TMDB link (?u=...)
    poster_url = None
    og_img = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if og_img:
        raw_og = og_img.group(1).strip()
        if "u=" in raw_og:
            u_part = raw_og.split("u=", 1)[1].split("&")[0]
            try:
                decoded_u = base64.b64decode(u_part).decode("utf-8", errors="ignore")
                if decoded_u.startswith("http"):
                    poster_url = decoded_u
            except Exception:
                pass
        if not poster_url:
            poster_url = raw_og

    if not poster_url:
        tmdb_m = re.search(r'src=["\'](https?://image\.tmdb\.org/t/p/(?:original|w500)/[^"\']+)["\']', html)
        if tmdb_m:
            poster_url = tmdb_m.group(1)

    # 2. Backdrops & Screenshots
    all_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    backdrop_candidates = []
    seen_imgs = set()
    for img in all_imgs:
        img_clean = img.strip()
        if img_clean in seen_imgs or img_clean == poster_url:
            continue
        if any(bad in img_clean.lower() for bad in ["logo", "icon", "badge", "avatar", "button", "nexdrive", "wp-includes"]):
            continue
        if any(good in img_clean for good in ["tmdb.org", "imgbb", "media-amazon", "static-prime"]):
            seen_imgs.add(img_clean)
            backdrop_candidates.append(img_clean)

    backdrop_urls = json.dumps(backdrop_candidates[:8]) if backdrop_candidates else None

    # 3. IMDb Rating
    imdb_m = re.search(r'IMDb(?:\s*Rating)?\s*[:–-]?\s*([0-9.]+(?:\s*/\s*10)?)', html, re.IGNORECASE)
    imdb_rating = imdb_m.group(1).strip() if imdb_m else None

    # 4. Genres
    genres_list = []
    genre_text_m = re.search(r'Genre[s]?\s*[:–-]?\s*([^\n<]+)', html, re.IGNORECASE)
    if genre_text_m:
        raw_g = genre_text_m.group(1).strip()
        for g in re.split(r"[,/|•]", raw_g):
            g_clean = g.strip()
            if g_clean and len(g_clean) > 2 and g_clean not in genres_list:
                genres_list.append(g_clean)

    COMMON_GENRES = ["Action", "Adventure", "Animation", "Biography", "Comedy", "Crime",
                     "Documentary", "Drama", "Family", "Fantasy", "History", "Horror",
                     "Mystery", "Romance", "Sci-Fi", "Sport", "Thriller", "War"]
    for cg in COMMON_GENRES:
        if cg not in genres_list and re.search(rf"\b{cg}\b", raw_title, re.IGNORECASE):
            genres_list.append(cg)

    genres = json.dumps(genres_list) if genres_list else None

    # 5. Synopsis / Storyline
    story_m = re.search(r'(?:Storyline|Synopsis|Plot)\s*[:–-]?\s*(?:<[^>]*>)?\s*([^\n<]+)', html, re.IGNORECASE)
    synopsis = story_m.group(1).strip() if story_m else None
    if synopsis:
        synopsis = re.sub(r'<[^>]+>', '', synopsis).strip()

    # 6. 18+ Content Flag (precise word boundaries on title and slug)
    title_slug_text = f"{raw_title} {slug}"
    is_18_plus = is_adult_title(raw_title, slug)

    # 7. Animation / Anime Flag — the shared rule, not a second copy of the patterns
    is_animated = looks_animated(title_slug_text)

    # 8. Media Classification (Source Site, Industry, Country, Language)
    source_site = "rogmovies" if "rogmovies" in page_url.lower() else "vegamovies"
    cls_meta = classify_media(source_site, raw_title, slug, html)

    return {
        "url": page_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": content_type,
        "seasons": seasons,
        "poster_url": poster_url,
        "backdrop_urls": backdrop_urls,
        "imdb_rating": imdb_rating,
        "genres": genres,
        "synopsis": synopsis,
        "is_18_plus": is_18_plus,
        "is_animated": is_animated,
        "source_site": cls_meta["source_site"],
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
    }


def parse_release_info(nex_title: str) -> dict:
    """
    Extracts quality, codec, audio languages, season, episode, and file size
    from the accurate Nexdrive <title> tag.
    Example: Ghosts of Mars (2001) {Hindi-English} 480p BluRay x264 [470MB] – Nexdrive.fit
    """
    title = re.sub(r"\s*[-–]\s*Nexdrive\.[a-z]+.*$", "", nex_title, flags=re.IGNORECASE).strip()

    # Quality
    qual_m = re.search(r"\b(480p|720p|1080p|2160p|4k)\b", title, re.IGNORECASE)
    quality = qual_m.group(1).lower() if qual_m else "unknown"

    # Codec
    codec_m = re.search(r"\b(x264|x265|hevc|10bit)\b", title, re.IGNORECASE)
    codec = codec_m.group(1).upper() if codec_m else ""

    # Size: e.g. [470MB], [1GB], [200MB/E]
    size_m = re.search(r"\[([0-9.]+\s*(?:MB|GB|mb|gb)(?:/[A-Za-z]+)?)\]", title)
    size = size_m.group(1) if size_m else ""

    # Languages: e.g. {Hindi-English}
    lang_m = re.search(r"\{([^}]+)\}", title)
    languages = lang_m.group(1).strip() if lang_m else ""

    # Season (detect S01, S02, Season 1, Season 2)
    sm = re.search(r"\b(?:S|Season\s*)(\d+)\b", title, re.IGNORECASE)
    season = f"S{int(sm.group(1)):02d}" if sm else None

    # Check batch vs episode list
    is_batch = bool(re.search(r"\b(batch|zip|complete)\w*\b", title, re.IGNORECASE))
    is_ep_list = bool(re.search(r"\[[^\]]*/E\]|\bEpisodes\b", title, re.IGNORECASE))
    if is_batch:
        episode = "Batch"
    else:
        ep_m = re.search(r"\b(E\d+)\b", title, re.IGNORECASE)
        episode = ep_m.group(1).upper() if ep_m else None

    return {
        "release_title": title,
        "quality": quality,
        "codec": codec,
        "size": size,
        "languages": languages,
        "season": season,
        "episode": episode,
        "is_batch": is_batch,
        "is_ep_list": is_ep_list,
    }


# ── Direct Navigators & Link Unwrappers ────────────────────────────────────────

def unwrap_fastdl(fastdl_url: str) -> tuple[str, str, int]:
    """
    Navigates FastDL embed page -> direct Google CDN download link.
    Returns: (final_url, resource_id, is_temporary)
    """
    # Extract canonical resource ID
    m = re.search(r"download=([A-Za-z0-9_-]+)", fastdl_url)
    res_id = m.group(1) if m else fastdl_url.split("/")[-1]

    code, _, html = http_get(fastdl_url)
    if code != 200:
        return fastdl_url, res_id, 0

    # FastDL places the destination link inside var reurl = "..."
    reurl_m = re.search(r'var\s+reurl\s*=\s*["\']([^"\']+)["\']', html)
    if reurl_m:
        raw_reurl = reurl_m.group(1).strip()
        # Check if direct link is embedded in dl.php?link=...
        if "link=" in raw_reurl:
            direct_part = raw_reurl.split("link=", 1)[1]
            direct_url = urllib.parse.unquote(direct_part)
            return direct_url, res_id, 1
        return raw_reurl, res_id, 1

    return fastdl_url, res_id, 0


def unwrap_vcloud(vcloud_url: str) -> list[tuple[str, str, str, int]]:
    """
    Decodes V-Cloud double base64 token and fetches direct server links
    (FSL Cloudflare R2 bucket & HubCloud 10Gbps servers).
    Returns list of: [(source_name, service, final_url, is_temporary)]
    """
    res_id = vcloud_url.rstrip("/").split("/")[-1].split("?")[0]
    code, final_vcloud_url, html = http_get(vcloud_url)
    if code != 200:
        return [("V-Cloud", "vcloud", vcloud_url, 0)]

    # Look for double base64 token script
    # var url = atob(atob('...'));
    b64_m = re.search(r"atob\(\s*atob\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\)", html)
    if not b64_m:
        return [("V-Cloud", "vcloud", final_vcloud_url, 0)]

    try:
        token_str = b64_m.group(1)
        d1 = base64.b64decode(token_str).decode("utf-8", errors="ignore")
        d2 = base64.b64decode(d1).decode("utf-8", errors="ignore")
        token_url = d2
    except Exception:
        return [("V-Cloud", "vcloud", final_vcloud_url, 0)]

    # Fetch token URL to get actual server buttons
    t_code, _, t_html = http_get(token_url)
    if t_code != 200:
        return [("V-Cloud (Token)", "vcloud", token_url, 0)]

    resolved = []
    # Search for server links
    # 1. Cloudflare R2 storage / FSL Server
    r2_links = re.findall(r'href=[\"\'](https?://[^\s\"\']*r2\.dev[^\s\"\']*)[\"\']', t_html)
    for l in r2_links:
        resolved.append(("V-Cloud [FSL Cloudflare R2]", "fsl_r2", l, 0))

    # 2. HubCloud 10Gbps server & Google CDN
    hub_links = re.findall(r'href=[\"\'](https?://[^\s\"\']*hubcloud\.[^\s\"\']+)[\"\']', t_html)
    for l in hub_links:
        direct_url, svc, is_temp = unwrap_hubcloud(l)
        if svc == "google_cdn":
            resolved.append(("V-Cloud [Google Direct CDN]", "google_cdn", direct_url, is_temp))
        else:
            resolved.append(("V-Cloud [HubCloud 10Gbps]", "hubcloud", l, 0))

    if not resolved:
        resolved.append(("V-Cloud (Resolved)", "vcloud", token_url, 0))

    return resolved


def unwrap_hubcloud(hub_url: str) -> tuple[str, str, int]:
    """
    Follows HubCloud GPDL link to direct Google CDN URL (video-downloads.googleusercontent.com)
    or falls back to the original HubCloud link.
    """
    if "gpdl" in hub_url:
        try:
            code, final_u, _ = http_get(hub_url, timeout=5, max_retries=1)
            if "link=" in final_u:
                direct = urllib.parse.unquote(final_u.split("link=", 1)[1])
                return direct, "google_cdn", 1
            elif "video-downloads.googleusercontent.com" in final_u:
                return final_u, "google_cdn", 1
        except Exception:
            pass
    return hub_url, "hubcloud", 0


def unwrap_vegadrive(vegadrive_url: str) -> tuple[str, str, int]:
    """
    Extracts canonical ID and maps to direct 10Gbps stream URL (/d/<id>/skyd).
    """
    m = re.search(r"/(?:s|d)/([A-Za-z0-9_-]+)", vegadrive_url)
    res_id = m.group(1) if m else vegadrive_url.split("/")[-1]
    # Fast direct endpoint on Vegadrive
    direct_url = f"https://one.vegadrive.me/d/{res_id}/skyd"
    return direct_url, res_id, 0


def unwrap_filepress(filepress_url: str) -> tuple[str, str, int]:
    """
    Extracts canonical file ID from FileBee / FilePress URL.
    """
    m = re.search(r"/file/([A-Za-z0-9_-]+)", filepress_url)
    res_id = m.group(1) if m else filepress_url.split("/")[-1]
    return filepress_url, res_id, 0


def unwrap_pixeldrain(pixeldrain_url: str) -> tuple[str, str, int]:
    """
    Unwraps a PixelDrain viewing URL into a high-speed direct CDN streaming URL.
    Input : https://pixeldrain.com/u/<FILE_ID>
    Output: https://pixeldrain.com/api/file/<FILE_ID>, <FILE_ID>, 0
    """
    m = re.search(r"/(?:u|d|api/file)/([A-Za-z0-9_-]+)", pixeldrain_url)
    if m:
        file_id = m.group(1)
        direct_url = f"https://pixeldrain.com/api/file/{file_id}"
        return direct_url, file_id, 0
    return pixeldrain_url, pixeldrain_url.rstrip("/").split("/")[-1], 0


#: A path ending in one of these is media ExoPlayer/`ffprobe` can open directly.
#: Query strings are stripped before the test, so `…/movie.mkv?token=…` counts.
_MEDIA_SUFFIXES = (
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".flv", ".ts",
    ".m3u8", ".mpd", ".mp3", ".m4a", ".aac",
)
#: Hosts whose whole purpose is to answer with bytes, even when the path has no
#: extension (a signed R2 object, Google's download endpoint, PixelDrain's API).
_DIRECT_MEDIA_HOSTS = frozenset({
    "video-downloads.googleusercontent.com",
    "drive.usercontent.google.com",
    "storage.direct-cloud.org",
    "firebasestorage.googleapis.com",
})
_DIRECT_MEDIA_HOST_SUFFIXES = (".r2.cloudflarestorage.com", ".r2.dev")
_DIRECT_MEDIA_MARKERS = ("pixeldrain.com/api/file/",)
#: Hosts that serve an HTML landing/embed page whose only value is the link it
#: hides. Returning one of these as a "stream" is what this pair of helpers is
#: here to prevent.
_BRIDGE_HOST_MARKERS = (
    "nexdrive", "vcloud", "vegadrive", "linkszilla", "greenmotors",
    "mobilejsr", "10moviesz",
    # Both packer hosts answer with an HTML page that holds a signed media URL;
    # only `importers/host_resolvers.py` may turn one into a stream, and a failed
    # attempt must therefore be refused in the v1 contract too.
    "mxdrop", "pkembed",
)


def is_direct_media_url(url: str) -> bool:
    """Whether ``url`` is already an endpoint that serves media bytes.

    Deliberately evidence-based: an extension, a known byte-serving host, or the
    PixelDrain API marker. An unknown URL is *not* called direct here; callers
    that need to tell "unknown" from "known bridge" use :func:`is_bridge_url`,
    because refusing every unrecognised host would break the long tail of CDNs
    this ledger already holds.
    """
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if path.endswith(_MEDIA_SUFFIXES):
        return True
    if host in _DIRECT_MEDIA_HOSTS:
        return True
    if any(host.endswith(suffix) for suffix in _DIRECT_MEDIA_HOST_SUFFIXES):
        return True
    low = str(url).lower()
    return any(marker in low for marker in _DIRECT_MEDIA_MARKERS)


def is_bridge_url(url: str) -> bool:
    """Whether ``url`` is a known HTML landing/embed page, not playable media.

    Used in two places in :func:`resolve_live_source`: a cached `final_url` that
    is a bridge is refreshed instead of served (a stored landing page would make
    ExoPlayer show an error where a video should be), and a re-resolve that still
    hands back a bridge is treated as a failure rather than a stream.
    """
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()
    if "hubcloud" in host:
        # `pixel.hubcloud…` is the 10Gbps byte server; everything else on a
        # hubcloud host is the `/drive/<id>` landing page or a gpdl redirector.
        return not host.startswith("pixel.")
    if "gamerxyt" in host:
        return "link=" not in query          # dl.php?link=<direct> unwraps
    if "fastdl" in host:
        return "embed" in path or "download=" in query or path.endswith(".php")
    if "gdflix" in host:
        return "/file/" in path or path in ("", "/")
    if "pixeldrain" in host:
        return "/api/file/" not in path
    return any(marker in host for marker in _BRIDGE_HOST_MARKERS)


def unwrap_gdflix(gdflix_url: str) -> tuple[str, str, int]:
    """GDFlix `file/<ID>` page → the direct Google endpoint behind it.

    GDFlix is a Google Drive proxy: the `/file/<id>` address is an HTML landing
    page and playing it in ExoPlayer produces an error, not a video. The page
    carries either an embedded `video-downloads.googleusercontent.com` URL or a
    Drive file id; both are unwrapped here. When neither is present the landing
    page is returned unchanged and the caller's bridge guard refuses it.
    """
    res_id = gdflix_url.rstrip("/").split("/")[-1].split("?")[0]
    try:
        code, _final_u, page = http_get(gdflix_url, timeout=10)
    except Exception:
        return gdflix_url, res_id, 0
    if code != 200 or not page:
        return gdflix_url, res_id, 0

    direct = re.search(
        r'https?://video-downloads\.googleusercontent\.com/[^\s"\'<>\\]+', page)
    if direct:
        return html_module.unescape(direct.group(0)), res_id, 1

    for pattern in (
        r'drive\.google\.com/file/d/([A-Za-z0-9_-]{20,})',
        r'drive\.google\.com/uc\?(?:[^"\'<>]*&)?id=([A-Za-z0-9_-]{20,})',
        r'drive\.usercontent\.google\.com/download\?(?:[^"\'<>]*&)?id=([A-Za-z0-9_-]{20,})',
        r'"fileId"\s*:\s*"([A-Za-z0-9_-]{20,})"',
        r'data-id=["\']([A-Za-z0-9_-]{20,})["\']',
    ):
        match = re.search(pattern, page)
        if match:
            file_id = match.group(1)
            return (f"https://drive.usercontent.google.com/download"
                    f"?id={file_id}&export=download"), res_id, 1
    return gdflix_url, res_id, 0


def unwrap_hubcloud_drive(hub_drive_url: str) -> list[dict]:
    """
    Unwraps HubCloud Drive URL (e.g. https://hubcloud.ist/drive/<ID>)
    via gamerxyt.com/hubcloud.php directly to:
    - Cloudflare R2 bucket signed stream (HTTP 206 resumable)
    - 10Gbps Server
    - PixelDrain server
    Returns list of source dicts.
    """
    results = []
    code, final_u, html = http_get(hub_drive_url, timeout=10)
    if code != 200 or not html:
        return [{
            "source_name": "HubCloud Drive",
            "service": "hubcloud",
            "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
            "source_url": hub_drive_url,
            "final_url": hub_drive_url,
            "is_temporary": 0,
        }]

    gx_m = re.search(r'href=["\'](https?://gamerxyt\.com/hubcloud\.php\?[^"\']+)["\']', html)
    if not gx_m:
        direct_anchors = re.findall(r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', html, re.S)
        for h, t in direct_anchors:
            if "r2.cloudflarestorage.com" in h:
                results.append({
                    "source_name": "⚡ HubCloud [FSL Cloudflare R2]",
                    "service": "fsl_r2",
                    "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
                    "source_url": hub_drive_url,
                    "final_url": h,
                    "is_temporary": 1,
                })
        return results or [{
            "source_name": "HubCloud Drive",
            "service": "hubcloud",
            "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
            "source_url": hub_drive_url,
            "final_url": hub_drive_url,
            "is_temporary": 0,
        }]

    gx_url = gx_m.group(1).replace("&amp;", "&")
    gx_code, _, gx_html = http_get(gx_url, timeout=12)
    if gx_code != 200 or not gx_html:
        return [{
            "source_name": "HubCloud Drive",
            "service": "hubcloud",
            "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
            "source_url": hub_drive_url,
            "final_url": gx_url,
            "is_temporary": 0,
        }]

    anchors = re.findall(r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', gx_html, re.S)
    for href, text in anchors:
        clean_t = re.sub(r'<[^>]+>', '', text).strip()
        h_lower = href.lower()
        if "r2.cloudflarestorage.com" in h_lower or "fsl server" in clean_t.lower():
            results.append({
                "source_name": "⚡ HubCloud [FSL Cloudflare R2]",
                "service": "fsl_r2",
                "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
                "source_url": hub_drive_url,
                "final_url": href,
                "is_temporary": 1,
            })
        elif "pixel.hubcloud" in h_lower or "10gbps" in clean_t.lower():
            results.append({
                "source_name": "⚡ HubCloud [10Gbps Fast Server]",
                "service": "hubcloud_10g",
                "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
                "source_url": hub_drive_url,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "pixeldrain" in h_lower:
            direct_pd, pd_id, _ = unwrap_pixeldrain(href)
            results.append({
                "source_name": "⚡ PixelDrain [Direct CDN]",
                "service": "pixeldrain",
                "resource_id": pd_id,
                "source_url": href,
                "final_url": direct_pd,
                "is_temporary": 0,
            })

    if not results:
        results.append({
            "source_name": "HubCloud Drive",
            "service": "hubcloud",
            "resource_id": hub_drive_url.rstrip("/").split("/")[-1],
            "source_url": hub_drive_url,
            "final_url": hub_drive_url,
            "is_temporary": 0,
        })

    return results


def unwrap_linkszilla(lz_url: str) -> list[dict]:
    """
    Unwraps LinksZilla bridge page (e.g. https://secure.linkszilla.top/view/<ID>)
    Extracts all mirror download links (HubCloud Drive, Direct-Cloud, GDFlix, Gofile, 1fichier, etc.)
    """
    results = []
    code, _, html = http_get(lz_url, timeout=10)
    if code != 200 or not html:
        return [{
            "source_name": "LinksZilla Bridge",
            "service": "linkszilla",
            "resource_id": lz_url.rstrip("/").split("/")[-1],
            "source_url": lz_url,
            "final_url": lz_url,
            "is_temporary": 0,
        }]

    anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S)
    for href, text in anchors:
        clean_t = re.sub(r'<[^>]+>', '', text).strip()
        h_lower = href.lower()
        if any(bad in h_lower for bad in ["javascript", "#", "linkszilla.top/view", "/login", "/signup", "/contact", "/terms"]):
            continue

        if "hubcloud." in h_lower:
            results.extend(unwrap_hubcloud_drive(href))
        elif "direct-cloud." in h_lower:
            cdn_u, svc, is_tmp = unwrap_direct_cloud(href)
            results.append({
                "source_name": "⚡ Direct-Cloud [High Speed]",
                "service": "direct_cloud",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": cdn_u,
                "is_temporary": is_tmp,
            })
        elif "gdflix." in h_lower:
            results.append({
                "source_name": "⚡ GDFlix Mirror",
                "service": "gdflix",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "gofile.io" in h_lower:
            results.append({
                "source_name": "⚡ Gofile [Direct Mirror]",
                "service": "gofile",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "1fichier.com" in h_lower:
            results.append({
                "source_name": "⚡ 1fichier Cloud",
                "service": "1fichier",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "clicknupload" in h_lower:
            results.append({
                "source_name": "⚡ ClicknUpload",
                "service": "clicknupload",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "megaup.net" in h_lower:
            results.append({
                "source_name": "⚡ MegaUp Mirror",
                "service": "megaup",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "watch-online" in h_lower:
            results.append({
                "source_name": "▶ Watch Online Stream",
                "service": "stream",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        else:
            domain = urllib.parse.urlparse(href).netloc.replace("www.", "")
            if domain:
                results.append({
                    "source_name": f"🌐 {clean_t or domain}",
                    "service": domain.split(".")[0],
                    "resource_id": href.rstrip("/").split("/")[-1],
                    "source_url": href,
                    "final_url": href,
                    "is_temporary": 0,
                })

    if not results:
        results.append({
            "source_name": "LinksZilla Bridge",
            "service": "linkszilla",
            "resource_id": lz_url.rstrip("/").split("/")[-1],
            "source_url": lz_url,
            "final_url": lz_url,
            "is_temporary": 0,
        })

    return results


def unwrap_direct_cloud(direct_cloud_url: str, timeout: int = 10) -> tuple[str, str, int]:
    """
    Unwraps direct-cloud bridge URL (e.g. https://dl.direct-cloud.top/d/<id>
    or https://storage.direct-cloud.org/d/<uid>) to its high-speed Google CDN
    direct stream link using session cookie-aware DOWNLOAD_GENERATE action negotiation.
    Returns: (final_stream_or_landing_url, service_name, is_temporary)
    """
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=SSL_CONTEXT)
        )
        req = urllib.request.Request(direct_cloud_url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with opener.open(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            landing_u = resp.geturl()

        m_uid = re.search(r'data-uid=["\']([^"\']+)["\']', html)
        m_token = re.search(r'data-token=["\']([^"\']+)["\']', html)
        if not m_uid or not m_token:
            return landing_u, "direct_cloud", 0

        uid = m_uid.group(1)
        token = m_token.group(1)
        action_url = "https://storage.direct-cloud.org/action"
        post_payload = json.dumps({
            "type": "DOWNLOAD_GENERATE",
            "payload": {"uid": uid, "access_token": token}
        }).encode("utf-8")

        post_req = urllib.request.Request(
            action_url,
            data=post_payload,
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Requested-With": "xmlhttprequest",
                "Origin": "https://storage.direct-cloud.org",
                "Referer": landing_u,
                "Cache-Control": "no-cache",
                "User-Agent": USER_AGENT,
            }
        )
        with opener.open(post_req, timeout=timeout) as post_resp:
            data = json.loads(post_resp.read().decode("utf-8"))
            if data.get("status") and data.get("download_url"):
                return data["download_url"], "google_cdn", 1
        return landing_u, "direct_cloud", 0
    except Exception:
        return direct_cloud_url, "direct_cloud", 0


def decode_greenmotors_payload(payload_b64: str) -> str | None:
    """
    Decodes the 4-layer obfuscated greenmotors payload:
    b64 -> b64 -> rot_13 -> b64 -> JSON {'o': b64_dest} -> b64 -> dest_url
    """
    try:
        p1 = base64.b64decode(payload_b64).decode("utf-8", errors="replace")
        p2 = base64.b64decode(p1).decode("utf-8", errors="replace")
        p3 = codecs.decode(p2, "rot_13")
        p4 = base64.b64decode(p3).decode("utf-8", errors="replace")
        data = json.loads(p4)
        if isinstance(data, dict) and "o" in data:
            return base64.b64decode(data["o"]).decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def unwrap_greenmotors(greenmotors_url: str, timeout: int = 10) -> list[dict]:
    """
    Unwraps HDHub4u greenmotors bridge (greenmotors.cc / greenmotors.club / etc.)
    by unpacking the multi-layer base64/rot13 payload and following the destination
    hublink archive to extract live HubCloud / PixelDrain / Direct-Cloud direct streams.
    """
    results = []
    resource_id = greenmotors_url.split("?id=")[-1][:24] if "?id=" in greenmotors_url else greenmotors_url.rstrip("/").split("/")[-1]

    code, fin_u, html = http_get(greenmotors_url, timeout=timeout)
    if code != 200 or not html:
        return [{
            "source_name": "⚡ HDHub4u Bridge",
            "service": "greenmotors",
            "resource_id": resource_id,
            "source_url": greenmotors_url,
            "final_url": greenmotors_url,
            "is_temporary": 0,
        }]

    m_payload = re.search(r's\([\'"]o[\'"],\s*[\'"]([A-Za-z0-9+/=]+)[\'"]', html)
    dest_url = None
    if m_payload:
        dest_url = decode_greenmotors_payload(m_payload.group(1))

    # Fallback to final URL if already redirected
    if not dest_url and ("hblinks." in fin_u or "/archives/" in fin_u):
        dest_url = fin_u

    if dest_url:
        dl = dest_url.lower()
        if "hblinks." in dl or "/archives/" in dl:
            c_hb, _, html_hb = http_get(dest_url, timeout=timeout)
            if c_hb == 200 and html_hb:
                anchors = re.findall(r'<a[^>]+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>', html_hb, re.S)
                for href, text in anchors:
                    clean_t = re.sub(r'<[^>]+>', '', text).strip()
                    hl = href.lower()
                    if "hubcloud." in hl:
                        results.extend(unwrap_hubcloud_drive(href))
                    elif "pixeldrain.com" in hl:
                        pdu, pd_id, is_tmp = unwrap_pixeldrain(href)
                        results.append({
                            "source_name": "⚡ PixelDrain [CDN]",
                            "service": "pixeldrain",
                            "resource_id": pd_id,
                            "source_url": href,
                            "final_url": pdu,
                            "is_temporary": is_tmp,
                        })
                    elif "direct-cloud." in hl:
                        cdn_u, svc, is_tmp = unwrap_direct_cloud(href)
                        results.append({
                            "source_name": "⚡ Direct-Cloud [High Speed]",
                            "service": "direct_cloud",
                            "resource_id": href.rstrip("/").split("/")[-1],
                            "source_url": href,
                            "final_url": cdn_u,
                            "is_temporary": is_tmp,
                        })
                    elif "fastdl." in hl:
                        fdu, svc, is_tmp = unwrap_fastdl(href)
                        results.append({
                            "source_name": f"⚡ FastDL [{svc.upper()}]",
                            "service": svc,
                            "resource_id": href.rstrip("/").split("/")[-1],
                            "source_url": href,
                            "final_url": fdu,
                            "is_temporary": is_tmp,
                        })
                    elif "hubdrive." in hl:
                        results.append({
                            "source_name": "⚡ HubDrive Mirror",
                            "service": "hubdrive",
                            "resource_id": href.rstrip("/").split("/")[-1],
                            "source_url": href,
                            "final_url": href,
                            "is_temporary": 0,
                        })

    if not results:
        results.append({
            "source_name": "⚡ HDHub4u Bridge",
            "service": "greenmotors",
            "resource_id": resource_id,
            "source_url": greenmotors_url,
            "final_url": dest_url or greenmotors_url,
            "is_temporary": 0,
        })

    return results


def fetch_kmhd_bridge(file_id: str, token: str = "") -> list[dict]:
    """
    Directly queries KatMovieHD backend API (https://api.dandndn.one/api/v1/file/<file_id>)
    with JWT token to retrieve direct HubDrive, GDFlix, KatDrive, 1fichier, SendCM mirrors.
    """
    results = []
    if not token:
        token = DOMAINS.get("kmhd_token", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTgwNzQ4NDIzMywiaWF0IjoxNzkxNzIyNzgxfQ.35zU5UqB-EwO8_8kYlK-3r1M69tH-0hQ58MhQ0g-5wU")

    api_url = f"https://api.dandndn.one/api/v1/file/{file_id}"
    req = urllib.request.Request(api_url, headers={
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {token}",
        "Origin": "https://links.kmhd.me",
        "Referer": "https://links.kmhd.me/",
    })
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            upload_links = data.get("upload_links", {})
            hub_res = upload_links.get("hubdrive_res")
            if hub_res and hub_res != "None":
                hub_url = f"https://hubcloud.ist/drive/{hub_res}"
                results.extend(unwrap_hubcloud_drive(hub_url))

            gd_res = upload_links.get("gdflix_res")
            if gd_res and gd_res != "None":
                results.append({
                    "source_name": "⚡ GDFlix [KatMirror]",
                    "service": "gdflix",
                    "resource_id": gd_res,
                    "source_url": f"https://new5.gdflix.io/file/{gd_res}",
                    "final_url": f"https://new5.gdflix.io/file/{gd_res}",
                    "is_temporary": 0,
                })

            kat_res = upload_links.get("katdrive_res")
            if kat_res and kat_res != "None":
                results.append({
                    "source_name": "⚡ KatDrive [Ultra Speed]",
                    "service": "katdrive",
                    "resource_id": kat_res,
                    "source_url": f"https://katdrive.net/file/{kat_res}",
                    "final_url": f"https://katdrive.net/file/{kat_res}",
                    "is_temporary": 0,
                })

            fc_res = upload_links.get("fichier_res")
            if fc_res and fc_res != "None":
                results.append({
                    "source_name": "⚡ 1fichier Cloud",
                    "service": "1fichier",
                    "resource_id": fc_res,
                    "source_url": f"https://1fichier.com/{fc_res}",
                    "final_url": f"https://1fichier.com/{fc_res}",
                    "is_temporary": 0,
                })

            send_res = upload_links.get("sendcm_res")
            if send_res and send_res != "None":
                results.append({
                    "source_name": "⚡ Send.cm Mirror",
                    "service": "sendcm",
                    "resource_id": send_res,
                    "source_url": f"https://send.cm/{send_res}",
                    "final_url": f"https://send.cm/{send_res}",
                    "is_temporary": 0,
                })
    except Exception:
        results.append({
            "source_name": "KMHD Bridge",
            "service": "kmhd",
            "resource_id": file_id,
            "source_url": f"https://links.kmhd.me/file/{file_id}",
            "final_url": f"https://links.kmhd.me/file/{file_id}",
            "is_temporary": 0,
        })

    return results


def unwrap_mobilejsr(jsr_url: str) -> list[dict]:
    """
    Unwraps 7StarHD / 10xflix MobileJSR bridge URL.
    Uses session cookie and CSRF token negotiation to unlock all direct streaming mirrors.
    """
    results = []
    html = ""
    try:
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=SSL_CONTEXT),
        )
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": jsr_url,
            "Origin": "https://mobilejsr.com",
        }
        # 1. GET initial landing page
        req = urllib.request.Request(jsr_url, headers=headers)
        res = opener.open(req, timeout=12)
        html = res.read().decode("utf-8", errors="ignore")

        # 2. Check for CSRF unlock form
        csrf_m = re.search(r'name=["\']_csrf["\']\s+value=["\']([^"\']+)["\']', html)
        if csrf_m:
            csrf_token = csrf_m.group(1)
            post_data = urllib.parse.urlencode({"_csrf": csrf_token}).encode("utf-8")
            req_post = urllib.request.Request(jsr_url, data=post_data, headers=headers)
            res_post = opener.open(req_post, timeout=12)
            html = res_post.read().decode("utf-8", errors="ignore")
    except Exception:
        # Fall back to simple HTTP GET if session negotiation fails
        code, fin_u, get_html = http_get(jsr_url, timeout=10)
        if code == 200 and get_html:
            html = get_html

    if not html:
        return [{
            "source_name": "MobileJSR Bridge",
            "service": "mobilejsr",
            "resource_id": jsr_url.rstrip("/").split("/")[-1],
            "source_url": jsr_url,
            "final_url": jsr_url,
            "is_temporary": 0,
        }]

    anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)
    for href, text in anchors:
        clean_t = re.sub(r'<[^>]+>', '', text).strip()
        h_lower = href.lower()
        if any(bad in h_lower for bad in [
            "javascript", "#", "/register", "/login", "/money", "/faqs", "/contact",
            "/page/", "/save/", "is.gd", "antiblock.org", "favicon"
        ]):
            continue
        if "hubcloud" in h_lower:
            results.extend(unwrap_hubcloud_drive(href))
        elif "hubdrive" in h_lower:
            results.append({
                "source_name": "⚡ HubDrive [Cloud]",
                "service": "hubdrive",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "filepress" in h_lower or "filebee" in h_lower:
            u_fp, fp_id, is_tmp = unwrap_filepress(href)
            results.append({
                "source_name": "⚡ FilePress [Google Drive]",
                "service": "filepress",
                "resource_id": fp_id,
                "source_url": href,
                "final_url": u_fp,
                "is_temporary": is_tmp,
            })
        elif "pixeldrain" in h_lower:
            u_pd, pd_id, _ = unwrap_pixeldrain(href)
            results.append({
                "source_name": "⚡ PixelDrain [Direct CDN]",
                "service": "pixeldrain",
                "resource_id": pd_id,
                "source_url": href,
                "final_url": u_pd,
                "is_temporary": 0,
            })
        elif "1fichier" in h_lower:
            results.append({
                "source_name": "⚡ 1fichier [High-Speed]",
                "service": "1fichier",
                "resource_id": href.rstrip("/").split("/")[-1].split("?")[0],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "gofile" in h_lower:
            results.append({
                "source_name": "⚡ GoFile [Cloud]",
                "service": "gofile",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "streamtape" in h_lower:
            results.append({
                "source_name": "▶ Streamtape [Web Player]",
                "service": "streamtape",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif "voe.sx" in h_lower or "/v/" in h_lower:
            results.append({
                "source_name": "▶ Voe [Stream Player]",
                "service": "voe",
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })
        elif href.startswith("http"):
            domain = urllib.parse.urlparse(href).netloc.replace("www.", "")
            results.append({
                "source_name": f"⚡ {clean_t or domain}",
                "service": domain.split(".")[0],
                "resource_id": href.rstrip("/").split("/")[-1],
                "source_url": href,
                "final_url": href,
                "is_temporary": 0,
            })

    if not results:
        results.append({
            "source_name": "MobileJSR Bridge",
            "service": "mobilejsr",
            "resource_id": jsr_url.rstrip("/").split("/")[-1],
            "source_url": jsr_url,
            "final_url": jsr_url,
            "is_temporary": 0,
        })
    return results



def extract_post_data_ssrmovies(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and LinksZilla releases from SSRMovies.
    """
    slug = post_url.rstrip("/").split("/")[-1]
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_m.group(1).split(" – SSRmovies")[0].split(" | ")[0].strip() if title_m else slug

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org).*$", "", raw_title, flags=re.IGNORECASE).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    tmdb_m = re.search(r'src=["\'](https?://image\.tmdb\.org/t/p/[^"\']+)["\']', html)
    if tmdb_m:
        poster_url = tmdb_m.group(1)
    else:
        og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if og_m:
            poster_url = og_m.group(1)

    cls_meta = classify_media("ssrmovies", raw_title, slug, html)

    lz_links = list(dict.fromkeys(re.findall(r'href=["\'](https?://secure\.linkszilla\.top/view/[a-zA-Z0-9_\-]+)["\']', html)))
    if verbose:
        print(f"    [SSRmovies] Found {len(lz_links)} LinksZilla releases for: {clean_title}")
    # Cap to top 12 major releases to prevent hanging on sports/WWE posts with 100+ links
    lz_links = lz_links[:12]

    releases = []
    for idx, lz_url in enumerate(lz_links, 1):
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', html[max(0, html.find(lz_url)-300):html.find(lz_url)+200], re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"

        rel_title = f"{clean_title} ({year or ''}) {qual.upper()} WEB-DL"
        sources = unwrap_linkszilla(lz_url)
        releases.append({
            "release_title": rel_title,
            "quality": qual,
            "codec": "x264",
            "size": "",
            "languages": cls_meta["language"],
            "season": None,
            "episode": None,
            "intermediate_url": lz_url,
            "source_site": "ssrmovies",
            "sources": sources,
        })

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "movie",
        "seasons": None,
        "poster_url": poster_url,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": json.dumps(["Action", "Drama"]) if "dual" in raw_title.lower() else None,
        "synopsis": None,
        "is_18_plus": 0,
        "is_animated": 0,
        "source_site": "ssrmovies",
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
        "canonical_key": canonical_key,
        "releases": releases,
    }


def extract_post_data_katmoviehd(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and KMHD API releases from KatMovieHD.
    """
    slug = post_url.rstrip("/").split("/")[-1]
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_m.group(1).split(" | ")[0].strip() if title_m else slug

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"^Download\s+", "", raw_title, flags=re.I)
    clean_title = re.sub(r"\s*aka\s+.*$", "", clean_title, flags=re.I)
    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org).*$", "", clean_title, flags=re.IGNORECASE).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    tmdb_m = re.search(r'https?://image\.tmdb\.org/t/p/(?:original|w500)/[a-zA-Z0-9_\-\.]+\.jpg', html)
    if tmdb_m:
        poster_url = tmdb_m.group(0)

    idx = html.find("post_content")
    content_area = html[idx:idx+35000].replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n') if idx != -1 else html

    imdb_m = re.search(r'IMDb(?:\s*Rating)?\s*[:-]?\s*([0-9.]+)', content_area, re.I)
    imdb_rating = f"{imdb_m.group(1)}/10" if imdb_m else None

    cls_meta = classify_media("katmoviehd", raw_title, slug, content_area)

    kmhd_files = list(dict.fromkeys(re.findall(r'href=["\'](https?://links\.kmhd\.me/file/([a-zA-Z0-9_\-]+))["\']', content_area)))
    if verbose:
        print(f"    [KatMovieHD] Found {len(kmhd_files)} KMHD releases for: {clean_title}")

    tok_m = re.search(r'"PUBLIC_TOKEN":"([^"]+)"', html)
    token = tok_m.group(1) if tok_m else ""

    releases = []
    for full_u, fid in kmhd_files:
        api_u = f"https://api.dandndn.one/api/v1/file/{fid}"
        req_api = urllib.request.Request(api_u, headers={
            'User-Agent': USER_AGENT,
            'Authorization': f'Bearer {token or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTgwNzQ4NDIzMywiaWF0IjoxNzkxNzIyNzgxfQ.35zU5UqB-EwO8_8kYlK-3r1M69tH-0hQ58MhQ0g-5wU"}',
            'Origin': 'https://links.kmhd.me'
        })
        fname = fid
        fsize_bytes = 0
        try:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req_api, context=ctx, timeout=8) as r_api:
                d_api = json.loads(r_api.read().decode('utf-8'))
                fname = d_api.get("name") or fid
                fsize_bytes = d_api.get("size") or 0
        except Exception:
            pass

        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', fname, re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"

        size_label = f"{round(fsize_bytes / (1024*1024), 1)}MB" if fsize_bytes else ""
        if fsize_bytes > 1024*1024*1024:
            size_label = f"{round(fsize_bytes / (1024*1024*1024), 2)}GB"

        sources = fetch_kmhd_bridge(fid, token)
        releases.append({
            "release_title": fname.replace(".mkv", "").replace(" mkv", ""),
            "quality": qual,
            "codec": "HEVC" if "x265" in fname.lower() or "hevc" in fname.lower() else "x264",
            "size": size_label,
            "languages": cls_meta["language"],
            "season": None,
            "episode": None,
            "intermediate_url": full_u,
            "source_site": "katmoviehd",
            "sources": sources,
        })

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "movie",
        "seasons": None,
        "poster_url": poster_url,
        "backdrop_urls": None,
        "imdb_rating": imdb_rating,
        "genres": json.dumps(["Action", "Adventure"]) if "action" in content_area.lower() else None,
        "synopsis": None,
        "is_18_plus": 0,
        "is_animated": 1 if "animation" in content_area.lower() else 0,
        "source_site": "katmoviehd",
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
        "canonical_key": canonical_key,
        "releases": releases,
    }


def extract_post_data_7starhd(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and MobileJSR releases from 7StarHD.
    """
    slug = post_url.rstrip("/").split("/")[-1]
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if h1_m:
        raw_title = re.sub(r"<[^>]+>", " ", h1_m.group(1)).strip()
        raw_title = re.sub(r"&#[xX]?[0-9a-fA-F]+;", "", raw_title)
        raw_title = html_module.unescape(raw_title).strip()
        raw_title = re.sub(r"[\uE000-\uF8FF]", "", raw_title).strip()
        raw_title = re.sub(r"\s+", " ", raw_title)
    else:
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        t_text = title_m.group(1).split(" | 7StarHD")[0].strip() if title_m else ""
        raw_title = t_text if t_text and t_text.lower() != "7starhd" else slug.replace("-", " ").title()

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org).*$", "", raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if og_m:
        poster_url = og_m.group(1)

    cls_meta = classify_media("7starhd", raw_title, slug, html)

    jsr_links = list(dict.fromkeys(re.findall(r'href=["\'](https?://mobilejsr\.com/view/[a-zA-Z0-9_\-]+)["\']', html)))
    if verbose:
        print(f"    [7StarHD] Found {len(jsr_links)} MobileJSR releases for: {clean_title}")

    releases = []
    for idx, jsr_u in enumerate(jsr_links, 1):
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', html[max(0, html.find(jsr_u)-200):html.find(jsr_u)+150], re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"

        rel_title = f"{clean_title} ({year or ''}) {qual.upper()} HDRip"
        sources = unwrap_mobilejsr(jsr_u)
        releases.append({
            "release_title": rel_title,
            "quality": qual,
            "codec": "x264",
            "size": "",
            "languages": cls_meta["language"],
            "season": None,
            "episode": None,
            "intermediate_url": jsr_u,
            "source_site": "7starhd",
            "sources": sources,
        })

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "movie",
        "seasons": None,
        "poster_url": poster_url,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": None,
        "synopsis": None,
        "is_18_plus": 0,
        "is_animated": 0,
        "source_site": "7starhd",
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
        "canonical_key": canonical_key,
        "releases": releases,
    }


def extract_post_data_10xflix(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and MobileJSR releases from 10xflix.
    Specializes in WWE weekly events, PLEs, and movies.
    """
    slug = post_url.rstrip("/").split("/")[-1]
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if h1_m:
        raw_title = re.sub(r"<[^>]+>", " ", h1_m.group(1)).strip()
        raw_title = re.sub(r"&#[xX]?[0-9a-fA-F]+;", "", raw_title)
        raw_title = html_module.unescape(raw_title).strip()
        raw_title = re.sub(r"[\uE000-\uF8FF]", "", raw_title).strip()
        raw_title = re.sub(r"\s+", " ", raw_title)
    else:
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        t_text = title_m.group(1).split("| 10xflix")[0].strip() if title_m else ""
        raw_title = t_text if t_text and t_text.lower() != "10xflix" else slug.replace("-", " ").title()

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org|full show|full movie).*$", "", raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if og_m:
        poster_url = og_m.group(1)
    else:
        img_m = re.search(r'<img[^>]+src=[\'"](https://blogger\.googleusercontent\.com/[^\'"]+)[\'"]', html)
        if img_m:
            poster_url = img_m.group(1)

    cls_meta = classify_media("10xflix", raw_title, slug, html)
    is_wwe = bool(re.search(r"\b(wwe|smackdown|raw|nxt|wrestlemania|summerslam|royal rumble|ple|ppv|aew)\b", slug.lower()))
    if is_wwe:
        cls_meta["industry"] = "WWE / Wrestling"

    jsr_links = list(dict.fromkeys(re.findall(r'href=["\'](https?://mobilejsr\.com/view/[a-zA-Z0-9_\-]+)["\']', html)))
    if verbose:
        print(f"    [10xflix] Found {len(jsr_links)} MobileJSR releases for: {clean_title}")

    releases = []
    for idx, jsr_u in enumerate(jsr_links, 1):
        idx_pos = html.find(jsr_u)
        nearby_html = html[max(0, idx_pos-100):min(len(html), idx_pos+250)]
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', nearby_html, re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"
        size_m = re.search(r'\[([0-9\.]+\s*(?:GB|MB))\]', nearby_html, re.I)
        size_str = size_m.group(1) if size_m else ""

        rel_title = f"{clean_title} ({year or ''}) {qual.upper()} HDRip"
        if is_wwe:
            rel_title = f"{clean_title} {qual.upper()} Full Show"

        sources = unwrap_mobilejsr(jsr_u)
        releases.append({
            "release_title": rel_title,
            "quality": qual,
            "codec": "x264",
            "size": size_str,
            "languages": cls_meta["language"],
            "season": None,
            "episode": None,
            "intermediate_url": jsr_u,
            "source_site": "10xflix",
            "sources": sources,
        })

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": "series" if is_wwe else "movie",
        "seasons": None,
        "poster_url": poster_url,
        "backdrop_urls": None,
        "imdb_rating": None,
        "genres": json.dumps(["WWE", "Sports Entertainment", "Action"]) if is_wwe else None,
        "synopsis": None,
        "is_18_plus": 0,
        "is_animated": 0,
        "source_site": "10xflix",
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
        "canonical_key": canonical_key,
        "releases": releases,
    }


def extract_hls_playlist_url(page_html: str, page_url: str) -> str | None:
    """Find the first HTTP(S) HLS playlist reference in an embed page."""
    if not page_html:
        return None

    normalized_html = html_module.unescape(page_html)
    normalized_html = (
        normalized_html
        .replace(r"\/", "/")
        .replace("\\u0026", "&")
        .replace("\\u003d", "=")
        .replace("\\x26", "&")
    )
    candidates = re.findall(
        r"""(?:(?:https?:)?//|/)[^\s"'<>\\]*?\.m3u8(?:\?[^\s"'<>\\]*)?""",
        normalized_html,
        flags=re.IGNORECASE,
    )
    for candidate in candidates:
        candidate = candidate.rstrip(")]},;")
        playlist_url = urllib.parse.urljoin(page_url, candidate)
        parsed = urllib.parse.urlparse(playlist_url)
        if parsed.scheme in ("http", "https") and parsed.path.lower().endswith(".m3u8"):
            return playlist_url
    return None


def resolve_vidout_playlist(embed_url: str, verbose: bool = False) -> str | None:
    """Read a VIDOUT embed page and return its HLS playlist URL, if present."""
    host = (urllib.parse.urlparse(embed_url).hostname or "").lower()
    if host != "vidout.pages.dev" and not host.endswith(".vidout.pages.dev"):
        return None

    try:
        code, final_url, page_html = http_get(embed_url, timeout=12)
    except Exception as exc:
        if verbose:
            print(f"    [MultiMovies] VIDOUT page request failed: {exc}")
        return None

    if code != 200:
        if verbose:
            print(f"    [MultiMovies] VIDOUT page returned HTTP {code}")
        return None

    playlist_url = extract_hls_playlist_url(page_html, final_url or embed_url)
    if not playlist_url and verbose:
        print("    [MultiMovies] No HLS playlist reference found on VIDOUT page")
    return playlist_url


def extract_post_data_multimovies(
    post_url: str,
    html: str,
    verbose: bool = True,
    *,
    crawl_episodes: bool = True,
    resolve_streams: bool = True,
) -> dict | None:
    """
    Extracts post metadata, embedded streaming servers, and download mirrors from MultiMovies.
    Uses watchConfig embedded JSON with Cineverse, GD mirror, Vidrift, RozgarLelo, VIDOUT.
    Extracts TMDB and IMDB IDs from embed server URLs.
    For series, crawls individual episode pages for per-episode streaming servers.
    """
    slug = post_url.rstrip("/").split("/")[-1]
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_m.group(1).split(" - MultiMovies")[0].strip() if title_m else slug

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org).*$", "", raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    backdrop_url = None
    synopsis = None
    genres = None
    imdb_rating = None

    # Parse watchItem embedded JSON
    item_m = re.search(r'watchItem\s*=\s*(\{.*?\});', html, re.DOTALL)
    if item_m:
        try:
            item_data = json.loads(item_m.group(1))
            poster_url = item_data.get("poster") or poster_url
            backdrop_url = item_data.get("backdrop") or backdrop_url
        except Exception:
            pass

    # Parse Schema.org JSON-LD for rich metadata
    for ld_m in re.finditer(r'<script\s+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            ld_data = json.loads(ld_m.group(1))
            if isinstance(ld_data, dict) and ld_data.get("@type") in {"Movie", "TVSeries", "TVEpisode"}:
                synopsis = ld_data.get("description") or synopsis
                if not genres and ld_data.get("genre"):
                    g = ld_data.get("genre")
                    genres = ", ".join(g) if isinstance(g, list) else str(g)
                if not imdb_rating and ld_data.get("aggregateRating"):
                    imdb_rating = str(ld_data["aggregateRating"].get("ratingValue") or "")
                if not poster_url and ld_data.get("image"):
                    poster_url = ld_data.get("image")
        except Exception:
            pass

    # Fallback poster and description from meta tags
    if not poster_url:
        og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if og_m:
            poster_url = og_m.group(1)
    if not synopsis:
        meta_desc = re.search(r'<meta\s+name=[\"\']description[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html, re.IGNORECASE)
        if meta_desc:
            synopsis = meta_desc.group(1).strip()

    is_series = "/series/" in post_url
    content_type = "series" if is_series else "movie"
    cls_meta = classify_media("multimovies", raw_title, slug, html)
    adult_patterns = [
        r"\b18\+\b", r"\badult\b", r"\berotic\b", r"\bhotshots\b",
        r"\bullu\b", r"\bkooku\b", r"\bprimeplay\b", r"\brabbit\b",
        r"\bhunters\b", r"\bunrated\b", r"\bnsfw\b",
    ]
    is_18_plus = int(any(
        re.search(pattern, f"{raw_title} {slug}", re.IGNORECASE)
        for pattern in adult_patterns
    ))

    releases = []
    tmdb_id = None
    imdb_id = None

    # 1. Parse watchConfig initialServers (single parse for both servers + ID extraction)
    cfg_m = re.search(r'watchConfig\s*=\s*(\{.*?\});', html, re.DOTALL)
    if cfg_m:
        try:
            cfg = json.loads(cfg_m.group(1))
            servers = cfg.get("initialServers", [])
            if verbose:
                print(f"    [MultiMovies] Found {len(servers)} streaming servers in watchConfig")
            for idx, s in enumerate(servers, 1):
                s_name = s.get("name", f"Server {idx}")
                s_url = s.get("url", "")

                # Extract TMDB and IMDB IDs from embed server URLs
                if s_url:
                    if not tmdb_id:
                        tm = re.search(r'/(?:movie|tv)/(?:tmdb/(?:movie|tv)\?id=)?(\d{4,})', s_url)
                        if tm:
                            tmdb_id = int(tm.group(1))
                    if not imdb_id:
                        im = re.search(r'/(tt\d{7,})', s_url)
                        if im:
                            imdb_id = im.group(1)

                if s_url and s_url.startswith("http"):
                    final_stream_url = (
                        resolve_vidout_playlist(s_url, verbose=verbose)
                        if resolve_streams else None
                    ) or s_url
                    is_hls = final_stream_url.lower().split("?", 1)[0].endswith(".m3u8")
                    playback_type = str(s.get("type") or "").strip().lower()
                    if is_hls:
                        playback_type = "hls"
                    elif playback_type not in {"iframe", "hls", "mp4", "video", "direct"}:
                        playback_type = (
                            "direct" if re.search(r"\.(?:mp4|webm|ogg)(?:$|\?)", final_stream_url, re.I)
                            else "iframe"
                        )
                    stream_source = {
                        "source_name": f"⚡ {s_name} [{'Direct HLS' if playback_type == 'hls' else playback_type.upper()}]",
                        "service": s_name.lower().replace(" ", ""),
                        "resource_id": final_stream_url.rstrip("/").split("/")[-1].split("?")[0],
                        "source_url": s_url,
                        "final_url": final_stream_url,
                        "playback_type": playback_type,
                        "is_temporary": 0,
                    }
                    releases.append({
                        "release_title": f"{clean_title} ({year or ''}) Stream Server {s_name}",
                        "quality": "1080p",
                        "codec": "H.264",
                        "size": "",
                        "languages": cls_meta["language"],
                        "season": "S01" if is_series else None,
                        "episode": None,
                        "intermediate_url": s_url,
                        "source_site": "multimovies",
                        "sources": [stream_source],
                    })
        except Exception as e:
            if verbose:
                print(f"    [MultiMovies] watchConfig parse error: {e}")

    # 2. Look for any download links (HubCloud, fast mirrors)
    for l, t in re.findall(r'<a[^>]+href=[\'\"](https?://[^\'\"]+)[\'"][^>]*>(.*?)</a>', html):
        t_clean = re.sub(r'<[^>]+>', ' ', t).strip()
        l_lower = l.lower()
        if any(k in l_lower for k in ["hubcloud", "gdflix", "drive.google", "rozgarlelo"]):
            sources = []
            if "hubcloud." in l_lower:
                direct_u, r_id, is_temp = unwrap_hubcloud(l)
                sources.append({
                    "source_name": "⚡ HubCloud [Direct Stream/DL]",
                    "service": "hubcloud",
                    "resource_id": r_id,
                    "source_url": l,
                    "final_url": direct_u,
                    "is_temporary": is_temp,
                })
            else:
                sources.append({
                    "source_name": f"🌐 {t_clean or 'Download Mirror'}",
                    "service": urllib.parse.urlparse(l).netloc.split(".")[0],
                    "resource_id": l.rstrip("/").split("/")[-1],
                    "source_url": l,
                    "final_url": l,
                    "is_temporary": 0,
                })
            releases.append({
                "release_title": f"{clean_title} ({year or ''}) {t_clean or 'Direct Download'}",
                "quality": "1080p",
                "codec": "x264",
                "size": "",
                "languages": cls_meta["language"],
                "season": "S01" if is_series else None,
                "episode": None,
                "intermediate_url": l,
                "source_site": "multimovies",
                "sources": sources,
            })

    # 3. Episode-level crawling for series
    if is_series and crawl_episodes:
        ep_links = re.findall(r'href=["\']([^"\']*?/series/[^"\']*?/season/(\d+)/episode/(\d+)[^"\']*)["\']', html)
        # Deduplicate and cap: max 3 seasons, 30 episodes total
        seen_eps = set()
        unique_eps = []
        for ep_url_raw, s_num, e_num in ep_links:
            s_int, e_int = int(s_num), int(e_num)
            if s_int > 3:
                continue
            ep_key = (s_int, e_int)
            if ep_key not in seen_eps and len(unique_eps) < 30:
                seen_eps.add(ep_key)
                # Build absolute URL
                if ep_url_raw.startswith("http"):
                    ep_abs = ep_url_raw
                else:
                    mm_base = DOMAINS.get("multimovies", "https://multimovies.garden")
                    ep_abs = mm_base.rstrip("/") + "/" + ep_url_raw.lstrip("/")
                unique_eps.append((ep_abs, s_int, e_int))

        if unique_eps and verbose:
            print(f"    [MultiMovies] Found {len(unique_eps)} episode links, crawling...")

        def _fetch_episode(ep_info):
            """Fetch a single episode page and extract its streaming servers."""
            ep_url, s_num, e_num = ep_info
            ep_releases = []
            try:
                code, _, ep_html = http_get(ep_url, timeout=12)
                if code != 200:
                    return ep_releases
                ep_cfg_m = re.search(r'watchConfig\s*=\s*(\{.*?\});', ep_html, re.DOTALL)
                if ep_cfg_m:
                    ep_cfg = json.loads(ep_cfg_m.group(1))
                    ep_servers = ep_cfg.get("initialServers", [])
                    for idx, s in enumerate(ep_servers, 1):
                        s_name = s.get("name", f"Server {idx}")
                        s_url = s.get("url", "")
                        if s_url and s_url.startswith("http"):
                            final_stream_url = (
                                resolve_vidout_playlist(s_url, verbose=verbose)
                                if resolve_streams else None
                            ) or s_url
                            is_hls = final_stream_url.lower().split("?", 1)[0].endswith(".m3u8")
                            playback_type = str(s.get("type") or "").strip().lower()
                            if is_hls:
                                playback_type = "hls"
                            elif playback_type not in {"iframe", "hls", "mp4", "video", "direct"}:
                                playback_type = (
                                    "direct" if re.search(r"\.(?:mp4|webm|ogg)(?:$|\?)", final_stream_url, re.I)
                                    else "iframe"
                                )
                            ep_releases.append({
                                "release_title": f"{clean_title} S{s_num:02d}E{e_num:02d} ({year or ''}) {s_name}",
                                "quality": "1080p",
                                "codec": "H.264",
                                "size": "",
                                "languages": cls_meta["language"],
                                "season": f"S{s_num:02d}",
                                "episode": f"E{e_num:02d}",
                                "intermediate_url": s_url,
                                "source_site": "multimovies",
                                "sources": [{
                                    "source_name": f"⚡ {s_name} [{'Direct HLS' if playback_type == 'hls' else playback_type.upper()}] [S{s_num:02d}E{e_num:02d}]",
                                    "service": s_name.lower().replace(" ", ""),
                                    "resource_id": final_stream_url.rstrip("/").split("/")[-1].split("?")[0],
                                    "source_url": s_url,
                                    "final_url": final_stream_url,
                                    "playback_type": playback_type,
                                    "is_temporary": 0,
                                }],
                            })
            except Exception:
                pass
            return ep_releases

        if unique_eps:
            with ThreadPoolExecutor(max_workers=min(6, len(unique_eps))) as executor:
                futures = {executor.submit(_fetch_episode, ep): ep for ep in unique_eps}
                for fut in as_completed(futures):
                    ep_rels = fut.result()
                    releases.extend(ep_rels)
            if verbose:
                ep_count = sum(1 for r in releases if r.get("episode"))
                print(f"    [MultiMovies] Episode crawl complete: {ep_count} episode streams found")

    return {
        "url": post_url,
        "slug": slug,
        "title": raw_title,
        "clean_title": clean_title,
        "year": year,
        "content_type": content_type,
        "seasons": None,
        "poster_url": poster_url,
        "backdrop_urls": backdrop_url,
        "imdb_rating": imdb_rating,
        "genres": genres,
        "synopsis": synopsis,
        "is_18_plus": is_18_plus,
        "is_animated": 0,
        "source_site": "multimovies",
        "industry": cls_meta["industry"],
        "country": cls_meta["country"],
        "language": cls_meta["language"],
        "canonical_key": canonical_key,
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "releases": releases,
    }


# ── Release & Source Extractor ────────────────────────────────────────────────


def extract_post_data_hdhub4u(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and download bridge links from HDHub4u.
    HDHub4u uses greenmotors.cc/?id=<base64> as download bridges.
    """
    slug = post_url.rstrip("/").split("/")[-1]
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if h1_m:
        raw_title = re.sub(r"<[^>]+>", " ", h1_m.group(1)).strip()
        raw_title = html_module.unescape(raw_title).strip()
        raw_title = re.sub(r"\s+", " ", raw_title)
    else:
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        t_text = title_m.group(1).split(" | ")[0].split(" - ")[0].strip() if title_m else ""
        raw_title = t_text if t_text else slug.replace("-", " ").title()

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|webrip|hdrip|bluray|esubs|dual audio|hindi|org|season\s*\d+|s\d+|all episodes).*$", "", raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    cover_m = re.search(r'<img[^>]+class=["\'][^"\']*movie-cover[^"\']*["\'][^>]*>', html, re.I | re.S)
    if cover_m:
        tag_str = re.sub(r'onerror=["\'][^"\']*["\']', '', cover_m.group(0))
        src_m = re.search(r'\bsrc=["\']([^"\']+)["\']', tag_str)
        if src_m:
            poster_url = urllib.parse.urljoin(post_url, src_m.group(1))
    if not poster_url:
        og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if og_m:
            poster_url = og_m.group(1)
        else:
            img_m = re.search(r'<img[^>]+src=["\'](https://catimages\.org/[^"\']+)["\']', html)
            if img_m:
                poster_url = img_m.group(1)

    is_series = bool(re.search(r"\b(season|s\d+|episode|series|complete|batch)\b", raw_title, re.I))
    content_type = "series" if is_series else "movie"
    season_m = re.search(r"\b(Season\s*\d+(?:\s*[-&]\s*\d+)?)\b", raw_title, re.IGNORECASE)
    seasons = season_m.group(1) if season_m else None
    cls_meta = classify_media("hdhub4u", raw_title, slug, html)

    # HDHub4u uses greenmotors.cc/?id=<base64> or hubcdn.io/cloud/ bridges
    bridge_links = list(dict.fromkeys(re.findall(
        r'href=["\'](https?://greenmotors\.[a-z]+/\?id=[A-Za-z0-9+/=_\-]+)["\']',
        html
    )))
    hubcdn_matches = re.findall(
        r'<a[^>]+href=["\'](https?://hubcdn\.io/cloud/[^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        re.I | re.S,
    )
    # Also look for any hblinks or direct episode link sets
    hb_links = list(dict.fromkeys(re.findall(
        r'href=["\'](https?://[^"\'<>\s]*(?:hblinks|hubcloud|gdflix|pixeldrain|fastdl)[^"\'<>\s]*)["\']',
        html
    )))

    if verbose:
        print(f"    [HDHub4u] Found {len(hubcdn_matches)} HubCDN + {len(bridge_links)} greenmotors bridges + {len(hb_links)} direct links for: {clean_title}")

    releases = []
    # Process HubCDN cloud links (hdtvb.net)
    for cloud_u, btn_lbl in hubcdn_matches:
        lbl_clean = re.sub(r'<[^>]+>', '', btn_lbl).strip()
        qual_m = re.search(r'\{(.*?)\}', lbl_clean)
        qual = qual_m.group(1) if qual_m else "HD"
        size_m = re.search(r'Download\s+([0-9\.]+\s*(?:Mb|Gb|MB|GB))', lbl_clean, re.I)
        size_str = size_m.group(1) if size_m else ""

        rel_title = f"{clean_title}"
        if year:
            rel_title += f" ({year})"
        if seasons:
            rel_title += f" {seasons}"
        rel_title += f" {qual}"
        if size_str:
            rel_title += f" [{size_str}]"

        releases.append({
            "release_title": rel_title,
            "quality": qual,
            "codec": "hevc" if "hevc" in qual.lower() else "x264",
            "size": size_str,
            "languages": cls_meta["language"],
            "season": seasons,
            "episode": None,
            "intermediate_url": cloud_u,
            "source_site": "hdhub4u",
            "sources": [{
                "source_name": f"⚡ HubCDN Gateway [{qual}]",
                "service": "hubcdn",
                "resource_id": cloud_u.rstrip("/").split("/")[-1][:32],
                "source_url": cloud_u,
                "final_url": cloud_u,
                "is_temporary": 0,
                "playback_type": "url",
            }],
        })
    # Process greenmotors bridges
    for idx, bridge_u in enumerate(bridge_links, 1):
        # Detect quality from surrounding HTML context
        idx_pos = html.find(bridge_u)
        nearby = html[max(0, idx_pos - 300):idx_pos + 200]
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', nearby, re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"
        size_m = re.search(r'\[([0-9\.]+\s*(?:GB|MB))\]', nearby, re.I)
        size_str = size_m.group(1) if size_m else ""
        ep_m = re.search(r'E\s*(\d+)\s*[-–]\s*E?\s*(\d+)|EP\s*(\d+)', nearby, re.I)
        ep_label = f"E{ep_m.group(1)}-E{ep_m.group(2)}" if ep_m and ep_m.group(1) else ""

        rel_title = f"{clean_title}"
        if seasons:
            rel_title += f" {seasons}"
        if ep_label:
            rel_title += f" {ep_label}"
        rel_title += f" {qual.upper()}"

        releases.append({
            "release_title": rel_title,
            "quality": qual,
            "codec": "x264",
            "size": size_str,
            "languages": cls_meta["language"],
            "season": seasons,
            "episode": ep_label or None,
            "intermediate_url": bridge_u,
            "source_site": "hdhub4u",
            "sources": [{
                "source_name": f"⚡ HDHub4u Bridge [{qual.upper()}]",
                "service": "greenmotors",
                "resource_id": bridge_u.split("?id=")[-1][:24],
                "source_url": bridge_u,
                "final_url": bridge_u,
                "is_temporary": 0,
            }],
        })

    # Process any direct HubCloud/GDFlix/Pixeldrain links
    for direct_u in hb_links:
        dl = direct_u.lower()
        if "hubcloud" in dl:
            sources = list(unwrap_hubcloud_drive(direct_u))
        elif "pixeldrain" in dl:
            pdu, pd_id, _ = unwrap_pixeldrain(direct_u)
            sources = [{"source_name": "⚡ PixelDrain [CDN]", "service": "pixeldrain", "resource_id": pd_id,
                        "source_url": direct_u, "final_url": pdu, "is_temporary": 0}]
        else:
            sources = [{"source_name": "⚡ Direct CDN", "service": urllib.parse.urlparse(direct_u).netloc.split(".")[0],
                        "resource_id": direct_u.rstrip("/").split("/")[-1][:32],
                        "source_url": direct_u, "final_url": direct_u, "is_temporary": 0}]
        idx_pos = html.find(direct_u)
        nearby = html[max(0, idx_pos - 200):idx_pos + 150]
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', nearby, re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"
        releases.append({
            "release_title": f"{clean_title} {qual.upper()} Direct",
            "quality": qual, "codec": "x264", "size": "",
            "languages": cls_meta["language"],
            "season": seasons, "episode": None,
            "intermediate_url": direct_u, "source_site": "hdhub4u", "sources": sources,
        })

    return {
        "url": post_url, "slug": slug, "title": raw_title, "clean_title": clean_title,
        "year": year, "content_type": content_type, "seasons": seasons,
        "poster_url": poster_url, "backdrop_urls": None, "imdb_rating": None, "genres": None,
        "synopsis": None, "is_18_plus": 0, "is_animated": 0,
        "source_site": "hdhub4u", "industry": cls_meta["industry"],
        "country": cls_meta["country"], "language": cls_meta["language"],
        "canonical_key": canonical_key, "releases": releases,
    }


def extract_post_data_bollyshares(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and download bridges from BollyShares/Bollyflix.
    BollyShares uses 10moviesz.mom/?id=<id> bridges (short encrypted IDs).
    """
    slug = post_url.rstrip("/").split("/")[-1]
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_m.group(1).split(" - ")[0].strip() if title_m else ""
    raw_title = raw_title.replace("Free ", "").strip()
    if not raw_title:
        raw_title = slug.replace("-", " ").title()

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|webrip|hdrip|bluray|esubs|dual audio|hindi|org|free).*$", "", raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if og_m:
        poster_url = og_m.group(1)

    is_series = bool(re.search(r"\b(season|s\d+|episode|series|complete|batch)\b", raw_title, re.I))
    content_type = "series" if is_series else "movie"
    season_m = re.search(r"\b(Season\s*\d+(?:\s*[-&]\s*\d+)?)\b", raw_title, re.IGNORECASE)
    seasons = season_m.group(1) if season_m else None
    cls_meta = classify_media("bollyshares", raw_title, slug, html)

    # BollyShares uses 10moviesz.mom/?id=<id> short bridges
    bridge_links = list(dict.fromkeys(re.findall(
        r'href=["\'](https?://10moviesz?\.[a-z]+/\?id=[^"\'\s<>]+)["\']',
        html
    )))
    # Also any hubcloud/pixeldrain direct
    direct_links = list(dict.fromkeys(re.findall(
        r'href=["\'](https?://[^"\'<>\s]*(?:hubcloud|pixeldrain|gdflix|fastdl)[^"\'<>\s]*)["\']',
        html
    )))

    if verbose:
        print(f"    [BollyShares] Found {len(bridge_links)} 10moviesz bridges + {len(direct_links)} direct for: {clean_title}")

    releases = []
    for bridge_u in bridge_links:
        idx_pos = html.find(bridge_u)
        nearby = html[max(0, idx_pos - 300):idx_pos + 200]
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', nearby, re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"
        size_m = re.search(r'\[([0-9\.]+\s*(?:GB|MB))\]', nearby, re.I)
        size_str = size_m.group(1) if size_m else ""
        releases.append({
            "release_title": f"{clean_title} {qual.upper()} Hindi",
            "quality": qual, "codec": "x264", "size": size_str,
            "languages": cls_meta["language"],
            "season": seasons, "episode": None,
            "intermediate_url": bridge_u, "source_site": "bollyshares",
            "sources": [{
                "source_name": f"⚡ BollyShares Bridge [{qual.upper()}]",
                "service": "10moviesz",
                "resource_id": re.search(r'\?id=([^&\s]+)', bridge_u).group(1)[:24] if re.search(r'\?id=([^&\s]+)', bridge_u) else "",
                "source_url": bridge_u, "final_url": bridge_u, "is_temporary": 0,
            }],
        })

    for direct_u in direct_links:
        dl = direct_u.lower()
        if "hubcloud" in dl:
            sources = list(unwrap_hubcloud_drive(direct_u))
        else:
            sources = [{"source_name": "⚡ Direct CDN", "service": urllib.parse.urlparse(direct_u).netloc.split(".")[0],
                        "resource_id": direct_u.rstrip("/").split("/")[-1][:32],
                        "source_url": direct_u, "final_url": direct_u, "is_temporary": 0}]
        releases.append({
            "release_title": f"{clean_title} Hindi Direct",
            "quality": "720p", "codec": "x264", "size": "",
            "languages": cls_meta["language"], "season": seasons, "episode": None,
            "intermediate_url": direct_u, "source_site": "bollyshares", "sources": sources,
        })

    return {
        "url": post_url, "slug": slug, "title": raw_title, "clean_title": clean_title,
        "year": year, "content_type": content_type, "seasons": seasons,
        "poster_url": poster_url, "backdrop_urls": None, "imdb_rating": None, "genres": None,
        "synopsis": None, "is_18_plus": 0, "is_animated": 0,
        "source_site": "bollyshares", "industry": cls_meta["industry"],
        "country": cls_meta["country"], "language": cls_meta["language"],
        "canonical_key": canonical_key, "releases": releases,
    }


def extract_post_data_filmyzilla(post_url: str, html: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata and /server/ download links from FilmyZilla74.
    FilmyZilla uses /server/<id>/<filename>.html pages per quality — we store them as direct sources.
    """
    slug = post_url.rstrip("/").split("/")[-1].replace(".html", "")
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    raw_title = title_m.group(1).split(" Free Download")[0].strip() if title_m else ""
    if not raw_title:
        raw_title = slug.replace("-", " ").title()

    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", raw_title)
    year = int(year_m.group(1)) if year_m else None

    clean_title = re.sub(r"\s*(?:1080p|720p|480p|2160p|4k|web-dl|webrip|hdrip|bluray|esubs|dual audio|hindi|org).*$", "", raw_title, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\s*\(\s*\d{4}\s*\).*$", "", clean_title).strip()
    # Remove quality suffix from filename-style titles
    clean_title = re.sub(r"\s*(?:Hindi Movie|Hindi|Movie)\s*$", "", clean_title, flags=re.I).strip()
    canonical_key = generate_canonical_key(clean_title, year)

    poster_url = None
    og_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if og_m:
        poster_url = og_m.group(1)

    is_series = bool(re.search(r"\b(season|s\d+|episode|series|complete|batch)\b", raw_title, re.I))
    content_type = "series" if is_series else "movie"
    cls_meta = classify_media("filmyzilla", raw_title, slug, html)

    # FilmyZilla uses /server/<id>/<filename>.html links — each is a quality variant page
    server_links = list(dict.fromkeys(re.findall(
        r'href=["\'](https?://www\.filmyzilla\d+\.com/server/\d+/[^\"\'<>\s]+\.html)["\']',
        html
    )))
    if not server_links:
        # Also catch relative /server/ paths
        rel_server = re.findall(r'href=["\'](/server/\d+/[^"\'<>\s]+\.html)["\']', html)
        base_domain = "/".join(post_url.split("/")[:3])
        server_links = [f"{base_domain}{p}" for p in rel_server]

    if verbose:
        print(f"    [FilmyZilla] Found {len(server_links)} /server/ download pages for: {clean_title}")

    releases = []
    for srv_url in server_links:
        # Extract quality and filename from the URL itself
        fn = srv_url.rstrip("/").split("/")[-1].replace(".html", "").replace(".mkv", "").replace(".mp4", "")
        qual_m = re.search(r'\b(480p|720p|1080p|2160p|4k)\b', fn, re.I)
        qual = qual_m.group(1).lower() if qual_m else "720p"
        # Friendly display name from filename
        display_name = fn.replace("-", " ").replace(".", " ").strip()

        releases.append({
            "release_title": f"{clean_title} {qual.upper()} [{display_name[:50]}]",
            "quality": qual, "codec": "x264", "size": "",
            "languages": cls_meta["language"],
            "season": None, "episode": None,
            "intermediate_url": srv_url, "source_site": "filmyzilla",
            "sources": [{
                "source_name": f"⚡ FilmyZilla [{qual.upper()}]",
                "service": "filmyzilla",
                "resource_id": srv_url.split("/server/")[1].split("/")[0] if "/server/" in srv_url else slug[:32],
                "source_url": srv_url,
                "final_url": srv_url,
                "is_temporary": 0,
            }],
        })

    return {
        "url": post_url, "slug": slug, "title": raw_title, "clean_title": clean_title,
        "year": year, "content_type": content_type, "seasons": None,
        "poster_url": poster_url, "backdrop_urls": None, "imdb_rating": None, "genres": None,
        "synopsis": None, "is_18_plus": 0, "is_animated": 0,
        "source_site": "filmyzilla", "industry": cls_meta["industry"],
        "country": cls_meta["country"], "language": cls_meta["language"],
        "canonical_key": canonical_key, "releases": releases,
    }


def extract_post_data(post_url: str, verbose: bool = True) -> dict | None:
    """
    Extracts post metadata, all releases, and resolves their download sources.
    Automatically detects site adapter for Vegamovies, RogMovies, SSRMovies, KatMovieHD, 7StarHD, 10xflix, MultiMovies, HDHub4u, BollyShares, and FilmyZilla.
    """
    if verbose:
        print(f"\n[→] Fetching post: {post_url}")
    code, final_url, html = http_get(post_url)
    if code != 200:
        print(f"[!] Failed to fetch post: HTTP {code}")
        return None

    # Multi-Site Dispatcher
    f_lower = final_url.lower()
    if "ssrmovies" in f_lower:
        return extract_post_data_ssrmovies(final_url, html, verbose)
    if "katmovie" in f_lower:
        return extract_post_data_katmoviehd(final_url, html, verbose)
    if "7starhd" in f_lower:
        return extract_post_data_7starhd(final_url, html, verbose)
    if "10xflix" in f_lower:
        return extract_post_data_10xflix(final_url, html, verbose)
    if "multimovies" in f_lower:
        return extract_post_data_multimovies(final_url, html, verbose)
    if "hdhub4u" in f_lower:
        return extract_post_data_hdhub4u(final_url, html, verbose)
    if "bollyshares" in f_lower or "bollyflix" in f_lower or "movie4u.top" in f_lower:
        return extract_post_data_bollyshares(final_url, html, verbose)
    if "filmyzilla" in f_lower:
        return extract_post_data_filmyzilla(final_url, html, verbose)

    post_meta = parse_post_metadata(final_url, html)
    if verbose:
        print(f"    Title: {post_meta['clean_title']} ({post_meta['year'] or 'N/A'})")
        print(f"    Type : {post_meta['content_type']}")

    # Find all Nexdrive links on the post page

    nex_links = re.findall(r'href=[\"\'](https?://nexdrive\.[a-z]+/[^\"\']+)[\"\']', html)
    # Deduplicate while preserving order
    seen_nex = set()
    unique_nex = []
    for l in nex_links:
        if l not in seen_nex:
            seen_nex.add(l)
            unique_nex.append(l)

    if verbose:
        print(f"    Found {len(unique_nex)} release options (Nexdrive bridges).")

    def _process_single_release(idx: int, nex_url: str) -> list[dict]:
        if verbose:
            print(f"    [{idx}/{len(unique_nex)}] Inspecting release bridge: {nex_url}", flush=True)

        n_code, n_final_url, n_html = http_get(nex_url)
        if n_code != 200:
            return []

        # Extract clean release title from <title> tag
        n_title_m = re.search(r"<title>(.*?)</title>", n_html, re.IGNORECASE)
        n_title = n_title_m.group(1).strip() if n_title_m else f"Release {idx}"

        rel_base = parse_release_info(n_title)
        rel_base["intermediate_url"] = nex_url

        if verbose:
            s_label = f" | Season: {rel_base['season']}" if rel_base['season'] else ""
            print(f"        -> {rel_base['release_title']}", flush=True)
            print(f"           Quality: {rel_base['quality']}{s_label} | Size: {rel_base['size']} | Lang: {rel_base['languages']}", flush=True)

        # Parse HTML to find download button paragraphs
        # Find all <p> tags containing valid download anchors
        p_blocks = []
        p_pattern = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
        for p_match in p_pattern.finditer(n_html):
            p_content = p_match.group(1)
            anchors = re.findall(r'<a\s+[^>]*href=[\"\'](https?://[^\"\']+)[\"\'][^>]*>(.*?)</a>', p_content, re.DOTALL)
            valid_anchors = [
                (href, text) for href, text in anchors
                if not any(bad in href.lower() for bad in ["javascript:", "telegram", "whatsapp", "#", "facebook", "twitter", "instagram", "nexdrive.", "how-to-download", "disclaimer", "privacy-policy"])
                and href.startswith("http")
            ]
            if valid_anchors:
                p_blocks.append(valid_anchors)

        def _resolve_anchor_list(anchor_list):
            sources = []
            for href, text in anchor_list:
                clean_btn = re.sub(r"<[^>]+>", "", text).strip()
                href_lower = href.lower()

                if "fastdl." in href_lower:
                    direct_url, res_id, is_temp = unwrap_fastdl(href)
                    sources.append({
                        "source_name": "⚡ G-Direct [Instant]",
                        "service": "fastdl",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": direct_url,
                        "is_temporary": is_temp,
                    })
                elif "vcloud." in href_lower:
                    res_id = href.rstrip("/").split("/")[-1].split("?")[0]
                    unwrapped_vclouds = unwrap_vcloud(href)
                    for s_name, s_srv, s_fin, is_temp in unwrapped_vclouds:
                        sources.append({
                            "source_name": s_name,
                            "service": s_srv,
                            "resource_id": res_id,
                            "source_url": href,
                            "final_url": s_fin,
                            "is_temporary": is_temp,
                        })
                elif "vegadrive." in href_lower:
                    direct_url, res_id, is_temp = unwrap_vegadrive(href)
                    sources.append({
                        "source_name": "⚡ V-Drive [10Gbps]",
                        "service": "vegadrive",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": direct_url,
                        "is_temporary": is_temp,
                    })
                elif "filebee." in href_lower or "filepress." in href_lower:
                    final_fp, res_id, is_temp = unwrap_filepress(href)
                    sources.append({
                        "source_name": "⚡ Filepress [G-Drive]",
                        "service": "filepress",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": final_fp,
                        "is_temporary": is_temp,
                    })
                elif "hubcloud." in href_lower:
                    direct_url, svc, is_temp = unwrap_hubcloud(href)
                    sources.append({
                        "source_name": "⚡ HubCloud [Direct]" if svc == "google_cdn" else "HubCloud 10Gbps",
                        "service": svc,
                        "resource_id": href.rstrip("/").split("/")[-1],
                        "source_url": href,
                        "final_url": direct_url,
                        "is_temporary": is_temp,
                    })
                elif "pixeldrain." in href_lower:
                    direct_url, res_id, is_temp = unwrap_pixeldrain(href)
                    sources.append({
                        "source_name": "⚡ PixelDrain [Direct CDN]",
                        "service": "pixeldrain",
                        "resource_id": res_id,
                        "source_url": href,
                        "final_url": direct_url,
                        "is_temporary": 0,
                    })
                elif "firebasestorage.googleapis.com" in href_lower:
                    sources.append({
                        "source_name": "⚡ Google Firebase [Direct]",
                        "service": "firebase",
                        "resource_id": href.split("/")[-1].split("?")[0],
                        "source_url": href,
                        "final_url": href,
                        "is_temporary": 0,
                    })
                else:
                    domain_name = urllib.parse.urlparse(href).netloc.replace("www.", "")
                    if domain_name:
                        sources.append({
                            "source_name": f"🌐 {clean_btn or domain_name}",
                            "service": domain_name.split(".")[0],
                            "resource_id": href.rstrip("/").split("/")[-1],
                            "source_url": href,
                            "final_url": href,
                            "is_temporary": 0,
                        })
            return sources

        results = []
        if len(p_blocks) > 1:
            # Multi-Episode mode: each p tag is an episode
            season_str = rel_base["season"] or "S01"
            for ep_num, anchor_list in enumerate(p_blocks, 1):
                ep_code = f"E{ep_num:02d}"
                ep_info = dict(rel_base)
                ep_info["episode"] = ep_code
                ep_info["release_title"] = f"{rel_base['release_title']} - {season_str}{ep_code}"
                ep_info["sources"] = _resolve_anchor_list(anchor_list)
                results.append(ep_info)
            if verbose:
                print(f"           ✓ Multi-Episode Page: extracted {len(results)} individual episodes ({season_str})", flush=True)
        else:
            # Single release / batch zip mode
            single_info = dict(rel_base)
            if p_blocks:
                single_info["sources"] = _resolve_anchor_list(p_blocks[0])
            else:
                all_anchors = re.findall(r'<a\s+[^>]*href=[\"\'](https?://[^\"\']+)[\"\'][^>]*>(.*?)</a>', n_html, re.DOTALL)
                single_info["sources"] = _resolve_anchor_list(all_anchors)
            results.append(single_info)
            if verbose:
                tag = f"Batch Zip ({rel_base['season']})" if rel_base.get("is_batch") else "Movie / Single Release"
                print(f"           ✓ {tag}: {len(single_info['sources'])} sources resolved", flush=True)

        return results

    # Concurrently inspect releases to maximize speed
    releases_data = []
    max_workers = min(6, len(unique_nex)) if unique_nex else 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(_process_single_release, idx, nex_url): idx for idx, nex_url in enumerate(unique_nex, 1)}
        indexed_results = []
        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                res = fut.result()
                if res:
                    indexed_results.append((idx, res))
            except Exception as e:
                if verbose:
                    print(f"    ✗ Error on release #{idx}: {e}", flush=True)

    # Sort results by original index order and flatten
    indexed_results.sort(key=lambda x: x[0])
    for r in indexed_results:
        releases_data.extend(r[1])

    post_meta["releases"] = releases_data
    return post_meta


# ── Cinemeta Universal Metadata Enrichment ─────────────────────────────────────

def fetch_cinemeta_metadata(title: str, year: int | None = None, content_type: str = "movie") -> dict | None:
    """
    Queries Stremio's Cinemeta official open REST API to enrich scraped posts
    with canonical IMDb IDs, TMDB posters/backdrops, official ratings, and genres.
    """
    if not title:
        return None
    clean = re.sub(r'\s*(?:1080p|720p|480p|2160p|4k|web-dl|bluray|hdrip|esubs|dual audio|hindi|org).*$', '', title, flags=re.I).strip()
    clean = re.sub(r'[\(\)\[\]]', ' ', clean).strip()
    c_type = "series" if content_type in ("series", "ongoing_season") else "movie"
    encoded = urllib.parse.quote(clean.lower())

    url = f"https://v3-cinemeta.strem.io/catalog/{c_type}/top/search={encoded}.json"
    headers = {"User-Agent": USER_AGENT}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8, context=SSL_CONTEXT) as r:
            data = json.loads(r.read())
        metas = data.get("metas", [])
        if not metas:
            return None

        # Pick best match based on year if provided
        best = metas[0]
        if year:
            for m in metas:
                r_info = str(m.get("releaseInfo", ""))
                if str(year) in r_info:
                    best = m
                    break

        imdb_id = best.get("imdb_id") or best.get("id")
        if not imdb_id:
            return None

        # Fetch full meta details
        detail_url = f"https://v3-cinemeta.strem.io/meta/{c_type}/{imdb_id}.json"
        req_d = urllib.request.Request(detail_url, headers=headers)
        with urllib.request.urlopen(req_d, timeout=8, context=SSL_CONTEXT) as r_d:
            d_data = json.loads(r_d.read())
        meta = d_data.get("meta", best)

        return {
            "imdb_id": imdb_id,
            "imdb_rating": meta.get("imdbRating"),
            "genres": meta.get("genres", []),
            "poster_url": meta.get("poster"),
            "backdrop_url": meta.get("background"),
            "synopsis": meta.get("description"),
            "year": meta.get("year") or year,
            "runtime": meta.get("runtime"),
            "name": meta.get("name"),
        }
    except Exception:
        return None


# ── Database Storage ──────────────────────────────────────────────────────────

def _json_list(value) -> list:
    """Read a JSON array or tolerate legacy/plain-text values without crashing."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str) and item.strip()]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [value]
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str) and item.strip()]


def _identity_values_conflict(post, tmdb_id, imdb_id) -> bool:
    for column, incoming in (("tmdb_id", tmdb_id), ("imdb_id", imdb_id)):
        existing = post[column]
        if existing not in (None, "") and incoming not in (None, ""):
            if str(existing).strip().casefold() != str(incoming).strip().casefold():
                return True
    return False


def _post_type_matches(post, content_type: str) -> bool:
    existing_type = (post["content_type"] or "").strip().casefold()
    series_types = {"series", "complete_season", "ongoing_season"}
    incoming_type = "series" if content_type in series_types else content_type
    existing_type = "series" if existing_type in series_types else existing_type
    return not existing_type or existing_type == incoming_type


def _find_existing_post(
    conn: sqlite3.Connection,
    *,
    url: str,
    source_site: str,
    canonical_key: str,
    content_type: str,
    year,
    tmdb_id,
    imdb_id,
):
    """Resolve an existing media row without silently merging ambiguous identities."""
    page_row = conn.execute(
        """
        SELECT p.* FROM post_sources ps
        JOIN posts p ON p.id = ps.post_id
        WHERE ps.source_site = ? AND ps.url = ?
        """,
        (source_site, url),
    ).fetchone()
    primary_url_row = conn.execute("SELECT * FROM posts WHERE url = ?", (url,)).fetchone()
    if page_row and primary_url_row and page_row["id"] != primary_url_row["id"]:
        raise ValueError(f"URL is already associated with conflicting media records: {url}")
    url_row = page_row or primary_url_row

    id_clauses = []
    id_params = []
    if imdb_id not in (None, ""):
        id_clauses.append("imdb_id = ?")
        id_params.append(imdb_id)
    if tmdb_id not in (None, ""):
        id_clauses.append("tmdb_id = ?")
        id_params.append(tmdb_id)

    id_rows = []
    if id_clauses:
        id_rows = conn.execute(
            f"SELECT * FROM posts WHERE {' OR '.join(id_clauses)} ORDER BY id",
            id_params,
        ).fetchall()
    unique_id_rows = {row["id"]: row for row in id_rows}
    if len(unique_id_rows) > 1:
        raise ValueError("IMDb/TMDB identifiers point to different existing media records")

    if unique_id_rows:
        id_row = next(iter(unique_id_rows.values()))
        if not _post_type_matches(id_row, content_type):
            raise ValueError("External media ID matches a record with a different media type")
        if _identity_values_conflict(id_row, tmdb_id, imdb_id):
            raise ValueError("External media IDs conflict with the matched database record")
        if url_row and url_row["id"] != id_row["id"]:
            raise ValueError(f"URL and external media ID point to different records: {url}")
        return id_row

    if url_row:
        if not _post_type_matches(url_row, content_type):
            raise ValueError(f"Indexed source URL now resolves to a different media type: {url}")
        if (
            year not in (None, "")
            and url_row["year"] not in (None, "")
            and str(year) != str(url_row["year"])
        ):
            raise ValueError(f"Indexed source URL now conflicts with the known release year: {url}")
        if _identity_values_conflict(url_row, tmdb_id, imdb_id):
            raise ValueError(f"URL is associated with conflicting external media IDs: {url}")
        return url_row

    if not canonical_key or canonical_key == "unknown":
        return None

    candidates = conn.execute(
        "SELECT * FROM posts WHERE canonical_key = ? ORDER BY id",
        (canonical_key,),
    ).fetchall()
    candidates = [
        row for row in candidates
        if (
            _post_type_matches(row, content_type)
            and not (
                year not in (None, "")
                and row["year"] not in (None, "")
                and str(year) != str(row["year"])
            )
            and not _identity_values_conflict(row, tmdb_id, imdb_id)
        )
    ]
    if len(candidates) > 1:
        raise ValueError(
            f"Canonical key {canonical_key!r} matches multiple records; refusing an arbitrary merge"
        )
    return candidates[0] if candidates else None


def _validate_scraped_data(data: dict):
    if not isinstance(data, dict):
        raise TypeError("Scraped media data must be a dictionary")
    url = str(data.get("url") or "").strip()
    clean_title = str(data.get("clean_title") or data.get("title") or "").strip()
    title = str(data.get("title") or clean_title).strip()
    source_site = str(data.get("source_site") or "vegamovies").strip().lower()
    content_type = str(data.get("content_type") or "movie").strip().lower()
    if not url:
        raise ValueError("Scraped media data is missing its source URL")
    parsed_source_url = urllib.parse.urlparse(url)
    if parsed_source_url.scheme not in {"http", "https"} or not parsed_source_url.netloc:
        raise ValueError(f"Source URL must be an absolute HTTP(S) URL: {url}")
    if not clean_title or clean_title.casefold() == "unknown":
        raise ValueError("Scraped media data is missing a usable title")
    if not source_site:
        raise ValueError("Scraped media data is missing its source site")

    releases = data.get("releases") or []
    if not isinstance(releases, list):
        raise ValueError("Scraped releases must be a list")
    valid_releases = [release for release in releases if isinstance(release, dict)]
    for release in valid_releases:
        if release.get("sources") is not None and not isinstance(release.get("sources"), list):
            raise ValueError("Release sources must be a list")
    return url, clean_title, title, source_site, content_type, valid_releases


def save_scraped_data(
    data: dict,
    *,
    enrich_metadata: bool = True,
    ensure_db: bool = True,
) -> int:
    """Enrich outside the DB lock, then atomically serialize identity lookup and save."""
    if not isinstance(data, dict):
        raise TypeError("Scraped media data must be a dictionary")
    data = dict(data)
    _validate_scraped_data(data)
    data["is_18_plus"] = int(
        bool(data.get("is_18_plus"))
        or is_adult_title(
            data.get("clean_title") or data.get("title") or "",
            data.get("original_title") or data.get("slug") or data.get("url") or "",
        )
    )
    if enrich_metadata:
        _enrich_scraped_metadata(data)
    # The animation flag, decided once for every scraper at the place a payload
    # becomes a post. A site's own parser may assert it; otherwise the shared title,
    # slug and genre vocabulary does. Before this, exactly one page parser ever set
    # the column, so 130,016 merged posts carried one animated title and an Anime
    # filter had nothing honest to show.
    data["is_animated"] = int(
        bool(data.get("is_animated"))
        or site_implies_animation(data.get("source_site"))
        or looks_animated(
            data.get("clean_title") or data.get("title") or "",
            data.get("slug") or data.get("url") or "",
            data.get("genres") or "",
        )
    )
    with _DB_WRITE_LOCK:
        return _save_scraped_data(data, ensure_db=ensure_db)


def _enrich_scraped_metadata(data: dict) -> None:
    clean_title = str(data.get("clean_title") or data.get("title") or "").strip()
    if not clean_title or clean_title.casefold() == "unknown":
        return
    placeholder_titles = {
        "7starhd", "rogmovies", "vegamovies", "katmoviehd",
        "ssrmovies", "10xflix", "multimovies", "",
    }
    if clean_title.casefold() in placeholder_titles:
        return

    poster = data.get("poster_url")
    rating = data.get("imdb_rating")
    genres = data.get("genres")
    if rating and get_poster_quality_rank(poster) >= 7 and genres and genres != "[]":
        return
    metadata = fetch_cinemeta_metadata(
        clean_title,
        data.get("year"),
        str(data.get("content_type") or "movie").strip().lower(),
    )
    if not metadata:
        return

    if not rating and metadata.get("imdb_rating"):
        data["imdb_rating"] = str(metadata["imdb_rating"])
    if metadata.get("poster_url") and get_poster_quality_rank(metadata["poster_url"]) > get_poster_quality_rank(poster):
        data["poster_url"] = metadata["poster_url"]
    if metadata.get("backdrop_url"):
        backdrops = _json_list(data.get("backdrop_urls"))
        if metadata["backdrop_url"] not in backdrops:
            backdrops.insert(0, metadata["backdrop_url"])
            data["backdrop_urls"] = json.dumps(backdrops)
    if metadata.get("genres") and (not genres or genres == "[]"):
        data["genres"] = json.dumps(metadata["genres"])
    if not data.get("synopsis") and metadata.get("synopsis"):
        data["synopsis"] = metadata["synopsis"]
    if not data.get("year") and metadata.get("year"):
        data["year"] = metadata["year"]
        data["canonical_key"] = generate_canonical_key(clean_title, data["year"])
    if not data.get("imdb_id") and metadata.get("imdb_id"):
        data["imdb_id"] = metadata["imdb_id"]


def _save_scraped_data(data: dict, *, ensure_db: bool = True) -> int:
    """
    Atomically save media metadata, each site's page URL, release options, and sources.
    Match order: external IDs, previously indexed page URL, then an unambiguous
    type-aware canonical title/year key. Ambiguous or conflicting identities fail
    explicitly instead of silently corrupting cross-site records.
    """
    url, clean_title, title, source_site, content_type, valid_releases = _validate_scraped_data(data)

    year = data.get("year")
    tmdb_id = data.get("tmdb_id")
    imdb_id = data.get("imdb_id")
    canonical_key = str(
        data.get("canonical_key") or generate_canonical_key(clean_title, year)
    ).strip().lower()
    if not canonical_key or canonical_key == "unknown":
        canonical_key = generate_canonical_key(clean_title, year)

    if ensure_db:
        init_db()
    with get_db() as conn:
        # Reserve the SQLite writer before matching, so another process cannot
        # insert a competing canonical record between lookup and insertion.
        conn.execute("BEGIN IMMEDIATE")
        existing = _find_existing_post(
            conn,
            url=url,
            source_site=source_site,
            canonical_key=canonical_key,
            content_type=content_type,
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
        )

        if existing:
            post_id = existing["id"]

            # 1. Poster Quality Hierarchy: TMDB original (10) > TMDB w500 (8) > TMDB (7) > CatImages/ImgBB (5) > Blog Upload (3)
            new_poster = data.get("poster_url")
            existing_poster = existing["poster_url"]
            if get_poster_quality_rank(new_poster) >= get_poster_quality_rank(existing_poster):
                chosen_poster = new_poster or existing_poster
            else:
                chosen_poster = existing_poster

            # 2. Merge backdrop screenshots
            exist_bd = _json_list(existing["backdrop_urls"])
            new_bd = _json_list(data.get("backdrop_urls"))
            combined_bd = list(dict.fromkeys(exist_bd + new_bd))[:12]
            chosen_backdrops = json.dumps(combined_bd) if combined_bd else None

            # 3. Merge genres
            exist_g = _json_list(existing["genres"])
            new_g = _json_list(data.get("genres"))
            combined_g = list(dict.fromkeys(exist_g + new_g))
            chosen_genres = json.dumps(combined_g) if combined_g else None

            # 4. Best metadata (synopsis, imdb_rating, year)
            chosen_imdb = existing["imdb_rating"] or data.get("imdb_rating")
            chosen_synopsis = (
                existing["synopsis"]
                if (existing["synopsis"] and len(existing["synopsis"]) > len(data.get("synopsis") or ""))
                else (data.get("synopsis") or existing["synopsis"])
            )
            chosen_year = existing["year"] if existing["year"] is not None else year

            # Update existing post row
            conn.execute(
                """
                UPDATE posts SET
                    canonical_key = ?,
                    title = CASE WHEN length(COALESCE(title, '')) > length(?) THEN title ELSE ? END,
                    clean_title = CASE WHEN lower(clean_title) IN ('7starhd', 'rogmovies', 'vegamovies', 'katmoviehd', 'ssrmovies', '10xflix', 'multimovies', '') OR clean_title IS NULL THEN ? ELSE clean_title END,
                    year = ?,
                    content_type = COALESCE(NULLIF(content_type, ''), ?),
                    poster_url = ?,
                    backdrop_urls = ?,
                    imdb_rating = ?,
                    genres = ?,
                    synopsis = ?,
                    tmdb_id = COALESCE(?, tmdb_id),
                    imdb_id = COALESCE(?, imdb_id),
                    industry = COALESCE(NULLIF(industry, ''), ?),
                    country = COALESCE(NULLIF(country, ''), ?),
                    language = COALESCE(NULLIF(language, ''), ?),
                    is_18_plus = MAX(is_18_plus, ?),
                    is_animated = MAX(is_animated, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    canonical_key,
                    title,
                    title,
                    clean_title,
                    chosen_year,
                    content_type,
                    chosen_poster,
                    chosen_backdrops,
                    chosen_imdb,
                    chosen_genres,
                    chosen_synopsis,
                    tmdb_id,
                    imdb_id,
                    data.get("industry"),
                    data.get("country"),
                    data.get("language"),
                    data.get("is_18_plus", 0),
                    data.get("is_animated", 0),
                    post_id,
                ),
            )

        else:
            # Insert brand new post
            cur = conn.execute(
                """
                INSERT INTO posts (
                    url, slug, title, clean_title, year, content_type, seasons,
                    poster_url, backdrop_urls, imdb_rating, genres, synopsis,
                    tmdb_id, imdb_id,
                    is_18_plus, is_animated, source_site, industry, country, language,
                    canonical_key, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                RETURNING id;
                """,
                (
                    url,
                    data.get("slug") or urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1],
                    title,
                    clean_title,
                    year,
                    content_type,
                    data.get("seasons"),
                    data.get("poster_url"),
                    data.get("backdrop_urls"),
                    data.get("imdb_rating"),
                    data.get("genres"),
                    data.get("synopsis"),
                    tmdb_id,
                    imdb_id,
                    data.get("is_18_plus", 0),
                    data.get("is_animated", 0),
                    source_site,
                    data.get("industry", "Hollywood"),
                    data.get("country", "USA"),
                    data.get("language", "English"),
                    canonical_key,
                ),
            )
            post_id = cur.fetchone()[0]

        source_cursor = conn.execute(
            """
            INSERT INTO post_sources
                (post_id, source_site, url, source_title, source_slug, last_seen_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_site, url) DO UPDATE SET
                source_title = COALESCE(excluded.source_title, post_sources.source_title),
                source_slug = COALESCE(excluded.source_slug, post_sources.source_slug),
                last_seen_at = CURRENT_TIMESTAMP
            WHERE post_sources.post_id = excluded.post_id
            """,
            (post_id, source_site, url, title or None, data.get("slug")),
        )
        if source_cursor.rowcount == 0:
            raise ValueError(f"Source URL is already linked to another media record: {url}")

        # Insert releases with source_site
        origin_url = str(data.get("origin_url") or url)
        if existing and valid_releases:
            # Refresh only the releases this page owns; other pages of the same site
            # contribute the rest of the title and must survive untouched.
            conn.execute(
                "DELETE FROM releases WHERE post_id = ? AND source_site = ? AND origin_url IS ?",
                (post_id, source_site, origin_url),
            )

        for rel in valid_releases:
            rel_cur = conn.execute(
                """
                INSERT INTO releases (post_id, release_title, season, episode, quality, codec, size, languages, intermediate_url, source_site, origin_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id;
                """,
                (
                    post_id,
                    rel.get("release_title") or title,
                    rel.get("season"),
                    rel.get("episode"),
                    rel.get("quality"),
                    rel.get("codec"),
                    rel.get("size"),
                    rel.get("languages"),
                    rel.get("intermediate_url"),
                    source_site,
                    origin_url,
                ),
            )
            rel_id = rel_cur.fetchone()[0]

            for src in rel.get("sources") or []:
                if not isinstance(src, dict):
                    continue
                conn.execute(
                    """
                    INSERT INTO download_sources
                        (release_id, source_name, service, resource_id, source_url,
                         final_url, playback_type, is_temporary, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active');
                    """,
                    (
                        rel_id,
                        src.get("source_name"),
                        src.get("service"),
                        src.get("resource_id"),
                        src.get("source_url"),
                        src.get("final_url"),
                        src.get("playback_type", "url"),
                        src.get("is_temporary", 0),
                    ),
                )

        # A page that produced no release was never "indexed": it is an empty or
        # unreadable response. Marking it scraped = 1 anyway is exactly how ~1.7k
        # katmoviehd and ~2.4k hindilinks4u URLs went missing with a green tick on
        # them, invisible to every later audit. Book a transient failure instead, so
        # the retry budget spends attempts on it, `last_cause` records why, and
        # `select_crawl_candidates` keeps it visible until the budget runs out.
        if valid_releases:
            conn.execute("UPDATE sitemap_cache SET scraped = 1 WHERE loc = ?", (url,))
        else:
            prior = conn.execute(
                "SELECT attempts FROM sitemap_cache WHERE loc = ?", (url,)).fetchone()
            parked, attempts = crawl_attempt_state(
                "parse_no_releases", prior_attempts=(prior[0] if prior else 0) or 0)
            conn.execute(
                "UPDATE sitemap_cache SET scraped = ?, attempts = ?, last_attempt = ?,"
                " last_cause = ? WHERE loc = ?",
                (parked, attempts, time.time(), "parse_no_releases", url),
            )

    return post_id


# A page that fails once is usually transient (Cloudflare interstitial, host
# rotate, timeout).  Before this, a failure set scraped = -1 forever and the
# crawler only ever selected scraped = 0, so ~42k failed pages were silently
# abandoned rather than queued.
MAX_CRAWL_ATTEMPTS = 3

#: Causes that describe the PAGE rather than our bad luck. A 404 will 404 again,
#: so it is parked on the first sighting instead of burning three requests on it;
#: everything else stays eligible for the retry budget. Keeping the two lists
#: separate is what lets an operator tell "gone upstream" from "our parser broke"
#: without re-crawling anything.
PERMANENT_CRAWL_CAUSES = frozenset({
    "http_404_gone",
    "http_410_gone",
    "not_a_post",
})

#: Retried until MAX_CRAWL_ATTEMPTS, then parked with the cause still on the row.
TRANSIENT_CRAWL_CAUSES = frozenset({
    "transport_error",
    "timeout",
    "http_403_forbidden",
    "http_429_rate_limited",
    "http_5xx_upstream_error",
    "blocked_challenge",
    "parse_no_releases",
    "parse_error",
    "sqlite_locked",
})


def classify_crawl_failure(exc=None, *, http_code=None, cause=None) -> str:
    """Name the reason a page did not become a post, in one of the two vocabularies.

    Detection only: a Cloudflare/JS interstitial is recorded as `blocked_challenge`
    and left alone — this never tries to solve or spoof a bot check.
    """
    if cause:
        return str(cause)[:60]
    code = http_code
    if exc is not None:
        if isinstance(exc, urllib.error.HTTPError):
            code = exc.code
        elif isinstance(exc, TimeoutError):
            # `socket.timeout` is an alias of TimeoutError on Python 3.10+.
            return "timeout"
        elif isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
            return "sqlite_locked"
        elif isinstance(exc, (urllib.error.URLError, OSError)):
            return "transport_error"
        return "parse_error"
    if code in (404, 410):
        return f"http_{code}_gone"
    if code == 403:
        return "http_403_forbidden"
    if code == 408:
        # A scraper-synthesised "we timed out" code, never a server response.
        return "timeout"
    if code == 429:
        return "http_429_rate_limited"
    if code and code >= 500:
        return "http_5xx_upstream_error"
    # `0` is what a scraper returns for "no response at all" — a connection
    # failure, not a page. It is falsy, so it must not fall through to the
    # parse-nothing default below.
    if code is not None and code != 200:
        return "transport_error"
    return "parse_no_releases"


#: Causes that mean "asking again right now makes it worse": the host is dark,
#: rate-limiting us, or bot-checking every page. A whole run of these is not a
#: backlog to grind through, it is a site we cannot crawl — world4ufree burned
#: 2,921 requeued rows in 12.8 seconds, which is only possible if every request
#: failed without ever returning a page.
SITE_DARK_CAUSES = frozenset({
    "transport_error",
    "timeout",
    "http_403_forbidden",
    "http_429_rate_limited",
    "http_5xx_upstream_error",
    "blocked_challenge",
})


def crawl_attempt_state(
    cause: str | None,
    *,
    prior_attempts: int = 0,
    permanent: frozenset = PERMANENT_CRAWL_CAUSES,
    max_attempts: int = MAX_CRAWL_ATTEMPTS,
) -> tuple[int, int]:
    """``(scraped, attempts)`` to book for a FAILED crawl attempt.

    Both outcomes are still ``-1`` — what separates them is the attempt count.
    A permanent cause parks the row on the first sighting (a 404 does not turn
    into a 200 because we asked twice more), while a transient one spends its
    retry budget and stays selectable by ``select_crawl_candidates`` until that
    budget runs out. The per-site staging crawlers use this same rule so an
    operator reads one vocabulary everywhere, with ``last_cause`` saying which
    of "gone upstream" and "we could not read it" a ``-1` actually means.
    """
    attempts = max(0, int(prior_attempts)) + 1
    if cause in permanent:
        return -1, max_attempts
    return -1, min(attempts, max_attempts)


def retry_backoff(attempt: int, *, base: float = 2.0, cap: float = 60.0) -> float:
    """Seconds to sit out before re-trying a transiently-failed URL in the same pass."""
    return min(cap, base * (2 ** max(0, int(attempt) - 1)))


class ConsecutiveFailureFuse:
    """Thread-safe stop signal for a pass that is failing for ONE external reason.

    counting individual failures is useless in a backlog; counting *consecutive*
    transport/403/429/5xx failures finds the case where the whole domain is dark
    or is bot-checking us. When it trips the crawler stops spending requests and
    leaves the rest of the queue untouched, so "abandoned" and "failed" stay
    distinguishable rows instead of thousands of identical ``-1``.
    """

    def __init__(self, threshold: int = 25, causes: frozenset = SITE_DARK_CAUSES):
        self.threshold = max(1, int(threshold))
        self.causes = causes
        self._streak = 0
        self._trip_reason: str | None = None
        self._lock = threading.Lock()

    @property
    def tripped(self) -> bool:
        return self._trip_reason is not None

    @property
    def streak(self) -> int:
        return self._streak

    @property
    def trip_reason(self) -> str | None:
        return self._trip_reason

    def record(self, cause: str | None) -> bool:
        """Book one outcome; True when this call tripped the fuse."""
        with self._lock:
            if cause in self.causes:
                self._streak += 1
                if self._trip_reason is None and self._streak >= self.threshold:
                    self._trip_reason = cause
                return self._trip_reason is not None
            self._streak = 0
            return False


def crawl_failure_breakdown(site: str | None = None, *, db_conn=None) -> list:
    """(cause, parked_count) for the failures the crawler gave up on."""
    sql = ("SELECT COALESCE(last_cause, 'unrecorded') AS cause, COUNT(*) "
           "FROM sitemap_cache WHERE scraped = -1")
    params: tuple = ()
    if site:
        sql += " AND site = ?"
        params = (site,)
    sql += " GROUP BY cause ORDER BY COUNT(*) DESC"
    if db_conn is not None:
        return db_conn.execute(sql, params).fetchall()
    with get_db() as conn:
        return conn.execute(sql, params).fetchall()


def record_crawl_attempt(url: str, *, indexed: bool, cause: str | None = None) -> None:
    """Stamp the crawl outcome; a failed page stays eligible until MAX_CRAWL_ATTEMPTS.

    `cause` is written to `sitemap_cache.last_cause` so `-1` stops being one opaque
    wall: a permanent cause parks the row immediately, a transient one leaves it in
    the retry budget, and a later reader can count the two apart.
    """
    parked_permanently = (not indexed) and cause in PERMANENT_CRAWL_CAUSES
    with get_db() as conn:
        if indexed:
            conn.execute(
                "UPDATE sitemap_cache SET scraped = 1, attempts = attempts + 1,"
                " last_attempt = ?, last_cause = NULL WHERE loc = ?",
                (time.time(), url),
            )
        else:
            conn.execute(
                "UPDATE sitemap_cache SET scraped = -1,"
                " attempts = CASE WHEN ? = 1 THEN ? ELSE attempts + 1 END,"
                " last_attempt = ?, last_cause = ? WHERE loc = ?",
                (1 if parked_permanently else 0, MAX_CRAWL_ATTEMPTS, time.time(),
                 cause, url),
            )


def select_crawl_candidates(conn, site_filter: str | None = None, limit: int = 5) -> list:
    """Pages worth crawling now: never-tried first, then failures still inside the budget."""
    retryable = MAX_CRAWL_ATTEMPTS
    if site_filter:
        return conn.execute(
            "SELECT loc, site FROM sitemap_cache"
            " WHERE site = ? AND (scraped = 0 OR (scraped = -1 AND attempts < ?))"
            " ORDER BY scraped DESC, lastmod DESC LIMIT ?",
            (site_filter, retryable, limit),
        ).fetchall()
    return conn.execute(
        "SELECT loc, site FROM sitemap_cache"
        " WHERE scraped = 0 OR (scraped = -1 AND attempts < ?)"
        " ORDER BY scraped DESC, lastmod DESC LIMIT ?",
        (retryable, limit),
    ).fetchall()

# ── Health Checker, Resumability & Self-Healing ───────────────────────────────

def probe_single_source(src: dict, timeout: int = 8) -> dict:
    """
    Probes a download source for:
    - HTTP Status code (200, 206, 302, 400, 404, 403, 500)
    - Status: 'active', 'dead', 'expired'
    - Resumability: tests HTTP Range request support (status 206, Accept-Ranges, Content-Range)
    - Exact file size in bytes
    - MIME type (Content-Type)
    - Latency (ms)
    """
    url = src["final_url"]
    headers = {
        "User-Agent": USER_AGENT,
        "Range": "bytes=0-100",
    }
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency_ms = int((time.time() - t0) * 1000)
            http_status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            crange = resp.headers.get("Content-Range", "")
            aranges = resp.headers.get("Accept-Ranges", "")
            clen = resp.headers.get("Content-Length")

            # Extract exact file size if available from Content-Range or Content-Length
            file_bytes = None
            if crange and "/" in crange:
                total_part = crange.split("/")[-1].strip()
                if total_part.isdigit():
                    file_bytes = int(total_part)
            elif clen and clen.isdigit():
                file_bytes = int(clen)

            is_resumable = int(http_status == 206 or (aranges and "bytes" in aranges.lower()) or bool(crange))
            status = "active" if http_status in (200, 206, 302) else "dead"

            return {
                "id": src["id"],
                "status": status,
                "is_resumable": is_resumable,
                "http_status": http_status,
                "file_size_bytes": file_bytes,
                "mime_type": ctype.split(";")[0].strip() if ctype else None,
                "latency_ms": latency_ms,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        latency_ms = int((time.time() - t0) * 1000)
        status = "expired" if e.code in (401, 403) else "dead"
        return {
            "id": src["id"],
            "status": status,
            "is_resumable": 0,
            "http_status": e.code,
            "file_size_bytes": None,
            "mime_type": None,
            "latency_ms": latency_ms,
            "error": f"HTTP {e.code} ({e.reason})",
        }
    except Exception as ex:
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "id": src["id"],
            "status": "dead",
            "is_resumable": 0,
            "http_status": 0,
            "file_size_bytes": None,
            "mime_type": None,
            "latency_ms": latency_ms,
            "error": str(ex),
        }


def run_health_check(post_id: int | None = None, dead_only: bool = False, max_workers: int = 12, verbose: bool = True) -> list[dict]:
    """
    Scans download sources, performs live status probes & resumability checks,
    and updates the database.
    """
    init_db()
    with get_db() as conn:
        if post_id:
            query = """
                SELECT s.id, s.final_url, s.source_name, s.service, r.release_title, p.clean_title
                FROM download_sources s
                JOIN releases r ON s.release_id = r.id
                JOIN posts p ON r.post_id = p.id
                WHERE p.id = ?
            """
            params = [post_id]
        else:
            query = """
                SELECT s.id, s.final_url, s.source_name, s.service, r.release_title, p.clean_title
                FROM download_sources s
                JOIN releases r ON s.release_id = r.id
                JOIN posts p ON r.post_id = p.id
                WHERE 1=1
            """
            params = []

        if dead_only:
            query += " AND s.status IN ('dead', 'expired')"

        rows = conn.execute(query, params).fetchall()

    if not rows:
        if verbose:
            print("[i] No sources found matching health check criteria.")
        return []

    if verbose:
        print("\n" + "=" * 80)
        print(f"🩺 Fast_Fetch Link Health & Resumability Diagnostic ({len(rows)} sources)")
        print("=" * 80)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(probe_single_source, dict(r)): r for r in rows}
        for fut in as_completed(future_map):
            r = future_map[fut]
            try:
                probe_res = fut.result()
                results.append((r, probe_res))
                if verbose:
                    st = probe_res["status"]
                    icon = "🟢" if st == "active" else ("🟡" if st == "expired" else "🔴")
                    res_tag = "⚡ Resumable" if probe_res["is_resumable"] else "📦 Stream"
                    size_mb = f"{probe_res['file_size_bytes'] / (1024 * 1024):.1f}MB" if probe_res["file_size_bytes"] else "N/A"
                    err_info = f" ({probe_res['error']})" if probe_res["error"] else ""
                    print(f"  {icon} [{probe_res['http_status'] or 'ERR':>3}] {r['source_name'][:24]:<24} | {res_tag:<11} | {size_mb:<8} | {probe_res['latency_ms']:>4}ms{err_info}", flush=True)
            except Exception as ex:
                if verbose:
                    print(f"  🔴 Error probing #{r['id']}: {ex}", flush=True)

    # Persist health check updates to database
    if results:
        with get_db() as conn:
            update_data = [
                (
                    pres["status"],
                    pres["is_resumable"],
                    pres["http_status"],
                    pres["file_size_bytes"],
                    pres["mime_type"],
                    pres["id"],
                )
                for _, pres in results
            ]
            conn.executemany("""
                UPDATE download_sources
                SET status = ?, is_resumable = ?, http_status = ?, file_size_bytes = ?, mime_type = ?,
                    last_checked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, update_data)

    if verbose:
        active_c = sum(1 for _, p in results if p["status"] == "active")
        dead_c = sum(1 for _, p in results if p["status"] == "dead")
        exp_c = sum(1 for _, p in results if p["status"] == "expired")
        res_c = sum(1 for _, p in results if p["is_resumable"])
        print("-" * 80)
        print(f"Summary: 🟢 Active: {active_c} | ⚡ Resumable: {res_c} | 🟡 Expired: {exp_c} | 🔴 Dead: {dead_c}")
        print("=" * 80 + "\n")

    return [pres for _, pres in results]


def heal_post_links(post_id: int, verbose: bool = True) -> dict:
    """
    Self-healing link engine:
    Re-scrapes Nexdrive / intermediate bridges to regenerate fresh, live tokens
    and direct URLs for dead or expired sources.
    """
    init_db()
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            if verbose:
                print(f"[!] Post #{post_id} not found.")
            return {"healed": 0, "error": "Post not found"}

        dead_sources = conn.execute("""
            SELECT s.id, s.release_id, r.intermediate_url, r.release_title
            FROM download_sources s
            JOIN releases r ON s.release_id = r.id
            WHERE r.post_id = ? AND s.status IN ('dead', 'expired')
        """, (post_id,)).fetchall()

    if not dead_sources:
        if verbose:
            print(f"[✓] Post #{post_id} has no dead or expired links. Everything is healthy!")
        return {"healed": 0, "status": "All healthy"}

    if verbose:
        print(f"\n[🔄] Self-Healing Post #{post_id} ('{post['clean_title']}')...")
        print(f"     Found {len(dead_sources)} dead/expired sources to revive.")

    # Re-extract post data
    fresh_data = extract_post_data(post["url"], verbose=verbose)
    if not fresh_data:
        if verbose:
            print("[!] Could not re-extract post from source site.")
        return {"healed": 0, "error": "Fetch failed"}

    # Save fresh data atomically
    save_scraped_data(fresh_data)

    # Re-run health check on the newly resolved sources
    if verbose:
        print("[i] Verifying fresh links health...")
    health = run_health_check(post_id=post_id, verbose=verbose)
    healed_count = sum(1 for h in health if h["status"] == "active")

    if verbose:
        print(f"[✓] Successfully healed Post #{post_id}! {healed_count} sources are now verified active.\n")

    return {"healed": healed_count, "total_active": healed_count}


# ── Observed link expiry (HANDOFF_apidocs A5) ────────────────────────────────
#
# Nothing used to write `cat_links.expires_at`, so `/play` sent a bundle-level
# 900 s that had nothing behind it and `resolve_live_source()` guessed at
# temporality with a 6-hour `last_checked_at` heuristic. These three functions
# replace the guess with a measurement where one is available, and stay silent
# (NULL, never a fabricated number) where it is not.
#
# An upstream CDN can lie or publish absurd windows (a year, or 0), so what we
# record is clamped into a band that is honest *for us*: short enough that a
# client never plays a dead URL believing the doc, long enough that we do not
# re-resolve a healthy link every second.
LINK_TTL_MAX_SECONDS = 900.0
LINK_TTL_MIN_SECONDS = 5.0


def parse_observed_ttl(headers, *, now: float | None = None) -> float | None:
    """Seconds a URL is still good for, read from the response's own headers.

    Accepts any case-insensitive mapping (or list of pairs). Only statements
    about *freshness* are honoured:

      Cache-Control: max-age=N   (or s-maxage=N when max-age is absent)
      Expires: <HTTP-date>

    `no-store` / `no-cache` are deliberately NOT read as "expired": they forbid
    an HTTP cache from re-serving the body, which says nothing about whether the
    signed token in the query string still works — treating them as 0 would make
    every honest CDN link look dead. No directive at all returns None, which the
    caller records as "never observed" rather than as a made-up TTL.
    """
    if not headers:
        return None
    now_ts = time.time() if now is None else float(now)
    get = headers.get if hasattr(headers, "get") else dict(headers).get

    def _lookup(name: str):
        value = get(name)
        if value is not None:
            return value
        low = name.lower()
        for key, val in (headers.items() if hasattr(headers, "items") else []):
            if str(key).lower() == low:
                return val
        return None

    ttl: float | None = None
    cc = _lookup("Cache-Control")
    if cc:
        ages = {}
        for part in str(cc).lower().split(","):
            if "=" in part:
                k, _, v = part.partition("=")
                try:
                    ages[k.strip()] = float(v.strip().strip('"'))
                except ValueError:
                    continue
        if "max-age" in ages:
            ttl = ages["max-age"]
        elif "s-maxage" in ages:
            ttl = ages["s-maxage"]

    if ttl is None:
        expires = _lookup("Expires")
        if expires:
            try:
                from email.utils import parsedate_to_datetime
                exp_dt = parsedate_to_datetime(str(expires))
            except Exception:
                exp_dt = None
            if exp_dt is not None:
                try:
                    ttl = exp_dt.timestamp() - now_ts
                except (OverflowError, OSError, ValueError):
                    ttl = None

    if ttl is None:
        return None
    if ttl <= 0:
        return 0.0
    # A declared window longer than our band is not trusted wholesale: the
    # longest real expiry we will promise a client is LINK_TTL_MAX_SECONDS.
    return min(float(ttl), LINK_TTL_MAX_SECONDS)


def probe_url_ttl(url: str, *, timeout: int = 6, headers: dict | None = None) -> tuple[float | None, dict]:
    """Knock on a resolved URL and report its own freshness window.

    Returns ``(ttl_seconds_or_None, {"observed": bool, "reason": str, ...})``.
    Tries HEAD first (one packet, no body) and falls back to a 1-byte ranged GET,
    because plenty of hosters answer 405/501 to HEAD. Never raises: a link we can
    serve but cannot interrogate simply has no observed TTL, and the caller must
    be able to tell "the host answered and declared nothing" (`no_directive`)
    from "we never got through" (`unreachable`) — only the first is information.
    """
    if not url or not url.startswith("http"):
        return None, {"observed": False, "reason": "not_a_url"}
    base = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Ranges": "bytes",
    }
    if headers:
        base.update(headers)
    attempts = (
        ("HEAD", {}),
        ("GET", {"Range": "bytes=0-0"}),
    )
    for method, extra in attempts:
        req = urllib.request.Request(url, headers={**base, **extra}, method=method)
        try:
            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=timeout) as resp:
                raw = dict(resp.headers)
                status = resp.status
                try:
                    resp.read(1)
                except Exception:
                    pass
        except Exception:
            continue
        ttl = parse_observed_ttl(raw)
        if ttl is None:
            return None, {"observed": False, "reason": "no_directive", "http": status}
        return ttl, {
            "observed": True,
            "ttl": ttl,
            "expires_at": time.time() + ttl,
            "http": status,
        }
    return None, {"observed": False, "reason": "unreachable"}


def record_link_expiry(source_id: int, ttl_seconds: float | None = None, *,
                       expires_at: float | None = None,
                       observed_via: str = "probe",
                       clear: bool = False) -> float | None:
    """Persist an observed expiry on the ledger link and its projected twin.

    Writes `download_sources.expires_at` (the ledger, our side of the boundary)
    and mirrors it onto `cat_links.expires_at` through
    `cat_links.ledger_link_id`, which is the link the v2 projector published from
    this exact row. The projection stays the projection: it is disposable, and a
    rebuild simply re-derives `expires_at` as NULL until the next resolve reports
    a fresh measurement — so writing through here is a cache fill, not an edit.

    A call with nothing to report leaves the previous observation alone; only
    `clear=True` deliberately writes NULL, which the resolve path uses when the
    host answered and declared no lifetime for the URL it just issued.
    Returns the stored `expires_at` (None when the row was cleared or not written).
    """
    if clear:
        expires_at = None
    elif expires_at is None:
        if ttl_seconds is None:
            return None
        expires_at = time.time() + max(0.0, float(ttl_seconds))
    stored = None if expires_at is None else float(expires_at)
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE download_sources SET expires_at = ?, ttl_source = ?,"
                " last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                (stored, observed_via, int(source_id)),
            )
            # The projected catalog may live in another file, or not exist yet.
            try:
                conn.execute(
                    "UPDATE cat_links SET expires_at = ? WHERE ledger_link_id = ?",
                    (stored, int(source_id)),
                )
            except sqlite3.Error:
                pass
    except sqlite3.Error:
        return None
    return stored


def _expiry_fields(src: dict, *, now: float | None = None) -> dict:
    """The published freshness pair for a resolve answer.

    `expires_in` is relative because a client cannot trust the server clock;
    `expires_at` is absolute so `/play` can echo the same instant it was given.
    Both are None when we have never measured — silence, not a made-up window.
    """
    raw = src.get("expires_at")
    if raw is None:
        return {"expires_at": None, "expires_in": None}
    try:
        stamp = float(raw)
    except (TypeError, ValueError):
        return {"expires_at": None, "expires_in": None}
    remaining = stamp - (time.time() if now is None else now)
    return {"expires_at": stamp, "expires_in": max(0.0, round(remaining, 3))}


_RESOLVERS = None


def _embed_resolvers():
    """`importers/host_resolvers.py`, imported on first use rather than at import.

    The unpackers for mxdrop and pkembed live with the importers that discovered
    them. Resolved lazily because the module graph must not be able to cycle:
    `host_resolvers` imports nothing from here today, and a top-level import would
    turn any future reverse dependency into a startup failure instead of a
    resolver call.

    A missing or broken module is `None`, not an exception: the JIT path then
    simply has no embed branch, and every other host resolves as before.
    """
    global _RESOLVERS
    if _RESOLVERS is None:
        directory = str(Path(__file__).resolve().parent / "importers")
        if directory not in sys.path:
            sys.path.insert(0, directory)
        try:
            import host_resolvers
        except (ImportError, OSError, SyntaxError):
            return None
        _RESOLVERS = host_resolvers
    return _RESOLVERS


def resolve_live_source(source_id: int, *, v2: bool = False) -> dict:
    """
    Just-In-Time (JIT) live stream resolver:
    Given a download_sources ID, returns an active, stream-ready URL.
    - If permanent (is_temporary == 0) and active: returns cached final_url instantly.
    - If temporary (is_temporary == 1) or expired: re-resolves the source_url
      bridge on-the-fly, updates the database cache with the fresh token, and returns it.

    ``v2=True`` selects the honest resolution contract for the v2 API (API_V2.md §12,
    HANDOFF_apidocs B13) and changes nothing on the default path, which the shipped
    v1 app depends on:
    - an unknown id and an adult-flagged id return the *same* failure envelope
      (``code == "not_found"``) so a restricted title is indistinguishable from an
      absent one, instead of leaking the words "18+" / "restricted";
    - when re-resolution fails, the answer is an honest
      ``code == "no_playable_source"`` failure rather than ``success: true`` carrying
      a stale URL, so a dead link can never look alive to the caller.
    """
    init_db()
    not_found = {"success": False, "error": "not_found", "code": "not_found"}
    with get_db() as conn:
        row = conn.execute("SELECT * FROM download_sources WHERE id = ?", (source_id,)).fetchone()
        if row:
            adult = conn.execute(
                "SELECT p.is_18_plus FROM download_sources s "
                "JOIN releases r ON r.id = s.release_id "
                "JOIN posts p ON p.id = r.post_id WHERE s.id = ?",
                (source_id,),
            ).fetchone()
            if adult and adult[0]:
                if v2:
                    # Identical to a missing id: never say why.
                    return dict(not_found)
                return {"success": False, "error": "Source restricted (18+ content)"}
    if not row:
        if v2:
            return dict(not_found)
        return {"success": False, "error": f"Source #{source_id} not found"}

    src = dict(row)
    now_ts = time.time()

    needs_refresh = False
    observed_expiry = _expiry_fields(src)
    if src["status"] in ("dead", "expired"):
        needs_refresh = True
    elif observed_expiry["expires_in"] is not None:
        # A measured window beats the heuristic: if we recorded that this token
        # dies in 20 minutes, it is not "fresh" just because we last looked at it
        # an hour ago — and equally it is not stale after 25 minutes.
        needs_refresh = observed_expiry["expires_in"] <= 0
    elif src.get("final_url") and is_bridge_url(src["final_url"]):
        # A cached landing page (HubCloud `/drive/…`, FastDL embed, GDFlix
        # `/file/…`, PixelDrain `/u/…`) is not playable media. Re-resolve it
        # instead of handing ExoPlayer HTML.
        needs_refresh = True
    elif src["is_temporary"]:
        if not src.get("last_checked_at"):
            needs_refresh = True
        else:
            try:
                t_struct = time.strptime(str(src["last_checked_at"]).split(".")[0], "%Y-%m-%d %H:%M:%S")
                age_hours = (now_ts - time.mktime(t_struct)) / 3600.0
                if age_hours > 6.0:
                    needs_refresh = True
            except Exception:
                needs_refresh = True

    if not needs_refresh and src.get("final_url"):
        return {
            "success": True,
            "id": src["id"],
            "url": src["final_url"],
            "cached": True,
            "refreshed": False,
            "service": src["service"],
            "is_temporary": bool(src["is_temporary"]),
            "is_resumable": bool(src["is_resumable"]),
            "source_name": src["source_name"],
            "mime_type": src.get("mime_type"),
            "file_size_bytes": src.get("file_size_bytes"),
            **observed_expiry,
        }

    # Needs fresh unwrap
    source_u = src.get("source_url") or src.get("final_url") or ""
    cached_u = src.get("final_url") or ""
    service = src.get("service") or ""
    fresh_url = None
    fresh_temp = src["is_temporary"]
    embed_verdict = None

    def hoster_input(marker):
        """The stored address that actually names this hoster.

        `source_url` is usually the site's own landing page; the hoster id often
        lives only in a previously unwrapped `final_url`. Prefer whichever one
        names the service, so a cached bridge can still be refreshed instead of
        being discarded as unresolvable.
        """
        low_source = source_u.lower()
        low_cached = cached_u.lower()
        if marker in low_source:
            return source_u
        if marker in low_cached:
            return cached_u
        return source_u

    def embed_from_verdict(verdict) -> str | None:
        """A packer's answer is a stream only when it says so itself.

        `verify=True` means the resolver already knocked on the byte endpoint with
        a 512-byte Range request, so `active` is a measurement rather than an
        assumption. Every other verdict — `unverified`, `expired`, `unknown`,
        `js_required` — is a page it could unpack but a file it could not read,
        and the caller below refuses it instead of persisting it as playable.
        """
        if isinstance(verdict, dict) and verdict.get("status") == "active":
            return verdict.get("final_url") or None
        return None

    try:
        hr = _embed_resolvers()
        if (service in ("fsl_r2", "hubcloud_10g", "hubcloud")
                or "hubcloud" in source_u.lower() or "hubcloud" in cached_u.lower()):
            hub = hoster_input("hubcloud")
            # `gpdl…hubcloud` is a redirector that carries the Google CDN URL in
            # its own Location; `/drive/<id>` is a landing page that needs the
            # gamerxyt hop. Try the cheap one for a gpdl URL first.
            if "gpdl" in hub:
                direct_u, _svc, is_temp = unwrap_hubcloud(hub)
                if is_direct_media_url(direct_u):
                    fresh_url = direct_u
                    fresh_temp = is_temp
            if not fresh_url:
                unwrapped = unwrap_hubcloud_drive(hub)
                for item in unwrapped:
                    if item.get("service") == service:
                        fresh_url = item.get("final_url")
                        fresh_temp = item.get("is_temporary", fresh_temp)
                        break
                if not fresh_url and unwrapped:
                    fresh_url = unwrapped[0].get("final_url")
                    fresh_temp = unwrapped[0].get("is_temporary", fresh_temp)
        elif (service == "direct_cloud" or "direct-cloud" in source_u.lower()
              or "direct-cloud" in cached_u.lower()):
            fresh_url, _, fresh_temp = unwrap_direct_cloud(hoster_input("direct-cloud"))
        elif (service == "greenmotors" or "greenmotors" in source_u.lower()
              or "greenmotors" in cached_u.lower()):
            unwrapped = unwrap_greenmotors(hoster_input("greenmotors"))
            if unwrapped:
                fresh_url = unwrapped[0].get("final_url")
                fresh_temp = unwrapped[0].get("is_temporary", fresh_temp)
        elif (service == "vcloud" or "vcloud" in source_u.lower()
              or "vcloud" in cached_u.lower()):
            v_res = unwrap_vcloud(hoster_input("vcloud"))
            if v_res:
                fresh_url = v_res[0][2]
                fresh_temp = v_res[0][3]
        elif (service == "fastdl" or "fastdl" in source_u.lower()
              or "fastdl" in cached_u.lower()):
            # FastDL's `embed.php?download=<id>` page carries `var reurl = …`;
            # `unwrap_hubcloud` knows nothing about that shape.
            direct_u, _res_id, is_temp = unwrap_fastdl(hoster_input("fastdl"))
            fresh_url = direct_u
            fresh_temp = is_temp
        elif (service == "gdflix" or "gdflix" in source_u.lower()
              or "gdflix" in cached_u.lower()):
            direct_u, _res_id, is_temp = unwrap_gdflix(hoster_input("gdflix"))
            fresh_url = direct_u
            fresh_temp = is_temp
        elif (service == "pixeldrain" or "pixeldrain" in source_u.lower()
              or "pixeldrain" in cached_u.lower()):
            direct_u, _, is_temp = unwrap_pixeldrain(hoster_input("pixeldrain"))
            fresh_url = direct_u
            fresh_temp = is_temp
        elif (service == "vegadrive" or "vegadrive" in source_u.lower()
              or "vegadrive" in cached_u.lower()):
            direct_u, _, is_temp = unwrap_vegadrive(hoster_input("vegadrive"))
            fresh_url = direct_u
            fresh_temp = is_temp
        elif hr and (service == hr.SERVICE_MXDROP or "mxdrop" in source_u.lower()
                     or "mxdrop" in cached_u.lower()):
            # The embed URL is the durable identifier and the mp4 is a result of
            # this call: mxdrop signs its `MDCore.wurl` with a ~6-hour window.
            embed = cached_u if hr.is_mxdrop_embed(cached_u) else source_u
            verdict = hr.unwrap_mxdrop(embed, verify=True)
            direct_u = embed_from_verdict(verdict)
            if direct_u:
                fresh_url = direct_u
                fresh_temp = 1
                embed_verdict = verdict
        elif hr and (service == hr.SERVICE_PKEMBED or "pkembed" in source_u.lower()
                     or "pkembed" in cached_u.lower()):
            embed = cached_u if hr.is_pkembed_embed(cached_u) else source_u
            verdict = hr.unwrap_pkembed(embed, verify=True)
            direct_u = embed_from_verdict(verdict)
            if direct_u:
                fresh_url = direct_u
                fresh_temp = 1
                embed_verdict = verdict
        elif "gamerxyt" in source_u.lower() or "gamerxyt" in cached_u.lower():
            gamer = hoster_input("gamerxyt")
            if "link=" in gamer:
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(gamer).query)
                candidate = urllib.parse.unquote((query.get("link") or [""])[0])
                if candidate:
                    fresh_url = candidate
                    fresh_temp = 1
    except Exception:
        pass

    # A resolver that answered with another landing page has not resolved
    # anything. Never persist it as the playable address: the callers below treat
    # "no fresh direct URL" honestly instead of sending ExoPlayer HTML.
    if fresh_url and is_bridge_url(fresh_url) and not is_direct_media_url(fresh_url):
        fresh_url = None

    if fresh_url and fresh_url != source_u:
        # A packer's verdict carries more than a URL. `verify=True` means the
        # resolver already read the first 512 bytes of the file, so its container,
        # its length and the status it came back with are measurements we paid
        # for; storing them saves the next probe and answers the seek question from
        # evidence. Every other hoster still gets the plain five-column update.
        measured = [(column, value) for column, value in (
            ("mime_type", (embed_verdict or {}).get("content_type")),
            ("file_size_bytes", (embed_verdict or {}).get("size_bytes")),
            ("http_status", (embed_verdict or {}).get("http_status")),
            ("is_resumable", 1 if (embed_verdict or {}).get("http_status") == 206 else None),
        ) if value is not None]
        for column, value in measured:
            src[column] = value
        with get_db() as conn:
            conn.execute(f"""
                UPDATE download_sources
                SET final_url = ?, is_temporary = ?, status = 'active',
                    last_checked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    {"".join(f", {column} = ?" for column, _value in measured)}
                WHERE id = ?
            """, (fresh_url, fresh_temp, *(value for _column, value in measured),
                  src["id"]))
        # Ask the URL itself how long it lives, instead of assuming. A fresh token
        # whose host declares no freshness window keeps `expires_at` NULL, and the
        # next call then falls back to the documented 6-hour temporary-link
        # ceiling rather than to a number we invented for it.
        observed_ttl, observed_info = probe_url_ttl(fresh_url)
        signed_ttl = (embed_verdict or {}).get("expires_in")
        expires_at = observed_info.get("expires_at")
        if expires_at is not None:
            record_link_expiry(src["id"], observed_ttl, expires_at=expires_at,
                               observed_via="response_headers")
            src["expires_at"] = expires_at
        elif isinstance(signed_ttl, (int, float)):
            # The packer CDNs answer with no Cache-Control and no Expires, so
            # `probe_url_ttl` honestly reports `no_directive` — but the lifetime is
            # not missing, it is signed into the query the packer handed us, and
            # `host_resolvers` already parsed it (`e` for mxdrop, `s` + `e` for
            # pkembed). Recording that number is what makes the cached answer
            # honest: without it a one-hour token would be served stale for five
            # hours, because the ceiling below is a six-hour guess.
            expires_at = time.time() + max(0.0, float(signed_ttl))
            record_link_expiry(src["id"], expires_at=expires_at,
                               observed_via="signed_params")
            src["expires_at"] = expires_at
        elif observed_info.get("reason") == "no_directive":
            # The host answered and declared nothing: drop any older measurement
            # so a stale, longer window cannot outlive the token it was read from.
            record_link_expiry(src["id"], clear=True, observed_via="no_directive")
            src["expires_at"] = None
        return {
            "success": True,
            "id": src["id"],
            "url": fresh_url,
            "cached": False,
            "refreshed": True,
            "service": src["service"],
            "is_temporary": bool(fresh_temp),
            "is_resumable": bool(src["is_resumable"]),
            "source_name": src["source_name"],
            "mime_type": src.get("mime_type"),
            "file_size_bytes": src.get("file_size_bytes"),
            **_expiry_fields(src),
        }

    # Nothing could be re-resolved. The legacy (v1) contract keeps handing back the
    # last known URL so the shipped app's behaviour is frozen, but the answer is now
    # flagged honestly (`stale: True`) and the ledger is marked so the projection can
    # demote the link's measured state instead of treating it as verified. The v2
    # contract refuses the stale URL outright: a link we could not re-resolve is a
    # failure, not a success.
    try:
        if src["status"] in ("dead", "expired") or src["is_temporary"]:
            with get_db() as conn:
                conn.execute(
                    "UPDATE download_sources SET status = 'expired', "
                    "last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (src["id"],),
                )
    except Exception:
        pass
    stale_url = src.get("final_url") or src.get("source_url")
    bridge_stale = bool(stale_url) and is_bridge_url(stale_url)
    if v2 or bridge_stale:
        # v1 keeps its frozen stale-URL behaviour for a real media address, but a
        # bridge page is never a playable answer in either contract: ExoPlayer
        # would fetch HTML and fail. Say "no playable source" instead of handing
        # the caller a landing page.
        return {
            "success": False,
            "id": src["id"],
            "error": "no_playable_source",
            "code": "no_playable_source",
            "reason": "bridge_unresolved" if bridge_stale else "re_resolve_failed",
            "stale": True,
        }
    return {
        "success": True,
        "id": src["id"],
        "url": stale_url,
        "cached": True,
        "refreshed": False,
        "stale": True,
        "service": src["service"],
        "is_temporary": bool(src["is_temporary"]),
        "is_resumable": bool(src["is_resumable"]),
        "source_name": src["source_name"],
        "mime_type": src.get("mime_type"),
        "file_size_bytes": src.get("file_size_bytes"),
        **_expiry_fields(src),
    }


def heal_expiring_sources(max_age_hours: int = 6, limit: int = 50, verbose: bool = True) -> dict:
    """
    Proactively heals temporary/expiring sources (Tier 2 signed CDN tokens)
    before they expire. Sweeps links where is_temporary=1 and last_checked_at > max_age_hours.
    """
    init_db()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, source_name, service, source_url, final_url
            FROM download_sources
            WHERE is_temporary = 1
              AND (
                  status IN ('expired', 'dead')
                  OR last_checked_at IS NULL
                  OR last_checked_at < datetime('now', ? || ' hours')
              )
            ORDER BY id ASC
            LIMIT ?
        """, (f"-{max_age_hours}", limit)).fetchall()

    if not rows:
        if verbose:
            print("[✓] All temporary download sources are currently healthy and within TTL!")
        return {"healed": 0, "total_examined": 0}

    if verbose:
        print("\n" + "=" * 65)
        print(f"🔄 Proactive Healing Sweep: {len(rows)} expiring sources found")
        print("=" * 65)

    healed_count = 0
    for r in rows:
        res = resolve_live_source(r["id"])
        if res.get("refreshed"):
            healed_count += 1
            if verbose:
                print(f"  ⚡ Healed #{r['id']} [{r['service']}]: {res['url'][:60]}...")
        elif res.get("success"):
            if verbose:
                print(f"  ✓ Valid #{r['id']} [{r['service']}]")
        else:
            if verbose:
                print(f"  ✗ Failed #{r['id']} [{r['service']}]: {res.get('error')}")

    if verbose:
        print(f"\n[✓] Sweep complete: {healed_count}/{len(rows)} sources refreshed with live tokens.\n")

    return {"healed": healed_count, "total_examined": len(rows)}


def start_healing_daemon(interval_hours: int = 6, max_iterations: int | None = None):
    """
    Runs an automated continuous background daemon that periodically heals
    expiring CDN links and pings mirror domains.
    """
    print("=" * 65)
    print(f"🛡️ Fast_Fetch Continuous Link-Healing Daemon Started")
    print(f"   Interval: Every {interval_hours} hours | Press Ctrl+C to stop")
    print("=" * 65)

    iteration = 0
    while True:
        iteration += 1
        print(f"\n[⏰] Daemon Cycle #{iteration} starting at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
        try:
            ping_domains(verbose=True)
            heal_expiring_sources(max_age_hours=interval_hours, verbose=True)
        except Exception as e:
            print(f"[!] Daemon error in cycle #{iteration}: {e}")

        if max_iterations and iteration >= max_iterations:
            print(f"[✓] Daemon completed requested {max_iterations} iterations.")
            break

        print(f"[i] Sleeping for {interval_hours} hours until next cycle...")
        time.sleep(interval_hours * 3600)


def ping_domains(verbose: bool = True) -> list[dict]:
    """
    Tests all configured domains, detects HTTP 301/302 redirects, and auto-updates
    domains in the database when sites migrate.
    """
    init_db()
    with get_db() as conn:
        rows = conn.execute("SELECT name, url FROM domains_config").fetchall()

    results = []
    if verbose:
        print("\n" + "=" * 65)
        print("🌐 Fast_Fetch Domain Health & Auto-Discovery Check")
        print("=" * 65)

    for r in rows:
        name, url = r["name"], r["url"]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=8) as resp:
                lat = int((time.time() - t0) * 1000)
                final_u = resp.geturl().rstrip("/")
                has_moved = final_u.lower() != url.rstrip("/").lower()
                if has_moved:
                    set_domain(name, final_u)
                    if verbose:
                        print(f"  🔀 {name:<12} : Migrated! {url} -> {final_u} (Auto-Updated in DB)")
                else:
                    if verbose:
                        print(f"  🟢 {name:<12} : Live ({lat}ms) | {url}")

                results.append({"name": name, "url": final_u, "status": "active", "latency": lat, "migrated": has_moved})
        except Exception as ex:
            if verbose:
                print(f"  🔴 {name:<12} : Offline/Blocked ({ex}) | {url}")
            results.append({"name": name, "url": url, "status": "offline", "error": str(ex)})

    if verbose:
        print("=" * 65 + "\n")
    return results


def migrate_domains_in_db(old_pattern: str, new_replacement: str) -> dict:
    """
    Rewrites historical URLs across posts, per-site pages, releases, and sitemaps.
    E.g. python fast_fetch.py domain migrate rogmovies.wtf rogmovies.one
    """
    init_db()
    with get_db() as conn:
        p_res = conn.execute("UPDATE posts SET url = replace(url, ?, ?) WHERE url LIKE ?", (old_pattern, new_replacement, f"%{old_pattern}%"))
        page_res = conn.execute("UPDATE post_sources SET url = replace(url, ?, ?) WHERE url LIKE ?", (old_pattern, new_replacement, f"%{old_pattern}%"))
        sm_res = conn.execute("UPDATE sitemap_cache SET loc = replace(loc, ?, ?) WHERE loc LIKE ?", (old_pattern, new_replacement, f"%{old_pattern}%"))
        r_res = conn.execute("UPDATE releases SET intermediate_url = replace(intermediate_url, ?, ?) WHERE intermediate_url LIKE ?", (old_pattern, new_replacement, f"%{old_pattern}%"))
        s_res = conn.execute("UPDATE download_sources SET source_url = replace(source_url, ?, ?), final_url = replace(final_url, ?, ?) WHERE source_url LIKE ? OR final_url LIKE ?",
                             (old_pattern, new_replacement, old_pattern, new_replacement, f"%{old_pattern}%", f"%{old_pattern}%"))
        d_res = conn.execute("UPDATE domains_config SET url = replace(url, ?, ?) WHERE url LIKE ?", (old_pattern, new_replacement, f"%{old_pattern}%"))

        return {
            "posts_updated": p_res.rowcount,
            "post_sources_updated": page_res.rowcount,
            "sitemaps_updated": sm_res.rowcount,
            "releases_updated": r_res.rowcount,
            "sources_updated": s_res.rowcount,
            "domains_updated": d_res.rowcount,
        }


# ── View & Reporting Helpers ──────────────────────────────────────────────────

def display_post_details(post_id: int) -> None:
    with get_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            print(f"[!] Post #{post_id} not found.")
            return

        print("\n" + "=" * 75)
        badge_18 = " [🔞 18+ ADULT]" if post["is_18_plus"] else ""
        badge_anim = " [🎨 ANIME/ANIMATED]" if post["is_animated"] else ""
        site_tag = (post["source_site"] or "vegamovies").upper()
        ind_tag = post["industry"] or "Hollywood"
        cnt_tag = post["country"] or "USA"
        lang_tag = post["language"] or "English"

        print(f"🎬 {post['clean_title']} ({post['year'] or 'Unknown Year'}){badge_18}{badge_anim}")
        print(f"🌐 First-seen site: {site_tag} | 🎭 Industry: {ind_tag} | 📍 Country: {cnt_tag} | 🗣️ Audio: {lang_tag}")
        print(f"🔗 URL : {post['url']}")
        page_rows = conn.execute(
            "SELECT source_site, url FROM post_sources WHERE post_id = ? ORDER BY source_site, url",
            (post_id,),
        ).fetchall()
        if page_rows:
            print("🔎 Site pages:")
            for page in page_rows:
                print(f"   [{page['source_site']}] {page['url']}")
        print(f"📁 Type: {post['content_type'].upper()}" + (f" | {post['seasons']}" if post['seasons'] else ""))
        if post["imdb_rating"]:
            print(f"⭐ IMDb: {post['imdb_rating']}")
        if post["genres"]:
            try:
                g_arr = json.loads(post["genres"])
                print(f"🏷️ Genres: {', '.join(g_arr)}")
            except Exception:
                print(f"🏷️ Genres: {post['genres']}")
        if post["poster_url"]:
            print(f"🖼️ Poster: {post['poster_url']}")
        if post["synopsis"]:
            print(f"📖 Synopsis: {post['synopsis'][:140]}...")
        print("=" * 75)

        releases = conn.execute("SELECT * FROM releases WHERE post_id = ? ORDER BY id ASC", (post_id,)).fetchall()
        if not releases:
            print("  (No releases indexed for this post)")
            return

        for r in releases:
            print(f"\n📦 [{r['quality'].upper()}] {r['release_title']}")
            print(f"   Size: {r['size'] or 'N/A'} | Audio: {r['languages'] or 'N/A'} | Codec: {r['codec'] or 'N/A'}")
            print(f"   Bridge: {r['intermediate_url']}")

            sources = conn.execute("SELECT * FROM download_sources WHERE release_id = ?", (r["id"],)).fetchall()
            for s in sources:
                st = s["status"]
                icon = "🟢" if st == "active" else ("🟡" if st == "expired" else "🔴")
                res_tag = " [⚡Resumable]" if s["is_resumable"] else " [📦Stream]"
                temp_flag = " ⏳(temp)" if s["is_temporary"] else ""
                size_str = f" ({s['file_size_bytes'] / (1024*1024):.1f}MB)" if s["file_size_bytes"] else ""
                print(f"     {icon} {s['source_name']}{res_tag}{size_str}{temp_flag}")
                print(f"        Final CDN: {s['final_url']}")
                print(f"        ID       : {s['resource_id']} [{s['service']}]")
        print("=" * 75 + "\n")


# ── CLI Interface ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fast_Fetch — Unified multi-site cinema & series scraper, direct link resolver, and cross-site canonical database builder"
    )
    subparsers = parser.add_subparsers(dest="command")

    SITE_CHOICES = ["vegamovies", "rogmovies", "ssrmovies", "7starhd", "katmoviehd", "multimovies", "10xflix", "hdhub4u", "bollyshares", "filmyzilla", "all"]
    SITE_INDIVIDUAL = ["vegamovies", "rogmovies", "ssrmovies", "7starhd", "katmoviehd", "multimovies", "10xflix", "hdhub4u", "bollyshares", "filmyzilla"]

    # sync
    sync_p = subparsers.add_parser("sync", help="Synchronize sitemaps/feeds into local cache")
    sync_p.add_argument("--site", choices=SITE_CHOICES, default="all", help="Source site to sync (default: all)")
    sync_p.add_argument("--limit", type=int, default=None, help="Limit number of sub-sitemaps to process")
    sync_p.add_argument("--categories", action="store_true", help="Also ingest paginated category archives for HDHub4u and SSRMovies")
    sync_p.add_argument("--cat-pages", type=int, default=3, help="Max pages per category to crawl (default: 3)")

    # sync-categories
    sync_cat_p = subparsers.add_parser("sync-categories", help="Ingest paginated category archives for HDHub4u / SSRMovies into local cache")
    sync_cat_p.add_argument("--site", choices=["hdhub4u", "ssrmovies", "all"], default="all", help="Source site (default: all)")
    sync_cat_p.add_argument("--pages", type=int, default=3, help="Max pages per category to crawl (default: 3)")
    sync_cat_p.add_argument("--category", type=str, default=None, help="Filter to specific category slug or ID")

    # search
    search_p = subparsers.add_parser("search", help="Instant offline search in sitemap cache")
    search_p.add_argument("query", help="Title or keyword to search")
    search_p.add_argument("--site", choices=SITE_CHOICES, default=None, help="Filter search to specific site")
    search_p.add_argument("--limit", type=int, default=20, help="Max results to return")

    # fetch
    fetch_p = subparsers.add_parser("fetch", help="Scrape post, unwrap direct links, and save to DB")
    fetch_p.add_argument("target", help="URL, slug, or search keyword")
    fetch_p.add_argument("--site", choices=SITE_INDIVIDUAL, default=None, help="Source site hint")

    # view
    view_p = subparsers.add_parser("view", help="View indexed post details and resolved links")
    view_p.add_argument("id_or_slug", help="Post ID or slug")

    # crawl
    crawl_p = subparsers.add_parser("crawl", help="Batch crawl latest N posts from sitemap/feeds")
    crawl_p.add_argument("limit", type=int, nargs="?", default=None, help="Number of latest posts to crawl (default: 5)")
    crawl_p.add_argument("--limit", "-n", dest="opt_limit", type=int, default=None, help="Number of latest posts to crawl")
    crawl_p.add_argument("--site", choices=SITE_INDIVIDUAL, default=None, help="Filter crawl to specific source site")

    # stats
    subparsers.add_parser("stats", help="Display database counts and metrics")

    # list
    list_p = subparsers.add_parser("list", help="List all media posts stored in the database")
    list_p.add_argument("--site", choices=SITE_INDIVIDUAL, default=None, help="Filter list by source site")

    # web
    web_p = subparsers.add_parser("web", help="Start the interactive web dashboard viewer")
    web_p.add_argument("--port", type=int, default=8080, help="Web viewer port (default: 8080)")

    # export-html
    html_p = subparsers.add_parser("export-html", help="Export database to standalone interactive HTML file")
    html_p.add_argument("--output", default="database_view.html", help="Output file name")

    # export
    export_p = subparsers.add_parser("export", help="Export resolved links database")
    export_p.add_argument("--format", choices=["json", "csv"], default="json", help="Export format")
    export_p.add_argument("--output", default=None, help="Output file path")

    # resolve-hubcloud
    subparsers.add_parser("resolve-hubcloud", help="Upgrade all stored HubCloud links to direct Google CDN streaming URLs")

    # health-check
    hc_p = subparsers.add_parser("health-check", aliases=["check"], help="Run live health check & resumability diagnostic on download links")
    hc_p.add_argument("--id", type=int, default=None, help="Check links for a specific post ID only")
    hc_p.add_argument("--dead-only", action="store_true", help="Only check currently marked dead or expired links")
    hc_p.add_argument("--workers", type=int, default=12, help="Concurrency workers (default: 12)")
    hc_p.add_argument("--heal", action="store_true", help="Automatically self-heal any posts found to have dead links after diagnostic")

    # heal
    heal_p = subparsers.add_parser("heal", help="Self-heal dead or expired links by regenerating fresh tokens")
    heal_p.add_argument("id", type=int, nargs="?", default=None, help="Post ID to heal (leave blank to heal all posts with dead links)")
    heal_p.add_argument("--all", action="store_true", help="Heal all posts that have dead or expired links")
    heal_p.add_argument("--daemon", action="store_true", help="Run continuous background auto-healing daemon")
    heal_p.add_argument("--interval", type=int, default=6, help="Interval in hours for daemon sweeps (default: 6)")
    heal_p.add_argument("--source-id", type=int, default=None, help="Target specific download source ID to resolve/heal")
    heal_p.add_argument("--expiring", action="store_true", help="Proactively sweep and renew expiring Tier 2 tokens")

    # resolve
    resolve_p = subparsers.add_parser("resolve", help="Just-In-Time (JIT) resolve an active direct stream link for a download source")
    resolve_p.add_argument("source_id", type=int, help="Download source ID to resolve")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start production REST API & Streaming Server")
    serve_p.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    serve_p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1 — nginx is the public gate; pass an "
             "explicit address only when this process really must face the network)",
    )

    # domain
    dom_p = subparsers.add_parser("domain", help="View, ping, harvest, or update domain mirrors")
    dom_p.add_argument("action", choices=["list", "set", "ping", "harvest", "migrate"], help="Domain action")
    dom_p.add_argument("name", nargs="?", default=None, help="Domain identifier or old domain string for migrate")
    dom_p.add_argument("url", nargs="?", default=None, help="New domain URL or replacement string for migrate")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    init_db()

    if args.command == "sync":
        sync_sitemaps(
            site=getattr(args, "site", "all"),
            max_sub_sitemaps=args.limit,
            include_categories=getattr(args, "categories", False),
            cat_pages=getattr(args, "cat_pages", 3),
        )

    elif args.command == "sync-categories":
        sync_category_archives(
            site=getattr(args, "site", "all"),
            max_pages_per_cat=getattr(args, "pages", 3),
            category=getattr(args, "category", None),
        )

    elif args.command == "search":
        if args.site == "multimovies":
            print(f"[i] Querying MultiMovies Live JSON API for '{args.query}'...")
            mm_res = search_multimovies(args.query, limit=args.limit)
            if mm_res:
                print(f"\n[✓] Found {len(mm_res)} matches on MultiMovies API:\n")
                for i, r in enumerate(mm_res, 1):
                    t_type = f"[{r['type'].upper()}]"
                    yr = f"({r['year']})" if r.get('year') else ""
                    q = f"[{r['quality']}]" if r.get('quality') else ""
                    print(f"{i:2d}. {t_type} {r['title']} {yr} {q}")
                    print(f"    URL: https://multimovies.garden{r['url']}")
                    if r.get('poster'):
                        print(f"    Poster: {r['poster']}")
                print()
                return
            else:
                print(f"[!] No live MultiMovies matches found. Checking local cache...")

        results = search_sitemap(args.query, site=args.site, limit=args.limit)
        if not results:
            # Fallback to MultiMovies API automatically if no local sitemap hits found
            print(f"[i] No matches found in local cache for '{args.query}'. Querying MultiMovies API...")
            mm_res = search_multimovies(args.query, limit=args.limit)
            if mm_res:
                print(f"\n[✓] Found {len(mm_res)} matches on MultiMovies Live API:\n")
                for i, r in enumerate(mm_res, 1):
                    t_type = f"[{r['type'].upper()}]"
                    yr = f"({r['year']})" if r.get('year') else ""
                    q = f"[{r['quality']}]" if r.get('quality') else ""
                    print(f"{i:2d}. [MULTIMOVIES] {t_type} {r['title']} {yr} {q}")
                    print(f"    URL: https://multimovies.garden{r['url']}")
                print()
                return

            print(f"[i] No matches found for '{args.query}'. (Run 'python fast_fetch.py sync' to update sitemap cache)")
            return
        print(f"\n[✓] Found {len(results)} matches for '{args.query}':\n")
        for i, r in enumerate(results, 1):
            scraped_badge = " [Indexed in DB]" if r["scraped"] else ""
            site_tag = f"[{r.get('site', 'vegamovies').upper()}] "
            print(f"{i:2d}. {site_tag}{r['slug']}{scraped_badge}")
            print(f"    URL: {r['loc']}")
            print(f"    Date: {r['lastmod']}")
        print()

    elif args.command == "fetch":
        target = args.target.strip()
        url = None
        if target.startswith("http://") or target.startswith("https://"):
            url = normalize_url(target)
        else:
            results = search_sitemap(target, site=args.site, limit=1)
            if results:
                url = results[0]["loc"]
                print(f"[i] Found matching post URL in sitemap: {url}")
            else:
                site_key = args.site or "vegamovies"
                base_u = DOMAINS.get(site_key, DOMAINS["vegamovies"])
                url = f"{base_u}/{target.strip('/')}/"

        data = extract_post_data(url, verbose=True)
        if data:
            post_id = save_scraped_data(data)
            print(f"\n[✓] Successfully saved to database as Post #{post_id}!")
            display_post_details(post_id)

    elif args.command == "view":
        target = args.id_or_slug.strip()
        with get_db() as conn:
            if target.isdigit():
                display_post_details(int(target))
            else:
                row = conn.execute("SELECT id FROM posts WHERE slug LIKE ? LIMIT 1", (f"%{target}%",)).fetchone()
                if row:
                    display_post_details(row["id"])
                else:
                    print(f"[!] No post matching '{target}' found in database.")

    elif args.command == "crawl":
        limit = args.opt_limit or args.limit or 5
        site_filter = getattr(args, "site", None)
        site_desc = f" ({site_filter.upper()})" if site_filter else " (All Sites)"
        print(f"[i] Crawling latest {limit} posts from sitemap{site_desc}...")

        with get_db() as conn:
            rows = select_crawl_candidates(conn, site_filter, limit)

        if not rows:
            print("[i] Cache empty or all crawled. Syncing sitemap first...")
            sync_sitemaps(site=site_filter or "all", max_sub_sitemaps=2)
            with get_db() as conn:
                rows = select_crawl_candidates(conn, site_filter, limit)

        new_services_found = set()
        crawled_count = 0
        total_releases = 0
        total_sources = 0

        for idx, r in enumerate(rows, 1):
            url = r["loc"]
            slug = url.rstrip("/").split("/")[-1]
            st = (r["site"] if "site" in r.keys() else "vegamovies").upper()
            print(f"[{idx:>3}/{len(rows)}] [{st}] Crawling: {slug[:45]} ...", flush=True)
            try:
                data = extract_post_data(url, verbose=False)
                if data:
                    pid = save_scraped_data(data)
                    rel_cnt = len(data.get("releases", []))
                    src_cnt = sum(len(rel.get("sources", [])) for rel in data.get("releases", []))
                    for rel in data.get("releases", []):
                        for s in rel.get("sources", []):
                            new_services_found.add(s["service"])
                    crawled_count += 1
                    total_releases += rel_cnt
                    total_sources += src_cnt
                    tag18 = " 🔞" if data.get("is_18_plus") else ""
                    anim_tag = " 🎨" if data.get("is_animated") else ""
                    ind_badge = f" [{data.get('industry', 'N/A')}]"
                    print(f"      ✓ Post #{pid}: {data['clean_title'][:30]}{ind_badge} | {rel_cnt} rel, {src_cnt} links{tag18}{anim_tag}", flush=True)
                else:
                    record_crawl_attempt(url, indexed=False,
                                         cause=classify_crawl_failure(cause="parse_no_releases"))
                    print(f"      ⚠ Skipped (no releases found)", flush=True)
            except Exception as e:
                reason = classify_crawl_failure(exc=e)
                record_crawl_attempt(url, indexed=False, cause=reason)
                print(f"      ✗ Error: [{reason}] {e}", flush=True)

        print("\n" + "=" * 70)
        with get_db() as conn:
            _parked = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = -1 AND attempts >= ?",
                (MAX_CRAWL_ATTEMPTS,),
            ).fetchone()[0]
            _queued = conn.execute(
                "SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 0 OR (scraped = -1 AND attempts < ?)",
                (MAX_CRAWL_ATTEMPTS,),
            ).fetchone()[0]
            _breakdown = crawl_failure_breakdown(site_filter, db_conn=conn)
        print(f"🎉 Crawl Complete! Indexed {crawled_count}/{len(rows)} posts")
        print(f"🔁 Still queued: {_queued:,} | 🛑 Parked after {MAX_CRAWL_ATTEMPTS} attempts: {_parked:,}")
        if _breakdown:
            # 'gone' and 'broken' are different work items; say which is which.
            print("🧭 Parked failures by cause (permanent = upstream gone, others retry-able):")
            for _cause, _n in _breakdown[:10]:
                _kind = "permanent" if _cause in PERMANENT_CRAWL_CAUSES else "transient"
                print(f"      {_cause:26s} {_n:7,}  {_kind}")
        print(f"📦 Total releases added: {total_releases}")
        print(f"🔗 Total direct sources added: {total_sources}")
        print(f"🌐 Services detected: {', '.join(sorted(new_services_found))}")
        print("=" * 70 + "\n")

    elif args.command == "stats":
        with get_db() as conn:
            s_count = conn.execute("SELECT COUNT(*) FROM sitemap_cache").fetchone()[0]
            sm_by_site = conn.execute("SELECT COALESCE(site, 'vegamovies'), COUNT(*) FROM sitemap_cache GROUP BY site").fetchall()
            sm_breakdown = " | ".join(f"{r[0].title()}: {r[1]:,}" for r in sm_by_site)
            s_scraped = conn.execute("SELECT COUNT(*) FROM sitemap_cache WHERE scraped = 1").fetchone()[0]

            p_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
            p_by_site = conn.execute(
                """
                SELECT source_site, COUNT(DISTINCT post_id)
                FROM (
                    SELECT source_site, post_id FROM post_sources
                    UNION
                    SELECT source_site, post_id FROM releases
                    WHERE source_site IS NOT NULL AND source_site != ''
                )
                GROUP BY source_site ORDER BY source_site
                """
            ).fetchall()
            p_breakdown = " | ".join(f"{r[0].title()}: {r[1]:,}" for r in p_by_site)

            p_holly = conn.execute("SELECT COUNT(*) FROM posts WHERE industry LIKE '%Hollywood%'").fetchone()[0]
            p_bolly = conn.execute("SELECT COUNT(*) FROM posts WHERE industry LIKE '%Bollywood%' OR country = 'India'").fetchone()[0]
            p_anime = conn.execute("SELECT COUNT(*) FROM posts WHERE is_animated = 1 OR industry = 'Anime'").fetchone()[0]

            r_count = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            src_count = conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0]
            active_src = conn.execute("SELECT COUNT(*) FROM download_sources WHERE status = 'active'").fetchone()[0]
            resumable_src = conn.execute("SELECT COUNT(*) FROM download_sources WHERE is_resumable = 1").fetchone()[0]

            print("\n" + "=" * 60)
            print("📊 Fast_Fetch Unified Multi-Site Database Metrics")
            print("=" * 60)
            print(f"  Sitemap/Feeds Cached  : {s_count:,} ({sm_breakdown})")
            print(f"  Catalog Posts Scraped : {s_scraped:,}")
            print(f"  Canonical Media Rows  : {p_count:,}")
            print(f"    └─ Site coverage    : {p_breakdown or 'No site attribution recorded'}")
            print(f"    ├─ Hollywood        : {p_holly:,}")
            print(f"    ├─ Bollywood/India  : {p_bolly:,}")
            print(f"    └─ Anime/Animated   : {p_anime:,}")
            print(f"  Total Release Variants: {r_count:,}")
            print(f"  Total Direct Sources  : {src_count:,} (🟢 Active: {active_src:,} | ⚡ Resumable: {resumable_src:,})")
            print(f"  Database Path         : {DB_PATH}")
            print("=" * 60 + "\n")

    elif args.command == "list":
        site_filter = getattr(args, "site", None)
        with get_db() as conn:
            sql = """
                SELECT
                    p.id, p.clean_title, p.year, p.source_site, p.industry, p.country, p.language,
                    (
                        SELECT GROUP_CONCAT(all_sites.source_site)
                        FROM (
                            SELECT source_site FROM post_sources WHERE post_id = p.id
                            UNION
                            SELECT source_site FROM releases
                            WHERE post_id = p.id AND source_site IS NOT NULL AND source_site != ''
                        ) AS all_sites
                    ) AS source_sites,
                    COUNT(DISTINCT r.id) as rel_count,
                    COUNT(DISTINCT s.id) as src_count
                FROM posts p
                LEFT JOIN post_sources ps ON ps.post_id = p.id
                LEFT JOIN releases r ON r.post_id = p.id
                LEFT JOIN download_sources s ON s.release_id = r.id
            """
            params = []
            if site_filter:
                sql += """ WHERE (
                    EXISTS (SELECT 1 FROM post_sources psf WHERE psf.post_id = p.id AND psf.source_site = ?)
                    OR EXISTS (SELECT 1 FROM releases rf WHERE rf.post_id = p.id AND rf.source_site = ?)
                )"""
                params.append(site_filter)
                params.append(site_filter)
            sql += """
                GROUP BY p.id
                ORDER BY p.id ASC
            """
            rows = conn.execute(sql, params).fetchall()

            if not rows:
                print("\n[i] No media posts indexed in the database yet.")
                return

            print("\n" + "=" * 105)
            print("🎬 Fast_Fetch Database — Multi-Site Indexed Media Collection")
            print("=" * 105)
            print(f"{'ID':<4} | {'Title':<26} | {'Year':<5} | {'Sites':<20} | {'Industry':<18} | {'Country':<6} | {'Audio':<15} | {'Rel':<4} | {'Links':<5}")
            print("-" * 105)
            for r in rows:
                y = str(r['year']) if r['year'] else 'N/A'
                t = r['clean_title'][:24]
                site = (r['source_sites'] or r['source_site'] or 'unknown').upper()[:19]
                ind = (r['industry'] or 'Hollywood')[:16]
                cnt = (r['country'] or 'USA')[:6]
                lang = (r['language'] or 'English')[:13]
                print(f"{r['id']:<4} | {t:<26} | {y:<5} | {site:<20} | {ind:<18} | {cnt:<6} | {lang:<15} | {r['rel_count']:<4} | {r['src_count']:<5}")
            print("=" * 105)
            print(f"Total: {len(rows)} media posts stored. Use 'python fast_fetch.py view <id>' for full details.\n")

    elif args.command == "web":
        import viewer
        viewer.start_server(args.port)

    elif args.command == "export-html":
        import viewer
        out = viewer.export_standalone_html(args.output)
        print(f"[✓] Standalone interactive HTML dashboard created at:\n    file:///{out.replace(chr(92), '/')}")

    elif args.command == "export":
        fmt = args.format
        out = args.output or f"fast_fetch_export.{fmt}"
        with get_db() as conn:
            rows = conn.execute("""
                SELECT
                    p.id AS post_id, p.url AS first_seen_url,
                    p.clean_title, p.year, p.content_type, p.source_site, p.industry, p.country, p.language, p.seasons,
                    r.source_site AS release_source_site, r.release_title, r.quality, r.size, r.languages,
                    s.source_name, s.service, s.resource_id, s.final_url, s.is_temporary
                FROM download_sources s
                JOIN releases r ON s.release_id = r.id
                JOIN posts p ON r.post_id = p.id
                ORDER BY p.id, r.id
            """).fetchall()

            items = [dict(r) for r in rows]
            source_pages = {}
            for page in conn.execute(
                "SELECT post_id, source_site, url, source_title FROM post_sources ORDER BY post_id, source_site"
            ).fetchall():
                source_pages.setdefault(page["post_id"], []).append({
                    "source_site": page["source_site"],
                    "url": page["url"],
                    "source_title": page["source_title"],
                })
            for item in items:
                item["source_pages"] = source_pages.get(item["post_id"], [])

            if fmt == "json":
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(items, f, indent=2, ensure_ascii=False)
            elif fmt == "csv":
                import csv
                for item in items:
                    item["source_pages"] = json.dumps(item["source_pages"], ensure_ascii=False)
                fieldnames = list(items[0].keys()) if items else [
                    "post_id", "first_seen_url", "clean_title", "year", "content_type",
                    "source_site", "industry", "country", "language", "seasons",
                    "release_source_site", "release_title", "quality", "size", "languages",
                    "source_name", "service", "resource_id", "final_url", "is_temporary",
                    "source_pages",
                ]
                with open(out, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(items)
            print(f"[✓] Exported {len(items)} records to {out} ({fmt.upper()})")

    elif args.command == "resolve-hubcloud":
        with get_db() as conn:
            rows = conn.execute("""
                SELECT id, final_url FROM download_sources
                WHERE final_url LIKE '%gpdl2.hubcloud.ist%'
            """).fetchall()

        if not rows:
            print("\n[i] No unresolved HubCloud links found in database.")
            return

        print(f"\n[i] Found {len(rows)} HubCloud links to resolve directly into Google CDN URLs...")

        def _resolve_row(r):
            sid, url = r["id"], r["final_url"]
            direct_u, svc, is_temp = unwrap_hubcloud(url)
            if svc == "google_cdn":
                return (sid, "V-Cloud [Google Direct CDN]", "google_cdn", direct_u, 1)
            return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_resolve_row, r) for r in rows]
            updates = []
            for fut in as_completed(futures):
                res = fut.result()
                if res:
                    updates.append(res)
                    print(f"  ✓ Upgraded #{res[0]} -> Google CDN", flush=True)

        if updates:
            with get_db() as conn:
                conn.executemany("""
                    UPDATE download_sources
                    SET source_name = ?, service = ?, final_url = ?, is_temporary = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, [(u[1], u[2], u[3], u[4], u[0]) for u in updates])
            print(f"\n[✓] Successfully upgraded {len(updates)}/{len(rows)} HubCloud links to Google CDN streaming links!\n")
        else:
            print("\n[!] Could not upgrade links.\n")

    elif args.command in ("health-check", "check"):
        results = run_health_check(post_id=args.id, dead_only=args.dead_only, max_workers=args.workers, verbose=True)
        if args.heal:
            with get_db() as conn:
                posts_with_dead = conn.execute("""
                    SELECT DISTINCT p.id, p.clean_title
                    FROM posts p
                    JOIN releases r ON r.post_id = p.id
                    JOIN download_sources s ON s.release_id = r.id
                    WHERE s.status IN ('dead', 'expired')
                    ORDER BY p.id ASC
                """).fetchall()
            if posts_with_dead:
                print(f"\n[🔄] Auto-healing {len(posts_with_dead)} posts with detected dead/expired links...")
                for r in posts_with_dead:
                    heal_post_links(r["id"], verbose=True)

    elif args.command == "heal":
        if getattr(args, "daemon", False):
            start_healing_daemon(interval_hours=getattr(args, "interval", 6))
        elif getattr(args, "source_id", None):
            res = resolve_live_source(args.source_id)
            print(json.dumps(res, indent=2))
        elif getattr(args, "expiring", False):
            heal_expiring_sources(max_age_hours=getattr(args, "interval", 6), verbose=True)
        elif args.id:
            heal_post_links(args.id, verbose=True)
        else:
            with get_db() as conn:
                posts_with_dead = conn.execute("""
                    SELECT DISTINCT p.id, p.clean_title
                    FROM posts p
                    JOIN releases r ON r.post_id = p.id
                    JOIN download_sources s ON s.release_id = r.id
                    WHERE s.status IN ('dead', 'expired')
                    ORDER BY p.id ASC
                """).fetchall()
            if not posts_with_dead:
                print("\n[✓] All posts in the database are 100% healthy! No dead or expired links found.\n")
            else:
                print(f"\n[🔄] Global self-healing initiated for {len(posts_with_dead)} posts with dead links...")
                total_healed = 0
                for r in posts_with_dead:
                    res = heal_post_links(r["id"], verbose=True)
                    total_healed += res.get("healed", 0)
                print(f"\n[✓] Global heal complete: revived {total_healed} link(s) across {len(posts_with_dead)} post(s)!\n")

    elif args.command == "resolve":
        res = resolve_live_source(args.source_id)
        print(json.dumps(res, indent=2))

    elif args.command == "serve":
        import viewer
        port = getattr(args, "port", 8080)
        host = getattr(args, "host", "127.0.0.1")
        viewer.start_server(port, host=host)

    elif args.command == "domain":
        if args.action == "list":
            with get_db() as conn:
                rows = conn.execute("SELECT name, url, status, last_checked FROM domains_config ORDER BY name").fetchall()
                print("\n" + "=" * 65)
                print("🌐 Configured Domain Mirrors")
                print("=" * 65)
                for r in rows:
                    print(f"  {r['name']:<18} : {r['url']} (Last checked: {r['last_checked'] or 'N/A'})")
                print("=" * 65 + "\n")
        elif args.action == "set":
            if not args.name or not args.url:
                print("[!] Usage: python fast_fetch.py domain set <name> <url>")
                return
            set_domain(args.name, args.url)
            print(f"[✓] Domain '{args.name}' updated to: {args.url}")
        elif args.action == "ping":
            ping_domains(verbose=True)
        elif args.action == "harvest":
            print("\n[i] Harvesting live sister domains from network headers...")
            h1 = harvest_sister_domains(http_get(DOMAINS.get("vegamovies", "https://vegamovies.gallery"))[2])
            h2 = harvest_sister_domains(http_get(DOMAINS.get("rogmovies", "https://rogmovies.one"))[2])
            all_h = {**h1, **h2}
            if all_h:
                print(f"[✓] Discovered & synchronized {len(all_h)} sister site domains:")
                for k, v in all_h.items():
                    print(f"    {k:<14} -> {v}")
            else:
                print("[✓] All sister site domains are already up-to-date in database!")
            print()
        elif args.action == "migrate":
            if not args.name or not args.url:
                print("[!] Usage: python fast_fetch.py domain migrate <old_domain_pattern> <new_domain_replacement>")
                print("    Example: python fast_fetch.py domain migrate rogmovies.wtf rogmovies.one")
                return
            res = migrate_domains_in_db(args.name, args.url)
            print(f"\n[✓] Domain migration '{args.name}' -> '{args.url}' complete:")
            print(f"    Posts updated   : {res['posts_updated']}")
            print(f"    Site pages updated: {res['post_sources_updated']}")
            print(f"    Sitemaps updated: {res['sitemaps_updated']}")
            print(f"    Releases updated: {res['releases_updated']}")
            print(f"    Sources updated : {res['sources_updated']}")
            print(f"    Domains updated : {res['domains_updated']}\n")


if __name__ == "__main__":
    main()
