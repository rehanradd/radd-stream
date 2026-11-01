#!/usr/bin/env python3
"""The escaping guard: one tag function decides escaping, and nothing bypasses it.

Why a source scan and not a behaviour test
──────────────────────────────────────────
A behaviour test drives the renderer and asserts the *answer* is safe, and that
worked for the case it was written for. It cannot say anything about the next
renderer. The defect this refuses produced a correct-looking page every time the
catalog happened to hold a title without a `<` in it — and this catalog is built
by scraping other people's HTML, so a `<` in a title is a normal row, not an
attack. Twelve call sites each remembering to call an escaper is twelve chances to
forget one, and the forgetting is invisible.

So the rule is a refusal over the source, in the shape `App/app/src/test/kotlin/
com/raddstream/app/tooling/PhoneCredentialGuardTest.kt` established on the phone
side at `836c31f`: scan, plus the two controls that make a scan mean something.
  * Positive control: the detector is run against the exact pre-fix line and MUST
    report it. Without that, a scanner that matches nothing — a bad regex, an empty
    file list, a comment rule that waives everything — is green forever.
  * Negative control: the detector is run over a comment that merely *names* the
    pattern (this very file, and `viewer.py`'s own explanation of the bug), and the
    finding must be waived, or prose about a deleted defect gets mistaken for the
    defect. The waiver is line-shaped on purpose: it applies only to a line that is
    nothing but a comment, and it is proved against the real page comment.

What is refused
───────────────
1. A template literal that begins with markup and interpolates a value, in either
   page script, unless it is an `esc` one. `esc` escapes every interpolation by
   default; injecting markup requires wrapping the value in `raw()`, which is
   greppable and deliberate.
2. Any interpolation at all inside an `on*="…"` attribute. This is the one an
   escaper cannot fix: `escapeHtml` turns a `'` into `&#39;`, the browser decodes it
   back to `'` *before* parsing the script that lives in the attribute, so the
   escaped form is exactly as breakable as the raw one. Values go in `data-*`.
3. A second escaper. Exactly one `escapeHtml` definition per page, one `esc` tag,
   and `ESCAPE_CORE_JS` shipped verbatim into both pages, so the dashboard's escaper
   and the PWA's cannot drift. On the Python side, exactly one `html.escape` call —
   inside `_e` — and every HTML builder using `_e`.
4. A `data-action` with no handler in that page's action map: a button that lost its
   function silently is the same class of defect as one that lost its escaping.
5. `?token=` anywhere in these files. The credential left the URL for good; a
   regression here would put it back into browser history, the `Referer`, and the
   nginx access log.

Run: python3 -S Fast_Fetch/test_html_escape_guard.py
"""
import ast
import functools
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIEWER_SOURCE = (HERE / "viewer.py").read_text(encoding="utf-8")
ADMIN_SOURCE = (HERE / "admin_panel.py").read_text(encoding="utf-8")

#: The two page scripts that build markup out of catalog rows, and the Python module
#: that builds the operator panel's HTML.
PAGES = ("DASHBOARD_HTML", "MOBILE_CLIENT_HTML")


def string_constant(source, name):
    """The value of a top-level `NAME = "…"` assignment, without importing the file.

    Importing `viewer` to read a constant would open databases; the guard is a text
    check and stays one.
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    value = node.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        return value.value
                    if (isinstance(value, ast.BinOp)
                            and isinstance(value.left, ast.Constant)
                            and isinstance(value.right, ast.Constant)):
                        return str(value.left.value) + str(value.right.value)
    raise AssertionError(f"{name} is not a plain string constant any more")


@functools.lru_cache(maxsize=None)
def viewer_page(name):
    """A page constant assembled from `PART + ESCAPE_CORE_JS + PART`.

    Concatenation order is preserved by walking the expression in source order. The
    first version of this used a queue, which returned the *last* literal before the
    first two, and the guard then scanned a page whose `</script>` came before its
    `<script>` — a permutation that still contained every fragment and so passed the
    "the core is shipped" test while testing nothing about the real document.
    """
    def flatten(node, parts):
        if isinstance(node, ast.BinOp):
            flatten(node.left, parts)
            flatten(node.right, parts)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(node.value)
        elif isinstance(node, ast.Name) and node.id == "ESCAPE_CORE_JS":
            parts.append(ESCAPE_CORE_JS)
        else:
            return False
        return True

    for node in ast.parse(VIEWER_SOURCE).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        parts = []
        if flatten(node.value, parts) and "".join(parts):
            return "".join(parts)
    raise AssertionError(f"{name} is not assembled from literals plus ESCAPE_CORE_JS")


ESCAPE_CORE_JS = string_constant(VIEWER_SOURCE, "ESCAPE_CORE_JS")

# ── what is scanned, and what is only prose about what was scanned ───────────

def page_script(page):
    """The JavaScript of a page, as a browser would take it: `<script>` to `</script>`.

    Both JS detectors run over this and nothing else. An interpolation can only exist
    inside a template literal, and every template literal in these pages lives in the
    script body, so scoping to it is complete; and it keeps the HTML and CSS above and
    below the script out of a JS-shaped scan. The static markup a Python f-string
    builds is scanned separately, in `admin_panel.py`.
    """
    blocks = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
    if len(blocks) != 1:
        raise AssertionError(f"expected one script block, found {len(blocks)}")
    return blocks[0]


#: A line whose first non-space characters are one of these explains code instead of
#: being code. Documenting a retired defect is how the next author avoids repeating
#: it, so a finding on such a line is waived.
COMMENT_LINES = ("//", "/*", "*", "<!--", "#")


def split_findings(js, findings, label):
    """Detector output, divided into prose and executable code.

    This replaced a JavaScript comment stripper, and the reason is worth keeping: a
    stripper cannot be written correctly with a two-character window. `ESCAPE_CORE_JS`
    contains the regex literal `/[&<>"']/g`, whose `"` opens a "string" that does not
    close where the stripper expects, so every comment after it survived as code and
    the guard reported its own explanatory comment as the defect. Deciding whether a
    line is a comment needs no lexer, is visible in the failure message, and stays
    strict in the direction that matters: markup quoted in a comment that shares its
    line with real code is still refused.
    """
    lines = js.splitlines()
    prose, code = [], []
    for number, text in findings:
        source = lines[number - 1] if 0 < number <= len(lines) else ""
        entry = f"{label}:{number} {text}"
        (prose if source.lstrip().startswith(COMMENT_LINES) else code).append(entry)
    return prose, code


def without_docstrings(source):
    """Every module/class/function docstring blanked out of a Python source.

    The module banner is the place where this file explains that `?token=` is gone,
    and prose that names a retired defect must not fail the build — the alternative
    is that the next author is forbidden from documenting the bug and repeats it.
    Code, including any string literal that actually builds a URL, is still scanned.
    """
    lines = source.splitlines(keepends=True)
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        literal = first.value
        for number in range(literal.lineno, literal.end_lineno + 1):
            text = lines[number - 1]
            start = literal.col_offset if number == literal.lineno else 0
            stop = literal.end_col_offset if number == literal.end_lineno else len(text)
            lines[number - 1] = text[:start] + " " * (stop - start) + text[stop:]
    return "".join(lines)


def line_of(text, index):
    return text.count("\n", 0, index) + 1


# ── the detectors ────────────────────────────────────────────────────────────

#: A backtick that opens a template literal whose first non-space content is a tag.
#: The `(^|[^\w$])` half is what excludes `esc\``: the character before the backtick
#: in that case is `c`, a word character.
MARKUP_TEMPLATE = re.compile(r"(?:^|[^\w$])`[ \t]*\n?[ \t]*<", re.MULTILINE)
INTERPOLATED_ATTRIBUTE = re.compile(r"""on[a-z]+="[^"]*[\${]""")


def unescaped_markup_templates(js):
    """Template literals that open with markup, interpolate, and are not `esc`."""
    findings = []
    for match in MARKUP_TEMPLATE.finditer(js):
        opening = match.end() - 1
        closing = js.find("`", opening + 1)
        body = js[opening + 1:closing] if closing > opening else js[opening + 1:]
        if "${" in body:
            findings.append((line_of(js, match.start()),
                             js[match.start():match.end() + 40].strip()[:70]))
    return findings


def interpolated_attributes(js):
    return [(line_of(js, match.start()), match.group(0)[:70])
            for match in INTERPOLATED_ATTRIBUTE.finditer(js)]


#: Each page and the one action map that answers its buttons. A page checked
#: against the other page's map would pass on handlers it does not ship.
PAGE_ACTION_MAPS = {"DASHBOARD_HTML": "ACTIONS", "MOBILE_CLIENT_HTML": "CLIENT_ACTIONS"}


def action_handlers_defined(js, map_name):
    """Every `data-action="x"` this page emits, and every `x` its map handles."""
    used = set(re.findall(r'data-action="([^"${]+)"', js))
    block = re.search(r"const " + map_name + r" = \{(.*?)\n[ ]{4}\};", js, re.DOTALL)
    declared = set()
    if block:
        #: `'x': fn` — the colon follows the closing quote with no space, so the
        #: pattern cannot require one; requiring it silently declared an empty map
        #: and made "every button has a handler" pass by looking at nothing.
        declared = set(re.findall(r"""['"]([a-z][a-z0-9-]*)['"]\s*:""",
                                  block.group(1)))
    return used, declared


#: An interpolation whose value comes from a call — `${num(p.id)}`, `${raw(…)}`.
#: Only the *leading* callee is read. `${p.id}` is a property lookup and is none of
#: this detector's business, and a call that is not first in the interpolation
#: (`${a ? f(x) : g(y)}`) is also not read; this guard refuses the shape these pages
#: actually use to build a fragment, and does not claim to be an interpreter.
LEADING_INTERPOLATED_CALL = re.compile(r"\$\{([A-Za-z_$][\w$]*)\(")

#: Names the JS environment provides before any page writes one.
JS_GLOBALS = frozenset({
    "String", "Number", "Boolean", "Array", "Object", "Math", "Date", "JSON",
    "RegExp", "Map", "Set", "Promise", "Symbol", "Error", "encodeURIComponent",
    "decodeURIComponent", "parseInt", "parseFloat", "isNaN", "fetch", "alert",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval", "structuredClone",
})


def defined_functions(js):
    """Every name this script binds as a function, by any of the three spellings.

    Deliberately presence-based rather than scope-based: `renderStats()` declares its
    own local `num` that means something different from the core's, and a text scan
    cannot tell those apart. That is the accepted weakness — this guard catches the
    name that exists *nowhere*, which is the typo that ships a broken row.
    """
    return (set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", js))
            | set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", js)))


def undefined_interpolated_calls(js):
    """A `${fn(…)}` in this page whose `fn` this page never defines.

    This exists because the escaping pass wrote JavaScript that no test on any host
    executes. `num()` inside `DASHBOARD_HTML` is the whole reason a playlist link
    survives its own interpolation: if the name is misspelled or the core stops
    shipping it, every row loses its button, and all seventeen Python tests over that
    page still pass, because no Python test runs a browser.
    """
    defined = defined_functions(js)
    findings = []
    for match in LEADING_INTERPOLATED_CALL.finditer(js):
        name = match.group(1)
        if name in defined or name in JS_GLOBALS:
            continue
        findings.append((line_of(js, match.start()),
                         js[match.start():match.start() + 60].split("\n")[0].strip()))
    return findings


class EscapeGuardTests(unittest.TestCase):
    """The refusal itself."""

    @staticmethod
    def js(name):
        """This page's script body, exactly as it ships."""
        return page_script(viewer_page(name))

    def code_findings(self, detector):
        """Every finding this detector makes on a line of executable code.

        Findings on comment-only lines are returned by `split_findings` as prose and
        deliberately dropped here; `DetectorControlsTests` proves the prose bucket is
        populated by the real files, so the drop is not the same thing as blindness.
        """
        offenders = []
        for name in PAGES:
            js = self.js(name)
            offenders += split_findings(js, detector(js), name)[1]
        return offenders

    def test_the_sharing_constant_is_shipped_into_both_pages(self):
        for name in PAGES:
            page = viewer_page(name)
            self.assertIn(ESCAPE_CORE_JS, page,
                          f"{name} no longer carries the shared escaping core, so "
                          "the two pages now have two escapers that can drift")

    def test_no_markup_template_reaches_html_without_the_esc_tag(self):
        offenders = self.code_findings(unescaped_markup_templates)
        self.assertEqual([], offenders,
                          "a value reached markup without `esc`. Found:\n"
                          + "\n".join(offenders))

    def test_nothing_is_interpolated_into_an_event_handler_attribute(self):
        offenders = self.code_findings(interpolated_attributes)
        offenders += split_findings(ADMIN_SOURCE,
                                    interpolated_attributes(ADMIN_SOURCE),
                                    "admin_panel.py")[1]
        self.assertEqual([], offenders,
                          "an `on*= attribute holds an interpolated value. No escaper "
                          "can make that context safe — put the value in a data-* "
                          "attribute. Found:\n" + "\n".join(offenders))

    def test_one_escaper_per_page_and_one_on_the_python_side(self):
        for name in PAGES:
            js = self.js(name)
            self.assertEqual(1, js.count("const escapeHtml ="),
                             f"{name} declares its own escaper again")
            self.assertEqual(1, js.count("const esc = ("),
                             f"{name} declares its own template tag again")
            self.assertEqual(0, js.count("function escapeHtml"),
                             f"{name} carries a second, older escaper")
        self.assertEqual(1, ADMIN_SOURCE.count("html.escape("),
                         "`_e` is the one Python escaper; a second call is a second "
                         "set of semantics")
        self.assertIn("def _e(", ADMIN_SOURCE, "_e is gone from the module")

    def test_every_button_that_carries_an_action_has_a_handler(self):
        for name, map_name in PAGE_ACTION_MAPS.items():
            js = self.js(name)
            used, declared = action_handlers_defined(js, map_name)
            self.assertTrue(used, f"{name} emits no data-action at all, so this "
                                  "test would pass on an empty page")
            self.assertTrue(declared, f"{name} lost its {map_name} map entirely")
            self.assertEqual(set(), used - declared,
                             f"{name} renders a data-action nobody answers")

    def test_no_credential_in_a_url_anywhere_on_the_operator_surface(self):
        """`?token=` was the leak; a regression would put the secret back into the
        browser history, the `Referer` and the nginx access log.

        Comment lines and docstrings are excluded because both files *describe* the
        retired defect; every line that executes, including a string literal that
        builds a URL, is still refused.
        """
        scanned = (("DASHBOARD_HTML", viewer_page("DASHBOARD_HTML")),
                   ("MOBILE_CLIENT_HTML", viewer_page("MOBILE_CLIENT_HTML")),
                   ("admin_panel.py", without_docstrings(ADMIN_SOURCE)),
                   ("viewer.py", without_docstrings(VIEWER_SOURCE)))
        offenders = [(label, line.strip()) for label, text in scanned
                     for line in text.splitlines()
                     if "?token=" in line and not line.lstrip().startswith(COMMENT_LINES)]
        self.assertEqual([], offenders,
                         "a credential went back into a URL:\n"
                         + "\n".join(f"{label}: {line}" for label, line in offenders))

    def test_the_two_pages_agree_on_the_data_attribute_rule(self):
        """Both pages read their ids back through `num()`/`Number()`, so a scraped
        value can never be executed as code by the handler that reads it."""
        for name in PAGES:
            js = self.js(name)
            for match in re.finditer(r'data-(?:value|id|key|crawler)="([^"]*)"', js):
                self.assertIn("${", match.group(0),
                              "a data attribute that is not an interpolation")

    def test_every_function_an_interpolation_calls_is_defined_on_the_same_page(self):
        """No page may call a helper it does not ship.

        Written the day the escaping pass went in, because that pass was the first
        change to this JavaScript that every one of our tests could pass while the
        page was broken. `num()` is now inside the playlist anchor, the probe button
        and the heal button; delete its definition or misspell it and each row loses
        its VLC link, and no Python test notices, because no Python test runs a
        browser. The runner is the only machine here that executes this file, and it
        executes it as text — which is the honest description of what is being
        claimed: not "the page works", but "no call in it names nothing".
        """
        offenders = self.code_findings(undefined_interpolated_calls)
        self.assertEqual([], offenders,
                          "an interpolation calls a function this page never "
                          "defines:\n" + "\n".join(offenders))

    def test_the_undefined_call_detector_has_something_to_look_at(self):
        """Positive control for the case above: the real pages contain interpolated
        calls, so a detector that matched nothing would report green blindness."""
        seen = set()
        for name in PAGES:
            js = self.js(name)
            called = {match.group(1)
                      for match in LEADING_INTERPOLATED_CALL.finditer(js)}
            self.assertEqual(set(), called - defined_functions(js) - JS_GLOBALS,
                             f"{name}: the control's universe disagrees with the "
                             "detector")
            seen |= called
        self.assertIn("num", seen,
                      f"no `${{fn(…)}}` found in either page; scanned universe is "
                      f"{sorted(seen)}")


class DetectorControlsTests(unittest.TestCase):
    """The two controls that make a scan mean something.

    Without them, the worst failure of a scanner is not a false positive: it is a
    regex that quietly matches nothing, and a green suite that has stopped looking.
    """

    PRE_FIX_SINK = 'html += `<div class="media-title">${p.clean_title}</div>`;'
    PRE_FIX_HANDLER = ('<button class="btn-action" '
                       'onclick="copyToClipboard(\'${s.final_url}\')">Copy</button>')
    FIXED_SINK = "html += esc`<div class=\"media-title\">${p.clean_title}</div>`;"
    FIXED_HANDLER = ('<button class="btn-action" data-action="copy-url" '
                     'data-value="${s.final_url}">Copy</button>')

    def test_the_detector_catches_the_line_it_was_written_for(self):
        self.assertTrue(unescaped_markup_templates(self.PRE_FIX_SINK),
                        "the markup-template detector matches nothing, which makes "
                        "every other test in this file decoration")
        self.assertTrue(interpolated_attributes(self.PRE_FIX_HANDLER),
                        "the attribute detector matches nothing")

    def test_the_detector_passes_the_fixed_form(self):
        self.assertEqual([], unescaped_markup_templates(self.FIXED_SINK))
        self.assertEqual([], interpolated_attributes(self.FIXED_HANDLER))

    def test_a_call_of_an_undefined_helper_is_caught_and_a_defined_one_is_not(self):
        """Controls for `undefined_interpolated_calls`, the newest detector.

        The shape it exists for is exactly what the escaping pass produced: a page
        that calls `num()` inside a template and defines `num()` somewhere else, or
        nowhere. Both directions are asserted, because a name set built by a regex
        that matches nothing reports every page as clean.
        """
        missing = 'html += esc`<a href="/api/m3u?id=${num(p.id)}">VLC</a>`;'
        self.assertEqual(1, len(undefined_interpolated_calls(missing)),
                         "the detector does not see a call of a name nothing defines")
        for spelling in ("    const num = v => String(v);\n",
                         "    function num(v) { return String(v); }\n"):
            self.assertEqual([], undefined_interpolated_calls(spelling + missing),
                             f"`{spelling.strip()}` is a real definition and was "
                             "reported as missing")
        self.assertEqual([], undefined_interpolated_calls(
            'html += `${p.id} · ${encodeURIComponent(p.slug)} · ${String(x)}`;'),
            "a property lookup or a JS global is not a missing helper")

    def test_prose_about_the_defect_is_not_the_defect(self):
        """A comment naming the pattern must not fail the build — the alternative is
        that nobody may describe the bug anywhere, and the next author repeats it.

        The detector is asserted to fire before the waiver is asserted. Waiving a
        finding and never making one look identical in a green suite and are not the
        same thing.
        """
        prose = ('  // The bug was `onclick="copyToClipboard(\'${s.final_url}\')"`\n'
                 '  // and `<b>${p.title}</b>` reached HTML unescaped.\n')
        self.assertTrue(unescaped_markup_templates(prose),
                        "the markup detector is blind, so the waiver below is "
                        "decoration")
        self.assertTrue(interpolated_attributes(prose),
                        "the attribute detector is blind")
        self.assertEqual([], split_findings(prose, unescaped_markup_templates(prose),
                                           "fixture")[1])
        self.assertEqual([], split_findings(prose, interpolated_attributes(prose),
                                            "fixture")[1])
        self.assertEqual(1, len(split_findings(prose, interpolated_attributes(prose),
                                               "fixture")[0]))

    def test_a_comment_that_shares_its_line_with_code_is_not_waived(self):
        """The waiver is for lines that are *only* commentary. A sink quoted after a
        statement on the same line stays refused, so the rule cannot be satisfied by
        commenting an unsafe template back into existence at the end of a line. The
        `//example.com` in the same fixture is a URL in code, not a comment: nothing
        here needs a JavaScript lexer to tell the two apart, which is the whole point —
        the lexer this file used to have read the regex literal `/[&<>"']/g` as a
        string and reported the guard's own comment as the defect."""
        mixed = ('const u = "//example.com/x";\n'
                 'html += "<i></i>"; // the old sink was `<b>${p.title}</b>`\n')
        findings = unescaped_markup_templates(mixed)
        self.assertTrue(findings, "the detector stopped matching")
        prose, code = split_findings(mixed, findings, "fixture")
        self.assertEqual([], prose)
        self.assertEqual(1, len(code), code)

    def test_the_action_map_detector_reads_a_real_map(self):
        """A handler set that comes back empty makes the button test vacuous, so the
        shape it parses has to be proved against a page that is deliberately broken."""
        page = ("    const ACTIONS = {\n"
                "      'copy-url': el => copyToClipboard(el.dataset.value),\n"
                "    };\n"
                "    html += esc`<button data-action=\"copy-url\">Copy</button>`;\n"
                "    html += esc`<button data-action=\"no-handler\">Zap</button>`;\n")
        used, declared = action_handlers_defined(page, "ACTIONS")
        self.assertEqual({"copy-url"}, declared, "the map was parsed but read empty")
        self.assertEqual({"copy-url", "no-handler"}, used)
        self.assertEqual({"no-handler"}, used - declared)

    def test_a_docstring_naming_the_retired_defect_is_not_the_defect(self):
        source = ('"""The panel used to write `?token=` into its own form."""\n'
                  "def build():\n"
                  '    """No `?token=` any more."""\n'
                  '    return "/api/data?token=" + secret\n')
        stripped = without_docstrings(source)
        self.assertNotIn("?token=", stripped.splitlines()[0],
                         "the module docstring survived, so the banner would fail "
                         "the build for describing the fix")
        self.assertIn("?token=", stripped,
                      "the blanking ate executable code, not just prose")

    def test_the_pages_own_comment_about_the_defect_is_not_reported(self):
        """The dashboard explains the bug in a `//` comment inside its own script,
        quoting the broken line. The detector must SEE that quote — otherwise the
        waiver below proves nothing — and must then put it in prose, not in code."""
        raw = page_script(viewer_page("DASHBOARD_HTML"))
        self.assertIn("""onclick="viewInDb('${""", raw,
                      "the explanatory comment is gone from the page, so this control "
                      "no longer exercises anything")
        findings = interpolated_attributes(raw)
        self.assertTrue(any("""onclick="viewInDb('${""" in text
                            for _number, text in findings),
                        "the detector does not match the real pre-fix line, which "
                        "would make every refusal in this file decoration")
        _prose, code = split_findings(raw, findings, "DASHBOARD_HTML")
        self.assertEqual([], code,
                          "the page's own documentation of the defect fails the build")

    def test_the_reassembled_page_is_a_document_not_a_bag_of_fragments(self):
        """Order control for `viewer_page` itself: a page whose closing tag precedes
        its opening tag is a permutation, and every detector would still find each
        fragment in it."""
        for name in PAGES:
            page = viewer_page(name)
            self.assertEqual(1, page.count("<script>"),
                             f"{name} no longer holds exactly one script block")
            self.assertLess(page.index("<script"), page.index("</script>"),
                            f"{name} was reassembled out of source order")
            self.assertGreater(len(page_script(page)), 1000,
                               f"{name}'s script body is a stub; nothing to scan")

    def test_the_guard_reads_real_source_not_a_fixture(self):
        """A scan of an empty file list is green forever; assert the files under
        scan are the ones this repo ships and that they are large."""
        self.assertTrue(VIEWER_SOURCE.startswith("#!/usr/bin/env python3")
                        or "DASHBOARD_HTML" in VIEWER_SOURCE)
        self.assertGreater(len(VIEWER_SOURCE), 50_000)
        self.assertGreater(len(ADMIN_SOURCE), 50_000)
        self.assertGreater(len(ESCAPE_CORE_JS), 500)


#: One `<button … role="tab" …>` tag, opening bracket to closing bracket. The
#: attributes wrap across source lines, so the unit scanned here is the tag, not a line.
TAB_BUTTON_TAG = re.compile(r'<button[^>]*role="tab"[^>]*>', re.DOTALL)


def tab_buttons(page):
    return TAB_BUTTON_TAG.findall(page)


def tag_attribute(tag, name):
    match = re.search(re.escape(name) + r'="([^"]*)"', tag)
    return match.group(1) if match else None


def balanced(text, opening_index):
    """The text from `text[opening_index]` (an open bracket) through its match."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    opening, closing = text[opening_index], pairs[text[opening_index]]
    depth, index = 0, opening_index
    while index < len(text):
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return text[opening_index:index + 1]
        index += 1
    raise AssertionError(f"unbalanced {opening!r} at offset {opening_index}")


def function_body(js, name):
    """The braces of `function name(…) {…}`, so a test can ask what the body does."""
    start = js.index("function " + name + "(")
    return balanced(js, js.index("{", start))


def event_listener(js, event_name):
    """The whole `addEventListener('name', …)` call, brackets counted."""
    start = js.index("addEventListener('" + event_name + "'")
    return balanced(js, js.index("(", start))


class TabSurfaceTests(unittest.TestCase):
    """The tab strip claims a structure, so the structure is now a tested fact.

    `role="tablist"` and `aria-selected` are not decoration: they change what keys a
    screen-reader user expects to press and what the page answers with. A claim the
    code does not keep is worse than no claim, because the user is told the page
    behaves one way while it behaves another. So each half of the contract — the
    markup's claim, the click's answer, and the keys the strip announces — is asserted
    against the shipped source here, the same way the escaping shape is asserted: as a
    scan, so the next author who adds a third tab either satisfies it or reads this
    file. Offline; no browser, no DOM, no server.
    """

    #: A tab button from before this contract: it paints `active`, calls a global
    #: straight from the markup, and says nothing about what it controls.
    PRE_FIX_TAB = ('<button class="tab-btn active" id="tab-db-btn" '
                   'onclick="switchMainTab(\'db\')">💾 Indexed Database Releases</button>')

    def test_every_tab_claims_a_panel_that_exists_on_the_same_page(self):
        for tag in tab_buttons(viewer_page("DASHBOARD_HTML")):
            panel = tag_attribute(tag, "aria-controls")
            self.assertTrue(panel, f"tab markup claims a role without a panel: {tag}")
            self.assertIn(f'id="{panel}"', viewer_page("DASHBOARD_HTML"),
                          f"aria-controls names {panel!r}, which the page does not contain")
            self.assertTrue(tag_attribute(tag, "aria-selected"),
                            f"{tag} is a tab that never says whether it is selected")
            self.assertEqual(tag_attribute(tag, "data-action"), "switch-tab",
                             f"a tab that selects itself from its own markup is an "
                             f"inline handler, not a delegated action: {tag}")

    def test_the_state_moves_with_the_paint(self):
        """`classList.toggle('active')` alone is the old defect: the page looks
        right and reads wrong, which is invisible to whoever depends on the reading."""
        body = function_body(page_script(viewer_page("DASHBOARD_HTML")), "switchMainTab")
        self.assertIn("aria-selected", body)
        self.assertIn("tabIndex", body)

    def test_the_tablist_answers_the_keys_it_announces(self):
        script = page_script(viewer_page("DASHBOARD_HTML"))
        self.assertIn("'keydown'", script,
                      "a tablist that announces itself and takes no arrow keys is a lie")
        handler = event_listener(script, "keydown")
        for key in ("ArrowRight", "ArrowLeft"):
            self.assertIn(key, handler, f"the tablist claims tabs and ignores {key}")
        self.assertIn("switchMainTab", handler)

    def test_no_tab_reaches_for_a_global_from_its_markup(self):
        page = viewer_page("DASHBOARD_HTML")
        self.assertNotIn('onclick="switchMainTab', page,
                         "delegated actions are the rule; an inline handler is how "
                         "the copy-to-clipboard defect was written in the first place")
        _, declared = action_handlers_defined(page_script(page), "ACTIONS")
        self.assertIn("switch-tab", declared,
                      "a data-action with no handler in the map is a dead button")
        #: `used` is a scan of the *script*, and the two tab buttons are static markup
        #: above it, so their action never appears in `used`. Asserting it there would
        #: be a check against the wrong surface. The claim that matters is the one the
        #: browser can actually break: every action the markup asks for is in the map.
        for tag in tab_buttons(page):
            action = tag_attribute(tag, "data-action")
            self.assertIn(action, declared,
                          f"markup asks for {action!r}, which no handler is registered "
                          f"for: {tag}")

    def test_the_tab_detector_has_something_to_look_at(self):
        """Proved against the pre-fix markup, as every detector in this file is. A
        guard that matches nothing is a green light that stopped looking."""
        real = tab_buttons(viewer_page("DASHBOARD_HTML"))
        self.assertGreaterEqual(len(real), 2,
                                f"the dashboard has {len(real)} tabs, and this class "
                                "would be scanning an empty list")
        for tag in real:
            self.assertTrue(tag_attribute(tag, "aria-controls"), tag)
        self.assertEqual([], tab_buttons(self.PRE_FIX_TAB),
                          "the detector also matches a button that claims no role, so "
                          "it is not scanning tabs at all")
        self.assertIsNone(tag_attribute(self.PRE_FIX_TAB, "aria-controls"),
                          "the pre-fix spelling must still fail the check it was "
                          "written to fail")


if __name__ == "__main__":
    unittest.main(verbosity=2)
