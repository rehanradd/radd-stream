package com.raddstream.app.brand

import android.content.Context
import com.raddstream.app.BuildConfig

/**
 * Brand — the thin typed view over the ONE brand file, `/brand.properties`.
 *
 * There are two paths into the same data, and neither duplicates the file:
 *
 *  1. **Build time** — `app/build.gradle.kts` reads brand.properties and emits
 *     `BuildConfig.BRAND_<KEY>` constants (every key), `resValue` colours and
 *     strings, the `${brandScheme}` manifest placeholder and applicationId /
 *     version. Those compile into this object, so the brand is already correct
 *     before a single byte of assets is read.
 *  2. **Start up** — `:app:generateBrandAssets` renders the same keys into
 *     `brand.json`, which Gradle merges into the APK assets from
 *     `build/generated/assets/brand/` (never committed, never hand-edited).
 *     Calling [load] once from `RaddStreamApplication.onCreate()` swaps in the
 *     runtime snapshot so copy strings, feature flags, TTLs and storage limits
 *     can be re-read without recompiling Kotlin.
 *
 * Every getter therefore prefers the loaded snapshot and falls back to the
 * compiled constant, so a screen that renders before `load()` still shows the
 * right brand instead of a blank string.
 *
 * Parsing is a hand-rolled flat-object reader, not `org.json`, so this class is
 * usable from plain JVM unit tests without Robolectric. The generated file is
 * always `{ "key": "string", ... }`; anything else is rejected and ignored.
 */
object Brand {

    // ── Runtime snapshot (populated by load(); empty until then) ─────────────
    @Volatile
    private var runtime: Map<String, String> = emptyMap()

    /** True once brand.json has been read successfully. */
    @Volatile
    var isLoaded: Boolean = false
        private set

    /** Asset name produced by :app:generateBrandAssets. */
    const val ASSET_NAME = "brand.json"

    /** Read `assets/brand.json`. Safe to call more than once; never throws. */
    fun load(context: Context) {
        val json = try {
            context.applicationContext.assets.open(ASSET_NAME)
                .bufferedReader()
                .use { it.readText() }
        } catch (_: Exception) {
            null
        } ?: return
        val parsed = parseFlatJson(json) ?: return
        runtime = parsed
        isLoaded = true
    }

    /** Inject a snapshot directly (used by tests and by dev-only re-branding). */
    fun useSnapshot(snapshot: Map<String, String>) {
        runtime = snapshot
        isLoaded = snapshot.isNotEmpty()
    }

    // ── Generic access ───────────────────────────────────────────────────────
    /** Raw value for a brand key, `""` when the key does not exist. */
    fun string(key: String): String = runtime[key]?.takeIf { it.isNotBlank() } ?: ""

    fun int(key: String, fallback: Int): Int = string(key).toIntOrNull() ?: fallback

    fun long(key: String, fallback: Long): Long = string(key).toLongOrNull() ?: fallback

    fun bool(key: String, fallback: Boolean): Boolean = when (string(key).lowercase()) {
        "true", "1", "yes", "on" -> true
        "false", "0", "no", "off" -> false
        else -> fallback
    }

    /** Every loaded key starting with [prefix], with the prefix removed. */
    fun keysUnder(prefix: String): Map<String, String> {
        val cut = if (prefix.endsWith(".")) prefix else "$prefix."
        return runtime.filterKeys { it.startsWith(cut) }.mapKeys { it.key.removePrefix(cut) }
    }

    // ── Identity ─────────────────────────────────────────────────────────────
    val name: String get() = string("identity.name").ifBlank { BuildConfig.BRAND_IDENTITY_NAME }
    val shortName: String get() =
        string("identity.name.short").ifBlank { BuildConfig.BRAND_IDENTITY_NAME_SHORT }
    val wordmarkFirst: String get() =
        string("identity.name.wordmark.first").ifBlank { BuildConfig.BRAND_IDENTITY_NAME_WORDMARK_FIRST }
    val wordmarkSecond: String get() =
        string("identity.name.wordmark.second").ifBlank { BuildConfig.BRAND_IDENTITY_NAME_WORDMARK_SECOND }
    val tagline: String get() = string("identity.tagline").ifBlank { BuildConfig.BRAND_IDENTITY_TAGLINE }
    val versionName: String get() = BuildConfig.VERSION_NAME
    val versionCode: Int get() = BuildConfig.VERSION_CODE
    val applicationId: String get() = BuildConfig.APPLICATION_ID

    // ── Copy strings ─────────────────────────────────────────────────────────
    /**
     * A `[copy]` string, formatted against `{placeholder}` tokens. Falls back to
     * the compiled constant when no snapshot is loaded yet, and to [fallback]
     * when the key exists in neither place, so a missing key can never crash UI.
     */
    fun copy(key: String, fallback: String = "", vararg args: Pair<String, String>): String {
        val raw = string("copy.$key")
            .ifBlank { compiledCopy(key) }
            .ifBlank { fallback }
        return args.fold(raw) { text, (token, value) -> text.replace("{$token}", value) }
    }

    private fun compiledCopy(key: String): String = when (key) {
        "brand_lockup_subtitle" -> BuildConfig.BRAND_COPY_BRAND_LOCKUP_SUBTITLE
        "home_title" -> BuildConfig.BRAND_COPY_HOME_TITLE
        "settings_about_heading" -> BuildConfig.BRAND_COPY_SETTINGS_ABOUT_HEADING
        "settings_about_body" -> BuildConfig.BRAND_COPY_SETTINGS_ABOUT_BODY
        "share_template" -> BuildConfig.BRAND_COPY_SHARE_TEMPLATE
        "offline_notice" -> BuildConfig.BRAND_COPY_OFFLINE_NOTICE
        "cache_locked_notice" -> BuildConfig.BRAND_COPY_CACHE_LOCKED_NOTICE
        "setup_heading" -> BuildConfig.BRAND_COPY_SETUP_HEADING
        "disclaimer_line" -> BuildConfig.BRAND_COPY_DISCLAIMER_LINE
        else -> ""
    }

    // ── Deep links + network identity ────────────────────────────────────────
    val deepLinkScheme: String get() = string("deeplink.scheme").ifBlank { BuildConfig.BRAND_DEEPLINK_SCHEME }

    /**
     * The catalog server a fresh install talks to, so "install and go" works. Empty means
     * "ship no server": the app then opens on Setup exactly as it did before this key
     * existed. Whatever is here is only a starting point — the person can point it at any
     * catalog they are authorized to use, and that choice is what gets persisted.
     */
    val defaultServerUrl: String
        get() = string("network.default_server_url")
            .ifBlank { BuildConfig.BRAND_NETWORK_DEFAULT_SERVER_URL }.trim()

    val userAgent: String get() =
        "${string("network.user_agent.product").ifBlank { BuildConfig.BRAND_NETWORK_USER_AGENT_PRODUCT }}" +
            "/${versionName} (${string("network.user_agent.version_suffix")
                .ifBlank { BuildConfig.BRAND_NETWORK_USER_AGENT_VERSION_SUFFIX }})"

    // ── Colours (hex strings; ui/theme/Color.kt turns them into Compose Colours) ──
    fun colorHex(dark: Boolean, role: String): String =
        string("colors.${if (dark) "dark" else "light"}.$role")
            .ifBlank { BuildConfig.BRAND_COLORS_DARK_PRIMARY }

    // ── Scheme behaviour + typography (brand [scheme] / [typography]) ────────
    val schemeDefaultDark: Boolean get() =
        bool("scheme.default_dark", BuildConfig.BRAND_SCHEME_DEFAULT_DARK.toBoolean())
    val schemeDynamicColorDefault: Boolean get() =
        bool("scheme.dynamic_color_default", BuildConfig.BRAND_SCHEME_DYNAMIC_COLOR_DEFAULT.toBoolean())
    val schemeName: String get() = string("scheme.name").ifBlank { BuildConfig.BRAND_SCHEME_NAME }

    /** Global text multiplier — brand.properties can grow type for small phones. */
    val typeScale: Float get() =
        string("typography.scale").toFloatOrNull()
            ?: BuildConfig.BRAND_TYPOGRAPHY_SCALE.toFloatOrNull() ?: 1f

    /** Font role names from `[typography]` — resolved to families by Type.kt. */
    val typeDisplayFamily: String get() =
        string("typography.display_family").ifBlank { BuildConfig.BRAND_TYPOGRAPHY_DISPLAY_FAMILY }
    val typeTextFamily: String get() =
        string("typography.text_family").ifBlank { BuildConfig.BRAND_TYPOGRAPHY_TEXT_FAMILY }

    /** A `[deeplink]`-shaped URI, e.g. deepLinkUri("detail/42") -> "radd://detail/42". */
    fun deepLinkUri(path: String): String = "$deepLinkScheme://${path.trimStart('/')}"

    // ── Feature flags ────────────────────────────────────────────────────────
    val offlineCacheEnabled: Boolean get() =
        bool("features.offline_cache", BuildConfig.BRAND_FEATURES_OFFLINE_CACHE.toBoolean())
    val lightSchemeSupported: Boolean get() =
        bool("features.light_scheme", BuildConfig.BRAND_FEATURES_LIGHT_SCHEME.toBoolean())
    val dynamicColorAllowed: Boolean get() =
        bool("features.dynamic_color", BuildConfig.BRAND_FEATURES_DYNAMIC_COLOR.toBoolean())
    val pipEnabled: Boolean get() = bool("features.pip", BuildConfig.BRAND_FEATURES_PIP.toBoolean())

    /**
     * Adult filtering is a project policy, not a brand knob: it can only ever be
     * ON. A `false` in brand.properties is ignored on purpose.
     */
    val adultFilterEnforced: Boolean get() = true

    // ── TTLs + storage limits ────────────────────────────────────────────────
    val catalogTtlSeconds: Long get() =
        long("cache.ttl.catalog_seconds", BuildConfig.BRAND_CACHE_TTL_CATALOG_SECONDS.toLongOrNull() ?: 3600L)
    val streamUrlTtlSeconds: Long get() = long("cache.ttl.stream_url_seconds", 1800L)
    val tempLinkGraceMinutes: Long get() = long("cache.ttl.temp_link_grace_minutes", 20L)
    val artworkTtlDays: Long get() = long("cache.ttl.artwork_days", 7L)
    val searchDebounceMillis: Int get() = int("cache.ttl.search_debounce_ms", 300)
    val offlineMaxBytes: Long get() = long("storage.offline_max_bytes", 16L * 1024 * 1024 * 1024)
    val perFileMaxBytes: Long get() = long("storage.per_file_max_bytes", 10L * 1024 * 1024 * 1024)
    val lowSpaceWarningBytes: Long get() = long("storage.low_space_warning_bytes", 1L * 1024 * 1024 * 1024)
    val aheadFetchMaxBytesPerPass: Long get() =
        long("storage.ahead_fetch_max_bytes_per_pass", 256L * 1024 * 1024)

    // ── Minimal flat-JSON reader ─────────────────────────────────────────────
    /**
     * Parses `{ "k": "v", ... }` where every value is a JSON string (exactly
     * what generateBrandAssets writes). Returns null when the shape is not that,
     * so a changed generator fails closed instead of half-branding the app.
     */
    fun parseFlatJson(text: String): Map<String, String>? {
        var i = 0
        val out = LinkedHashMap<String, String>()

        fun skipWs() { while (i < text.length && text[i].isWhitespace()) i++ }
        fun readString(): String? {
            if (i >= text.length || text[i] != '"') return null
            i++
            val sb = StringBuilder()
            while (i < text.length) {
                val ch = text[i]
                if (ch == '"') {
                    i++
                    return sb.toString()
                }
                if (ch == '\\') {
                    i++
                    if (i >= text.length) return null
                    when (val esc = text[i]) {
                        'n' -> { sb.append('\n'); i++ }
                        'r' -> { sb.append('\r'); i++ }
                        't' -> { sb.append('\t'); i++ }
                        '"' -> { sb.append('"'); i++ }
                        '\\' -> { sb.append('\\'); i++ }
                        '/' -> { sb.append('/'); i++ }
                        'u' -> {
                            if (i + 5 > text.length) return null
                            val code = text.substring(i + 1, i + 5).toIntOrNull(16) ?: return null
                            sb.append(code.toChar())
                            i += 5
                        }
                        else -> return null
                    }
                    continue
                }
                sb.append(ch)
                i++
            }
            return null
        }

        skipWs()
        if (i >= text.length || text[i] != '{') return null
        i++
        skipWs()
        if (i < text.length && text[i] == '}') return out
        while (i < text.length) {
            skipWs()
            val key = readString() ?: return null
            skipWs()
            if (i >= text.length || text[i] != ':') return null
            i++
            skipWs()
            val value = readString() ?: return null
            if (!key.startsWith("_")) out[key] = value
            skipWs()
            val separator = if (i < text.length) text[i] else return null
            when (separator) {
                ',' -> i++
                '}' -> return out
                else -> return null
            }
        }
        return null
    }
}
