import java.io.File
import java.util.Base64
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.hilt)
    alias(libs.plugins.kotlin.kapt)
}

// ═════════════════════════════════════════════════════════════════════════════
//  BRAND — one file re-skins this app: <repo root>/brand.properties
// ═════════════════════════════════════════════════════════════════════════════
//  Read with java.util.Properties (no plugin, no dependency) and fanned out to:
//    • BuildConfig.BRAND_<KEY with '.' -> '_'>  (String, every key)
//    • resValue("color",  ...)  for every resources.colors.* key
//    • resValue("string", ...)  for the launcher label / wordmark strings
//    • manifestPlaceholders["brandScheme"] for the deep-link <data android:scheme>
//    • applicationId / namespace / versionName / versionCode / debug suffix
//    • build/generated/assets/brand/brand.json, merged into assets at build time
//      (Brand.kt reads that JSON at startup; it is generated, never hand-edited,
//       and lives under build/ so it can never be committed by accident)
//  The same file is read by Fast_Fetch/config.py with configparser. `[section]`
//  header lines load as empty-valued keys whose name starts with '[' — skipped.
val brandPropsFile = File(rootDir.parentFile, "brand.properties")
if (!brandPropsFile.exists()) {
    throw GradleException("brand.properties missing at $brandPropsFile — the app cannot be branded.")
}
val brandProps = Properties().apply { brandPropsFile.inputStream().use { load(it) } }
val brandKeys = brandProps.stringPropertyNames().filter { !it.startsWith("[") }.sorted()

fun brand(key: String, fallback: String): String =
    (brandProps.getProperty(key) ?: "").trim().ifEmpty { fallback }

fun brandInt(key: String, fallback: Int): Int = brand(key, "").toIntOrNull() ?: fallback

fun brandField(key: String): String = "BRAND_" + key.uppercase().replace('.', '_').replace('-', '_')

fun brandJsonEscape(value: String): String = buildString {
    for (ch in value) when (ch) {
        '\\' -> append("\\\\")
        '"' -> append("\\\"")
        '\n' -> append("\\n")
        '\r' -> append("\\r")
        '\t' -> append("\\t")
        else -> if (ch < ' ') append("\\u%04x".format(ch.code)) else append(ch)
    }
}

// Fail fast: a typo'd hex must break the build, not silently ship the old brand.
val brandHexPattern = Regex("^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
brandKeys.filter { it.startsWith("colors.") || it.startsWith("resources.colors.") }.forEach { key ->
    val hex = brand(key, "")
    if (!brandHexPattern.matches(hex)) {
        throw GradleException("brand.properties $key='$hex' is not #RRGGBB or #AARRGGBB")
    }
}

val brandAssetsDir = File(layout.buildDirectory.get().asFile, "generated/assets/brand")


// ── Version (brand.properties wins; CI env vars can still override) ──────────
val versionNameFromEnv = System.getenv("VERSION_NAME") ?: brand("identity.version.name", "0.1.0")
val versionCodeFromEnv = System.getenv("VERSION_CODE")?.toIntOrNull()
    ?: brandInt("identity.version.code", 1)

val brandApplicationId = brand("identity.application.id", "com.raddstream.app")
val brandDebugSuffix = brand("identity.application.id.debug.suffix", ".debug")

android {
    namespace   = brand("identity.namespace", brandApplicationId)
    compileSdk  = 35

    sourceSets {
        getByName("main") {
            // brand.json is generated into build/ by generateBrandAssets below.
            assets.srcDir(brandAssetsDir)
        }
    }

    signingConfigs {
        create("release") {
            val keystoreBase64 = System.getenv("KEYSTORE_BASE64") ?: ""
            val storePassword  = System.getenv("KEY_STORE_PASSWORD") ?: ""
            val keyAlias       = System.getenv("KEY_ALIAS") ?: ""
            val keyPassword    = System.getenv("KEY_PASSWORD") ?: ""

            if (keystoreBase64.isNotEmpty() && storePassword.isNotEmpty()) {
                val keystoreFile = File(layout.buildDirectory.asFile.get(), "radd-release.jks")
                keystoreFile.parentFile?.mkdirs()
                keystoreFile.writeBytes(Base64.getDecoder().decode(keystoreBase64))
                storeFile = keystoreFile
                this.storePassword = storePassword
                this.keyAlias = keyAlias
                this.keyPassword = keyPassword
            }
        }
    }

    defaultConfig {
        applicationId = brandApplicationId
        minSdk        = 21
        targetSdk     = 35
        versionCode   = versionCodeFromEnv
        versionName   = versionNameFromEnv

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true

        // Deep-link scheme, consumed by AndroidManifest.xml as ${brandScheme}.
        manifestPlaceholders["brandScheme"] = brand("deeplink.scheme", "radd")

        // Every brand key becomes BuildConfig.BRAND_<UPPER_SNAKE> (String).
        // Brand.kt exposes typed accessors; Color.kt / Type.kt read the hexes
        // and type scale from here, so no Kotlin file carries a brand literal.
        brandKeys.forEach { key ->
            buildConfigField("String", brandField(key), "\"${brandJsonEscape(brand(key, ""))}\"")
        }

        // XML-side colours (themes.xml, launcher layers, splash) reference
        // @color/<name>; res/values/colors.xml no longer declares them.
        brandKeys.filter { it.startsWith("resources.colors.") }.forEach { key ->
            resValue("color", key.removePrefix("resources.colors."), brand(key, "#000000"))
        }

        // XML-side strings. @string/brand_app_name is the manifest label, so the
        // launcher name comes from brand.properties, not res/values/strings.xml.
        resValue("string", "brand_app_name", brand("identity.name", "RADD Stream"))
        resValue("string", "brand_app_name_short", brand("identity.name.short", brand("identity.name", "RADD Stream")))
        resValue("string", "brand_wordmark_first", brand("identity.name.wordmark.first", "Radd"))
        resValue("string", "brand_wordmark_second", brand("identity.name.wordmark.second", "Stream"))
        resValue("string", "brand_tagline", brand("identity.tagline", ""))
    }

    buildTypes {
        debug {
            applicationIdSuffix = brandDebugSuffix
            isDebuggable        = true
            isMinifyEnabled     = false
        }
        release {
            isMinifyEnabled   = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            val keystoreBase64 = System.getenv("KEYSTORE_BASE64") ?: ""
            if (keystoreBase64.isNotEmpty()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose     = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

// ── brand.json: generated asset, single runtime source for Brand.kt ──────────
// Flat JSON object of every brand key. Regenerated on every build whenever
// brand.properties changes, and merged into the APK assets via the sourceSets
// entry above, so copy strings / TTLs / flags can be read at startup.
val generateBrandAssets = tasks.register("generateBrandAssets") {
    description = "Render brand.json into the merged assets from brand.properties"
    group = "branding"
    inputs.file(brandPropsFile)
    outputs.dir(brandAssetsDir)
    doLast {
        brandAssetsDir.mkdirs()
        val json = buildString {
            appendLine("{")
            appendLine("  \"_generated\": \"by :app:generateBrandAssets from /brand.properties — DO NOT HAND-EDIT\",")
            appendLine("  \"_brandFile\": \"${brandJsonEscape(brandPropsFile.absolutePath)}\",")
            brandKeys.forEachIndexed { index, key ->
                val terminator = if (index == brandKeys.lastIndex) "" else ","
                append("  \"")
                append(brandJsonEscape(key))
                append("\": \"")
                append(brandJsonEscape(brand(key, "")))
                appendLine("\"$terminator")
            }
            appendLine("}")
        }
        File(brandAssetsDir, "brand.json").writeText(json)
        logger.lifecycle("[brand] ${brand("identity.name", "?")} v${brand("identity.version.name", "?")} " +
            "appId=${brand("identity.application.id", "?")} scheme=${brand("deeplink.scheme", "radd")} " +
            "primary=${brand("colors.dark.primary", "?")} keys=${brandKeys.size}")
    }
}

tasks.named("preBuild") { dependsOn(generateBrandAssets) }

dependencies {
    // ── Compose BOM (all Compose versions in sync) ────────────────────────────
    val composeBom = platform(libs.compose.bom)
    implementation(composeBom)
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons.extended)
    implementation(libs.activity.compose)
    debugImplementation(libs.compose.ui.tooling)

    // ── Navigation ────────────────────────────────────────────────────────────
    implementation(libs.navigation.compose)

    // ── Media3 / ExoPlayer ────────────────────────────────────────────────────
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.exoplayer.hls)
    implementation(libs.media3.exoplayer.dash)
    implementation(libs.media3.ui)
    implementation(libs.media3.session)

    // ── Networking ────────────────────────────────────────────────────────────
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)

    // ── Hilt DI ───────────────────────────────────────────────────────────────
    implementation(libs.hilt.android)
    kapt(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)

    // ── Room ──────────────────────────────────────────────────────────────────
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    kapt(libs.room.compiler)

    // ── Image loading (Coil) ──────────────────────────────────────────────────
    implementation(libs.coil.compose)

    // ── Lifecycle + Coroutines ────────────────────────────────────────────────
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.coroutines.android)

    // ── DataStore (server URL preference) ────────────────────────────────────
    implementation(libs.datastore.preferences)

    // ── Core ──────────────────────────────────────────────────────────────────
    implementation(libs.core.ktx)

    // ── Tests ─────────────────────────────────────────────────────────────────
    testImplementation(libs.junit)
}
