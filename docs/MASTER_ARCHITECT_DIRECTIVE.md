# 🏛️ MASTER_ARCHITECT_DIRECTIVE.md — 20-Year Architecture, App Innovations & Multi-VM Federation

> **Directive Level:** Top-Level Project Directive / Core Lead & Senior Engineer Guidance  
> **Target Audience:** Qoder Agent (Qwen), Antigravity Agent, Replit Agent, and all autonomous contributors  
> **Author:** Project Lead & Dao Partner  
> **Effective Date:** October 2026 – Indefinite  

---

## 🧭 Executive Summary & Core Mandate

This document establishes the **20-year technical blueprint and operational directives** for the `radd-stream` project. 

The project's goal is to build the world's most resilient, decentralized, zero-bandwidth-cost media indexing engine and high-performance streaming client. Every agent operating on this codebase must adhere strictly to these architectural foundations, future-proofing mechanisms, and mobile UX innovations.

---

## 🏛️ Part 1: Non-Negotiable Core Invariants (The Inviolable Laws)

1. **Zero External Dependencies in Python Backend**:
   - The backend runs **100% on Python Standard Library** (`urllib`, `sqlite3`, `json`, `re`, `html`, `concurrent.futures`, `hashlib`, `unicodedata`).
   - **Never run `pip install`**. Dependency rot kills software over 5–20 years. Standard library ensures code executes identically decades from now.
2. **Zero Video Bandwidth on Infrastructure (The 302 Handoff Model)**:
   - The server **never proxies or moves video bytes**. Video streams are resolved and handed off via **HTTP 302 Redirect** directly to high-speed CDNs (Google 10Gbps CDN `lh3.googleusercontent.com`, Cloudflare R2, PixelDrain, FastDL).
   - Google and Cloudflare shoulder all multi-gigabyte bandwidth costs; our servers move only ~300 bytes of plain text per play request.
3. **Strict Staging Database Isolation**:
   - Every scraped site must reside in its own isolated SQLite database in `/home/ubuntu/radd-stream-data/<site_name>.db` (e.g. `vegamovies.db`, `bolly4u.db`, `toonworld4all.db`).
   - **NEVER merge into production `fast_fetch.db` without explicit confirmation**.
4. **Archival Completeness with 18+ Display Filtering**:
   - Scrapers ingest 100% of available data including adult titles, storing them with `is_18_plus = 1`.
   - All presentation surfaces (REST API, viewer dashboard, M3U playlists, Android app) strictly filter out `is_18_plus = 1` rows at the query level (`WHERE is_18_plus = 0`).
5. **Universal Provenance Redaction (Zero-Leak Policy)**:
   - Third parties and normal users must never see upstream site names (e.g., *Vegamovies*, *Bolly4u*, *HubCloud*) or raw upstream URLs with the naked eye.
   - Use `Fast_Fetch/redact.py` to scrub all origins and tokens into opaque, cryptographically signed stream handles.

---

## 🌐 Part 2: Multi-VM Federation & Cluster Architecture ($0/Month)

Rather than relying on a single vulnerable Oracle Cloud VM, the system is designed to scale across **2–3 independent free-tier VMs** (registered under separate accounts/identities):

```
                                  Android Mobile App
                                           │
                                           ▼
                     Cloudflare Load Balancer / DNS (Free)
                         (Health checks every 60s)
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              ▼                            ▼                            ▼
         VM #1 (Primary API)          VM #2 (Hot Backup)           VM #3 (Dedicated Crawler)
    ┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
    │ • Catalog API v2     │     │ • Catalog API v2     │     │ • 50+ Site Scrapers  │
    │ • Viewer Server      │     │ • Viewer Server      │     │ • Link Unwrappers    │
    │ • Synced DB Copy     │     │ • Synced DB Copy     │     │ • Raw Staging DBs    │
    └──────────────────────┘     └──────────────────────┘     └──────────────────────┘
              ▲                            ▲                            │
              │                            │                            │
              └──────────── Sync DB Snapshots via Hugging Face ─────────┘
```

### 1. Separation of Labor
- **API Nodes (VM #1 & VM #2)**: Exclusively serve Android app JSON queries, search, and 302 stream redirects. Low CPU, zero crawler interference, instant sub-millisecond responses.
- **Worker Node (VM #3)**: Runs long-running background crawlers, bridge resolvers (like ToonWorld4All's 226k links), and sitemap synchronizers with `nice -n 12`.

### 2. Zero-Downtime Cloudflare Edge Failover
- Point the public API domain (via Cloudflare Tunnels/DNS) to VM #1 and VM #2.
- If Oracle reclaims or reboots VM #1, Cloudflare automatically fails over to VM #2 in <60 seconds.

### 3. Asynchronous Database Replication via Hugging Face
- VM #3 pushes daily SQLite snapshots to Hugging Face dataset `radddao/radd-stream-backups` using `backup-hf`.
- VM #1 and VM #2 run a simple cron script to pull database updates (`git-lfs pull`), keeping them completely synchronized without complex database clustering software.

---

## 🚀 Part 3: Infinite Site Expansion & Automated Link Healing

### The Law of Infinite Site Expansion
- **The Problem:** Direct CDN links naturally decay after weeks or months as upstream storage accounts rotate.
- **The Solution:** **Continuous, infinite site ingestion.**
  - We do not stop at 18 or 20 sites. We continuously add every discovered streaming portal (`extramovies`, `katmovies`, `mkvcage`, `yts`, etc.).
  - Whenever a new site is indexed, it injects brand-new, active 10Gbps CDN links into the canonical catalog for existing titles.
  - The `catalog_v2.py` Link Truth engine scores and floats the newest, highest-speed links to the top of the play ladder. Link decay is defeated automatically by catalog freshness.

### SQLite FTS5 for 1,000,000+ Title Scalability
- For catalogs exceeding 100,000 titles, replace linear memory scans with SQLite's built-in **FTS5 (Full-Text Search 5)** virtual tables.
- Standard library supported, zero pip dependencies, sub-millisecond search across millions of records with BM25 ranking.

---

## 📱 Part 4: Advanced Android Client Innovations (Netflix UI + MX Player Parity)

Qoder and frontend contributors must construct the Android app around these next-generation specifications:

### 1. Hybrid Architecture: Netflix UI + MX Player Core
* **Browsing Experience**: High-density hero carousels, category shelves, genre filters, and clean typography.
* **Playback Experience**: MX Player-grade touch gestures built directly on **AndroidX Media3 (ExoPlayer)**:
  - Vertical swipe left = Screen brightness (window-level).
  - Vertical swipe right = Volume HUD.
  - Double-tap left/right = ±10s smooth seek with animated ripple.
  - Two-finger vertical swipe = Playback speed (0.25× to 4.0× in 0.25× steps).
  - Long-press = Instant 2.0× speed boost (releases back to 1.0×).
  - Pinch-to-zoom = Seamless aspect ratio switching (Fit, Fill/Crop, 16:9, Zoom).

### 2. Silent Multi-CDN Stream Failover
* The app requests a stream bundle containing the primary high-speed link and up to 3 runner-up backup mirrors.
* If ExoPlayer encounters an `HttpDataSourceException` (e.g. 403 Forbidden or network drop) during playback, it **silently switches to the backup mirror at the exact current playback timestamp** without showing an error dialog to the user.

### 3. Single Winner Per Quality Tier (Task 28 Standard)
* The user is never overwhelmed by a raw list of 20 identical links.
* The API and App collapse links into **one best+fastest option per quality tier** (4K, 1080p, 720p, 480p).
* "Auto" quality is the default.

### 4. Background Offline Download Engine
* Chunked background download manager using `WorkManager` and Media3 `DownloadService`.
* Automatic pause on mobile data, auto-resume on Wi-Fi reconnection, and encrypted local storage.

### 5. Multi-Container & Codec Mastery
* Ensure native playback for HLS (`.m3u8`), MP4, MKV, WebM, with soft-subtitle selection (`.srt`, `.vtt`) and multi-channel audio tracks (Hindi 5.1, English 5.1).

---

## 📋 Part 5: Senior Guidance for Qoder Agent

To Qoder (`qwen2.5-coder` on Oracle VM):
1. **Praise for Work Completed**:
   - Successfully resolved 225,833 out of 226,438 ToonWorld4All bridge links (99.7% completion).
   - Fixed the 271 compile errors in the Android Kotlin tree and unified duplicate models.
   - Built the zero-leak token redaction engine (`Fast_Fetch/redact.py`) with 147 passing unit tests.
2. **Current Directive**:
   - Complete **Task 28**: Finalize the *"One best+fastest option per quality tier"* logic in `catalog_api.py` and the corresponding download/quality card in the Android client.
   - Stage and commit the clean, working Android files (`App/`) to ensure no work is lost on VM reboot.
   - Continue running pre-push unit tests (`python3 -S Fast_Fetch/test_database.py`) before pushing to GitHub.

---
*End of Directive. Adhere to these principles across all sessions.*
