package com.raddstream.app.data.local

/**
 * A video that already lives on this phone, found through MediaStore — the
 * Media Vault's "on this phone" list. The URI is the provider's own
 * `content://media/…` address for the row, so the player opens it exactly like
 * a finished download; the title is the file's display name, never a path.
 *
 * Everything in this file is pure — plain values in, plain values out — so the
 * query shape, the title rule and the folder rule are all pinned by JVM tests
 * without a provider. The [LocalFilesRepository] owns the Cursor.
 */
data class LocalVideoFile(
    val uri: String,
    val title: String,
    val durationMs: Long,
    val sizeBytes: Long,
    val folder: String,
    val dateAddedMs: Long,
)

/** The file name a row with no usable name is shown under. Never blank. */
const val LOCAL_VIDEO_UNTITLED = "Local video"

/** Containers the plan promises: .mp4, .mkv, .webm. */
val LOCAL_VIDEO_MIMES = setOf("video/mp4", "video/x-matroska", "video/webm")

private val LOCAL_VIDEO_EXTENSIONS = setOf("mp4", "mkv", "webm")

/**
 * The MediaStore query for the Movies/ and Download/ folders, as a selection
 * string plus its arguments. [useRelativePath] is true on API 29+, where the
 * provider answers `relative_path` (`Movies/…`, `Download/…`); older releases
 * have only the `_data` filesystem path. The format clause accepts either a
 * known video MIME or a known extension, because providers disagree about
 * which one they fill in for .mkv rows.
 */
fun localVideoSelection(useRelativePath: Boolean): Pair<String, Array<String>> {
    val folderColumn = if (useRelativePath) "relative_path" else "_data"
    val folderArgs = if (useRelativePath) {
        arrayOf("Movies%", "Download%")
    } else {
        arrayOf("%/Movies/%", "%/Download/%")
    }
    val selection = "($folderColumn LIKE ? OR $folderColumn LIKE ?) AND " +
        "(mime_type IN (?, ?, ?) OR _display_name LIKE ? OR _display_name LIKE ? OR _display_name LIKE ?)"
    val args = folderArgs + arrayOf(
        "video/mp4", "video/x-matroska", "video/webm",
        "%.mp4", "%.mkv", "%.webm",
    )
    return selection to args
}

/**
 * A display name out of whatever the provider stored. The extension comes
 * off, underscores read as spaces, and a name that is blank or only digits
 * (a bare row id wearing a name) falls back to [LOCAL_VIDEO_UNTITLED] — the
 * same honesty rule [LocalVideoOpen] applies to an outside intent.
 */
fun localVideoTitle(displayName: String?): String {
    val raw = displayName?.takeIf { it.isNotBlank() } ?: return LOCAL_VIDEO_UNTITLED
    val name = raw.substringAfterLast('/').substringBeforeLast('.')
    val cleaned = name.replace('_', ' ').filterNot { it.isISOControl() }.trim().take(80)
    return cleaned.takeIf { it.isNotEmpty() && !cleaned.all { ch -> ch.isDigit() } }
        ?: LOCAL_VIDEO_UNTITLED
}

/**
 * Which of the two folders a row came from, for the row's subtitle. A
 * `relative_path` reads `Movies/…` / `Download/…`; a `_data` path carries the
 * same folders after a `/`. Anything else is honest about being neither.
 */
fun localVideoFolder(relativePath: String?, dataPath: String?): String {
    val path = relativePath ?: dataPath ?: return "On this phone"
    return when {
        path.startsWith("Movies/") || path.contains("/Movies/") -> "Movies"
        path.startsWith("Download/") || path.contains("/Download/") -> "Downloads"
        else -> "On this phone"
    }
}

/** The defensive re-check on a row the SQL already filtered: a known video MIME or a known extension. */
fun isLocalVideoFile(mimeType: String?, displayName: String?): Boolean {
    if (mimeType?.lowercase() in LOCAL_VIDEO_MIMES) return true
    val extension = displayName?.substringAfterLast('.', "").orEmpty().lowercase()
    return extension in LOCAL_VIDEO_EXTENSIONS
}

/**
 * One cursor row as a [LocalVideoFile], or null when the row is not one of the
 * promised containers after all. [uri] is the provider address the repository
 * already built for the row id; [dateAddedMs] is epoch milliseconds (the
 * provider stores seconds).
 */
fun localVideoFromRow(
    uri: String,
    displayName: String?,
    durationMs: Long,
    sizeBytes: Long,
    relativePath: String?,
    dataPath: String?,
    mimeType: String?,
    dateAddedMs: Long,
): LocalVideoFile? {
    if (!isLocalVideoFile(mimeType, displayName)) return null
    return LocalVideoFile(
        uri = uri,
        title = localVideoTitle(displayName),
        durationMs = durationMs,
        sizeBytes = sizeBytes,
        folder = localVideoFolder(relativePath, dataPath),
        dateAddedMs = dateAddedMs,
    )
}
