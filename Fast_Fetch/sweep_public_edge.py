#!/usr/bin/env python3
"""Real-data leak sweep — the operator's gate before an API change ships.

`test_redact.py` proves the projection on a planted fixture. This proves it on
the *catalog*: it boots the server against a real database (a snapshot copy, so
the live ledger is never touched), walks a sample of every site in it, and tries
to make the public port say a site name, a hoster name, or an upstream URL.

    python3 -S Fast_Fetch/sweep_public_edge.py --db /path/to/catalog_snapshot.db
    python3 -S Fast_Fetch/sweep_public_edge.py --db … --probe   # resolve some handles

Exit code 0 means: on every sampled post and every public route, no brand-shaped
needle appeared, no foreign URL host appeared, no provenance key appeared, the
operator-only routes were 404, a raw row id was 400, and hidden titles answered
exactly as absent ones. It also means the *operator* port still answers with all
of that — without that positive control, a silent projection could pass this
test while the healing pipeline quietly lost its data.

Stdlib only, loopback only, and deliberately small: this box is one core, so the
JIT resolver (which is network-bound) is probed for a handful of links, not
thousands.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Fast_Fetch"))

#: Hosts a public body is allowed to name: our own server, and the public art
#: CDNs whose URLs we hand out verbatim. Anything else was written by an upstream.
OUR_HOSTS = {"localhost", "127.0.0.1", "www.w3.org", "img.youtube.com",
             "i.ytimg.com", "fonts.googleapis.com", "fonts.gstatic.com"}


class Sweep:
    def __init__(self, public: int, operator: int):
        self.public = public
        self.operator = operator
        self.failures: list[str] = []
        self.notes: list[str] = []
        self.soft: list[str] = []
        self.seen_soft: set[tuple[str, str]] = set()
        self.reported: set[tuple[str, str]] = set()
        self.url_hosts: set[str] = set()
        self.brand_re = re.compile(r"(?!x)x")
        self.plain_re = re.compile(r"(?!x)x")

    # ── reporting ────────────────────────────────────────────────────────────
    def flag(self, text: str) -> None:
        if text not in self.failures:
            self.failures.append(text)

    def report(self, route: str, needle: str, body: str) -> None:
        key = (route, needle.lower())
        if key in self.reported:
            return
        self.reported.add(key)
        pos = body.lower().find(needle.lower())
        window = body[max(0, pos - 90):pos + 90].replace("\n", " ")
        self.failures.append(f"{route}: {needle!r} -> …{window}…")

    def note_plain_word(self, route: str, needle: str, body: str) -> None:
        """A bare English word that some hoster happens to use as its label
        ("drop", "click", "embed") is not a leak on its own — `redact` deliberately
        does not delete those from display text, because an honest label would go
        with them. Collected here for a human to read, never asserted."""
        key = (route, needle.lower())
        if key in self.seen_soft:
            return
        self.seen_soft.add(key)
        pos = body.lower().find(needle.lower())
        self.soft.append(f"{route}: {needle!r} -> "
                         f"…{body[max(0, pos - 70):pos + 70].replace(chr(10), ' ')}…")

    # ── transport ────────────────────────────────────────────────────────────
    @staticmethod
    def _get(port: int, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
        try:
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            return (response.status, dict(response.getheaders()),
                    response.read().decode("utf-8", "replace"))
        except (OSError, http.client.HTTPException) as ex:
            return 0, {}, f"{type(ex).__name__}: {ex}"
        finally:
            conn.close()

    def get(self, port: int, path: str):
        """This sweep is the traffic that trips our own limiter, so a 429 here
        means the route was never looked at — wait it out instead of passing it."""
        status, headers, body = 429, {}, ""
        for attempt in range(4):
            status, headers, body = self._get(port, path)
            if status != 429:
                return status, headers, body
            time.sleep(min(10 * (attempt + 1), 45))
        self.flag(f"still rate-limited after retries: {path}")
        return status, headers, body

    # ── the four questions every route gets asked ────────────────────────────
    def scan(self, path: str, port: int | None = None, expect=(200, 302),
             label="public"):
        port = self.public if port is None else port
        status, _headers, body = self.get(port, path)
        if status not in expect:
            self.flag(f"{label} {path}: status {status}")
            return status, {}, body
        if label == "operator":
            return status, {}, body
        for match in self.brand_re.finditer(body):
            self.report(f"{label} {path}", match.group(0), body)
        for match in self.plain_re.finditer(body):
            self.note_plain_word(path, match.group(0), body)
        for match in re.finditer(r"https?://([A-Za-z0-9._-]+)", body):
            host = match.group(1).lower()
            self.url_hosts.add(host)
            if host not in OUR_HOSTS and not host.startswith("127."):
                self.flag(f"{label} {path}: hands out upstream host {host}")
        import redact
        try:
            keys = redact.provenance_keys(json.loads(body))
        except (json.JSONDecodeError, ValueError):
            return status, {}, body
        if keys:
            self.flag(f"{label} {path}: publishes keys {sorted(set(keys))}")
        return status, {}, body

    def must_be_404(self, path: str, port: int | None = None, why: str = "route"):
        status, _, _ = self.get(self.public if port is None else port, path)
        if status != 404:
            self.flag(f"public answered {why} {path} with {status}")

    # ── vocabulary ───────────────────────────────────────────────────────────
    def harvest(self, conn, redact, db: str, cache: str | None) -> tuple:
        """Every site name and upstream host the ledger recorded, plus redact's own
        vetted vocabulary. Expensive on a multi-gigabyte catalog, so it is cached."""
        if cache and Path(cache).exists():
            data = json.load(open(cache))
            print(f"[i] needles from cache: {len(data['needles'])}")
            return data["sites"], set(data["hosts"]), set(data["needles"])
        sites = [r[0] for r in conn.execute(
            "SELECT DISTINCT source_site FROM posts WHERE source_site IS NOT NULL")]
        hosts = set()
        for col, table in (("final_url", "download_sources"),
                           ("source_url", "download_sources"),
                           ("url", "posts"), ("intermediate_url", "releases"),
                           ("origin_url", "releases")):
            for (value,) in conn.execute(
                    f"SELECT DISTINCT substr({col}, instr({col}, '//') + 2) "
                    f"FROM {table} WHERE {col} LIKE 'http%'"):
                head = str(value or "").split("/")[0].split(":")[0].lower()
                if "." in head:
                    hosts.add(head)
        needles = set(redact.site_needles(db)) | {h.lower() for h in hosts} \
            | {s.lower() for s in sites}
        if cache:
            try:
                json.dump({"sites": sites, "hosts": sorted(hosts),
                           "needles": sorted(needles)}, open(cache, "w"))
            except OSError:
                pass
        return sites, hosts, needles

    def compile_patterns(self, redact, sites, needles) -> None:
        """Two buckets, and the split is redact's own: a token shaped like a brand
        (a dot, a hyphen, a digit, a domain, or a name in the site list) must never
        appear in a public body, so it is asserted. A plain word is only collected."""
        needles = {n for n in needles
                   if n and len(n) >= 4 and n not in redact.GENERIC_TOKENS}
        named = {s.lower() for s in sites}
        brand = {n for n in needles
                 if re.search(r"[-.0-9]", n) or n in named or redact.brand_shaped(n)}
        plain = sorted(needles - brand, key=len, reverse=True)
        self.brand_re = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in
                              sorted(brand, key=len, reverse=True)) + r")\b",
            re.IGNORECASE) if brand else re.compile(r"(?!x)x")
        self.plain_re = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in plain) + r")\b",
            re.IGNORECASE) if plain else re.compile(r"(?!x)x")
        print(f"[i] needles: {len(needles)} asserted {len(brand)}, "
              f"reviewed-by-hand {len(plain)}, sites {len(sites)}")

    # ── the walk ─────────────────────────────────────────────────────────────
    def run(self, db: str, probe: bool, sample_posts: int, secret: str) -> int:
        os.environ["RADD_DB_PATH"] = db
        import redact
        OUR_HOSTS.update(redact.PUBLIC_IMAGE_HOSTS)
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        # A cache beside a read-only snapshot is a luxury; recomputing is slower
        # but the sweep must run either way.
        try:
            self.harvest_cache = db + ".sweep_needles.json"
        except OSError:
            self.harvest_cache = None
        sites, hosts, needles = self.harvest(conn, redact, db, self.harvest_cache)
        self.compile_patterns(redact, sites, needles)

        ids = [r[0] for r in conn.execute(
            "SELECT id FROM posts WHERE is_18_plus IS NULL OR is_18_plus = 0 "
            "ORDER BY RANDOM() LIMIT ?", (sample_posts,))]
        per_site = [r[0] for r in conn.execute(
            "SELECT MAX(id) FROM posts WHERE source_site IS NOT NULL "
            "AND (is_18_plus IS NULL OR is_18_plus = 0) GROUP BY source_site")]
        hidden = [r[0] for r in conn.execute(
            "SELECT id FROM posts WHERE is_18_plus = 1 ORDER BY RANDOM() LIMIT 10")]
        sample = sorted(set(ids + per_site))
        raw_link_row = conn.execute(
            "SELECT s.id FROM download_sources s JOIN releases r ON r.id = s.release_id "
            "JOIN posts p ON p.id = r.post_id WHERE p.is_18_plus = 0 LIMIT 1").fetchone()
        raw_link = raw_link_row[0] if raw_link_row else 1

        env = dict(os.environ, RADD_DB_PATH=db,
                   RADD_INTERNAL_PORT=str(self.operator), RADD_STREAM_SECRET=secret)
        server = subprocess.Popen(
            [sys.executable, "-S", "Fast_Fetch/fast_fetch.py", "serve",
             "--host", "127.0.0.1", "--port", str(self.public)],
            cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)
        try:
            self.wait_until_up()

            for path in ("/api/v1/stats", "/", "/client"):
                self.scan(path)
            for page in (1, 2, 3, 250):
                self.scan(f"/api/v1/posts?limit=100&page={page}")
            for ctype in ("movie", "series"):
                self.scan(f"/api/v1/posts?type={ctype}&limit=100")
            for query in ("2024", "hind", "bollywood", "720p", "480p", "anime"):
                self.scan(f"/api/v1/posts?q={urllib.parse.quote(query)}&limit=100")

            probed = 0
            for index, post_id in enumerate(sample):
                status, _, body = self.scan(f"/api/v1/posts/{post_id}")
                if status != 200:
                    continue
                detail = json.loads(body)["data"]
                for release in detail["releases"]:
                    for source in release["sources"]:
                        if not probe or index > 10 or probed > 25:
                            continue
                        probed += 1
                        self.scan(f"/api/v1/stream"
                                  f"?id={urllib.parse.quote(source['stream_id'])}"
                                  f"&redirect=0", expect=(200, 404))
                for key in ("poster_url", "backdrop_urls"):
                    for ref in re.split(r"[,\s]+", str(detail.get(key) or "")):
                        if "api/v1/art" in ref:
                            parsed = urllib.parse.urlparse(ref)
                            self.scan(f"{parsed.path}?{parsed.query}",
                                      expect=(200, 302, 404))
            self.notes.append(f"probed {probed} handles (the JIT resolver is "
                              f"network-bound, so this stays small on one core)")

            for post_id in sample[:8]:
                self.scan(f"/api/m3u?id={post_id}")
            for post_id in hidden:
                self.scan(f"/api/v1/posts/{post_id}", expect=(404,), label="hidden")
                self.scan(f"/api/m3u?id={post_id}")

            for path in ("/api/data", "/api/sitemap?q=a",
                         "/api/fetch?url=https://example.com", "/api/heal?id=1",
                         "/api/health-check?id=1", "/api/v1/rules"):
                self.must_be_404(path, why="operator route")

            for path in (f"/api/v1/stream?id={raw_link}",
                         f"/api/v1/art?id={raw_link}&k=poster"):
                status, _, _ = self.get(self.public, path)
                if status != 400:
                    self.flag(f"public accepted a bare row id: {path} → {status}")

            # Positive control: if the operator port stopped answering with
            # provenance, this sweep would prove nothing at all.
            _, _, op_posts = self.get(self.operator, "/api/v1/posts?limit=20")
            if "source_site" not in op_posts:
                self.flag("operator /api/v1/posts lost its provenance — "
                          "the sweep proves nothing")
            _, _, op_detail = self.get(self.operator, f"/api/v1/posts/{sample[0]}")
            if "final_url" not in op_detail:
                self.flag("operator post detail no longer carries the raw links")
            _, _, op_rules = self.get(self.operator, "/api/v1/rules")
            if "pixeldrain" not in op_rules:
                self.flag("operator /api/v1/rules is empty")
        finally:
            server.terminate()
            try:
                server.wait(20)
            except subprocess.TimeoutExpired:
                server.kill()
            conn.close()
            if self.harvest_cache and Path(self.harvest_cache).exists():
                Path(self.harvest_cache).unlink()

        print("\n" + "=" * 72)
        for note in self.notes:
            print("[i]", note)
        print(f"[i] hosts named inside public bodies: {sorted(self.url_hosts)}")
        if self.soft:
            print(f"[i] plain-word matches for hand review ({len(self.soft)}):")
            for line in self.soft[:25]:
                print("    ·", line)
        if self.failures:
            print(f"LEAKS: {len(self.failures)}")
            for line in self.failures[:40]:
                print("  x", line)
            return 1
        print(f"OK — the public port named no site, no hoster and no upstream host "
              f"across {len(sample) + 12} sampled posts and every route")
        return 0

    def wait_until_up(self) -> None:
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.public), 1).close()
                socket.create_connection(("127.0.0.1", self.operator), 1).close()
                return
            except OSError:
                time.sleep(0.5)
        raise SystemExit("server did not come up")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True,
                        help="a snapshot of the catalog to project (never the live "
                             "ledger: this opens it read-only but boots a server on it)")
    parser.add_argument("--public", type=int, default=8090)
    parser.add_argument("--operator", type=int, default=8091)
    parser.add_argument("--posts", type=int, default=40,
                        help="random posts to sample on top of one per site")
    parser.add_argument("--probe", action="store_true",
                        help="also resolve a handful of stream handles (network-bound)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"[!] no such database: {args.db}", file=sys.stderr)
        return 2
    sweep = Sweep(args.public, args.operator)
    return sweep.run(args.db, args.probe, args.posts,
                     os.environ.get("RADD_STREAM_SECRET", "sweep-secret-not-production"))


if __name__ == "__main__":
    sys.exit(main())
