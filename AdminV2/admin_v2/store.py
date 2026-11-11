"""SQLite stores: admin_v2.db (workspace only), plus two fixture DBs.

- admin_v2.db: panel state only. Never a live catalog, never a live ledger.
- catalog_fixture.db: MOCK works only, read-only in services (search /
  slider validation). Titles are labelled MOCK in every fixture row.
- ledger_fixture.db: MOCK accounts + payment claims. VIP credit goes
  through ledger functions only; the panel never edits vip_until directly.

SQLite discipline (smart-methods research §3): WAL, busy_timeout ~5s,
single-writer lock, batched transactions, capped cache/job tables.
"""
import os
import sqlite3
import threading
import time

WRITE_LOCK = threading.RLock()

FLEET_SITES = [
    "10xflix", "7starhd", "9xmovies", "bolly4u", "castle",
    "desicinemas", "dramadog", "filmyzilla", "harpalgeo", "hdhub4u",
    "hdtvb", "hindilinks4u", "katmoviehd", "megacartoons",
    "movienestbd", "moviesdrive", "moviezguru", "multimovies",
    "rareanimes", "rogmovies", "ssrmovies", "toonworld4all",
    "vegamovies", "world4ufree", "xprimehub",
]

# Coin pass prices, stored in the live catalog's app_remote_config
# (day 500 / weekend 1200 / monthly 5000 / download 100 / request
# 300 / theme 250 — the live values the security audit found). The
# panel could neither show nor edit them (admin-panel audit 2026-11-08
# §Money); they are monetization fields now, read from the catalog
# when wired and from the panel row otherwise.
COIN_REDEEM_FIELDS = [
    "coin_redeem_day", "coin_redeem_weekend", "coin_redeem_monthly",
    "coin_redeem_download", "coin_redeem_request", "coin_redeem_theme",
]
COIN_REDEEM_DEFAULTS = {
    "coin_redeem_day": 500, "coin_redeem_weekend": 1200,
    "coin_redeem_monthly": 5000, "coin_redeem_download": 100,
    "coin_redeem_request": 300, "coin_redeem_theme": 250,
}

# The docs inventory names 16 monetization fields; the design says 17.
# The 17th column is the row id itself. No field is invented here.
MONETIZATION_FIELDS = [
    "pak_till_id", "pak_jazzcash_number", "pak_easypaisa_number",
    "pak_raast_id", "vip_monthly_pkr", "vip_yearly_pkr",
    "monetag_zone_id", "adsterra_tag_id", "shrinkme_api_token",
    "droplink_api_token", "maintenance_mode", "apk_update_url",
    "feature_downloads", "feature_pure_cinema", "feature_chromecast",
    "feature_quality_gate",
] + COIN_REDEEM_FIELDS

TUNING_DEFAULTS = {
    "resolver_concurrency": 2, "candidate_cap": 10, "cache_ttl_h": 6,
    "warmup_count": 50, "warmup_interval_h": 24,
    "rate_limit_play_per_min": 30, "import_cap": 25,
    "import_concurrency": 1, "prefetch_queue": 100,
    "prefetch_concurrency": 1, "hero_max": 6, "section_cap": 20,
    "home_sections_max": 12, "domain_check_interval_min": 60,
    "free_quality_cap": "720p",
    "theme_mode": "dark", "theme_accent": "",
    "theme_dynamic_color": 0, "theme_hero_autoplay": 1,
    "theme_hero_interval_s": 5,
    "tabs": "home,search,my_list,settings",
    "disclaimer_text": "", "disclaimer_version": 0,
    "disclaimer_email": "radddao1@gmail.com",
}

# Columns stored as TEXT (everything else in TUNING_DEFAULTS is INTEGER).
TUNING_TEXT_COLUMNS = frozenset({"free_quality_cap", "theme_mode", "theme_accent", "tabs", "disclaimer_text", "disclaimer_email"})

MIGRATIONS = [
    (1, """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS admin_users (
      id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, password_changed_at INTEGER,
      totp_secret_encrypted TEXT, role TEXT NOT NULL DEFAULT 'owner',
      is_active INTEGER NOT NULL DEFAULT 1, created_by INTEGER,
      last_login_at INTEGER, failed_attempts INTEGER NOT NULL DEFAULT 0,
      locked_until INTEGER, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS admin_sessions (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
      session_token_hash TEXT NOT NULL, csrf_token_hash TEXT NOT NULL,
      created_at INTEGER, last_seen_at INTEGER, expires_at INTEGER,
      ip_masked TEXT, user_agent_label TEXT, revoked_at INTEGER);
    CREATE TABLE IF NOT EXISTS admin_login_attempts (
      id INTEGER PRIMARY KEY, username_attempted TEXT, ip_masked TEXT,
      success INTEGER NOT NULL DEFAULT 0, attempted_at INTEGER);
    CREATE TABLE IF NOT EXISTS admin_audit_log (
      id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL,
      target_type TEXT, target_id TEXT, before_json TEXT, after_json TEXT,
      ip_masked TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS admin_recovery_codes (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
      code_hash TEXT NOT NULL, used_at INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS app_remote_config_v2 (
      id INTEGER PRIMARY KEY CHECK (id = 1), config_version INTEGER NOT NULL DEFAULT 1,
      pak_till_id TEXT DEFAULT '', pak_jazzcash_number TEXT DEFAULT '',
      pak_easypaisa_number TEXT DEFAULT '', pak_raast_id TEXT DEFAULT '',
      vip_monthly_pkr INTEGER NOT NULL DEFAULT 200,
      vip_yearly_pkr INTEGER NOT NULL DEFAULT 1500,
      monetag_zone_id TEXT DEFAULT '', adsterra_tag_id TEXT DEFAULT '',
      shrinkme_api_token TEXT DEFAULT '', droplink_api_token TEXT DEFAULT '',
      maintenance_mode INTEGER NOT NULL DEFAULT 0, apk_update_url TEXT DEFAULT '',
      feature_downloads INTEGER NOT NULL DEFAULT 1,
      feature_pure_cinema INTEGER NOT NULL DEFAULT 1,
      feature_chromecast INTEGER NOT NULL DEFAULT 1,
      feature_quality_gate INTEGER NOT NULL DEFAULT 0,
      min_version_code INTEGER, latest_version_code INTEGER,
      latest_version_name TEXT DEFAULT '', force_update INTEGER NOT NULL DEFAULT 0,
      force_update_message TEXT DEFAULT '', maintenance_message TEXT DEFAULT '',
      brand_primary TEXT DEFAULT '#2563EB', brand_accent TEXT DEFAULT '#2563EB',
      region_order TEXT DEFAULT 'pakistan,india,asia,international',
      free_quality_cap TEXT DEFAULT '720p', updated_by INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS app_remote_config_history (
      id INTEGER PRIMARY KEY, config_version INTEGER NOT NULL,
      snapshot_json TEXT NOT NULL, published_by INTEGER, published_at INTEGER);
    CREATE TABLE IF NOT EXISTS scheduled_publishes (
      id INTEGER PRIMARY KEY, scheduled_at INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', created_by INTEGER,
      created_at INTEGER, fired_at INTEGER, fired_version INTEGER,
      cancel_at INTEGER, cancel_by INTEGER, note TEXT);
    CREATE TABLE IF NOT EXISTS vip_grants (
      id INTEGER PRIMARY KEY, account_hint TEXT NOT NULL, payment_id INTEGER,
      months INTEGER NOT NULL, reason TEXT, granted_by INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS user_flags (
      id INTEGER PRIMARY KEY, account_hint TEXT NOT NULL, flag TEXT NOT NULL,
      reason TEXT, expires_at INTEGER, created_by INTEGER,
      cleared_at INTEGER, cleared_by INTEGER, created_at INTEGER);
    """),
    (2, """
    CREATE TABLE IF NOT EXISTS home_sections (
      id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
      position INTEGER NOT NULL DEFAULT 0, is_enabled INTEGER NOT NULL DEFAULT 1,
      is_adult_only INTEGER NOT NULL DEFAULT 0, visible_to TEXT NOT NULL DEFAULT 'all',
      source_rule TEXT NOT NULL DEFAULT 'latest', category_key TEXT,
      created_by INTEGER, updated_by INTEGER, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS slider_cards (
      id INTEGER PRIMARY KEY, section_id INTEGER NOT NULL, work_id INTEGER NOT NULL,
      position INTEGER NOT NULL DEFAULT 0, title_override TEXT,
      is_enabled INTEGER NOT NULL DEFAULT 1, starts_at INTEGER, ends_at INTEGER,
      created_by INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS content_visibility (
      id INTEGER PRIMARY KEY, scope TEXT NOT NULL, scope_id TEXT NOT NULL,
      is_hidden INTEGER NOT NULL DEFAULT 1, reason TEXT NOT NULL, note TEXT,
      expires_at INTEGER, created_by INTEGER, restored_at INTEGER,
      restored_by INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
      position INTEGER NOT NULL DEFAULT 0, is_enabled INTEGER NOT NULL DEFAULT 1,
      is_adult_only INTEGER NOT NULL DEFAULT 0, created_by INTEGER,
      updated_by INTEGER, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS category_works (
      id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL, work_id INTEGER NOT NULL,
      position INTEGER NOT NULL DEFAULT 0, created_by INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS category_history (
      id INTEGER PRIMARY KEY, category_id INTEGER, action TEXT NOT NULL,
      before_json TEXT, after_json TEXT, actor_id INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS content_safety (
      id INTEGER PRIMARY KEY CHECK (id = 1), adult_content_enabled INTEGER NOT NULL DEFAULT 0,
      adult_gate_confirmed INTEGER NOT NULL DEFAULT 0, updated_by INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS content_safety_history (
      id INTEGER PRIMARY KEY, field TEXT NOT NULL, before_value TEXT,
      after_value TEXT, actor_id INTEGER, reason TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS broadcasts (
      id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
      severity TEXT NOT NULL DEFAULT 'info', target TEXT NOT NULL DEFAULT 'all',
      target_detail TEXT,
      starts_at INTEGER, ends_at INTEGER, status TEXT NOT NULL DEFAULT 'draft',
      published_by INTEGER, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS contact_messages (
      id INTEGER PRIMARY KEY, app_account_hint TEXT, category TEXT NOT NULL DEFAULT 'other',
      subject TEXT, body TEXT, status TEXT NOT NULL DEFAULT 'open',
      linked_report_id INTEGER, linked_work_id INTEGER, created_at INTEGER,
      resolved_at INTEGER, resolved_by INTEGER, internal_note TEXT);
    CREATE TABLE IF NOT EXISTS reports (
      id INTEGER PRIMARY KEY, source TEXT NOT NULL DEFAULT 'app_report',
      work_id INTEGER, reason TEXT NOT NULL, detail TEXT, reporter_hint TEXT,
      status TEXT NOT NULL DEFAULT 'open', temp_hidden_at INTEGER,
      verified_at INTEGER, decided_by INTEGER, decision_note TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS report_actions (
      id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL, action TEXT NOT NULL,
      actor_id INTEGER, note TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS importer_blocklist_notes (
      id INTEGER PRIMARY KEY, importer_key TEXT NOT NULL, reason TEXT,
      created_by INTEGER, created_at INTEGER, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS tuning_settings (
      id INTEGER PRIMARY KEY CHECK (id = 1), updated_by INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS tuning_history (
      id INTEGER PRIMARY KEY, control_name TEXT NOT NULL, before_value TEXT,
      after_value TEXT, actor_id INTEGER, reason TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS pauses (
      id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
      is_paused INTEGER NOT NULL DEFAULT 1, reason TEXT, paused_by INTEGER,
      paused_at INTEGER, resumed_at INTEGER, resumed_by INTEGER);
    CREATE TABLE IF NOT EXISTS domain_registry (
      site_key TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'source_site',
      active_domain TEXT, status TEXT NOT NULL DEFAULT 'healthy',
      health_score INTEGER NOT NULL DEFAULT 100, last_checked_at INTEGER,
      last_success_at INTEGER, last_failure_reason TEXT, override_by INTEGER,
      override_at INTEGER, override_note TEXT, auto_failover INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS domain_candidates (
      id INTEGER PRIMARY KEY, site_key TEXT NOT NULL, domain TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'owner_typed', fingerprint_ok INTEGER NOT NULL DEFAULT 0,
      first_seen_at INTEGER, last_seen_at INTEGER, times_seen INTEGER NOT NULL DEFAULT 1,
      status TEXT NOT NULL DEFAULT 'candidate', validated_at INTEGER);
    CREATE TABLE IF NOT EXISTS domain_health_checks (
      id INTEGER PRIMARY KEY, site_key TEXT NOT NULL, domain_checked TEXT,
      checked_at INTEGER, dns_ok INTEGER, tcp_ok INTEGER, tls_ok INTEGER,
      http_status INTEGER, fingerprint_ok INTEGER, latency_ms INTEGER,
      failure_reason TEXT, network TEXT NOT NULL DEFAULT 'vm');
    CREATE TABLE IF NOT EXISTS domain_history (
      id INTEGER PRIMARY KEY, site_key TEXT NOT NULL, from_domain TEXT,
      to_domain TEXT, changed_by INTEGER, change_reason TEXT,
      validated_at INTEGER, applied_at INTEGER);
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload_json TEXT,
      status TEXT NOT NULL DEFAULT 'queued', progress INTEGER NOT NULL DEFAULT 0,
      attempts INTEGER NOT NULL DEFAULT 0, idempotency_key TEXT UNIQUE,
      result_json TEXT, created_by INTEGER, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS analytics_daily (
      id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE, catalog_works INTEGER,
      projection_age_h INTEGER, pending_payments INTEGER, approved_payments INTEGER,
      open_reports INTEGER, failed_domains INTEGER, active_broadcasts INTEGER);
    CREATE TABLE IF NOT EXISTS resolved_cache (
      cache_key TEXT PRIMARY KEY, backend TEXT, quality TEXT NOT NULL DEFAULT 'full',
      value_json TEXT, expires_at INTEGER, stale_until INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS circuits (
      backend TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'closed',
      fail_count INTEGER NOT NULL DEFAULT 0, transport_strikes INTEGER NOT NULL DEFAULT 0,
      last_fail_at INTEGER, last_cause TEXT, opened_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS dashboard_cache (
      cache_key TEXT PRIMARY KEY, value_json TEXT, expires_at INTEGER,
      stale_until INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS fleet_crawlers (
      site_key TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'idle',
      last_sync_at INTEGER, progress INTEGER NOT NULL DEFAULT 0,
      failure_reason TEXT, created_at INTEGER, updated_at INTEGER);
    CREATE TABLE IF NOT EXISTS fleet_runs (
      id INTEGER PRIMARY KEY, site_key TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'sync',
      limit_n INTEGER NOT NULL DEFAULT 25, status TEXT NOT NULL DEFAULT 'queued',
      created_by INTEGER, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS fleet_audit (
      id INTEGER PRIMARY KEY, site_key TEXT, action TEXT NOT NULL,
      detail TEXT, created_at INTEGER);
    """),
    (3, """
    CREATE INDEX IF NOT EXISTS idx_audit_actor ON admin_audit_log(actor_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON admin_audit_log(action, created_at);
    CREATE INDEX IF NOT EXISTS idx_sessions_hash ON admin_sessions(session_token_hash);
    CREATE INDEX IF NOT EXISTS idx_visibility_scope ON content_visibility(scope, scope_id, is_hidden);
    CREATE INDEX IF NOT EXISTS idx_cards_section ON slider_cards(section_id, position);
    CREATE INDEX IF NOT EXISTS idx_catworks_cat ON category_works(category_id, position);
    CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_contact_status ON contact_messages(status, created_at);
    CREATE INDEX IF NOT EXISTS idx_domain_health ON domain_health_checks(site_key, checked_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
    """),
    # v4 (2026-11-08, admin-panel audit): scheduled_publishes was
    # added to migration 1's SQL AFTER the live DB had already applied
    # v1, so the live DB (schema_version 3) never got the table and
    # every /admin/live load 500'd. A NEW migration creates it — never
    # append to an already-applied migration again. Fresh DBs already
    # have it from v1; this is a no-op for them.
    (4, """
    CREATE TABLE IF NOT EXISTS scheduled_publishes (
      id INTEGER PRIMARY KEY, scheduled_at INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', created_by INTEGER,
      created_at INTEGER, fired_at INTEGER, fired_version INTEGER,
      cancel_at INTEGER, cancel_by INTEGER, note TEXT);
    """),
]


def _ensure_v5_columns(conn):
    """Migration 5 (2026-11-08, admin-panel audit): additive columns
    only, applied idempotently — a re-run adds nothing twice, so a
    half-applied v5 can never break the next start.

    - domain_registry.last_redirect_to: where the checker was last
      redirected to (the Domains page shows a moved domain instead of
      blessing the stale one as healthy).
    - domain_health_checks.final_domain: the host the check actually
      fingerprinted, after following redirects.
    - app_remote_config_v2 coin_redeem_*: the six coin pass prices the
      panel could previously neither show nor edit.
    """
    wanted = [
        ("domain_registry", "last_redirect_to", "TEXT"),
        ("domain_health_checks", "final_domain", "TEXT"),
    ]
    for name, default in COIN_REDEEM_DEFAULTS.items():
        wanted.append(("app_remote_config_v2", name,
                       "INTEGER NOT NULL DEFAULT %d" % default))
    for table, col, coltype in wanted:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if col not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, coltype))
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (5)")
    conn.commit()


def connect(path):
    conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000")
    return conn


def migrate(conn):
    with WRITE_LOCK:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        cur = conn.execute("SELECT MAX(version) AS v FROM schema_version")
        current = cur.fetchone()["v"] or 0
        for version, sql in MIGRATIONS:
            if version > current:
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()
        _ensure_v5_columns(conn)
        # CSRF tokens are per-session form secrets, not passwords: they
        # are stored with the session so server-rendered forms can use
        # them. The session token itself is never stored, only hashed.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(admin_sessions)")}
        if "csrf_token" not in cols:
            conn.execute("ALTER TABLE admin_sessions ADD COLUMN csrf_token TEXT")
            conn.commit()
        _seed(conn)


def _seed(conn):
    now = int(time.time())
    conn.execute("INSERT OR IGNORE INTO app_remote_config_v2 (id) VALUES (1)")
    conn.execute("INSERT OR IGNORE INTO content_safety (id) VALUES (1)")
    # tuning_settings has only id + audit columns besides values; add
    # value columns on first use via ALTER if missing (keeps migration 2
    # readable while still giving every control a real column).
    existing = {r[1] for r in conn.execute("PRAGMA table_info(tuning_settings)")}
    for name in TUNING_DEFAULTS:
        if name not in existing:
            coltype = "TEXT" if name in TUNING_TEXT_COLUMNS else "INTEGER"
            conn.execute("ALTER TABLE tuning_settings ADD COLUMN %s %s" % (name, coltype))
    conn.execute("INSERT OR IGNORE INTO tuning_settings (id) VALUES (1)")
    # broadcasts gained target_detail after the table existed: an existing
    # database gets the column the same way tuning does, rather than a
    # migration nobody runs.
    bcols = {r[1] for r in conn.execute("PRAGMA table_info(broadcasts)")}
    if "target_detail" not in bcols:
        conn.execute("ALTER TABLE broadcasts ADD COLUMN target_detail TEXT")
    # Seed defaults ONLY where the column is still NULL. An unconditional
    # UPDATE here used to wipe every operator tuning change on every panel
    # restart (2026-11-06 audit): a fresh row gets all defaults, an
    # existing row keeps its values, and a newly added column gets just
    # its own default.
    for name, default in TUNING_DEFAULTS.items():
        conn.execute(
            "UPDATE tuning_settings SET %s = ? WHERE id = 1 AND %s IS NULL"
            % (name, name),
            (default,),
        )
    # Home rails are seeded DISTINCT (2026-11-11 panel fix): hero is
    # curated, trending uses the quality-scored trending rule, and the
    # movie/series rails use the category rule with a type filter — the
    # old seed gave all three the 'latest' rule, so Trending, Movies
    # and Series showed the same 20 newest posts. The movie rail is
    # keyed 'movie' (not 'movies') so it replaces the app's built-in
    # movie rail instead of duplicating it; 'series' already replaces
    # the built-in series rail. INSERT OR IGNORE: only fresh DBs get
    # this; the live DB is updated by the matching migration SQL.
    for i, (key, title, rule, cat_key) in enumerate([
        ("hero", "Hero", "curated", None),
        ("trending", "Trending", "trending", None),
        ("movie", "Movies", "category", "movie"),
        ("series", "Series", "category", "series"),
    ]):
        conn.execute(
            "INSERT OR IGNORE INTO home_sections (key, title, position, is_enabled, source_rule, category_key) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (key, title, i, rule, cat_key),
        )
    for site in FLEET_SITES:
        conn.execute(
            "INSERT OR IGNORE INTO fleet_crawlers (site_key, status, created_at) VALUES (?, 'idle', ?)",
            (site, now),
        )
    conn.commit()


def init_catalog_fixture(path):
    if os.path.exists(path):
        return connect(path)
    conn = connect(path)
    conn.executescript("""
    CREATE TABLE works (id INTEGER PRIMARY KEY, title TEXT NOT NULL,
      type TEXT NOT NULL, year INTEGER, adult_flag INTEGER,
      language TEXT DEFAULT '', dub_label TEXT DEFAULT '',
      poster_state TEXT DEFAULT 'real');
    CREATE INDEX idx_works_title ON works(title);
    """)
    rows = [
        (1, "MOCK Movie One", "movie", 2024, 0, "hindi", "hindi-dubbed", "real"),
        (2, "MOCK Series One", "series", 2023, 0, "urdu", "urdu-original", "real"),
        (3, "MOCK Adult Work", "movie", 2022, 1, "english", "english-original", "real"),
        (4, "MOCK Unknown Flag Work", "movie", 2025, None, "hindi", "hindi-dubbed", "real"),
        (5, "MOCK Movie Two", "movie", 2024, 0, "english", "english-original", "real"),
        (6, "MOCK Drama One", "series", 2021, 0, "urdu", "urdu-original", "real"),
    ]
    conn.executemany("INSERT INTO works VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def init_ledger_fixture(path):
    if os.path.exists(path):
        return connect(path)
    conn = connect(path)
    conn.executescript("""
    CREATE TABLE app_accounts (account_hint TEXT PRIMARY KEY, tier TEXT NOT NULL DEFAULT 'free',
      vip_until INTEGER, device_count INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE payment_claims (id INTEGER PRIMARY KEY, account_hint TEXT NOT NULL,
      method TEXT NOT NULL, amount_pkr INTEGER NOT NULL, months INTEGER NOT NULL,
      tid_value TEXT, status TEXT NOT NULL DEFAULT 'pending',
      created_at INTEGER, decided_at INTEGER, decided_by INTEGER);
    CREATE TABLE ledger_entries (id INTEGER PRIMARY KEY, account_hint TEXT NOT NULL,
      kind TEXT NOT NULL, months INTEGER, payment_id INTEGER, note TEXT, created_at INTEGER);
    CREATE INDEX idx_claims_status ON payment_claims(status, created_at);
    """)
    now = int(time.time())
    conn.executemany(
        "INSERT INTO app_accounts VALUES (?,?,?,?)",
        [("ac***01", "free", None, 1), ("ac***02", "vip", now + 30 * 86400, 2)],
    )
    # tid_value is left NULL in fixtures on purpose: no transaction id
    # is stored, printed, or quoted in any fixture, doc, or report.
    conn.executemany(
        "INSERT INTO payment_claims VALUES (?,?,?,?,?,NULL,'pending',?,NULL,NULL)",
        [(1, "ac***01", "jazzcash", 200, 1, now),
         (2, "ac***02", "easypaisa", 1500, 12, now)],
    )
    conn.commit()
    return conn
