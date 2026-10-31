package com.raddstream.relay

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
import java.net.MalformedURLException
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
 * X-Merchant-Secret header and {"gateway", "tid", "amount"}. The route exists on
 * trunk (`viewer.py:_merchant_relay`, landed 0e5ae28) and answers on the loopback
 * ports only; the shipped default URL is therefore the SSH tunnel endpoint, and a
 * public-IP base URL is wrong until the host has TLS.
 */
class RelayService : Service() {

    private val executor = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val draining = AtomicBoolean(false)
    private var failures = 0
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private val drainRunnable = Runnable {
        runCatching { executor.execute { drain() } }
    }

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
                    is PostVerdict.Ok -> {
                        failures = 0
                        queue.removeAt(0)
                        RelayPrefs.saveQueue(this, queue)
                        RelayPrefs.markRelayed(this, item.tid)
                        RelayLog.add("relayed ${item.gateway} ${item.tid} · Rs ${item.amount}")
                    }
                    is PostVerdict.Reject -> {
                        // Reject means "retrying this exact request cannot help"
                        // (bad secret, malformed payload) — it does NOT mean the
                        // money did not arrive. The item leaves the active queue
                        // for the dead-letter list: still on the device, visible
                        // in the log, replayable after the operator fixes the
                        // cause. Deleting it would destroy the only record that a
                        // payment happened.
                        queue.removeAt(0)
                        RelayPrefs.saveQueue(this, queue)
                        RelayPrefs.addDeadLetter(this, item)
                        RelayLog.add(
                            "DEAD ${item.gateway} ${item.tid} · Rs ${item.amount} — " +
                                "${result.reason}; kept for replay",
                        )
                    }
                    is PostVerdict.Retry -> {
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

    private fun post(config: RelayPrefs.Config, item: QueueItem): PostVerdict {
        // Parsed before the transport try: MalformedURLException extends
        // IOException, and a typo'd URL must be a permanent configuration error,
        // not a retry that hides it.
        val url = try {
            URL(config.baseUrl.trimEnd('/') + WEBHOOK_PATH)
        } catch (e: MalformedURLException) {
            return PostVerdict.Reject("bad URL: ${e.message}")
        }
        var connection: HttpURLConnection? = null
        return try {
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 15_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                setRequestProperty("X-Merchant-Secret", config.secret)
                setRequestProperty("User-Agent", "RaddRelay/1.0")
            }
            connection = conn
            val payload = JSONObject()
                .put("gateway", item.gateway)
                .put("tid", item.tid)
                .put("amount", item.amount.toLongOrNull() ?: item.amount)
                .toString()
            conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }

            // The rule lives in PostVerdict so the JVM suite can table-test it;
            // 403 in particular is a proxy refusing the route, not a verdict on
            // the merchant secret.
            PostVerdict.of(conn.responseCode)
        } catch (io: IOException) {
            PostVerdict.Retry(io.message ?: "network error")
        } catch (e: Exception) {
            PostVerdict.Reject(e.message ?: e.javaClass.simpleName)
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

    companion object {
        const val ACTION_START = "com.raddstream.relay.START"
        const val ACTION_STOP = "com.raddstream.relay.STOP"
        private const val CHANNEL_ID = "relay"
        private const val NOTIFICATION_ID = 41
        const val WEBHOOK_PATH = "/api/v2/payment/sms-webhook"

        @Volatile
        var isRunning: Boolean = false
            private set

        /**
         * Called by the receiver, on the receiver's thread.
         *
         * The TID is written to the persistent queue BEFORE the service is
         * asked to run, because Android 12+ can refuse a background
         * foreground-service start from an SMS broadcast. If that happens the
         * payment is already safe and the next start — the operator opening the
         * app, or the service's own retry — sends it.
         *
         * Duplicates are dropped by TID: an already-relayed id, one already
         * waiting in the queue, or one already dead-lettered is logged and
         * ignored (a dead-lettered id is replayed from the app, not re-queued
         * by a redelivered SMS).
         */
        fun accept(context: Context, payment: SmsParser.Payment) {
            val tid = payment.tid
            if (RelayPrefs.isRelayed(context, tid)) {
                RelayLog.add("skip ${payment.gateway} $tid — already relayed")
                return
            }
            if (RelayPrefs.loadDeadLetter(context).any { it.tid == tid }) {
                RelayLog.add("skip ${payment.gateway} $tid — dead-lettered; replay after a fix")
                return
            }
            val queue = RelayPrefs.loadQueue(context)
            if (queue.any { it.tid == tid }) {
                RelayLog.add("skip ${payment.gateway} $tid — already queued")
                return
            }
            queue.add(QueueItem(payment.gateway, tid, payment.amount))
            RelayPrefs.saveQueue(context, queue)
            RelayLog.add("queued ${payment.gateway} $tid · Rs ${payment.amount}")
            try {
                context.startForegroundService(
                    Intent(context, RelayService::class.java).setAction(ACTION_START),
                )
            } catch (e: Exception) {
                RelayLog.add(
                    "service start refused (${e.javaClass.simpleName}) — " +
                        "$tid is queued and sends on the next start",
                )
            }
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
    private const val KEY_DEAD = "dead_letter"
    // The sanctioned transport is the operator phone's outbound SSH tunnel to the
    // server's loopback port. The public edge cannot reach the webhook by design
    // (nginx 403s /api/v2/payment), so a public-IP base URL is wrong until the
    // host has TLS.
    private const val DEFAULT_URL = "http://127.0.0.1:8099"
    private const val RELAYED_CAP = 500
    private const val DEAD_CAP = 100

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
    fun loadQueue(context: Context): MutableList<QueueItem> =
        readItems(prefs(context).getString(KEY_QUEUE, "[]"))

    @Synchronized
    fun saveQueue(context: Context, queue: List<QueueItem>) {
        prefs(context).edit().putString(KEY_QUEUE, writeItems(queue)).apply()
    }

    /**
     * Payments the server refused in a way retrying cannot fix (bad secret,
     * malformed payload). They are kept, not deleted: the server dedupes on
     * gateway+TID+amount, so replaying one can only help, while losing it
     * destroys the only record that money arrived.
     */
    @Synchronized
    fun loadDeadLetter(context: Context): MutableList<QueueItem> =
        readItems(prefs(context).getString(KEY_DEAD, "[]"))

    @Synchronized
    fun saveDeadLetter(context: Context, items: List<QueueItem>) {
        prefs(context).edit().putString(KEY_DEAD, writeItems(items)).apply()
    }

    @Synchronized
    fun addDeadLetter(context: Context, item: QueueItem) {
        val items = loadDeadLetter(context)
        if (items.none { it.tid == item.tid }) items.add(0, item)
        saveDeadLetter(context, items.take(DEAD_CAP))
    }

    /** Moves every dead-lettered payment back onto the active queue. */
    @Synchronized
    fun replayDeadLetter(context: Context): Int {
        val dead = loadDeadLetter(context)
        if (dead.isEmpty()) return 0
        val queue = loadQueue(context)
        var moved = 0
        for (item in dead.asReversed()) {
            if (isRelayed(context, item.tid)) continue
            if (queue.any { it.tid == item.tid }) continue
            queue.add(item)
            moved += 1
        }
        saveQueue(context, queue)
        saveDeadLetter(context, emptyList())
        return moved
    }

    private fun readItems(raw: String?): MutableList<QueueItem> = runCatching {
        val array = JSONArray(raw ?: "[]")
        MutableList(array.length()) { index ->
            val item = array.getJSONObject(index)
            QueueItem(
                item.optString("gateway"),
                item.optString("tid"),
                item.optString("amount"),
            )
        }
    }.getOrElse {
        Log.w("RaddRelay", "unreadable payment list, starting empty", it)
        mutableListOf()
    }

    private fun writeItems(items: List<QueueItem>): String {
        val array = JSONArray()
        for (item in items) {
            array.put(
                JSONObject()
                    .put("gateway", item.gateway)
                    .put("tid", item.tid)
                    .put("amount", item.amount),
            )
        }
        return array.toString()
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
