#!/usr/bin/env python3
"""End-to-end scenario matrix for the public edge (A–G), over real HTTP.

Every scenario boots the two policies the service ships — `operator=False` and
`operator=True` on ephemeral loopback ports — against a temporary ledger, and
asks the documented question rather than reading the code under test. The
fixture and both servers come from `test_redact.py` (`FixtureMixin` and the
`make_server(...)` pattern in `PublicEdgeHttpTests`); nothing here invents a
second server or touches the production catalog.

    python3 -S Fast_Fetch/test_public_edge_scenarios.py

Scenarios
---------
A. The adult invariant — a flagged post is 404 on both ports, its links never
   play, the playlist carries no entry, and a *typo'd* link id refuses too
   (`redact.link_is_adult` answers True for unknown ids on purpose).
B. The twin leak — one canonical key carried by a flagged and an unflagged row.
   Task #13 landed the key-level law (`inherit_key_adult` inside the write that
   sets the flag, `reconcile_key_adult`/`backfill_adult_key.py` for rows written
   before it), so the scenario asserts that documented lifecycle: a pre-law twin
   is served until the bounded repair, the play route already refuses its link
   (`link_is_adult` asks the work's key), the repair lowers the public total by
   exactly what it flipped, and a flagged re-crawl reconciles the sibling through
   the ingest path. v2's projection folds both copies into one hidden work.
C. Pagination bounds — `?limit=`, `?page=`, non-numeric, negative, huge — on
   v1 posts, v2 browse/search/suggest, and `/api/m3u?id=`. Each answers a
   documented band or our own 4xx, never a 502-class answer. `/api/m3u?id=abc`
   used to raise out of the handler and drop the connection; it now answers the
   detail route's 400 (regression guard).
D. Rate limiting — the bucket keys on `X-Real-IP` (or the last `X-Forwarded-For`
   hop when that header is absent), so a spoofed leftmost XFF cannot mint a
   bucket; over budget is the app's 429. (Behind the shipped nginx an over-limit
   request is answered 503 *before* the app because `limit_req_status` is unset;
   that is host config, documented in docs/API_SURFACE_AUDIT.md, not this app.)
E. Download directness — with `feature_link_shorteners` at its documented 0 and
   a shortener token saved, a free download 302s to the direct media URL with
   `Content-Disposition: attachment`; the shortener is never called.
F. Provenance suppression — no planted site/hoster token and none of
   `redact.PROVENANCE`'s key names survive any public body, including a column
   added to the ledger *after* the code shipped (proved structurally: the value
   is new to the vocabulary, so only an allowlist can keep it in).
G. v1 vs v2 — the same catalog question through both, and every v2 catalog
   route answered by this app on :8080 (the edge's 403 is nginx's `^~ /api/`
   catch-all; the documented install allows only `/api/v2/account`, which the
   last test pins in ORACLE_DEPLOYMENT.md).

Offline and stdlib-only. `RADD_SKIP_LIVE_ENRICH=1` (set by `test_redact`) keeps
ingest off the network; every URL the tests follow is loopback.
"""

from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import admin_panel        # noqa: E402
import catalog_v2         # noqa: E402
import fast_fetch         # noqa: E402
import redact             # noqa: E402
import test_redact        # noqa: E402  (fixture + _NoRedirect, by design)
import viewer             # noqa: E402

SENTINELS = tuple(test_redact.SENTINELS)
DIRECT_URL = "https://media.example.test/film.mp4"
NEW_COLUMN_SENTINEL = "zznewhostergamma"
_UNREACHABLE = (urllib.error.URLError, http.client.RemoteDisconnected,
                ConnectionError)


class ScenarioMatrix(test_redact.FixtureMixin):
    """The whole matrix on one pair of servers and one temporary ledger."""

    # -- servers: the two policies, exactly as `viewer.start_server` builds them #
    @classmethod
    def setUpClass(cls):
        cls.public_server = viewer.make_server("127.0.0.1", 0, operator=False)
        cls.operator_server = viewer.make_server("127.0.0.1", 0, operator=True)
        for server in (cls.public_server, cls.operator_server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.public_port = cls.public_server.server_address[1]
        cls.operator_port = cls.operator_server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for server in (cls.public_server, cls.operator_server):
            server.shutdown()
            server.server_close()

    def setUp(self):
        self.make_ledger()
        redact.limiter._buckets.clear()

    def tearDown(self):
        redact.limiter._buckets.clear()
        super().tearDown()

    # -- transport ---------------------------------------------------------- #
    def request(self, path, port=None, headers=None, follow=False):
        """One loopback request. A dropped connection is reported as status 0 —
        a loud, readable failure instead of a stack trace from the client."""
        port = port or self.public_port
        opener = urllib.request.build_opener() if follow else \
            urllib.request.build_opener(test_redact._NoRedirect)
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     headers=headers or {})
        try:
            with opener.open(req, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()
        except _UNREACHABLE as error:
            return 0, {}, f"connection dropped ({type(error).__name__}: {error})".encode()

    def fetch_json(self, path, port=None, headers=None, expect=200):
        status, headers, body = self.request(path, port, headers)
        self.assertEqual(status, expect, f"{path} → {status}: {body[:300]!r}")
        return json.loads(body), headers

    def handle(self, source_id):
        return redact.mint_token(int(source_id), viewer.signing_secret())

    # -- fixture extensions ------------------------------------------------- #
    def add_direct_post(self):
        """A work whose one source is a static media file — the shape the
        download route is documented to hand out (`test_download_endpoint`)."""
        post_id = fast_fetch.save_scraped_data(test_redact.media(
            "somecdn.site", "https://somecdn.site/movie/ordinary-film/",
            clean_title="Ordinary Film", final_url=DIRECT_URL,
            source_name="Direct Mirror", service="direct"))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE download_sources SET status = 'active', is_temporary = 0,"
                " is_resumable = 1, mime_type = 'video/mp4'"
                " WHERE release_id IN (SELECT id FROM releases WHERE post_id = ?)",
                (post_id,))
        return post_id

    def add_row(self, *, clean_title, key, site, slug, adult=0, year=2024):
        """A second ledger row for a work another row already carries.

        `save_scraped_data` merges same-key payloads into one post, so the
        production shape (442 keys with more than one row, per AGENTS.md) can
        only be reproduced by writing the row directly."""
        url = f"https://{site}.example/{slug}/"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO posts (url, slug, title, clean_title, year,"
                " content_type, source_site, is_18_plus, canonical_key)"
                " VALUES (?, ?, ?, ?, ?, 'movie', ?, ?, ?)",
                (url, slug, f"{clean_title} ({year})", clean_title, year, site,
                 adult, key))
        return cur.lastrowid

    def add_twin(self):
        """The production shape from AGENTS.md: an unflagged second row for a
        work whose other row is flagged (hindilinks4u `4-play_2021`).

        Written directly, i.e. as a row from before the key law existed; the
        documented repair is `reconcile_key_adult` / `backfill_adult_key.py`."""
        key = self.one("SELECT canonical_key FROM posts WHERE id = ?",
                       (self.adult_id,))[0]
        return self.add_row(clean_title="Adult Diary", key=key, site="bolly4u",
                            slug="adult-diary-hindi-download")

    def add_source(self, post_id, *, site="bolly4u", slug="legacy"):
        """One playable link on a post, the shape a pre-law row carried."""
        with sqlite3.connect(self.db_path) as conn:
            release = conn.execute(
                "INSERT INTO releases (post_id, release_title, quality,"
                " intermediate_url, origin_url, source_site)"
                " VALUES (?, 'HD', '720p', ?, ?, ?)",
                (post_id, DIRECT_URL,
                 f"https://{site}.example/{slug}/", site)).lastrowid
            return conn.execute(
                "INSERT INTO download_sources (release_id, source_name, service,"
                " source_url, final_url, status, is_temporary, mime_type)"
                " VALUES (?, 'Direct Mirror', 'direct', ?, ?, 'active', 0,"
                " 'video/mp4')",
                (release, DIRECT_URL, DIRECT_URL)).lastrowid

    def project(self):
        """Rebuild the v2 `cat_*` tables the same way production does."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            catalog_v2.project(conn, rev=1, verbose=False)
            conn.commit()
        finally:
            conn.close()

    def inject_new_column(self, value=NEW_COLUMN_SENTINEL):
        """A column nobody reviewed, carrying a value no vocabulary knows."""
        with sqlite3.connect(self.db_path) as conn:
            for table in ("posts", "releases", "download_sources"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN brand_new_column TEXT")
                conn.execute(f"UPDATE {table} SET brand_new_column = ?", (value,))

    # ------------------------------------------------------------------ #
    # A. the adult invariant
    # ------------------------------------------------------------------ #
    def test_a_a_flagged_post_is_absent_on_both_ports(self):
        for label, port in (("public", self.public_port),
                            ("operator", self.operator_port)):
            status, _, body = self.request(f"/api/v1/posts/{self.adult_id}", port)
            self.assertEqual(status, 404, f"{label} detail: {body[:200]}")
            self.assertNotIn(b"Adult Diary", body)
        listed = self.fetch_json("/api/v1/posts?limit=50")[0]
        self.assertNotIn(self.adult_id, [row["id"] for row in listed["results"]])

    def test_a_flagged_links_never_play_on_either_port(self):
        link = self.source_id(self.adult_id)
        handle = self.handle(link)
        for route in ("stream", "download"):
            for label, port in (("public", self.public_port),
                                ("operator", self.operator_port)):
                status, _, body = self.request(
                    f"/api/v1/{route}?id={handle}", port)
                self.assertEqual(status, 404, f"{label} /api/v1/{route}: {body[:200]}")
                self.assertEqual(json.loads(body),
                                 {"success": False, "error": "not_found"})

    def test_a_a_typoed_link_id_is_refused_like_a_flagged_one(self):
        """A linked id that never existed must not play on either port.

        On the *public* port this is the documented collapse: both routes answer
        404, and the error is one of the two public names (`no_playable_source`
        from the stream redirector, `not_found` from download). On the *operator*
        port `full=True` passes the resolver payload through raw, so the status
        and wording differ (stream answers 404 with the resolver's own sentence,
        download answers 200 with `success: false`) — the invariant there is that
        no playable answer comes back: no 302/Location, `success` is false.
        """
        typo = self.handle(999999)
        for route in ("stream", "download"):
            status, headers, body = self.request(
                f"/api/v1/{route}?id={typo}", self.public_port)
            self.assertEqual(status, 404, f"public /api/v1/{route} → {body[:200]}")
            payload = json.loads(body)
            self.assertIs(payload["success"], False)
            self.assertIn(payload["error"], ("not_found", "no_playable_source"))

            status, headers, body = self.request(
                f"/api/v1/{route}?id={typo}", self.operator_port)
            self.assertNotIn("Location", {k.title(): v for k, v in headers.items()},
                             f"operator /api/v1/{route} redirected a typo'd id")
            payload = json.loads(body)
            self.assertIs(payload["success"], False,
                          f"operator /api/v1/{route} → {status} {body[:200]}")

    def test_a_link_is_adult_answers_true_for_an_unknown_id(self):
        """Regression guard for the documented contract.

        `redact.link_is_adult` documents (and AGENTS.md repeats) that "an
        unknown link answers True too, so a vanished row, a typo and a flagged
        title are indistinguishable". It used to end `return bool(row and
        row[0])`, i.e. False for an absent row, and the guard only held because
        the resolver happened to 404 afterwards. Absence now answers True, and
        the key roll-up means a legacy twin's link answers for the work.
        """
        self.assertTrue(redact.link_is_adult(999999, self.db_path),
                        "an unknown link id must answer True, not False")

    def test_a_the_playlist_carries_no_playable_entry_for_a_flagged_work(self):
        """On the app port the playlist is empty, exactly like an absent id. At
        the edge the route is not on nginx's allowlist, so it never arrives."""
        for port in (self.public_port, self.operator_port):
            status, _, body = self.request(f"/api/m3u?id={self.adult_id}", port)
            self.assertEqual(status, 200, body[:200])
            self.assertNotIn(b"#EXTINF", body)
            self.assertNotIn(b"/api/v1/stream", body)

    def test_a_a_safe_handle_still_plays(self):
        """The deny must be the adult rule, not a broken redirector."""
        handle = self.handle(self.source_id(self.post_id))
        status, headers, _ = self.request(f"/api/v1/stream?id={handle}")
        self.assertIn(status, (200, 302))
        if status == 302:
            self.assertTrue(headers["Location"].startswith("https://pixeldrain.com/"))

    # ------------------------------------------------------------------ #
    # B. the twin leak (task #13, landed at 20f5fcc)
    # ------------------------------------------------------------------ #
    def test_b_a_legacy_twin_is_closed_by_the_documented_repair(self):
        """AGENTS.md: rows written before the key law stay public until
        `backfill_adult_key.py` (here its `reconcile_key_adult` core) closes
        them. The play route is already safe before the repair, because
        `link_is_adult` answers for the work's key, not the one row."""
        twin = self.add_twin()
        link = self.add_source(twin)
        key = self.one("SELECT canonical_key FROM posts WHERE id = ?",
                       (self.adult_id,))[0]

        with fast_fetch.get_db() as conn:
            exposures = dict(fast_fetch.adult_key_exposures(conn))
        self.assertEqual(exposures.get(key), 1,
                         "the audit must see exactly the exposed row")

        before = self.fetch_json("/api/v1/posts?limit=50")[0]["total"]
        self.assertEqual(before, 2,
                         "the unflagged legacy twin is the served copy until repaired")
        self.assertTrue(redact.link_is_adult(link, self.db_path),
                        "a link on the twin must be adult by the work's key")
        status, _, body = self.request(f"/api/v1/stream?id={self.handle(link)}")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body),
                         {"success": False, "error": "not_found"})

        flipped = fast_fetch.reconcile_key_adult(self.db_path)
        self.assertEqual(flipped, 1)
        after = self.fetch_json("/api/v1/posts?limit=50")[0]["total"]
        self.assertEqual(before - after, flipped,
                         "the repair lowers the public total by exactly what it flipped")

        listed = self.fetch_json("/api/v1/posts?q=Adult+Diary&limit=50")[0]
        self.assertEqual(listed["total"], 0)
        self.assertNotIn(twin, [row["id"] for row in listed["results"]])
        status, _, _ = self.request(f"/api/v1/posts/{twin}")
        self.assertEqual(status, 404, "the repaired twin must stop answering")
        with fast_fetch.get_db() as conn:
            flags = {row["id"]: row["is_18_plus"] for row in
                     conn.execute("SELECT id, is_18_plus FROM posts")}
        self.assertEqual((flags[self.adult_id], flags[twin]), (1, 1))

    def test_b_a_flagged_write_reconciles_the_sibling_through_the_ingest_path(self):
        """Task #13's actual fix: the write that sets the flag flips every row
        that already carries the key, so a re-crawl closes a pre-law twin with
        no audit or repair step."""
        twin = self.add_twin()
        fast_fetch.save_scraped_data(test_redact.media(
            "gamerxyt", "https://gamerxyt.example/adult-title/",
            clean_title="Adult Diary", source_name="Gamerxyt Mirror",
            service="gamerxyt", final_url="https://gamerxyt.click/f/9", adult=1))
        with fast_fetch.get_db() as conn:
            flags = {row["id"]: row["is_18_plus"] for row in
                     conn.execute("SELECT id, is_18_plus FROM posts")}
        self.assertEqual((flags[self.adult_id], flags[twin]), (1, 1))
        listed = self.fetch_json("/api/v1/posts?q=Adult+Diary&limit=50")[0]
        self.assertEqual(listed["total"], 0)
        status, _, _ = self.request(f"/api/v1/posts/{twin}")
        self.assertEqual(status, 404)

    def test_b_the_v2_projection_folds_both_copies_into_one_hidden_work(self):
        """The projection uses the same any-row rule, so the reconciled key is
        one hidden work, not two answers."""
        self.add_twin()
        fast_fetch.reconcile_key_adult(self.db_path)
        self.project()
        payload = self.fetch_json("/api/v2/search?q=Adult+Diary")[0]
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["total_estimate"], 0)
        with fast_fetch.get_db() as conn:
            hidden = conn.execute(
                "SELECT COUNT(*) FROM cat_works WHERE is_18_plus = 1"
            ).fetchone()[0]
        self.assertEqual(hidden, 1, "both copies fold into one hidden work")

    # ------------------------------------------------------------------ #
    # C. pagination bounds
    # ------------------------------------------------------------------ #
    def test_c_v1_posts_answers_the_documented_bands(self):
        for raw, want in (("abc", 20), ("", 20), ("1e3", 20), ("-5", 1),
                          ("0", 1), ("100000", 100), ("3", 3)):
            with self.subTest(limit=raw):
                path = "/api/v1/posts?limit=" + urllib.parse.quote(raw)
                payload = self.fetch_json(path)[0]
                self.assertEqual(payload["limit"], want, path)
                self.assertGreaterEqual(payload["page"], 1)
        for raw, want in (("abc", 1), ("", 1), ("-5", 1), ("0", 1),
                          ("999999999999999999999", 1_000_000), ("2", 2)):
            with self.subTest(page=raw):
                path = "/api/v1/posts?page=" + urllib.parse.quote(raw)
                payload = self.fetch_json(path)[0]
                self.assertEqual(payload["page"], want, path)

    def test_c_v2_listings_answer_the_documented_bands(self):
        self.project()
        # In v2, limit=0 is interpreted as "absent" (`_int_or_none(0) or
        # DEFAULT_LIMIT`), so it answers the documented default of 24, unlike
        # v1 where the floor is 1. Both are defaults, not 502s.
        for raw, want in (("abc", 24), ("", 24), ("-5", 1), ("0", 24),
                          ("999999", 100)):
            with self.subTest(route="browse", limit=raw):
                payload = self.fetch_json(
                    "/api/v2/browse?limit=" + urllib.parse.quote(raw))[0]
                self.assertEqual(payload["limit"], want)
            with self.subTest(route="search", limit=raw):
                payload = self.fetch_json(
                    "/api/v2/search?q=example&limit="
                    + urllib.parse.quote(raw))[0]
                self.assertEqual(payload["limit"], want)
        for raw in ("abc", "", "-5", "999999"):
            with self.subTest(route="suggest", limit=raw):
                status, _, body = self.request(
                    "/api/v2/suggest?q=ex&limit=" + urllib.parse.quote(raw))
                self.assertEqual(status, 200, body[:200])
        status, _, body = self.request("/api/v1/search/by-media?q=Example&limit=abc")
        self.assertEqual(status, 200, body[:200])

    def test_c_a_bad_cursor_is_a_400_problem_not_a_crash(self):
        self.project()
        for raw in ("not-a-cursor", "%%%", "0"):
            with self.subTest(cursor=raw):
                status, headers, body = self.request(
                    "/api/v2/browse?cursor=" + urllib.parse.quote(raw))
                self.assertEqual(status, 400, body[:300])
                self.assertIn("problem+json", headers.get("Content-Type", ""))
                self.assertEqual(json.loads(body)["code"], "cursor_invalid")

    def test_c_a_non_numeric_m3u_id_must_not_drop_the_connection(self):
        """Regression guard for the class `bounded_int` exists to stop.

        `viewer.bounded_int` documents that a bare `int()` on caller text raises
        out of the handler and the edge answers 502. `/api/m3u` used to cast its
        `id` with one, so `?id=abc` closed the socket with no response at all.
        The route now answers the same 400 as the detail route's invalid id;
        either our own 4xx or an empty playlist is acceptable, never a drop.
        """
        for raw in ("abc", "1.5", "  ", "9e9"):
            with self.subTest(id=raw):
                status, _, body = self.request(
                    "/api/m3u?id=" + urllib.parse.quote(raw))
                self.assertIn(status, (200, 400),
                              f"/api/m3u?id={raw!r} → {body[:200]!r}")

    # ------------------------------------------------------------------ #
    # D. rate limiting
    # ------------------------------------------------------------------ #
    def test_d_a_spoofed_forwarded_for_does_not_mint_a_bucket(self):
        budget = redact.BUCKET_LIMITS["play"][0]
        real_ip = "203.0.113.7"
        seen = []
        for i in range(budget):
            status, headers, _ = self.request(
                "/api/m3u?id=0",
                headers={"X-Real-IP": real_ip,
                         "X-Forwarded-For": f"10.0.0.{i % 250}, 198.51.100.1"})
            self.assertEqual(status, 200, f"request {i} was throttled early")
            seen.append(int(headers["RateLimit-Remaining"]))
        self.assertEqual(seen[:2], [budget - 1, budget - 2],
                         "spoofed leftmost XFF must not reset the budget")
        status, headers, body = self.request(
            "/api/m3u?id=0",
            headers={"X-Real-IP": real_ip, "X-Forwarded-For": "10.9.9.9"})
        self.assertEqual(status, 429, body[:200])
        self.assertEqual(json.loads(body)["error"], "rate_limited")
        self.assertGreaterEqual(int(headers["Retry-After"]), 1)
        # A different address our edge set is a different bucket.
        status, headers, _ = self.request(
            "/api/m3u?id=0", headers={"X-Real-IP": "198.51.100.4"})
        self.assertEqual(status, 200)
        self.assertEqual(int(headers["RateLimit-Remaining"]), budget - 1)

    def test_d_without_real_ip_the_last_forwarded_hop_is_the_key(self):
        """nginx appends `$proxy_add_x_forwarded_for`, so the hop its peer wrote
        is the last entry; the first is whatever the caller typed."""
        _, first, _ = self.request(
            "/api/m3u?id=0", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"})
        _, second, _ = self.request(
            "/api/m3u?id=0", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.9"})
        self.assertEqual(int(second["RateLimit-Remaining"]),
                         int(first["RateLimit-Remaining"]) - 1,
                         "two spoofed leftmost entries shared one bucket")
        _, other, _ = self.request(
            "/api/m3u?id=0", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.10"})
        self.assertEqual(int(other["RateLimit-Remaining"]),
                         redact.BUCKET_LIMITS["play"][0] - 1,
                         "a different appended hop is a different client")

    # ------------------------------------------------------------------ #
    # E. download directness
    # ------------------------------------------------------------------ #
    def test_e_the_retired_shortener_never_detours_a_free_download(self):
        post_id = self.add_direct_post()
        link = self.source_id(post_id)
        with sqlite3.connect(self.db_path) as conn:
            admin_panel._ensure_monetization(conn)
            conn.execute("UPDATE app_remote_config SET shrinkme_api_token = ?"
                         " WHERE id = 1", ("shrinkme-token",))
            flag = conn.execute("SELECT feature_link_shorteners"
                                " FROM app_remote_config WHERE id = 1").fetchone()[0]
            targets = admin_panel.shortener_targets(conn)
        self.assertEqual(int(flag or 0), 0, "the shipped flag is documented as 0")
        self.assertEqual(targets, [], "a saved token is not consent to detour")

        with mock.patch.object(viewer, "call_shortener",
                               side_effect=AssertionError("shortener was called")):
            status, headers, _ = self.request(f"/api/v1/download?id={self.handle(link)}")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], DIRECT_URL)
        self.assertEqual(headers["Cache-Control"], "no-store")
        disposition = headers.get("Content-Disposition", "")
        self.assertTrue(disposition.startswith("attachment;"), disposition)
        self.assertTrue(disposition.rstrip('"').endswith(".mp4"), disposition)

        status, _, body = self.request(
            f"/api/v1/download?id={self.handle(link)}&redirect=0")
        self.assertEqual(status, 200)
        self.assertNotIn(b"media.example.test", body)
        self.assertNotIn(b"somecdn.site", body.lower())

    # ------------------------------------------------------------------ #
    # F. provenance suppression
    # ------------------------------------------------------------------ #
    def public_bodies(self, post_id, link):
        """Every public body a client can reach, with the shape it comes in."""
        handle = self.handle(link)
        return [
            ("/", "/", "html"),
            ("posts list", "/api/v1/posts?limit=50", "json"),
            ("post detail", f"/api/v1/posts/{post_id}", "json"),
            ("stream descriptor", f"/api/v1/stream?id={handle}&redirect=0", "json"),
            ("download descriptor", f"/api/v1/download?id={handle}&redirect=0", "json"),
            ("playlist", f"/api/m3u?id={post_id}", "text"),
            ("stats", "/api/v1/stats", "json"),
            ("by-media", "/api/v1/search/by-media?q=Example", "json"),
            ("v2 browse", "/api/v2/browse", "json"),
            ("v2 search", "/api/v2/search?q=Example", "json"),
            ("v2 suggest", "/api/v2/suggest?q=Ex", "json"),
        ]

    def assert_body_is_clean(self, label, kind, body):
        text = body.decode("utf-8", "replace")
        for needle in SENTINELS + (NEW_COLUMN_SENTINEL,):
            self.assertNotIn(needle, text.lower(),
                             f"{label} publishes the provenance token {needle!r}")
        if kind == "json":
            payload = json.loads(body)
            self.assertEqual(redact.provenance_keys(payload), [],
                             f"{label} publishes a provenance key")
            self.assertEqual(redact.is_clean(payload), [],
                             f"{label} leaks a provenance value")

    def test_f_no_provenance_survives_any_public_body(self):
        post_id = self.add_direct_post()
        self.project()
        link = self.source_id(post_id)
        for label, path, kind in self.public_bodies(post_id, link):
            status, _, body = self.request(path)
            self.assertEqual(status, 200, f"{label} → {status}: {body[:200]}")
            self.assert_body_is_clean(label, kind, body)

    def test_f_a_column_added_later_is_invisible_by_construction(self):
        """The allowlist, not the vocabulary: the value below is in no needle
        list, so its absence means a reviewed view denied it."""
        post_id = self.add_direct_post()
        self.inject_new_column()
        self.project()
        link = self.source_id(post_id)
        for label, path, kind in self.public_bodies(post_id, link):
            status, _, body = self.request(path)
            self.assertEqual(status, 200, f"{label} → {status}: {body[:200]}")
            self.assert_body_is_clean(label, kind, body)

    # ------------------------------------------------------------------ #
    # G. v1 vs v2
    # ------------------------------------------------------------------ #
    def test_g_v1_and_v2_answer_the_same_catalog_question(self):
        """v1 answers ledger rows; v2 answers works. For a work carried by two
        rows the two surfaces differ in *count* and agree in *identity*, and
        both exclude the flagged work."""
        extra = self.add_row(clean_title="Example Film", key="example-film_2024",
                             site="bolly4u", slug="example-film-print")
        self.project()
        v1 = self.fetch_json("/api/v1/posts?q=Example+Film&limit=50")[0]
        v2 = self.fetch_json("/api/v2/search?q=Example+Film")[0]
        keys = {self.one("SELECT canonical_key FROM posts WHERE id = ?", (pid,))[0]
                for pid in (self.post_id, extra)}
        self.assertEqual(len(keys), 1, "the fixture is one work on two rows")
        self.assertEqual(v1["total"], 2, "v1 lists one row per page")
        self.assertEqual({row["clean_title"] for row in v1["results"]},
                         {"Example Film"})
        self.assertEqual([item["title"] for item in v2["items"]], ["Example Film"])
        self.assertEqual(v2["total_estimate"], 1, "v2 lists one entry per work")
        self.assertGreaterEqual(v2["items"][0]["site_count"], 2,
                                "both ledger rows are attributed to the work")
        # Neither surface names the flagged work.
        self.assertNotIn("Adult Diary", json.dumps(v1))
        self.assertNotIn("Adult Diary", json.dumps(v2))

    def test_g_every_v2_catalog_route_answers_on_the_app_port(self):
        """403 is the edge's job (`^~ /api/`); the app must answer here, or the
        allowlist could not ever expose it. `/api/data` is the in-app analogue of
        an edge refusal: an operator route the public port 404s."""
        self.project()
        browse = self.fetch_json("/api/v2/browse")[0]
        work_id = browse["items"][0]["id"]
        routes = ("/api/v2/manifest", "/api/v2/browse", "/api/v2/search?q=Example",
                  "/api/v2/suggest?q=Ex", "/api/v2/stats", "/api/v2/health",
                  f"/api/v2/works/{work_id}",
                  f"/api/v2/feed.m3u?work_id={work_id}")
        for path in routes:
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 200, f"{path} → {status}: {body[:200]}")
        for path in ("/api/v2/episodes/999999", "/api/v2/releases/999999"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 404, f"{path} → {status}")
                self.assertIn("problem+json", headers.get("Content-Type", ""))
                self.assertEqual(json.loads(body)["code"], "not_found")
        status, _, _ = self.request("/api/data")
        self.assertEqual(status, 404, "the bulk dump stays operator-only")

    def test_g_the_documented_edge_allows_only_account_under_api_v2(self):
        """Documentation-level, because nginx is not part of this test process:
        the recorded install is deny-by-default with one v2 allowlist."""
        doc = (Path(__file__).resolve().parent.parent / "ORACLE_DEPLOYMENT.md")
        text = doc.read_text(encoding="utf-8")
        installed = text.split("What is actually installed", 1)[1].split(
            "```nginx", 1)[0]
        self.assertIn("^~ /api/v2/account", installed,
                      "the only v2 route the edge allows is the account surface")
        self.assertIn("location ^~ /api/ { return 403; }", installed,
                      "every other /api/ path is refused at the edge")
        self.assertIn("a `^~ /api/v2/account` block", installed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
