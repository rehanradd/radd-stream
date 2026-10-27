package com.raddstream.app.data.downloads

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.content.ContextCompat
import com.google.gson.Gson
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.buildRaddGson
import com.raddstream.app.network.streamRedirectUrl
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.util.Locale
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

/** The five states a public download can be in. */
enum class DeviceDownloadState { QUEUED, DOWNLOADING, PAUSED, READY, FAILED }

/** One public download as the Downloads screen and the service both see it. */
data class DeviceDownload(
    val id: String,
    val title: String,
    val printLabel: String,
    val state: DeviceDownloadState,
    val bytesDownloaded: Long,
    val bytesTotal: Long,
    val localUri: String?,
    val mimeType: String,
    val fileName: String,
) {
    val progress: Float
        get() = if (bytesTotal > 0) {
            (bytesDownloaded.toFloat() / bytesTotal.toFloat()).coerceIn(0f, 1f)
        } else {
            0f
        }

    val percent: Int?
        get() = if (bytesTotal > 0) (progress * 100).toInt().coerceIn(0, 100) else null

    val playing: Boolean get() = state == DeviceDownloadState.READY && !localUri.isNullOrBlank()
    val canPause: Boolean
        get() = state == DeviceDownloadState.QUEUED || state == DeviceDownloadState.DOWNLOADING
    val canResume: Boolean
        get() = state == DeviceDownloadState.PAUSED || state == DeviceDownloadState.FAILED
}

/** What one enqueue attempt did, so the caller can say something true to the viewer. */
sealed interface DeviceDownloadResult {
    data class Enqueued(val download: DeviceDownload) : DeviceDownloadResult
    data object NeedsPermission : DeviceDownloadResult
    data class Refused(val message: String) : DeviceDownloadResult
}

/**
 * The persisted half of one public download. [url] is always our own redirector — the server's
 * resolve answer is used only to verify the handle and name the container, never to learn an
 * upstream location. The service owns the bytes; this class owns the durable state and the
 * observable list both screens read.
 */
data class DeviceDownloadEntity(
    val id: String = "",
    val handle: String = "",
    val url: String = "",
    val title: String = "",
    val printLabel: String = "",
    val mimeType: String = "video/mp4",
    val fileName: String = "",
    val bytesDownloaded: Long = 0L,
    val bytesTotal: Long = 0L,
    val state: DeviceDownloadState = DeviceDownloadState.QUEUED,
    val localUri: String? = null,
    val enqueuedAt: Long = 0L,
    val error: String? = null,
)

/**
 * Public, user-visible downloads written to `Movies/RaddStream/` by [DownloadService].
 * Kept separate from the in-app cache engine: these bytes survive the app and play in
 * any video player.
 *
 * The repository is also the service's durable memory. Progress is held in memory and
 * flushed at a human pace (about once a second) so a long download does not rewrite
 * SharedPreferences for every network chunk, while a pause, failure or completion is
 * always persisted before the UI hears about it.
 */
@Singleton
class DeviceDownloadsRepository @Inject constructor(
    @ApplicationContext val context: Context,
    private val apiProvider: ApiProvider,
) {
    private val gson: Gson = buildRaddGson()
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val _downloads = MutableStateFlow<List<DeviceDownload>>(emptyList())
    val downloads: StateFlow<List<DeviceDownload>> = _downloads.asStateFlow()

    private var persistedAt = HashMap<String, Long>()

    init {
        // A row left mid-flight by a dead process is paused, not silently downloading:
        // nothing is feeding it until the service is asked again.
        val entries = load().map {
            if (it.state == DeviceDownloadState.DOWNLOADING) {
                it.copy(state = DeviceDownloadState.PAUSED)
            } else {
                it
            }
        }
        persist(entries)
        emit(entries)
    }

    /** API 28 and older need the legacy write permission; API 29+ writes through MediaStore. */
    fun hasWriteAccess(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ||
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.WRITE_EXTERNAL_STORAGE,
            ) == PackageManager.PERMISSION_GRANTED

    suspend fun enqueue(
        handle: String,
        title: String,
        printLabel: String,
    ): DeviceDownloadResult = withContext(Dispatchers.IO) {
        if (handle.isBlank()) return@withContext DeviceDownloadResult.Refused(
            "This copy has no address to download.",
        )
        if (!hasWriteAccess()) return@withContext DeviceDownloadResult.NeedsPermission

        val entries = load()
        entries.firstOrNull { it.handle == handle && it.state != DeviceDownloadState.FAILED }
            ?.let { existing ->
                when (existing.state) {
                    DeviceDownloadState.QUEUED ->
                        runCatching { DownloadService.start(context, existing.id) }
                    DeviceDownloadState.PAUSED -> requestResume(existing.id)
                    else -> Unit
                }
                return@withContext DeviceDownloadResult.Enqueued(existing.toUi())
            }

        val baseUrl = runCatching { apiProvider.currentBaseUrl() }.getOrNull()
            ?: return@withContext DeviceDownloadResult.Refused(
                "Connect to a catalog server before downloading.",
            )
        val meta = runCatching { apiProvider.current().resolveStream(handle, "0") }.getOrNull()
        if (meta == null || !meta.success || meta.streamId == null) {
            return@withContext DeviceDownloadResult.Refused(
                "The server could not verify this copy just now. Try another print.",
            )
        }
        val mime = videoMime(meta.mimeType, meta.kind)
            ?: return@withContext DeviceDownloadResult.Refused(
                "This copy is a web page or a segmented playlist, not one downloadable video file.",
            )

        val cleanTitle = title.trim().ifBlank { "Video" }
        val cleanLabel = printLabel.trim()
        val entry = DeviceDownloadEntity(
            id = UUID.randomUUID().toString(),
            handle = handle,
            url = streamRedirectUrl(baseUrl, handle),
            title = cleanTitle,
            printLabel = cleanLabel,
            mimeType = mime,
            fileName = uniqueFileName(cleanTitle, cleanLabel, extensionFor(mime), entries),
            bytesTotal = meta.fileSizeBytes ?: 0L,
            state = DeviceDownloadState.QUEUED,
            enqueuedAt = System.currentTimeMillis(),
        )
        val updated = entries + entry
        persist(updated)
        emit(updated)
        val started = runCatching { DownloadService.start(context, entry.id) }.isSuccess
        if (!started) {
            update(entry.id) {
                it.copy(state = DeviceDownloadState.FAILED, error = "The system refused to start the download.")
            }
            return@withContext DeviceDownloadResult.Refused(
                "The system would not start the download. Try again from the app.",
            )
        }
        DeviceDownloadResult.Enqueued(entry.toUi())
    }

    fun requestPause(id: String) {
        val current = load().firstOrNull { it.id == id } ?: return
        if (current.state != DeviceDownloadState.QUEUED &&
            current.state != DeviceDownloadState.DOWNLOADING
        ) {
            return
        }
        update(id) { it.copy(state = DeviceDownloadState.PAUSED) }
        DownloadService.pause(context, id)
    }

    fun requestResume(id: String) {
        val current = load().firstOrNull { it.id == id } ?: return
        if (current.state != DeviceDownloadState.PAUSED &&
            current.state != DeviceDownloadState.FAILED
        ) {
            return
        }
        update(id) { it.copy(state = DeviceDownloadState.QUEUED, error = null) }
        DownloadService.start(context, id)
    }

    fun requestRemove(id: String) {
        val current = load().firstOrNull { it.id == id } ?: return
        if (current.state == DeviceDownloadState.READY ||
            current.state == DeviceDownloadState.FAILED ||
            current.state == DeviceDownloadState.PAUSED
        ) {
            deleteOutput(current)
            removeEntry(id)
        } else {
            // An active writer must close its stream before the file is deleted.
            DownloadService.cancel(context, id)
        }
    }

    internal fun entity(id: String): DeviceDownloadEntity? =
        load().firstOrNull { it.id == id }

    internal fun markRunning(id: String, downloaded: Long, total: Long) {
        updateInMemory(id) {
            if (it.state == DeviceDownloadState.PAUSED ||
                it.state == DeviceDownloadState.FAILED ||
                it.state == DeviceDownloadState.READY
            ) {
                it
            } else {
                it.copy(
                    state = DeviceDownloadState.DOWNLOADING,
                    bytesDownloaded = downloaded,
                    bytesTotal = if (total > 0) total else it.bytesTotal,
                )
            }
        }
    }

    internal fun markProgress(id: String, downloaded: Long, total: Long) {
        markRunning(id, downloaded, total)
        val now = System.currentTimeMillis()
        if (now - (persistedAt[id] ?: 0L) >= PROGRESS_FLUSH_MS) {
            persistedAt[id] = now
            persist(currentEntities())
        }
    }

    internal fun markPaused(id: String, downloaded: Long) {
        update(id) {
            it.copy(
                state = DeviceDownloadState.PAUSED,
                bytesDownloaded = downloaded,
                error = null,
            )
        }
    }

    internal fun markFailed(id: String, downloaded: Long, total: Long) {
        update(id) {
            it.copy(
                state = DeviceDownloadState.FAILED,
                bytesDownloaded = downloaded,
                bytesTotal = if (total > 0) total else it.bytesTotal,
                error = "Download stopped before it finished.",
            )
        }
    }

    internal fun markReady(id: String, downloaded: Long, total: Long, localUri: String) {
        update(id) {
            it.copy(
                state = DeviceDownloadState.READY,
                bytesDownloaded = downloaded,
                bytesTotal = if (total > 0) total else it.bytesTotal,
                localUri = localUri,
                error = null,
            )
        }
        persistedAt.remove(id)
    }

    internal fun setOutputUri(id: String, uri: String) {
        update(id) { it.copy(localUri = uri) }
    }

    /** Drops the resume offset when the destination cannot append; bytes restart from zero. */
    internal fun resetResume(id: String) {
        update(id) { it.copy(bytesDownloaded = 0L) }
    }

    internal fun nextQueued(): DeviceDownloadEntity? =
        load().firstOrNull { it.state == DeviceDownloadState.QUEUED }

    internal fun removeEntry(id: String) {
        val remaining = load().filterNot { it.id == id }
        persistedAt.remove(id)
        persist(remaining)
        emit(remaining)
    }

    internal fun deleteOutput(entity: DeviceDownloadEntity) {
        val raw = entity.localUri?.takeIf { it.isNotBlank() } ?: return
        val uri = runCatching { Uri.parse(raw) }.getOrNull() ?: return
        when (uri.scheme?.lowercase(Locale.ROOT)) {
            "content" -> runCatching { context.contentResolver.delete(uri, null, null) }
            "file" -> uri.path?.let { runCatching { File(it).delete() } }
        }
    }

    internal fun uiRow(id: String): DeviceDownload? = entity(id)?.toUi()

    private fun update(id: String, transform: (DeviceDownloadEntity) -> DeviceDownloadEntity) {
        val updated = load().map { if (it.id == id) transform(it) else it }
        persist(updated)
        emit(updated)
    }

    private fun updateInMemory(id: String, transform: (DeviceDownloadEntity) -> DeviceDownloadEntity) {
        val updated = currentEntities().map { if (it.id == id) transform(it) else it }
        emit(updated)
    }

    private var memory: List<DeviceDownloadEntity>? = null

    @Synchronized
    private fun currentEntities(): List<DeviceDownloadEntity> {
        memory?.let { return it }
        return load().also { memory = it }
    }

    @Synchronized
    private fun persist(entries: List<DeviceDownloadEntity>) {
        memory = entries
        prefs.edit().putString(KEY_ENTRIES, gson.toJson(entries)).apply()
    }

    @Synchronized
    private fun load(): List<DeviceDownloadEntity> {
        memory?.let { return it }
        val raw = prefs.getString(KEY_ENTRIES, null) ?: return emptyList()
        val entries = runCatching {
            gson.fromJson(raw, Array<DeviceDownloadEntity>::class.java)?.toList().orEmpty()
        }.getOrDefault(emptyList())
        memory = entries
        return entries
    }

    private fun emit(entries: List<DeviceDownloadEntity>) {
        _downloads.value = entries
            .sortedByDescending { it.enqueuedAt }
            .map { it.toUi() }
    }

    private fun DeviceDownloadEntity.toUi(): DeviceDownload = DeviceDownload(
        id = id,
        title = title.ifBlank { "Video" },
        printLabel = printLabel,
        state = state,
        bytesDownloaded = bytesDownloaded,
        bytesTotal = bytesTotal,
        localUri = localUri,
        mimeType = mimeType,
        fileName = fileName,
    )

    private fun videoMime(declared: String?, kind: String?): String? {
        val mime = declared?.trim()?.lowercase(Locale.ROOT).orEmpty()
        if ("mpegurl" in mime || "mp2t" in mime) return null
        if (mime.startsWith("video/")) {
            return when {
                "matroska" in mime -> "video/x-matroska"
                "webm" in mime -> "video/webm"
                "x-msvideo" in mime -> "video/x-msvideo"
                else -> "video/mp4"
            }
        }
        if ("matroska" in mime) return "video/x-matroska"
        if (mime.isBlank() || mime == "application/octet-stream") {
            // A direct/resolve/download handle is a byte endpoint; "external" without a video
            // mime is a landing page, and saving HTML under a video name helps nobody.
            return if (kind in setOf("direct", "resolve", "download")) "video/mp4" else null
        }
        return null
    }

    private fun extensionFor(mime: String): String = when (mime) {
        "video/x-matroska" -> "mkv"
        "video/webm" -> "webm"
        "video/x-msvideo" -> "avi"
        else -> "mp4"
    }

    private fun uniqueFileName(
        title: String,
        printLabel: String,
        extension: String,
        existing: List<DeviceDownloadEntity>,
    ): String {
        val base = sanitize("$title${if (printLabel.isNotBlank()) " [$printLabel]" else ""}")
            .ifBlank { "video" }
            .take(MAX_NAME_CHARS)
        val used = existing.map { it.fileName }.toSet()
        var candidate = "$base.$extension"
        var suffix = 2
        while (candidate in used) {
            candidate = "$base ($suffix).$extension"
            suffix++
        }
        return candidate
    }

    private fun sanitize(value: String): String =
        value.replace(Regex("""[\\/:*?"<>|\u0000-\u001F]"""), "_")
            .trim()
            .trim('.')

    private companion object {
        const val PREFS_NAME = "radd_device_downloads"
        const val KEY_ENTRIES = "entries"
        const val MAX_NAME_CHARS = 80
        const val PROGRESS_FLUSH_MS = 1_000L
    }
}
