package com.raddstream.app.data

import android.app.ActivityManager
import android.content.Context
import com.raddstream.app.brand.Brand
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.flow.first

/**
 * The process-wide holder for the aggregates-only telemetry Tracking A sends.
 *
 * Why an object and not an injected repository: the counters are touched from
 * places Hilt cannot reach — [PlaybackService] is a plain `MediaSessionService`,
 * the crash handler runs before any injection exists, and the OkHttp interceptor
 * is a lambda built once per client. One volatile snapshot, read everywhere,
 * written in exactly one place ([refresh], plus [init] for the device class).
 *
 * What it holds is deliberately small: a consent bit, a random install id, the
 * region card, the two language choices, and a coarse device class. No name,
 * no number, no location, no title, no query — the server's `usage_stats`
 * module refuses anything else by shape, and this holder has nothing else to
 * give it. Until the viewer answers the first-run dialog, [consentAccepted]
 * is false and nothing new leaves the phone: no install header, no usage
 * block, and no counter is even recorded, so a later "yes" never flushes
 * counts from before the answer.
 */
object Telemetry {

    /** The usage-block field names the server accepts (`usage_stats.CLIENT_FIELDS`). */
    val USAGE_FIELDS: Set<String> = setOf(
        "ad_requests", "ads_filled", "ad_impressions", "ad_clicks",
        "rewarded_completions", "coins_granted", "playback_attempts",
        "playback_buffer_failures", "playback_errors", "crashes", "errors",
    )

    @Volatile
    var consentAccepted: Boolean = false
        private set

    @Volatile
    var installId: String? = null
        private set

    @Volatile
    var region: String? = null
        private set

    @Volatile
    var audioLanguage: String? = null
        private set

    @Volatile
    var subtitleLanguage: String? = null
        private set

    @Volatile
    var deviceClass: String = "unknown"
        private set

    /** The app version the server reads as `app_version`. Same string as the User-Agent. */
    val appVersion: String get() = Brand.versionName

    /** The viewer's stated locale tag (`en-PK`): the server reads only its region subtag. */
    val acceptLanguage: String get() = Locale.getDefault().toLanguageTag()

    private var counters: UsageCounters? = null

    /**
     * Build the counter store and the device class. Safe to call twice: the
     * store is created once, and RAM does not change under a running process.
     * Does not touch consent — [refresh] owns that, once DataStore has loaded.
     */
    fun init(context: Context) {
        if (counters == null) {
            counters = UsageCounters(
                SharedPreferencesUsageCounterStore(context),
                gate = { consentAccepted },
            )
        }
        if (deviceClass == "unknown") {
            deviceClass = deviceClassFor(totalMemoryBytes(context))
        }
    }

    /**
     * Read the viewer's answers from DataStore into the snapshot. Runs on
     * launch and again right after the consent dialog or the Settings switch
     * is answered, so a changed answer takes effect without a restart.
     *
     * The install id is minted only for a viewer who said yes: a declined or
     * unanswered consent leaves [installId] null, and the interceptor then
     * sends no install header — the server falls back to the credential
     * digest, exactly as it did before this build existed.
     */
    suspend fun refresh(settings: ServerSettingsRepository) {
        val consent = settings.analyticsConsent.first()
        consentAccepted = consent == true
        if (consentAccepted) {
            installId = settings.ensureInstallUuid()
            region = settings.userRegion.first()
            audioLanguage = settings.preferredAudioLanguage.first()
            subtitleLanguage = settings.preferredSubtitleLanguage.first()
        } else {
            installId = null
            region = null
            audioLanguage = null
            subtitleLanguage = null
        }
    }

    /**
     * Count one crash and hand the process to whoever was going to kill it.
     * Installed in `RaddStreamApplication.onCreate`, before anything else can
     * crash. The write is a synchronous SharedPreferences commit wrapped in
     * `runCatching`, because the process is dying and a suspending DataStore
     * write would never land; if there was no previous handler, the process
     * is killed outright rather than left running in a broken state.
     */
    fun installCrashHandler() {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        // TEMP-DIAG 4 (revert before merge): the test executor dies with
        // exit 1 and no test output (runs 471/473/474/475/476). This handler
        // is the only place that can swallow an uncaught exception silently
        // (it records a counter and, with no previous handler, kills the
        // process — a no-op under Robolectric's ShadowProcess). Print the
        // exception and the chain state so the next CI run shows WHAT
        // throws, if anything, and whether Crashlytics' handler is chained.
        System.err.println("TEMP-DIAG 4: installCrashHandler previous=$previous")
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            System.err.println("TEMP-DIAG 4: uncaught on ${thread.name}: $error")
            error.printStackTrace()
            runCatching { counters?.record("crashes") }
            if (previous != null) {
                previous.uncaughtException(thread, error)
            } else {
                android.os.Process.killProcess(android.os.Process.myPid())
            }
        }
    }

    fun recordPlaybackAttempt() = counters?.record("playback_attempts")

    fun recordPlaybackBufferFailure() = counters?.record("playback_buffer_failures")

    fun recordPlaybackError() = counters?.record("playback_errors")

    fun recordRewardedCompletion() = counters?.record("rewarded_completions")

    fun recordCoinsGranted(coins: Int) = counters?.record("coins_granted", coins)

    /** The non-zero counts to ride the next progress report, if any. */
    fun takeUsageSnapshot(): Map<String, Int> = counters?.snapshot() ?: emptyMap()

    /** Forget exactly the counts a progress report carried, once it landed. */
    fun acknowledgeUsage(sent: Map<String, Int>) = counters?.acknowledge(sent)

    private fun totalMemoryBytes(context: Context): Long {
        val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
            ?: return 0L
        val info = ActivityManager.MemoryInfo()
        return runCatching { manager.getMemoryInfo(info); info.totalMem }.getOrDefault(0L)
    }
}

/**
 * The coarse device class the server splits crashes, errors and buffer
 * failures by. RAM only, on purpose: a model string is a fingerprint and
 * `usage_stats` refuses to store one, so the phone sends a bucket instead.
 * Thresholds are the usual low-end lines — under 3 GiB is a budget phone,
 * under 6 GiB is mid-range, the rest is high — and 0 (unreadable) reads as
 * low rather than inventing a class.
 */
fun deviceClassFor(totalMemBytes: Long): String = when {
    totalMemBytes < 3L * 1024L * 1024L * 1024L -> "low"
    totalMemBytes < 6L * 1024L * 1024L * 1024L -> "mid"
    else -> "high"
}

/** One random id per install, minted once and never derived from the phone. */
fun newInstallUuid(): String = UUID.randomUUID().toString()
