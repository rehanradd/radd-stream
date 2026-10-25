#!/usr/bin/env python3
"""api_v2.py — the v2 wire layer (API_V2.md §12), mounted by viewer.py.

Layer 1 is the `cat_*` projection (`catalog_v2.py`). Layer 2 is the read model
(`catalog_api.py`), which already applies the single adult scope and already
refuses to build provenance into any shape. What was missing was the HTTP edge:
every route in §12 existed as a Python function and none of it was reachable.
This module is that edge, and it invents no vocabulary — it moves Layer 2's
payloads onto a socket under the cross-cutting rules of §16:

  * RFC 9457 `application/problem+json` with the closed code list of §16.4;
    a route never invents a code, and a body never carries a stack trace or a
    reason that names a site.
  * One `adult_scope()` where-clause for every query written here, plus a
    wire-level key denial (`deny_flag_keys`) so the flag itself can never appear
    in a public body — §13's "not even as false". `redact.VIEWS` legitimately
    carries the key for an admin listing, and `redact.py` is the owner's file, so
    the denial lives at the wire.
  * `ETag` / `If-None-Match` → 304 and per-route-class `Cache-Control` (§16.2).
  * `RateLimit-Limit/Remaining/Reset` on every response and `Retry-After` on 429
    (§16.5), served by the *existing* `redact.limiter` token buckets — this
    module keeps no counter of its own.
  * Provenance stays denied: Layer-2 payloads leave through its `@public_edge`
    (`redact.scrub`), and the handful of shapes built here (manifest, stats,
    sync, feed) are scrubbed explicitly.

`operator=True` (the loopback port) is the only caller that may see unlisted
rows at all, and it is set on the server instance, never on a request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from email.utils import formatdate

import catalog_api
import catalog_v2
import redact
import release_descriptor
import tiers

CONTRACT_VERSION = "2.1.0"
BASE_PATH = "/api/v2"

#: §16.4 — the complete, closed enumeration. Adding a code is additive; renaming
#: one is a v3 decision. Clients switch on `code`; `title` is human copy.
PROBLEM_CODES: dict[str, tuple[int, str]] = {
    "invalid_params": (400, "Invalid request parameters"),
    "cursor_invalid": (400, "The pagination cursor is not valid for this request"),
    "unauthorised": (401, "Authentication required"),
    "licence_required": (402, "A licence is required before this can be played"),
    "forbidden": (403, "This action is not allowed"),
    "not_found": (404, "The requested resource does not exist"),
    "no_playable_source": (409, "No source for this target can currently play"),
    "gone": (410, "This resource has been withdrawn from the catalog"),
    "bundle_expired": (410, "This play bundle has expired"),
    "licence_expired": (410, "The licence window for this item has passed"),
    "rate_limited": (429, "Too many requests"),
    "target_unresolvable": (422, "The requested target cannot be assembled"),
    "internal": (500, "Internal error"),
    "unavailable": (503, "The catalog is not ready"),
}

#: Layer 2's internal words → the public enumeration. Nothing else maps: an
#: unrecognised code collapses to `not_found`, never to a new public code.
_CODE_ALIASES = {
    "invalid_input": "invalid_params",
    "bad_input": "invalid_params",
    "bad_connection": "unavailable",
    "no_source_recorded": "no_playable_source",
    "no_playable_source": "no_playable_source",
}

#: §13: the flag, and any synonym of it, is never a public key — not even as
#: `false`, because a field that appears only for hidden rows is itself the leak.
_FLAG_KEY_RE = re.compile(r"adult|18[_+]?plus|restricted|nsfw|x18", re.IGNORECASE)

#: The same vocabulary as a *value*. `_FLAG_KEY_RE` deletes a field called `adult`;
#: this one deletes the word from a sentence, so a diagnostic that quotes a
#: upstream refusal cannot publish §13's vocabulary either. `restricted` is matched
#: only beside the rest of the phrase (a plain "Access restricted" from a hoster is
#: a transport fact, `18+`/`adult` is the flag), but `adult`, `18+`, `nsfw` and
#: `x18` are never legitimate public words in any position.
_FLAG_VALUE_RE = re.compile(
    r"\b(?:18\s*\+|18[\s_]?plus|adult(?:\s+[a-z]{2,12})?|nsfw|x18|restricted\s+"
    r"\(?\s*(?:18\s*\+|adult)[^)]*\)?|[(\[]\s*18\s*\+\s*[)\]])\b",
    re.IGNORECASE)

#: §16.9 is a deny-*list*, so a field added to a Layer-2 shape later is published
#: until somebody remembers to add its name to `redact.PROVENANCE`. `suggest`
#: proved the hole: `poster_url` is a stored image URL of the site we scraped it
#: from, no key on that list ends in `_url` that Layer 2 hands out, and the wire
#: forwarded it verbatim. The wire therefore also refuses any key whose *name*
#: announces an upstream image URL; routes that legitimately have artwork rewrite
#: it into our own handle first (`_public_art`), which is what every other shape
#: already carries.
_RAW_URL_KEY_RE = re.compile(
    r"^(?:poster|backdrop|banner|og|thumb|thumbnail|preview|image|artwork|cover)"
    r"_?urls?$", re.IGNORECASE)

#: §16.2 cache classes.
CACHE_BROWSE = "public, max-age=60"
CACHE_DETAIL = "public, max-age=300, stale-while-revalidate=3600"
CACHE_MANIFEST = "public, max-age=3600"
CACHE_NO_STORE = "no-store"

MAX_SYNC_LIMIT = 200
MAX_FEED_ITEMS = 2000
MAX_BODY_BYTES = 64 * 1024
MAX_OFFSET_SECONDS = 24 * 3600
REPORT_EVENTS = ("played", "stalled", "failed", "resolved")
PREFER_VALUES = ("quality", "speed", "data_saver")

#: §7.1 — the link axis published as data. These are the exact weights
#: `catalog_v2.project()` writes into `cat_links.rank_score`; the test suite
#: recomputes a projected row from this table, so editing one side without the
#: other fails a test instead of drifting silently.
LINK_RANK_WEIGHTS = {
    "playability": {"stream": 500, "both": 500, "download": 250,
                    "resolve_required": 120, "webview": 80, "none": 0},
    "tier1_bonus": 150,
    "non_ephemeral_bonus": 100,
    "accepts_ranges_bonus": 50,
    "state": {"active": 100, "unknown": 0, "unchecked": 0, "otherwise": -450},
    "range": [0, 900],
}
#: The measured half of axis 2, published as the arithmetic it actually is: the
#: test suite recomputes `link_health.score_link()` from this table, so a weight
#: changed on one side without the other fails a test instead of making the
#: manifest a document a client has to take on faith. `tiers.score()` is a separate
#: thing (it picks the winner *inside* a quality band from the public link view) and
#: is published under `band_collapse`, never confused with this.
LINK_MEASURED = {
    "scale": tiers.MEASURED_SCALE,
    "field": "candidates[].rank_score",
    "range": [0, 1000],
    "ceiling": tiers.MEASURED_CEILING,
    "producer": "link_health.score_link()",
    "applied_by": "catalog_v2._blend_link() / apply_evidence()",
    "requires": "a cat_link_evidence row naming a protocol (§6.2)",
    "weights": {
        "not_ok": 0,
        "streamable": 300,
        "downloadable": 150,
        "accepts_ranges": 100,
        "cors_open": 80,
        "speed": {"points": 100, "saturates_at_mbps": 20},
        "latency": {"points": 100, "full_at_ms": 150, "zero_at_ms": 3000},
        "tier_weights": {1: 1.0, 2: 0.7, 3: 0.4},
        "is_temporary": -150,
        "protocol_embed": -100,
    },
    "clamped": [0, 1000],
}
#: §7.1 asks the manifest to say *which scale a given link's `rank_score` is on*.
#: That is a per-link fact, not a global one, so it is published as the field a
#: client reads and the rule that fills it — Layer 1 decides it in `_blend_link()`,
#: and `tiers.scale_of()` is the same decision re-read from the wire shape.
LINK_SCALE_SELECTOR = {
    "field": "score_scale",
    "carried_by": ["candidates[]", "stream_candidates[]", "alternates[]",
                   "download_options[]", "tiers[].link", "/sync?scope=health items[]"],
    "values": {tiers.PRIOR_SCALE: list(tiers.SCALE_RANGES[tiers.PRIOR_SCALE]),
               tiers.MEASURED_SCALE: list(tiers.SCALE_RANGES[tiers.MEASURED_SCALE])},
    "rule": ("measured when the projector folded a probe into rank_score "
             "(cat_links carries a measured verdict), else projection_prior"),
    "decided_by": "tiers.scale_of()",
    "never_comparable": True,
}
#: The band-collapse score, which ranks the copies *inside* one quality band.
BAND_COLLAPSE = {
    "field": "tiers[].link score (presentation order only)",
    "formula": "tiers.score(link, band)",
    "inputs": ["kind", "state", "http_status", "resumable", "rank_score",
               "speed_mbps", "latency_ms", "ephemeral", "last_evidence_at",
               "size_bytes"],
    "note": ("a sort key, never a published number: it adds `rank_score`/4 rather "
             "than trusting either axis alone, so it is deliberately on neither scale"),
}

#: The print axis, read out of the module that computes it — never re-typed.
PRINT_FORMULA = {
    "field": "print.quality_score",
    "range": [0, 1000],
    "cam_ceiling": release_descriptor.CAM_FAMILY_CEILING,
    "cam_family": sorted(release_descriptor.CAM_FAMILY),
    "weights": {
        "resolution": dict(sorted(release_descriptor.RESOLUTION_WEIGHTS.items())),
        "source_tag": dict(sorted(release_descriptor.SOURCE_TAG_WEIGHTS.items())),
        "bonuses": {
            "hdr_at_1080p_plus": 60, "bit_depth_12": 30, "bit_depth_10": 20,
            "codec_h265_av1": 30, "official_print": 40, "subs_external": 20,
            "subs_hardcoded": 5, "dual_audio": 25, "layout_5_1": 15,
            "edition_alternate": 15, "watermarked": -60,
        },
    },
    "clamped": True,
}

#: §16.5 buckets, expressed against the buckets `redact.py` already defines. The
#: doc asks for a separate `/sync` budget of 120/min; no such bucket exists in the
#: shared config, and standing up a second limiter would fork the policy, so sync
#: rides `browse` (60/min) and `/manifest` publishes the number actually enforced.
ROUTE_BUCKETS = {
    "play": "play",
    "resolve": "play",
    "report": "reports",
    "offset": "reports",
    "browse": "browse",
    "search": "browse",
    "suggest": "browse",
    "works": "browse",
    "episodes": "browse",
    "releases": "browse",
    "manifest": "browse",
    "stats": "browse",
    "sync": "browse",
    "collections": "browse",
    "health": "browse",
    "feed.m3u": "browse",
}

#: How many path segments each route head may carry (§12). A head that ignores its
#: extra segments answers the *wrong* route's payload for a URL that does not exist:
#: `/api/v2/sync/catalog` returned a 200 catalog page, so a client that mistyped a
#: path cached an answer it could never reproduce, and a route added later at that
#: same address would silently change meaning. Only the documented shapes answer.
ROUTE_ARITY = {
    "GET": {"manifest": (1,), "browse": (1,), "search": (1,), "suggest": (1,),
            "sync": (1,), "stats": (1,), "health": (1,), "feed.m3u": (1,),
            "works": (2, 4), "episodes": (2,), "releases": (2,), "resolve": (2,),
            "collections": (1, 2)},
    "POST": {"play": (1,), "links": (3,), "episodes": (3,)},
}


# ── request session ──────────────────────────────────────────────────────────

@contextmanager
def session(db_path):
    """One connection per request, committed on success — the same contract
    `viewer.get_db` runs for v1, kept local so this module mounts without the
    viewer having to hand a connection to every route."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── the one adult rule, and the wire denial of the flag ──────────────────────

def adult_scope(alias: str = "w") -> str:
    """The single adult where-clause (§13), shared with every public emitter.

    Every query this module writes starts from here. A route that forgot it still
    could not *display* a row — the shapes are built by `catalog_api`, which
    scopes them — but the counts it reports would skew, and §13 forbids count
    skew as a signal.
    """
    return redact.adult_clause(alias)


def deny_flag_keys(obj):
    """Drop every key that names the flag, recursively."""
    if isinstance(obj, dict):
        return {key: deny_flag_keys(value) for key, value in obj.items()
                if not _FLAG_KEY_RE.search(str(key))}
    if isinstance(obj, (list, tuple)):
        return [deny_flag_keys(value) for value in obj]
    return obj


def deny_raw_urls(obj):
    """Drop every key that names an upstream image URL, recursively.

    Runs once, in `json_response`, so it covers every route built here and every
    route added later — the denial is structural, not a review of one shape."""
    if isinstance(obj, dict):
        return {key: deny_raw_urls(value) for key, value in obj.items()
                if not _RAW_URL_KEY_RE.search(str(key))}
    if isinstance(obj, (list, tuple)):
        return [deny_raw_urls(value) for value in obj]
    return obj


#: §16.9 rewrites the *value* of every field a user reads (`redact.TEXT_KEYS`), and
#: Layer 2 owns that list. Diagnostics are the second family of free text that
#: leaves this wire: `cat_link_evidence.error` holds whatever a probe or a client
#: said about a server — "hubcloud refused the range request" — and it reaches the
#: public play bundle as `probe_error`, under a key that is not a display key, so
#: nothing upstream of here ever cleaned it. A diagnosis that names a hoster is
#: still provenance, so the wire cleans the family.
_DIAGNOSTIC_KEY_RE = re.compile(
    r"^(?:[a-z0-9]+_)*(?:error|reason|detail|message|note|notes|warning|diagnostic"
    r"|summary)$", re.IGNORECASE)


def clean_diagnostic_text(obj):
    """Run every diagnostic string through `redact.scrub_text`, recursively."""
    if isinstance(obj, dict):
        return {key: (_flag_value_deny(redact.scrub_text(value))
                      if isinstance(value, str) and _DIAGNOSTIC_KEY_RE.match(str(key))
                      else clean_diagnostic_text(value))
                for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_diagnostic_text(value) for value in obj]
    return obj


# ── parameter parsing ────────────────────────────────────────────────────────

def _q(query: dict, name: str, default: str = "") -> str:
    values = query.get(name)
    if not values:
        return default
    return str(values[0]).strip()


def _q_list(query: dict, *names) -> list[str]:
    out: list[str] = []
    for name in names:
        for raw in query.get(name) or []:
            for piece in str(raw).split(","):
                piece = piece.strip()
                if piece:
                    out.append(piece)
    return out


def _int_or_none(value):
    text = str(value if value is not None else "").strip()
    if not text or not text.lstrip("-").isdigit():
        return None
    return int(text)


def _bool_or(value, default: bool = False) -> bool:
    text = str(value if value is not None else "").strip().lower()
    if text in ("", "any"):
        return default
    return text in ("1", "true", "yes", "on")


def _available(query: dict):
    text = _q(query, "available")
    if text in ("", "any"):
        return None
    if text in ("1", "true"):
        return True
    return text if text in ("stream", "download") else None


def _tri_state(query: dict, name: str):
    text = _q(query, name)
    if text in ("", "any"):
        return None
    return _bool_or(text)


# ── response primitives ──────────────────────────────────────────────────────

def request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16]


def etag_for(seed, rev) -> str:
    """Weak validator (§16.2). Byte-equivalence is not promised, so `W/"…"`, and
    the version vector is folded in so a health sweep cannot invalidate a catalog
    cache and a projection invalidates exactly the caches whose rows moved.

    `rev` is either one group (an int, the legacy single-catalog form) or the whole
    `version_vector()` dict; both render through `rev_token`, so a validator and a
    `/sync` body built from the same vector carry the same digits."""
    digest = hashlib.sha1(str(seed).encode("utf-8")).hexdigest()[:16]
    return f'W/"cat-{rev_token(rev)}-{digest}"'


def etag_matches(header: str, etag: str) -> bool:
    text = str(header or "").strip()
    if not text:
        return False
    if text == "*":
        return True
    wanted = etag.strip().lstrip("W/").strip('"')
    return any(candidate.strip().lstrip("W/").strip('"') == wanted
               for candidate in text.split(","))


def _cache_headers(*, cache: str, etag: str = "", rid: str = "",
                   last_modified=None) -> list[tuple[str, str]]:
    headers = [("Cache-Control", cache), ("Vary", "Accept-Encoding")]
    if etag:
        headers.append(("ETag", etag))
    if last_modified:
        headers.append(("Last-Modified", formatdate(float(last_modified), usegmt=True)))
    if rid:
        headers.append(("X-Request-Id", rid))
    return headers


def not_modified(handler, *, cache: str, etag: str, rid: str = "",
                 last_modified=None) -> None:
    """304 carries validators and nothing else — no body, no Content-Length."""
    try:
        handler.send_response(304)
        for key, value in _cache_headers(cache=cache, etag=etag, rid=rid,
                                         last_modified=last_modified):
            handler.send_header(key, value)
        # A headerless reply is still a reply: §16.5 puts the triple on the `304`s
        # too, and this path bypasses `send_bytes`, where the mount attaches it.
        for key, value in (getattr(handler, "rate_headers", []) or []):
            handler.send_header(key, value)
        handler.send_header("Connection", "close")
        handler.end_headers()
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        pass


def attach_rate_headers(handler, path: str, method: str = "GET") -> None:
    """Guarantee this reply carries the §16.5 triple, whoever mounted us.

    The HTTP host's gate spends one token per request and attaches its own copy;
    when it has, these exact numbers are reused rather than a second contradictory
    triple. `redact.limiter.peek` never spends, so a bare mount still publishes the
    budget the *one* shared bucket holds instead of halving every limit — and no
    route here keeps a counter of its own.
    """
    if getattr(handler, "rate_headers", None):
        return
    verdict = redact.limiter.peek(bucket_for(path, method), redact.client_ip(handler))
    handler.rate_headers = redact.limiter.headers(verdict)


def retry_after(handler, path: str, method: str = "GET") -> str:
    """Seconds until this route's bucket reopens, for a caller already over it."""
    _, opened, _limit, window = redact.limiter.state(
        bucket_for(path, method), redact.client_ip(handler))
    return str(max(1, int(round(window - (time.time() - opened)))))


def _flag_value_deny(text: str) -> str:
    """Strip §13's vocabulary out of a value, not just out of a key.

    `deny_flag_keys` removes a field named `adult`; it cannot remove the word from
    a sentence. A diagnosis is the one family of strings here that quotes somebody
    else's failure, and v1's resolver answers an 18+ source with
    `"Source restricted (18+ content)"` — served verbatim, that sentence would tell
    a caller the title exists *and* why we hide it, which is the exact inference
    §13 exists to forbid."""
    if not isinstance(text, str) or not text:
        return text
    return re.sub(r"\s{2,}", " ", _FLAG_VALUE_RE.sub("", text)).strip(" ()[]·,-")


def problem(handler, *, code: str, rid: str, instance: str, detail: str = "",
            extra: dict | None = None, headers: list[tuple[str, str]] | None = None,
            cache: str = CACHE_NO_STORE) -> None:
    """RFC 9457 problem body (`application/problem+json`), §16.4.

    `type` is a per-code URI under our own API root; `instance` is the route that
    answered; `code` is the stable machine code. `details` is scrubbed and
    flag-denied like every other payload, because a diagnostic field is still a
    public field.

    A code outside §16.4's closed list answers `not_found`, never `internal`: a
    typo, a retired code (`adult_restricted` is the one that matters) or a Layer-2
    word nobody mapped must not become a new public code, and it must not become a
    500 that says "this route knows something it will not tell you".
    """
    given = str(code or "")
    resolved = _CODE_ALIASES.get(given, given)
    if resolved not in PROBLEM_CODES or _FLAG_KEY_RE.search(resolved):
        resolved = "not_found"
    status, title = PROBLEM_CODES[resolved]
    body = {
        "type": f"/api/v2/problems/{resolved}",
        "title": title,
        "status": status,
        "instance": instance,
        "code": resolved,
        "request_id": rid,
    }
    if detail:
        body["detail"] = _flag_value_deny(redact.scrub_text(detail))
    if extra:
        body["details"] = clean_diagnostic_text(redact.scrub(deny_flag_keys(extra)))
    stamp = list(_cache_headers(cache=cache, rid=rid))
    stamp.extend(headers or [])
    if resolved == "rate_limited" and not any(
            name.lower() == "retry-after" for name, _ in stamp):
        # §16.5: a 429 without `Retry-After` makes a mobile client retry blind.
        stamp.append(("Retry-After", retry_after(handler, instance,
                                                 getattr(handler, "v2_method", "GET"))))
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_bytes(payload, content_type="application/problem+json; charset=utf-8",
                       status=status, extra_headers=stamp)


def json_response(handler, payload, *, rid: str, status: int = 200,
                  cache: str = CACHE_BROWSE, etag: str = "", last_modified=None,
                  operator: bool = False, headers: list[tuple[str, str]] | None = None
                  ) -> None:
    body = payload if operator else clean_diagnostic_text(
        deny_raw_urls(deny_flag_keys(payload)))
    extra = list(_cache_headers(cache=cache, etag=etag, rid=rid,
                                last_modified=last_modified))
    extra.extend(headers or [])
    handler.send_json(body, status=status, extra_headers=extra)


def _from_layer2(result: dict) -> tuple[bool, str, str]:
    """Translate a Layer-2 envelope into a §16.4 code: ``(ok, code, message)``."""
    if result.get("ok"):
        return True, "", ""
    error = result.get("error") or {}
    raw = str(error.get("code") or "not_found")
    code = _CODE_ALIASES.get(raw, raw)
    if code not in PROBLEM_CODES:
        code = "not_found"
    return False, code, str(error.get("message") or "")


def send_layer2(handler, result: dict, *, rid: str, path: str, cache: str,
                etag_seed: str, rev, last_modified=None, operator: bool = False,
                not_found_detail: str = "") -> None:
    """Put a Layer-2 envelope on the wire, validating it against the vector.

    `rev` is the whole `version_vector()` (§16.2), so the validator a client reuses
    moves whenever any group that this reply could depend on moved."""
    ok, code, message = _from_layer2(result)
    if not ok:
        detail = (not_found_detail or message) if code == "not_found" else message
        problem(handler, code=code, rid=rid, instance=path, detail=detail)
        return
    if cache != CACHE_NO_STORE:
        etag = etag_for(f"{etag_seed}|{json.dumps(result, sort_keys=True, default=str)}",
                        rev)
        if etag_matches(str(handler.headers.get("If-None-Match") or ""), etag):
            not_modified(handler, cache=cache, etag=etag, rid=rid,
                         last_modified=last_modified)
            return
    else:
        etag = ""
    json_response(handler, result, rid=rid, cache=cache, etag=etag,
                  last_modified=last_modified, operator=operator)


# ── catalog revision / readiness ─────────────────────────────────────────────

#: §16.2's four version groups, in the order they are folded into a validator.
VERSION_GROUPS = ("catalog_rev", "health_rev", "offsets_rev", "entitlements_rev")

#: The meta key that carried the health group before Layer 1 grew `health_rev`
#: (§16.2: "Backing today: `cat_projection_meta.health`"). Read as a fallback so a
#: projection built either way moves the validator instead of resetting it to 0.
_LEGACY_HEALTH_KEY = "health"


def _as_rev(value) -> int:
    """A revision as a non-negative int; anything unreadable is `0` (§16.2)."""
    text = str(value if value is not None else "").strip()
    if not text:
        return 0
    try:
        number = float(text)
    except (TypeError, ValueError):
        return 0
    return int(number) if number > 0 else 0


def catalog_rev(conn) -> int:
    try:
        row = conn.execute("SELECT COALESCE(MAX(source_rev), 0) AS v FROM cat_works").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["v"]) if row else 0


def _meta_revisions(conn) -> dict:
    """Read the version groups straight out of `cat_projection_meta`.

    This is the degradation path: Layer 1's own `projection_versions()` helper may
    not exist yet, or may not carry a key, and a missing key is `0` rather than a
    crash — the wire must still answer with a validator it can revalidate.
    """
    stored: dict[str, str] = {}
    try:
        for row in conn.execute("SELECT key, value FROM cat_projection_meta"):
            stored[str(row[0])] = row[1]
    except sqlite3.Error:
        stored = {}
    out = {key: _as_rev(stored.get(key)) for key in VERSION_GROUPS}
    if not out["health_rev"]:
        out["health_rev"] = _as_rev(stored.get(_LEGACY_HEALTH_KEY))
    return out


def version_vector(conn) -> dict:
    """The four §16.2 groups as one dict — the only source a validator is built from.

    `/sync` publishes this same dict and every cached GET folds it into its `ETag`,
    so the two can never disagree about what moved. `catalog_rev` is the greater of
    the declared group and the newest `source_rev` actually stamped on a work: a
    row that moved further than the declaration did would otherwise keep serving a
    stale `304` under a validator nobody re-wrote.
    """
    getter = getattr(catalog_v2, "projection_versions", None)
    out = _meta_revisions(conn)
    if callable(getter):
        try:
            given = getter(conn) or {}
        except Exception:
            # A half-built Layer-1 helper must not take the edge down; the meta
            # read above already answers with what the projection actually holds.
            given = {}
        if isinstance(given, dict):
            for key in VERSION_GROUPS:
                if key in given:
                    out[key] = _as_rev(given.get(key))
    out["catalog_rev"] = max(out["catalog_rev"], catalog_rev(conn))
    return {key: int(out[key]) for key in VERSION_GROUPS}


def rev_token(rev) -> str:
    """A revision, or a whole version vector, as the digits inside an `ETag`."""
    if isinstance(rev, dict):
        return "-".join(str(_as_rev(rev.get(key))) for key in VERSION_GROUPS)
    return str(_as_rev(rev))


def projected_at(conn):
    try:
        row = conn.execute("SELECT value FROM cat_projection_meta WHERE key = 'projected_at'"
                           ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return None


def has_catalog(conn) -> bool:
    """True once Layer 1 exists. A socket answering v2 with no projection is a
    503 with `Retry-After`, not a 200 full of zeroes."""
    try:
        conn.execute("SELECT 1 FROM cat_works LIMIT 1").fetchone()
    except sqlite3.Error:
        return False
    return True


# ── GET /manifest (§7.1, §12) ────────────────────────────────────────────────

def public_catalog_counts(conn, state_counts: dict) -> dict:
    """The manifest's catalog census, inside the same adult scope as `/stats`.

    `catalog_api.catalog_state` scopes works, prints, links, episodes and seasons,
    but its `link_states` block is a bare `GROUP BY` over every `cat_links` row and
    `last_projection` is the projector's own tally of the *ledger*. Published as
    they are, the manifest says 11 links while `/stats` says 9 and the two numbers
    differ by exactly the hidden rows — §13 forbids count skew as a signal, and a
    census of the posts we hold is the one table this service never shows.
    """
    counts = {key: value for key, value in (state_counts or {}).items()
              if key not in ("link_states", "last_projection", "open_review_queue",
                             "offsets")}
    scope = adult_scope("w")
    counts["link_states"] = {
        row["state"]: row["n"] for row in conn.execute(
            f"""
            SELECT COALESCE(l.state, 'unknown') AS state, COUNT(*) AS n
            FROM cat_links l JOIN cat_works w ON w.id = l.work_id
            WHERE {scope} GROUP BY COALESCE(l.state, 'unknown')
            """)}
    try:
        counts["open_review_queue"] = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM cat_review_queue q
            JOIN cat_works w ON w.id = q.work_id
            WHERE q.resolved_at IS NULL AND {scope}
            """).fetchone()["n"]
        counts["offsets"] = conn.execute(
            f"""
            SELECT COUNT(DISTINCT o.work_key) AS n FROM cat_offsets o
            JOIN cat_works w ON w.work_key = o.work_key WHERE {scope}
            """).fetchone()["n"]
    except sqlite3.Error:
        # A projection older than these tables simply has nothing to report.
        counts["open_review_queue"] = 0
        counts["offsets"] = 0
    return counts


def manifest_payload(conn) -> dict:
    """The machine-readable contract, both scoring axes published as data.

    A client that caches the catalog can re-rank on either axis and reproduce the
    server's answer, because every weight is here — read from the modules that
    compute it, so the manifest cannot tell a story the code does not act out.
    """
    state = catalog_api.catalog_state(conn)
    versions = version_vector(conn)
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "base": BASE_PATH,
        "media_type": "application/json; charset=utf-8",
        "scoring": {
            "print": PRINT_FORMULA,
            "link": {
                "field": "candidates[].rank_score",
                "axes": {
                    "projection_prior": {"range": list(LINK_RANK_WEIGHTS["range"]),
                                         "weights": dict(LINK_RANK_WEIGHTS),
                                         "producer": "catalog_v2.project()"},
                    "measured": dict(LINK_MEASURED),
                },
                "which_one_is_served": dict(LINK_SCALE_SELECTOR),
                "band_collapse": dict(BAND_COLLAPSE),
            },
        },
        "enums": {
            "sort": list(catalog_api.SORT_KEYS),
            "order": ["asc", "desc"],
            "coverage_type": list(catalog_api.COVERAGE_TYPES),
            "kind": ["bridge", "cdn_direct", "cloud_page", "dead_end", "download_only",
                     "embed", "hls_manifest", "unknown"],
            "playability": ["both", "download", "none", "resolve_required", "stream",
                            "unknown", "webview"],
            "state": ["active", "dead", "expired", "unknown", "unchecked"],
            "tier": [1, 2],
            "prefer": list(PREFER_VALUES),
            "report_event": list(REPORT_EVENTS),
            "work_type": sorted(catalog_api._CONTENT_TYPE_ALIASES),
            "quality": sorted(catalog_api._QUALITY_ALIASES),
            "available": ["stream", "download"],
        },
        "limits": {
            "browse_limit": {"default": catalog_api.DEFAULT_LIMIT,
                             "max": catalog_api.MAX_LIMIT},
            "search_limit": {"default": catalog_api.DEFAULT_LIMIT,
                             "max": catalog_api.MAX_SEARCH_LIMIT},
            "suggest_limit": {"default": 10, "max": 20, "min_query_chars": 2},
            "sync_limit": {"default": 100, "max": MAX_SYNC_LIMIT},
            "body_bytes": MAX_BODY_BYTES,
        },
        "rate_limit": {
            "headers": ["RateLimit-Limit", "RateLimit-Remaining", "RateLimit-Reset"],
            "retry_after_on": 429,
            "buckets": {name: {"limit": int(limit), "window_seconds": int(window)}
                        for name, (limit, window) in sorted(redact.BUCKET_LIMITS.items())},
            "route_buckets": dict(ROUTE_BUCKETS),
        },
        "error_codes": {code: {"status": status, "title": title}
                        for code, (status, title) in sorted(PROBLEM_CODES.items())},
        "cache_classes": {"browse": CACHE_BROWSE, "detail": CACHE_DETAIL,
                          "manifest": CACHE_MANIFEST, "no_store": CACHE_NO_STORE},
        "conditional_requests": {"etag": "weak", "header": "If-None-Match", "on_match": 304,
                                 "version_groups": list(VERSION_GROUPS),
                                 "folded_into_etag": True},
        "pagination": {"style": "keyset cursor", "opaque": True,
                       "carries": ["next_cursor", "has_more", "total_estimate", "limit"]},
        "visibility_policy": {
            "rows_are_never_deleted": True,
            "unlisted_answer": "not_found",
            "unlisted_status": 404,
            "note": ("a stored row that is not published answers exactly like a row that"
                     " does not exist, and no response carries the field that decides it"),
        },
        "implemented": {"layer1": True, "layer2": True, "wire": True,
                        "schema_version": catalog_v2.SCHEMA_VERSION},
        "catalog": {"rev": versions["catalog_rev"],
                    "versions": dict(versions),
                    "projected_at": state.get("projected_at"),
                    "counts": redact.scrub(deny_flag_keys(
                        public_catalog_counts(conn, state.get("counts") or {})))},
    }


# ── GET /stats (§12; B15 — never v1's SQL) ───────────────────────────────────

def stats_payload(conn) -> dict:
    """Totals for the public catalog, every one computed inside `adult_scope()`.

    v1's `/api/v1/stats` counts `posts` and `download_sources` wholesale, unlisted
    rows included (HANDOFF B15). Nothing here reuses that SQL: every number is
    read from the projection with the work scoped, so a hidden title cannot
    contribute to a count either.

    §12 also asks for "totals by site". A per-site breakdown *is* the answer to
    "which site did this come from", which is the one thing this service never
    publishes (§16.9) — so the breakdown is by behaviour instead: state,
    playability, tier, band, language.
    """
    scope = adult_scope("w")
    versions = version_vector(conn)
    counts = {
        "works": conn.execute(
            f"SELECT COUNT(*) FROM cat_works w WHERE {scope}").fetchone()[0],
        "seasons": conn.execute(
            f"SELECT COUNT(*) FROM cat_seasons s JOIN cat_works w ON w.id = s.work_id"
            f" WHERE {scope}").fetchone()[0],
        "episodes": conn.execute(
            f"SELECT COUNT(*) FROM cat_episodes e JOIN cat_works w ON w.id = e.work_id"
            f" WHERE {scope}").fetchone()[0],
        "prints": conn.execute(
            f"SELECT COUNT(*) FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
            f" WHERE {scope}").fetchone()[0],
        "links": conn.execute(
            f"SELECT COUNT(*) FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
            f" WHERE {scope}").fetchone()[0],
    }
    by_type = {row["work_type"]: row["n"] for row in conn.execute(
        f"SELECT COALESCE(w.work_type, 'unknown') AS work_type, COUNT(*) AS n"
        f" FROM cat_works w WHERE {scope}"
        f" GROUP BY COALESCE(w.work_type, 'unknown')")}
    by_band = {row["resolution"]: row["n"] for row in conn.execute(
        f"SELECT COALESCE(r.resolution, 'unknown') AS resolution, COUNT(*) AS n"
        f" FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
        f" WHERE {scope} GROUP BY COALESCE(r.resolution, 'unknown')")}
    by_print_class = {row["bucket"]: row["n"] for row in conn.execute(
        f"SELECT CASE"
        f"         WHEN r.quality_score >= 700 THEN 'premium'"
        f"         WHEN r.quality_score >= 450 THEN 'high'"
        f"         WHEN r.quality_score >= 250 THEN 'standard'"
        f"         ELSE 'low' END AS bucket, COUNT(*) AS n"
        f" FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
        f" WHERE {scope} GROUP BY bucket")}
    link_health = {row["state"]: row["n"] for row in conn.execute(
        f"SELECT COALESCE(l.state, 'unknown') AS state, COUNT(*) AS n"
        f" FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
        f" WHERE {scope} GROUP BY COALESCE(l.state, 'unknown')")}
    by_playability = {row["playability"]: row["n"] for row in conn.execute(
        f"SELECT COALESCE(l.playability, 'unknown') AS playability, COUNT(*) AS n"
        f" FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
        f" WHERE {scope} GROUP BY COALESCE(l.playability, 'unknown')")}
    by_tier = {str(row["tier"]): row["n"] for row in conn.execute(
        f"SELECT COALESCE(l.tier, 2) AS tier, COUNT(*) AS n"
        f" FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
        f" WHERE {scope} GROUP BY COALESCE(l.tier, 2)")}
    measured = conn.execute(
        f"""
        SELECT COUNT(*) AS n,
               COALESCE(AVG(e.speed_mbps), 0) AS speed,
               COALESCE(AVG(e.latency_ms), 0) AS latency,
               COALESCE(SUM(CASE WHEN e.ok = 1 THEN 1 ELSE 0 END), 0) AS ok,
               COALESCE(SUM(CASE WHEN e.accepts_ranges = 1 THEN 1 ELSE 0 END), 0) AS ranges
        FROM cat_link_evidence e
        JOIN (SELECT link_id, MAX(probed_at) AS probed_at FROM cat_link_evidence
              GROUP BY link_id) latest
          ON latest.link_id = e.link_id AND latest.probed_at = e.probed_at
        JOIN cat_links l ON l.id = e.link_id
        JOIN cat_works w ON w.id = l.work_id
        WHERE {scope}
        """).fetchone()
    streamable = (int(by_playability.get("stream", 0) or 0)
                  + int(by_playability.get("both", 0) or 0))
    downloadable = (int(by_playability.get("download", 0) or 0)
                    + int(by_playability.get("both", 0) or 0))
    links_total = sum(link_health.values())
    return {
        "ok": True,
        "counts": counts,
        "by_work_type": by_type,
        "by_band": by_band,
        "by_print_class": by_print_class,
        "link_health": {
            "by_state": link_health,
            "by_playability": by_playability,
            "by_tier": by_tier,
            "streamable": streamable,
            "downloadable": downloadable,
            "ok_ratio": round(int(link_health.get("active", 0) or 0) / links_total, 4)
                        if links_total else 0.0,
            "probes": {
                "total": int(measured["n"] or 0),
                "ok": int(measured["ok"] or 0),
                "resumable": int(measured["ranges"] or 0),
                "avg_speed_mbps": round(float(measured["speed"] or 0), 2),
                "avg_latency_ms": round(float(measured["latency"] or 0), 2),
            },
        },
        "catalog": {"rev": versions["catalog_rev"],
                    "versions": versions,
                    "projected_at": projected_at(conn),
                    "schema_version": catalog_v2.SCHEMA_VERSION},
        "generated_at": time.time(),
    }


def health_payload(conn) -> dict:
    """§12 liveness/readiness. `no-store`: it is an ops endpoint, and a cached
    "ready" is precisely the failure mode it exists to catch."""
    ready = has_catalog(conn)
    versions = version_vector(conn)
    return {
        "ok": True,
        "status": "ready" if ready else "unavailable",
        "contract_version": CONTRACT_VERSION,
        "schema_version": catalog_v2.SCHEMA_VERSION,
        "catalog_rev": versions["catalog_rev"],
        "versions": versions,
        "projected_at": projected_at(conn),
        "server_time": time.time(),
    }


# ── GET /sync (§16.3) ────────────────────────────────────────────────────────

def cursor_encode(rev, row_id: int) -> str:
    """`(rev, id)` of the last row handed out → an opaque keyset cursor (§16.1).

    `rev` is normally the catalog revision (an integer) but is a row's own version
    timestamp for the scopes keyed on one, so an integral value keeps the integer
    form and anything else keeps every digit a float comparison needs."""
    value = float(rev)
    text = str(int(value)) if value.is_integer() else repr(value)
    raw = f"v1|{text}|{int(row_id)}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


_CURSOR_REV_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _cursor_value(text, *, allow_fraction: bool):
    """One cursor slot as a number, or ``None`` when it is not one.

    Strictly digits (optionally a single fractional part): a forged or truncated
    slot fails here rather than becoming a `float()` exception, and never reaches
    the query as something the caller chose.
    """
    text = str(text or "").strip()
    if not _CURSOR_REV_RE.match(text):
        return None
    if "." in text:
        return float(text) if allow_fraction else None
    return int(text)


def cursor_decode(token) -> tuple[int, int] | None:
    text = str(token or "").strip()
    if not text:
        return (0, 0)
    try:
        padded = text + "=" * (-len(text) % 4)
        parts = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").split("|")
    except Exception:
        return None
    if len(parts) != 3 or parts[0] != "v1":
        return None
    rev = _cursor_value(parts[1], allow_fraction=True)
    row_id = _cursor_value(parts[2], allow_fraction=False)
    if rev is None or row_id is None:
        return None
    return rev, row_id


def sync_payload(conn, *, scope: str, since, limit: int, secret: str,
                 operator: bool = False) -> dict:
    """Row-level upserts for one version group.

    §16.3 keys catalog rows by `work_key`. That column names the identity a
    scraped page carries, so it is on the provenance deny-list by design and
    `redact.scrub` would strip it from the response anyway; the same rows are
    therefore keyed by `work_ref` (an opaque handle for the same value) and by
    our own `id`. Tombstones are empty and say so: the projector does not record
    a withdrawal yet, and pretending otherwise would be a false promise.

    Two rules every scope here obeys, because each was broken once:

    * §13 applies to *all* of them. `AND` binds tighter than `OR`, so writing
      `WHERE rev > :rev OR (…){adult}` leaves the first arm unscoped — a hidden
      title then pours out of `/sync` while every other route 404s it. The
      keyset is parenthesised, and `entitlements` joins to the work it belongs to
      so the clause can reach it.
    * §16.1: a page continues on the exact pair the query orders by, taken from
      the *row*, not from the emitted item. Deriving it from the item gave the
      `health` and `entitlements` scopes a cursor that decoded back to where it
      started, so a client following `next_cursor` refetched the same first row
      forever and never saw the second one.
    """
    rev = catalog_rev(conn)
    versions = version_vector(conn)
    decoded = cursor_decode(since)
    if decoded is None:
        return {"__error__": "cursor_invalid"}
    cur_rev, cur_id = decoded
    scope = (scope or "catalog").lower()
    if scope not in ("catalog", "health", "entitlements"):
        return {"__error__": "invalid_params"}
    where = "" if operator else f" AND {adult_scope('w')}"
    items: list[dict] = []
    after = (cur_rev, cur_id)
    if scope == "catalog":
        rows = conn.execute(
            f"""
            SELECT w.* FROM cat_works w
            WHERE (COALESCE(w.source_rev, 0) > :rev
                   OR (COALESCE(w.source_rev, 0) = :rev AND w.id > :id)){where}
            ORDER BY COALESCE(w.source_rev, 0) ASC, w.id ASC LIMIT :lim
            """, {"rev": cur_rev, "id": cur_id, "lim": limit}).fetchall()
        for row in rows:
            item = catalog_api._browse_item(row)
            item = redact.scrub(deny_flag_keys(item))
            item["rev"] = int(row["source_rev"] or 0)
            item["work_ref"] = (redact.mint_text(str(row["work_key"]), secret)
                                if secret else str(row["id"]))
            items.append(item)
        if rows:
            after = (int(rows[-1]["source_rev"] or 0), int(rows[-1]["id"]))
    elif scope == "health":
        # §16.3 publishes `score_scale` per row, and §7.1's two scales are not
        # comparable, so this cannot be a constant: a link whose journal holds a
        # probe (a row that names a protocol — exactly what `_blend_link()` requires
        # to switch a score over) is on the measured scale, everything else is
        # still on the projection prior. An older projection with no evidence table
        # has nothing measured in it.
        probe = """CASE WHEN EXISTS (SELECT 1 FROM cat_link_evidence x
                                     WHERE x.link_id = l.id
                                       AND COALESCE(x.protocol, '') <> '')
                        THEN 1 ELSE 0 END AS probed"""
        try:
            rows = conn.execute(
                f"""
                SELECT l.id, l.state, l.rank_score, l.playability, l.last_evidence_at,
                       l.latency_ms, {probe}
                FROM cat_links l JOIN cat_works w ON w.id = l.work_id
                WHERE (COALESCE(l.last_evidence_at, 0) > :rev
                       OR (COALESCE(l.last_evidence_at, 0) = :rev AND l.id > :id)){where}
                ORDER BY COALESCE(l.last_evidence_at, 0) ASC, l.id ASC LIMIT :lim
                """, {"rev": float(cur_rev or 0), "id": cur_id, "lim": limit}).fetchall()
        except sqlite3.Error:
            rows = conn.execute(
                f"""
                SELECT l.id, l.state, l.rank_score, l.playability, l.last_evidence_at,
                       l.latency_ms, 0 AS probed
                FROM cat_links l JOIN cat_works w ON w.id = l.work_id
                WHERE (COALESCE(l.last_evidence_at, 0) > :rev
                       OR (COALESCE(l.last_evidence_at, 0) = :rev AND l.id > :id)){where}
                ORDER BY COALESCE(l.last_evidence_at, 0) ASC, l.id ASC LIMIT :lim
                """, {"rev": float(cur_rev or 0), "id": cur_id, "lim": limit}).fetchall()
        for row in rows:
            scale = tiers.scale_of({"measured": bool(row["probed"]) or row["latency_ms"] is not None})
            items.append({"link_ref": link_ref_for(int(row["id"]), secret),
                          "state": row["state"],
                          "rank_score": row["rank_score"],
                          "playability": row["playability"],
                          "score_scale": scale,
                          "score_range": list(tiers.SCALE_RANGES[scale]),
                          "last_evidence_at": row["last_evidence_at"]})
        if rows:
            after = (float(rows[-1]["last_evidence_at"] or 0.0), int(rows[-1]["id"]))
    else:
        rows = conn.execute(
            f"""
            SELECT e.* FROM cat_entitlements e
            JOIN cat_works w ON w.id = e.work_id
            WHERE (e.updated_at > :rev OR (e.updated_at = :rev AND e.id > :id)){where}
            ORDER BY e.updated_at ASC, e.id ASC LIMIT :lim
            """, {"rev": float(cur_rev or 0), "id": cur_id, "lim": limit}).fetchall()
        for row in rows:
            items.append({"id": row["id"], "work_id": row["work_id"],
                          "release_id": row["release_id"], "model": row["model"],
                          "region": row["region"], "updated_at": row["updated_at"]})
        if rows:
            after = (float(rows[-1]["updated_at"] or 0.0), int(rows[-1]["id"]))
    next_cursor = None
    if len(items) == limit and items:
        next_cursor = cursor_encode(after[0], after[1])
    return {
        "ok": True,
        "scope": scope,
        "rev": rev,
        # §16.2/§16.3: the same four groups the `ETag`s of the cached routes are
        # folded from, read from the same call — a client that diffs `/sync`
        # versions and re-reads a validator can never be told two different stories.
        "versions": versions,
        "items": items,
        "count": len(items),
        "limit": limit,
        "tombstones": [],
        "tombstones_note": ("withdrawal is not recorded by the projector yet, so no row"
                            " can be announced as removed"),
        "next_cursor": next_cursor,
        "generated_at": time.time(),
    }



# ── GET /feed.m3u (§12) ──────────────────────────────────────────────────────

def feed_playlist(conn, *, work_id, base_url: str, secret: str) -> str:
    """An IPTV playlist of what a player may actually start right now.

    Adult-scoped, and only links that are non-ephemeral, streamable and active:
    an IPTV client has no failover logic, so a token that expired between the
    projection and the playlist load is a dead channel rather than a retry.
    Titles are our own display title with brands removed, and every entry is
    addressed to *our* host through our own resolver — a playlist naming an
    upstream server would undo everything this layer exists to do.
    """
    clauses = [adult_scope("w"), "l.ephemeral = 0",
               "l.playability IN ('stream', 'both')", "l.state = 'active'"]
    params: dict = {"lim": MAX_FEED_ITEMS}
    if work_id is not None:
        clauses.append("w.id = :wid")
        params["wid"] = int(work_id)
    rows = conn.execute(
        f"""
        SELECT l.id, w.id AS work_ref_id, w.title, w.runtime_minutes,
               (SELECT MAX(e.runtime_minutes) FROM cat_episodes e WHERE e.work_id = w.id)
                 AS episode_runtime
        FROM cat_links l
        JOIN cat_works w ON w.id = l.work_id
        WHERE {' AND '.join(clauses)}
        ORDER BY w.id DESC, l.id ASC
        LIMIT :lim
        """, params).fetchall()
    lines = ['#EXTM3U']
    for row in rows:
        title = redact.scrub_text(row["title"] or "Untitled")
        runtime = int(row["episode_runtime"] or row["runtime_minutes"] or 0)
        duration = runtime * 60 if runtime > 0 else -1
        handle = redact.mint_token(int(row["id"]), secret) if secret else str(row["id"])
        target = (f"{base_url}{BASE_PATH}/resolve/"
                  f"{urllib.parse.quote(handle, safe='')}")
        lines.append(f'#EXTINF:-1 tvg-name="{title}" group-title="{title}",{title}')
        lines.append(target)
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


# ── GET /resolve/{link_id} (§12, B13) ────────────────────────────────────────

def link_row(conn, link_id: int, *, operator: bool):
    """One `cat_links` row inside the adult scope.

    A row that is not published and a row that does not exist both answer `None`,
    so the caller cannot tell them apart — which is the whole of §13.
    """
    where = "l.id = :id" if operator else f"l.id = :id AND {adult_scope('w')}"
    return conn.execute(
        f"""
        SELECT l.*, w.is_18_plus FROM cat_links l
        JOIN cat_works w ON w.id = l.work_id WHERE {where}
        """, {"id": int(link_id)}).fetchone()


def ledger_source_id(conn, row):
    """Map a projected link back to its ledger row, so the JIT resolver — which
    owns the bridge recipes — is reused rather than copied (§12 "wraps
    `resolve_live_source` without its fall-through bug").

    `cat_links` deliberately holds no foreign key into the ledger: a projection
    must survive a rebuild of the rows it was read from, so the join is by the URL
    the link was built from.
    """
    try:
        found = conn.execute(
            """
            SELECT s.id FROM download_sources s
            WHERE s.source_url = :url OR s.final_url = :url
               OR s.final_url = :final OR s.source_url = :final
            ORDER BY CASE WHEN s.status = 'active' THEN 0 ELSE 1 END, s.id DESC
            LIMIT 1
            """, {"url": row["url"], "final": row["final_url"]}).fetchone()
    except sqlite3.Error:
        return None
    return int(found["id"]) if found else None


def static_url(row) -> str:
    """A URL a player may be sent to right now, or nothing.

    Only a non-ephemeral, live link whose own classification says it opens
    directly qualifies. `resolve_required` is deliberately excluded: Layer 1
    classified it as a hoster *page*, and 302-ing a player to a page is how a
    link used to look alive while playing nothing. Everything else goes through
    the resolver or fails honestly — which is the one thing a dead or expiring
    link can never again do: answer 200.
    """
    if int(row["ephemeral"] or 0):
        return ""
    if str(row["state"] or "") not in ("active", "unknown", "unchecked"):
        return ""
    if str(row["playability"] or "") not in ("stream", "both", "download"):
        return ""
    return str(row["final_url"] or row["url"] or "")


def resolve_target(conn, *, link_id: int, operator: bool):
    """``("not_found", None)`` / ``("failed", details)`` / ``("url", payload)``."""
    row = link_row(conn, link_id, operator=operator)
    if row is None:
        return "not_found", None
    direct = static_url(row)
    if direct:
        return "url", {"url": direct, "refreshed": False, "cached": True}
    source_id = ledger_source_id(conn, row)
    if source_id is None:
        return "failed", {"link_id": int(link_id), "reason": "no_ledger_source"}
    import fast_fetch
    try:
        result = fast_fetch.resolve_live_source(int(source_id), v2=True)
    except Exception:
        return "failed", {"link_id": int(link_id), "reason": "resolver_error"}
    if result.get("success") and result.get("url"):
        return "url", {"url": result["url"],
                       "refreshed": bool(result.get("refreshed")),
                       "cached": bool(result.get("cached")),
                       "mime_type": result.get("mime_type"),
                       "file_size_bytes": result.get("file_size_bytes"),
                       "resumable": bool(result.get("is_resumable")),
                       "expires_in": 6 * 3600 if result.get("is_temporary") else None}
    # B13: the resolver no longer answers `success: true` with a stale URL, so an
    # exhausted ladder reaches here as a failure instead of a fake playable.
    if str(result.get("code") or "") == "not_found":
        return "not_found", None
    return "failed", {"link_id": int(link_id),
                      "reason": str(result.get("reason") or "re_resolve_failed")}


# ── POST /links/{id}/report (§12; feeds axis 2) ──────────────────────────────

def ensure_side_tables(conn) -> None:
    """Client telemetry is ingest, not projection, so it gets its own tables and
    never a `cat_*` one: `catalog_v2.project(reset=True)` rebuilds those from
    scratch and would erase the evidence reports exist to accumulate."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS client_link_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER NOT NULL,
            work_id INTEGER,
            event TEXT NOT NULL,
            latency_ms INTEGER,
            detail TEXT,
            client_ref TEXT,
            reported_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_client_reports_link"
        " ON client_link_reports(link_id, reported_at DESC)")


def record_link_report(conn, *, link_id: int, work_id, event: str, latency_ms,
                       detail: str, client_ref: str) -> int:
    # Both strings are typed by a client about somebody's server, and this row is
    # read back: `cat_link_evidence.error` (which the wire then prints as
    # `probe_error`) is the scrubbed copy, so storing the raw one here would keep a
    # provenance string in our catalog under a different name.
    detail_text = redact.scrub_text(str(detail or ""))[:200]
    cursor = conn.execute(
        "INSERT INTO client_link_reports (link_id, work_id, event, latency_ms, detail,"
        " client_ref, reported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (int(link_id), work_id, event, latency_ms, detail_text,
         redact.scrub_text(str(client_ref or ""))[:64], time.time()))
    if catalog_api._has_table(conn, "cat_link_evidence"):
        # The measured axis is the point of the report: one confirmation per event,
        # `ok` for a source that played, not for one that stalled or failed.
        conn.execute(
            "INSERT INTO cat_link_evidence (link_id, probed_at, ok, latency_ms, error)"
            " VALUES (?, ?, ?, ?, ?)",
            (int(link_id), time.time(), 1 if event in ("played", "resolved") else 0,
             latency_ms, detail_text or None))
    return int(cursor.lastrowid or 0)


# ── routing ──────────────────────────────────────────────────────────────────

def is_v2(path: str) -> bool:
    return path == BASE_PATH or path.startswith(BASE_PATH + "/")


def _tail(path: str) -> list[str]:
    return [urllib.parse.unquote(piece) for piece in path.split("/") if piece][2:]


def shape_allowed(method: str, segments: list[str]) -> bool:
    """True when this path is one of §12's documented shapes for its head.

    An unknown head is allowed through: it reaches the `not_found` fall-through at
    the end of the dispatcher and answers the same sentence it always did.
    """
    head = segments[0] if segments else ""
    wanted = ROUTE_ARITY.get(method or "GET", {}).get(head)
    return wanted is None or len(segments) in wanted


def bucket_for(path: str, method: str = "GET") -> str:
    """Which shared `redact.limiter` bucket this request pays into."""
    segments = _tail(path)
    head = segments[0] if segments else ""
    if method == "POST":
        if head == "play":
            return ROUTE_BUCKETS["play"]
        if head == "links" and len(segments) == 3 and segments[2] == "report":
            return ROUTE_BUCKETS["report"]
        if head == "episodes" and len(segments) == 3 and segments[2] == "offset":
            return ROUTE_BUCKETS["offset"]
        return ROUTE_BUCKETS["browse"]
    if head == "resolve":
        return ROUTE_BUCKETS["resolve"]
    return ROUTE_BUCKETS.get(head, "browse")


def link_ref_parse(handle, secret: str, *, operator: bool) -> int | None:
    """Our own opaque handle → a `cat_links` row id, or ``None``.

    `redact.parse_token` owns this rule and already carries the one exception:
    the plain integer form is accepted when ``signed_only`` is False (the loopback
    port, where the operator's own curl and healing scripts address rows directly)
    and refused when it is True, because a row id is *enumerable* — walking
    1..N would harvest every file URL we hold without our API ever naming a host.
    A fallback here that retried `handle.isdigit()` cancelled that rule on the
    public port, so there is deliberately no fallback.
    """
    return redact.parse_token(handle, secret, signed_only=not operator)


def link_ref_for(link_id: int, secret: str) -> str:
    """The public address of one link: a handle we minted, never the row id (§16.9)."""
    return redact.mint_token(int(link_id), secret) if secret else str(int(link_id))


def _public_art(result: dict, *, base_url: str, secret: str) -> dict:
    """Replace a Layer-2 raw image URL with our own art handle, in place.

    `suggest` is the one read-model shape that still carries a stored image URL
    under its own name; every other shape publishes the structured `poster`
    object `catalog_api._images` builds. Rewriting it here keeps type-ahead and
    cards byte-identical for the same artwork — and if we did not, `deny_raw_urls`
    would silently delete the field instead, which is a worse client outcome than
    a handle that resolves.
    """
    for item in result.get("items") or []:
        if not isinstance(item, dict) or "poster_url" not in item:
            continue
        raw = item.pop("poster_url")
        item["poster"] = catalog_api._images(
            {"id": item.get("id"), "poster_url": raw},
            base_url=base_url, secret=secret)["poster"]
    return result


def listing_kwargs(query: dict, *, operator: bool, for_search: bool) -> dict:
    kwargs = {
        "content_type": _q(query, "type") or _q(query, "work_type") or None,
        "genres": _q_list(query, "genre", "genres"),
        "languages": _q_list(query, "language", "languages"),
        "qualities": _q_list(query, "quality", "qualities"),
        "sort": _q(query, "sort") or ("relevance" if for_search else "trending"),
        "order": _q(query, "order") or "desc",
        "cursor": _q(query, "cursor") or None,
        "limit": _int_or_none(_q(query, "limit")) or catalog_api.DEFAULT_LIMIT,
        "include_adult": bool(operator),
        "q": _q(query, "q") or None,
    }
    if not for_search:
        kwargs.update({
            "available": _available(query),
            "year_from": _int_or_none(_q(query, "year_from")),
            "year_to": _int_or_none(_q(query, "year_to")),
            "min_quality": _int_or_none(_q(query, "min_quality")),
            "animated": _tri_state(query, "animated"),
            "country": _q_list(query, "country") or None,
            "industry": _q_list(query, "industry") or None,
        })
    return kwargs


def route_get(handler, path: str, query: dict, *, db_path, operator: bool,
              base_url: str, secret: str) -> bool:
    """Serve one v2 GET. Returns True when this module answered."""
    if not is_v2(path):
        return False
    segments = _tail(path)
    rid = request_id()
    handler.v2_method = "GET"
    attach_rate_headers(handler, path, "GET")
    if not shape_allowed("GET", segments):
        problem(handler, code="not_found", rid=rid, instance=path,
                detail="No such v2 route.")
        return True
    catalog_api.configure_public(base_url, secret)
    with session(db_path) as conn:
        if not has_catalog(conn):
            problem(handler, code="unavailable", rid=rid, instance=path,
                    detail="The catalog projection has not been built yet.",
                    headers=[("Retry-After", "60")])
            return True
        versions = version_vector(conn)
        stamp = projected_at(conn)
        head = segments[0] if segments else ""

        if head == "manifest":
            payload = manifest_payload(conn)
            etag = etag_for(json.dumps(payload, sort_keys=True, default=str), versions)
            if etag_matches(str(handler.headers.get("If-None-Match") or ""), etag):
                not_modified(handler, cache=CACHE_MANIFEST, etag=etag, rid=rid,
                             last_modified=stamp)
                return True
            json_response(handler, payload, rid=rid, cache=CACHE_MANIFEST, etag=etag,
                          last_modified=stamp, operator=operator)
            return True

        if head in ("browse", "search"):
            for_search = head == "search"
            if for_search and not _q(query, "q"):
                problem(handler, code="invalid_params", rid=rid, instance=path,
                        detail="`q` is required on /search.")
                return True
            kwargs = listing_kwargs(query, operator=operator, for_search=for_search)
            if for_search:
                kwargs["fields"] = _q_list(query, "fields") or None
                result = catalog_api.search(conn, **kwargs)
            else:
                result = catalog_api.browse(conn, **kwargs)
            send_layer2(handler, result, rid=rid, path=path, cache=CACHE_BROWSE,
                        etag_seed=head, rev=versions, last_modified=stamp,
                        operator=operator)
            return True

        if head == "suggest":
            text = _q(query, "q")
            if not text:
                problem(handler, code="invalid_params", rid=rid, instance=path,
                        detail="`q` is required on /suggest.")
                return True
            result = catalog_api.suggest(conn, q=text,
                                         limit=_int_or_none(_q(query, "limit")) or 10,
                                         include_adult=bool(operator))
            _public_art(result, base_url=base_url, secret=secret)
            send_layer2(handler, result, rid=rid, path=path, cache=CACHE_BROWSE,
                        etag_seed=f"suggest|{text}", rev=versions, last_modified=stamp,
                        operator=operator)
            return True

        if head == "works" and len(segments) >= 2 and segments[1]:
            ident = segments[1]
            if len(segments) == 4 and segments[2] == "seasons":
                number = _int_or_none(segments[3])
                if number is None:
                    problem(handler, code="invalid_params", rid=rid, instance=path,
                            detail="Season number must be an integer.")
                    return True
                result = catalog_api.season_detail(conn, work_id=ident,
                                                   season_number=number,
                                                   include_adult=bool(operator))
                seed, detail = f"season|{ident}|{number}", "No such season in the catalog."
            else:
                if len(segments) not in (2,):
                    problem(handler, code="not_found", rid=rid, instance=path,
                            detail="No such v2 route.")
                    return True
                result = catalog_api.work_detail(
                    conn, work_id=ident, include_adult=bool(operator),
                    fields=_q_list(query, "fields") or None,
                    include_provenance=bool(operator))
                seed, detail = f"work|{ident}|{_q(query, 'fields')}", \
                    "No such work in the catalog."
            send_layer2(handler, result, rid=rid, path=path, cache=CACHE_DETAIL,
                        etag_seed=seed, rev=versions, last_modified=stamp,
                        operator=operator, not_found_detail=detail)
            return True

        if head == "episodes" and len(segments) == 2:
            result = catalog_api.episode_detail(conn, episode_id=segments[1],
                                                include_adult=bool(operator))
            send_layer2(handler, result, rid=rid, path=path, cache=CACHE_DETAIL,
                        etag_seed=f"episode|{segments[1]}", rev=versions,
                        last_modified=stamp, operator=operator,
                        not_found_detail="No such episode in the catalog.")
            return True

        if head == "releases" and len(segments) == 2:
            result = catalog_api.release_detail(conn, release_id=segments[1],
                                                include_adult=bool(operator))
            send_layer2(handler, result, rid=rid, path=path, cache=CACHE_DETAIL,
                        etag_seed=f"release|{segments[1]}", rev=versions,
                        last_modified=stamp, operator=operator,
                        not_found_detail="No such print in the catalog.")
            return True

        if head == "resolve" and len(segments) == 2:
            handle = segments[1]
            link_id = link_ref_parse(handle, secret, operator=bool(operator))
            if link_id is None:
                problem(handler, code="invalid_params", rid=rid, instance=path,
                        detail="The link reference is not one we issued.")
                return True
            kind, payload = resolve_target(conn, link_id=int(link_id),
                                           operator=bool(operator))
            if kind == "not_found":
                problem(handler, code="not_found", rid=rid, instance=path,
                        detail="No such link in the catalog.")
                return True
            if kind == "failed":
                problem(handler, code="no_playable_source", rid=rid, instance=path,
                        detail="This source could not be re-resolved right now.",
                        extra=payload)
                return True
            if _q(query, "redirect", "1") not in ("0", "false", "no"):
                # The 302 model: the player follows it and gets bytes, the VM
                # moves none of them, and the URL never appears in a JSON body.
                handler.send_response(302)
                handler.send_header("Location", payload["url"])
                handler.send_header("Cache-Control", CACHE_NO_STORE)
                for name, value in redact.cors_headers_for(
                        str(handler.headers.get("Origin") or "")):
                    handler.send_header(name, value)
                handler.send_header("X-Request-Id", rid)
                # §16.5 on the redirect too: this path writes its own header block,
                # so the budget the gate already spent has to be repeated here.
                for name, value in (getattr(handler, "rate_headers", []) or []):
                    handler.send_header(name, value)
                handler.send_header("Connection", "close")
                handler.end_headers()
                return True
            issued = link_ref_for(int(link_id), secret)
            json_response(handler, redact.scrub(deny_flag_keys({
                "ok": True,
                "link_ref": issued,
                "stream_id": issued,
                "kind": "url",
                "mime_type": payload.get("mime_type"),
                "file_size_bytes": payload.get("file_size_bytes"),
                "resumable": bool(payload.get("resumable")),
                "expires_in": payload.get("expires_in"),
                "refreshed": bool(payload.get("refreshed")),
            })), rid=rid, cache=CACHE_NO_STORE, operator=operator)
            return True

        if head == "sync":
            scope = _q(query, "scope") or "catalog"
            limit = _int_or_none(_q(query, "limit")) or 100
            result = sync_payload(conn, scope=scope, since=_q(query, "since"),
                                  limit=max(1, min(MAX_SYNC_LIMIT, limit)),
                                  secret=secret, operator=bool(operator))
            if result.get("__error__"):
                code = result.pop("__error__")
                problem(handler, code=code, rid=rid, instance=path,
                        detail="The sync cursor is not one we issued."
                               if code == "cursor_invalid"
                               else "`scope` must be catalog, health or entitlements.")
                return True
            send_layer2(handler, result, rid=rid, path=path, cache=CACHE_NO_STORE,
                        etag_seed=f"sync|{scope}|{_q(query, 'since')}", rev=versions,
                        last_modified=stamp, operator=operator)
            return True

        if head == "collections":
            # No backing table exists (§12 marks it 📝), and an id we cannot look
            # up answers exactly like any other id we cannot look up.
            problem(handler, code="not_found", rid=rid, instance=path,
                    detail="No such collection in the catalog.")
            return True

        if head == "feed.m3u":
            body = feed_playlist(conn, work_id=_int_or_none(_q(query, "work_id")),
                                 base_url=base_url, secret=secret)
            etag = etag_for(body, versions)
            if etag_matches(str(handler.headers.get("If-None-Match") or ""), etag):
                not_modified(handler, cache=CACHE_DETAIL, etag=etag, rid=rid,
                             last_modified=stamp)
                return True
            filename = f"radd-{_q(query, 'work_id') or 'all'}.m3u"
            handler.send_bytes(body.encode("utf-8"),
                               content_type="application/x-mpegURL; charset=utf-8",
                               extra_headers=(_cache_headers(cache=CACHE_DETAIL,
                                                             etag=etag, rid=rid,
                                                             last_modified=stamp)
                                              + [("Content-Disposition",
                                                  f'attachment; filename="{filename}"')]))
            return True

        if head == "stats":
            payload = stats_payload(conn)
            etag = etag_for(json.dumps(payload["counts"], sort_keys=True, default=str)
                            + json.dumps(payload["catalog"], sort_keys=True,
                                         default=str), versions)
            if etag_matches(str(handler.headers.get("If-None-Match") or ""), etag):
                not_modified(handler, cache=CACHE_BROWSE, etag=etag, rid=rid,
                             last_modified=stamp)
                return True
            json_response(handler, payload, rid=rid, cache=CACHE_BROWSE, etag=etag,
                          last_modified=stamp, operator=operator)
            return True

        if head == "health":
            json_response(handler, health_payload(conn), rid=rid, cache=CACHE_NO_STORE,
                          operator=operator)
            return True

    problem(handler, code="not_found", rid=rid, instance=path,
            detail="No such v2 route.")
    return True


# ── POST surface ─────────────────────────────────────────────────────────────

def read_body(handler) -> tuple[dict | None, str]:
    """A parsed JSON object, or the §16.4 code explaining why it is not one."""
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return None, "invalid_params"
    if length < 0 or length > MAX_BODY_BYTES:
        return None, "invalid_params"
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}, ""
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "invalid_params"
    if not isinstance(parsed, dict):
        return None, "invalid_params"
    return parsed, ""


def route_post(handler, path: str, query: dict, *, db_path, operator: bool,
               base_url: str, secret: str) -> bool:
    if not is_v2(path):
        return False
    segments = _tail(path)
    rid = request_id()
    handler.v2_method = "POST"
    attach_rate_headers(handler, path, "POST")
    catalog_api.configure_public(base_url, secret)
    body, body_error = read_body(handler)
    if body_error:
        problem(handler, code=body_error, rid=rid, instance=path,
                detail="The request body must be a JSON object.")
        return True
    if not shape_allowed("POST", segments):
        problem(handler, code="not_found", rid=rid, instance=path,
                detail="No such v2 route.")
        return True
    head = segments[0] if segments else ""

    with session(db_path) as conn:
        if not has_catalog(conn):
            problem(handler, code="unavailable", rid=rid, instance=path,
                    detail="The catalog projection has not been built yet.",
                    headers=[("Retry-After", "60")])
            return True

        if head == "play":
            route_play(handler, conn, body, rid=rid, path=path, operator=operator)
            return True

        if head == "links" and len(segments) == 3 and segments[2] == "report":
            ensure_side_tables(conn)
            link_id = link_ref_parse(segments[1], secret, operator=bool(operator))
            if link_id is None:
                problem(handler, code="invalid_params", rid=rid, instance=path,
                        detail="The link reference is not one we issued.")
                return True
            event = str(body.get("event") or "").strip().lower()
            if event not in REPORT_EVENTS:
                problem(handler, code="invalid_params", rid=rid, instance=path,
                        detail="`event` must be one of " + ", ".join(REPORT_EVENTS) + ".",
                        extra={"allowed": list(REPORT_EVENTS)})
                return True
            row = link_row(conn, int(link_id), operator=bool(operator))
            if row is None:
                problem(handler, code="not_found", rid=rid, instance=path,
                        detail="No such link in the catalog.")
                return True
            latency = _int_or_none(body.get("ms") if body.get("ms") is not None
                                   else body.get("latency_ms"))
            report_id = record_link_report(
                conn, link_id=int(link_id), work_id=row["work_id"], event=event,
                latency_ms=max(0, latency) if latency is not None else None,
                detail=str(body.get("error") or "")[:200],
                client_ref=str(body.get("device") or "")[:64])
            json_response(handler, {"ok": True, "recorded": True,
                                    "report_id": report_id, "event": event,
                                    "link_ref": link_ref_for(int(link_id), secret)},
                          rid=rid, cache=CACHE_NO_STORE, operator=operator)
            return True

        if head == "episodes" and len(segments) == 3 and segments[2] == "offset":
            route_offset(handler, conn, body, segments[1], rid=rid, path=path,
                         operator=operator)
            return True

    problem(handler, code="not_found", rid=rid, instance=path,
            detail="No such v2 route.")
    return True


def route_play(handler, conn, body: dict, *, rid: str, path: str, operator: bool) -> None:
    """POST /play — one PlayBundle for a work, a print or an episode (§8.1, §9, S11).

    `prefer` orders the ladder on either axis; a print whose only copies are
    downloads answers 200 with an empty play ladder and the download options
    present (S11), because "you may save this" is a real answer, not a conflict.
    """
    release_id = _int_or_none(body.get("release_id"))
    episode_id = _int_or_none(body.get("episode_id"))
    work_id = _int_or_none(body.get("work_id"))
    named = release_id is not None or episode_id is not None or work_id is not None
    if release_id is None and episode_id is not None:
        # Read inside the adult scope like every other query here. Unscoped, this
        # one lookup still ended up answering `not_found` (the print it points at is
        # filtered by `play_bundle`), but a hidden row reaching *any* branch of a
        # route is the shape that turns into a leak the next time somebody edits the
        # branch — §13 puts the scope on the read, not on the reply.
        where = "" if operator else f" AND {adult_scope('w')}"
        row = conn.execute(
            f"""
            SELECT e.best_release_id FROM cat_episodes e
            JOIN cat_works w ON w.id = e.work_id WHERE e.id = ?{where}
            """, (episode_id,)).fetchone()
        release_id = _int_or_none(row["best_release_id"]) if row else None
    if release_id is None and work_id is not None:
        where = "" if operator else f" AND {adult_scope('w')}"
        row = conn.execute(
            f"""
            SELECT r.id FROM cat_releases r JOIN cat_works w ON w.id = r.work_id
            WHERE r.work_id = :wid{where}
            ORDER BY r.quality_score DESC, r.id ASC LIMIT 1
            """, {"wid": work_id}).fetchone()
        release_id = _int_or_none(row["id"]) if row else None
    if release_id is None:
        # Two different questions, and §13 decides which answer is legal. A caller
        # that named no target at all has made a malformed request: 400. A caller
        # that *did* name one we cannot see has asked for a row that is either
        # absent or unlisted, and those are the same sentence to the public: the
        # same 404 an unknown `release_id` gets from `play_bundle` below, with the
        # same wording. Answering 400 here instead made /play an oracle for the
        # hidden titles — a 400 meant "that work exists and is 18+".
        if named:
            problem(handler, code="not_found", rid=rid, instance=path,
                    detail="No playable print exists for that target.")
        else:
            problem(handler, code="invalid_params", rid=rid, instance=path,
                    detail="One of `release_id`, `episode_id` or `work_id` is required.")
        return

    bundle = catalog_api.play_bundle(conn, release_id=int(release_id),
                                     episode_id=episode_id,
                                     include_adult=bool(operator))
    ok, code, _message = _from_layer2(bundle)
    if not ok:
        problem(handler, code=code or "not_found", rid=rid, instance=path,
                detail="No playable print exists for that target.")
        return
    prefer = str(body.get("prefer") or "quality").strip().lower()
    if prefer not in PREFER_VALUES:
        prefer = "quality"
    apply_prefer(bundle, prefer)
    bundle["prefer"] = prefer
    bundle["device"] = str(body.get("device") or "")[:64] or None
    if not bundle.get("playable"):
        if bundle.get("download_options"):
            bundle["reason"] = "download_only"
            json_response(handler, bundle, rid=rid, cache=CACHE_NO_STORE,
                          operator=operator)
            return
        problem(handler, code="no_playable_source", rid=rid, instance=path,
                detail=(f"{len(bundle.get('tried') or [])} ranks tried; every candidate"
                        " returned a transport or HTTP failure."),
                extra={"tried": bundle.get("tried") or [],
                       "candidate_count": bundle.get("candidate_count")})
        return
    json_response(handler, bundle, rid=rid, cache=CACHE_NO_STORE, operator=operator)


def apply_prefer(bundle: dict, prefer: str) -> None:
    """§9 — the two axes, chosen by the caller instead of assumed by us."""
    def sort_key(link: dict):
        size = int(link.get("size_bytes") or link.get("file_size_bytes") or 0)
        speed = float(link.get("speed_mbps") or 0)
        rank = int(link.get("rank_score") or 0)
        if prefer == "speed":
            return (0 if link.get("measured") else 1, -speed, -rank,
                    int(link.get("link_id") or 0))
        if prefer == "data_saver":
            return (0 if size else 1, size, -rank, int(link.get("link_id") or 0))
        return (1 if link.get("dead") else 0, -rank, -speed,
                int(link.get("link_id") or 0))

    for field in ("candidates", "stream_candidates", "alternates", "download_options"):
        items = bundle.get(field)
        if isinstance(items, list):
            bundle[field] = sorted(items, key=sort_key)
    ladder = bundle.get("tiers") or []
    if prefer == "speed":
        ladder = sorted(ladder, key=lambda tier: -float((tier.get("link") or {})
                                                        .get("speed_mbps") or 0))
    elif prefer == "data_saver":
        ladder = sorted(ladder, key=lambda tier: int((tier.get("link") or {})
                                                     .get("size_bytes") or 0))
    bundle["tiers"] = ladder
    playable = [link for link in (bundle.get("candidates") or []) if link.get("playable")]
    if playable:
        bundle["recommended_link_id"] = playable[0]["link_id"]
    bundle["ladder_exhausted"] = not playable


def route_offset(handler, conn, body: dict, raw_episode_id: str, *, rid: str,
                 path: str, operator: bool) -> None:
    """POST /episodes/{id}/offset — a learned pack offset into `cat_offsets`.

    The row is addressed by our own episode id and stored against the work's
    identity; the identity string itself is never echoed back.
    """
    episode_id = _int_or_none(raw_episode_id)
    offset = _int_or_none(body.get("offset_seconds"))
    if episode_id is None:
        problem(handler, code="invalid_params", rid=rid, instance=path,
                detail="Episode id must be an integer.")
        return
    if offset is None or offset < 0 or offset > MAX_OFFSET_SECONDS:
        problem(handler, code="invalid_params", rid=rid, instance=path,
                detail=f"`offset_seconds` must be an integer between 0 and {MAX_OFFSET_SECONDS}.")
        return
    where = "" if operator else f" AND {adult_scope('w')}"
    row = conn.execute(
        f"""
        SELECT e.id, e.number, e.work_id, s.number AS season_number, w.work_key
        FROM cat_episodes e
        JOIN cat_seasons s ON s.id = e.season_id
        JOIN cat_works w ON w.id = e.work_id
        WHERE e.id = :id{where}
        """, {"id": episode_id}).fetchone()
    if row is None:
        problem(handler, code="not_found", rid=rid, instance=path,
                detail="No such episode in the catalog.")
        return
    chapter = body.get("chapter_title")
    # `chapter_title` is echoed back to every public client by the next `/play` and
    # episode read, so a client that posts "hdhub4u S01E01" would publish a source
    # site through our own catalog. Scrub it at ingest, the same rule
    # `record_link_report` applies to a reported error string.
    chapter_text = redact.scrub_text(str(chapter))[:200].strip() if chapter else ""
    catalog_v2.record_offset(conn, work_key=str(row["work_key"]),
                             episode_number=int(row["number"]),
                             offset_seconds=int(offset),
                             season_number=int(row["season_number"] or 0),
                             release_label=str(body.get("release_label") or ""),
                             chapter_title=chapter_text or None)
    json_response(handler, {"ok": True, "recorded": True,
                            "episode_id": int(row["id"]),
                            "season": int(row["season_number"] or 0),
                            "episode": int(row["number"]),
                            "offset_seconds": int(offset)},
                  rid=rid, cache=CACHE_NO_STORE, operator=operator)
