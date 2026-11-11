"""Mood and descriptive queries: map a feeling or a description to genres.

Gap A4: a viewer types "something funny to watch tonight" or "sad love
story" and the search has nowhere to put it — it only matches literal
title tokens. This module is a small, hand-curated lexicon, not a model:
a query's words are stemmed (lightly — "romantic" and "romance" are the
same intent) and matched against the moods below. The result is a set of
genre tokens the caller intersects with the normal search, so a mood
query narrows rather than replaces it.

The same lexicon also carries the Hindi/Urdu layer: a query in
Devanagari or Roman Urdu/Hindi ("mazahiya", "romantic film") maps to the
same English genre tokens, so a Hindi query finds English titles — the
catalog's genres are English, the viewer's language is not.

Matching is deliberately conservative: a mood fires only when a whole
stemmed word from the query appears in the lexicon. "Fun" does not fire
on "funeral" (whole-word match), and a query with no mood word returns
nothing — the caller then runs the ordinary search untouched.
"""

from __future__ import annotations

#: mood -> genre tokens (the catalog's `genres` values, lowercased).
#: Order is the presentation order: the first genre is the mood's
#: closest match and is the one "Did you mean" shows first.
MOOD_TO_GENRES: dict[str, tuple[str, ...]] = {
    "funny": ("comedy",),
    "comedy": ("comedy",),
    "laugh": ("comedy",),
    "hilarious": ("comedy",),
    "humor": ("comedy",),
    "humour": ("comedy",),
    "mazahiya": ("comedy",),
    "hasna": ("comedy",),
    "romantic": ("romance",),
    "romance": ("romance",),
    "love": ("romance", "drama"),
    "lovestory": ("romance", "drama"),
    "romcom": ("romance", "comedy"),
    "mohabbat": ("romance",),
    "pyaar": ("romance",),
    "pyar": ("romance",),
    "ishq": ("romance",),
    "sad": ("drama",),
    "emotional": ("drama",),
    "heartbreaking": ("drama",),
    "cry": ("drama",),
    "dukhi": ("drama",),
    "scary": ("horror", "thriller"),
    "horror": ("horror",),
    "haunted": ("horror",),
    "ghost": ("horror",),
    "dar": ("horror",),
    "bhoot": ("horror",),
    "thrilling": ("thriller", "action"),
    "thriller": ("thriller",),
    "suspense": ("thriller", "mystery"),
    "mystery": ("mystery", "thriller"),
    "detective": ("mystery", "crime"),
    "crime": ("crime", "thriller"),
    "action": ("action",),
    "fight": ("action",),
    "war": ("action", "history"),
    "adventure": ("adventure", "action"),
    "sci-fi": ("science fiction",),
    "scifi": ("science fiction",),
    "sciencefiction": ("science fiction",),
    "space": ("science fiction",),
    "fantasy": ("fantasy",),
    "magic": ("fantasy",),
    "jadui": ("fantasy",),
    "superhero": ("action", "fantasy"),
    "animation": ("animation",),
    "cartoon": ("animation", "family"),
    "kids": ("family", "animation"),
    "family": ("family",),
    "children": ("family", "animation"),
    "bachon": ("family", "animation"),
    "musical": ("music",),
    "music": ("music",),
    "dance": ("music",),
    "biography": ("biography", "drama"),
    "history": ("history", "drama"),
    "historical": ("history", "drama"),
    "documentary": ("documentary",),
    "sports": ("sport",),
    "sport": ("sport",),
    "western": ("western",),
    "inspirational": ("drama",),
    "feelgood": ("comedy", "drama"),
    "feel-good": ("comedy", "drama"),
    "uplifting": ("drama", "comedy"),
    "dark": ("thriller", "crime"),
    "light": ("comedy", "family"),
    "short": ("short",),
}

#: Roman-Urdu/Hindi and Devanagari words that name a genre outright
#: (not a mood): the query is about the genre, not about a title that
#: happens to contain the word. These map to the same genre tokens.
DESCRIPTIVE_TO_GENRES: dict[str, tuple[str, ...]] = {
    "mazahiya": ("comedy",),
    "hasna": ("comedy",),
    "comedy": ("comedy",),
    "mohabbat": ("romance",),
    "pyaar": ("romance",),
    "pyar": ("romance",),
    "ishq": ("romance",),
    "romantic": ("romance",),
    "dar": ("horror",),
    "bhoot": ("horror",),
    "jadui": ("fantasy",),
    "bachon": ("family", "animation"),
    "jung": ("action", "war"),
    "ladai": ("action",),
    "action": ("action",),
    "horror": ("horror",),
    "thriller": ("thriller",),
    "drama": ("drama",),
    "sci-fi": ("science fiction",),
}

#: Devanagari forms of the same words, so a query typed in Hindi script
#: maps identically. Normalisation (below) folds a Devanagari query into
#: its Roman key before lookup.
DEVANAGARI_TO_ROMAN: dict[str, str] = {
    "मजाहिया": "mazahiya",
    "हँसना": "hasna",
    "हंसना": "hasna",
    "मोहब्बत": "mohabbat",
    "प्यार": "pyaar",
    "इश्क़": "ishq",
    "इश्क": "ishq",
    "डर": "dar",
    "भूत": "bhoot",
    "जादुई": "jadui",
    "बच्चों": "bachon",
    "जंग": "jung",
    "लड़ाई": "ladai",
    "रोमांटिक": "romantic",
    "कॉमेडी": "comedy",
    "एक्शन": "action",
    "हॉरर": "horror",
    "थ्रिलर": "thriller",
    "ड्रामा": "drama",
}

#: The moods and descriptive words merged into one lookup. Descriptive
#: entries win on a collision (they name the genre outright).
_WORD_TO_GENRES: dict[str, tuple[str, ...]] = {
    **MOOD_TO_GENRES,
    **DESCRIPTIVE_TO_GENRES,
}

#: Trailing filler a viewer adds around a mood ("something funny to watch
#: tonight", "a good scary movie") — stripped before matching so the mood
#: word is what remains. These are never genre words themselves.
_FILLER_WORDS = frozenset({
    "something", "anything", "movie", "movies", "film", "films", "show",
    "shows", "watch", "tonight", "today", "good", "best", "great", "nice",
    "please", "want", "like", "looking", "for", "a", "an", "the", "to",
    "and", "or", "of", "in", "on", "with", "me", "i", "am", "is", "kuch",
    "koi", "acha", "accha", "dekhna", "dekhne", "chahiye", "story",
    "stories", "kahaani", "kahani",
})

# Light stemming: strip a trailing plural / adjective suffix so
# "romantic", "romance" and "romances" collapse, and "comedies" finds
# "comedy". Only applied when the bare word is not itself a key.
_SUFFIXES = ("ies", "ing", "ed", "es", "s")


def _stem(word: str) -> str:
    """Light stem: "comedies" -> "comedy", "thrillers" -> "thriller"."""
    if word in _WORD_TO_GENRES:
        return word
    if word.endswith("ies") and len(word) > 4:
        candidate = word[:-3] + "y"
        if candidate in _WORD_TO_GENRES:
            return candidate
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            candidate = word[: -len(suffix)]
            if candidate in _WORD_TO_GENRES:
                return candidate
    return word


def _words(query: str) -> list[str]:
    """Query words, lowercased, Devanagari folded to Roman, split on
    anything that is not a letter or digit."""
    import re

    text = (query or "").lower()
    for devanagari, roman in DEVANAGARI_TO_ROMAN.items():
        text = text.replace(devanagari, " " + roman + " ")
    return [w for w in re.split(r"[^a-z0-9]+", text) if w]


def moods_for_query(query: str) -> list[str]:
    """The mood words a query contains, in query order, deduped."""
    seen: set[str] = set()
    out: list[str] = []
    for word in _words(query):
        stemmed = _stem(word)
        if stemmed in _WORD_TO_GENRES and stemmed not in seen:
            seen.add(stemmed)
            out.append(stemmed)
    return out


def genres_for_query(query: str) -> list[str]:
    """Genre tokens a query's mood/descriptive words map to, in order,
    deduped. [] when the query names no mood — the caller then runs the
    ordinary search untouched."""
    seen: set[str] = set()
    out: list[str] = []
    for mood in moods_for_query(query):
        for genre in _WORD_TO_GENRES[mood]:
            if genre not in seen:
                seen.add(genre)
                out.append(genre)
    return out


def strip_mood_words(query: str) -> str:
    """The query with its mood and filler words removed — the literal
    remainder the caller still searches for (a title, an actor, a year).
    Returns "" when nothing literal remains, e.g. "something funny"."""
    kept: list[str] = []
    for word in _words(query):
        if word in _FILLER_WORDS:
            continue
        if _stem(word) in _WORD_TO_GENRES:
            continue
        kept.append(word)
    return " ".join(kept)
