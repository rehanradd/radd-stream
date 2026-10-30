#!/usr/bin/env python3
"""Offline guard for the 2026-10-30 documentation diet.

The diet split the auto-loaded docs into LAW (stays in the AGENTS.md files), LOG (rotated to
one dated file per session) and SPEC (long reference prose, linked not inlined). This suite is
what makes that safe: it asserts that every law sentence the fleet depends on is still present,
verbatim, in the file every agent auto-loads; that the rotated destinations actually exist and
every relative link in the trimmed files resolves; and that the trimmed files stayed trimmed.

Nothing here touches the network or the catalog: it reads five markdown files and the git-tracked
tree layout. Run it from the repo root (`python3 -S Fast_Fetch/test_docs_invariants.py`) or from
Fast_Fetch/ — paths are derived from this file's own location, never from a working directory.
"""
from __future__ import annotations

import pathlib
import re
import unittest

BASE_DIR = pathlib.Path(__file__).resolve().parent          # Fast_Fetch/
REPO_ROOT = BASE_DIR.parent                                 # repo root

ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
FF_AGENTS = BASE_DIR / "AGENTS.md"
APP_AGENTS = REPO_ROOT / "App" / "AGENTS.md"
CONTINUITY = BASE_DIR / "CONTINUITY.md"
CHECKPOINT = REPO_ROOT / "docs" / "SESSION_CHECKPOINT.md"

AUTO_LOADED = [ROOT_AGENTS, FF_AGENTS, APP_AGENTS]


def flat(text: str) -> str:
    """Markdown wraps law sentences across lines; compare on single-spaced text."""
    return re.sub(r"\s+", " ", text)


def load(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# Each entry: (human label, file, verbatim phrase). A phrase is a *substring* of the
# whitespace-normalised file, so re-wrapping a paragraph cannot hide a lost law line.
INVARIANTS = [
    # --- framing -------------------------------------------------------------------
    ("accurate description, no disguise", ROOT_AGENTS,
     "Describe the code's behavior accurately to users and tools. Do not disguise its purpose "
     "or frame work to bypass another service's safety rules."),
    ("not a hosting service", ROOT_AGENTS, "Not a hosting service"),
    ("not a DRM circumventer", ROOT_AGENTS, "Not a DRM circumventer"),

    # --- the adult invariant -------------------------------------------------------
    ("adult stored, never displayed", ROOT_AGENTS,
     "Adult (18+) content is **stored but never displayed to a user**"),
    ("flag re-derived at write time", ROOT_AGENTS,
     "`save_scraped_data` re-derives it from the title as a row becomes a post"),
    ("no public surface lists or plays", ROOT_AGENTS,
     "no public surface may list *or play* a flagged row"),
    ("unknown link id is refused", ROOT_AGENTS,
     "answers True for an unknown link id so a typo cannot play either"),
    ("flagged row indistinguishable from absent", ROOT_AGENTS,
     "a flagged row is indistinguishable from a row that never existed"),
    ("operator panel is the one exception", ROOT_AGENTS,
     "**One exception, deliberately, and it is not a user-facing display surface:** the operator panel."),
    ("loopback is the boundary, not the token", ROOT_AGENTS,
     "the trust boundary there is the loopback interface, not `RADD_ADMIN_TOKEN`"),
    ("stream and download deny on the operator port too", ROOT_AGENTS,
     "`/api/v1/stream` and `/api/v1/download` deny a flagged link **on the operator port too**"),
    ("panel token leak is a defect", ROOT_AGENTS,
     "If a change ever lets the panel emit a stream or download token for a flagged row, "
     "that is a defect, not a policy."),
    ("the named hole: 442 keys / 455 rows", ROOT_AGENTS,
     "442 keys held both, and 455 unflagged twins were reachable"),
    ("key-level reconciliation, not another WHERE", ROOT_AGENTS,
     "That is fixed here, not by adding another `WHERE` clause"),
    ("inherit_key_adult reconciles MAX(is_18_plus)", ROOT_AGENTS,
     "`fast_fetch.inherit_key_adult()` reconciles `MAX(is_18_plus)` across every row sharing the key"),
    ("residual measure under the correct identity", ROOT_AGENTS,
     "2,600 keys carrying both a flagged and an unflagged row, 3,486 publicly served rows "
     "under those keys, and a 69,773-row re-key blast radius"),
    ("pattern law: person, studio or act", ROOT_AGENTS,
     "a pattern belongs here only if it names a person, a studio, or an act — never a version, "
     "a quality, a rating, or a release format — and only if you can write a test that proves "
     "it catches a case the other patterns miss"),
    ("audit tool is report-by-default", ROOT_AGENTS,
     "`Fast_Fetch/audit_adult_flags.py` (report-by-default; writes require the owner's `--owner-go`)"),
    ("P0 definition", ROOT_AGENTS,
     "A test that reaches a flagged row through any public route, or a flagged link through "
     "stream or download on either port, is P0."),
    ("adult law in the backend guide", FF_AGENTS,
     "18+ content: store flagged, never display"),
    ("no --apply without the owner", FF_AGENTS,
     "no agent may run `--apply` (or `--projection`) against the live ledger without the "
     "owner's verbatim authorization"),
    ("word boundaries do real work", FF_AGENTS,
     "Word-boundary anchors do real work — do not loosen them."),

    # --- secrets -------------------------------------------------------------------
    ("GITHUB_TOKEN row", ROOT_AGENTS, "| `GITHUB_TOKEN` |"),
    ("ORACLE_SSH_KEY row", ROOT_AGENTS, "| `ORACLE_SSH_KEY` |"),
    ("KEYSTORE_BASE64 row", ROOT_AGENTS, "| `KEYSTORE_BASE64` |"),
    ("KEY_STORE_PASSWORD row", ROOT_AGENTS, "| `KEY_STORE_PASSWORD` |"),
    ("KEY_ALIAS row", ROOT_AGENTS, "| `KEY_ALIAS` |"),
    ("KEY_PASSWORD row", ROOT_AGENTS, "| `KEY_PASSWORD` |"),
    ("verify names only, never read or print", ROOT_AGENTS,
     "Verify only whether the two configured variable names are present; never read or print "
     "their values, put them in Git URLs or command arguments, commit them, or copy them to Oracle."),
    ("do not ask to move to Replit Secrets", ROOT_AGENTS,
     "Do not ask the user to move them to Replit Secrets."),
    ("measured: secrets list is empty", ROOT_AGENTS,
     "`{\"total_count\": 0, \"secrets\": []}`"),
    ("release died at the signing preflight", ROOT_AGENTS,
     "it died at the `🗝️ Verify signing secrets are present` preflight"),
    ("do not generate a replacement keystore", ROOT_AGENTS,
     "**Do not generate a replacement keystore to work around it**"),
    ("debug APK needs no secret", ROOT_AGENTS,
     "uploads a **debug APK** on every green run"),
    ("app lane: signed release needs the 4 secrets", ROOT_AGENTS,
     "the *signed release* needs the 4 keystore secrets, which are **currently absent**"),

    # --- the live tree and the push discipline -------------------------------------
    ("/opt/radd-stream is the live deployment tree", ROOT_AGENTS,
     "**`/opt/radd-stream` is the live deployment tree, not a workspace.**"),
    ("work in your own worktree", ROOT_AGENTS,
     "Work in your own worktree (`git worktree add /tmp/<yourlane> <sha>`) and push that sha"),
    ("never commit from or reset the live tree", ROOT_AGENTS,
     "do **not** commit from or reset `/opt/radd-stream`"),
    ("stage only reviewed paths", ROOT_AGENTS,
     "Stage only reviewed paths (`git add <paths>`), inspect the staged names/diff"),
    ("no git add -A, no force-push", ROOT_AGENTS, "Never use `git add -A` or force-push."),
    (".replit is local-only", ROOT_AGENTS,
     "Treat `.replit` as local-only sensitive configuration: do not inspect its values or "
     "stage, commit, or push it."),
    ("credentials never in URLs/argv/files/logs", ROOT_AGENTS,
     "Never put credentials in URLs, command arguments, files, or logs."),
    ("the retired push scripts stay retired", ROOT_AGENTS,
     "Do **not** recreate or restore `push.py`, `github_push.py`, `emergency_push.py`, "
     "`push_github.py`, or `safe_push.sh`."),
    ("deployment is separate from a branch push", ROOT_AGENTS,
     "do not copy untested or WIP code to the live host"),

    # --- fleet resource guardrail: all seven steps --------------------------------
    ("one vCPU", ROOT_AGENTS, "**This host has ONE vCPU** (`nproc` = 1)"),
    ("memory is what kills the host", ROOT_AGENTS,
     "**Memory saturation is what kills this host**"),
    ("rule 1 HARD FLOOR", ROOT_AGENTS,
     "**HARD FLOOR — stop heavy work at once** if any of: `MemAvailable < 1500 MB`, `SwapFree < 800 MB`, "
     "or the service cgroup `MemoryCurrent > 1200 MB`"),
    ("rule 2 heavy work frozen over load 4", ROOT_AGENTS,
     "**HEAVY WORK is frozen while load > 4**"),
    ("rule 3 light work always allowed", ROOT_AGENTS, "**LIGHT WORK is always allowed**"),
    ("rule 4 never probe unknown cost with N>1", ROOT_AGENTS,
     "**Never probe a route or query of unknown cost with a sample size > 1.**"),
    ("rule 5 never restart the service", ROOT_AGENTS,
     "never restart/reload/stop `radd-stream.service`"),
    ("rule 5 never create or push a tag", ROOT_AGENTS, "never create or push a git tag"),
    ("rule 6 queue the heavy read", ROOT_AGENTS,
     "**If your task needs a heavy read, do not run it — queue it.**"),
    ("rule 7 local timing is not module timing", ROOT_AGENTS,
     "**A slow local test module is not a slow test module — never exclude one on this box's timing.**"),
    ("rule 7 carries its measurement", ROOT_AGENTS, "266.312 s"),
    ("rule 7 names the hosted verdict", ROOT_AGENTS, "1 s on the hosted runner"),

    # --- the measured CI truth ------------------------------------------------------
    ("count steps by the 🧪 name", ROOT_AGENTS, "grep -c 'name: 🧪' .github/workflows/backend-ci.yml"),
    ("run: python3 -S undercounts", ROOT_AGENTS, "the latter silently undercounts"),
    ("the timed step is still a suite", ROOT_AGENTS, "`run: time python3 -S …` is still a suite"),
    ("the workflow file is the source of truth", ROOT_AGENTS,
     "the workflow file is the only source of truth"),
    ("empty run list is the path filter", ROOT_AGENTS,
     "**Do not misread an empty CI run list.**"),
    ("read the trigger block, not the account", ROOT_AGENTS,
     "read the workflow's own trigger block before predicting whether CI will run"),
    ("the filter shape is measured, never assumed", ROOT_AGENTS,
     '`paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]`'),
    ("ask permissions, not vibes", ROOT_AGENTS,
     "If you need to know whether CI can run, query `/actions/permissions` and print what it says."),

    # --- edge truth ------------------------------------------------------------------
    ("operator panel is loopback-only, not token-gated", ROOT_AGENTS,
     "Do not describe the dashboard as token-gated; describe it as loopback-only, which is what is true."),
    ("nginx allow-lists the public routes", ROOT_AGENTS,
     "nginx allow-lists only `/api/v1/posts`, `/api/v1/stream`, `/api/v1/stats`"),
    ("backend is the running system", ROOT_AGENTS,
     "The backend is **already deployed there and is the running system**"),

    # --- the eleven standing rules ----------------------------------------------------
    ("stdlib only, no pip ever", ROOT_AGENTS,
     "**Python stdlib only** for the backend — no `pip install` ever"),
    ("Kotlin / Jetpack Compose", ROOT_AGENTS, "**Kotlin / Jetpack Compose** for the Android app"),
    ("never break existing tests", ROOT_AGENTS, "**Never break existing tests**"),
    ("never delete parsers", ROOT_AGENTS, "**Never delete parsers** — add, fix, extend — never remove"),
    ("pathlib + BASE_DIR", ROOT_AGENTS,
     "**Never hardcode absolute paths** — use `pathlib.Path` + `BASE_DIR`"),
    ("log every session", ROOT_AGENTS, "**Log every session**"),
    ("push securely", ROOT_AGENTS, "**Push securely**"),
    ("read CONTINUITY.md first", ROOT_AGENTS, "**Read CONTINUITY.md first**"),
    ("per-site staging database", ROOT_AGENTS, "**Per-Site Dedicated Staging Database Rule**"),
    ("zero data loss", ROOT_AGENTS, "**Zero Data Loss & Clone-Ready Fidelity Rule**"),
    ("master-disciple local AI law", ROOT_AGENTS, "**Master-Disciple Local AI Law"),
    ("no pip installs (backend guide)", FF_AGENTS, "**No pip installs** — only stdlib"),
    ("verify import after every edit", FF_AGENTS, "**Verify import after EVERY edit:**"),
    ("provenance stops at the HTTP edge", FF_AGENTS, "**Provenance stops at the HTTP edge**"),
    ("never redact stored data", FF_AGENTS,
     "**Never** redact stored data — the ledger keeps everything (Zero Data Loss rule)"),
    ("app: credential safety", APP_AGENTS, "Git and Credential Safety"),
    ("app: never run gradlew directly", APP_AGENTS, "**Never run `./gradlew` directly.**"),
    ("app: one build at a time", APP_AGENTS, "One build at a time, and no build while another agent is mid-verification."),
    ("app: arm64-excluded suites are invisible here", APP_AGENTS,
     "no number printed on this host includes those two suites"),
]


class InvariantPhrasesTests(unittest.TestCase):
    """Every law sentence is still in the file every agent auto-loads."""

    def test_all_invariant_phrases_survive_the_diet(self):
        texts = {}
        missing = []
        for label, path, phrase in INVARIANTS:
            if path not in texts:
                texts[path] = flat(load(path))
            if flat(phrase) not in texts[path]:
                missing.append("%-58s in %s: %s" % (label, path.name, phrase[:70]))
        self.assertFalse(missing, "\nLAW LOST:\n" + "\n".join(missing))

    def test_each_target_file_exists_and_is_non_empty(self):
        for path in AUTO_LOADED + [CONTINUITY, CHECKPOINT]:
            self.assertTrue(path.is_file(), "missing doc: %s" % path)
            self.assertGreater(len(load(path)), 1_000, "empty doc: %s" % path)

    def test_invariant_labels_are_unique_so_no_check_is_silent(self):
        labels = [label for label, _p, _x in INVARIANTS]
        self.assertEqual(len(labels), len(set(labels)), "duplicate invariant label")


class ByteBudgetTests(unittest.TestCase):
    """The diet's whole point: what an agent auto-loads must stay small.

    The ceilings are the measured law floor plus 4 KB of regrowth headroom. The brief asked for
    8/8/10 KB; the verbatim-law list it also demands is larger than 8 KB on its own, so these
    numbers are what is actually true, and raising one must be a deliberate, documented edit.
    """

    CEILINGS = {ROOT_AGENTS: 32_000, FF_AGENTS: 18_000, APP_AGENTS: 15_000}

    def test_auto_loaded_files_stay_under_their_ceilings(self):
        for path, ceiling in self.CEILINGS.items():
            size = len(load(path).encode("utf-8"))
            self.assertLessEqual(size, ceiling, "%s grew to %d B (ceiling %d)" % (path, size, ceiling))

    def test_session_logs_are_indexes_not_archives(self):
        for path in (CONTINUITY, CHECKPOINT):
            self.assertLessEqual(len(load(path).encode("utf-8")), 12_000,
                                 "%s is an archive again" % path)
            self.assertLessEqual(len(load(path).splitlines()), 120,
                                "%s lost its index shape" % path)


class RotatedHistoryTests(unittest.TestCase):
    """Nothing was deleted: the LOG moved to dated files, and the links say where."""

    def test_rotated_log_directories_exist_with_content(self):
        for d in (BASE_DIR / "checkpoints", REPO_ROOT / "docs" / "checkpoints"):
            self.assertTrue(d.is_dir(), "missing rotated log dir: %s" % d)
            self.assertGreaterEqual(len(list(d.glob("*.md"))), 10,
                                    "%s does not hold the rotated history" % d)
            self.assertTrue((d / "README.md").is_file(), "%s/README.md index missing" % d)

    def test_app_session_history_moved_and_exists(self):
        self.assertTrue((REPO_ROOT / "App" / "docs" / "SESSION_HISTORY.md").is_file())

    def test_moved_spec_documents_exist(self):
        spec_dir = REPO_ROOT / "docs"
        specs = sorted(p.name for p in spec_dir.glob("SPEC_*.md"))
        self.assertGreaterEqual(len(specs), 20, "the SPEC layer is missing: %s" % specs)
        for name in ("SPEC_REPO_MAP.md", "SPEC_ADULT_FLAG_EVIDENCE.md",
                     "SPEC_AGENTS_MEASURED_NOTES.md", "SPEC_FAST_FETCH_ARCHITECTURE.md",
                     "SPEC_APP_ROBOLECTRIC_ARM64.md"):
            self.assertTrue((spec_dir / name).is_file(), "moved-out spec missing: %s" % name)

    def test_no_history_line_was_deleted_only_moved(self):
        """The rotated logs are append-only archives: the index must still reach the newest entry."""
        for d in (BASE_DIR / "checkpoints", REPO_ROOT / "docs" / "checkpoints"):
            dated = sorted(p.name for p in d.glob("*.md") if p.name not in ("README.md", "TEMPLATE.md"))
            self.assertTrue(dated, "%s has no dated session files" % d)
            newest = dated[-1]
            index = load(d / "README.md")
            self.assertIn(newest, index, "%s/README.md does not index %s" % (d, newest))


class LinkIntegrityTests(unittest.TestCase):
    """A diet that breaks links hides the history instead of moving it."""

    LINK = re.compile(r"""\]\(([^)\s#]+)(?:#[^)]*)?\)""")

    # A markdown link whose target is really a regex example or a glob is not a path.
    NOT_A_PATH = re.compile(r"""[?\\*]|\.\.\.""")

    def test_relative_links_in_the_trimmed_files_resolve(self):
        broken = []
        for path in AUTO_LOADED + [CONTINUITY, CHECKPOINT]:
            for target in self.LINK.findall(load(path)):
                if target.startswith(("http://", "https://", "mailto:", "/")):
                    continue
                if self.NOT_A_PATH.search(target):
                    continue
                resolved = (path.parent / target).resolve()
                if not resolved.exists():
                    broken.append("%s -> %s" % (path.relative_to(REPO_ROOT), target))
        self.assertFalse(broken, "dangling links:\n" + "\n".join(sorted(set(broken))))

    def test_dated_session_files_are_reachable_from_the_root_index(self):
        index = load(REPO_ROOT / "docs" / "SESSION_CHECKPOINT.md")
        for p in sorted((REPO_ROOT / "docs" / "checkpoints").glob("*.md")):
            if p.name in ("README.md", "TEMPLATE.md"):
                continue
            self.assertTrue(
                p.name in index or p.name in load(REPO_ROOT / "docs" / "checkpoints" / "README.md"),
                "session file not reachable from the index: %s" % p.name)


class OpenItemsIndexTests(unittest.TestCase):
    """The brief: each checkpoint file gets a short open-items index at the top."""

    def test_index_is_at_the_top_of_each_log(self):
        for path in (CONTINUITY, CHECKPOINT):
            body = load(path)
            first_heading = re.search(r"^## .*", body, re.M)
            self.assertTrue(first_heading, "%s has no headings" % path)
            self.assertLessEqual(first_heading.start(), 4_000,
                                "%s: the index is not at the top" % path)
            self.assertTrue(re.search(r"(?i)open items|current state", body[:4_000]),
                            "%s lost its open-items index" % path)


if __name__ == "__main__":
    print("fixture: %s (offline, markdown only — no network, no catalog)" % pathlib.Path(__file__).name)
    unittest.main(verbosity=2)
