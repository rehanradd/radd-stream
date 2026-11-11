"""Fixture app client: reads only the public contract, like a phone would.

This is the proof layer for the pairing matrix (§22): a panel control
only counts as working if this client, reading the same public
endpoints/serve-time rules the real app uses, sees the change — and
sees it return on undo.

App-needs folding (research-app-needs): the public contract here
supports the Now items the panel can lever — reliable Play inputs
(cache + direct-first + silent failover + honest no-source), search
with real posters and de-duplication (one card per work), language/dub
filters, adult fail-closed, one-tap report feeding the admin queue,
and Pakistan VIP payments. Player, casting, recommendations, sync,
and other app features are NOT built here; they are recorded as
app-side Next/Later items in the progress log.
"""
import time

V1_REMOTE_CONFIG_KEYS = {
    "maintenance_mode", "apk_update_url", "feature_downloads",
    "feature_pure_cinema", "feature_chromecast", "feature_quality_gate",
    "vip_monthly_pkr", "vip_yearly_pkr", "pak_till_id",
    "pak_jazzcash_number", "pak_easypaisa_number", "pak_raast_id",
    "monetag_zone_id", "adsterra_tag_id",
}


def _latest_snapshot(service):
    row = service.admin.execute(
        "SELECT * FROM app_remote_config_history ORDER BY config_version DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    import json
    return json.loads(row["snapshot_json"])


def public_remote_config(service):
    """Public, ungated, additive-only. Never a token, never a raw link."""
    cfg = service._redacted_config(service._config_row())
    # apk_update_url is the app's own update link (not a content/host
    # link): the app needs the real URL here, but the redacted config
    # strips it for audit safety, so read it from the raw row.
    raw = service._config_row()
    snap = _latest_snapshot(service)
    config_version = snap["config"]["config_version"] if snap else cfg["config_version"]
    # Feature pauses are enforced here, where the panel is the
    # consumer: a paused feature reads as off until resumed. (A
    # prefetch_global pause has no panel consumer and stays stored-only.)
    _feat = {
        "downloads": bool(cfg["feature_downloads"]),
        "pure_cinema": bool(cfg["feature_pure_cinema"]),
        "chromecast": bool(cfg["feature_chromecast"]),
        "quality_gate": bool(cfg["feature_quality_gate"]),
    }
    for _name in list(_feat):
        if service.is_paused("feature", _name):
            _feat[_name] = False
    out = {
        "config_version": config_version,
        "maintenance_mode": bool(cfg["maintenance_mode"]),
        "apk_update_url": raw.get("apk_update_url") or "",
        "feature_flags": _feat,
        "vip": {"monthly_pkr": cfg["vip_monthly_pkr"], "yearly_pkr": cfg["vip_yearly_pkr"]},
        "payments": {
            "jazzcash_till_id": cfg["pak_till_id"],
            "jazzcash_mobile_account": cfg["pak_jazzcash_number"],
            "easypaisa_mobile_number": cfg["pak_easypaisa_number"],
            "raast_instant_id": cfg["pak_raast_id"],
        },
        "ads": {"monetag_rewarded_zone_id": cfg["monetag_zone_id"],
                "adsterra_native_banner_id": cfg["adsterra_tag_id"]},
        "link_shorteners": {
            "shrinkme": cfg["shrinkme_configured"],
            "droplink": cfg["droplink_configured"],
        },
        # Additive v2 fields: an old app must ignore these safely.
        "sections": home_layout(service),
        "active_broadcasts": service.active_broadcasts(),
        "free_quality_cap": cfg.get("free_quality_cap", "720p"),
        "region_order": cfg.get("region_order", ""),
        "refresh_note": "visible on next app refresh",
    }
    return out


def old_app_parse(public_config):
    """Old-app fixture: reads only v1 keys, ignores new fields, no crash.

    The v1 contract was flat; the v2 public body groups flags, VIP,
    payments, and ads into objects. An old app reads the grouped
    values it knows and ignores sections/active_broadcasts/etc.
    """
    flags = public_config.get("feature_flags", {})
    vip = public_config.get("vip", {})
    pays = public_config.get("payments", {})
    ads = public_config.get("ads", {})
    flat = {
        "maintenance_mode": public_config.get("maintenance_mode"),
        "apk_update_url": public_config.get("apk_update_url"),
        "feature_downloads": flags.get("downloads"),
        "feature_pure_cinema": flags.get("pure_cinema"),
        "feature_chromecast": flags.get("chromecast"),
        "feature_quality_gate": flags.get("quality_gate"),
        "vip_monthly_pkr": vip.get("monthly_pkr"),
        "vip_yearly_pkr": vip.get("yearly_pkr"),
        "pak_till_id": pays.get("jazzcash_till_id"),
        "pak_jazzcash_number": pays.get("jazzcash_mobile_account"),
        "pak_easypaisa_number": pays.get("easypaisa_mobile_number"),
        "pak_raast_id": pays.get("raast_instant_id"),
        "monetag_zone_id": ads.get("monetag_rewarded_zone_id"),
        "adsterra_tag_id": ads.get("adsterra_native_banner_id"),
    }
    return {k: v for k, v in flat.items() if k in V1_REMOTE_CONFIG_KEYS}


def _work_visible(service, work, section_key=None, section_adult_only=False):
    # Adult fail-closed: adult (1) or unknown (None) is hidden from any
    # non-adult surface, regardless of any panel hide/unhide.
    if not section_adult_only and work["adult_flag"] != 0:
        return False
    if service.is_work_hidden(work["id"], section_key):
        return False
    return True


def home_layout(service):
    """Published home only (draft changes do not appear until publish)."""
    snap = _latest_snapshot(service)
    if not snap:
        return []
    layout = []
    for entry in snap["home"]["sections"]:
        sec = entry["section"]
        if not sec["is_enabled"]:
            continue
        if service.is_paused("section", sec["key"]):
            continue  # paused keeps its place in draft, omitted live
        if sec.get("category_key") and service.is_paused("category", sec["category_key"]):
            continue  # a paused category omits its sections live
        if not sec["is_adult_only"]:
            # An adult-only section is omitted when the global switch
            # is OFF (it is always OFF in v2, OD-18).
            pass
        safety = service.get_content_safety({"role": "auditor", "id": 0})
        if sec["is_adult_only"] and not safety["adult_content_enabled"]:
            continue
        cards = []
        for card in entry["cards"]:
            if not card["is_enabled"]:
                continue
            work = service._get_work_any(card["work_id"])
            if not work:
                continue
            if not _work_visible(service, work, sec["key"], bool(sec["is_adult_only"])):
                continue
            # De-duplication: one card per work per section.
            if any(c["work_id"] == work["id"] for c in cards):
                continue
            cards.append({"work_id": work["id"], "title": work["title"],
                          "type": work["type"], "year": work["year"],
                          "language": work.get("language", ""), "dub_label": work.get("dub_label", ""),
                          "poster_state": work.get("poster_state", "missing"),
                          "title_override": card["title_override"]})
        if not cards and sec.get("source_rule") in ("latest", "trending", "category"):
            # Source-rule execution: a section with no explicit cards
            # resolves its rule against the real catalog (or fixture).
            # Hero is 'curated' by default and never fills this way.
            try:
                preview = service.resolve_section_preview(
                    {"role": "auditor", "id": 0}, sec["key"])
            except Exception:
                preview = {"items": []}
            cap = 20
            for work in preview.get("items", [])[:cap]:
                if not _work_visible(service, work, sec["key"], bool(sec["is_adult_only"])):
                    continue
                if any(c["work_id"] == work["id"] for c in cards):
                    continue
                cards.append({"work_id": work["id"], "title": work["title"],
                              "type": work["type"], "year": work["year"],
                              "language": work.get("language", ""),
                              "dub_label": work.get("dub_label", ""),
                              "poster_state": work.get("poster_state", "missing"),
                              "title_override": None})
        if sec["key"] == "hero" and not cards:
            continue  # hero 0 = hero omitted, never an empty hero
        layout.append({"key": sec["key"], "title": sec["title"],
                       "position": sec["position"], "cards": cards})
    layout.sort(key=lambda s: s["position"])
    return layout


def vip_status(service, account_hint):
    """Fresh ledger read every time — never cached (safety rule)."""
    live = service._live_ledger() if hasattr(service, "_live_ledger") else None
    if live is not None:
        res = live.search_users(q=account_hint, limit=5)
        for item in res["items"]:
            if item["account_hint"] == account_hint:
                return {"account_hint": item["account_hint"], "tier": item["tier"],
                        "vip_until": item["vip_until"],
                        "device_count": item.get("device_count", 0)}
        return None
    row = service.ledger.execute(
        "SELECT * FROM app_accounts WHERE account_hint=?", (account_hint,)).fetchone()
    if not row:
        return None
    return {"account_hint": row["account_hint"], "tier": row["tier"],
            "vip_until": row["vip_until"], "device_count": row["device_count"]}


def domain_lookup(service, site_key):
    return service.resolve_domain(site_key)


def resolved_link(service, cache_key):
    """Resolved-cache read with its quality flag (full/stale/None)."""
    from . import smart
    value, quality = smart.cache_get(service.admin, cache_key)
    return {"value": value, "quality": quality or "miss"}


def play_candidates(service, candidates, probe_fn):
    """Direct-first early-exit, with an audit note for skipped candidates.

    Returns (winner, skipped_notes, quality) where quality is 'full'
    on a winner and 'failed' with an honest no-source otherwise.
    """
    from . import smart
    winner, skipped = smart.early_exit_probe(candidates, probe_fn)
    if winner:
        return winner, skipped, "full"
    return None, skipped, "failed"
