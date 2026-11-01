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

    /**
     * True for exactly a published APK digest: 64 lowercase hex characters, nothing else.
     *
     * Lowercase-only is deliberate. The admin form normalises case on write and refuses a row
     * that is not 64 hex (`Fast_Fetch/admin_panel.py`, UPD-1a), so an uppercase or 63-character
     * value here did not come from that form — it came from a paste that will never match the
     * hash of a correctly downloaded file. A digest that cannot match is worse than no digest,
     * because it reads as a download that was checked.
     */
    fun isApkDigest(raw: String?): Boolean {
        val value = raw?.trim().orEmpty()
        return value.length == 64 && value.all { it in '0'..'9' || it in 'a'..'f' }
    }

    /**
     * True when an APK link is worth offering at all: `https` anywhere, or plain `http` only to
     * loopback, where the wire is the device itself rather than a network path.
     *
     * This is a gate on the *offer*, not a verification of the install. `openDownload` fires
     * `ACTION_VIEW` and never asks `REQUEST_INSTALL_PACKAGES`, so the app receives no bytes and
     * cannot hash anything; the cleartext case this refuses is the one where a tampered file would
     * still install silently.
     */
    fun isVerifiableDownloadUrl(raw: String?): Boolean {
        val value = raw?.trim()?.lowercase().orEmpty()
        if (value.startsWith("https://")) return true
        if (!value.startsWith("http://")) return false
        val authority = value.removePrefix("http://")
            .substringBefore('/')
            .substringBefore('?')
            .substringAfterLast('@')
        // An IPv6 literal is bracketed, so every colon inside the brackets belongs to the address
        // and only a port may follow the closing bracket. Both brackets come off here: cutting on
        // the closing one alone leaves the host as "[::1", which matches nothing, and an
        // unbracketed IPv6 has no port anyway.
        val host = if (authority.startsWith("[")) {
            authority.substringAfter('[').substringBefore(']')
        } else {
            authority.substringBeforeLast(':')
        }
        if (host == "localhost" || host == "::1") return true
        // `127/8` is loopback, `127.example.com` is not, so the prefix has to be followed by
        // nothing but octets. A name that merely starts like the range is a host on the internet.
        return host.startsWith("127.") && host.drop(4).all { it.isDigit() || it == '.' }
    }
}
