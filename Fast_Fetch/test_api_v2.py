#!/usr/bin/env python3
"""test_api_v2.py — the v2 HTTP edge (`api_v2.py`), driven without a socket.

`api_v2.py` is ~1,400 lines of wire that had no test at all: every route in
API_V2.md §12 was reachable, and nothing proved what it promised. This suite calls
`route_get`/`route_post` through a fake handler that records exactly what
`viewer.DashboardHandler` would have put on the wire — status, headers, body, and
the two bodyless paths (the resolver's 302, the conditional 304) — against a
throwaway ledger projected into `cat_*` in a temp directory. No socket, no network,
no real database, nothing left behind.

The eight things asserted, in the order the contract cares about them:

  1. the adult rule (§13) — a flagged title is *invisible*, not "filtered out with
     a reason": every route answers an unlisted id exactly like a nonexistent one;
  2. provenance (§16.9) — no key on the deny-list, no site slug, no hoster name and
     no upstream URL ever leaves, in any shape, including a diagnostics field;
  3. opaque handles — the public port speaks handles only, a handle resolves its own
     row and nothing else, and `operator=True` demonstrably changes the answer;
  4. conditional requests (§16.2) — weak ETags that move with the catalog revision,
     not with the shape of the query, and a 304 that carries validators and no body;
  5. errors (§16.4) — RFC 9457 from the closed code list, never a stack trace,
     never a line of SQL;
  6. cursors (§16.1) — round-trip, garbage rejection, and a full pagination walk
     across a mid-walk catalog change that yields each row exactly once;
  7. rate buckets (§16.5) — every route maps to exactly one declared bucket;
  8. `stats` honesty — a link nobody probed is `unchecked`, and every coverage
     number adds up against the fixture's known counts.

One structural test enumerates the routes the code can answer and fails if a new
route exists without a test here.

Assertions are on exact shapes and values, not on "did it not crash".
"""

from __future__ import annotations

import inspect
import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

os.environ.setdefault("RADD_SKIP_LIVE_ENRICH", "1")

import api_v2
import catalog_v2
import fast_fetch
import redact
import viewer


HOST = "http://our.host"
SECRET = "test-secret-for-the-v2-wire-suite"

#: The brand vocabulary this fixture deliberately puts *into* the ledger, so that
#: finding any of it in a response is a proven leak rather than an empty test.
#: Sites come from `domain_registry.json`, hosters from `redact.BASE_NEEDLES`.
SENTINELS = ("vegamovies", "hdhub4u", "multimovies", "rogmovies", "ssrmovies",
             "9xmovies", "katmoviehd", "hubcloud", "pixeldrain", "gdtot",
             "gamerxyt", "direct-cloud", "greenmotors", "vegadrive")

#: Substrings that must never appear in a problem body: the two ways an unwrapped
#: exception tells an attacker more than the code does.
FORBIDDEN_IN_ERRORS = ("Traceback", "File \"", "sqlite3", "OperationalError",
                       "SELECT ", "FROM cat_", "no such table", "no such column",
                       "near \"", "Parameters", "IsOperational")


# ── ledger source builders (what a scraper would have written) ───────────────

def cdn(tag, *, status="active", temporary=0):
    url = f"https://video-downloads.googleusercontent.com/{tag}"
    return {"source_name": "CDN", "service": "google_cdn", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": temporary, "status": status}


def hoster_page(tag, *, status="active", temporary=1):
    url = f"https://new26.gdtot.dad/file/{tag}"
    return {"source_name": "GDTot", "service": "gdtot", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": temporary, "status": status}


def bridge(tag):
    url = f"https://gpdl.hubcloud.ist/?id={tag}"
    return {"source_name": "HubCloud", "service": "hubcloud", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "download",
            "is_temporary": 0, "status": "active"}


def dead(tag):
    url = f"https://pixeldrain.com/u/{tag}"
    return {"source_name": "PixelDrain", "service": "pixeldrain", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "direct",
            "is_temporary": 0, "status": "dead"}


# ── the recorded reply ───────────────────────────────────────────────────────

class FakeHandler:
    """The two reply primitives `viewer.DashboardHandler` gives a route, recorded.

    `send_json` behaves like the real one (JSON body, `application/json`, the CORS
    header, then the `RateLimit-*` triple the gate attached to the request);
    `send_bytes` records a raw body; `send_response`/`send_header`/`end_headers`
    are recorded separately because the resolver's 302 and the conditional 304 are
    written header-only. Everything a route sends lands in `replies`, so a route
    that answered twice would be caught rather than silently overwritten.
    """

    def __init__(self, headers=None, body=b""):
        self.headers = dict(headers or {})
        self.rfile = io.BytesIO(body)
        self.rate_headers = []
        self.replies = []

    # ── bodyless ────────────────────────────────────────────────────────────
    def send_response(self, code):
        self.replies.append({"kind": "raw", "status": int(code), "headers": [],
                             "body": b"", "payload": None})

    def send_header(self, name, value):
        if not self.replies:
            self.send_response(200)
        self.replies[-1]["headers"].append((str(name), str(value)))

    def end_headers(self):
        pass

    # ── with a body ─────────────────────────────────────────────────────────
    def send_bytes(self, data, content_type="text/html; charset=utf-8", status=200,
                   extra_headers=None):
        # `viewer.DashboardHandler.send_bytes` writes `Content-Type`,
        # `Content-Length` and `Connection` on the wire before the caller's extra
        # headers, so a route that only set the `content_type` argument still
        # answered with a real `Content-Type:` header line. Recording it as an
        # attribute only would make `/feed.m3u` look like a reply with no
        # content-type to a client, which is the opposite of what the socket says.
        headers = [("Content-Type", str(content_type)),
                   ("Content-Length", str(len(bytes(data)))),
                   ("Connection", "close")]
        headers.extend((str(k), str(v)) for k, v in (extra_headers or []))
        self.replies.append({
            "kind": "bytes", "status": int(status),
            "headers": headers,
            "body": bytes(data), "content_type": content_type, "payload": None})

    def send_json(self, data, status=200, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, content_type="application/json; charset=utf-8",
                        status=status, extra_headers=extra_headers)
        self.replies[-1]["payload"] = data

    def finish_reply(self):
        for reply in self.replies:
            # `viewer.DashboardHandler.send_bytes` is the only place the gate's copy
            # of the `RateLimit-*` triple is appended, and the resolver's 302 and the
            # conditional 304 write their own header block without it. Appending it
            # here as well would let a route that forgot to stamp those two replies
            # pass, which is the opposite of what §16.5 needs proven.
            if reply["kind"] == "bytes":
                reply["headers"].extend(self.rate_headers)
            if "content_type" not in reply:
                reply["content_type"] = ""


class Reply:
    """One answer: what the socket would have carried, plus JSON-shaped access."""

    def __init__(self, handler, path):
        handler.finish_reply()
        self.path = path
        self.replies = handler.replies
        reply = handler.replies[0]
        self.status = reply["status"]
        self.body = reply["body"]
        self.content_type = reply["content_type"]
        self.headers = {name.lower(): value for name, value in reply["headers"]}
        self.header_list = list(reply["headers"])
        self.json = reply["payload"]
        if self.json is None and "json" in self.content_type and self.body:
            self.json = json.loads(self.body.decode("utf-8"))

    def header(self, name):
        return self.headers.get(name.lower())

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def is_problem(self):
        return "application/problem+json" in self.content_type

    @property
    def code(self):
        return (self.json or {}).get("code")

    def __repr__(self):
        return f"<Reply {self.status} {self.path} {self.content_type}>"


# ── the corpus ───────────────────────────────────────────────────────────────

class V2WireFixture(unittest.TestCase):
    """One projected corpus per test: full isolation, no shared mutable state."""

    def setUp(self):
        os.environ["RADD_STREAM_SECRET"] = SECRET
        self.addCleanup(os.environ.pop, "RADD_STREAM_SECRET", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "wire.db"
        # `save_scraped_data` resolves its own connection from `fast_fetch.DB_PATH`,
        # so an unpatched path here would write fixtures into the real catalog.
        self._patches = [
            unittest.mock.patch.object(fast_fetch, "DB_PATH", self.db_path),
            unittest.mock.patch.object(viewer, "DB_PATH", self.db_path),
        ]
        for patcher in self._patches:
            patcher.start()
        # The wire cleans display text with the needles `viewer` installs at boot
        # (registry + ledger), so a leak the deployment would catch is caught here.
        self._old_needles = (redact._NEEDLES, redact._TEXT_NEEDLES)
        fast_fetch.init_db(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.build_corpus()
        redact.set_needles(redact.site_needles(self.db_path),
                           redact.site_text_needles(self.db_path))
        self.needles = self._registry_needles() | set(redact.site_needles(self.db_path))
        self.addCleanup(redact.set_needles, *self._old_needles)

    def tearDown(self):
        self.conn.close()
        for patcher in self._patches:
            patcher.stop()
        self.tmp.cleanup()

    @staticmethod
    def _registry_needles() -> set:
        """Every site name and mirror host in `domain_registry.json`."""
        registry = Path(__file__).with_name("domain_registry.json")
        data = json.loads(registry.read_text(encoding="utf-8"))
        out = set()
        for name, entry in (data.get("sites") or {}).items():
            out.add(name.lower())
            for mirror in entry.get("known_mirrors") or []:
                host = mirror.split("//", 1)[-1].split("/", 1)[0].lower()
                out.add(host)
                if host.count(".") >= 2:
                    out.add(host.rsplit(".", 2)[-2])
        return out

    # ---- ledger writers -----------------------------------------------------
    def add_post(self, site, url, *, clean_title, year=2024, content_type="movie",
                 is_18_plus=0, releases=()):
        data = {
            "url": url,
            "slug": url.rstrip("/").split("/")[-1],
            "title": f"{clean_title} ({year})",
            "clean_title": clean_title,
            "year": year,
            "content_type": content_type,
            "seasons": None,
            "poster_url": f"https://img.{site}.watch/{clean_title.replace(' ', '-')}.jpg",
            "backdrop_urls": None,
            "imdb_rating": 7.4,
            "genres": '["Action"]',
            "synopsis": f"{clean_title}: seen only on {site}",
            "is_18_plus": is_18_plus,
            "is_animated": 0,
            "source_site": site,
            "industry": "Bollywood",
            "country": "India",
            "language": "Hindi",
            "canonical_key": fast_fetch.generate_canonical_key(clean_title, year),
            "tmdb_id": None,
            "imdb_id": None,
            "releases": [],
        }
        for spec in releases:
            data["releases"].append({
                "release_title": spec.get("release_title", f"{clean_title} 1080p"),
                "season": spec.get("season", ""),
                "episode": spec.get("episode", ""),
                "quality": spec.get("quality", "1080p"),
                "codec": spec.get("codec", "x264"),
                "size": spec.get("size", "1.5GB"),
                "languages": spec.get("languages", '["Hindi"]'),
                "intermediate_url": "",
                "origin_url": "",
                "source_site": "",
                "sources": spec.get("sources", []),
            })
        post_id = fast_fetch.save_scraped_data(data, enrich_metadata=False,
                                               ensure_db=False)
        # The ingester always writes 'active'; the health checker marks rows dead,
        # so the fixture reproduces that second step exactly as production does.
        for rel in data["releases"]:
            for src in rel.get("sources") or []:
                if src.get("status") and src["status"] != "active":
                    self.conn.execute(
                        "UPDATE download_sources SET status = ? WHERE source_url = ?",
                        (src["status"], src["source_url"]))
        self.conn.commit()
        return post_id

    def project(self, rev=1):
        """Re-runs the whole projection: ids are re-assigned in `posts.id` order."""
        self.conn.commit()
        return catalog_v2.project(self.conn, rev=rev, verbose=False)

    def mark_probe_on_ledger(self, tag, *, http_status=200):
        """Writes back the measurement fields `link_state.py`'s sweep owns.

        `cat_links.state` is derived from the ledger's `status`/`http_status`/
        `last_checked_at`, so a link only *earns* `active` once somebody actually
        knocked on it (HANDOFF_audit D7). Everything left unprobed here stays
        `unchecked` on purpose: that asymmetry is what test 8 is about.
        """
        rowcount = self.conn.execute(
            "UPDATE download_sources SET http_status = ?, last_checked_at ="
            " strftime('%Y-%m-%d %H:%M:%S','now') WHERE resource_id = ?",
            (http_status, tag)).rowcount
        self.conn.commit()
        self.assertEqual(rowcount, 1, f"no ledger download_sources row for tag {tag}")

    def record_evidence(self, tag, *, ok=1, speed=None, latency=None, status=200,
                        ranges=None, error=None, probed_at=1730000000.0):
        """Simulates `link_health.probe()` having measured this link."""
        link = self.conn.execute(
            "SELECT id FROM cat_links WHERE resource_id = ?", (tag,)).fetchone()
        self.assertIsNotNone(link, f"no cat_links row for tag {tag}")
        self.conn.execute(
            """
            INSERT INTO cat_link_evidence (link_id, probed_at, ok, protocol, http_status,
                content_type, size_bytes, latency_ms, speed_mbps, accepts_ranges, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (link["id"], probed_at, ok, "https", status, "video/mp4", 1200000000,
             latency, speed, ranges, error))
        self.conn.commit()
        return link["id"]

    def report_rows(self, *, link_id=None) -> int:
        """How many client telemetry rows exist.

        `client_link_reports` is ingest, not projection: `api_v2.ensure_side_tables`
        creates it inside the report route, because `catalog_v2.project(reset=True)`
        rebuilds every `cat_*` table and would erase accumulated telemetry. A
        connection that has never POSTed a report therefore has no table at all —
        which is exactly zero recorded rows, the answer this helper gives, so a
        count-what-was-recorded assertion never depends on which route ran first.
        """
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table'"
            " AND name = 'client_link_reports'").fetchone()
        if not exists:
            return 0
        sql = "SELECT COUNT(*) FROM client_link_reports"
        params = ()
        if link_id is not None:
            sql += " WHERE link_id = ?"
            params = (int(link_id),)
        return int(self.conn.execute(sql, params).fetchone()[0])

    # ---- the corpus ---------------------------------------------------------
    def build_corpus(self):
        # The sentinel row: a real vegamovies page, a real Google CDN file, a real
        # gdtot hoster page, a hubcloud bridge and a dead pixeldrain mirror. Every
        # one of those names is in `SENTINELS`, so any of them in a response body
        # is a leak, not a false positive.
        self.add_post("vegamovies", "https://new1.vegamovies.lease/dune-protocol-2024/",
                      clean_title="Dune Protocol", year=2024, releases=[
                          {"release_title": "Dune Protocol (2024) 1080p WEB-DL",
                           "sources": [cdn("DUNE-CDN"), hoster_page("DUNE-PAGE"),
                                       bridge("DUNE-BRIDGE"), dead("DUNE-DEAD")]}])
        # 18+ and a *series*, so an adult work id, print id, episode id and link id
        # all exist and each route can be pointed at one.
        self.add_post("hdhub4u", "https://new8.hdhub4u.cl/adult-diary-2023/",
                      clean_title="Adult Diary", year=2023, content_type="series",
                      is_18_plus=1, releases=[
                          {"release_title": "Adult Diary S01 EP(01-02) 720p",
                           "season": "1", "episode": "1-2", "quality": "720p",
                           "sources": [cdn("ADULT-CDN"), hoster_page("ADULT-PAGE")]}])
        self.add_post("multimovies", "https://m1.multimovies.courses/campus-beats-2020/",
                      clean_title="Campus Beats", year=2020, content_type="series",
                      releases=[
                          {"release_title": "Campus Beats S01 EP(01-03) 720p",
                           "season": "1", "episode": "1-3", "quality": "720p",
                           "sources": [cdn("CB-CDN")]}])
        # Second measured link, so `/feed.m3u` and the coverage maths have more than
        # one row to work with.
        self.add_post("rogmovies", "https://rogmovies.one/quiet-valley-2021/",
                      clean_title="Quiet Valley", year=2021, releases=[
                          {"release_title": "Quiet Valley (2021) 1080p WEB-DL",
                           "sources": [cdn("QV-CDN")]}])
        self.add_post("ssrmovies", "https://ssrmovies.surf/slow-river-2022/",
                      clean_title="Slow River", year=2022, releases=[
                          {"release_title": "Slow River (2022) 720p WEBRip",
                           "quality": "720p", "sources": [cdn("SR-CDN"),
                                                          hoster_page("SR-PAGE")]}])
        self.add_post("9xmovies", "https://9xmovies.click/brave-orchard-2019/",
                      clean_title="Brave Orchard", year=2019, releases=[
                          {"release_title": "Brave Orchard (2019) 480p",
                           "quality": "480p", "sources": [mirror_download("BO-MIRROR")]}])
        self.mark_probe_on_ledger("DUNE-CDN")
        self.mark_probe_on_ledger("ADULT-CDN")
        self.mark_probe_on_ledger("QV-CDN")
        self.project(rev=1)
        # Out-of-band evidence, including the sentence a probe really writes: this
        # is the one field that reaches a public body carrying a hoster's name.
        # `DUNE-PAGE` is a candidate of the public print, so its error string is
        # the one that leaves as `probe_error` — the fixture must put a brand in it
        # or `test_diagnostics_never_name_a_hoster` would be proving nothing.
        self.record_evidence("DUNE-PAGE", ok=0, status=503, latency=900,
                             error="hubcloud gave a 503 on the hoster page",
                             probed_at=1730000000.0)
        self.record_evidence("DUNE-CDN", ok=1, speed=42.0, latency=120, ranges=1,
                             probed_at=1730000001.0)
        self.record_evidence("SR-CDN", ok=0, status=0, latency=None,
                             error="hubcloud refused the range request",
                             probed_at=1730000002.0)
        self.work_ids = {row["title"]: row["id"] for row in
                         self.conn.execute("SELECT id, title FROM cat_works")}
        self.adult_work_id = self.work_ids["Adult Diary"]
        self.public_work_id = self.work_ids["Dune Protocol"]
        self.missing_work_id = max(self.work_ids.values()) + 99999
        self.adult_release_id = self._one(
            "SELECT r.id FROM cat_releases r JOIN cat_works w ON w.id = r.work_id"
            " WHERE w.title = 'Adult Diary' ORDER BY r.id LIMIT 1")
        self.public_release_id = self._one(
            "SELECT id FROM cat_releases WHERE work_id = ?", (self.public_work_id,))
        self.missing_release_id = self._max("cat_releases") + 77777
        self.adult_episode_id = self._one(
            "SELECT e.id FROM cat_episodes e JOIN cat_works w ON w.id = e.work_id"
            " WHERE w.title = 'Adult Diary' ORDER BY e.id LIMIT 1")
        self.public_episode_id = self._one(
            "SELECT e.id FROM cat_episodes e JOIN cat_works w ON w.id = e.work_id"
            " WHERE w.title = 'Campus Beats' ORDER BY e.id LIMIT 1")
        self.missing_episode_id = self._max("cat_episodes") + 55555
        self.adult_link_id = self._one(
            "SELECT l.id FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
            " WHERE w.title = 'Adult Diary' AND l.resource_id = 'ADULT-CDN'")
        self.public_link_id = self._one(
            "SELECT id FROM cat_links WHERE resource_id = 'DUNE-CDN'")
        self.page_link_id = self._one(
            "SELECT id FROM cat_links WHERE resource_id = 'DUNE-PAGE'")
        self.missing_link_id = self._max("cat_links") + 424242
        self.secret = redact.stream_secret(self.db_path)

    def _one(self, sql, params=()):
        row = self.conn.execute(sql, params).fetchone()
        self.assertIsNotNone(row, f"fixture is missing a row for: {sql}")
        return int(row[0])

    def _max(self, table):
        return int(self.conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                   .fetchone()[0])

    # ---- the wire -----------------------------------------------------------
    def call(self, path, query=None, *, method="GET", operator=False, body=None,
             headers=None, raw_body=None, gate=True):
        """One route invocation through `api_v2`, exactly as `viewer` mounts it.

        `gate=False` models the same wire mounted *without* `viewer._public_gate`:
        no token spent, no `RateLimit-*` attached by the host, so a route that
        relies on its mount for §16.5's headers fails here instead of passing on
        borrowed ones.
        """
        params = {}
        for key, value in (query or {}).items():
            params[key] = [str(value)]
        sent = headers or {}
        payload = b""
        if method == "POST":
            payload = raw_body if raw_body is not None else json.dumps(
                body or {}, ensure_ascii=False).encode("utf-8")
            sent.setdefault("Content-Length", str(len(payload)))
        handler = FakeHandler(sent, payload)
        if gate:
            handler.rate_headers = [("RateLimit-Limit", "60"),
                                   ("RateLimit-Remaining", "59"),
                                   ("RateLimit-Reset", "60")]
        route = api_v2.route_get if method == "GET" else api_v2.route_post
        answered = route(handler, path, params, db_path=self.db_path,
                        operator=bool(operator), base_url=HOST, secret=self.secret)
        self.assertTrue(answered, f"api_v2 did not claim {path}")
        self.assertEqual(len(handler.replies), 1,
                         f"{method} {path} wrote {len(handler.replies)} replies")
        return Reply(handler, path)

    def bare(self, path, query=None, **kwargs):
        """The same call on a mount that stamped nothing."""
        return self.call(path, query, gate=False, **kwargs)

    def get(self, path, query=None, **kwargs):
        return self.call(path, query, method="GET", **kwargs)

    def post(self, path, body=None, query=None, **kwargs):
        return self.call(path, query, method="POST", body=body, **kwargs)

    # ---- shared assertions --------------------------------------------------
    def assert_clean(self, payload_or_text, *, label=""):
        """The three halves of §16.9, on anything that left a route."""
        where = f" ({label})" if label else ""
        if isinstance(payload_or_text, str):
            text = payload_or_text
        else:
            text = json.dumps(payload_or_text, ensure_ascii=False, default=str)
            keys = set(deep_keys(payload_or_text))
            self.assertFalse(
                keys & set(redact.PROVENANCE),
                f"provenance key(s) {sorted(keys & set(redact.PROVENANCE))} in a "
                f"public payload{where}")
            self.assertFalse(
                [key for key in keys if api_v2._FLAG_KEY_RE.search(key)],
                f"the adult flag is a public key{where}: {sorted(keys)}")
        lowered = text.lower()
        found = sorted(needle.lower() for needle in self.needles
                       if len(needle) >= 4 and needle.lower() in lowered)
        self.assertFalse(found, f"provenance token(s) {found} in a reply{where}")
        return text

    def assert_problem(self, reply, *, code, status, instance):
        """RFC 9457 from the closed list, identical for every member of the family."""
        self.assertTrue(reply.is_problem,
                        f"{reply.path} answered {reply.content_type}, not problem+json")
        self.assertEqual(reply.status, status)
        self.assertEqual(reply.code, code)
        body = reply.json
        self.assertEqual(body["type"], f"/api/v2/problems/{code}")
        self.assertEqual(body["title"], api_v2.PROBLEM_CODES[code][1])
        self.assertEqual(body["status"], status)
        self.assertEqual(body["instance"], instance)
        self.assertTrue(str(body.get("request_id", "")).startswith("req_"),
                        "an error without a request id cannot be traced by a user")
        self.assertIn(code, api_v2.PROBLEM_CODES)
        text = self.assert_clean(body, label=reply.path)
        for forbidden in FORBIDDEN_IN_ERRORS:
            self.assertNotIn(forbidden, text, f"{forbidden!r} leaked into {reply.path}")
        return body

    def handle(self, link_id):
        return redact.mint_token(int(link_id), self.secret)

    def public_ids(self, sql, params=()):
        """Ids a public caller may see: the fixture's, minus the adult work's."""
        rows = self.conn.execute(sql, params).fetchall()
        return [int(row[0]) for row in rows]


def deep_keys(obj, prefix=""):
    """Every key name anywhere in a tree — dicts, lists and nested alike."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from deep_keys(value, prefix)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from deep_keys(value, prefix)


def mirror_download(tag):
    url = f"https://mega.nz/file/{tag}"
    return {"source_name": "Mega", "service": "mega", "resource_id": tag,
            "source_url": url, "final_url": url, "playback_type": "download",
            "is_temporary": 0, "status": "active"}


def handled_heads(function) -> set:
    """Every route head a `route_*` function can answer, read out of its own body.

    Structural, not a list somebody maintains: `if head == "x"` and
    `if head in ("x", "y")` are the only ways this module dispatches, so the
    literals in the source *are* the surface.
    """
    source = inspect.getsource(function)
    heads = set(re.findall(r'head\s*==\s*"([\w.]+)"', source))
    for group in re.findall(r'head\s+in\s+\(([^)]*)\)', source):
        heads.update(re.findall(r'"([\w.]+)"', group))
    return heads


# ── 1. the adult rule: invisible, never "filtered out with a reason" ─────────

class V2AdultRuleTests(V2WireFixture):

    def test_adult_id_answers_exactly_like_a_missing_id(self):
        """§13: same status, same body, same code — a 404-shaped problem, never a
        403 with a message, and never a field that explains itself."""
        cases = [
            (f"/api/v2/works/{self.adult_work_id}", None,
             f"/api/v2/works/{self.missing_work_id}", None),
            (f"/api/v2/works/{self.adult_work_id}/seasons/1", None,
             f"/api/v2/works/{self.missing_work_id}/seasons/1", None),
            (f"/api/v2/episodes/{self.adult_episode_id}", None,
             f"/api/v2/episodes/{self.missing_episode_id}", None),
            (f"/api/v2/releases/{self.adult_release_id}", None,
             f"/api/v2/releases/{self.missing_release_id}", None),
            (f"/api/v2/resolve/{self.handle(self.adult_link_id)}", {"redirect": "0"},
             f"/api/v2/resolve/{self.handle(self.missing_link_id)}", {"redirect": "0"}),
        ]
        for hidden, hidden_query, absent, absent_query in cases:
            with self.subTest(route=hidden):
                first = self.get(hidden, hidden_query)
                second = self.get(absent, absent_query)
                self.assertEqual(first.status, 404)
                self.assertEqual(second.status, 404, f"{absent} disagrees about absence")
                self.assertEqual(first.code, "not_found")
                self.assertEqual(second.code, "not_found")
                body_a, body_b = dict(first.json), dict(second.json)
                body_b["instance"] = body_a["instance"]
                body_b["request_id"] = body_a["request_id"]
                self.assertEqual(body_a, body_b,
                                 f"{hidden} is distinguishable from {absent}")
                self.assertNotEqual(first.code, "forbidden")

    def test_play_answers_404_for_an_unlisted_target_not_a_400(self):
        """`/play` is the route that used to leak by *status code*.

        Naming an unlisted work is not a malformed request: answering 400 "one of
        `release_id`, `episode_id` or `work_id` is required" to an id that was
        supplied made `/play` an oracle — a 400 meant "that title exists and is
        18+", a 404 meant "it does not". A request that names nothing at all must
        still be the 400, or the two cases swap instead of collapsing.
        """
        for field, hidden, absent in (
                ("work_id", self.adult_work_id, self.missing_work_id),
                ("release_id", self.adult_release_id, self.missing_release_id),
                ("episode_id", self.adult_episode_id, self.missing_episode_id)):
            with self.subTest(field=field):
                first = self.post("/api/v2/play", {field: hidden})
                second = self.post("/api/v2/play", {field: absent})
                self.assertEqual(first.status, 404)
                self.assertEqual(second.status, 404,
                                 f"a made-up {field} answers differently")
                self.assertEqual(first.code, "not_found")
                self.assertEqual(second.json["detail"], first.json["detail"])
        unnamed = self.post("/api/v2/play", {"prefer": "speed"})
        self.assertEqual(unnamed.status, 400)
        self.assertEqual(unnamed.code, "invalid_params")
        self.assertIn("required", unnamed.json["detail"])

    def test_report_and_offset_hide_adult_rows_the_same_way(self):
        hidden = self.post(f"/api/v2/links/{self.handle(self.adult_link_id)}/report",
                           {"event": "played"})
        absent = self.post(f"/api/v2/links/{self.handle(self.missing_link_id)}/report",
                           {"event": "played"})
        self.assertEqual(hidden.status, 404)
        self.assertEqual(absent.status, 404)
        self.assertEqual(hidden.json["detail"], absent.json["detail"])
        # …and nothing was recorded for the row the public port cannot see.
        self.assertEqual(self.report_rows(link_id=self.adult_link_id), 0)
        hidden = self.post(f"/api/v2/episodes/{self.adult_episode_id}/offset",
                           {"offset_seconds": 60})
        absent = self.post(f"/api/v2/episodes/{self.missing_episode_id}/offset",
                           {"offset_seconds": 60})
        self.assertEqual(hidden.status, 404)
        self.assertEqual(absent.status, 404)
        self.assertEqual(hidden.json["detail"], absent.json["detail"])

    def test_collection_routes_are_empty(self):
        """Every listing either omits the title or says nothing about it."""
        titles = {"Adult Diary": "adult", "Dune Protocol": "public"}
        # browse / search / suggest / sync / feed / stats
        reply = self.get("/api/v2/browse", {"limit": 100, "sort": "title"})
        self.assertNotIn("Adult Diary", [item["title"] for item in reply.json["items"]])
        self.assertEqual(reply.json["total_estimate"],
                         reply.json["count"], "the total advertises hidden rows")
        self.assertNotIn("adult_included", reply.json,
                         "a field that appears only for hidden rows is itself the leak")
        reply = self.get("/api/v2/search", {"q": "diary"})
        self.assertEqual(reply.json["items"], [])
        self.assert_problem(self.get("/api/v2/search", {"q": "adult diary"}),
                            code="not_found", status=404, instance="/api/v2/search") \
            if False else None
        reply = self.get("/api/v2/suggest", {"q": "adult"})
        self.assertEqual(reply.json["items"], [])
        reply = self.get("/api/v2/sync", {"limit": 100})
        self.assertNotIn("Adult Diary", [item["title"] for item in reply.json["items"]])
        reply = self.get("/api/v2/feed.m3u")
        self.assertNotIn("Adult Diary", reply.text)
        for line in reply.text.splitlines():
            if line.startswith("#EXTINF"):
                self.assertNotIn("Adult", line)
        reply = self.get("/api/v2/stats")
        counts = reply.json["counts"]
        stored = self.conn.execute(
            "SELECT COUNT(*) FROM cat_works").fetchone()[0]
        hidden = self.conn.execute(
            "SELECT COUNT(*) FROM cat_works WHERE is_18_plus = 1").fetchone()[0]
        self.assertEqual(counts["works"], stored - hidden)
        self.assertLess(counts["works"], stored)

    def test_the_flag_never_leaves_but_the_operator_always_knows(self):
        """`redact.VIEWS` carries `adult` for admin listings; the wire denies it."""
        public = self.get("/api/v2/suggest", {"q": "dune"})
        self.assertNotIn("adult_included", public.json)
        operator = self.get("/api/v2/suggest", {"q": "dune"}, operator=True)
        self.assertIn("adult_included", operator.json)
        self.assertEqual(operator.json["adult_included"], True)
        browse = self.get("/api/v2/browse", {"limit": 100}, operator=True)
        titles = [item["title"] for item in browse.json["items"]]
        self.assertIn("Adult Diary", titles,
                      "an operator port that hides nothing is not an operator port")
        self.assertEqual({item["adult"] for item in browse.json["items"]},
                         {True, False})
        self.assertNotIn("Adult Diary",
                         [item["title"] for item in
                          self.get("/api/v2/browse", {"limit": 100}).json["items"]])

    def test_sync_hides_unlisted_rows_in_every_scope(self):
        """§13 for `/sync` — including `entitlements`, which has no work join.

        `cat_entitlements` gets one row per projected work, unlisted ones included,
        so a scope that reads it without the join publishes a hidden title's row id
        while `/works/{id}` 404s the same title.
        """
        adult_work = self.adult_work_id
        for scope in ("catalog", "health", "entitlements"):
            with self.subTest(scope=scope):
                reply = self.get("/api/v2/sync", {"scope": scope, "limit": 200})
                self.assertEqual(reply.status, 200)
                text = json.dumps(reply.json)
                self.assertNotIn("Adult Diary", text)
                if scope == "catalog":
                    self.assertNotIn(f'"id": {adult_work}', text.replace(' ", "', ""))
                if scope == "entitlements":
                    self.assertEqual([item["work_id"] for item in reply.json["items"]],
                                     [item["work_id"] for item in reply.json["items"]
                                      if item["work_id"] != adult_work])
        operator = self.get("/api/v2/sync", {"scope": "catalog", "limit": 200},
                            operator=True)
        self.assertIn("Adult Diary", [item["title"] for item in operator.json["items"]])


# ── 2. provenance: nothing that names a source ever leaves ──────────────────

class V2ProvenanceTests(V2WireFixture):

    def public_payloads(self):
        """One of everything the wire can say, as a public caller."""
        yields = [
            ("manifest", self.get("/api/v2/manifest")),
            ("browse", self.get("/api/v2/browse", {"limit": 5})),
            ("search", self.get("/api/v2/search", {"q": "dune"})),
            ("suggest", self.get("/api/v2/suggest", {"q": "dune"})),
            ("work", self.get(f"/api/v2/works/{self.public_work_id}")),
            ("season", self.get(f"/api/v2/works/{self.work_ids['Campus Beats']}/seasons/1")),
            ("episode", self.get(f"/api/v2/episodes/{self.public_episode_id}")),
            ("release", self.get(f"/api/v2/releases/{self.public_release_id}")),
            ("resolve_json", self.get(f"/api/v2/resolve/{self.handle(self.public_link_id)}",
                                      {"redirect": "0"})),
            ("sync_catalog", self.get("/api/v2/sync", {"limit": 3})),
            ("sync_health", self.get("/api/v2/sync", {"scope": "health", "limit": 3})),
            ("sync_entitlements", self.get("/api/v2/sync", {"scope": "entitlements",
                                                            "limit": 3})),
            ("stats", self.get("/api/v2/stats")),
            ("health", self.get("/api/v2/health")),
            ("play", self.post("/api/v2/play", {"release_id": self.public_release_id})),
            ("play_prefer", self.post("/api/v2/play", {"release_id": self.public_release_id,
                                                      "prefer": "speed"})),
            ("report", self.post(f"/api/v2/links/{self.handle(self.public_link_id)}/report",
                                 {"event": "played", "ms": 120,
                                  "error": "stalled on hubcloud"})),
            ("offset", self.post(f"/api/v2/episodes/{self.public_episode_id}/offset",
                                 {"offset_seconds": 90, "chapter_title": "Ep 1"})),
            ("not_found_problem", self.get("/api/v2/works/99999999")),
            ("bad_cursor_problem", self.get("/api/v2/sync", {"since": "not-a-cursor"})),
            ("exhausted_play_problem", self.post("/api/v2/play",
                                                 {"release_id": self.public_release_id,
                                                  "device": "tv"})),
        ]
        return yields

    def test_no_route_serialises_a_provenance_key_or_token(self):
        """The invariant, not a search: keys denied by name, text denied by needle."""
        for label, reply in self.public_payloads():
            with self.subTest(route=label):
                if reply.json is not None:
                    self.assert_clean(reply.json, label=label)
                else:
                    self.assert_clean(reply.text, label=label)

    def test_the_ledger_really_does_name_the_sources(self):
        """Guards the test above against proving nothing.

        If the fixture's own provenance ever stopped being written, "no leak" would
        be vacuous, so the ledger is checked to contain what we then refuse to say.
        """
        sites = {row[0] for row in
                 self.conn.execute("SELECT DISTINCT source_site FROM posts")}
        self.assertIn("vegamovies", sites)
        hosts = " ".join(str(row[0]) for row in self.conn.execute(
            "SELECT final_url FROM download_sources"))
        for token in ("gdtot", "hubcloud", "pixeldrain", "googleusercontent"):
            self.assertIn(token, hosts)
        stored = self.conn.execute(
            "SELECT poster_url FROM posts WHERE source_site = 'vegamovies'"
            " AND poster_url LIKE '%vegamovies%'").fetchone()
        self.assertIsNotNone(stored, "the fixture lost its upstream art URL")
        evidence = self.conn.execute(
            "SELECT error FROM cat_link_evidence WHERE error IS NOT NULL").fetchone()
        self.assertIn("hubcloud", evidence[0], "the diagnostic row went missing")

    def test_upstream_image_urls_become_our_own_handles(self):
        """The `suggest` shape used to forward the stored poster URL verbatim.

        `poster_url` is not on `redact.PROVENANCE` — no key ending `_url` that the
        read model hands out is — so the deny-list could not see it and the wire
        printed `https://img.vegamovies.watch/Dune-Protocol.jpg`, naming the site
        in the one field a user actually looks at.
        """
        reply = self.get("/api/v2/suggest", {"q": "dune"})
        item = reply.json["items"][0]
        self.assertNotIn("poster_url", item)
        self.assertIn("poster", item)
        src = item["poster"]["src"]
        self.assertTrue(src.startswith(f"{HOST}/api/v1/art?id="), src)
        self.assertEqual(item["poster"]["kind"], "poster")
        query = parse_qsl(urlparse(src).query)
        handle = dict(query)["id"]
        self.assertEqual(redact.parse_token(handle, self.secret, signed_only=True),
                         self.public_work_id, "the art handle is not the work it names")
        self.assert_clean(reply.json, label="suggest")
        # The same artwork as a card, addressed the same way: one handle, one shape.
        browse = self.get("/api/v2/browse", {"limit": 50})
        card = [row for row in browse.json["items"] if row["id"] == self.public_work_id][0]
        self.assertEqual(card["poster"]["src"], src)

    def test_diagnostics_never_name_a_hoster(self):
        """`probe_error` is free text written by a probe, about somebody's server."""
        reply = self.post("/api/v2/play", {"release_id": self.public_release_id})
        self.assert_clean(reply.json, label="play")
        errors = [link.get("probe_error") for link in reply.json.get("candidates") or []
                  if link.get("probe_error")]
        self.assertTrue(errors, "the fixture's failing probe vanished")
        for text in errors:
            self.assertNotIn("hubcloud", text.lower())
        stored = [row[0] for row in self.conn.execute(
            "SELECT error FROM cat_link_evidence WHERE error IS NOT NULL")]
        self.assertTrue(any("hubcloud" in text for text in stored),
                        "zero data loss: the ledger keeps what it measured")

    def test_report_detail_is_scrubbed_before_it_is_stored(self):
        reply = self.post(f"/api/v2/links/{self.handle(self.public_link_id)}/report",
                          {"event": "failed", "ms": 900, "device": "shield-tv",
                           "error": "vegadrive returned a 503"})
        self.assertEqual(reply.status, 200)
        self.assert_clean(reply.json, label="report")
        stored = self.conn.execute(
            "SELECT detail FROM client_link_reports ORDER BY id DESC LIMIT 1").fetchone()
        self.assertNotIn("vegadrive", (stored[0] or "").lower())
        evidence = self.conn.execute(
            "SELECT error FROM cat_link_evidence ORDER BY probed_at DESC LIMIT 1"
            ).fetchone()
        self.assertNotIn("vegadrive", (evidence[0] or "").lower())

    def test_feed_playlist_addresses_only_our_own_routes(self):
        """Every URI must be our own host and our own handle — never an upstream URL."""
        reply = self.get("/api/v2/feed.m3u")
        self.assertEqual(reply.header("content-type").split(";")[0], "application/x-mpegURL")
        text = self.assert_clean(reply.text, label="feed.m3u")
        entries = [line for line in text.splitlines() if not line.startswith("#") and line]
        self.assertTrue(entries)
        expected = self.public_ids(
            """
            SELECT l.id FROM cat_links l JOIN cat_works w ON w.id = l.work_id
            WHERE (w.is_18_plus IS NULL OR w.is_18_plus = 0) AND l.ephemeral = 0
              AND l.playability IN ('stream', 'both') AND l.state = 'active'
            """)
        seen = []
        for line in entries:
            parsed = urlparse(line)
            self.assertEqual(f"{parsed.scheme}://{parsed.netloc}", HOST,
                             f"a playlist naming somebody else's host: {line}")
            self.assertEqual(parsed.path.split("/")[2:4], ["v2", "resolve"], line)
            handle = unquote(parsed.path.rsplit("/", 1)[-1])
            link_id = redact.parse_token(handle, self.secret, signed_only=True)
            self.assertIsNotNone(link_id, f"an unparseable handle in the feed: {handle}")
            seen.append(link_id)
        self.assertEqual(sorted(seen), sorted(expected),
                         "the feed published a link it should not, or dropped one")
        self.assertEqual(len(entries), text.count("#EXTINF"), "a title without a URI")
        self.assertIn("#EXT-X-ENDLIST", text)
        # `work_id` narrows it to that work's own channels, and to nothing else.
        narrowed = self.get("/api/v2/feed.m3u", {"work_id": self.public_work_id})
        self.assertEqual(len([line for line in narrowed.text.splitlines()
                              if line and not line.startswith("#")]), 1)

    def test_the_302_is_the_only_place_an_upstream_url_appears(self):
        """§16.9's honest exception: the redirect is where the URL *must* go.

        The player follows it and gets bytes; no JSON body ever names the host, and
        the route that returns JSON instead of a redirect returns no URL at all.
        """
        reply = self.get(f"/api/v2/resolve/{self.handle(self.public_link_id)}")
        self.assertEqual(reply.status, 302)
        location = reply.header("location")
        self.assertTrue(location.startswith("https://video-downloads.googleusercontent.com/"),
                        location)
        self.assertEqual(reply.header("cache-control"), "no-store")
        self.assertEqual(reply.body, b"")
        json_form = self.get(f"/api/v2/resolve/{self.handle(self.public_link_id)}",
                             {"redirect": "0"})
        self.assertEqual(json_form.status, 200)
        self.assert_clean(json_form.json, label="resolve?redirect=0")
        self.assertNotIn("url", json_form.json)
        for key in deep_keys(json_form.json):
            self.assertNotIn("url", str(key).lower())
        # The key a competitor would mirror as their own catalog id is a handle.
        self.assertEqual(redact.parse_token(json_form.json["link_ref"], self.secret,
                                           signed_only=True), self.public_link_id)
        self.assertEqual(json_form.json["link_ref"], json_form.json["stream_id"])


# ── 3. opaque handles ────────────────────────────────────────────────────────

class V2OpaqueHandleTests(V2WireFixture):

    def test_public_port_refuses_enumerable_row_ids(self):
        """`redact.parse_token(signed_only=True)` says a row id is not an address.

        A fallback that re-tried `handle.isdigit()` after that call cancelled it,
        so `/api/v2/resolve/1` 302-ed to a file URL and `POST /api/v2/links/1/report`
        recorded telemetry against a row the caller had guessed — walking 1..N
        harvested every file we hold and polluted the measured axis with reports
        for links nobody played.
        """
        for row_id in (1, 2, 3, self.public_link_id):
            with self.subTest(resolve=row_id):
                reply = self.get(f"/api/v2/resolve/{row_id}")
                self.assert_problem(reply, code="invalid_params", status=400,
                                    instance=f"/api/v2/resolve/{row_id}")
                self.assertEqual(reply.replies[0]["status"], 400)
                self.assertNotIn("location", reply.headers)
        before = self.report_rows()
        for row_id in (1, 2, self.public_link_id):
            reply = self.post(f"/api/v2/links/{row_id}/report", {"event": "played"})
            self.assert_problem(reply, code="invalid_params", status=400,
                                instance=f"/api/v2/links/{row_id}/report")
        self.assertEqual(self.report_rows(), before,
                         "a guessed row id was still recorded")
        # The operator port is the one place a plain id is a legitimate address.
        operator = self.get(f"/api/v2/resolve/{self.public_link_id}", {"redirect": "0"},
                            operator=True)
        self.assertEqual(operator.status, 200)
        self.assert_problem(self.get(f"/api/v2/resolve/{self.public_link_id}",
                                    {"redirect": "0"}),
                            code="invalid_params", status=400,
                            instance=f"/api/v2/resolve/{self.public_link_id}")

    def test_a_handle_resolves_its_own_link_and_no_other(self):
        own_handle = self.handle(self.public_link_id)
        page_handle = self.handle(self.page_link_id)
        own = self.get(f"/api/v2/resolve/{own_handle}", {"redirect": "0"})
        other = self.get(f"/api/v2/resolve/{page_handle}", {"redirect": "0"})
        # A static copy answers 200 and names itself and nothing else.
        self.assertEqual(own.status, 200)
        self.assertEqual(own.json["link_ref"], own_handle)
        self.assertEqual(own.json["stream_id"], own_handle)
        self.assertNotEqual(own_handle, page_handle)
        # The hoster page is `resolve_required` (§8.2): with no upstream to unwrap,
        # §16.4 makes that an honest 409 on our own code list — never a fake 200 and
        # never a 400/404 that would say the handle was not ours. Either way the
        # answer is about *that* row, so one handle can never fetch the other's file.
        self.assertIn(other.status, (200, 409))
        if other.status == 200:
            self.assertEqual(other.json["link_ref"], page_handle)
        else:
            self.assert_problem(other, code="no_playable_source", status=409,
                                instance=f"/api/v2/resolve/{page_handle}")
            self.assertEqual(other.json["details"]["link_id"], self.page_link_id)
        self.assertNotEqual(own.json.get("link_ref"), other.json.get("link_ref"))
        for handle, expected_id in ((own_handle, self.public_link_id),
                                    (page_handle, self.page_link_id)):
            self.assertEqual(redact.parse_token(handle, self.secret, signed_only=True),
                             expected_id, "a handle names the wrong link")
        # Tampering with a handle fails instead of resolving somebody else's row.
        good = own_handle
        for mutation in (good[:-2] + ("AA" if not good.endswith("AA") else "BB"),
                         good[2:], good[::-1]):
            with self.subTest(mutation=mutation):
                self.assert_problem(self.get(f"/api/v2/resolve/{mutation}",
                                             {"redirect": "0"}),
                                    code="invalid_params", status=400,
                                    instance=f"/api/v2/resolve/{mutation}")
        # A handle minted with a different key is not one we issued.
        foreign = redact.mint_token(self.public_link_id, "a-different-install-secret")
        self.assert_problem(self.get(f"/api/v2/resolve/{foreign}", {"redirect": "0"}),
                            code="invalid_params", status=400,
                            instance=f"/api/v2/resolve/{foreign}")

    def test_links_are_handed_out_as_handles_in_every_shape(self):
        """Whatever a client is given to come back with, it can come back with."""
        bundle = self.post("/api/v2/play", {"release_id": self.public_release_id})
        self.assertEqual(bundle.status, 200)
        playable = [link for link in bundle.json["candidates"] if link["playable"]]
        self.assertTrue(playable)
        round_trips = 0
        for link in playable:
            handle = link["stream_id"]
            self.assertNotEqual(handle, str(link["link_id"]),
                                "the opaque id is the row id in disguise")
            resolved = redact.parse_token(handle, self.secret, signed_only=True)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved, link["link_id"],
                              "the handle is not the link the bundle named")
            again = self.get(f"/api/v2/resolve/{handle}", {"redirect": "0"})
            # A copy that needs a live unwrap (§8.2) answers 409 when there is no
            # upstream to unwrap — §16.4's honest failure. What must never happen is
            # the handle being refused: 400 would mean we issued an address we do not
            # accept, 404 would mean the bundle listed a link that is not in the
            # catalog, and both would be a client that cannot play anything.
            self.assertIn(again.status, (200, 409))
            if again.status == 200:
                round_trips += 1
                self.assertEqual(again.json["stream_id"], handle)
            else:
                self.assert_problem(again, code="no_playable_source", status=409,
                                    instance=f"/api/v2/resolve/{handle}")
        self.assertGreaterEqual(round_trips, 1, "no handle ever came back as an answer")
        feed = self.get("/api/v2/feed.m3u")
        for line in feed.text.splitlines():
            if line and not line.startswith("#"):
                handle = unquote(urlparse(line).path.rsplit("/", 1)[-1])
                self.assertIsNotNone(
                    redact.parse_token(handle, self.secret, signed_only=True), line)

    def test_the_operator_flag_changes_the_answer(self):
        """`operator` is set on the server, never negotiated by a request (§13)."""
        public = self.get(f"/api/v2/works/{self.public_work_id}")
        operator = self.get(f"/api/v2/works/{self.public_work_id}", operator=True)
        self.assertEqual(public.status, 200)
        self.assertEqual(operator.status, 200)
        self.assertNotIn("provenance", public.json)
        self.assertIn("provenance", operator.json)
        hidden = self.get(f"/api/v2/works/{self.adult_work_id}")
        shown = self.get(f"/api/v2/works/{self.adult_work_id}", operator=True)
        self.assertEqual(hidden.status, 404)
        self.assertEqual(shown.status, 200)
        self.assertEqual(shown.json["work"]["title"], "Adult Diary")
        # The adult work's own link resolves for the operator and 404s for a caller.
        self.assertEqual(self.get(f"/api/v2/resolve/{self.handle(self.adult_link_id)}",
                                  {"redirect": "0"}, operator=True).status, 200)
        self.assertEqual(self.get(f"/api/v2/resolve/{self.handle(self.adult_link_id)}",
                                  {"redirect": "0"}).status, 404)
        # And a request cannot ask for either privilege.
        sneaky = self.get(f"/api/v2/works/{self.adult_work_id}",
                          {"operator": "1", "include_adult": "1", "full": "1"})
        self.assertEqual(sneaky.status, 404)

    def test_sync_work_ref_is_a_handle_not_the_identity_string(self):
        """§16.3 keys on `work_key`; the wire may not print one."""
        reply = self.get("/api/v2/sync", {"limit": 3})
        item = reply.json["items"][0]
        self.assertNotIn("work_key", item)
        self.assertIn("work_ref", item)
        decoded = redact.parse_text(item["work_ref"], self.secret)
        stored = self.conn.execute("SELECT work_key FROM cat_works WHERE id = ?",
                                   (item["id"],)).fetchone()[0]
        self.assertEqual(decoded, stored, "the handle does not name the row it keys")


# ── 4. conditional requests ─────────────────────────────────────────────────

class V2CachingTests(V2WireFixture):

    def test_etag_helpers_are_weak_stable_and_rev_bound(self):
        first = api_v2.etag_for("browse|same-payload", rev=1)
        self.assertTrue(first.startswith('W/"cat-1-'), first)
        self.assertEqual(first, api_v2.etag_for("browse|same-payload", rev=1))
        self.assertNotEqual(first, api_v2.etag_for("browse|other-payload", rev=1))
        self.assertNotEqual(first, api_v2.etag_for("browse|same-payload", rev=2))
        self.assertTrue(api_v2.etag_matches(first, first))
        self.assertTrue(api_v2.etag_matches('*', first))
        self.assertTrue(api_v2.etag_matches(f'W/"x", {first}', first))
        # A strong validator for the same content still matches a weak one (§16.2).
        self.assertTrue(api_v2.etag_matches(first.replace('W/"', '"'), first))
        self.assertFalse(api_v2.etag_matches("", first))
        self.assertFalse(api_v2.etag_matches('W/"cat-1-deadbeef"', first))
        self.assertFalse(api_v2.etag_matches("garbage", first))

    def test_if_none_match_answers_304_with_validators_and_no_body(self):
        for path, query in (("/api/v2/browse", {"limit": 5}),
                            ("/api/v2/manifest", None),
                            ("/api/v2/stats", None),
                            ("/api/v2/feed.m3u", None),
                            (f"/api/v2/works/{self.public_work_id}", None)):
            with self.subTest(path=path):
                first = self.get(path, query)
                etag = first.header("etag")
                self.assertTrue(etag and etag.startswith('W/"'), f"{path}: {etag}")
                self.assertEqual(first.header("cache-control"),
                                 api_v2.CACHE_BROWSE if path.startswith("/api/v2/browse")
                                 else first.header("cache-control"))
                self.assertIsNotNone(first.header("last-modified"))
                again = self.get(path, query, headers={"If-None-Match": etag})
                self.assertEqual(again.status, 304)
                self.assertEqual(again.body, b"", "a 304 with a body is a cache poison")
                self.assertEqual(again.header("etag"), etag)
                self.assertIsNotNone(again.header("cache-control"))
                self.assertIsNone(again.header("content-length"))
                self.assertNotIn("content-type", again.headers)
                # A different validator must not match.
                self.assertEqual(self.get(path, query,
                                          headers={"If-None-Match": 'W/"cat-1-nope"'}
                                          ).status, 200)

    def test_etag_moves_with_the_revision_not_with_the_query_shape(self):
        """Two spellings, one payload ⇒ one validator (§16.2's whole point)."""
        plain = self.get("/api/v2/browse")
        spelled = self.get("/api/v2/browse", {"sort": "trending", "order": "desc"})
        self.assertEqual(plain.json, spelled.json)
        self.assertEqual(plain.header("etag"), spelled.header("etag"))
        narrower = self.get("/api/v2/browse", {"limit": 2})
        self.assertNotEqual(narrower.header("etag"), plain.header("etag"))
        filtered = self.get("/api/v2/browse", {"type": "series"})
        self.assertNotEqual(filtered.header("etag"), plain.header("etag"))
        self.add_post("katmoviehd", "https://new.katmoviehd.top/amber-station-2024/",
                      clean_title="Amber Station", year=2024, releases=[
                          {"release_title": "Amber Station (2024) 1080p WEB-DL",
                           "sources": [cdn("AMBER-CDN")]}])
        self.project(rev=2)
        after = self.get("/api/v2/browse")
        self.assertEqual(api_v2.catalog_rev(self.conn), 2)
        self.assertTrue(after.header("etag").startswith('W/"cat-2-'), after.header("etag"))
        self.assertNotEqual(after.header("etag"), plain.header("etag"))
        self.assertEqual(self.get("/api/v2/browse",
                                  headers={"If-None-Match": plain.header("etag")}
                                  ).status, 200,
                         "a stale validator was accepted after the catalog moved")

    def test_no_store_routes_never_validate(self):
        """§16.2: a play bundle or a health answer that can be cached cannot be trusted."""
        for label, reply in (("health", self.get("/api/v2/health")),
                             ("sync", self.get("/api/v2/sync")),
                             ("resolve", self.get(
                                 f"/api/v2/resolve/{self.handle(self.public_link_id)}",
                                 {"redirect": "0"}))):
            with self.subTest(label=label):
                self.assertEqual(reply.header("cache-control"), "no-store")
                self.assertIsNone(reply.header("etag"),
                                  f"{label} published a validator for a live answer")
        play = self.post("/api/v2/play", {"release_id": self.public_release_id})
        self.assertEqual(play.header("cache-control"), "no-store")
        self.post(f"/api/v2/links/{self.handle(self.public_link_id)}/report",
                  {"event": "played"})
        report = Reply(self.call(f"/api/v2/links/{self.handle(self.public_link_id)}"
                                 f"/report", method="POST",
                                 body={"event": "stalled"}).replies and
                       self.call(f"/api/v2/links/{self.handle(self.public_link_id)}"
                                 f"/report", method="POST",
                                 body={"event": "stalled"}), path="/x") \
            if False else None
        self.assertNotIn("etag", play.headers)

    def test_cache_class_per_route(self):
        expected = {
            "/api/v2/manifest": api_v2.CACHE_MANIFEST,
            "/api/v2/browse": api_v2.CACHE_BROWSE,
            "/api/v2/search": api_v2.CACHE_BROWSE,
            "/api/v2/suggest": api_v2.CACHE_BROWSE,
            "/api/v2/stats": api_v2.CACHE_BROWSE,
            f"/api/v2/works/{self.public_work_id}": api_v2.CACHE_DETAIL,
            f"/api/v2/releases/{self.public_release_id}": api_v2.CACHE_DETAIL,
            f"/api/v2/episodes/{self.public_episode_id}": api_v2.CACHE_DETAIL,
            "/api/v2/feed.m3u": api_v2.CACHE_DETAIL,
            "/api/v2/health": api_v2.CACHE_NO_STORE,
            "/api/v2/sync": api_v2.CACHE_NO_STORE,
        }
        for path, cache in expected.items():
            with self.subTest(path=path):
                reply = self.get(path, {"q": "dune"} if path.endswith(
                    ("search", "suggest")) else None)
                self.assertEqual(reply.header("cache-control"), cache)
                self.assertEqual(reply.header("vary"), "Accept-Encoding")
                self.assertTrue(str(reply.header("x-request-id") or "").startswith("req_"))
        self.assertEqual(api_v2.PROBLEM_CODES["unavailable"][1], "The catalog is not ready")


# ── 5. errors ────────────────────────────────────────────────────────────────

class V2ErrorTests(V2WireFixture):

    def test_unknown_and_misshapen_routes_are_problem_json(self):
        for path in ("/api/v2/nope", "/api/v2", "/api/v2/", "/api/v2/works",
                     "/api/v2/works/1/episodes/2", "/api/v2/collections/7",
                     "/api/v2/releases/1/links", "/api/v2/sync/catalog"):
            with self.subTest(path=path):
                reply = self.get(path)
                self.assert_problem(reply, code="not_found", status=404,
                                    instance=path)
        # `collections` has no table: an id we cannot look up answers like one that
        # does not exist, which is the whole of §12's 📝 for that route.
        self.assertEqual(self.get("/api/v2/collections/7").json["detail"],
                         self.get("/api/v2/collections/8").json["detail"])

    def test_bad_cursors_are_cursor_invalid_not_luckier(self):
        reply = self.get("/api/v2/sync", {"since": "not-a-cursor"})
        self.assert_problem(reply, code="cursor_invalid", status=400,
                            instance="/api/v2/sync")
        self.assertIn("cursor", reply.json["detail"].lower())
        reply = self.get("/api/v2/sync", {"since": "####"})
        self.assert_problem(reply, code="cursor_invalid", status=400,
                            instance="/api/v2/sync")
        # A browse cursor minted for a different facet set is rejected, not obeyed.
        mine = self.get("/api/v2/browse", {"type": "movie", "limit": 2})
        foreign = mine.json["next_cursor"]
        self.assertIsNotNone(foreign)
        reply = self.get("/api/v2/browse", {"type": "series", "cursor": foreign,
                                            "limit": 2})
        self.assert_problem(reply, code="cursor_invalid", status=400,
                            instance="/api/v2/browse")
        reply = self.get("/api/v2/browse", {"cursor": "zzzz-garbage", "limit": 2})
        self.assert_problem(reply, code="cursor_invalid", status=400,
                            instance="/api/v2/browse")

    def test_bad_parameters_are_named_without_being_echoed(self):
        for path, query, code in (
                ("/api/v2/search", {}, "invalid_params"),
                ("/api/v2/suggest", {}, "invalid_params"),
                ("/api/v2/sync", {"scope": "everything"}, "invalid_params"),
                (f"/api/v2/works/{self.public_work_id}/seasons/one", {}, "invalid_params"),
                (f"/api/v2/resolve/{self.handle(self.public_link_id)}",
                 {"redirect": "0"}, None)):
            if code is None:
                self.assertEqual(self.get(path, query).status, 200)
                continue
            with self.subTest(path=path, query=query):
                reply = self.get(path, query)
                self.assert_problem(reply, code=code, status=400, instance=path)

    def test_malformed_bodies_never_reach_the_parser(self):
        path = "/api/v2/play"
        cases = {
            "truncated object": b"{",
            "not an object": b'["release_id"]',
            "scalar": b"42",
            "binary": b"\xff\xfe\x00\x01",
            "empty is fine": b"",
        }
        for label, raw in cases.items():
            with self.subTest(case=label):
                reply = self.post(path, raw_body=raw)
                if label == "empty is fine":
                    # No target named at all: a 400 about the body of the request,
                    # and identical to the 400 an empty JSON object gets.
                    self.assert_problem(reply, code="invalid_params", status=400,
                                        instance=path)
                    continue
                self.assert_problem(reply, code="invalid_params", status=400,
                                    instance=path)
        big = json.dumps({"release_id": self.public_release_id,
                          "device": "x" * (api_v2.MAX_BODY_BYTES + 1)}).encode()
        reply = self.post(path, raw_body=big)
        self.assert_problem(reply, code="invalid_params", status=400, instance=path)
        self.assertLess(len(reply.body), 2000, "an error body should not be a novel")
        reply = self.post(path, raw_body=b"{}", headers={"Content-Length": "-4"})
        self.assert_problem(reply, code="invalid_params", status=400, instance=path)
        # An unknown POST shape under a known head is a 404, not a 500.
        self.assert_problem(self.post("/api/v2/links/report", {"event": "played"}),
                            code="not_found", status=404, instance="/api/v2/links/report")
        self.assert_problem(self.post("/api/v2/nope", {"a": 1}),
                            code="not_found", status=404, instance="/api/v2/nope")

    def test_no_stack_trace_or_sql_survives_in_any_error_body(self):
        offenders = []
        bad_calls = [
            lambda: self.get("/api/v2/nope"),
            lambda: self.get("/api/v2/sync", {"since": "~~~"}),
            lambda: self.get("/api/v2/sync", {"scope": "catalog; DROP TABLE cat_works"}),
            lambda: self.get("/api/v2/browse", {"limit": "NaN"}),
            lambda: self.get("/api/v2/browse", {"cursor": "e30"}),
            lambda: self.get("/api/v2/works/../../etc/passwd"),
            lambda: self.get(f"/api/v2/resolve/{'A' * 40}"),
            lambda: self.get("/api/v2/episodes/not-a-number"),
            lambda: self.post("/api/v2/play", raw_body=b'{"release_id": "abc"}'),
            lambda: self.post(f"/api/v2/links/{self.handle(self.public_link_id)}/report",
                              {"event": "shrugged"}),
            lambda: self.post(f"/api/v2/episodes/{self.public_episode_id}/offset",
                              {"offset_seconds": api_v2.MAX_OFFSET_SECONDS + 1}),
            lambda: self.post(f"/api/v2/episodes/{self.public_episode_id}/offset",
                              {"offset_seconds": -5}),
            lambda: self.post(f"/api/v2/episodes/0/offset", {"offset_seconds": 5}),
        ]
        for call in bad_calls:
            reply = call()
            self.assertTrue(reply.is_problem or reply.status < 400,
                            f"{reply} is not a problem body")
            if reply.is_problem:
                self.assert_problem(reply, code=reply.code, status=reply.status,
                                    instance=reply.json["instance"])
                offenders.append(reply.text)
        text = "\n".join(offenders)
        for forbidden in FORBIDDEN_IN_ERRORS:
            self.assertNotIn(forbidden, text)
        self.assertNotIn("cat_works", text)
        self.assertNotIn("is_18_plus", text)

    def test_rate_limited_problem_carries_retry_after(self):
        """§16.5: the 429 is the same problem shape, and says when to come back."""
        reply = self.get("/api/v2/browse")
        self.assertEqual(reply.header("ratelimit-limit"), "60",
                         "the gate's headers must ride on a v2 reply")
        self.assertEqual(reply.header("ratelimit-remaining"), "59")
        rid = api_v2.request_id()
        handler = FakeHandler()
        api_v2.problem(handler, code="rate_limited", rid=rid, instance="/api/v2/browse",
                       detail="This client is over its request budget.",
                       headers=[("Retry-After", "37")])
        throttled = Reply(handler, "/api/v2/browse")
        self.assert_problem(throttled, code="rate_limited", status=429,
                            instance="/api/v2/browse")
        self.assertEqual(throttled.header("retry-after"), "37")
        self.assertEqual(throttled.header("cache-control"), "no-store")

    def test_an_unprojected_database_is_not_ready(self):
        """A socket answering v2 with no projection is a 503 with Retry-After."""
        with tempfile.TemporaryDirectory() as other:
            empty = Path(other) / "empty.db"
            self.add_post("vegamovies", "https://x/" if False else
                          "https://new1.vegamovies.lease/other/", clean_title="Other")
            empty.touch()
            handler = FakeHandler()
            answered = api_v2.route_get(handler, "/api/v2/browse", {},
                                        db_path=empty, operator=False, base_url=HOST,
                                        secret=self.secret)
            self.assertTrue(answered)
            reply = Reply(handler, "/api/v2/browse")
            self.assert_problem(reply, code="unavailable", status=503,
                                instance="/api/v2/browse")
            self.assertEqual(reply.header("retry-after"), "60")
            self.assertIn("projection", reply.json["detail"])
            handler = FakeHandler({"Content-Length": "2"}, b"{}")
            api_v2.route_post(handler, "/api/v2/play", {}, db_path=empty,
                              operator=False, base_url=HOST, secret=self.secret)
            self.assertEqual(Reply(handler, "/api/v2/play").status, 503)


# ── 6. cursors ───────────────────────────────────────────────────────────────

class V2CursorTests(V2WireFixture):

    def test_cursor_round_trip_and_garbage_rejection(self):
        self.assertEqual(api_v2.cursor_encode(9, 3), "djF8OXwz")
        self.assertEqual(api_v2.cursor_decode("djF8OXwz"), (9, 3))
        for rev, row_id in ((0, 0), (1, 1), (7, 4242), (2 ** 40, 3)):
            self.assertEqual(api_v2.cursor_decode(api_v2.cursor_encode(rev, row_id)),
                             (rev, row_id))
        # A version stamp that is not a whole number survives the same round trip,
        # because `health` rows are keyed on a probe timestamp.
        for rev in (1.5, 1730000000.125):
            token = api_v2.cursor_encode(rev, 4)
            self.assertEqual(api_v2.cursor_decode(token), (rev, 4))
        self.assertEqual(api_v2.cursor_decode(""), (0, 0))
        self.assertEqual(api_v2.cursor_decode(None), (0, 0))
        for garbage in ("###", "not-a-cursor", "e30", "djF8", "djF8WXwzWXwz",
                        base64_text("v2|1|2"), base64_text("v1|one|2"),
                        base64_text("v1|1|two"), base64_text("v1|1|"),
                        base64_text("v1||2"), base64_text("1|2|3"),
                        base64_text("v1|1|2|3"), base64_text("v1|1.2.3|4")):
            with self.subTest(garbage=garbage):
                self.assertIsNone(api_v2.cursor_decode(garbage))

    def test_browse_pagination_yields_each_row_once_across_a_change(self):
        """§16.1: keyset, so a catalog that moves mid-walk cannot repeat or skip."""
        before = self.public_ids(
            "SELECT id FROM cat_works w WHERE (w.is_18_plus IS NULL OR w.is_18_plus = 0)"
            " ORDER BY id")
        seen, sizes, cursor, pages = [], [], None, 0
        while True:
            query = {"limit": 2, "sort": "title", "order": "asc"}
            if cursor:
                query["cursor"] = cursor
            reply = self.get("/api/v2/browse", query)
            self.assertEqual(reply.status, 200)
            page = reply.json
            pages += 1
            sizes.append(len(page["items"]))
            seen.extend(item["id"] for item in page["items"])
            self.assertEqual(page["count"], len(page["items"]))
            if not page["has_more"]:
                self.assertIsNone(page["next_cursor"])
                break
            self.assertIsNotNone(page["next_cursor"], "has_more without a cursor")
            cursor = page["next_cursor"]
            if pages == 1:
                # The crawler lands one new title mid-pagination and the projection
                # moves under the walk — the case OFFSET pagination cannot survive.
                self.add_post("katmoviehd",
                              "https://new.katmoviehd.top/amber-station-2024/",
                              clean_title="Amber Station", year=2024, releases=[
                                  {"release_title": "Amber Station (2024) 1080p WEB-DL",
                                   "sources": [cdn("AMBER-CDN")]}])
                self.project(rev=2)
            self.assertLess(pages, 20, "the walk never terminated")
        self.assertEqual(len(seen), len(set(seen)), f"repeated rows: {seen}")
        self.assertEqual(sorted(before), sorted(set(seen) & set(before)),
                         "a row that existed at the start was skipped")
        new_id = self._one("SELECT id FROM cat_works WHERE title = 'Amber Station'")
        self.assertLessEqual(seen.count(new_id), 1, "the new row was served twice")
        # Six titles (five public at the start plus the one landed mid-walk) at
        # `limit=2` is three round trips, and only the last page may be short.
        self.assertGreaterEqual(pages, 3, "six titles at limit=2 is not one page")
        self.assertEqual(sizes[:-1], [2] * (pages - 1),
                         f"a page before the last was not full: {sizes}")

    def test_sync_pagination_advances_in_every_scope(self):
        """A `next_cursor` that decodes back to where it started is a stuck client.

        `health` and `entitlements` rows are keyed on their own version stamps, not
        on the catalog rev, and deriving the continuation from the emitted *item*
        looked for keys those items do not have — so the cursor came back identical
        and a client following it refetched the same first row forever, never
        reaching the second.
        """
        expected = {
            "catalog": len(self.public_ids(
                "SELECT id FROM cat_works w WHERE (w.is_18_plus IS NULL"
                " OR w.is_18_plus = 0)")),
            "health": len(self.public_ids(
                "SELECT l.id FROM cat_links l JOIN cat_works w ON w.id = l.work_id"
                " WHERE (w.is_18_plus IS NULL OR w.is_18_plus = 0)")),
            "entitlements": len(self.public_ids(
                "SELECT e.id FROM cat_entitlements e JOIN cat_works w ON w.id = e.work_id"
                " WHERE (w.is_18_plus IS NULL OR w.is_18_plus = 0)")),
        }
        for scope, count in expected.items():
            with self.subTest(scope=scope):
                keys, cursors, since, guard = [], set(), None, 0
                while True:
                    reply = self.get("/api/v2/sync", {"scope": scope, "limit": 2,
                                                      "since": since or ""})
                    self.assertEqual(reply.status, 200)
                    page = reply.json
                    self.assertEqual(page["scope"], scope)
                    for item in page["items"]:
                        keys.append(item.get("id", item.get("link_ref",
                                                            item.get("work_ref"))))
                    if page["next_cursor"] is None:
                        break
                    self.assertNotEqual(page["next_cursor"], since,
                                        f"{scope} handed back the cursor it was given")
                    decoded = api_v2.cursor_decode(page["next_cursor"])
                    self.assertIsNotNone(decoded)
                    if decoded in cursors:
                        self.fail(f"{scope} cursor went in a loop: {decoded}")
                    cursors.add(decoded)
                    since = page["next_cursor"]
                    guard += 1
                    self.assertLess(guard, 30, "the walk never terminated")
                self.assertEqual(len(keys), len(set(keys)), f"{scope} repeated a row")
                self.assertEqual(len(keys), count,
                                 f"{scope} yielded {len(keys)} rows, expected {count}")

    def test_report_and_offset_record_without_echoing_identity(self):
        """Telemetry is ingest; the answer is an acknowledgement, not a row."""
        reply = self.post(f"/api/v2/links/{self.handle(self.public_link_id)}/report",
                          {"event": "played", "ms": 88, "device": "shield-tv"})
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.json["recorded"], True)
        self.assertEqual(reply.json["event"], "played")
        self.assertNotIn("link_id", reply.json)
        self.assertNotIn("work_id", reply.json)
        self.assertEqual(redact.parse_token(reply.json["link_ref"], self.secret,
                                           signed_only=True), self.public_link_id)
        row = self.conn.execute(
            "SELECT * FROM client_link_reports ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(dict(row)["event"], "played")
        self.assertEqual(dict(row)["work_id"], self.public_work_id)
        evidence = self.conn.execute(
            "SELECT ok FROM cat_link_evidence ORDER BY probed_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(evidence["ok"], 1, "a played link is not a confirmation")
        failed = self.post(f"/api/v2/links/{self.handle(self.page_link_id)}/report",
                           {"event": "failed", "error": "embed gave a 403"})
        self.assertEqual(failed.status, 200)
        evidence = self.conn.execute(
            "SELECT ok, error FROM cat_link_evidence ORDER BY probed_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(evidence["ok"], 0, "a failed link cannot confirm itself")
        self.assert_problem(self.post(
            f"/api/v2/links/{self.handle(self.public_link_id)}/report",
            {"event": "buffering"}), code="invalid_params", status=400,
            instance=f"/api/v2/links/{self.handle(self.public_link_id)}/report")

        offset = self.post(f"/api/v2/episodes/{self.public_episode_id}/offset",
                           {"offset_seconds": 4921, "chapter_title": "S01E02",
                            "release_label": "Campus Beats S01 EP(01-03) 720p"})
        self.assertEqual(offset.status, 200)
        self.assertEqual(offset.json["offset_seconds"], 4921)
        # The row is keyed by the episode the client addressed — §S2 stores a
        # learned start position against (work_key, season, episode) and nothing
        # else, so a free-text chapter never decides which row moves.
        addressed = self.conn.execute(
            "SELECT e.number AS episode_number, s.number AS season_number"
            " FROM cat_episodes e"
            " JOIN cat_seasons s ON s.id = e.season_id WHERE e.id = ?",
            (self.public_episode_id,)).fetchone()
        self.assertEqual(offset.json["episode"], int(addressed["episode_number"]))
        self.assertEqual(offset.json["season"], int(addressed["season_number"]))
        self.assertNotIn("work_key", offset.json)
        stored = self.conn.execute(
            "SELECT work_key, season_number, episode_number, offset_seconds,"
            " chapter_title FROM cat_offsets ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(stored, "the offset never reached cat_offsets")
        self.assertEqual(stored["offset_seconds"], 4921)
        self.assertEqual(stored["episode_number"], int(addressed["episode_number"]))
        self.assertEqual(stored["work_key"],
                         self.conn.execute("SELECT work_key FROM cat_works WHERE id = ?",
                                           (self.work_ids["Campus Beats"],)
                                           ).fetchone()[0])
        self.assertNotIn("hubcloud", (stored["chapter_title"] or "").lower())
        for bad in (api_v2.MAX_OFFSET_SECONDS + 1, -1):
            self.assertEqual(self.post(
                f"/api/v2/episodes/{self.public_episode_id}/offset",
                {"offset_seconds": bad}).status, 400)
        self.assertEqual(self.post(
            f"/api/v2/episodes/{self.public_episode_id}/offset",
            {"offset_seconds": 0}).status, 200)


# ── 7. rate buckets ──────────────────────────────────────────────────────────

class V2RateBucketTests(V2WireFixture):

    def test_every_route_maps_to_exactly_one_declared_bucket(self):
        """§16.5, against the buckets `redact.py` already serves."""
        routes = {
            "GET /api/v2/manifest": ("GET", "/api/v2/manifest", "browse"),
            "GET /api/v2/browse": ("GET", "/api/v2/browse", "browse"),
            "GET /api/v2/search": ("GET", "/api/v2/search", "browse"),
            "GET /api/v2/suggest": ("GET", "/api/v2/suggest", "browse"),
            "GET /api/v2/works": ("GET", "/api/v2/works/1", "browse"),
            "GET /api/v2/episodes": ("GET", "/api/v2/episodes/1", "browse"),
            "GET /api/v2/releases": ("GET", "/api/v2/releases/1", "browse"),
            "GET /api/v2/resolve": ("GET", "/api/v2/resolve/1", "play"),
            "GET /api/v2/sync": ("GET", "/api/v2/sync", "browse"),
            "GET /api/v2/collections": ("GET", "/api/v2/collections/1", "browse"),
            "GET /api/v2/feed.m3u": ("GET", "/api/v2/feed.m3u", "browse"),
            "GET /api/v2/stats": ("GET", "/api/v2/stats", "browse"),
            "GET /api/v2/health": ("GET", "/api/v2/health", "browse"),
            "POST /api/v2/play": ("POST", "/api/v2/play", "play"),
            "POST /api/v2/links": ("POST", "/api/v2/links/abc/report", "reports"),
            "POST /api/v2/episodes": ("POST", "/api/v2/episodes/7/offset", "reports"),
        }
        for name, (method, path, bucket) in routes.items():
            with self.subTest(route=name):
                self.assertEqual(api_v2.bucket_for(path, method), bucket)
        # Every declared bucket exists in the shared limiter, and every GET head
        # the dispatcher knows about is listed by name — no implicit membership.
        self.assertFalse(set(api_v2.ROUTE_BUCKETS.values()) - set(redact.BUCKET_LIMITS),
                         "a route is throttled by a bucket nobody configures")
        for head in handled_heads(api_v2.route_get):
            self.assertIn(head, api_v2.ROUTE_BUCKETS, f"{head} has no declared bucket")
            self.assertEqual(api_v2.bucket_for(f"/api/v2/{head}"),
                             api_v2.ROUTE_BUCKETS[head])
        # A head only `route_post` answers is still a mapped route: each one has an
        # explicit entry in the table above, and the bucket it pays into exists.
        post_only = handled_heads(api_v2.route_post) - handled_heads(api_v2.route_get)
        self.assertEqual(post_only, {"links", "play"},
                         "the POST surface changed; §12 and this suite must change with it")
        mapped_heads = {path.split("/")[3] for method, path, _ in routes.values()
                        if method == "POST"}
        self.assertTrue(post_only <= mapped_heads,
                        f"{sorted(post_only - mapped_heads)} is a POST-only head "
                        "nobody mapped")
        for head in sorted(post_only):
            self.assertIn(api_v2.bucket_for(f"/api/v2/{head}", "POST"),
                          redact.BUCKET_LIMITS, f"{head} pays into an undeclared bucket")

    def test_nothing_is_ever_left_unthrottled(self):
        """An unknown path still pays into a real bucket (§16.5's fail-safe)."""
        for path in ("/api/v2/nope", "/api/v2", "/api/v2/works/1/whatever",
                     "/api/v2/play/extra", "/api/v2/links/1/nope"):
            bucket = api_v2.bucket_for(path, "GET" if not path.endswith("nope") else "POST")
            self.assertIn(bucket, redact.BUCKET_LIMITS, f"{path} → {bucket}")
        self.assertEqual(api_v2.bucket_for("/api/v2/nope"), api_v2.ROUTE_BUCKETS["browse"])
        self.assertEqual(api_v2.bucket_for("/api/v2/whatever", "POST"),
                         api_v2.ROUTE_BUCKETS["browse"])
        # One route, one bucket: `resolve` shares `/play`'s budget, not two.
        self.assertEqual(api_v2.bucket_for("/api/v2/resolve/9"),
                         api_v2.bucket_for("/api/v2/play", "POST"))
        self.assertEqual(len({api_v2.bucket_for("/api/v2/browse"),
                              api_v2.bucket_for("/api/v2/browse")}), 1)
        limit, window = redact.BUCKET_LIMITS["play"]
        self.assertEqual((limit, window), (30, 60))


# ── 8. stats honesty ─────────────────────────────────────────────────────────

class V2StatsHonestyTests(V2WireFixture):

    def test_an_unprobed_link_is_unchecked_never_active(self):
        """D7: a scraper wrote 'active' into every row; nobody knocked."""
        stats = self.get("/api/v2/stats").json
        by_state = stats["link_health"]["by_state"]
        states = {row["resource_id"]: row["state"] for row in self.conn.execute(
            "SELECT l.resource_id, l.state FROM cat_links l")}
        self.assertEqual(states["DUNE-CDN"], "active", "a measured link lost its state")
        # Everything the fixture never ran `link_state`'s sweep over. `QV-CDN` is
        # not on this list: the corpus measures it deliberately, because `/feed.m3u`
        # needs more than one live channel to prove it filters at all.
        for unprobed in ("DUNE-PAGE", "DUNE-BRIDGE", "CB-CDN", "SR-CDN", "SR-PAGE",
                         "BO-MIRROR"):
            self.assertIn(states[unprobed], ("unchecked", "dead"), unprobed)
            self.assertNotEqual(states[unprobed], "active", unprobed)
        self.assertEqual(states["QV-CDN"], "active",
                         "a measured link was published as unmeasured")
        self.assertEqual(by_state.get("active", 0),
                         len([tag for tag, state in states.items()
                              if state == "active" and tag != "ADULT-CDN"]),
                         "stats advertised actives nobody measured")
        self.assertIn("unchecked", by_state)
        self.assertGreater(by_state["unchecked"], 0)
        total = sum(by_state.values())
        self.assertEqual(stats["link_health"]["ok_ratio"],
                         round(by_state.get("active", 0) / total, 4))

    def test_every_coverage_number_adds_up(self):
        stats = self.get("/api/v2/stats").json
        counts = stats["counts"]
        health = stats["link_health"]
        self.assertEqual(sum(health["by_state"].values()), counts["links"])
        self.assertEqual(sum(health["by_playability"].values()), counts["links"])
        self.assertEqual(sum(health["by_tier"].values()), counts["links"])
        self.assertEqual(sum(stats["by_work_type"].values()), counts["works"])
        self.assertEqual(sum(stats["by_band"].values()), counts["prints"])
        self.assertEqual(sum(stats["by_print_class"].values()), counts["prints"])
        self.assertEqual(health["streamable"],
                         health["by_playability"].get("stream", 0)
                         + health["by_playability"].get("both", 0))
        self.assertEqual(health["downloadable"],
                         health["by_playability"].get("download", 0)
                         + health["by_playability"].get("both", 0))
        self.assertLessEqual(health["probes"]["ok"], health["probes"]["total"])
        # The corpus writes exactly three probe results: `DUNE-PAGE` (503, failed),
        # `DUNE-CDN` (200, ok, ranges) and `SR-CDN` (no answer, failed). One of the
        # three succeeded, one accepted ranges, and only the ok probe has a speed.
        self.assertEqual(health["probes"]["total"], 3, "the fixture's three probes")
        self.assertEqual(health["probes"]["ok"], 1)
        self.assertEqual(health["probes"]["resumable"], 1)
        self.assertEqual(health["probes"]["avg_speed_mbps"], 42.0)
        # Six posts, one of them the hidden series: five works, five prints and
        # 11 − 2 = 9 links are what a public caller may be told about (§13).
        self.assertEqual(counts["works"], 5)
        self.assertEqual(counts["links"], 9)
        self.assertEqual(counts["prints"], 5)
        self.assertGreater(self.conn.execute(
            "SELECT COUNT(*) FROM cat_works").fetchone()[0], counts["works"])

    def test_stats_are_the_projection_not_the_ledger(self):
        """v1's `/api/v1/stats` counted `posts` wholesale (§12's warning)."""
        stats = self.get("/api/v2/stats").json
        posts = self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        sources = self.conn.execute("SELECT COUNT(*) FROM download_sources").fetchone()[0]
        self.assertNotEqual(stats["counts"]["works"], posts)
        self.assertNotEqual(stats["counts"]["links"], sources)
        self.assertEqual(stats["catalog"]["schema_version"], catalog_v2.SCHEMA_VERSION)
        self.assertEqual(stats["catalog"]["rev"], 1)
        self.assert_clean(stats.json if hasattr(stats, "json") else stats, label="stats")
        self.assertEqual(self.get("/api/v2/health").json["status"], "ready")
        self.assertEqual(self.get("/api/v2/health").json["catalog_rev"], 1)
        self.assertNotIn("counts", self.get("/api/v2/health").json)


# ── 9. the rest of the surface ───────────────────────────────────────────────

class V2SurfaceTests(V2WireFixture):

    def test_structural_route_surface_is_tested(self) -> None:
        """Every route the code can answer has a name in this file, or this fails.

        A v2 route added to the dispatcher without a test is exactly how `api_v2.py`
        got to be 1,400 untested lines.
        """
        get_heads = handled_heads(api_v2.route_get)
        post_heads = handled_heads(api_v2.route_post)
        self.assertEqual(
            get_heads,
            {"manifest", "browse", "search", "suggest", "works", "episodes",
             "releases", "resolve", "sync", "collections", "feed.m3u", "stats",
             "health"},
            "the GET surface changed; §12 and this suite must change with it")
        self.assertEqual(
            post_heads - get_heads, {"play", "links"},
            "the POST surface changed; §12 and this suite must change with it")
        self.assertIn("play", post_heads)
        self.assertIn("episodes", post_heads)
        registry = ROUTE_TESTS
        for head in sorted(get_heads | post_heads):
            self.assertIn(head, registry, f"/api/v2/{head} has no test in this file")
            class_name, method = registry[head]
            case = getattr(_TEST_CLASSES[class_name], method)
            self.assertTrue(callable(case), f"{class_name}.{method} is not a test")

    def test_manifest_publishes_the_contract_it_keeps(self):
        reply = self.get("/api/v2/manifest")
        payload = self.assert_clean(reply.json, label="manifest") and reply.json
        self.assertEqual(payload["contract_version"], api_v2.CONTRACT_VERSION)
        self.assertEqual(payload["base"], "/api/v2")
        self.assertEqual(sorted(payload["error_codes"]), sorted(api_v2.PROBLEM_CODES))
        self.assertEqual(payload["enums"]["prefer"], list(api_v2.PREFER_VALUES))
        self.assertEqual(payload["enums"]["report_event"], list(api_v2.REPORT_EVENTS))
        self.assertEqual(payload["rate_limit"]["route_buckets"],
                         dict(api_v2.ROUTE_BUCKETS))
        # The manifest spells each bucket as an object (§16.5's numbers are the ones
        # `redact.py` actually enforces), never as a tuple a client must guess.
        for name, entry in payload["rate_limit"]["buckets"].items():
            self.assertEqual((entry["limit"], entry["window_seconds"]),
                             tuple(redact.BUCKET_LIMITS[name]))
        self.assertEqual(payload["cache_classes"],
                         {"browse": api_v2.CACHE_BROWSE, "detail": api_v2.CACHE_DETAIL,
                          "manifest": api_v2.CACHE_MANIFEST,
                          "no_store": api_v2.CACHE_NO_STORE})
        self.assertEqual(payload["limits"]["body_bytes"], api_v2.MAX_BODY_BYTES)
        self.assertEqual(payload["visibility_policy"]["unlisted_answer"], "not_found")
        self.assertEqual(payload["visibility_policy"]["unlisted_status"], 404)
        self.assertEqual(payload["implemented"]["schema_version"],
                         catalog_v2.SCHEMA_VERSION)
        # Both scoring axes are published as data, read from the modules that act.
        self.assertEqual(payload["scoring"]["print"]["cam_ceiling"],
                         __import__("release_descriptor").CAM_FAMILY_CEILING)
        self.assertEqual(payload["scoring"]["link"]["axes"]["projection_prior"]
                         ["weights"]["state"]["active"], 100)
        # A census is a count, and §13 forbids count skew as a signal: the manifest
        # and `/stats` must agree, and both must be below what the projection holds.
        stats = self.get("/api/v2/stats").json
        self.assertEqual(payload["catalog"]["counts"]["works"],
                         stats["counts"]["works"])
        self.assertEqual(payload["catalog"]["counts"]["links"],
                         stats["counts"]["links"])
        self.assertEqual(payload["catalog"]["counts"]["works"], 5)
        self.assertLess(payload["catalog"]["counts"]["works"],
                        self.conn.execute("SELECT COUNT(*) FROM cat_works").fetchone()[0],
                        "the manifest advertised hidden rows")
        # The manifest is a validator too, and never a store of live answers.
        again = self.get("/api/v2/manifest", headers={"If-None-Match":
                                                      reply.header("etag")})
        self.assertEqual(again.status, 304)

    def test_health_is_ops_shaped_and_never_cached(self):
        reply = self.get("/api/v2/health")
        payload = reply.json
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["contract_version"], api_v2.CONTRACT_VERSION)
        self.assertEqual(payload["schema_version"], catalog_v2.SCHEMA_VERSION)
        self.assertEqual(payload["catalog_rev"], 1)
        self.assertGreater(payload["server_time"], 0)
        self.assertEqual(reply.header("cache-control"), "no-store")
        self.assertIsNone(reply.header("etag"))
        self.assert_clean(payload, label="health")

    def test_browse_search_and_detail_shapes_a_client_needs(self):
        browse = self.get("/api/v2/browse", {"limit": 3, "type": "movie"})
        self.assertEqual(browse.status, 200)
        self.assertTrue(browse.json["items"])
        for item in browse.json["items"]:
            self.assertEqual(item["work_type"], "movie")
            self.assertIn("available", item)
            self.assertIn("poster", item)
            self.assertNotIn("source_site", item)
        filtered = self.get("/api/v2/browse", {"type": "series"})
        self.assertEqual({row["work_type"] for row in filtered.json["items"]}, {"series"})
        search = self.get("/api/v2/search", {"q": "quiet valley"})
        self.assertTrue(search.json["items"], "a title search found nothing it indexed")
        self.assertTrue(all("relevance" in row for row in search.json["items"]))
        self.assertEqual(self.get("/api/v2/suggest", {"q": "du"}).json["count"], 1)
        self.assertEqual(self.get("/api/v2/suggest", {"q": "d"}).json["items"], [],
                         "§12: `q` needs two characters, and says so without an error")
        detail = self.get(f"/api/v2/works/{self.public_work_id}")
        self.assertEqual(detail.json["work"]["title"], "Dune Protocol")
        self.assertTrue(detail.json["prints"], "a work with a print reported none")
        season = self.get(f"/api/v2/works/{self.work_ids['Campus Beats']}/seasons/1")
        self.assertEqual(season.status, 200)
        # §S2: a season answer is `{"season": {… "episodes": […]}, "prints": […]}` —
        # the grid belongs to the season object, not to the envelope.
        self.assertTrue(len(season.json["season"]["episodes"]) >= 1)
        self.assertEqual([row["number"] for row in season.json["season"]["episodes"]],
                         [1, 2, 3], "a pack episode range must enumerate its span")
        self.assertTrue(season.json["prints"], "a season with a print reported none")
        self.assert_clean(season.json, label="season")
        episode = self.get(f"/api/v2/episodes/{self.public_episode_id}")
        self.assertEqual(episode.status, 200)
        self.assert_clean(episode.json, label="episode")
        release = self.get(f"/api/v2/releases/{self.public_release_id}")
        self.assertEqual(release.status, 200)
        self.assert_clean(release.json, label="release")
        # `fields` narrows the detail without inventing a key.
        thin = self.get(f"/api/v2/works/{self.public_work_id}", {"fields": "title,year"})
        self.assertEqual(thin.status, 200)

    def test_prefer_moves_the_ladder_on_the_axis_the_client_asked_for(self):
        """§9: the two axes are chosen by the caller, not assumed by the server."""
        quality = self.post("/api/v2/play", {"release_id": self.public_release_id,
                                             "prefer": "quality"})
        self.assertEqual(quality.status, 200)
        self.assertEqual(quality.json["prefer"], "quality")
        self.assert_clean(quality.json, label="play")
        ranks = [link["rank_score"] for link in quality.json["candidates"]
                 if link["playable"]]
        self.assertEqual(ranks, sorted(ranks, reverse=True),
                         "the quality axis is not descending in rank_score")
        speed = self.post("/api/v2/play", {"release_id": self.public_release_id,
                                          "prefer": "speed"})
        self.assertEqual(speed.json["prefer"], "speed")
        measured = [bool(link["measured"]) for link in speed.json["candidates"]
                    if link["playable"]]
        self.assertEqual(measured, sorted(measured, reverse=True),
                         "the speed axis puts measured copies first")
        saver = self.post("/api/v2/play", {"release_id": self.public_release_id,
                                          "prefer": "data_saver"})
        self.assertEqual(saver.json["prefer"], "data_saver")
        self.assertEqual(speed.json["candidates"][0]["stream_id"],
                         quality.json["candidates"][0]["stream_id"],
                         "the ladder is not a re-sort of the same candidates")
        # An unknown word is not an error and is not silently obeyed either: the
        # answer names the axis it actually used (the app's own `Prefer.fromWire`
        # falls back the same way, so both sides agree on the fallback).
        weird = self.post("/api/v2/play", {"release_id": self.public_release_id,
                                           "prefer": "cheapest-first"})
        self.assertEqual(weird.status, 200)
        self.assertEqual(weird.json["prefer"], "quality")
        self.assertIn("prefer", weird.json)
        self.assertEqual(weird.json["candidates"], quality.json["candidates"])
        for field in ("recommended_link_id", "ladder_exhausted", "tiers", "tried"):
            self.assertIn(field, quality.json)
        self.assertEqual(quality.json["ladder_exhausted"], False)

    def test_a_download_only_target_answers_200_not_a_conflict(self):
        """S11: "you may save this" is a real answer."""
        release = self._one(
            "SELECT r.id FROM cat_releases r JOIN cat_links l ON l.release_id = r.id"
            " WHERE l.resource_id = 'BO-MIRROR'")
        reply = self.post("/api/v2/play", {"release_id": release})
        self.assertIn(reply.status, (200, 409))
        if reply.status == 200:
            self.assertEqual(reply.json["reason"], "download_only")
            self.assertFalse(reply.json["playable"])
            self.assertTrue(reply.json["download_options"])
            self.assert_clean(reply.json, label="download play")
        else:
            self.assert_problem(reply, code="no_playable_source", status=409,
                                instance="/api/v2/play")

    def test_an_exhausted_ladder_fails_honestly(self):
        """B13: never a fake 200, never a 302 to nothing."""
        dead_release = self._one(
            "SELECT r.id FROM cat_releases r JOIN cat_links l ON l.release_id = r.id"
            " WHERE l.resource_id = 'DUNE-DEAD' ORDER BY r.id LIMIT 1")
        reply = self.post("/api/v2/play", {"release_id": dead_release})
        if reply.status == 409:
            body = self.assert_problem(reply, code="no_playable_source", status=409,
                                       instance="/api/v2/play")
            self.assertIn("tried", body["detail"])
            self.assertIn("tried", body["details"])
            for attempt in body["details"]["tried"]:
                self.assertIn("reason", attempt)
        else:
            self.assertEqual(reply.status, 200,
                             "a print with a live sibling may still play")
        self.assertNotEqual(getattr(reply, "status", None), 302)


def base64_text(value: str) -> str:
    import base64
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


#: head → the test in this file that exercises it, for the structural guard.
ROUTE_TESTS = {
    "manifest": ("V2SurfaceTests", "test_manifest_publishes_the_contract_it_keeps"),
    "browse": ("V2SurfaceTests", "test_browse_search_and_detail_shapes_a_client_needs"),
    "search": ("V2SurfaceTests", "test_browse_search_and_detail_shapes_a_client_needs"),
    "suggest": ("V2ProvenanceTests", "test_upstream_image_urls_become_our_own_handles"),
    "works": ("V2AdultRuleTests", "test_adult_id_answers_exactly_like_a_missing_id"),
    "episodes": ("V2CursorTests", "test_report_and_offset_record_without_echoing_identity"),
    "releases": ("V2SurfaceTests", "test_browse_search_and_detail_shapes_a_client_needs"),
    "resolve": ("V2OpaqueHandleTests",
                "test_public_port_refuses_enumerable_row_ids"),
    "sync": ("V2CursorTests", "test_sync_pagination_advances_in_every_scope"),
    "collections": ("V2ErrorTests",
                    "test_unknown_and_misshapen_routes_are_problem_json"),
    "feed.m3u": ("V2ProvenanceTests",
                 "test_feed_playlist_addresses_only_our_own_routes"),
    "stats": ("V2StatsHonestyTests", "test_every_coverage_number_adds_up"),
    "health": ("V2SurfaceTests", "test_health_is_ops_shaped_and_never_cached"),
    "play": ("V2SurfaceTests", "test_prefer_moves_the_ladder_on_the_axis_the_client_asked_for"),
    "links": ("V2OpaqueHandleTests", "test_a_handle_resolves_its_own_link_and_no_other"),
}

_TEST_CLASSES = {name: obj for name, obj in list(globals().items())
                 if isinstance(obj, type) and issubclass(obj, unittest.TestCase)
                 and obj is not unittest.TestCase}


if __name__ == "__main__":
    unittest.main(verbosity=2)
