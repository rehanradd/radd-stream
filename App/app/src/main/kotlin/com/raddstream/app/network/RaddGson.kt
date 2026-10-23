package com.raddstream.app.network

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.TypeAdapter
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import com.google.gson.stream.JsonWriter

/**
 * The one Gson configuration the whole app must use.
 *
 * WHY THE LENIENT ADAPTERS EXIST
 * ------------------------------
 * The backend is SQLite behind `json.dumps`, so the JSON type of a column follows the
 * column's storage affinity, not the model's intent:
 *  - `download_sources.is_temporary` / `is_resumable` are INTEGER 0/1 and arrive as
 *    `1` / `0` from `GET /api/v1/posts/{id}` (a bare `SELECT *`), while
 *    `resolve_live_source()` wraps them in `bool()` and arrives as `true` / `false` from
 *    `GET /api/v1/stream`. Same concept, two JSON spellings on two live endpoints, and
 *    `API_V2.md` §6 promises booleans again.
 *  - `posts.year` / `posts.tmdb_id` are INTEGER-affinity but SQLite keeps a value that
 *    does not look numeric (a `"2017-2019"` range some scrapers emit) as TEXT.
 *
 * Gson's built-in adapters throw `JsonSyntaxException` on those surprises, which in an
 * Android app means a crash on one bad catalog row. Each adapter below therefore accepts
 * every spelling the server can legitimately produce, maps what it cannot understand to
 * `null` (= "no evidence", never a fabricated value), and can never crash the client.
 *
 * Registration is by boxed hierarchy type, so it applies to the nullable Kotlin fields
 * (`Int?`, `Boolean?`, …) that the wire models use for exactly that reason.
 */
fun buildRaddGson(): Gson = GsonBuilder()
    .registerTypeHierarchyAdapter(java.lang.Integer::class.java, LenientIntAdapter())
    .registerTypeHierarchyAdapter(java.lang.Long::class.java, LenientLongAdapter())
    .registerTypeHierarchyAdapter(java.lang.Double::class.java, LenientDoubleAdapter())
    .registerTypeHierarchyAdapter(java.lang.Boolean::class.java, LenientBooleanAdapter())
    .create()

/** Integer | "2026" | "2026.0" | null → Int?. Anything unparseable is null, not 0. */
class LenientIntAdapter : TypeAdapter<Int?>() {
    override fun write(out: JsonWriter, value: Int?) {
        if (value == null) out.nullValue() else out.value(value.toLong())
    }

    override fun read(reader: JsonReader): Int? = when (reader.peek()) {
        JsonToken.NULL -> { reader.nextNull(); null }
        JsonToken.BOOLEAN -> { reader.nextBoolean(); null }
        else -> parseLenientInt(reader.nextString())
    }
}

/** Same contract as [LenientIntAdapter] for 64-bit columns (`file_size_bytes`). */
class LenientLongAdapter : TypeAdapter<Long?>() {
    override fun write(out: JsonWriter, value: Long?) {
        if (value == null) out.nullValue() else out.value(value)
    }

    override fun read(reader: JsonReader): Long? = when (reader.peek()) {
        JsonToken.NULL -> { reader.nextNull(); null }
        JsonToken.BOOLEAN -> { reader.nextBoolean(); null }
        else -> parseLenientLong(reader.nextString())
    }
}

/** REAL columns (`speed_mbps`, `imdb_rating` if a future build sends a number). */
class LenientDoubleAdapter : TypeAdapter<Double?>() {
    override fun write(out: JsonWriter, value: Double?) {
        if (value == null) out.nullValue() else out.value(value)
    }

    override fun read(reader: JsonReader): Double? = when (reader.peek()) {
        JsonToken.NULL -> { reader.nextNull(); null }
        JsonToken.BOOLEAN -> { reader.nextBoolean(); null }
        else -> reader.nextString().trim().toDoubleOrNull()
    }
}

/**
 * Boolean | 0/1 | "true"/"false" | null → Boolean?.
 * This is the field type that the previous model got wrong (`isTemporary: Int?` against a
 * JSON boolean), so both spellings are now legal by design on every endpoint.
 */
class LenientBooleanAdapter : TypeAdapter<Boolean?>() {
    override fun write(out: JsonWriter, value: Boolean?) {
        if (value == null) out.nullValue() else out.value(value)
    }

    override fun read(reader: JsonReader): Boolean? = when (reader.peek()) {
        JsonToken.NULL -> { reader.nextNull(); null }
        JsonToken.BOOLEAN -> reader.nextBoolean()
        else -> parseLenientBoolean(reader.nextString())
    }
}

internal fun parseLenientInt(raw: String?): Int? {
    val text = raw?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    text.toIntOrNull()?.let { return it }
    val asDouble = text.toDoubleOrNull()
    if (asDouble != null && asDouble.isFinite()) return asDouble.toInt()
    // "S07", "(01-06)" and friends: first digit run is the number, if any.
    return Regex("\\d+").find(text)?.value?.toIntOrNull()
}

internal fun parseLenientLong(raw: String?): Long? {
    val text = raw?.trim()?.takeIf { it.isNotEmpty() } ?: return null
    text.toLongOrNull()?.let { return it }
    val asDouble = text.toDoubleOrNull()
    if (asDouble != null && asDouble.isFinite()) return asDouble.toLong()
    return Regex("\\d+").find(text)?.value?.toLongOrNull()
}

internal fun parseLenientBoolean(raw: String?): Boolean? {
    val text = raw?.trim()?.lowercase() ?: return null
    return when (text) {
        "true", "1", "yes", "y" -> true
        "false", "0", "no", "n" -> false
        else -> null
    }
}
