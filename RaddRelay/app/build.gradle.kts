plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Deliberately dependency-free on the runtime side: no AndroidX, no Compose, no
// HTTP client. The whole app is four Kotlin files, the framework, and JUnit for
// the parser test, which is what keeps the APK in the "well under 1 MB" range.
android {
    namespace = "com.raddstream.relay"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.raddstream.relay"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
