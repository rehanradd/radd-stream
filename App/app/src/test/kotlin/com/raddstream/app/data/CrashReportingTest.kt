package com.raddstream.app.data

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.google.firebase.FirebaseApp
import com.google.firebase.crashlytics.FirebaseCrashlytics
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * Crashlytics wiring, on the JVM under Robolectric (x86_64-only like every
 * Robolectric suite — see the arm64 exclusion in `app/build.gradle.kts`).
 *
 * What this pins: calling [CrashReporting.install] — the exact call
 * `RaddStreamApplication.onCreate` makes before `Telemetry.installCrashHandler`
 * — never throws, initialises Firebase from the committed
 * `google-services.json`, and leaves a default uncaught-exception handler
 * installed. It does NOT send a crash anywhere: there is no fake crash in
 * the UI and none here — a thrown test exception would kill the test JVM.
 *
 * The Firebase config the test reads is the generated `values.xml` the
 * google-services plugin renders from `App/app/google-services.json` into
 * the debug variant's resources (`isIncludeAndroidResources` is on in
 * `app/build.gradle.kts`); if that file is ever removed, `install` still
 * does not throw — but the FirebaseApp assertion below fails, which is the
 * loud signal that the config is missing.
 */
@RunWith(RobolectricTestRunner::class)
class CrashReportingTest {

    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test
    fun `install does not throw and leaves Firebase initialised`() {
        CrashReporting.install(context)

        assertTrue(
            "FirebaseApp was not initialised — google-services.json is missing or unprocessed",
            FirebaseApp.getApps(context).isNotEmpty(),
        )
        assertNotNull(FirebaseCrashlytics.getInstance())
    }

    @Test
    fun `install is idempotent`() {
        CrashReporting.install(context)
        CrashReporting.install(context)

        assertTrue(FirebaseApp.getApps(context).isNotEmpty())
        assertNotNull(FirebaseCrashlytics.getInstance())
    }

    @Test
    fun `install then Telemetry handler leaves a default handler installed`() {
        CrashReporting.install(context)
        Telemetry.installCrashHandler()

        assertNotNull(
            "no default uncaught-exception handler after the launch sequence",
            Thread.getDefaultUncaughtExceptionHandler(),
        )
    }
}
