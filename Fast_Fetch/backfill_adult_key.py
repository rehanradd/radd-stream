#!/usr/bin/env python3
"""Reconcile `posts.is_18_plus` across rows that share one work identity, and report
what that law still cannot reach.

Why this file exists: the adult rule (`redact.adult_clause`) is applied per **row**,
while a work's identity is per **key**. `save_scraped_data()` folded the flag with
`is_18_plus = MAX(is_18_plus, ?)` on the single row it touched, so a `canonical_key`
that already carried several rows never reconciled. Measured in production: 442 keys
hold both a flagged row and an unflagged one, and **455 unflagged rows are therefore
publicly served while their sibling is hidden** — one film, two addresses, and the
public list answers for the one nobody flagged.

Two steps in one file, because the flag has two homes, exactly like
`backfill_animated_flag.py`:

* the **ledger** (`posts.is_18_plus`) — what `/api/v1/posts` filters on;
* the **projection** (`cat_works.is_18_plus`) — what the v2 API and the app filter on.

The ledger step is `fast_fetch.inherit_key_adult()`, one bounded statement per key,
each resolved by `idx_posts_canonical_key` rather than by scanning the table — the
same rule the ingest path now runs, so the repair and the law cannot disagree.

The projection step reconciles the second home without a rebuild: a full
`catalog_v2.project()` of this catalog is hours of one CPU, and `cat_work_sites`
already keeps every post folded into its work, so the roll-up column can be updated
from the projection's own rows. It is the same `any()` rule the projector applies.
It then **deletes the adult-excluded counters** `/api/v1/stats` reads: those stamps
were taken before the flip, and `_get_cached_stats()` treats a missing stamp as
"count it live" rather than publishing a stale public number. That invalidation is
the honest half of this shortcut.

Read-only by default. The ledger fold is **agreement-gated** since order #60: a key folds
only when every row it would flip corroborates a flagged sibling by title, with no
derivable year contradicting it. The
43-row hazard measurement (crown, `CROWN_ADULT_MEASUREMENT.md` §3) showed a literal
`MAX(is_18_plus)` per key hides legitimate works when the adult row's own `canonical_key`
contradicts its own title — `100-bullets_2016` holding public "100 Bullets" beside flagged
"Frank Phoenix UNRATED" is two works under one wrong key, not one work filed twice. The
gate refuses those keys; `--apply-all` keeps the old ungated fold as an explicit, printed
legacy path.

The residual it used to leave unwritten — a work flagged on one
site and served by another under a *different* key — is reachable without re-keying
anything, by grouping on `(clean_title, year)` instead of `canonical_key`. It must be
reached only with `--corroborate`, because propagation multiplies one row's verdict across
its siblings and a stored flag is not always anybody's evidence: measured on the live
catalog 2026-10-30 (`--audit`), 10,816 of 15,068 flags cannot be reproduced by
`is_adult_title()` at all, and the works they hide are mostly mainstream. Folding across
those would hide 3,490 further rows; `--corroborate` hides the 12 that stand on
reproducible evidence.

Do not read `--apply-all` as safe merely because it is the older shape. It is the printed
un-gated legacy fold: it propagates asserted-only flags too, one key at a time, over every
collision the gate would have refused; `--audit` is what tells you how much of a catalog is
in that asserted-only state. Re-keying stored
rows stays out of scope: `find_existing_post` raises once a `canonical_key` matches more
than one record, so rewriting 150k keys into the title+year scheme would put thousands of
works over that threshold and break ingest.

    python3 -S Fast_Fetch/backfill_adult_key.py <db.path>                        # report (+gate split)
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --audit                 # provenance
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --corroborate           # report
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --corroborate --apply   # fold
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --corroborate --undo    # reverse it
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --apply                # ledger, agree-gated
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --apply-all            # UN-GATED legacy fold
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --apply --projection   # + cat_*/stats
    python3 -S Fast_Fetch/backfill_adult_key.py <db.path> --undo                 # reverse the key fold
                                                                                  # (falls back to the
                                                                                  # corroborated undo)

Stdlib only. Never run it while a projection is reading the same database.
"""
from __future__ import annotations

import argparse
import html
import re
import sqlite3
import sys
import time
from pathlib import Path

import fast_fetch
import redact

#: The keys that hold both a flagged row and an unflagged one, with the number of
#: exposed (unflagged) rows under each. `unknown` is excluded: it is the shared bucket
#: every titleless payload lands in, not one work, and propagating from it would hide
#: unrelated titles on the strength of one bad page.
EXPOSED_KEYS_SQL = """
    SELECT canonical_key,
           SUM(CASE WHEN COALESCE(is_18_plus, 0) = 0 THEN 1 ELSE 0 END) AS exposed
      FROM posts
     WHERE canonical_key IS NOT NULL AND canonical_key <> '' AND canonical_key <> 'unknown'
     GROUP BY canonical_key
    HAVING MAX(COALESCE(is_18_plus, 0)) = 1
       AND MIN(COALESCE(is_18_plus, 0)) = 0
     ORDER BY exposed DESC
"""

PUBLIC_TOTAL_SQL = f"SELECT COUNT(*) FROM posts WHERE {redact.adult_clause('posts')}"

#: A work the projection hides while a ledger row folded into it is still public —
#: flagged on one site, served under another key. Read-only evidence for the residual.
#: `DISTINCT p.id` because one post can be folded through several pages, and the
#: number being reported is rows a caller can read, not join pairs.
RESIDUAL_SQL = """
    SELECT COUNT(DISTINCT p.id) FROM cat_works w
      JOIN cat_work_sites s ON s.work_id = w.id
      JOIN posts p ON p.id = s.post_id
     WHERE w.is_18_plus = 1 AND COALESCE(p.is_18_plus, 0) = 0
"""

#: The same `any()` roll-up the projector applies, reached through the projection's
#: own work→post table.
PROJECTION_FLAG_SQL = """
    UPDATE cat_works SET is_18_plus = 1
     WHERE is_18_plus = 0
       AND EXISTS (SELECT 1 FROM cat_work_sites s JOIN posts p ON p.id = s.post_id
                   WHERE s.work_id = cat_works.id AND COALESCE(p.is_18_plus, 0) = 1)
"""

#: Every adult-excluded counter `/api/v1/stats` publishes. A flag flip invalidates all
#: of them at once, and the endpoint's all-or-nothing stamp rule turns that into a
#: live recount instead of a stale public number.
SAFE_STAMP_KEYS = ("works_safe", "adult_works", "releases_safe", "links_safe",
                   "links_active_safe", "links_resumable_safe", "links_temporary_safe",
                   "links_by_state_safe")

# ───────────────────────────── the agreement gate (order #60) ─────────────────────────
# A key may fold only when every exposed row under it *corroborates* a flagged sibling:
# the row's own title must name the same work as the sibling's, and no derivable year
# may contradict. Title alone is not identity ("Dom" 2021 and "Dom" 2024 are two films);
# year alone is not identity ("Death Race" 2000 vs "Death Race 2000" 1975). A year that
# is PRESENT on both sides and different quarantines; a year nobody recorded is silence,
# not contradiction — the `year` column is empty on 269 of the 407 exposed rows, so
# requiring a present year would quarantine the very reconciliation AGENTS.md prescribes. The quarantine bias applies to evidence that
# CONTRADICTS, not to evidence that is absent — and a row with no title at all is
# refused outright, because it corroborates nothing. The bias direction is deliberate:
# a false quarantine leaves a row public for a human; a false agree hides a legitimate
# work on a mis-keyed sibling's verdict. That is the 43-row hazard of
# CROWN_ADULT_MEASUREMENT.md §3, encoded as a refusal.

#: Scraper distribution vocabulary that says nothing about work identity. Kept short and
#: named: every entry must be a tag a release adds, never a word that can be part of the
#: work's name ("season" and "part" are work-bearing and deliberately absent; digits stay too, so
#: "Death Race 2000" ≠ "Death Race").
BOILERPLATE_TOKENS = frozenset({
    "dual", "audio", "hindi", "english", "tamil", "telugu", "dubbed", "dub",
    "org", "line", "orgline", "full", "movie", "hd", "esubs", "subs", "subtitles",
    "uncut", "unrated", "x264", "x265", "hevc", "webrip", "web", "dl", "bluray",
    "hdrip", "dvdrip", "ts", "cam",
})

_PUA_RE = re.compile(r"[\ue000-\uf8ff]")
_YEAR_IN_PAREN_RE = re.compile(r"[\[\(](?:19|20)\d{2}[\]\)]")
_QUALITY_RE = re.compile(r"\b(?:480p|720p|1080p|2160p|4k|uhd)\b")
_NONWORD_RE = re.compile(r"[^a-z0-9 ]+")


def title_tokens(text) -> frozenset:
    """Normalised identity tokens of one title string; empty set when nothing remains."""
    t = html.unescape(str(text or "")).lower()
    t = _PUA_RE.sub(" ", t)
    t = _YEAR_IN_PAREN_RE.sub(" ", t)
    t = _QUALITY_RE.sub(" ", t)
    t = t.replace("&", " and ")
    t = _NONWORD_RE.sub(" ", t)
    return frozenset(w for w in t.split() if w not in BOILERPLATE_TOKENS)


def _edit_distance_le_one(a: str, b: str) -> bool:
    """Cheap ≤1 check (substitution, one insert/delete) — the typo tolerance for pairs
    like schor/chor, adhigaram/adhigaaram. Returns False for anything beyond one edit."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    long_s, short_s = (a, b) if la > lb else (b, a)
    i = j = skipped = 0
    while i < len(long_s) and j < len(short_s):
        if long_s[i] != short_s[j]:
            skipped += 1
            if skipped > 1:
                return False
            i += 1
        else:
            i += 1
            j += 1
    return True


def titles_corroborate(a_tokens: frozenset, b_tokens: frozenset) -> bool:
    """True when two token sets name one work: exact, compact ("Rangi Taranga" =
    "RangiTaranga"), or one-typo apart with equal token counts. A subset is NOT an
    agreement — "Death Race" ⊂ "Death Race 2000" is the collision the year rule exists
    to catch, and dropping the subset rule is what keeps mis-keyed siblings out."""
    if not a_tokens or not b_tokens:
        return False
    if a_tokens == b_tokens:
        return True
    if "".join(sorted(a_tokens)) == "".join(sorted(b_tokens)):
        return True
    if len(a_tokens) != len(b_tokens):
        return False
    ta, tb = sorted(a_tokens), sorted(b_tokens)
    diff = [x for x, y in zip(ta, tb) if x != y]
    if len(diff) != 1:
        return False
    i = ta.index(diff[0])
    return _edit_distance_le_one(ta[i], tb[i])


def row_year(row) -> str:
    y = str(row["year"] or "").strip()
    return y if y.isdigit() else ""


_YEAR_IN_TEXT_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def derivable_year(row) -> str:
    """The year this row claims, or "" when it claims none.

    The `year` column first; then the LAST four-digit 19xx/20xx in the row's own title
    (last, because a scraper writes "Foo (2019) Dual Audio 720p" and the trailing
    release-year is the one that survives boilerplate stripping). Empty is silence, not
    evidence: most exposed rows in this catalog carry no year at all, and demanding one
    would quarantine the reconciliation AGENTS.md prescribes.
    """
    y = row_year(row)
    if y:
        return y
    raw = str(row["clean_title"] or "") + " " + str(row["title"] or "")
    found = _YEAR_IN_TEXT_RE.findall(raw)
    return found[-1] if found else ""


def title_agrees(a, b) -> bool:
    """Row-level corroboration (the order's named, importable gate): same normalised
    title, and no derivable year that contradicts. `clean_title` first, `title` fallback;
    a row with neither can corroborate nothing and disagrees with everything."""
    return titles_agree_with_reason(a, b)[0]


def titles_agree_with_reason(a, b) -> tuple[bool, str]:
    """`title_agrees` with the reason, so a refusal is auditable instead of mysterious.

    Reasons: `agree`, `no_title`, `title_disagree`, `year_drift` — the four labels the
    report prints and the suite pins.
    """
    ta = title_tokens(a["clean_title"] or a["title"])
    tb = title_tokens(b["clean_title"] or b["title"])
    if not ta or not tb:
        return False, "no_title"
    if not titles_corroborate(ta, tb):
        return False, "title_disagree"
    ya, yb = derivable_year(a), derivable_year(b)
    if ya and yb and ya != yb:
        return False, "year_drift"
    return True, "agree"


#: One row per exposed sibling the gate folded, with the pre-state needed to restore it
#: byte-exactly (NULL and 0 are different stored values; `prior IS NOT 1` covers both).
KEY_FOLD_JOURNAL_DDL = """
CREATE TABLE IF NOT EXISTS adult_key_fold_journal (
    post_id INTEGER PRIMARY KEY,
    canonical_key TEXT NOT NULL,
    prior_is_18_plus INTEGER,
    source_post_id INTEGER,
    evidence TEXT,
    decided_at REAL NOT NULL
)
"""

#: The columns the gate reads — one bounded scan, no regex against the whole ledger.
GATE_FIELDS = ("id", "title", "clean_title", "year", "canonical_key", "is_18_plus")


def classify_exposures(conn) -> dict:
    """Split every exposed row under an exposure key into agree / quarantine, per key.

    Read-only, one grouped pass. A key folds only when EVERY exposed row under it
    corroborates SOME flagged sibling (`all-rows-or-nothing`, because `inherit_key_adult`
    semantics are per-key: a half-folded key is not a thing this law writes).
    Returns {"exposed_keys", "exposed_rows", "agree_keys", "quarantine_keys",
    "agree_rows", "quarantine_rows", "verdicts": {key: [row verdicts]},
    "fold_targets": [(post_id, key, source_post_id, evidence)]}.
    """
    rows = conn.execute(
        "SELECT %s FROM posts"
        " WHERE canonical_key IS NOT NULL AND canonical_key <> '' AND canonical_key <> 'unknown'"
        % ", ".join(GATE_FIELDS)).fetchall()
    buckets: dict = {}
    for row in rows:
        buckets.setdefault(str(row["canonical_key"]).strip().lower(), []).append(row)

    verdicts: dict = {}
    agree_keys: list = []
    quarantine_keys: list = []
    targets: list = []
    agree_rows = quarantine_rows = exposed_rows = 0
    for key, members in sorted(buckets.items()):
        flagged = [r for r in members if int(r["is_18_plus"] or 0) == 1]
        exposed = [r for r in members if int(r["is_18_plus"] or 0) == 0]
        if not flagged or not exposed:
            continue
        exposed_rows += len(exposed)
        key_rows = []
        key_targets = []
        key_clean = True
        for e in exposed:
            best = (False, "title_disagree")
            source = None
            for f in flagged:
                ok, reason = titles_agree_with_reason(e, f)
                if ok:
                    best = (True, "agree")
                    source = f
                    break
                if reason == "year_drift" and best[0] is False:
                    best = (False, reason)
                    source = None
                elif reason == "no_title" and best[1] == "title_disagree":
                    best = (False, reason)
            key_rows.append((int(e["id"]), best[0], best[1],
                             int(source["id"]) if source else None))
            if best[0]:
                key_targets.append((int(e["id"]), key, int(source["id"]),
                                    "agreement-gated fold: row %d corroborates flagged "
                                    "sibling %d under key %s" % (e["id"], source["id"], key)))
            else:
                key_clean = False
        # a row on a refused key stays QUARANTINED too: the row count follows the
        # key verdict, because a half-folded key is not a write this law performs.
        agree_rows += len(key_targets) if key_clean else 0
        quarantine_rows += (len(exposed) - len(key_targets)) if key_clean else len(exposed)
        if key_clean:
            targets.extend(key_targets)
        verdicts[key] = key_rows
        (agree_keys if key_clean else quarantine_keys).append(key)
    return {
        "exposed_keys": len(verdicts),
        "exposed_rows": exposed_rows,
        "agree_keys": agree_keys,
        "quarantine_keys": quarantine_keys,
        "agree_rows": agree_rows,
        "quarantine_rows": quarantine_rows,
        "verdicts": verdicts,
        "fold_targets": targets,
    }


def fold_rows(conn, targets) -> int:
    """Flip the named rows to flagged, journaling the pre-state of each. Returns flips.

    Per-row primary-key updates, not `inherit_key_adult`, because the gate is per-row
    even though its refusal is per-key: a key in the agree set has every exposed row
    corroborated, so row-by-row flipping writes exactly the same set as the key-level
    MAX would — and keeps the pre-state to undo it from.
    """
    conn.execute(KEY_FOLD_JOURNAL_DDL)
    flipped = 0
    now = time.time()
    for post_id, key, source_id, evidence in targets:
        prior = conn.execute(
            "SELECT is_18_plus FROM posts WHERE id = ?", (post_id,)).fetchone()
        if prior is None:
            continue
        cur = conn.execute(
            "UPDATE posts SET is_18_plus = 1 WHERE id = ? AND is_18_plus IS NOT 1",
            (post_id,))
        if cur.rowcount:
            conn.execute(
                "INSERT OR REPLACE INTO adult_key_fold_journal"
                " (post_id, canonical_key, prior_is_18_plus, source_post_id, evidence,"
                " decided_at) VALUES (?, ?, ?, ?, ?, ?)",
                (post_id, key, prior[0], source_id, evidence, now))
            flipped += 1
    return flipped


def undo_key_fold(conn) -> dict:
    """Restore every journaled row to its byte-exact pre-state (NULL stays NULL).

    Unlike the corroborated undo this keeps no row hidden on independent evidence: the
    key fold is a repair of a stated pre-condition, and an undo that silently differs
    from the pre-state is a second write nobody authorised. The projection roll-up is
    not reversed here — it never was, in either fold — and stamp invalidation is not
    undone because a missing stamp only costs a live recount.
    """
    out = {"restored": 0, "kept": 0}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'"
                    " AND name = 'adult_key_fold_journal'").fetchone() is None:
        return out
    entries = conn.execute(
        "SELECT post_id, prior_is_18_plus FROM adult_key_fold_journal"
        " ORDER BY post_id").fetchall()
    for post_id, prior in entries:
        cur = conn.execute(
            "UPDATE posts SET is_18_plus = ? WHERE id = ? AND is_18_plus IS 1",
            (prior, post_id))
        conn.execute("DELETE FROM adult_key_fold_journal WHERE post_id = ?", (post_id,))
        if cur.rowcount:
            out["restored"] += 1
        else:
            out["kept"] += 1
    return out


def _has_table(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,)).fetchone() is not None


def public_total(conn) -> int:
    """What `/api/v1/posts` claims the catalog holds — every non-flagged row."""
    return int(conn.execute(PUBLIC_TOTAL_SQL).fetchone()[0] or 0)


def exposed_keys(conn) -> list[tuple[str, int]]:
    return [(str(row[0]), int(row[1] or 0)) for row in conn.execute(EXPOSED_KEYS_SQL)]


def residual_exposures(conn) -> int | None:
    """Rows still public under a *different* key than the flagged copy.

    `None` when the projection is not in this database, which is a different answer
    from zero: without `cat_works` there is no cross-site identity to measure against.
    """
    if not (_has_table(conn, "cat_works") and _has_table(conn, "cat_work_sites")):
        return None
    return int(conn.execute(RESIDUAL_SQL).fetchone()[0] or 0)


def apply_ledger(conn, keys) -> int:
    """Flag every exposed sibling, key by key. Returns the rows flipped.

    `keys` is required: the caller has to have seen the exposure list before any
    write, which is the whole point of the report/`--apply` split.
    """
    flipped = 0
    for key in keys:
        flipped += fast_fetch.inherit_key_adult(conn, key)
    return flipped


def apply_projection(conn) -> tuple[int, int]:
    """Fold the ledger's flags into `cat_works`, then retire the safe stamps.

    Independent of the agreement gate (order #60): this roll-up is `any()` over posts
    already folded INTO the work, so it cannot invent a collision the ledger refused —
    it can only inherit flags the ledger already carries. Crown measured its over-flag
    direction at 0 (`CROWN_ADULT_MEASUREMENT.md` §2), so it keeps its own flag and never
    consults `classify_exposures`.

    Returns (works hidden, stamp keys deleted).
    """
    if not (_has_table(conn, "cat_works") and _has_table(conn, "cat_work_sites")):
        print("[!] no projection in this database — run catalog_v2.project() instead")
        return (0, 0)
    cur = conn.execute(PROJECTION_FLAG_SQL)
    hidden = max(int(cur.rowcount or 0), 0)
    dropped = invalidate_safe_stamp(conn)
    return (hidden, dropped)


def invalidate_safe_stamp(conn) -> int:
    """Delete the adult-excluded counters `/api/v1/stats` reads.

    After a flip they describe the catalog as it was. `_get_cached_stats()` answers
    from a live recount the moment a stamp is missing, so deleting them costs one
    counting query and buys a number that cannot be stale.
    """
    if not _has_table(conn, "cat_projection_meta"):
        return 0
    marks = ",".join("?" * len(SAFE_STAMP_KEYS))
    cur = conn.execute(
        f"DELETE FROM cat_projection_meta WHERE key IN ({marks})", SAFE_STAMP_KEYS)
    return cur.rowcount


def mem_headroom_mb(meminfo: str = "/proc/meminfo") -> int:
    """MemAvailable in MB — the pass below holds the whole ledger in memory, so on this
    one-CPU box it is a load decision, not just a correctness one."""
    try:
        with open(meminfo) as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


def audit_flags(conn, *, samples: int = 12) -> dict:
    """Split every stored flag into what the central rule reproduces and what it cannot.

    The second half is not "false positives" — a title with no adult vocabulary can still
    name an adult work — it is flags nobody can re-derive from the row's own text, which
    is exactly the population that may not be *propagated* to other rows and the worklist
    a human has to review. Read-only.
    """
    rows = conn.execute(
        "SELECT %s FROM posts WHERE COALESCE(is_18_plus, 0) = 1"
        % ", ".join(fast_fetch.ADULT_FOLD_FIELDS)).fetchall()
    reproducible = [row for row in rows if fast_fetch.adult_rule_agrees(row)]
    asserted = [row for row in rows if not fast_fetch.adult_rule_agrees(row)]
    return {
        "flagged": len(rows),
        "reproducible": len(reproducible),
        "asserted_only": len(asserted),
        "samples": [(row["id"], str(row["source_site"] or ""),
                     str(row["clean_title"] or row["title"] or "")[:60])
                    for row in asserted[:samples]],
    }


def run_audit(db_path: Path) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        out = audit_flags(conn)
    finally:
        conn.close()
    print(f"[i] {db_path}: {out['flagged']:,} rows carry the flag; "
          f"{out['reproducible']:,} reproduce from `is_adult_title()`, "
          f"{out['asserted_only']:,} are asserted-only and cannot be propagated")
    for post_id, site, title in out["samples"]:
        print(f"      id={post_id} site={site or '?':<14} {title!r}")
    return 0


def run_corroborated(db_path: Path, *, apply: bool, undo: bool = False) -> int:
    """The precision-gated fold: propagate only what the shared rule can defend.

    `--undo` first reverses this pass's own flips and leaves any flag that has since
    gained independent evidence (the rule agrees, or a sibling under the same key is
    flagged). Every write happens in one transaction, journal and all.
    """
    headroom = mem_headroom_mb()
    if headroom and headroom < 2000:
        print(f"[!] refused: MemAvailable {headroom} MB < 2000 MB — this pass loads the "
              f"ledger once, and the live box is out of breath", file=sys.stderr)
        return 3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    started = time.time()
    try:
        if undo:
            out = fast_fetch.undo_corroborated_adult_fold(conn)
            conn.commit()
            print(f"[✓] undo: {out['unflagged']:,} rows restored, {out['kept']:,} kept "
                  f"(their flag now stands on its own evidence)")
            return 0
        before = public_total(conn)
        exposures = fast_fetch.corroborated_adult_exposures(conn)
        print(f"[i] corroborated exposures: {len(exposures):,} rows publicly served under "
              f"a flag the rule reproduces (public total {before:,})")
        for item in exposures[:10]:
            print(f"      post {item['post_id']}  <-  {item['evidence']}")
        if len(exposures) > 10:
            print(f"      … {len(exposures) - 10} more")
        if not apply:
            print("[i] report only; pass --corroborate --apply to write, --undo to reverse")
            return 0
        flipped = fast_fetch.apply_corroborated_adult_fold(conn, exposures)
        after = public_total(conn)
        if flipped != before - after:
            print(f"[!] VERIFICATION FAILED: flipped {flipped} rows but the public total "
                  f"moved {before - after}", file=sys.stderr)
            conn.rollback()
            return 1
        dropped = invalidate_safe_stamp(conn)
        conn.commit()
        print(f"[✓] {flipped:,} rows hidden and journalled in `adult_fold_journal`; "
              f"{dropped:,} adult-excluded stamps retired")
        left = fast_fetch.corroborated_adult_exposures(conn)
        print(f"[i] corroborated exposures after the fold: {len(left):,} — must be 0")
        return 0 if not left else 1
    finally:
        print(f"[i] {time.time() - started:.1f}s", flush=True)
        conn.close()


def report(db_path: Path, *, apply: bool = False, projection: bool = False,
           apply_all: bool = False) -> dict:
    started = time.time()
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro" if not (apply or apply_all) else str(db_path),
        uri=not (apply or apply_all))
    conn.row_factory = sqlite3.Row
    try:
        before = public_total(conn)
        keys = exposed_keys(conn)
        exposed_rows = sum(count for _, count in keys)
        gate = classify_exposures(conn)
        summary = {
            "db": str(db_path),
            "public_total_before": before,
            "exposed_keys": len(keys),
            "exposed_rows": exposed_rows,
            "agree_keys": len(gate["agree_keys"]),
            "quarantine_keys": len(gate["quarantine_keys"]),
            "agree_rows": gate["agree_rows"],
            "quarantine_rows": gate["quarantine_rows"],
            "residual_other_key": residual_exposures(conn),
            "residual_after": None,
            "flipped": 0,
            "verified": None,
            "works_hidden_by_projection": 0,
            "stamps_dropped": 0,
            "public_total_after": before,
        }
        print(f"[i] {db_path}: public posts {before:,}; "
              f"{len(keys):,} keys hold a flagged and an unflagged row; "
              f"{exposed_rows:,} rows are exposed")
        print(f"[i] gate: exposed rows {gate['exposed_rows']:,} = "
              f"agree {gate['agree_rows']:,} + quarantine {gate['quarantine_rows']:,} "
              f"({len(gate['agree_keys'])} keys fold, {len(gate['quarantine_keys'])} refused)")
        for key in gate["quarantine_keys"][:60]:
            for post_id, ok, reason, _src in gate["verdicts"][key]:
                if not ok:
                    print(f"      QUARANTINE key={key} post={post_id} reason={reason}")
        if len(gate["quarantine_keys"]) > 60:
            print(f"      … {len(gate['quarantine_keys']) - 60} more quarantined keys")
        if summary["residual_other_key"] is None:
            print("[i] residual (same work, different key): no projection in this db")
        else:
            print(f"[i] residual (same work, different key): "
                  f"{summary['residual_other_key']:,} rows — not touched here")
        for key, count in keys[:10]:
            print(f"      {key}  exposed={count}")
        if len(keys) > 10:
            print(f"      … {len(keys) - 10} more keys")

        if not (apply or apply_all):
            print("[i] report only; pass --apply for the agree-gated fold, "
                  "--apply-all for the UN-GATED legacy fold")
            return summary

        if apply_all:
            print("[!] UN-GATED legacy fold (--apply-all): hiding EVERY exposed row, "
                  "including the quarantined keys the agreement gate refused")
            targets = []
            for k, _c in keys:
                for r in conn.execute(
                        "SELECT id FROM posts WHERE canonical_key = ?"
                        " AND is_18_plus IS NOT 1", (k,)):
                    targets.append((int(r["id"]), k, None,
                                    "un-gated --apply-all legacy fold"))
        else:
            targets = gate["fold_targets"]
            print(f"[i] agree-gated fold: {len(targets):,} rows under "
                  f"{len(gate['agree_keys']):,} keys")
        summary["flipped"] = fold_rows(conn, targets)
        after = public_total(conn)
        summary["public_total_after"] = after
        summary["verified"] = (summary["flipped"] == before - after)
        if not summary["verified"]:
            print(f"[!] VERIFICATION FAILED: flipped {summary['flipped']} rows but the "
                  f"public total moved {before - after}", file=sys.stderr)
            conn.rollback()
            # the write never happened — say so with the post-ROLLBACK number, not
            # the uncommitted one the check itself measured:
            summary["public_total_after"] = public_total(conn)
            return summary
        print(f"[✓] ledger: {summary['flipped']:,} rows flagged; "
              f"public total {before:,} -> {after:,} (exactly the rows flipped)")
        summary["residual_after"] = residual_exposures(conn)
        if summary["residual_after"] is not None:
            print(f"[i] residual after the flip: {summary['residual_after']:,} rows — "
                  f"the same work flagged on one site and served under another key, "
                  f"which this law cannot reach")
        if projection:
            hidden, dropped = apply_projection(conn)
            summary["works_hidden_by_projection"] = hidden
            summary["stamps_dropped"] = dropped
            print(f"[✓] projection: {hidden:,} works hidden; {dropped:,} "
                  f"adult-excluded stamps retired, so /api/v1/stats recounts live "
                  f"until the next rebuild")
        conn.commit()
        return summary
    finally:
        print(f"[i] {time.time() - started:.1f}s", flush=True)
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="write the ledger reconciliation, agree-gated keys only "
                             "(default: report only)")
    parser.add_argument("--apply-all", action="store_true",
                        help="UN-GATED legacy fold: reconcile EVERY exposed key, "
                             "quarantined collisions included; prints its own warning")
    parser.add_argument("--projection", action="store_true",
                        help="with --apply/--apply-all, also fold flags into cat_works")
    parser.add_argument("--audit", action="store_true",
                        help="read-only: how many stored flags the central rule still "
                             "reproduces, and how many are asserted-only")
    parser.add_argument("--corroborate", action="store_true",
                        help="propagate only flags the central rule reproduces "
                             "(report; combine with --apply to write)")
    parser.add_argument("--undo", action="store_true",
                        help="reverse the key fold (--undo), exactly restoring each "
                             "journaled row's pre-state; with --corroborate, reverses "
                             "the corroborated pass instead (falls back to it when no "
                             "key-fold journal exists)")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"[!] no such database: {args.db}", file=sys.stderr)
        return 2
    if args.audit:
        return run_audit(args.db)
    if args.corroborate:
        return run_corroborated(args.db, apply=args.apply, undo=args.undo)
    if args.undo:
        return run_key_undo(args.db)
    report(args.db, apply=args.apply, projection=args.projection,
           apply_all=args.apply_all)
    return 0


def run_key_undo(db_path: Path) -> int:
    """Plain `--undo`: reverse the agreement-gated/`--apply-all` key fold, byte-exactly.

    Backwards shape kept on purpose: when this database holds no key-fold journal
    entries, the argument still means exactly what it meant before order #60 — the
    corroborated undo runs, with its memory gate and its output wording untouched —
    so old runbooks neither no-op nor change shape.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        out = undo_key_fold(conn)
        if out["restored"] or out["kept"]:
            conn.commit()
            print(f"[✓] key-fold undo: {out['restored']:,} rows restored byte-exactly "
                  f"to their journaled pre-state, {out['kept']:,} untouched "
                  f"(no longer flagged — nothing was double-written)")
            dropped = invalidate_safe_stamp(conn)
            conn.commit()
            if dropped:
                print(f"[i] {dropped:,} adult-excluded stamps retired")
            return 0
    finally:
        conn.close()
    return run_corroborated(db_path, apply=False, undo=True)


if __name__ == "__main__":
    sys.exit(main())
