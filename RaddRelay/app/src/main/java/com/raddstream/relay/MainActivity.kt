package com.raddstream.relay

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.net.HttpURLConnection
import java.net.URL

/**
 * The operator's one screen: status, server settings, start/stop, a webhook
 * probe, dead-letter replay, and the live relay log.
 *
 * Deliberately plain framework views — no AndroidX, no Compose — because this
 * app exists to be small, cheap on a low-end phone, and easy to audit.
 */
class MainActivity : Activity() {

    private lateinit var statusView: TextView
    private lateinit var logView: TextView
    private lateinit var urlInput: EditText
    private lateinit var secretInput: EditText
    private val handler = Handler(Looper.getMainLooper())

    private val refresh = object : Runnable {
        override fun run() {
            renderStatus()
            logView.text = RelayLog.snapshot().joinToString("\n")
            handler.postDelayed(this, 1_000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        val config = RelayPrefs.config(this)
        urlInput.setText(config.baseUrl)
        secretInput.setText(config.secret)
    }

    override fun onResume() {
        super.onResume()
        handler.removeCallbacks(refresh)
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    // -------------------------------------------------------------------- UI

    private fun buildUi(): ScrollView {
        val root = ScrollView(this)
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(24))
        }
        root.addView(column)

        column.addView(TextView(this).apply {
            text = "RaddRelay"
            textSize = 26f
            setTypeface(typeface, Typeface.BOLD)
        })

        statusView = TextView(this).apply {
            textSize = 14f
            setPadding(0, dp(6), 0, dp(14))
        }
        column.addView(statusView)

        column.addView(label("Server URL"))
        urlInput = EditText(this).apply {
            inputType = InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
            hint = "http://127.0.0.1:8099"
        }
        column.addView(urlInput)
        column.addView(TextView(this).apply {
            text = "Use the SSH tunnel endpoint (127.0.0.1:8099). A public IP is " +
                "wrong until the host has TLS — the edge refuses this route by design."
            textSize = 11f
            setPadding(0, dp(2), 0, 0)
        })

        column.addView(label("Merchant secret (X-Merchant-Secret)"))
        secretInput = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setSingleLine()
            hint = "shared with the server operator"
        }
        column.addView(secretInput)

        column.addView(buttonRow(
            button("Save") { saveConfig() },
            button("Send test") { testConnection() },
        ))

        column.addView(buttonRow(
            button("Start relay") { startRelay() },
            button("Stop relay") { stopRelay() },
        ))

        column.addView(buttonRow(
            button("Replay dead letter") { replayDeadLetter() },
        ))

        column.addView(label("Relay log"))
        logView = TextView(this).apply {
            textSize = 11f
            typeface = Typeface.MONOSPACE
            setTextIsSelectable(true)
            setPadding(dp(8), dp(8), dp(8), dp(8))
        }
        column.addView(logView, LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT,
        ))

        column.addView(TextView(this).apply {
            text = "Only SMS from 8558 (JazzCash) and 3737 (EasyPaisa) are read. " +
                "The message text never leaves the phone — only gateway, TID and amount."
            textSize = 11f
            setPadding(0, dp(18), 0, 0)
        })
        return root
    }

    private fun label(text: String) = TextView(this).apply {
        this.text = text
        textSize = 13f
        setPadding(0, dp(12), 0, dp(4))
    }

    private fun button(text: String, onClick: () -> Unit) = Button(this).apply {
        this.text = text
        setOnClickListener { onClick() }
    }

    private fun buttonRow(vararg views: Button): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(8), 0, 0)
        }
        for (view in views) {
            row.addView(view, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        return row
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    // --------------------------------------------------------------- actions

    private fun saveConfig() {
        RelayPrefs.setConfig(this, urlInput.text.toString(), secretInput.text.toString())
        val config = RelayPrefs.config(this)
        RelayLog.add(
            if (config.secret.isBlank()) "configuration saved — secret is EMPTY, relaying is blocked"
            else "configuration saved — ${config.baseUrl}",
        )
    }

    private fun startRelay() {
        saveConfig()
        val missing = buildList {
            if (checkSelfPermission(Manifest.permission.RECEIVE_SMS)
                != PackageManager.PERMISSION_GRANTED) add(Manifest.permission.RECEIVE_SMS)
            if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (missing.isNotEmpty()) {
            requestPermissions(missing.toTypedArray(), REQUEST_PERMISSIONS)
            return
        }
        RelayPrefs.setEnabled(this, true)
        startForegroundService(
            Intent(this, RelayService::class.java).setAction(RelayService.ACTION_START),
        )
        RelayLog.add("relay started")
    }

    private fun stopRelay() {
        RelayPrefs.setEnabled(this, false)
        stopService(Intent(this, RelayService::class.java))
        RelayLog.add("relay stopped")
    }

    /**
     * Probes the real webhook with a deliberately invalid body.
     *
     * The server verifies X-Merchant-Secret before it reads a byte of the body,
     * so the answer separates the causes the app can actually observe:
     * 401 = the secret, 403 = a proxy refused the route (i.e. the URL is the
     * public edge, not the tunnel), 404 = the route is not deployed on whatever
     * answered, and any 4xx from the handler itself means the route was reached
     * and the secret accepted. An unparseable payload cannot become a payment,
     * and the probe never touches the queue.
     */
    private fun testConnection() {
        val config = RelayPrefs.config(this)
        if (config.baseUrl.isBlank()) {
            RelayLog.add("test: no server URL configured")
            return
        }
        Thread {
            var connection: HttpURLConnection? = null
            try {
                val url = URL(config.baseUrl.trimEnd('/') + RelayService.WEBHOOK_PATH)
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 8_000
                    readTimeout = 8_000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("X-Merchant-Secret", config.secret)
                    setRequestProperty("User-Agent", "RaddRelay/1.0")
                }
                connection = conn
                conn.outputStream.use { it.write("{}".toByteArray(Charsets.UTF_8)) }
                val code = conn.responseCode
                val note = when (code) {
                    401 -> "the merchant secret was rejected"
                    403 -> "a proxy refused the route — this URL is not the tunnel endpoint"
                    404 -> "route not deployed on whatever answered"
                    in 200..299 -> "the endpoint accepted the probe — check the ledger"
                    in 400..499 -> "route reached, secret accepted; the probe body was refused"
                    else -> "unexpected answer from ${url.host}"
                }
                RelayLog.add("test: HTTP $code — $note")
            } catch (e: Exception) {
                RelayLog.add("test failed: ${e.message ?: e.javaClass.simpleName}")
            } finally {
                connection?.disconnect()
            }
        }.start()
    }

    private fun replayDeadLetter() {
        val moved = RelayPrefs.replayDeadLetter(this)
        if (moved == 0) {
            RelayLog.add("replay: no dead-lettered payments to move")
            return
        }
        RelayLog.add("replay: $moved payment(s) back on the queue")
        runCatching {
            startForegroundService(
                Intent(this, RelayService::class.java).setAction(RelayService.ACTION_START),
            )
        }.onFailure {
            RelayLog.add("replay: service start refused (${it.javaClass.simpleName})")
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQUEST_PERMISSIONS) return
        if (checkSelfPermission(Manifest.permission.RECEIVE_SMS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            startRelay()
        } else {
            RelayLog.add("SMS permission denied — the relay cannot see payments")
        }
    }

    // ----------------------------------------------------------------- state

    private fun renderStatus() {
        val config = RelayPrefs.config(this)
        val queued = RelayPrefs.loadQueue(this).size
        val dead = RelayPrefs.loadDeadLetter(this).size
        val state = if (RelayService.isRunning) "running" else "stopped"
        val secret = if (config.secret.isBlank()) "not set" else "set"
        statusView.text =
            "Service: $state · queued: $queued · dead: $dead · secret: $secret\n" +
                "Server: ${config.baseUrl.ifBlank { "(not set)" }}"
    }

    companion object {
        private const val REQUEST_PERMISSIONS = 41
    }
}
