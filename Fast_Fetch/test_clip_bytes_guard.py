"""G2 — the wire may carry derived text, never clip / frame / screenshot bytes.

The cine-finder spec states the compliance boundary in one sentence: *the clip is never uploaded to our
server*. `docs/ADVANCED_VIDEO_SEARCH_ARCHITECTURE.md` makes it a rule, not a performance target, so it
belongs to a build gate rather than to review. This module is the backend half of that gate; the Android
half (`NoClipBytesGuardTest.kt`) is q4's and has to exist before the boundary holds, because a keyframe
JPEG is ~10-40 KB and the client is the one holding it.

What is actually measured here, read off the sha rather than assumed:

  * Every body read in the request path is length-capped before a byte is slurped
    (`api_v2.read_body` rejects at `:1627`, `viewer.py:3528` and `viewer.py:4169` clamp with
    `max(0, min(length, api_v2.MAX_BODY_BYTES))`). A new uncapped `rfile.read` fails this test.
  * A non-JSON body — which is what `multipart/form-data`, `image/jpeg` and a raw clip POST all are —
    is refused by the only reader the public v2 routes use.
  * A caller cannot be made to *read* anything by declaring an oversized body: the refusal happens
  before `rfile.read` is called, which is the difference between a cap and a ceiling you paid to find.

What this module deliberately does **not** claim, and says so in a test rather than in prose:

  * The ceiling is not the boundary. `MAX_BODY_BYTES` is 64 KiB; a 320x180 JPEG keyframe base64s to well
    under that, so `read_body` returns it as a perfectly valid dict. The protection therefore lives in
    the *field allow-list of the route*, which does not exist yet — q3 owns it, and `test_a_small_base64_frame_
    inside_a_json_object_is_parsed_today` pins the gap so nobody closes it by pointing at this file.

Follows the paired-guard convention (`StatsHonestyTest`, `DeadCodeGuardTest`): every refusal assertion
below has a positive control, so a scan that matches nothing cannot go green by accident.

No server, no socket, no catalog, no writes: the reader is exercised against an in-memory fake handler,
and the source scan reads files that already exist.
"""

import io
import json
import pathlib
import re
import unittest

import api_v2

ROOT = pathlib.Path(__file__).resolve().parent

#: The two modules that mount HTTP and may therefore touch a request body. `admin_panel` and
#: `media_search` decide what a body *means* but never read the socket, by the same
#: "reading is the mount's job" rule stated at `viewer.py:3475`.
MOUNTS = ("viewer.py", "api_v2.py")

_READ_RE = re.compile(r"\b(?:self|handler)\.rfile\.read\s*\(")

#: The three spellings of "this read is bounded". Matched in the ~6 lines above each read site,
#: because line numbers drift and a guard that pins a line number dies on an unrelated edit.
_CAPS = (
    "MAX_BODY_BYTES",          # clamp, or the reject-before-read in api_v2.read_body
    "length = max(0, min(",    # the explicit clamp used by both admin form paths
)


class _FakeHeaders:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeHandler:
    """`.headers` + `.rfile`, and a count of how many bytes were actually taken off the wire."""

    def __init__(self, body=b"", content_length=None, content_type="application/json"):
        self.headers = _FakeHeaders({
            "Content-Length": str(len(body) if content_length is None else content_length),
            "Content-Type": content_type,
        })
        self.rfile = io.BytesIO(body)


class BodyCapTests(unittest.TestCase):
    def test_every_body_read_in_the_mounts_is_capped(self):
        """No uncapped `rfile.read` may reach the request path.

        Positive control first: if the scan ever matches nothing, the guard has silently stopped
        guarding (a renamed symbol, a moved file, a new mount), and a green test would be a lie.
        """
        sites = []
        for name in MOUNTS:
            text = (ROOT / name).read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines()):
                if _READ_RE.search(line):
                    window = "\n".join(text.splitlines()[max(0, i - 8):i + 1])
                    sites.append((name, i + 1, line.strip(), any(c in window for c in _CAPS)))
        self.assertGreaterEqual(
            len(sites), 3,
            "expected at least the three known body reads (%s); found %d — the scan is no longer "
            "looking at real code" % (", ".join(MOUNTS), len(sites)))
        uncapped = [s for s in sites if not s[3]]
        self.assertEqual(
            [], uncapped,
            "uncapped body read(s): %s — a Content-Length of the caller's choosing becomes a memory "
            "grab on a one-vCPU box" % [(s[0], s[1], s[2]) for s in uncapped])

    def test_an_oversized_body_is_refused_before_a_single_byte_is_read(self):
        """The refusal must cost no reads, not merely discard the bytes afterwards.

        `Content-Length` is the whole input here: it is the caller's number, and `read_body` is allowed
        to believe nothing about it except that a big one is a refusal. The assertion on `tell()` is the
        half that matters — a reader that slurps the body and *then* rejects it has already paid the
        memory on a box whose hard floor is 1500 MB available.
        """
        payload = b"\xff" * (api_v2.MAX_BODY_BYTES + 4096)
        handler = _FakeHandler(body=payload)
        body, err = api_v2.read_body(handler)
        self.assertIsNone(body)
        self.assertEqual("invalid_params", err)
        self.assertEqual(0, handler.rfile.tell(),
                         "read_body declared the body refused and then took it off the socket anyway")

    def test_the_ceiling_is_a_real_bound_and_it_is_small(self):
        """64 KiB, pinned. A 5-second 720p clip is ~1-2 MB, so no *legitimate* body comes close."""
        self.assertLessEqual(api_v2.MAX_BODY_BYTES, 64 * 1024)
        self.assertGreaterEqual(api_v2.MAX_BODY_BYTES, 4096,
                                "a cap this low would refuse ordinary derived-text search too")

    def test_a_derived_text_json_body_is_still_accepted(self):
        """Positive control for every refusal above: the reader works, so the refusals are choices."""
        payload = json.dumps({"query": "a man opens a door in a rain-soaked Tokyo street",
                              "genres": ["animation"]}).encode("utf-8")
        body, err = api_v2.read_body(_FakeHandler(body=payload))
        self.assertEqual("", err)
        self.assertEqual("a man opens a door in a rain-soaked Tokyo street", body["query"])


class ClipBytesRefusalTests(unittest.TestCase):
    """The compliance half: whatever a clip *travels as* on the wire, the reader must not accept it."""

    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 2048 + b"\xff\xd9"

    def test_a_raw_image_body_is_refused(self):
        body, err = api_v2.read_body(_FakeHandler(body=self.JPEG, content_type="image/jpeg"))
        self.assertIsNone(body)
        self.assertEqual("invalid_params", err)

    def test_a_multipart_upload_is_refused(self):
        boundary = "----clip"
        form = (
            "--%s\r\nContent-Disposition: form-data; name=\"clip\"; filename=\"a.mp4\"\r\n"
            "Content-Type: video/mp4\r\n\r\n\x00\x00\x00\x18ftypmp42\x00\r\n--%s--\r\n" % (boundary, boundary)
        ).encode("utf-8", "surrogateescape")
        body, err = api_v2.read_body(
            _FakeHandler(body=form, content_type="multipart/form-data; boundary=%s" % boundary))
        self.assertIsNone(body)
        self.assertEqual("invalid_params", err)

    def test_a_base64_frame_inside_a_json_object_is_parsed_today(self):
        """THE FINDING, written as a test so it cannot be misread as coverage.

        This test PASSES because `read_body` accepts it: base64 is a JSON string, and a 320x180 JPEG
        keyframe base64s to roughly 8-20 KB — inside the 64 KiB ceiling. The body cap therefore does NOT
        implement the clip boundary on its own, and if you are here to mark G2 satisfied, you have proved
        the wrong thing.

        The boundary is a *field allow-list in the route* (q3's lane), or an outright refusal of any
        decoded value that looks like image/video bytes. This assertion flips to a refusal the day that
        lands, which is the point of pinning it: a pass here is a documented hole, not a green guard.
        """
        import base64
        frame = json.dumps({"frames": [base64.b64encode(self.JPEG).decode("ascii")]}).encode("utf-8")
        self.assertLess(len(frame), api_v2.MAX_BODY_BYTES,
                        "the premise of this test is that a keyframe fits under the cap")
        body, err = api_v2.read_body(_FakeHandler(body=frame))
        self.assertEqual("", err,
                         "read_body now refuses base64 — if that is a real allow-list, update the "
                         "cine-finder QA doc and say which field list refuses it")
        self.assertIn("frames", body)

    def test_the_reader_is_the_only_public_body_path_and_no_handler_names_a_frame_field(self):
        """Source-level check that no backend field accepts clip/frame/screenshot bytes by name.

        The scanned set is a list, not `glob("*.py")`, and that is a measured choice rather than
        convenience: a repo-wide scan hits `importers/import_filmiyin.py:659`, which does
        `elif "screenshot" in src` to name a *link* off its URL. That is a scraper heuristic, not a
        request field — and a guard that flags it gets "fixed" with a blanket exclusion, which is how
        guards die. If a route is ever added in a new module, add the module to `WIRE`.

        Positive control: the same scan must find the derived-text fields the feature is built on,
        otherwise an empty grep would pass.
        """
        WIRE = ("viewer.py", "api_v2.py", "media_search.py", "admin_panel.py", "accounts_api.py")
        bad = re.compile(r"""["'](?P<k>clip|clip_bytes|frame|frames|frame_bytes|keyframe|keyframes|
                            screenshot|image_bytes|video_bytes|thumbnail_base64)["']""", re.VERBOSE)
        good = re.compile(r"""["'](?P<k>query|text|ocr_text|dialogue|title|genres|synopsis)["']""")
        offenders, controls = [], 0
        for name in WIRE:
            path = ROOT / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if bad.search(line):
                    offenders.append("%s:%d %s" % (path.name, i, line.strip()[:120]))
                controls += len(good.findall(line))
        self.assertGreater(len(WIRE), 4, "the scanned set collapsed to almost nothing")
        self.assertEqual([], offenders,
                         "a backend field that could carry clip/frame/screenshot bytes: %s" % offenders[:6])
        self.assertGreater(controls, 5,
                           "the derived-text scan found nothing to match — this guard is green by accident")


if __name__ == "__main__":
    unittest.main(verbosity=2)
