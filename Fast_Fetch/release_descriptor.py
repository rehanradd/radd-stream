#!/usr/bin/env python3
"""release_descriptor.py — deterministic free-text -> structured "print" parser.

The `releases` table stores quality / codec / size / season / episode / release_title as whatever the
scraper saw on the page; the v2 API layer wants one structured description of a release (a "print")
instead. Pure, zero I/O, standard library only: `describe()` never raises and never returns None —
absent data is "", 0, [] or "unknown". `combined_quality_score` is the documented total order, the cam
family capped so a high resolution can never launder a cam.
"""

from __future__ import annotations

import re
from decimal import Decimal

# Worst -> best confirmed rung with the product weight each rung earns. The
# unconfirmed `unknown` (50) sits below every rung on purpose: a plain 480p
# download is a known-good print, an unprovable one is a risk.
QUALITY_LADDER = (("480p_or_lower", 100), ("480p", 120), ("720p", 200), ("1080p", 300), ("2160p", 400))
RESOLUTION_UNKNOWN_WEIGHT = 50
RESOLUTION_WEIGHTS = dict(QUALITY_LADDER, unknown=RESOLUTION_UNKNOWN_WEIGHT)

# Source weights. Match precedence in `_SOURCE_PATTERNS` follows this order, so
# a label naming two capture methods keeps the better-distributed one. `hdtc`
# (HD-TeleCine) is a cam-family capture: it sits between `telesync` and
# `telecine` and inherits the cam ceiling, so no resolution can launder it.
SOURCE_TAG_WEIGHTS = {"uhd_bluray": 300, "bluray": 280, "web_dl": 240, "webrip": 220, "hdtv": 180,
                      "dvdrip": 150, "telesync": 80, "hdtc": 75, "telecine": 70, "ppv": 20,
                      "cam": 20, "unknown": 60}
CAM_FAMILY = ("cam", "telesync", "hdtc", "telecine")
CAM_FAMILY_CEILING = 250
OFFICIAL_SOURCE_TAGS = ("bluray", "uhd_bluray", "web_dl", "webrip", "hdtv", "dvdrip")
QUALITY_LABELS = {"2160p": "4K UHD", "1080p": "Full HD", "720p": "HD", "480p": "SD", "480p_or_lower": "SD"}

# Site/operator watermarks seen in scraped labels. `etleb` is kept next to
# `etlb` because real labels spell the same group both ways.
WATERMARK_MARKERS = ("watermark", "watermarked", "hdhub4u wm", "x265 webdl wm", "webdl wm",
                     "i60x", "etlb", "etleb", "psa")

# Two-letter aliases are listed only where they are not also a quality token,
# which is why bare `hd` never means Hindi here.
LANGUAGE_ALIASES = {
    "hindi": "Hindi", "hin": "Hindi", "english": "English", "eng": "English",
    "tamil": "Tamil", "tam": "Tamil", "telugu": "Telugu", "tel": "Telugu",
    "telegu": "Telugu", "kannada": "Kannada", "kan": "Kannada",
    "malayalam": "Malayalam", "mal": "Malayalam", "mallu": "Malayalam",
    "punjabi": "Punjabi", "pun": "Punjabi", "marathi": "Marathi",
    "bengali": "Bengali", "ben": "Bengali", "bangla": "Bengali",
    "bhojpuri": "Bhojpuri", "bhojp": "Bhojpuri", "korean": "Korean", "kor": "Korean",
    "japanese": "Japanese", "jap": "Japanese", "chinese": "Chinese",
    "mandarin": "Chinese",
}

# Longest-first, because every match is masked out: `ddp` must win before `dd`.
AUDIO_CODEC_PATTERNS = (("ddp", r"\bddp\b|\bddplus\b|\bdd\+\b"), ("dts-hd", r"\bdts[\s\-\.]*hd\b"),
                        ("truehd", r"\btrue[\s\-]?hd\b"), ("eac3", r"\beac\s*3\b"),
                        ("ac3", r"\bac\s*3\b"), ("atmos", r"\batmos\b"), ("dts", r"\bdts\b|\bhdts\b"),
                        ("aac", r"\baac\b"), ("flac", r"\bflac\b"), ("opus", r"\bopus\b"),
                        ("mp2", r"\bmp\s*2\b"), ("dd", r"\bdd\b"))

SUBTITLE_EXTERNAL_PATTERNS = ((r"\be[\s\-]?subs?\b", ("English",)),
                              (r"\beng(?:lish)?[\s\-\.]*subs?\b", ("English",)),
                              (r"\bsubtitles?\b|\bsub\b", ()), (r"\bmulti[\s\-]?subs?\b", ()))
SUBTITLE_HARDCODED_PATTERNS = (r"\bhard[\s\-]?subs?\b|\bh[\s\-]?subs?\b|\bhardcoded[\s\-]?subs?\b",
                               r"\bburn(?:ed|ing)?[\s\-]?subs?\b",
                               r"\bon[\s\-]?screen[\s\-]?subs?\b")
EDITION_PATTERNS = (("director_cut", "directorscut|directorcut"),
                    ("extended", "extendedcut|extendededition|extended"),
                    ("imax", "imaxedition|imax"), ("unrated", "unrated"),
                    ("remastered", "remastered|remaster"), ("restored", "restored|4krestoration"),
                    ("uncut", "uncut"), ("fan_edit", "fanedit"),
                    ("theatrical", "theatricalcut|theatrical|originalcut"))

# Word-boundary patterns, so `repack` never reads as a pack of episodes.
PACK_PATTERNS = (r"\bbatch(?:es)?\b", r"\bcomplet(?:e|ed)\b", r"\ball episodes?\b",
                 r"\bfull movies?\b", r"\bzip\b", r"\bpack\b", r"\bmulti[\s\-]?eps?\b")
MULTI_SEASON_PATTERNS = (r"\ball seasons\b", r"\bseasons?\s*\d+\s*-\s*\d+\b",
                         r"\bdual\s*seasons?\b", r"\bcollection\b")
MINISERIES_RE = r"\bmini[\s\-]?series\b"
SERIES_WORD_RE = r"\b(?:web[\s\-]?series|series|season|saga)\b"
# These words prove the print is episodic without naming a season or an episode,
# so such a label can never be called a movie and its scope stays "unknown".
EPISODIC_HINTS_RE = r"\b(?:grand\s+)?premieres?\b|\bfinale\b|\bweeklies\b|\blive show\b"

# Conservative scene-group recovery. Group names are UPPER-case by convention, so
# a mixed-case or lower-case candidate is never guessed; every word the corpus
# uses for quality, source, codec, container, audio, subtitle, version, edition,
# pack, language or watermark purposes is denied outright, and `''` is returned
# whenever the label does not actually carry a group.
GROUP_MIN_LEN, GROUP_MAX_LEN = 3, 15
_GROUP_CANDIDATE_RE = re.compile(r"[A-Z][A-Z0-9]{2,14}")
# The trailing `-NAME` release suffix only counts when what precedes the dash is
# a scene tech word (x265, 1080p, WEB-DL, HDRip...), so hyphenated titles like
# "CHIP-IN" or "MECH-X4" never read as a group.
_GROUP_DASH_RE = re.compile(r"[-_]([A-Za-z][A-Za-z0-9]{2,14})\s*$")
_GROUP_BRACKET_RE = re.compile(r"[\[\(\{]\s*([A-Za-z][A-Za-z0-9]{2,14})\s*[\]\)\}]")
_GROUP_RESOLUTION_HEAD_RE = re.compile(
    r"^(?:2160p?|1080p?|720p|480p|360p|240p|uhd|4k|fhd|full\s?hd)\b", re.I)
_GROUP_TRIM = " \t.,:;!?|/\\'\"`-_"
_GROUP_DENY_WORDS = frozenset((
    "2160p", "1080p", "720p", "480p", "360p", "240p", "uhd", "4k", "fhd", "hd", "sd", "sdr",
    "hdr", "hdr10", "hdr10plus", "dolbyvision", "dovi", "dv", "hlg", "x265", "x264", "x266",
    "h265", "h264", "hevc", "avc", "av1", "av01", "xvid", "mpeg", "mpeg2", "prores", "webm",
    "mkv", "mp4", "avi", "mov", "m4a", "ts", "tc", "scr", "bluray", "bd", "dvd", "dvd5", "dvd9",
    "bdrip", "brrip", "remux", "demux", "web", "webdl", "webrip", "dvdrip", "hdrip", "hddvd",
    "vhsrip", "hdtv", "hdtc", "hdts", "hdcam", "cam", "camrip", "telesync", "telecine",
    "screener", "workprint", "ppv", "dd", "ddp", "ddplus", "dolby", "dts", "dtshd", "dtsx",
    "truehd", "atmos", "ac3", "eac3", "aac", "flac", "opus", "mp2", "mp3", "stereo", "51",
    "71", "20", "multi", "dual", "audio", "multiaudio", "dualaudio", "dub", "dubbed", "sub",
    "subs", "esub", "esubs", "subtitle", "subtitles", "hsub", "hsubs", "engsub", "engsubs",
    "hardsub", "hardsubs", "burned", "burnt", "hardcoded", "onscreen", "mvs", "batch",
    "dl", "web", "rip", "org", "unofficial", "official", "single", "series", "webseries",
    "episode", "movie", "movies", "full", "films", "film",
    "complete", "completed", "all", "ep", "eps", "episode", "episodes", "season", "seasons",
    "pack", "zip", "proper", "repack", "internal", "faster", "fix", "fixed", "nfo", "nfofix",
    "cut", "extended", "unrated", "remastered", "remaster", "restored", "restoration",
    "uncut", "imax", "fan", "fansub", "fanedit", "theatrical", "original", "directors",
    "directorscut", "uncensored", "limited", "nogrp", "ngrp", "nogroup", "no", "none",
    "unknown", "watermark", "watermarked", "wm", "gb", "mb", "tb", "kb",
)) | frozenset(re.sub(r"[^a-z0-9]", "", w.lower()) for w in WATERMARK_MARKERS) \
    | frozenset(re.sub(r"[^a-z0-9]", "", w.lower()) for w in LANGUAGE_ALIASES) \
    | frozenset(re.sub(r"[^a-z0-9]", "", w.lower()) for w in LANGUAGE_ALIASES.values())

PRINT_KEYS = ("resolution", "quality_label", "source_tag", "codec", "bit_depth", "hdr",
              "container", "audio", "subtitles", "edition", "version", "release_group", "is_pack",
              "episode_range", "season", "episode", "scope", "size_bytes", "size_per_episode_bytes",
              "watermarked", "official_print", "quality_score", "title_stub")

_DASHES = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
           "\u2212": "-", "\u00ad": "-", "\u00a0": " ", "\u200b": ""}
_RESOLUTION_PATTERNS = (("2160p", r"\b(?:2160p?|uhd|4k)\b"), ("1080p", r"\b(?:1080p?|fhd|full\s?hd)\b"),
                        ("720p", r"\b720p?\b"), ("480p", r"\b480p?\b"),
                        ("480p_or_lower", r"\b(?:360p|240p|144p|480p_or_lower)\b"))
_SOURCE_PATTERNS = (
    ("bluray", r"\bblu[\s\-]?ray\b|\bbdrip\b|\bdemux\b|\bdvd\s?9\b"),
    ("web_dl", r"\bweb[\s\-]?dl\b|\bwebdl\b|\bweb[\s\-]?download\b"),
    ("webrip", r"\bweb[\s\-]?rip\b|\bwebrip\b|\bnfweb\b|\bamzn[\s\-]?web\b|\bdsny[\s\-]?web\b"),
    ("hdtv", r"\bhd\s?tv\b|\bhdtv\b|\bdvb[\s\-]?rip\b|\bdtv\b"),
    ("dvdrip", r"\bdvd[\s\-]?rip\b|\bdvdrip\b|\bhdrip\b|\bhddvd\b|\bvhsrip\b"),
    ("ppv", r"\bppv\b|\bpay[\s\-]?per[\s\-]?view\b"), ("telesync", r"\btelesync\b|\btsrip\b|\bhdts\b|\bts\b"),
    # HDTC (HD-TeleCine) is a cam-family capture, not a distribution print; the
    # corpus spells it `HDTC` and `HD-TC`, and every separator variant folds in.
    ("hdtc", r"\bh[\s\-\.]*d[\s\-\.]*t[\s\-\.]*c\b|\bhd[\s\-\.]*tc\b"),
    ("telecine", r"\btelecine\b|\btc\b|\bscr\b|\bscreener\b"),
    ("cam", r"\bhq[\s\-]?cam\b|\bcam[\s\-]?rip\b|\bcam\b|\bmdf\b|\bcamera\b"))
_CODEC_PATTERNS = (("h265", r"\bx[\s\-\.]*265\b|\bh[\s\-\.]*265\b|\bhevc\b|\b265\b"),
                   ("h264", r"\bx[\s\-\.]*264\b|\bh[\s\-\.]*264\b|\bavc\b|\b264\b"),
                   ("av1", r"\bav1\b|\bav01\b"), ("xvid", r"\bxvid\b"),
                   ("mpeg2", r"\bmpeg[\s\-]?2\b|\bmpeg\b|\bmpgv\b|\bdvdvideo\b"))
_CONTAINER_PATTERNS = (("mkv", r"\.mkv\b|\bmkv\b"), ("mp4", r"\.mp4\b|\bmp4\b"),
                       ("avi", r"\.avi\b|\bavi\b"), ("mov", r"\.mov\b|\bmov\b"),
                       # `ts` counts as a container only as an extension: the
                       # same two letters are the usual telesync abbreviation.
                       ("ts", r"\.ts\b"), ("m4a", r"\.m4a\b|\bm4a\b"))
_HDR10_PLUS_RE = r"\bhdr[\s.\-]*10[\s.\-]*\+|\bhdr\s*\+\s*10\b|\bhdr\s?plus\b"
_UNITS = {"kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "tb": 1024 ** 4}
_PER_EPISODE = r"(\s*/\s*(?:e|ep|eps|episode|episodes?)\b|\s+per\s+(?:ep|episode|eps)\b)?"
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(kb|mb|gb|tb)\b" + _PER_EPISODE, re.I)
_RANGE_PATTERNS = (r"\bs\d{1,3}e(\d{1,3})\s*(?:-|to|thru|through)\s*(?:s\d{1,3}e?|e)?(\d{1,3})\b",
                   r"\b(?:ep(?:isode)?s?|e)\s*[\(\[\{]?\s*(\d{1,3})\s*(?:-|to|thru|through)"
                   r"\s*[\)\]\}]?\s*(?:e?\.?\s*)(\d{1,3})\s*[\)\]\}]?",
                   r"[\(\[\{]\s*(\d{1,3})\s*(?:-|to|thru|through)\s*(\d{1,3})\s*[\)\]\}]")
_SEASON_PATTERNS = (r"^(?:s\s*)?(\d{1,3})\b", r"\bseason\s*(\d{1,3})\b",
                    r"\bs(\d{1,3})(?=e(?:p|\d))", r"\bs(\d{1,3})\b")
_EPISODE_PATTERNS = (r"^(?:e\s*)?(\d{1,3})\b", r"\bs\d{1,3}e(\d{1,3})\b",
                     r"\bep(?:isode)?\s*\.?\s*(\d{1,3})\b")
_BIT_DEPTH_RE = r"\b(12|10|8)\s?[\s\-\.]?bits?\b"
_VERSION_RE = r"\bv(\d{1,3})\b"

_LANGUAGE_NOISE = "|".join(sorted(name.lower() for name in set(LANGUAGE_ALIASES.values())))
# Everything lifted out of the label on the way to `title_stub`.
_NOISE_PATTERNS = (
    r"\b(?:2160p?|1080p?|720p|480p|360p|240p|uhd|4k|fhd|full\s?hd|hd|sd)\b",
    r"\b(?:x[\s\-\.]*26[45]|h[\s\-\.]*26[45]|hevc|avc|av1|xvid|mpeg ?2?|26[45])\b",
    r"\b(?:1[028]|8)\s?[\s\-\.]?bits?\b", r"\b(?:dolby ?vision|dv|hdr ?10 ?\+|hdr ?10 ?\+?|hlg|dovi)\b",
    r"\b(?:blu[\s\-]?ray|bdrip|demux|web[\s\-]?(?:dl|rip)|webdl|hd ?tv|dvd ?9|hdrip|dvdrip|vhsrip)\b",
    r"\b(?:dts[-.]?hd|dtsx|truehd|atmos|ac ?3|eac ?3|aac|mp2|opus|flac|ddp|dd|5\.1|7\.1|2\.0|stereo)\b",
    r"\b(?:dual ?audio|multi ?audio|dubbed|dub|org|subtitles?|subs?|esubs?|eng ?subs?"
    r"|hard ?subs?|h ?subs?|burned ?subs|on ?screen ?subs)\b",
    r"\.(?:mkv|mp4|avi|mov|m4a|ts)\b",
    r"\b(?:" + _LANGUAGE_NOISE + r")\b", r"\d+(?:\.\d+)?\s?(?:kb|mb|gb|tb)(?:\s*/\s*e(?:p)?)?",
    r"\b(?:season\s?\d+|s\d{1,3}ep?\(?\d{1,3}(?:\s*(?:-|to|thru|through)\s*(?:ep?\.?\s*)?\d{1,3})?\)?"
    r"|s\d{1,3}(?:e\d{1,3})?|ep(?:isode)?s?\.?\s?\(?\d+(?:\s*(?:-|to)\s*\d+)?\)?"
    r"|e\d{1,3}(?:\s*(?:-|to|thru|through)\s*e?\d{1,3})?)\b",
    r"\b(?:batch|complete[d]?|all episodes?|all seasons|full movies?|zip|pack)\b",
    r"\b(?:director'?s? ?cut|extended ?cut?|unrated|remastered|restored|uncut|imax|fan ?edit"
    r"|theatrical(?: ?cut)?|original ?cut)\b",
    r"\b(?:v\d{1,3}|repack|proper|web ?series|mini ?series)\b",
    r"\b(?:watermark(?:ed)?|wm|i60x|etlb|etleb|psa)\b")
_EMPTY_GROUP_RE = re.compile(r"[\(\[\{][\s.,+|/&\-]*[\)\]\}]")
_NUMERIC_GROUP_RE = re.compile(r"[\(\[\{][\s.,+|&\-]*(?:\d{1,4}|\d{1,3}\s*(?:-|to)\s*\d{1,3})[\s.,+|&\-]*[\)\]\}]")
_BRACKET_PAIRS = (("(", ")"), ("[", "]"), ("{", "}"))


def _tidy(value) -> str:
    """Case-preserving search text: stringified, capped, unicode dashes folded."""
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    text = value[:4000]
    for src, dst in _DASHES.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def _squash(value) -> str:
    """Lowercased `_tidy`; every detector matches against this form."""
    return _tidy(value).lower()


def _compact(value) -> str:
    """Alphanumerics only: `Web-DL`, `Web DL`, `webdl` collapse to `webdl`."""
    return re.sub(r"[^a-z0-9]+", "", _squash(value))


def _mask(text: str, spans) -> str:
    out = list(text)
    for start, end in spans:
        out[start:end] = [" "] * (end - start)
    return "".join(out)


def resolution_rank(res: str) -> int:
    return RESOLUTION_WEIGHTS.get(_squash(res), RESOLUTION_UNKNOWN_WEIGHT)


def source_rank(tag: str) -> int:
    return SOURCE_TAG_WEIGHTS.get(_squash(tag), SOURCE_TAG_WEIGHTS["unknown"])


def _number(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


def _first(table, text: str) -> str:
    """First entry of a (name, pattern) table whose pattern fires, else `unknown`."""
    for name, pattern in table:
        if re.search(pattern, text):
            return name
    return "unknown"


def _detect_resolution(quality: str, title: str) -> str:
    """Best rung named in the `quality` column, else the best the label names."""
    for field in (quality, title):
        found = [res for res, pat in _RESOLUTION_PATTERNS if re.search(pat, field)]
        if found:
            return max(found, key=resolution_rank)
    return "unknown"


def _detect_codec(codec: str, quality: str, title: str) -> str:
    """First codec named, reading the explicit columns before the label."""
    for field in (codec, quality, title):
        found = _first(_CODEC_PATTERNS, field)
        if found != "unknown":
            return found
    return "unknown"


def _detect_hdr(text: str) -> list:
    """Best format first; the HDR10+ span is masked so it is never also hdr10."""
    out = []
    if re.search(r"\bdolby\s?vision\b|\bdv\b|\bdovi\b", text):
        out.append("dolby_vision")
    plus = [m.span() for m in re.finditer(_HDR10_PLUS_RE, text)]
    if plus:
        out.append("hdr10_plus")
    rest = _mask(text, plus)
    if re.search(r"\bhdr\s?10\b|\bhdr\b", rest):
        out.append("hdr10")
    if re.search(r"\bhlg\b", rest):
        out.append("hlg")
    return out


def _detect_languages(*fields: str) -> list:
    """Language names in order of first appearance; `Hindi-English` reads both."""
    found = []
    for field in fields:
        for token in re.findall(r"\b[a-z]{2,12}\b", field):
            name = LANGUAGE_ALIASES.get(token)
            if name and name not in found:
                found.append(name)
    return found


def _detect_audio(text: str, extra_languages: str) -> dict:
    languages = _detect_languages(extra_languages, text)
    codecs, rest = [], text
    for name, pattern in AUDIO_CODEC_PATTERNS:
        m = re.search(pattern, rest)
        if m:
            codecs.append(name)
            rest = _mask(rest, [m.span()])
    # The enum has no 7.1 slot, so a 7.1 track reports the surround layout
    # `5.1` rather than being thrown away as `unknown`.
    layout = ("5.1" if re.search(r"\b[57]\s?\.\s?1\b", text)
              else "2.0" if re.search(r"\b2\s?\.\s?0\b|\bstereo\b", text) else "unknown")
    dual = bool(re.search(r"\bdual[\s\-]?audi[oa]?\b|\bmulti[\s\-]?audi[oa]\b", text))
    return {"languages": languages, "channel_layout": layout, "codecs": codecs,
            "dual_audio": dual or len(languages) >= 2}


def _detect_subtitles(text: str) -> dict:
    langs, external = [], False
    for pattern, names in SUBTITLE_EXTERNAL_PATTERNS:
        if re.search(pattern, text):
            external = True
            langs.extend(n for n in names if n not in langs)
    hardcoded = any(re.search(p, text) for p in SUBTITLE_HARDCODED_PATTERNS)
    return {"available": external or hardcoded or bool(langs), "hardcoded": hardcoded,
            "external": external, "langs": langs}


def _detect_episode_range(text: str) -> str:
    for pattern in _RANGE_PATTERNS:
        for m in re.finditer(pattern, text):
            lo, hi = int(m.group(1)), int(m.group(2))
            if 1 <= lo <= 999 and 1 <= hi <= 999:
                return f"{min(lo, hi)}-{max(lo, hi)}"
    return ""


def _detect_index(column: str, text: str, patterns, limit: int) -> int:
    """First number the explicit column names, then the label; 0 means none."""
    for field, pattern in zip((column, text, text, text), patterns):
        if 1 <= (value := _number(pattern, field)) <= limit:
            return value
    return 0


def _detect_scope(text: str, season: int, episode: int, is_pack: bool, has_range: bool) -> str:
    series_named = bool(re.search(SERIES_WORD_RE, text))
    if any(re.search(p, text) for p in MULTI_SEASON_PATTERNS):
        return "multi_season"
    if re.search(MINISERIES_RE, text):
        return "miniseries"
    if has_range or episode or season or (is_pack and series_named):
        return "episode_range" if has_range else "episode" if episode else "season_pack"
    return "unknown" if series_named or re.search(EPISODIC_HINTS_RE, text) else "movie"


def _detect_size(size: str, title: str) -> tuple:
    """(total_bytes, per_episode_bytes). A `/E` figure is per episode, so the total
    stays 0 — the file count is unknown. Decimal keeps `2.24 GB` byte-exact instead
    of drifting through binary floating point."""
    for field in (size, title):
        for m in _SIZE_RE.finditer(field):
            value = int((Decimal(m.group(1)) * _UNITS[m.group(2).lower()]).to_integral_value())
            if value > 0:
                return (0, value) if m.group(3) else (value, 0)
    return 0, 0


def _is_official_print(source_tag: str, watermarked: bool, edition: str, resolution: str) -> bool:
    """Legitimate/distributed copy rather than a cam or a fan edit. Every cam-family
    tag — including `hdtc`, which used to fall through as `unknown` and earn the
    official bonus — is refused outright. An `unknown` source still counts when the
    resolution is confirmed: the label names no capture method at all and nothing
    marks it as a theatre recording, so calling it unofficial would punish plain
    re-encodes."""
    if watermarked or edition == "fan_edit" or source_tag in CAM_FAMILY:
        return False
    return (source_tag in OFFICIAL_SOURCE_TAGS
            or (source_tag == "unknown" and resolution != "unknown"))


def _plausible_group(candidate: str) -> str:
    """The candidate as canonical UPPER case, or '' when it is not a group.
    Rejects: mixed/lower case (never guessed), the denials above, version tokens
    like V2, anything with a long digit run, and anything a tech detector reads,
    so `-x265`, `-ESubs`, `-MULTI` and `REPACK v2` can never become a group."""
    cand = candidate.strip(_GROUP_TRIM)
    if not GROUP_MIN_LEN <= len(cand) <= GROUP_MAX_LEN or cand != cand.upper():
        return ""
    if not _GROUP_CANDIDATE_RE.fullmatch(cand):
        return ""
    compact = cand.lower()
    # `MULTISUBS`/`DUBBED`/`HINDIDUB`-style compounds are quality words too, not groups.
    if (compact in _GROUP_DENY_WORDS
            or re.search(r"(?:subs?|dub(?:bed)?|audio|edition|season|episode|pack)$", compact)
            or re.match(r"^(?:multi|dual|hard|burn|non|with)", compact)
            or re.fullmatch(
                r"v\d{1,3}|s\d{1,3}|e\d{1,3}|s\d{1,3}(?:ep|e|x)\d{1,3}|ep(?:isode)?\d{1,3}"
                r"|part\d*|vol(?:ume)?\d*|season\d*|chapter\d*", compact)
            or re.search(r"\d{3,}", compact)):
        return ""
    padded = " " + compact + " "
    if (_detect_resolution(compact, "") != "unknown"
            or _first(_SOURCE_PATTERNS, padded) != "unknown"
            or _first(_CODEC_PATTERNS, padded) != "unknown"):
        return ""
    return cand


def _group_prefix_tech(prefix: str) -> bool:
    """True when some alnum chunk of the text before the dash is a scene tech
    word (resolution, source or codec), i.e. the dash really is a release
    suffix (`x265-GROUP`, `1080p.WEB-DL-PEAK`) and not a hyphenated title."""
    for part in re.split(r"[^a-z0-9]+", prefix.lower()):
        if not part or not re.search(r"[a-z]", part):
            continue
        padded = " " + part + " "
        if (_detect_resolution(part, "") != "unknown"
                or _first(_SOURCE_PATTERNS, padded) != "unknown"
                or _first(_CODEC_PATTERNS, padded) != "unknown"):
            return True
    return False


def _detect_release_group(title: str, format_named: bool) -> str:
    """Recover the SCENE group a scraper printed in the label, or ''.
    Accepted forms, in precedence order: the trailing `-NAME` release suffix
    (only when the pre-dash text names a tech word), an upper-case
    `[NAME]`/`(NAME)`/`{NAME}` token, a bare upper-case last word, and an
    upper-case word immediately before a resolution (the `GROUP 1080p ...`
    spelling). The last two require the label to name at least one real print
    component first, so a plain title's final word is never mistaken for a
    group. The label itself is never rewritten — this is an added field only."""
    text = _tidy(title)
    if not text:
        return ""
    m = _GROUP_DASH_RE.search(text)
    if m and (group := _plausible_group(m.group(1))) and _group_prefix_tech(text[:m.start()]):
        return group
    for bracketed in _GROUP_BRACKET_RE.findall(text):
        if (group := _plausible_group(bracketed)):
            return group
    if not format_named:
        return ""
    words = text.split()
    if words and (group := _plausible_group(words[-1])):
        return group
    for i, word in enumerate(words[1:], start=1):
        if _GROUP_RESOLUTION_HEAD_RE.match(word.strip(_GROUP_TRIM)):
            if (group := _plausible_group(words[i - 1])):
                return group
    return ""


def _quality_label(resolution: str, source_tag: str, quality: str, title: str) -> str:
    """Cam family always says CAM, otherwise the rung name. A bare `HD` is not a
    resolution, so it survives here as a display label only."""
    if source_tag in CAM_FAMILY or source_tag == "ppv":
        return "CAM"
    if resolution in QUALITY_LABELS:
        return QUALITY_LABELS[resolution]
    return "HD" if re.search(r"\bhd\b|fhd|full\s?hd", quality + " " + title) else ""


def _clean_fragment(text: str) -> str:
    """Drops noise tokens, then the brackets and separators they leave behind."""
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I)
    for _ in range(3):
        text = _EMPTY_GROUP_RE.sub(" ", text)
        text = _NUMERIC_GROUP_RE.sub(" ", text)
    if any(text.count(o) != text.count(c) for o, c in _BRACKET_PAIRS):
        text = re.sub(r"[\(\)\[\]\{\}]", " ", text)
    text = re.sub(r"(?:\s*[\|/\-+]\s*){2,}", " | ", text)
    text = re.sub(r"\s+([,|])", r"\1", text)
    text = re.sub(r"([,|])\s+", r"\1 ", text)
    return re.sub(r"\s{2,}", " ", text).strip(" \t\r\n-+|/.,:")


def combined_quality_score(resolution: str = "unknown", source_tag: str = "unknown",
                           hdr=None, bit_depth: int = 0, codec: str = "unknown",
                           official_print: bool = False, subtitles=None, audio=None,
                           edition: str = "unknown", watermarked: bool = False) -> int:
    """Documented total order over one print's components, clamped to 0..1000.

    score = resolution_weight + source_weight
            + 60  when dolby_vision, hdr10 or hdr10_plus is present AND resolution is 1080p/2160p
            + 30  when bit_depth == 12, else 20 when bit_depth == 10
            + 30  when codec is h265 or av1 (efficiency bonus over h264)
            + 40  when official_print
            + 20  when subtitles are external, else 5 when hardcoded
            + 25  when dual_audio, + 15 when the layout is 5.1
            + 15  when edition is director_cut/extended/remastered/restored
            - 60  when watermarked
    then cam-family totals are capped at 250 and the result is clamped 0..1000.
    The best describable print (2160p UHD BluRay, DV, 12-bit, AV1, official,
    external subs, dual audio 5.1, director's cut) scores 935, so the clamp is
    defensive; every weight follows the product's preference order, so a better
    component always means a strictly higher score.
    """
    score = resolution_rank(resolution) + source_rank(source_tag)
    if set(hdr or ()) & {"dolby_vision", "hdr10", "hdr10_plus"} and resolution in ("1080p", "2160p"):
        score += 60
    score += 30 if bit_depth == 12 else 20 if bit_depth == 10 else 0
    score += 30 if codec in ("h265", "av1") else 0
    score += 40 if official_print else 0
    subs, aud = subtitles or {}, audio or {}
    score += 20 if subs.get("external") else 5 if subs.get("hardcoded") else 0
    score += 25 if aud.get("dual_audio") else 0
    score += 15 if aud.get("channel_layout") == "5.1" else 0
    score += 15 if edition in ("director_cut", "extended", "remastered", "restored") else 0
    score -= 60 if watermarked else 0
    if source_tag in CAM_FAMILY:
        score = min(score, CAM_FAMILY_CEILING)
    return max(0, min(1000, score))


def describe(release_title: str = "", quality: str = "", codec: str = "",
             size: str = "", season: str = "", episode: str = "",
             languages: str = "", source_site: str = "") -> dict:
    """Parse one release label into the structured print the API layer serves.

    Precedence is explicit-column-first, label-second: `quality` and `codec` are trusted
    before `release_title`, but whatever they failed to name is still recovered from the
    label, so `quality="720p-HEVC"` with an empty `codec` still reports `h265`.
    `source_site` is scanned only for watermark markers; it changes no other component.
    """
    try:
        q_text, c_text = _squash(quality), _squash(codec)
        t_text, lang_text = _squash(release_title), _squash(languages)
        s_text, e_text = _squash(season), _squash(episode)
        all_text = " ".join(p for p in (q_text, c_text, t_text, lang_text) if p)

        resolution = _detect_resolution(q_text, t_text)
        source_tag = _first(_SOURCE_PATTERNS, all_text)
        if source_tag == "bluray" and resolution == "2160p":
            source_tag = "uhd_bluray"   # a 2160p disc is its own, better rung
        detected_codec = _detect_codec(c_text, q_text, t_text)
        bit_depth = _number(_BIT_DEPTH_RE, all_text)
        container = _first(_CONTAINER_PATTERNS, all_text)
        edition = _first(EDITION_PATTERNS, _compact(all_text))
        version = _number(_VERSION_RE, all_text)
        hdr = _detect_hdr(all_text)
        audio = _detect_audio(all_text, lang_text)
        subtitles = _detect_subtitles(all_text)
        episode_range = _detect_episode_range(all_text)
        has_range = bool(episode_range)
        season_no = _detect_index(s_text, all_text, _SEASON_PATTERNS, 99)
        # A range or a pack yields 0: that file covers many episodes, not one.
        episode_no = 0 if has_range else _detect_index(e_text, all_text, _EPISODE_PATTERNS, 999)
        is_pack = has_range or any(re.search(p, all_text) for p in PACK_PATTERNS)
        scope = _detect_scope(all_text, season_no, episode_no, is_pack, has_range)
        size_bytes, per_episode = _detect_size(_squash(size), t_text)
        site_blob = " ".join(_squash(f) for f in (release_title, quality, codec, size, source_site))
        watermarked = any(marker in site_blob for marker in WATERMARK_MARKERS)
        official_print = _is_official_print(source_tag, watermarked, edition, resolution)
        release_group = _detect_release_group(
            release_title,
            resolution != "unknown" or source_tag != "unknown" or detected_codec != "unknown")
        return {
            "resolution": resolution,
            "quality_label": _quality_label(resolution, source_tag, q_text, t_text),
            "source_tag": source_tag, "codec": detected_codec, "bit_depth": bit_depth,
            "hdr": hdr, "container": container, "audio": audio, "subtitles": subtitles,
            "edition": edition, "version": version, "release_group": release_group,
            "is_pack": is_pack,
            "episode_range": episode_range, "season": season_no, "episode": episode_no, "scope": scope,
            "size_bytes": size_bytes, "size_per_episode_bytes": per_episode,
            "watermarked": watermarked, "official_print": official_print,
            "quality_score": combined_quality_score(resolution, source_tag, hdr, bit_depth, detected_codec,
                                                    official_print, subtitles, audio, edition, watermarked),
            "title_stub": _clean_fragment(_tidy(release_title)),
        }
    except Exception:
        return _fallback_print()


def _fallback_print() -> dict:
    """Unparseable-to-the-end input still yields a complete, honest print."""
    return {"resolution": "unknown", "quality_label": "", "source_tag": "unknown",
            "codec": "unknown", "bit_depth": 0, "hdr": [], "container": "unknown",
            "audio": {"languages": [], "channel_layout": "unknown", "codecs": [], "dual_audio": False},
            "subtitles": {"available": False, "hardcoded": False, "external": False, "langs": []},
            "edition": "unknown", "version": 0, "release_group": "", "is_pack": False,
            "episode_range": "",
            "season": 0, "episode": 0, "scope": "unknown", "size_bytes": 0,
            "size_per_episode_bytes": 0, "watermarked": False, "official_print": False,
            "quality_score": combined_quality_score(), "title_stub": ""}
