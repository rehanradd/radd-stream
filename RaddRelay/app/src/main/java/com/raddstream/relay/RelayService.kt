package com.raddstream.relay

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** One TID waiting for (or in the middle of) a POST. */
data class QueueItem(val gateway: String, val tid: String, val amount: String)

/**
 * Foreground service that owns the offline queue and the POSTs.
 *
 * Why a service: a broadcast receiver gets seconds, the operator's phone may be
 * offline for hours, and the TID must survive both. The service holds a
 * persistent queue in SharedPreferences, retries with backoff, and wakes up when
 * the network comes back.
 *
 * The endpoint is POST {server}/api/v2/payment/sms-webhook with the
 * X-Merchant-Secret header and {"gateway", "tid", "amount"}. Measured 2026-10-31:
 * that route does not exist in Fast_Fetch yet — the catalog server only has the
 * authenticated /api/v2/account/payment claim. See README §"Server contract".
 */
class RelayService : Service() {

    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val draining = AtomicBoolean(false)
    private var failures = 0
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private val drainRunnable = Runnable { executor.execute { drain() } }

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(NOTIFICATION_ID, buildNotification(null))
        isRunning = true
        registerNetwork()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                RelayPrefs.setEnabled(this, false)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_START -> RelayPrefs.setEnabled(this, true)
        }
        drainLater(0)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        isRunning = false
        networkCallback?.let {
            runCatching {
                (getSystemService(ConnectivityManager::class.java))?.unregisterNetworkCallback(it)
            }
        }
        main.removeCallbacks(drainRunnable)
        executor.shutdown()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ queue

    /**
     * Post queued items in order. Runs on the single executor thread; the
     * compareAndSet keeps a network callback and a manual retry from draining
     * the same queue twice.
     */
    private fun drain() {
        if (!draining.compareAndSet(false, true)) return
        try {
            var queue = RelayPrefs.loadQueue(this)
            while (queue.isNotEmpty()) {
                val config = RelayPrefs.config(this)
                if (config.baseUrl.isBlank() || config.secret.isBlank()) {
                    RelayLog.add("not configured — ${queue.size} queued; set URL and secret")
                    break
                }
                if (!networkAvailable()) {
                    RelayLog.add("offline — ${queue.size} queued")
                    break
                }
                val item = queue.first()
                when (val result = post(config, item)) {
                    is PostResult.Ok -> {
                        failures = 0
                        queue.removeAt(0)
                        RelayPrefs.saveQueue(this, queue)
                        RelayPrefs.markRelayed(this, item.tid)
                        RelayLog.add("relayed ${item.gateway} ${item.tid} · Rs ${item.amount}")
                    }
                    is PostResult.Reject -> {
                        // A 4xx means the request itself is wrong (bad secret,
                        // malformed payload). Retrying cannot fix it, and the
                        // operator must see it, so the item leaves the queue
                        // with a permanent-failure log line, never silently.
                        queue.removeAt(0)
                        RelayPrefs.saveQueue(this, queue)
                        RelayLog.add("REJECTED ${item.tid} — ${result.reason}")
                    }
                    is PostResult.Retry -> {
                        failures += 1
                        RelayLog.add("retry ${item.tid} — ${result.reason}")
                        break
                    }
                }
            }
            queue = RelayPrefs.loadQueue(this)
            updateNotification(queue.size)
        } finally {
            draining.set(false)
        }
        if (RelayPrefs.loadQueue(this).isNotEmpty()) {
            drainLater(backoffMillis(failures))
        }
    }

    private fun backoffMillis(failures: Int): Long = when {
        failures <= 1 -> 30_000L
        failures == 2 -> 120_000L
        else -> 600_000L
    }

    // ------------------------------------------------------------- networking

    private sealed class PostResult {
        object Ok : PostResult()
        data class Reject(val reason: String) : PostResult()
        data class Retry(val reason: String) : PostResult()
    }

    private fun post(config: RelayPrefs.Config, item: QueueItem): PostResult {
        var connection: HttpURLConnection? = null
        return try {
            val url = URL(config.baseUrl.trimEnd('/') + WEBHOOK_PATH)
            connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 15_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("X-Merchant-Secret", config.secret)
                setRequestProperty("User-Agent", "RaddRelay/1.0")
            }
            val payload = JSONObject()
                .put("gateway", item.gateway)
                .put("tid", item.tid)
                .put("amount", item.amount.toLongOrNull() ?: item.amount)
                .toString()
            connection.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }

            when (val code = connection.responseCode) {
                in 200..299 -> PostResult.Ok
                409 -> PostResult.Ok            // idempotent duplicate
                401, 403 -> PostResult.Reject("HTTP $code — merchant secret rejected")
                408, 429 -> PostResult.Retry("HTTP $code")
                in 400..499 -> PostResult.Reject("HTTP $code")
                else -> PostResult.Retry("HTTP $code")
            }
        } catch (io: IOException) {
            PostResult.Retry(io.message ?: "network error")
        } catch (e: Exception) {
            // A malformed URL is a configuration error, not a transport one:
            // retrying it forever would hide the mistake.
            PostResult.Reject(e.message ?: e.javaClass.simpleName)
        } finally {
            connection?.disconnect()
        }
    }

    private fun networkAvailable(): Boolean {
        val manager = getSystemService(ConnectivityManager::class.java) ?: return false
        val capabilities = manager.getNetworkCapabilities(manager.activeNetwork) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    private fun registerNetwork() {
        val manager = getSystemService(ConnectivityManager::class.java) ?: return
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                RelayLog.add("network available — draining")
                drainLater(0)
            }
        }
        networkCallback = callback
        runCatching { manager.registerDefaultNetworkCallback(callback) }
    }

    private fun drainLater(delayMillis: Long) {
        main.removeCallbacks(drainRunnable)
        if (delayMillis <= 0L) main.post(drainRunnable)
        else main.postDelayed(drainRunnable, delayMillis)
    }

    // ----------------------------------------------------------- notification

    private fun createChannel() {
        val manager = getSystemService(NotificationManager::class.java) ?: return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "RaddRelay",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Persistent relay status. Turning this off hides the app's only indicator."
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(queued: Int?): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("RaddRelay Active - Listening for JazzCash/EasyPaisa")
            .setContentIntent(open)
            .setOngoing(true)
        if (queued != null && queued > 0) {
            builder.setContentText("$queued payment(s) waiting to relay")
        }
        return builder.build()
    }

    private fun updateNotification(queued: Int) {
        runCatching {
            getSystemService(NotificationManager::class.java)
                ?.notify(NOTIFICATION_ID, buildNotification(queued))
        }
    }

    private fun paymentFrom(intent: Intent?): SmsParser.Payment? {
        if (intent?.action != ACTION_ENQUEUE) return null
        val gateway = intent.getStringExtra(EXTRA_GATEWAY) ?: return null
        val tid = intent.getStringExtra(EXTRA_TID) ?: return null
        val amount = intent.getStringExtra(EXTRA_AMOUNT) ?: return null
        return SmsParser.Payment(gateway, tid, amount)
    }

    companion object {
        const val ACTION_START = "com.raddstream.relay.START"
        const val ACTION_STOP = "com.raddstream.relay.STOP"
        const val ACTION_ENQUEUE = "com.raddstream.relay.ENQUEUE"
        private const val EXTRA_GATEWAY = "gateway"
        private const val EXTRA_TID = "tid"
        private const val EXTRA_AMOUNT = "amount"
        private const val CHANNEL_ID = "relay"
        private const val NOTIFICATION_ID = 41
        const val WEBHOOK_PATH = "/api/v2/payment/sms-webhook"

        @Volatile
        var isRunning: Boolean = false
            private set

        /** Called by the receiver. Starting a foreground service from an SMS
         *  broadcast is permitted on every API this app targets (26–34). */
        fun enqueue(context: Context, payment: SmsParser.Payment) {
            val intent = Intent(context, RelayService::class.java)
                .setAction(ACTION_ENQUEUE)
                .putExtra(EXTRA_GATEWAY, payment.gateway)
                .putExtra(EXTRA_TID, payment.tid)
                .putExtra(EXTRA_AMOUNT, payment.amount)
            context.startForegroundService(intent)
        }
    }
}

/** Restarts the relay after a reboot if the operator had started it. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (!RelayPrefs.isEnabled(context)) return
        context.startForegroundService(
            Intent(context, RelayService::class.java).setAction(RelayService.ACTION_START),
        )
    }
}

/** Server URL, merchant secret, the pending queue, and the relayed-TID set. */
object RelayPrefs {

    private const val FILE = "raddrelay"
    private const val KEY_URL = "server_url"
    private const val KEY_SECRET = "merchant_secret"
    private const val KEY_ENABLED = "enabled"
    private const val KEY_QUEUE = "queue"
    private const val KEY_RELAYED = "relayed_tids"
    private const val DEFAULT_URL = "http://92.4.95.252"
    private const val RELAYED_CAP = 500

    data class Config(val baseUrl: String, val secret: String)

    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun config(context: Context): Config {
        val prefs = prefs(context)
        return Config(
            baseUrl = prefs.getString(KEY_URL, DEFAULT_URL).orEmpty().trim(),
            secret = prefs.getString(KEY_SECRET, "").orEmpty().trim(),
        )
    }

    fun setConfig(context: Context, baseUrl: String, secret: String) {
        prefs(context).edit()
            .putString(KEY_URL, baseUrl.trim())
            .putString(KEY_SECRET, secret.trim())
            .apply()
    }

    fun isEnabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_ENABLED, enabled).apply()
    }

    @Synchronized
    fun loadQueue(context: Context): MutableList<QueueItem> {
        val raw = prefs(context).getString(KEY_QUEUE, "[]") ?: "[]"
        return runCatching {
            val array = JSONArray(raw)
            MutableList(array.length()) { index ->
                val item = array.getJSONObject(index)
                QueueItem(
                    item.optString("gateway"),
                    item.optString("tid"),
                    item.optString("amount"),
                )
            }
        }.getOrElse {
            Log.w("RaddRelay", "unreadable queue, starting empty", it)
            mutableListOf()
        }
    }

    @Synchronized
    fun saveQueue(context: Context, queue: List<QueueItem>) {
        val array = JSONArray()
        for (item in queue) {
            array.put(
                JSONObject()
                    .put("gateway", item.gateway)
                    .put("tid", item.tid)
                    .put("amount", item.amount),
            )
        }
        prefs(context).edit().putString(KEY_QUEUE, array.toString()).apply()
    }

    @Synchronized
    fun isRelayed(context: Context, tid: String): Boolean =
        runCatching {
            val array = JSONArray(prefs(context).getString(KEY_RELAYED, "[]"))
            (0 until array.length()).any { array.optString(it) == tid }
        }.getOrDefault(false)

    @Synchronized
    fun markRelayed(context: Context, tid: String) {
        val array = runCatching {
            JSONArray(prefs(context).getString(KEY_RELAYED, "[]"))
        }.getOrElse { JSONArray() }
        val kept = JSONArray()
        kept.put(tid)
        var index = 0
        // Newest first, capped: the set only needs to cover a retry window,
        // not the lifetime of the phone.
        while (index < array.length() && kept.length() < RELAYED_CAP) {
            val value = array.optString(index)
            if (value.isNotEmpty() && value != tid) kept.put(value)
            index += 1
        }
        prefs(context).edit().putString(KEY_RELAYED, kept.toString()).apply()
    }
}

/** In-memory log shown by MainActivity; survives as long as the process. */
object RelayLog {

    private const val CAP = 300
    private val lines = ArrayDeque<String>()
    private val stamp = SimpleDateFormat("HH:mm:ss", Locale.US)

    @Synchronized
    fun add(message: String) {
        lines.addLast(stamp.format(Date()) + "  " + message)
        while (lines.size > CAP) lines.removeFirst()
    }

    @Synchronized
    fun snapshot(): List<String> = lines.toList()
}
