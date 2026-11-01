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
import subprocess
import unittest

BASE_DIR = pathlib.Path(__file__).resolve().parent          # Fast_Fetch/
REPO_ROOT = BASE_DIR.parent                                 # repo root

ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
FF_AGENTS = BASE_DIR / "AGENTS.md"
APP_AGENTS = REPO_ROOT / "App" / "AGENTS.md"
CONTINUITY = BASE_DIR / "CONTINUITY.md"
CHECKPOINT = REPO_ROOT / "docs" / "SESSION_CHECKPOINT.md"
#: The one file a lane reads to learn how to reach the panel, and the one that
#: carried the wording root AGENTS.md forbids.
ADMIN_DOC = REPO_ROOT / "docs" / "ADMIN_PANEL_ACCESS.md"
MEASURED_NOTES = REPO_ROOT / "docs" / "SPEC_AGENTS_MEASURED_NOTES.md"
#: Where the arm64/Robolectric evidence lives since the 2026-10-30 diet. `App/AGENTS.md` links it by
#: name, so it passes the reachability test even though it is not auto-loaded.
APP_ROBO_DOC = REPO_ROOT / "docs" / "SPEC_APP_ROBOLECTRIC_ARM64.md"

FF_CKPT = BASE_DIR / "checkpoints"
DOC_CKPT = REPO_ROOT / "docs" / "checkpoints"

#: The gate's own module list. Docs may describe the gate; only this file decides what runs.
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "backend-ci.yml"

AUTO_LOADED = [ROOT_AGENTS, FF_AGENTS, APP_AGENTS]


def flat(text: str) -> str:
    """Markdown wraps law sentences across lines; compare on single-spaced text."""
    return re.sub(r"\s+", " ", text)


def load(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def git_show(rev: str, rel: str):
    """`git show <rev>:<path>` from this file's own clone. None if the object is not present."""
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "show", "%s:%s" % (rev, rel)],
                          capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


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
    ("merge-time fold is the cross-key reconciliation", ROOT_AGENTS,
     "`merge_catalogs.reconcile_adult_on_merge()` folds a work's flagged row onto its siblings only"),
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
    # Converted 2026-11-01 (q5, Muse's 09:03 word): the old literal was an API *response body* —
    # `{"total_count": 0, "secrets": []}` — so the pin guarded a measurement that `63396c1` already
    # overturned. What the paragraph is for is the reading rule it states: an empty list is evidence
    # only once you have checked the reader's own repo permissions. That clause is what is pinned now.
    ("an empty list from a scoped read is still a real answer", ROOT_AGENTS,
     "so it is a real answer and not a permission artifact"),
    # Converted 2026-11-01 (q5, slice 2 of the ordinary eight). The old literal was a 2026-10-29 run
    # outcome ("it died at the `🗝️ Verify signing secrets are present` preflight"), and the audit's own
    # suggested replacement — "That preflight is why exercising this is safe", the sentence right after
    # it — is now the dangerous half of the paragraph: run `41104217171` *cleared* that preflight, so a
    # dispatched release run is no longer stopped by it. Pinning the audit's suggestion would have
    # frozen a false safety guarantee into the gate. So this pin moves subject, not just phrase: it
    # lands on the live reading rule from the file that records release-run history, and the staleness
    # of the `AGENTS.md` safety sentence is reported to the supervisor rather than edited by this lane
    # (the file is 10 B under its ceiling and the sentence is policy, not prose).
    ("a red release run is read from the job log, not the summary", MEASURED_NOTES,
     "read the job log, not the summary"),
    ("do not generate a replacement keystore", ROOT_AGENTS,
     "**Do not generate a replacement keystore to work around it**"),
    # Converted 2026-11-01 (q5, slice 4). The old literal was a workflow behaviour snapshot — "uploads a
    # **debug APK** on every green run" — which any edit to `ci.yml`'s artifact step can falsify without
    # meaning anything. The clause pinned now is the reason that made the snapshot useful in the first
    # place, and it does not depend on a step existing. Self-check against the rule from slice 3: this
    # sentence's *other* half is already pinned by `app lane: signed release needs the 4 secrets`, so
    # two pins do land in one sentence — accepted, because debug-variant and release-variant are two
    # propositions that reword apart, which is the test, not the sentence boundary.
    ("the debug build needs no signing secret", ROOT_AGENTS,
     "the debug build needs no secrets"),
    ("app lane: signed release needs the 4 secrets", ROOT_AGENTS,
     "the *signed release* needs the 4 keystore secrets"),
    # Converted 2026-11-01 (q5, slice 3). The old literal — "No signed APK or AAB has ever existed for
    # this product" — is an event-expiring sentence: it goes false on the first successful release and
    # stays false, so the pin was a countdown to its own deletion. The gap it documents is also the
    # pressure that makes a lane want to manufacture an artifact, which is why this bites on the
    # identity rule instead: a self-generated key is not a workaround, it is a different product line.
    # Same sentence as the `do not generate a replacement keystore` pin: that one holds the prohibition,
    # this one holds the reason, and they can be reworded apart. Why that is not the duplicate the tag
    # clause would have been is argued in the slice-3 section of
    # `Fast_Fetch/checkpoints/20261101-q5-pin-conversions-the-eight-ordinary-slices.md`.
    ("the owner's signing key is the only correct one", ROOT_AGENTS,
     "the owner's key is the only correct one"),
    ("cutting and moving tags is owner-only", ROOT_AGENTS,
     "Moving or re-cutting a tag is an owner action"),

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
    # Converted 2026-11-01 (q5, Muse's slice): these two pinned a *measured number* — `266.312 s`
    # and `1 s on the hosted runner` — so any lane that re-measured rule 7 turned CI red for editing
    # a stopwatch reading. The numbers stay in `AGENTS.md` where they belong (rule 7 cites its run
    # id); the pin now bites on the two clauses that make the numbers non-load-bearing, which is the
    # shape the ADMIN_DOC pins in the edge-truth block below already use. Trade, stated plainly: the tax
    # is gone and so is the guarantee that anyone re-measures — rule 7's own sentence is what demands it.
    ("rule 7 says the local number is a symptom", ROOT_AGENTS,
     "the local number is a symptom of the guardrail, not a property of the code"),
    ("rule 7 gives CI the timing authority", ROOT_AGENTS,
     "only CI's per-step timing decides whether a suite belongs in the gate"),

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
    # Converted 2026-11-01 (q5, slice 5 of the ordinary eight). The old literal was a verbatim copy of
    # `backend-ci.yml`'s own `paths:` list — configuration a lane may legitimately change, and `AGENTS.md`
    # itself calls such a list "a snapshot that grows". The guard would have turned CI red on a lane that
    # widened the filter for a good reason (adding `docs/**`, say), reporting a docs-law regression that was
    # only a CI configuration change. `AGENTS.md` keeps the shape where it belongs: dated, anchored to
    # `dc73ac7`, and explicitly labelled "what the filter is today".
    # The clause pinned now is the one that forbids trusting *any* transcription, including this file's.
    # Nearest-neighbour check before accepting, because the series rule is coverage not accumulation: the
    # two adjacent pins are `the workflow file is the only source of truth` (about the *step list* — a stale
    # count quoted in prose) and `read the trigger block, not the account` (the *obligation to measure*).
    # This one is neither: it is the `paths-ignore` incident — a shape quoted into a doc that could not be
    # reproduced against the tree or the object store. Three propositions that each fire alone, so three
    # pins. No `AGENTS.md` byte moved; headroom stays 10 B.
    ("the method outranks any quoted trigger shape", ROOT_AGENTS,
     "the method above is the law and not a quoted shape"),
    ("ask permissions, not vibes", ROOT_AGENTS,
     "If you need to know whether CI can run, query `/actions/permissions` and print what it says."),

    # --- edge truth ------------------------------------------------------------------
    ("operator panel is loopback-only, not token-gated", ROOT_AGENTS,
     "Do not describe the dashboard as token-gated; describe it as loopback-only, which is what is true."),
    ("the panel's own guide states the ordering, not the credential", ADMIN_DOC,
     "Never describe the dashboard as token-gated: holding `RADD_ADMIN_TOKEN` does not make it reachable"),
    ("the panel guide separates the running tree from the repository", ADMIN_DOC,
     "Read that table as the state of the *running tree*, not of the repository."),
    # Converted 2026-11-01 (q5): the old phrase was a *prefix* of a seven-item enumeration in the Key
    # Links row (`/api/v1/posts`, `/api/v1/stream`, `/api/v1/stats` … the row also carries `/download`,
    # `/search/by-media`, `/app/remote-config`, `/v2/account*`, `/download/`). It still matched, so this
    # pin was not broken — it was doubly wrong: it red-fires on any reorder or reword of a list the doc
    # has visibly grown once already, while giving false comfort that the allow-list was guarded when it
    # only ever described its first three entries. What is invariant is the *shape* of the policy — nginx
    # is the edge and it allow-lists, it does not block-list — so that clause is what is pinned now. The
    # live list stays in `AGENTS.md` (Key Links, row "Backend REST API (publicly reachable)") as the
    # measured fact it is; it carries no date there, which is a separate weakness and is *not* claimed
    # fixed here.
    ("nginx allow-lists rather than block-lists at the edge", ROOT_AGENTS,
     "allow-lists only the public routes"),
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
    # Converted 2026-11-01 (q5, slice 6). Two defects in one entry. (a) The old literal — "no number
    # printed on this host includes those two suites" — is a claim over the *history of runs on this
    # box*, which no reader can re-derive and no test can execute. Its rot path is honest editing: a
    # lane that re-measures, lifts the arm64 exclusion, or simply tightens the wording updates that
    # sentence, and the gate then reports a docs-law regression for a bookkeeping edit. (b) Its subject
    # sentence in `App/AGENTS.md` begins "The exclusion stays", which cannot be pinned there: `load()`
    # keeps the blockquote markers and `flat()` collapses the wrap to "The exclusion > stays", so any
    # phrase crossing that line break is unreachable by this matcher — verified by matching, not by
    # reading, which is the slice-3 lesson. So the target moves to the spec doc `App/AGENTS.md` links by
    # name, and the literal becomes the universal rule rather than the historical tally: the suites are
    # invisible to *any* number printed on this host, which holds whether or not the nine have ever run
    # here and does not depend on a run history nobody can audit.
    # Consequence stated, not hidden: the pin no longer proves the suites are excluded, only that the
    # reading rule is on the page. Proof of exclusion lives in the build file that does it.
    ("the arm64-excluded suites are invisible to any local number", APP_ROBO_DOC,
     "they are invisible to any number printed on this host"),

    # --- law written to trunk AFTER the rotation, absorbed by the rebase onto `4fe6f65` ----------
    # A guard that enumerates only the laws it knew at writing time is the failure mode this diet
    # exists to prevent, so the enumeration grows with the tree instead of freezing at 2026-10-30.
    ("live tree is what ExecStart loads, not a workspace",
     DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
     "— which is what `ExecStart` loads, not a workspace —"),
    ("a restart loads the superseded mixture, not trunk",
     DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
     "any restart of `radd-stream` today loads that superseded mixture, not trunk"),
    ("supervisor refuses to commit over or reset the live tree",
     DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
     "I am **not** committing over it and **not** resetting it"),
    ("every lane brief names its own /tmp worktree as mandatory",
     DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
     "every lane brief from now on names its own `/tmp/<lane>` worktree as mandatory"),
    ("dispatch frozen below the memory floor",
     DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
     "nothing new goes out while `MemAvailable` < 1800 MB"),
    ("killing a backup is not a safety measure",
     DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
     "killing a backup is not a safety measure"),
    ("zero-source posts are a FAIL, not a design choice",
     FF_CKPT / "20261030-q2-themoviebox-crawl-2026-10-30-parser-fixes-detail-api-preference.md",
     "The vault stays a FAIL until some surface publishes a playable URL"),
    ("a crawl gate refusal is reported, not silently retried",
     FF_CKPT / "20261030-q2-themoviebox-crawl-2026-10-30-parser-fixes-detail-api-preference.md",
     "No crawl, no re-derive, zero network requests this turn."),
    ("memory-floor test failures are not feed regressions",
     FF_CKPT / "20261030-q2-themoviebox-crawl-2026-10-30-parser-fixes-detail-api-preference.md",
     "DiscoveryTests were memory-floor failures, not feed regressions"),
    ("transport failures are attributed to the site only below load 4",
     FF_CKPT / "20261030-q2-themoviebox-crawl-2026-10-30-parser-fixes-detail-api-preference.md",
     "attribute a transport failure to the site only below load 4"),
    ("the detail API is preferred only when a subjectId exists",
     FF_CKPT / "20261030-q2-themoviebox-crawl-2026-10-30-parser-fixes-detail-api-preference.md",
     "Crawl now prefers the API when the queued row carries a `subjectId`"),
    # Converted 2026-11-01 (q5, slice 7). The old literal was the *classification* sentence — "MovieBox is a
    # **metadata + trailer-evidence** source, not a playable-source site, from this host at this time". It
    # reads like a law and is actually a measurement with a timestamp on it: the first lane that resolves a
    # playable print rewrites that sentence as honest bookkeeping and the guard reports it as a policy
    # change. The interest the classification serves is unconditional and is stated two sentences later, so
    # the pin moves onto it: no sources row may be written for a print that was never resolved. That clause
    # is true before the site gains playability and true after, because it is about *resolution*, not about
    # the site's identity — which is precisely the test this series uses.
    # Trade, stated: the pin no longer keeps the classification wording on the page. The classification stays
    # in `SITES.md` where it belongs — dated, and paired with the two measured caps behind it — and the next
    # slice takes the display half of the same paragraph (`Do not list it as scraped-and-playable anywhere`),
    # deliberately not this one, so slices 7 and 8 pin two obligations that fire alone instead of re-pinning
    # one proposition twice the way the two old state literals did.
    ("no sources row for a print that was never resolved", REPO_ROOT / "Fast_Fetch" / "SITES.md",
     "No `sources` row may be written for a print we have never resolved."),
    # Converted 2026-11-01 (q5, slice 8 — the last of the ordinary eight). The old literal was a per-site
    # status cell in the `SITES.md` inventory table: "**metadata + trailer evidence only; no playable print
    # is resolvable from this host**". Inventory rows are rewritten by whoever crawls next, so a pin living in
    # one is a timer on routine bookkeeping, and this one repeated slice 7's proposition rather than adding a
    # second obligation — the duplication the audit flagged. It now pins the display half of §25's verdict,
    # the obligation that the table row was only ever summarising: never present this site's rows as
    # scraped-and-playable to a user. Unconditional in the same way slice 7's write-law is — resolving a
    # playable print does not license advertising a play that is not there — and the two fire apart: a lane
    # that changes what may be *written* leaves the display sentence standing, and a lane that rewords the
    # display rule leaves the write rule standing.
    # What is NOT claimed: no pin in this file can prove what MovieBox serves today. That is an inventory
    # fact, it belongs in the table and in the dated §25 measurement, and it is deliberately unpinned now —
    # the guard checks laws, and a guard that checks ledgers goes red on true news.
    ("never present an unresolved site as scraped-and-playable", REPO_ROOT / "Fast_Fetch" / "SITES.md",
     "Do not list it as scraped-and-playable anywhere."),
]


class InvariantPhrasesTests(unittest.TestCase):
    """Every law sentence is still in the file every agent auto-loads."""

    def test_all_invariant_phrases_survive_the_diet(self):
        texts = {}
        missing = []
        for label, path, phrase in INVARIANTS:
            if not path.is_file():
                missing.append("%-58s file gone: %s" % (label, path.relative_to(REPO_ROOT)))
                continue
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

    def test_every_invariant_target_is_reachable_from_the_loaded_indexes(self):
        """A law kept in a file no index points at is a law nobody will read again.

        Every file this suite asserts against must be either one of the auto-loaded docs, or
        linked by name from `Fast_Fetch/CONTINUITY.md` / `docs/SESSION_CHECKPOINT.md`, or indexed
        by the README of the archive directory that holds it.
        """
        needles = flat("\n".join(load(p) for p in AUTO_LOADED + [CONTINUITY, CHECKPOINT]))
        indexes = {
            FF_CKPT: load(FF_CKPT / "README.md"),
            DOC_CKPT: load(DOC_CKPT / "README.md"),
            (REPO_ROOT / "App" / "docs"): "",
            REPO_ROOT / "docs": "",
        }
        unreachable = []
        for _label, path, _phrase in INVARIANTS:
            if path in AUTO_LOADED or path in (CONTINUITY, CHECKPOINT):
                continue
            if path.name in needles:
                continue
            holder = indexes.get(path.parent)
            if holder is not None and path.name in holder:
                continue
            unreachable.append("%s (%s)" % (path.relative_to(REPO_ROOT), _label))
        self.assertFalse(unreachable,
                         "law text present but unreachable from any index:\n"
                         + "\n".join(sorted(set(unreachable))))


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


class AbsorbedTrunkEditTests(unittest.TestCase):
    """The rebase-onto-`4fe6f65` guarantee: a lane's entry survives the rotation that happened
    under it, verbatim, in the archive layout, and is named by the indexes a lane actually reads.

    This is the enumeration the original suite could not have known about — it was written before
    trunk moved. A diet that only checks its own snapshot is the failure mode the diet exists to
    prevent, so any future lane that appends to an index here must extend this list, not delete it.
    """

    # (archive path, must-be-reachable-from, [headings / one-line claims that must not be lost])
    ABSORBED = [
        (FF_CKPT / "20261030-q2-themoviebox-crawl-2026-10-30-parser-fixes-detail-api-preference.md",
         (CONTINUITY, FF_CKPT / "README.md"),
         ["[Q2-MOVIEBOX-CRAWL] 2026-10-30 — parser fixes + detail-API preference; crawl gate closed",
          "q4 gate: DiscoveryTests were memory-floor failures, not feed regressions",
          "`test_themoviebox_detail_api.py` (new, offline): **18 tests green**",
          "themoviebox.db` = **44 posts / 0 releases / 0 sources**",
          "**NOT verified (network gate closed):**"]),
        (DOC_CKPT / "20261030-2026-10-30-04-15-qoder4-master-the-box-entered-the-halt-band.md",
         (CHECKPOINT, DOC_CKPT / "README.md"),
         ["2026-10-30 04:15 — qoder4 master: the box entered the halt band",
          "The finding that outranks the load number: the live tree is stale *and* dirty",
          "85 behind / 2 ahead",
          "22 of them backend"]),
        (DOC_CKPT / "20261030-2026-10-30-cont-moviedbox-detail-api-parser-credits-backdrop.md",
         (CHECKPOINT, DOC_CKPT / "README.md"),
         ["2026-10-30 (cont.) — MovieBox: detail-API parser, credits/backdrop/languages fixed",
          "**Load was 7.01 (gate 5.5), so step 1 did not run.**",
          "posts with zero sources is a FAIL"]),
    ]

    def test_absorbed_headings_survive_verbatim_in_their_archive(self):
        missing = []
        for path, _reachable, phrases in self.ABSORBED:
            if not path.is_file():
                missing.append("%s — the whole absorbed file is gone" % path.relative_to(REPO_ROOT))
                continue
            text = flat(load(path))
            for phrase in phrases:
                if phrase.rstrip() == phrase and flat(phrase) not in text:
                    missing.append("%s: %s" % (path.name, phrase[:72]))
        self.assertFalse(missing, "\nABSORBED TRUNK TEXT LOST:\n" + "\n".join(missing))

    def test_absorbed_files_are_named_by_the_index_a_lane_actually_reads(self):
        for path, reachable, _phrases in self.ABSORBED:
            holders = [p for p in reachable if p.is_file() and path.name in load(p)]
            self.assertTrue(holders,
                            "%s is not named by %s — the entry exists but nobody will find it"
                            % (path.name, [str(p.relative_to(REPO_ROOT)) for p in reachable]))

    def test_the_index_counts_are_the_directory_listings(self):
        """A pointer file that miscounts its own archives is a pointer nobody can follow.

        Both indexes open with "N session files cover …" / "N files cover …". That number used to
        be prose, and prose went stale the first time another lane added a file; now it is compared
        against the directory on every CI run.
        """
        claims = [(CONTINUITY, FF_CKPT, r"(\d+) session files"),
                  (CHECKPOINT, DOC_CKPT, r"(\d+) files cover")]
        for index, archive, pattern in claims:
            found = re.search(pattern, load(index))
            self.assertTrue(found, "%s lost its archive count claim" % index.name)
            actual = len([p for p in archive.glob("*.md") if p.name != "README.md"])
            self.assertEqual(int(found.group(1)), actual,
                             "%s claims %s archive files, %s holds %d"
                             % (index.relative_to(REPO_ROOT), found.group(1),
                                archive.relative_to(REPO_ROOT), actual))

    def test_trunk_added_no_line_that_is_now_nowhere(self):
        """Every line trunk appended to the two rotated logs exists somewhere in this tree.

        Re-checked against the trunk shas themselves rather than against my snapshot of them: if a
        future rotation drops a line, this fails even though the earlier conservation test — which
        only knows `dc73ac7` — stays green.
        """
        for rel in ("Fast_Fetch/CONTINUITY.md", "docs/SESSION_CHECKPOINT.md"):
            trunk = git_show("4fe6f65", rel)
            if trunk is None:
                self.skipTest("trunk sha not in this clone; offline guard cannot re-check it")
            before = git_show("dc73ac7", rel)
            added = set(trunk.splitlines()) - set(before.splitlines())
            corpus = flat("".join(load(p) for p in (CONTINUITY, CHECKPOINT)) + "".join(
                p.read_text(encoding="utf-8") for d in (FF_CKPT, DOC_CKPT) for p in d.glob("*.md")))
            lost = [line for line in added
                    if re.sub(r"^[-*#> \t]+", "", line).strip() and flat(line) not in corpus]
            self.assertFalse(lost, "%s: %d trunk line(s) exist nowhere after the rotation:\n%s"
                             % (rel, len(lost), "\n".join(sorted(lost)[:12])))


class ConflictMarkerTests(unittest.TestCase):
    """A resolved merge must not leave its tooling behind in the file.

    Measured 2026-10-30: landing two lanes' checkpoint entries onto the same index line left a
    bare `=======` in `Fast_Fetch/checkpoints/README.md`, and it reached trunk. It broke no test,
    because nothing looked for it, and the index kept claiming to be complete while carrying
    diff debris — which is worse than an obvious failure, since a lane trusts a pointer file.
    Stripping markers is a resolution step; a resolved file that still has them is unresolved.
    """

    #: The files more than one lane appends to, so the files a merge actually collides in.
    MERGED = AUTO_LOADED + [CONTINUITY, CHECKPOINT, ADMIN_DOC,
                            FF_CKPT / "README.md", DOC_CKPT / "README.md"]

    def test_no_lane_edited_file_carries_conflict_markers(self):
        offenders = []
        for path in self.MERGED:
            if not path.is_file():
                continue
            for n, line in enumerate(load(path).splitlines(), 1):
                if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line in ("<<<<<<<", "=======", ">>>>>>>"):
                    offenders.append("%s:%d %r" % (path.relative_to(REPO_ROOT), n, line[:20]))
        self.assertFalse(offenders, "unresolved merge markers:\n" + "\n".join(offenders))


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


class WorkflowSuiteCoverageTests(unittest.TestCase):
    """The gate is the module list in `backend-ci.yml`, re-derived on every run.

    A number in a doc is a memory; the workflow's own steps are the fact. Measured 2026-10-31
    at `babb06f`: 35 suite steps, 35 run commands, all 35 files present, and 86 test modules
    on disk — that is the receipt, never an assertion. Nothing here quotes a total: adding a
    suite, deleting or renaming a module, pointing a step at a file that does not exist, or
    running one module twice all fail without anyone editing a count.
    """

    STEP = re.compile(r"^\s*- name: 🧪\s+(\S+\.py)\b", re.M)
    RUN = re.compile(r"^\s*run:\s+(?:time\s+)?python3\s+-S\s+(\S*test_[a-z0-9_]+\.py)\s*$", re.M)

    #: Modules on disk that exist and are NOT in the gate. This is a DEFECT INVENTORY, not a
    #: policy: an unregistered suite does not run on anyone's push, so every name here is a
    #: known gap rather than a choice. The list is a ratchet, not a
    #: count: a NEW module must be registered in the workflow or added here with the reason it
    #: cannot run; registering one means deleting it here; deleting or renaming one fails too.
    #: What it enforces is `in_gate | UNREGISTERED == on_disk` — exact set equality, modulo the
    #: debt — which becomes plain equality the moment the debt is paid.
    UNREGISTERED = frozenset({
        "test_10xflix_import.py", "test_5movierulz_import.py", "test_7starhd_import.py",
        "test_9xmovies.py",
        "test_all_sites.py", "test_animahd_import.py", "test_aryplus_import.py",
        "test_audit_staging.py", "test_backfill_animated_flag.py", "test_backfill_tmdb.py",
        "test_bolly4u_import.py", "test_convert_mp4moviez.py", "test_desicinemas.py",
        "test_desiserials_import.py", "test_download_endpoint.py", "test_dramacool_import.py",
        "test_engagement.py", "test_filmiyin_import.py", "test_filmyhit_import.py",
        "test_filmywap_import.py", "test_filmyzilla_import.py", "test_hdhub4u_import.py",
        "test_hdtvb_import.py", "test_hindilinks4u.py", "test_hindilinks4u_retry.py",
        "test_host_resolvers.py", "test_import_humtv.py", "test_import_katmoviehd.py",
        "test_import_wp_family.py", "test_katmoviehd.py", "test_katmoviehd_import.py",
        "test_kisskh_import.py", "test_kuttymovies_import.py", "test_levidia_import.py",
        "test_moviecok_import.py", "test_moviesmela_import.py", "test_moviezguru.py",
        "test_mp4moviez_import.py", "test_multimovies_import.py", "test_pagalmovies_import.py",
        "test_rareanimes_import.py", "test_rogmovies_import.py",
        "test_ssrmovies_import.py", "test_stream_resolvers.py", "test_themoviebox_import.py",
        "test_toonworld4all.py", "test_vegamovies_import.py", "test_world4ufree_import.py",
    })

    def _steps(self):
        return [pathlib.PurePosixPath(p).name for p in self.STEP.findall(load(WORKFLOW))]

    def _runs(self):
        return [pathlib.PurePosixPath(p).name for p in self.RUN.findall(load(WORKFLOW))]

    def _on_disk(self):
        return {p.name for d in (BASE_DIR, BASE_DIR / "importers") for p in d.glob("test_*.py")}

    def test_every_step_names_the_module_its_run_command_runs(self):
        steps, runs = self._steps(), self._runs()
        self.assertTrue(steps, "backend-ci.yml has no 🧪 suite steps")
        self.assertEqual(steps, runs,
                         "a step's name and its run command disagree (or a suite lost its 🧪):\n"
                         "  not run: %s\n  not named: %s"
                         % (sorted(set(steps) - set(runs)), sorted(set(runs) - set(steps))))

    def test_no_suite_runs_twice(self):
        runs = self._runs()
        dupes = sorted({name for name in runs if runs.count(name) > 1})
        self.assertFalse(dupes, "a module runs in two steps: %s" % dupes)

    def test_every_step_runs_a_module_that_exists(self):
        missing = sorted(set(self._runs()) - self._on_disk())
        self.assertFalse(missing, "the gate runs modules that are not in the tree:\n"
                         + "\n".join(missing))

    def test_every_module_is_registered_or_recorded_as_debt(self):
        on_disk, in_gate = self._on_disk(), set(self._runs())
        undeclared = sorted(on_disk - in_gate - self.UNREGISTERED)
        self.assertFalse(undeclared,
                         "a module exists and runs on no one's push. Register it in "
                         "backend-ci.yml, or add it to UNREGISTERED with the reason it cannot "
                         "run:\n" + "\n".join(undeclared))
        registered = sorted(self.UNREGISTERED & in_gate)
        self.assertFalse(registered, "now in the gate; delete from UNREGISTERED:\n"
                         + "\n".join(registered))
        gone = sorted(self.UNREGISTERED - on_disk)
        self.assertFalse(gone, "deleted or renamed; prune UNREGISTERED:\n" + "\n".join(gone))


if __name__ == "__main__":
    print("fixture: %s (offline, markdown only — no network, no catalog)" % pathlib.Path(__file__).name)
    unittest.main(verbosity=2)
