package com.raddstream.app.network.models

import com.google.gson.JsonParser
import com.google.gson.JsonSyntaxException

/*
 * Helpers for the three v1 columns that are TEXT but hold a LIST.
 *
 * The truth they have to survive (verified against the live ledger, 2026-10-22):
 *  - `posts.genres`        → "Action, Adventure, Drama, Fantasy"        (CSV)
 *  - `posts.language`      → "Hindi + English + Japanese"               (not JSON either)
 *  - `posts.backdrop_urls` → '["https://a.jpg", "https://b.jpg"]'       (a JSON array
 *                            stored as a string), and sometimes one bare URL.
 * Gson cannot decode any of these into `List<String>` because the wire type is a String,
 * so [listOf] is the only sanctioned way to read them. It never throws: a malformed
 * "JSON array" falls back to CSV splitting, and a null stays an empty list.
 */
object WireText {

    /** Splits a CSV / " / "-joined / JSON-array-string column into trimmed, non-blank items. */
    fun listOf(raw: String?): List<String> {
        val text = raw?.trim().orEmpty()
        if (text.isEmpty()) return emptyList()
        if (text.startsWith("[")) {
            val parsed = try {
                val element = JsonParser.parseString(text)
                if (element.isJsonArray) {
                    element.asJsonArray.mapNotNull { item ->
                        if (item.isJsonNull) null else item.asString.trim().takeIf { it.isNotEmpty() }
                    }
                } else null
            } catch (e: JsonSyntaxException) {
                null
            } catch (e: IllegalStateException) {
                null
            }
            if (parsed != null) return parsed
        }
        // Strip stray brackets/quotes so a half-written JSON array still reads as items.
        val cleaned = text.trim('[', ']', '(', ')').replace("\"", " ")
        return splitOnAny(cleaned, ",", " / ", "+", ";", "|")
    }

    /** Splits on several separators at once, then trims and drops blanks and dups. */
    fun splitOnAny(text: String?, vararg separators: String): List<String> {
        val source = text?.trim().orEmpty()
        if (source.isEmpty()) return emptyList()
        // Qualified on purpose: inside this object an unqualified `listOf` is THIS member
        // function, so the short form would call itself forever on any non-JSON value.
        var parts: List<String> = kotlin.collections.listOf(source)
        for (separator in separators) {
            parts = parts.flatMap { it.split(separator) }
        }
        return parts.map { it.trim() }.filter { it.isNotEmpty() }.distinct()
    }

    /** True when a v1 URL string is worth handing to any client at all. */
    fun isHttpUrl(raw: String?): Boolean {
        val value = raw?.trim()?.lowercase().orEmpty()
        return value.startsWith("http://") || value.startsWith("https://")
    }
}
