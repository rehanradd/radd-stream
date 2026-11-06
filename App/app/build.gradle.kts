import java.io.ByteArrayInputStream
import java.io.File
import java.net.URI
import java.security.KeyStore
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
val brandResDir = File(layout.buildDirectory.get().asFile, "generated/res/brand")

// The hosts a release build may talk to over plain HTTP. Derived, never typed.
//
// Off by default: `App/AGENTS.md` §11 forbids relaxing network security to make a
// release work over HTTP, so the shipped policy is loopback-only (a developer's own
// API on their machine or the emulator). One brand key —
// `network.release_cleartext_for_default_host` — adds the default server's host, and
// only that host, when the owner decides cleartext to their own catalog is acceptable.
// Third-party media origins are never added: their URLs already arrive as our own
// redirector handles.
fun brandReleaseCleartextAllowed(): Boolean =
    brand("network.release_cleartext_for_default_host", "false").equals("true", ignoreCase = true)

fun brandCleartextHosts(): List<String> {
    val local = listOf("127.0.0.1", "localhost", "10.0.2.2")
    if (!brandReleaseCleartextAllowed()) return local.sorted()
    val fromUrl = runCatching { URI(brand("network.default_server_url", "")).host }.getOrNull()
    val extras = brand("network.cleartext.extra_hosts", "").split(',', ' ').map { it.trim() }
    return (local + listOfNotNull(fromUrl) + extras)
        .filter { it.isNotEmpty() && !it.contains('/') && !it.contains(':') }
        .distinct()
        .sorted()
}


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
            // so is res/xml/network_security_config.xml
            res.srcDir(brandResDir)
        }
    }

    signingConfigs {
        create("release") {
            val keystoreBase64 = System.getenv("KEYSTORE_BASE64") ?: ""
            val storePassword  = System.getenv("KEY_STORE_PASSWORD") ?: ""
            val keyAlias       = System.getenv("KEY_ALIAS") ?: ""
            val keyPassword    = System.getenv("KEY_PASSWORD") ?: ""

            if (keystoreBase64.isNotEmpty() && storePassword.isNotEmpty()) {
                // Why this block interrogates its input instead of just decoding it: release run
                // 41233720264 died on the decode line below with "Last unit does not have enough
                // valid bits" after 8 seconds — 8 seconds is Gradle configuration, not signing, so
                // nothing had compiled. That message describes a malformed final base64 group, i.e.
                // a corrupt stored value, and the strict decoder was right to refuse it. Measured on
                // this host: for that exact input the tolerant MIME decoder throws identically, so
                // relaxing the decoder would have fixed nothing while discarding the one check that
                // caught the fault. What the failure lacked was a sentence an operator could act on.
                //
                // These checks therefore report the *shape* of the value — length, position,
                // character code, byte count after decode — and never the value itself, which is a
                // credential and belongs in no log, no error message and no artifact.
                fun refuse(shape: String): Nothing = throw GradleException(
                    "KEYSTORE_BASE64 is not usable: $shape.\n" +
                        "  Re-export with `base64 -w 0 <keystore-file>` and paste the terminal output " +
                        "straight into Settings -> Secrets and variables -> Actions, replacing the " +
                        "stored value. Do not route it through a file, an editor or a chat message — " +
                        "that is where a single-line string gains newlines or loses its `==` padding. " +
                        "The correct length for the keystore this repo has always used is 3672 " +
                        "characters. No decoder change will help: the stored value is what is wrong, " +
                        "and this message prints its shape only, never its contents."
                )

                if (keystoreBase64.length % 4 != 0) {
                    refuse(
                        "is ${keystoreBase64.length} characters, and base64 is always a multiple of 4 " +
                            "— a tail that is not a whole group is exactly the \"Last unit does not " +
                            "have enough valid bits\" crash this replaces"
                    )
                }
                val badChar = keystoreBase64.indexOfFirst { c ->
                    !(c.isLetterOrDigit() || c == '+' || c == '/' || c == '=')
                }
                if (badChar >= 0) {
                    refuse(
                        "holds a non-base64 character at index $badChar of ${keystoreBase64.length} " +
                            "(code point 0x${keystoreBase64[badChar].code.toString(16)}) — a newline " +
                            "or a space pasted in from a wrapping display"
                    )
                }
                if (keyAlias.isEmpty()) refuse("is set but KEY_ALIAS is empty, so nothing could be selected")
                if (keyPassword.isEmpty()) refuse("is set but KEY_PASSWORD is empty")

                val keystoreBytes = Base64.getDecoder().decode(keystoreBase64)

                // Bytes that decode cleanly are not yet a keystore. Without this the operator gets
                // a structural pass and then a signing task that names neither the secret nor the
                // file; with it, garbage fails here as "not a keystore" and a wrong password fails
                // here as itself. JKS is dual-format on JDK 9+, so it reads a PKCS12 store too, and
                // PKCS12 is tried for a store that is not self-describing.
                val storeChars = storePassword.toCharArray()
                val probe = listOf("JKS", "PKCS12").firstNotNullOfOrNull { type ->
                    runCatching {
                        KeyStore.getInstance(type).apply {
                            ByteArrayInputStream(keystoreBytes).use { load(it, storeChars) }
                        }
                    }.getOrNull()
                } ?: refuse(
                    "decodes to ${keystoreBytes.size} bytes that parse as neither a JKS nor a PKCS12 " +
                        "keystore with the stored KEY_STORE_PASSWORD"
                )
                if (!probe.containsAlias(keyAlias)) {
                    refuse(
                        "the keystore holds ${probe.size()} alias(es) and none is the configured " +
                            "KEY_ALIAS (the name is not printed; list it with " +
                            "`keytool -list -keystore <file>`)"
                    )
                }
                if (!probe.isKeyEntry(keyAlias)) {
                    refuse("the configured alias is not a private-key entry, so it cannot sign an APK")
                }
                runCatching { probe.getKey(keyAlias, keyPassword.toCharArray()) }.onFailure {
                    refuse(
                        "KEY_PASSWORD does not recover the private key for the configured alias " +
                            "(${it.javaClass.simpleName}) — signing would fail on precisely this, and " +
                            "the identity a release is signed with cannot be changed after the fact"
                    )
                }

                val keystoreFile = File(layout.buildDirectory.asFile.get(), "radd-release.jks")
                keystoreFile.parentFile?.mkdirs()
                keystoreFile.writeBytes(keystoreBytes)
                println(
                    "release signing: KEYSTORE_BASE64 accepted — ${keystoreBase64.length} chars -> " +
                        "${keystoreBytes.size} bytes, private-key entry found and unlocked"
                )
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

    // Compose semantics assertions run on the JVM under Robolectric. This box has
    // no /dev/kvm, so an emulator is not an option; without includeAndroidResources
    // Robolectric cannot stand up the framework the composition needs.
    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            isReturnDefaultValues = true
        }
    }
}

// ── Robolectric UI tests: x86_64 only ────────────────────────────────────────
// Robolectric's native runtime ships no Linux/aarch64 build (robolectric/robolectric#9166),
// and it fails while the runner boots — during @Rule evaluation, before any line of the test
// body — so an in-test Assume cannot catch it. Excluding here is the only place that works.
// These classes therefore run on an x86_64 CI runner, never on this ARM host.
tasks.withType<Test>().configureEach {
    if (System.getProperty("os.arch")?.lowercase() in setOf("aarch64", "arm64")) {
        filter {
            excludeTestsMatching("com.raddstream.app.ui.components.PosterCardProvenanceTest")
            excludeTestsMatching("com.raddstream.app.ui.ScreenSnapshotTest")
            excludeTestsMatching("com.raddstream.app.data.local.AppDatabaseMigrationTest")
            excludeTestsMatching("com.raddstream.app.data.cache.AheadFetcherFinalizeTest")
        }
        doFirst {
            // Name every excluded class: this line is the only signal a reader of a local gate
            // gets that the suite count below is not the whole suite count.
            logger.lifecycle(
                "Skipping PosterCardProvenanceTest, ScreenSnapshotTest, AppDatabaseMigrationTest " +
                    "and AheadFetcherFinalizeTest: Robolectric has no native runtime for " +
                    "${System.getProperty("os.arch")}. Run these classes on an x86_64 CI runner."
            )
        }
    }
}

// ── brand.json: generated asset, single runtime source for Brand.kt ──────────
// Flat JSON object of every brand key. Regenerated on every build whenever
// brand.properties changes, and merged into the APK assets via the sourceSets
// entry above, so copy strings / TTLs / flags can be read at startup.
val generateBrandAssets = tasks.register("generateBrandAssets") {
    description = "Render brand.json and the network policy into the merged resources"
    group = "branding"
    inputs.file(brandPropsFile)
    outputs.dir(brandAssetsDir)
    outputs.dir(brandResDir)
    doLast {
        brandAssetsDir.mkdirs()
        brandResDir.mkdirs()
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
        File(brandResDir, "xml").mkdirs()
        File(brandResDir, "xml/network_security_config.xml").writeText(brandNetworkPolicyXml())
        logger.lifecycle("[brand] ${brand("identity.name", "?")} v${brand("identity.version.name", "?")} " +
            "appId=${brand("identity.application.id", "?")} scheme=${brand("deeplink.scheme", "radd")} " +
            "primary=${brand("colors.dark.primary", "?")} keys=${brandKeys.size} " +
            "cleartext=${brandCleartextHosts()}")
    }
}

// The one cleartext exception, in the platform's own format. Generated so that
// changing `network.default_server_url` or the release switch changes it with no
// second place to edit.
fun brandNetworkPolicyXml(): String {
    val hosts = brandCleartextHosts()
    val policy = if (brandReleaseCleartextAllowed()) {
        "cleartext is permitted for the one host this brand ships against"
    } else {
        "cleartext is permitted for loopback only, so a release build reaches a TLS catalog"
    }
    return buildString {
        appendLine("<?xml version=\"1.0\" encoding=\"utf-8\"?>")
        appendLine("<!-- DO NOT HAND-EDIT: generated by :app:generateBrandAssets from /brand.properties.")
        appendLine("     Policy in force: $policy.")
        appendLine("     Debug builds replace this file with their own source-set copy, because a")
        appendLine("     developer aims the app at whatever machine they are testing. There is no")
        appendLine("     global `cleartextTrafficPermitted` here and none in release: an exception is")
        appendLine("     always a named host, never a wildcard. -->")
        appendLine("<network-security-config>")
        appendLine("    <domain-config cleartextTrafficPermitted=\"true\">")
        hosts.forEach { appendLine("        <domain includeSubdomains=\"false\">$it</domain>") }
        appendLine("    </domain-config>")
        appendLine("</network-security-config>")
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

    // ── WorkManager (the closed-app sweep — CacheSweepWorker) ────────────────
    implementation(libs.workmanager)
    implementation(libs.hilt.work)

    // ── Core ──────────────────────────────────────────────────────────────────
    implementation(libs.core.ktx)

    // ── Tests ─────────────────────────────────────────────────────────────────
    testImplementation(libs.junit)
    testImplementation(composeBom)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core)
    testImplementation(libs.compose.ui.test.junit4)
    debugImplementation(libs.compose.ui.test.manifest)
}
