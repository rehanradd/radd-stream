"""Server-rendered HTML, design §21 exactly, no external assets.

Radd Stream brand: deep violet primary, dark plum sidebar, soft
lavender-grey page, white cards with shadow. Layout is a CSS grid:
sidebar + main column, so the page header lives inside the main
column and is never covered by the sidebar. Tokens: 4-point spacing
(4,8,12,16,20,24,32,48), system font stack, 16px base text, tap
targets >=44px, status always colour + icon + label, dark + light
via prefers-color-scheme, breakpoints <600 phone (bottom tabs),
600-767 drawer, 768-1023 2-column, >=1024 sidebar, >=1280
3-column dashboard. No JavaScript, no external font, no external
script, no tracker. Icons are inline SVG only.
"""
import html
from datetime import datetime, timezone

CSS = """
:root{--bg:#F3F4F9;--card:#FFFFFF;--surface:#F7F7FC;--text:#191B26;
--secondary:#5A5F73;--border:#E3E5EF;--primary:#5B21B6;
--primary-strong:#4C1D95;--primary-soft:#EDE9FE;--accent:#DB2777;
--success:#15803D;--success-bg:#DCFCE7;--warning:#B45309;
--warning-bg:#FEF3C7;--danger:#B91C1C;--danger-bg:#FEE2E2;
--info:#1D4ED8;--info-bg:#DBEAFE;--sidebar-bg:#1C1533;
--sidebar-text:#C9C4E8;--shadow:0 1px 2px rgba(23,16,53,.06),0 8px 24px rgba(23,16,53,.06);
--shadow-lg:0 2px 6px rgba(23,16,53,.08),0 16px 40px rgba(23,16,53,.12)}
@media (prefers-color-scheme: dark){
:root{--bg:#0F0E18;--card:#1B1929;--surface:#232036;--text:#F2F0FA;
--secondary:#A8A4C2;--border:#2E2A45;--primary:#A78BFA;
--primary-strong:#C4B5FD;--primary-soft:#2E2452;--accent:#F472B6;
--success:#4ADE80;--success-bg:#14532D;--warning:#FBBF24;
--warning-bg:#451A03;--danger:#F87171;--danger-bg:#450A0A;
--info:#93C5FD;--info-bg:#172554;--sidebar-bg:#17122B;
--sidebar-text:#B9B2E0;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.4);
--shadow-lg:0 2px 6px rgba(0,0,0,.5),0 16px 40px rgba(0,0,0,.5)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
font-size:16px;line-height:1.55}
a{color:var(--primary)} a:focus-visible,button:focus-visible,
input:focus-visible,select:focus-visible,textarea:focus-visible{
outline:3px solid var(--primary);outline-offset:2px}
.shell{min-height:100vh}
.maincol{min-width:0}
header.pagehead{padding:20px 16px 0;max-width:1200px;margin:0 auto}
header.pagehead h1{font-size:26px;line-height:1.2;margin:0}
.tagline{color:var(--secondary);margin:4px 0 0;font-size:14px}
main{padding:16px 16px 120px 16px;max-width:1200px;margin:0 auto}
h1{font-size:26px;line-height:1.2;margin:0 0 16px 0}
h2{font-size:20px;line-height:1.25;margin:0 0 12px 0}
h3{font-size:16px;margin:0 0 8px 0}
p{margin:0 0 12px 0}
.muted{color:var(--secondary)}
.card{background:var(--card);border:1px solid var(--border);
border-radius:16px;padding:20px;margin:0 0 16px 0;box-shadow:var(--shadow)}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;
border-radius:999px;font-size:13px;font-weight:600;background:var(--info-bg);color:var(--info)}
.badge.success{background:var(--success-bg);color:var(--success)}
.badge.warning{background:var(--warning-bg);color:var(--warning)}
.badge.danger{background:var(--danger-bg);color:var(--danger)}
.badge.info{background:var(--info-bg);color:var(--info)}
button,.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
min-height:44px;min-width:44px;padding:12px 20px;border-radius:12px;
border:1px solid transparent;background:var(--primary);color:#fff;
text-decoration:none;font-size:16px;font-weight:600;cursor:pointer}
button:hover,.btn:hover{background:var(--primary-strong)}
.btn.secondary{background:transparent;border-color:var(--border);color:var(--text)}
.btn.secondary:hover{background:var(--surface)}
.btn.danger{background:var(--danger)}
.btn.danger:hover{background:#991B1B}
label{display:block;margin:12px 0 4px 0;font-weight:600}
label.check{display:flex;align-items:center;gap:12px;margin:16px 0 4px 0;cursor:pointer}
label.check input[type=checkbox]{width:22px;height:22px;min-height:22px;
flex:0 0 auto;margin:0;accent-color:var(--primary)}
input,select,textarea{width:100%;min-height:44px;padding:10px 12px;
border-radius:12px;border:1px solid var(--border);
background:var(--card);color:var(--text);font-size:16px;
box-shadow:inset 0 1px 2px rgba(23,16,53,.04)}
input[type=checkbox]{width:auto;min-height:24px}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--border);
border-radius:16px;margin:0 0 16px 0;box-shadow:var(--shadow)}
.tablewrap table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:12px 16px;border-bottom:1px solid var(--border);vertical-align:middle}
thead th{font-size:13px;text-transform:uppercase;letter-spacing:.04em;
color:var(--secondary);background:var(--surface);white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
td .badge{white-space:nowrap}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.bottomnav{position:fixed;left:0;right:0;bottom:0;display:flex;
background:var(--card);border-top:1px solid var(--border);
padding-bottom:env(safe-area-inset-bottom)}
.bottomnav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;
padding:8px 2px 10px;min-height:56px;text-decoration:none;color:var(--secondary);font-size:12px}
.bottomnav a .nav-ico{display:flex;padding:2px 10px;border-radius:999px}
.bottomnav a.active{color:var(--primary);font-weight:700}
.bottomnav a.active .nav-ico{background:var(--primary-soft)}
.sidebar{display:none}
.stickybar{padding:16px 0 0;display:flex;flex-wrap:wrap;gap:12px}
.stickybar button{flex:0 1 auto}
.skeleton{background:var(--surface);border-radius:16px;height:64px;margin:0 0 12px 0}
.error{border:1px solid var(--danger);color:var(--danger);background:var(--danger-bg);
border-radius:12px;padding:16px}
.empty{border:1px dashed var(--border);border-radius:16px;padding:20px;color:var(--secondary)}
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:0 0 16px 0}
.stat{background:var(--card);border:1px solid var(--border);border-radius:16px;
padding:20px;box-shadow:var(--shadow)}
.stat-label{font-size:14px;color:var(--secondary);font-weight:600}
.stat-num{font-size:32px;font-weight:800;line-height:1.15;margin:6px 0}
.filterbar{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;
background:var(--card);border:1px solid var(--border);border-radius:16px;
padding:16px;margin:0 0 16px 0;box-shadow:var(--shadow)}
.filterbar .field{flex:1 1 200px}
.filterbar label{margin:0 0 4px 0}
.filterbar button{flex:0 0 auto}
.pager{margin:0 0 16px 0}
.auth{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px}
.auth-card{width:100%;max-width:420px;background:var(--card);
border:1px solid var(--border);border-radius:20px;padding:32px 28px;box-shadow:var(--shadow-lg)}
.auth-card button{width:100%}
.auth-logo{display:flex;flex-direction:column;align-items:center;gap:12px;
text-align:center;margin-bottom:8px}
.auth-logo .brand-name{font-size:22px;font-weight:800}
.auth-card h1{text-align:center}
.auth-card .lede{text-align:center;color:var(--secondary);font-size:14px}
.auth-note{text-align:center;color:var(--secondary);font-size:14px;margin:16px 0 0 0}
@media (max-width:767px){
.tablewrap{border:none;background:transparent;box-shadow:none;border-radius:0;overflow:visible}
table,thead,tbody,th,td,tr{display:block} thead{display:none}
tbody tr{background:var(--card);border:1px solid var(--border);border-radius:16px;
padding:12px 16px;margin:0 0 12px 0;box-shadow:var(--shadow)}
td{border:none;padding:4px 0}
td::before{content:attr(data-label);display:block;font-weight:700;
font-size:13px;color:var(--secondary)}
.stickybar button{flex:1 1 100%}}
@media (min-width:768px){
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media (min-width:1024px){
.shell{display:grid;grid-template-columns:264px minmax(0,1fr)}
.sidebar{display:flex;flex-direction:column;position:sticky;top:0;height:100vh;
background:var(--sidebar-bg);color:var(--sidebar-text);padding:20px 12px;overflow-y:auto}
.sidebar .brand{display:flex;gap:12px;align-items:center;padding:4px 12px 20px;color:#fff}
.sidebar .brand-name{font-size:18px;font-weight:800;line-height:1.2}
.sidebar .brand-sub{font-size:13px;color:var(--sidebar-text)}
.sidebar a.navitem{display:flex;align-items:center;gap:12px;padding:11px 12px;
min-height:44px;border-radius:10px;color:var(--sidebar-text);text-decoration:none;font-weight:600}
.sidebar a.navitem:hover{background:rgba(255,255,255,.06);color:#fff}
.sidebar a.navitem.active{background:rgba(255,255,255,.12);color:#fff}
.sidebar a.navitem svg{flex:0 0 auto}
.sidebar .side-foot{margin-top:auto;padding:16px 12px 4px;font-size:13px;color:var(--sidebar-text)}
header.pagehead{padding:28px 32px 0}
main{padding:24px 32px 48px 32px}
.bottomnav{display:none}
.stats{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media (min-width:1280px){.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}}
"""

STATUS = {
    "Active": ("success", "✓"), "Published": ("success", "✓"),
    "Paused": ("warning", "⏸"), "Disabled": ("info", "○"),
    "Failed": ("danger", "⚠"), "Pending": ("warning", "◷"),
    "Draft": ("info", "◷"), "Warning": ("warning", "⚠"),
    "Unknown": ("warning", "?"), "Healthy": ("success", "✓"),
    "free": ("info", "○"), "vip": ("success", "★"),
    "pending": ("warning", "◷"), "approved": ("success", "✓"),
    "rejected": ("danger", "✕"), "Safe": ("success", "✓"),
    "Adult": ("danger", "⚠"), "Enabled": ("success", "✓"),
    "open": ("warning", "◷"), "in_progress": ("info", "◷"),
    "resolved": ("success", "✓"), "spam": ("danger", "✕"),
    "info": ("info", "•"), "warning": ("warning", "⚠"),
    "critical": ("danger", "⚠"), "idle": ("info", "○"),
    "running": ("success", "▶"), "Real": ("success", "✓"),
    "real": ("success", "✓"), "missing": ("warning", "?"),
    "broken": ("danger", "✕"),
}


def badge(label):
    """Status pill: colour + icon + label. The label is stored raw
    (lowercase enum values like "pending" or "in_progress"); the
    display capitalises it ("Pending", "In Progress") so the table
    never shows raw lowercase text (audit §Cosmetic). Lookup uses the
    raw label first, so existing STATUS keys keep working."""
    cls, icon = STATUS.get(label, ("info", "•"))
    display = str(label).replace("_", " ").title()
    return '<span class="badge %s">%s %s</span>' % (cls, icon, html.escape(display))


def fmt_date(ts):
    """Unix seconds -> '04 Dec 2026'. None/0/invalid -> an em dash."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return "—"
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y")
    except (OverflowError, OSError, ValueError):
        return "—"


def fmt_datetime(ts):
    """Unix seconds -> '05 Nov 2026, 14:32'. None/0/invalid -> an em dash."""
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return "—"
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %Y, %H:%M")
    except (OverflowError, OSError, ValueError):
        return "—"


def fmt_mixed_datetime(value):
    """A last-sync stamp that may be unix seconds (admin_fleet_audit)
    or an ISO-8601 string (crawler <site>_status.json updated_at).
    Either renders as '05 Nov 2026, 14:32'; anything else -> an em dash."""
    if isinstance(value, (int, float)):
        return fmt_datetime(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "—"
        try:
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%d %b %Y, %H:%M")
        except ValueError:
            pass
        try:
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%d %b %Y, %H:%M")
        except ValueError:
            return "—"
    return "—"


def fmt_pkr(amount):
    """Integer rupees -> 'PKR 1,500'. Invalid -> an em dash."""
    try:
        return "PKR {:,}".format(int(amount))
    except (TypeError, ValueError):
        return "—"


def esc(v):
    return html.escape(str(v) if v is not None else "")


class Raw(str):
    """A table cell already rendered as safe HTML (e.g. a badge)."""


def _logo(size, gid):
    return ('<svg width="%d" height="%d" viewBox="0 0 40 40" aria-hidden="true">'
            '<defs><linearGradient id="%s" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#7C3AED"/>'
            '<stop offset="1" stop-color="#DB2777"/></linearGradient></defs>'
            '<rect width="40" height="40" rx="11" fill="url(#%s)"/>'
            '<path d="M16 12l12 8-12 8z" fill="#fff"/></svg>') % (size, size, gid, gid)


# Inline SVG icons (stroke = currentColor, 20px). No external assets.
ICONS = {
    "home": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>',
    "film": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 10h4M3 14h4M17 10h4M17 14h4"/></svg>',
    "layers": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/></svg>',
    "users": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3.5"/><path d="M3.5 20c.5-3.5 2.8-5 5.5-5s5 1.5 5.5 5"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 15c2 .3 3.5 1.6 4 4"/></svg>',
    "banknote": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 12h.01M18 12h.01"/></svg>',
    "inbox": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>',
    "flag": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 21V4"/><path d="M6 4h11l-2 4 2 4H6"/></svg>',
    "megaphone": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10v4h4l5 4V6L7 10H3z"/><path d="M16 9a4 4 0 010 6"/></svg>',
    "globe": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>',
    "server": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M8 7.5h.01M8 16.5h.01"/></svg>',
    "chart": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 20v-6M11 20V6M17 20v-9"/><path d="M3 20h18"/></svg>',
    "sliders": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h9M19 7h1M4 17h3M13 17h7"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>',
    "search": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    "live": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/><path d="M7.5 7.5a6.4 6.4 0 000 9M16.5 7.5a6.4 6.4 0 010 9M4.6 4.6a10.5 10.5 0 000 14.8M19.4 4.6a10.5 10.5 0 010 14.8"/></svg>',
    "activity": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
    "dots": '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>',
    "wrench": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>',
    "coins": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="9" r="6.5"/><path d="M14.8 4.6a6.5 6.5 0 010 8.8"/></svg>',
    "database": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
}

NAV_ITEMS = [
    ("home", "/admin", "Home", "home"),
    ("content", "/admin/content", "Content", "film"),
    ("sections", "/admin/sections", "Sections", "layers"),
    ("users", "/admin/users", "Users", "users"),
    ("money", "/admin/money", "Money", "banknote"),
    ("inbox", "/admin/inbox", "Inbox", "inbox"),
    ("requests", "/admin/requests", "Requests", "search"),
    ("reports", "/admin/reports", "Reports", "flag"),
    ("broadcasts", "/admin/broadcasts", "Broadcasts", "megaphone"),
    ("live", "/admin/live", "Live", "live"),
    ("live-tv", "/admin/live-tv", "Live TV", "live"),
    ("domains", "/admin/domains", "Domains", "globe"),
    ("fleet", "/admin/fleet", "Fleet", "server"),
    ("analytics", "/admin/analytics", "Analytics", "chart"),
    ("usage", "/admin/usage", "Usage", "activity"),
    ("tuning", "/admin/tuning", "Tuning", "wrench"),
    ("monetization", "/admin/monetization", "Monetization", "coins"),
    ("data-health", "/admin/data-health", "Data health", "database"),
    ("settings", "/admin/settings", "Settings", "sliders"),
]

BOTTOM_ITEMS = [
    ("home", "/admin", "Home", "home"),
    ("content", "/admin/content", "Content", "film"),
    ("users", "/admin/users", "Users", "users"),
    ("money", "/admin/money", "Money", "banknote"),
    ("more", "/admin/more", "More", "dots"),
]

# Bottom-tab highlight for pages that have no bottom tab of their own.
BOTTOM_ACTIVE = {
    "sections": "content",
    "inbox": "more", "requests": "more", "reports": "more", "broadcasts": "more", "live": "more",
    "live-tv": "more",
    "domains": "more", "fleet": "more", "analytics": "more", "usage": "more",
    "tuning": "more", "monetization": "more", "data-health": "more",
    "settings": "more", "search": "more",
}


def layout(title, body, active="home", csrf="", state="", error="", nav=True):
    parts = []
    if state == "loading":
        parts.append('<div class="skeleton" aria-label="Loading"></div>'
                     '<div class="skeleton" aria-label="Loading"></div>')
    if error:
        parts.append('<div class="error" role="alert">%s. Try again.</div>' % esc(error))
    parts.append(body)
    if not nav:
        return """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s — Radd Stream Admin</title><style>%s</style></head>
<body><header class="pagehead"><h1>Radd Stream Admin</h1><p class="tagline">Visible on next app refresh. Never instant.</p></header>
<main>%s</main></body></html>""" % (esc(title), CSS, "".join(parts))
    side = "".join(
        '<a class="navitem%s" href="%s">%s<span>%s</span></a>' % (
            " active" if active == key else "", href, ICONS[icon], label)
        for key, href, label, icon in NAV_ITEMS
    )
    bottom_active = BOTTOM_ACTIVE.get(active, active)
    nav = "".join(
        '<a href="%s" class="%s"><span class="nav-ico">%s</span>%s</a>' % (
            href, "active" if bottom_active == key else "", ICONS[icon], label)
        for key, href, label, icon in BOTTOM_ITEMS
    )
    return """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s — Radd Stream Admin</title><style>%s</style></head>
<body><div class="shell"><nav class="sidebar" aria-label="Admin sections">
<div class="brand">%s<div><div class="brand-name">Radd Stream</div><div class="brand-sub">Admin Panel</div></div></div>
%s<div class="side-foot">Radd Stream Admin · v2</div></nav>
<div class="maincol"><header class="pagehead"><h1>%s</h1><p class="tagline">Visible on next app refresh. Never instant.</p></header>
<main>%s</main></div></div><nav class="bottomnav" aria-label="Admin tabs">%s</nav>
</body></html>""" % (esc(title), CSS, _logo(40, "lg-side"), side, esc(title), "".join(parts), nav)


def table(headers, rows, empty_text, next_action=""):
    if not rows:
        return '<div class="empty"><p>%s</p>%s</div>' % (
            esc(empty_text), ('<p><a class="btn" href="%s">Next step</a></p>' % next_action) if next_action else "")
    head = "".join("<th>%s</th>" % esc(h) for h in headers)
    body = "".join(
        "<tr>" + "".join(
            '<td data-label="%s">%s</td>' % (
                esc(headers[i]) if i < len(headers) else "",
                c if isinstance(c, Raw) else esc(c))
            for i, c in enumerate(r)) + "</tr>" for r in rows
    )
    return ('<div class="tablewrap"><table><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>') % (head, body)


def form_hidden(csrf, nxt):
    """Hidden CSRF + _next fields for every authenticated HTML form."""
    return ('<input type="hidden" name="csrf_token" value="%s">'
            '<input type="hidden" name="_next" value="%s">') % (esc(csrf or ""), esc(nxt))


def login_page(error=""):
    err = '<div class="error" role="alert">%s</div>' % esc(error) if error else ""
    return """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Log in — Radd Stream Admin</title><style>%s</style></head>
<body><div class="auth"><div class="auth-card">
<div class="auth-logo">%s<div class="brand-name">Radd Stream</div></div>
<h1>Admin sign in</h1>
<p class="lede">Sign in to manage the app, catalog, users and payments.</p>
%s
<form method="post" action="/admin/login" aria-label="Admin login">
<label for="username">Username</label>
<input id="username" name="username" type="text" autocomplete="username" required>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<label for="totp">Authenticator code, if you use one</label>
<input id="totp" name="totp" type="text" inputmode="numeric" autocomplete="one-time-code">
<div class="stickybar"><button type="submit">Log in</button></div>
</form><p class="auth-note">No forgot-password link here. Recovery is VM-local only.</p>
</div></div></body></html>""" % (CSS, _logo(56, "lg-login"), err)
