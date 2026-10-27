package com.raddstream.app.data.downloads

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.IBinder
import android.os.SystemClock
import android.provider.MediaStore
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.raddstream.app.MainActivity
import com.raddstream.app.brand.Brand
import dagger.hilt.android.AndroidEntryPoint
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream
import javax.inject.Inject
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * The one writer of public downloads. A foreground service is used instead of
 * `DownloadManager` because the platform's public API has no pause/resume (only remove),
 * while the requirement is an honest pause that keeps its bytes.
 *
 * Every request goes to our own `/api/v1/stream?id=<handle>` redirector; OkHttp follows the
 * 302, so the upstream location never reaches this process. Bytes land in
 * `Movies/RaddStream/` — through MediaStore on Android 10+, through the public directory on
 * older devices. The notification carries real progress and Pause / Resume / Cancel.
 */
@AndroidEntryPoint
class DownloadService : Service() {

    @Inject lateinit var repo: DeviceDownloadsRepository

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val queue = ArrayDeque<String>()
    private var activeId: String? = null
    private var job: Job? = null
    private var foreground = false

    private val client = OkHttpClient.Builder()
        .followRedirects(true)
        .followSslRedirects(true)
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private val notifications by lazy {
        getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    }

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Video downloads",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Progress for videos saved to Movies/RaddStream."
                setShowBadge(false)
            }
            notifications.createNotificationChannel(channel)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val id = intent?.getStringExtra(EXTRA_ID).orEmpty()
        when (intent?.action) {
            ACTION_START -> if (id.isNotBlank()) {
                if (activeId != id && !queue.contains(id)) queue.addLast(id)
                ensureForeground(id)
                pump()
            }

            ACTION_PAUSE -> if (id.isNotBlank()) {
                queue.remove(id)
                if (activeId == id) job?.cancel()
                val current = repo.entity(id)
                if (current != null) {
                    repo.markPaused(id, current.bytesDownloaded)
                    notifyPaused(current)
                }
                finishIfIdle()
            }

            ACTION_CANCEL -> if (id.isNotBlank()) {
                queue.remove(id)
                if (activeId == id) job?.cancel()
                repo.entity(id)?.let { repo.deleteOutput(it) }
                repo.removeEntry(id)
                finishIfIdle()
            }

            null -> {
                // A restart with no instruction: only rows that still say QUEUED move.
                repo.nextQueued()?.let { queue.addLast(it.id) }
                pump()
            }
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun pump() {
        if (activeId != null) return
        val next = queue.firstOrNull { repo.entity(it)?.state == DeviceDownloadState.QUEUED }
            ?: run {
                finishIfIdle()
                return
            }
        queue.remove(next)
        activeId = next
        job = scope.launch {
            try {
                download(next)
            } finally {
                activeId = null
                job = null
                pump()
            }
        }
    }

    private suspend fun download(id: String): Unit = withContext(Dispatchers.IO) {
        val entry = repo.entity(id) ?: return@withContext
        if (entry.state != DeviceDownloadState.QUEUED) return@withContext

        var output: OutputStream? = null
        var downloaded = entry.bytesDownloaded.coerceAtLeast(0L)
        var total = entry.bytesTotal
        var target: OutputTarget? = null
        try {
            target = prepareOutput(entry)
            repo.setOutputUri(id, target.uri.toString())

            val builder = Request.Builder()
                .url(entry.url)
                .header("User-Agent", Brand.userAgent)
            if (downloaded > 0) builder.header("Range", "bytes=$downloaded-")
            val response = client.newCall(builder.build()).execute()
            response.use { answer ->
                if (!answer.isSuccessful) throw IOException("HTTP ${answer.code}")
                val body = answer.body ?: throw IOException("empty body")
                if (downloaded > 0 && answer.code != 206) downloaded = 0L
                total = totalBytes(answer.header("Content-Range"), body.contentLength(), downloaded)
                // Some providers refuse append mode. A Range response starts at the old
                // offset, so the only correct restart is a fresh request from zero.
                val stream = try {
                    openOutput(target.uri, downloaded > 0)
                } catch (refusal: IOException) {
                    if (downloaded == 0L) throw refusal
                    repo.resetResume(id)
                    return@withContext download(id)
                }
                output = stream
                repo.markRunning(id, downloaded, total)
                notifyProgress(id, entry, downloaded, total)

                body.byteStream().use { input ->
                    val buffer = ByteArray(CHUNK_BYTES)
                    var lastNotify = 0L
                    while (true) {
                        coroutineContext.ensureActive()
                        val read = input.read(buffer)
                        if (read < 0) break
                        stream.write(buffer, 0, read)
                        downloaded += read
                        val now = SystemClock.elapsedRealtime()
                        if (now - lastNotify >= NOTIFY_INTERVAL_MS) {
                            lastNotify = now
                            repo.markProgress(id, downloaded, total)
                            notifyProgress(id, entry, downloaded, total)
                        }
                    }
                }
            }
            output?.flush()
            output?.close()
            output = null
            finalizeOutput(target.uri, entry.mimeType)
            repo.markReady(id, downloaded, total, target.uri.toString())
            notifyCompleted(entry.title)
        } catch (cancelled: CancellationException) {
            closeQuietly(output)
            val now = repo.entity(id)
            if (now != null && now.state != DeviceDownloadState.PAUSED) {
                repo.markPaused(id, downloaded)
            }
            throw cancelled
        } catch (failure: Throwable) {
            closeQuietly(output)
            val now = repo.entity(id)
            if (now != null && now.state != DeviceDownloadState.PAUSED) {
                repo.markFailed(id, downloaded, total)
                notifyFailed(now, downloaded, total)
            }
        }
    }

    private data class OutputTarget(val uri: Uri, val isMediaStore: Boolean)

    private fun prepareOutput(entry: DeviceDownloadEntity): OutputTarget {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val existing = entry.localUri
                ?.let { runCatching { Uri.parse(it) }.getOrNull() }
                ?.takeIf { it.scheme == "content" }
            if (existing != null) return OutputTarget(existing, true)
            val values = ContentValues().apply {
                put(MediaStore.Video.Media.DISPLAY_NAME, entry.fileName)
                put(MediaStore.Video.Media.MIME_TYPE, entry.mimeType)
                put(
                    MediaStore.Video.Media.RELATIVE_PATH,
                    "${Environment.DIRECTORY_MOVIES}/$SUBDIR",
                )
                put(MediaStore.Video.Media.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("MediaStore refused the destination")
            return OutputTarget(uri, true)
        }
        val file = publicFile(entry.fileName)
        file.parentFile?.mkdirs()
        if (!file.exists()) file.createNewFile()
        return OutputTarget(Uri.fromFile(file), false)
    }

    private fun openOutput(uri: Uri, append: Boolean): OutputStream {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && uri.scheme == "content") {
            val mode = if (append) "wa" else "w"
            return contentResolver.openOutputStream(uri, mode)
                ?: throw IOException("could not open the download destination")
        }
        val file = File(requireNotNull(uri.path))
        return FileOutputStream(file, append)
    }

    private fun finalizeOutput(uri: Uri, mime: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && uri.scheme == "content") {
            val values = ContentValues().apply {
                put(MediaStore.Video.Media.IS_PENDING, 0)
            }
            runCatching { contentResolver.update(uri, values, null, null) }
        } else {
            uri.path?.let { path ->
                runCatching {
                    MediaScannerConnection.scanFile(this, arrayOf(path), arrayOf(mime), null)
                }
            }
        }
    }

    private fun publicFile(fileName: String): File = File(
        File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), SUBDIR),
        fileName,
    )

    private fun totalBytes(contentRange: String?, contentLength: Long, already: Long): Long {
        contentRange?.substringAfterLast('/')?.trim()?.toLongOrNull()?.takeIf { it > 0 }
            ?.let { return it }
        if (contentLength > 0) return already + contentLength
        return 0L
    }

    private fun closeQuietly(output: OutputStream?) {
        runCatching { output?.close() }
    }

    // ── notification ────────────────────────────────────────────────────────────

    private fun ensureForeground(id: String) {
        val entry = repo.entity(id) ?: return
        if (foreground) return
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            buildNotification(entry, entry.state, entry.bytesDownloaded, entry.bytesTotal),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            } else {
                0
            },
        )
        foreground = true
    }

    private fun notifyProgress(
        id: String,
        entry: DeviceDownloadEntity,
        downloaded: Long,
        total: Long,
    ) {
        val current = repo.entity(id) ?: entry
        if (!foreground || current.state == DeviceDownloadState.PAUSED) return
        notifications.notify(
            NOTIFICATION_ID,
            buildNotification(current, DeviceDownloadState.DOWNLOADING, downloaded, total),
        )
    }

    private fun notifyPaused(entry: DeviceDownloadEntity) {
        if (foreground) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_DETACH)
            foreground = false
        }
        notifications.notify(
            NOTIFICATION_ID,
            buildNotification(entry, DeviceDownloadState.PAUSED, entry.bytesDownloaded, entry.bytesTotal),
        )
    }

    private fun notifyFailed(entry: DeviceDownloadEntity, downloaded: Long, total: Long) {
        notifications.notify(
            NOTIFICATION_ID,
            buildNotification(entry, DeviceDownloadState.FAILED, downloaded, total),
        )
    }

    private fun notifyCompleted(title: String) {
        notifications.notify(COMPLETE_NOTIFICATION_ID, completedNotification(title))
    }

    private fun buildNotification(
        entry: DeviceDownloadEntity,
        state: DeviceDownloadState,
        downloaded: Long,
        total: Long,
    ): Notification {
        val percent = if (total > 0) ((downloaded * 100) / total).toInt().coerceIn(0, 100) else 0
        val text = when (state) {
            DeviceDownloadState.QUEUED -> "Queued"
            DeviceDownloadState.DOWNLOADING -> if (total > 0) "Downloading $percent%" else "Downloading"
            DeviceDownloadState.PAUSED -> "Paused — ${formatBytes(downloaded)} saved"
            DeviceDownloadState.READY -> "Saved to Movies/$SUBDIR"
            DeviceDownloadState.FAILED -> "Stopped — open Downloads to resume"
        }
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(entry.title)
            .setContentText(text)
            .setOnlyAlertOnce(true)
            .setContentIntent(openAppIntent())
            .setOngoing(state == DeviceDownloadState.DOWNLOADING ||
                state == DeviceDownloadState.QUEUED)
        if (state == DeviceDownloadState.DOWNLOADING && total > 0) {
            builder.setProgress(100, percent, false)
        } else if (state == DeviceDownloadState.DOWNLOADING) {
            builder.setProgress(0, 0, true)
        }
        when (state) {
            DeviceDownloadState.DOWNLOADING, DeviceDownloadState.QUEUED ->
                builder.addAction(0, "Pause", serviceIntent(ACTION_PAUSE, entry.id))
            DeviceDownloadState.PAUSED, DeviceDownloadState.FAILED ->
                builder.addAction(0, "Resume", resumeIntent(entry.id))
            else -> Unit
        }
        builder.addAction(0, "Cancel", serviceIntent(ACTION_CANCEL, entry.id))
        return builder.build()
    }

    private fun completedNotification(title: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle(title)
            .setContentText("Download complete · Movies/$SUBDIR")
            .setAutoCancel(true)
            .setContentIntent(openAppIntent())
            .build()

    private fun serviceIntent(action: String, id: String): PendingIntent =
        PendingIntent.getService(
            this,
            (action + id).hashCode(),
            Intent(this, DownloadService::class.java).setAction(action).putExtra(EXTRA_ID, id),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    private fun resumeIntent(id: String): PendingIntent =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            PendingIntent.getForegroundService(
                this,
                (ACTION_START + id).hashCode(),
                Intent(this, DownloadService::class.java)
                    .setAction(ACTION_START)
                    .putExtra(EXTRA_ID, id),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        } else {
            serviceIntent(ACTION_START, id)
        }

    private fun openAppIntent(): PendingIntent {
        val launch = packageManager.getLaunchIntentForPackage(packageName)
            ?: Intent(this, MainActivity::class.java)
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(
            this,
            0,
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun finishIfIdle() {
        if (activeId != null) return
        val pending = repo.nextQueued()
        if (pending != null) {
            queue.addLast(pending.id)
            pump()
            return
        }
        if (foreground) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            foreground = false
        }
        stopSelf()
    }

    private fun formatBytes(bytes: Long): String = when {
        bytes >= 1_000_000_000 -> "%.1f GB".format(bytes / 1_000_000_000.0)
        bytes >= 1_000_000 -> "%.0f MB".format(bytes / 1_000_000.0)
        bytes >= 1_000 -> "%.0f KB".format(bytes / 1_000.0)
        else -> "$bytes B"
    }

    companion object {
        private const val CHANNEL_ID = "radd_downloads"
        private const val NOTIFICATION_ID = 7101
        private const val COMPLETE_NOTIFICATION_ID = 7102
        private const val EXTRA_ID = "download_id"
        private const val ACTION_START = "com.raddstream.app.downloads.START"
        private const val ACTION_PAUSE = "com.raddstream.app.downloads.PAUSE"
        private const val ACTION_CANCEL = "com.raddstream.app.downloads.CANCEL"
        private const val SUBDIR = "RaddStream"
        private const val CHUNK_BYTES = 64 * 1024
        private const val NOTIFY_INTERVAL_MS = 750L

        fun start(context: Context, id: String) {
            val intent = Intent(context, DownloadService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_ID, id)
            ContextCompat.startForegroundService(context, intent)
        }

        fun pause(context: Context, id: String) {
            val intent = Intent(context, DownloadService::class.java)
                .setAction(ACTION_PAUSE)
                .putExtra(EXTRA_ID, id)
            runCatching { context.startService(intent) }
        }

        fun cancel(context: Context, id: String) {
            val intent = Intent(context, DownloadService::class.java)
                .setAction(ACTION_CANCEL)
                .putExtra(EXTRA_ID, id)
            runCatching { context.startService(intent) }
        }
    }
}
