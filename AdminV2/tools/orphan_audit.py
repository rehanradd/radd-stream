"""Orphan audit (§22 steps 1-5), workspace only.

Checks:
1. Every pairing-matrix endpoint exists in the server's route table.
2. Every pairing-matrix field table is a known schema/fixture table
   (or a named display-only field).
3. Every pairing-matrix behaviour name is known.
4. Every server API route appears in the matrix, or is a listed helper.
Exit 0 = zero orphans. Exit 1 = orphans found (do not ship).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from admin_v2 import pairing  # noqa: E402

DISPLAY_ONLY_FIELDS = {"panel_settings_display"}
KNOWN_BEHAVIOURS = {
    "auth_session", "dashboard_counts", "audit_browser", "home_layout",
    "search_works", "tuning_value", "pause_effect", "vip_status",
    "flag_stored", "payment_list", "payment_detail", "public_remote_config",
    "contact_status", "report_status", "domain_lookup", "fleet_list",
    "analytics_rows", "panel_settings", "request_list", "live_tv",
}
KNOWN_TABLES = {
    "admin_sessions", "admin_users", "admin_audit_log", "home_sections",
    "slider_cards", "content_visibility", "categories", "category_works",
    "content_safety", "tuning_settings", "pauses", "user_flags",
    "app_remote_config_v2", "app_remote_config_history", "scheduled_publishes", "broadcasts",
    "contact_messages", "reports", "report_actions", "domain_registry",
    "domain_candidates", "domain_health_checks", "domain_history",
    "fleet_crawlers", "fleet_runs", "analytics_daily", "catalog_fixture",
    "ledger_fixture", "dashboard_cache", "payment_transactions",
    "user_accounts", "app_remote_config", "cat_works", "posts",
    "admin_fleet_audit", "cat_link_evidence", "cat_review_queue",
    "cat_projection_meta", "movie_requests", "coin_ledger",
    "usage_device", "usage_metric", "usage_dim_metric",
    "live_tv_registry",
}
HELPER_ROUTES = {
    ("POST", "/admin/api/v2/auth/logout"),
    ("GET", "/admin/api/v2/auth/me"),
    ("POST", "/admin/api/v2/auth/password-change"),
    ("GET", "/admin/api/v2/remote-config/history"),
    ("POST", "/admin/api/v2/analytics/compute"),
    ("POST", "/admin/api/v2/prune"),
    ("GET", "/admin/api/v2/payments/search"),
}
# Matrix endpoints handled outside the R() route table (login page /
# public contract dispatch in _dispatch, not in _api).
NON_R_ROUTES = {
    ("POST", "/admin/login"),
    ("POST", "/admin/api/v2/auth/logout"),
    ("POST", "/admin/api/v2/auth/password-change"),
    ("GET", "/api/v1/app/remote-config"),
}


def norm(path):
    path = re.sub(r"\{[^}]+\}", "{param}", path)
    path = re.sub(r"\(\[\^/\]\+\)", "{param}", path)
    path = re.sub(r"\(\\d\+\)", "{param}", path)
    return path


def server_routes():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "admin_v2", "server.py")).read()
    routes = set()
    for meth, pattern in re.findall(r'R\(\("(GET|POST|PUT|DELETE)",\s*r"\^([^"]+)\$"', src):
        routes.add((meth, norm(pattern)))
    return routes


def main():
    orphans = []
    matrix_eps = set()
    for control, (meth, path, field, behaviour) in pairing.MATRIX.items():
        matrix_eps.add((meth, norm(path)))
        if behaviour not in KNOWN_BEHAVIOURS:
            orphans.append("behaviour unknown for control %s: %s" % (control, behaviour))
        if field in DISPLAY_ONLY_FIELDS:
            continue
        if field.split(".")[0] not in KNOWN_TABLES:
            orphans.append("field table unknown for control %s: %s" % (control, field))
    routes = server_routes()
    for meth, path in sorted(matrix_eps):
        if (meth, path) in NON_R_ROUTES:
            continue
        if (meth, path) not in routes:
            orphans.append("matrix endpoint has no server route: %s %s" % (meth, path))
    helper_norm = {(m, norm(p)) for m, p in HELPER_ROUTES}
    for meth, path in sorted(routes):
        if (meth, path) in matrix_eps or (meth, path) in helper_norm:
            continue
        orphans.append("server route has no matrix control: %s %s" % (meth, path))
    if orphans:
        print("ORPHANS FOUND (%d):" % len(orphans))
        for o in orphans:
            print(" - " + o)
        return 1
    print("Orphan audit: 0 orphans (%d matrix controls, %d server routes)"
          % (len(pairing.MATRIX), len(routes)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
