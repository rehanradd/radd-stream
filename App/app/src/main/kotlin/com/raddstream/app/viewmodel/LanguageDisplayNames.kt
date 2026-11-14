package com.raddstream.app.viewmodel

/**
 * F23 (Batch B): the name of a language in its own script — the chip label a
 * reader of that language recognises at a glance, without having to read
 * Latin letters for a word they know in their own alphabet.
 *
 * The stored value stays the English name ("Hindi"): preferences, region
 * seeds and the wire never change, and a stored value with no native script
 * (English, Japanese, "Player default") simply has none. Only the paint
 * carries both scripts — see [displayLanguageName].
 */
fun nativeScriptName(englishName: String): String? = when (englishName) {
    "Hindi" -> "हिन्दी"
    "Urdu" -> "اردو"
    "Tamil" -> "தமிழ்"
    "Telugu" -> "తెలుగు"
    "Punjabi" -> "ਪੰਜਾਬੀ"
    "Bengali" -> "বাংলা"
    "Marathi" -> "मराठी"
    "Malayalam" -> "മലയാളം"
    "Kannada" -> "ಕನ್ನಡ"
    "Gujarati" -> "ગુજરાતી"
    else -> null
}

/**
 * The chip label: "Hindi · हिन्दी" when the language has its own script,
 * the bare English name when it does not. Both scripts, so the chip is
 * findable by a reader of either — and the English name stays first, so a
 * list of chips still scans in the order the viewer already knows.
 */
fun displayLanguageName(englishName: String): String =
    nativeScriptName(englishName)?.let { "$englishName · $it" } ?: englishName
