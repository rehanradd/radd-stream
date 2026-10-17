import java.io.File
import java.util.Base64

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.hilt)
    alias(libs.plugins.kotlin.kapt)
}

// ── Version (overridable from CI env vars) ────────────────────────────────────
val versionNameFromEnv  = System.getenv("VERSION_NAME") ?: "0.1.0"
val versionCodeFromEnv  = System.getenv("VERSION_CODE")?.toIntOrNull() ?: 1

android {
    namespace   = "com.raddstream.app"
    compileSdk  = 35

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
        applicationId = "com.raddstream.app"
        minSdk        = 21
        targetSdk     = 35
        versionCode   = versionCodeFromEnv
        versionName   = versionNameFromEnv

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
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
