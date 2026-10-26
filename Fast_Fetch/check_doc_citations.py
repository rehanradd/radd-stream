#!/usr/bin/env python3
"""Doc-citation drift check: does every `file.py:NNN` in the API docs still point
at code that says what the sentence says?

Why this file exists: `HANDOFF_apidocs.md` and `API_V2.md` pin their claims to line
numbers. A line number is the most fragile reference in the repo — one function
growing nine lines silently turns a correct doc into a doc that sends the next agent
to the wrong place, and nothing fails. This checker makes that failure audible
instead.

    python3 -S Fast_Fetch/check_doc_citations.py            # report
    python3 -S Fast_Fetch/check_doc_citations.py --quiet    # exit code only

Stdlib only, read-only, no database, no network.

The rule is a heuristic and deliberately conservative: a citation passes when the
window around the cited lines contains *something the sentence names* — either a
word that looks like an identifier (`_covered_episodes`, `cat_links`,
`print_version`) or the symbol from the nearest backtick group. Bare `:NNN`
continuations are skipped: their file comes from earlier prose, and guessing wrong
would report drift that isn't there.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DOCS = [BASE_DIR / "API_V2.md", BASE_DIR / "HANDOFF_apidocs.md"]

#: `api_v2.py:565`, `` `catalog_v2.py:1266` ``, `viewer.py:2526-2530`
CITED = re.compile(r"`?(?!\.)([a-z_0-9]+\.py)`?[:~](\d+)(?:-(\d+))?")
#: anything in the sentence that looks like a code identifier
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]{4,}")
#: a backtick group that names a symbol, e.g. `_finalize()` or `cat_links.state`
SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z_0-9./ ]{2,60}?)`")

#: module names in this directory: a sentence that cites `catalog_v2.py` names the
#: file, not a line in it, so the file's own stem can never prove a citation
MODULES = {p.stem for p in BASE_DIR.glob("*.py")}

#: English glue — never proof that a citation lands on the right line
STOP = {
    "the", "and", "for", "with", "that", "this", "from", "have", "same", "also",
    "into", "when", "which", "where", "must", "only", "none", "null", "true",
    "false", "cols", "line", "lines", "docs", "doc", "code", "path", "value",
    "values", "corrected", "already", "still", "never", "every", "either",
    "nothing", "anything", "because", "about", "against", "below", "above",
    "under", "after", "before", "those", "these", "them", "they", "there",
    "here", "what", "when", "how", "much", "many", "most", "less", "more",
    "built", "frozen", "keeps", "keep", "makes", "made", "uses", "used",
    "means", "meant", "shows", "shown", "gives", "given", "puts", "sets",
}


def _tokens(sentence: str, target: str) -> set[str]:
    """The code names a sentence claims, minus the module names it merely cites."""
    stem = target.rsplit(".", 1)[0]
    skip = {stem, f"{stem}.py"} | MODULES
    found = {w for w in IDENT.findall(sentence)
             if w.lower() not in STOP and w not in skip and not w.endswith("able")}
    for group in SYMBOL.findall(sentence):
        for tok in re.split(r"[./ ()]", group):
            if len(tok) >= 4 and tok not in skip:
                found.add(tok)
    return found


def check_doc(doc: Path) -> tuple[list[str], list[str]]:
    """Return (hard failures, suspects).

    A hard failure is provable: the file is gone or the line number is past the
    end of the file — the doc then points at nothing. A suspect is a heuristic
    judgement (no word the sentence names appears near the cited line) and is
    worth reading, not worth failing a build over.
    """
    hard: list[str] = []
    soft: list[str] = []
    lines = doc.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, 1):
        # a claim can wrap across two lines, so the prose that names the symbol
        # may sit on the line above the citation itself
        sentence = line if lineno == 1 else lines[lineno - 2] + " " + line
        for target, cited, last in CITED.findall(line):
            if not target:
                continue        # a bare `:NNN` inherits its file from earlier prose
            path = BASE_DIR / target
            if not path.is_file():
                hard.append(f"{doc.name}:{lineno}: {target} does not exist")
                continue
            body = path.read_text(encoding="utf-8").splitlines()
            start = int(cited) - 1
            if start >= len(body):
                hard.append(f"{doc.name}:{lineno}: {target}:{cited} is past the end "
                            f"of the file ({len(body)} lines)")
                continue
            end = int(last or cited)
            window = "\n".join(body[max(0, start - 6):end + 6])
            tokens = _tokens(sentence, target)
            if tokens and not any(tok in window for tok in tokens):
                soft.append(f"{doc.name}:{lineno}: {target}:{cited} — none of "
                            f"{sorted(tokens)[:6]} appears near that line")
    return hard, soft


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="print only the counts")
    parser.add_argument("--strict", action="store_true",
                        help="treat a heuristic suspect as a failure too")
    args = parser.parse_args(argv)
    hard: list[str] = []
    soft: list[str] = []
    for doc in DOCS:
        if doc.exists():
            h, s = check_doc(doc)
            hard.extend(h)
            soft.extend(s)
    if not args.quiet:
        for problem in hard:
            print(f"[X] {problem}")
        for problem in soft:
            print(f"[?] {problem}")
    print(f"[{'X' if hard else '✓'}] {len(DOCS)} docs: {len(hard)} broken, "
          f"{len(soft)} suspect")
    return 1 if hard or (args.strict and soft) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
