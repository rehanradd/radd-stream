package com.raddstream.app.data

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/**
 * The crash-handler guard for the spurious Firebase Sessions `NullPointerException`
 * under Robolectric (runs 471/473/474/475/476: the Gradle test executor died
 * with exit 1 and no test XMLs).
 *
 * What the guard pins: a `SessionLifecycleClient` crash on a Firebase background
 * thread is counted in the local aggregates but never delegated to the previous
 * handler — under Robolectric that chain ends at Crashlytics, which records the
 * report and kills the process, and a spurious test-environment crash must not
 * kill the test worker. A real crash still delegates. The guard is Robolectric-only
 * by construction (`Class.forName` on `RuntimeEnvironment`), so on a real phone
 * every crash reaches Crashlytics exactly as before.
 */
@RunWith(RobolectricTestRunner::class)
class TelemetryCrashHandlerTest {

    private val originalHandler = Thread.getDefaultUncaughtExceptionHandler()

    @After
    fun restoreHandler() {
        Thread.setDefaultUncaughtExceptionHandler(originalHandler)
    }

    @Test
    fun `firebase sessions noise under robolectric is counted but not delegated`() {
        val delegated = mutableListOf<Throwable>()
        Thread.setDefaultUncaughtExceptionHandler { _, error -> delegated.add(error) }
        Telemetry.installCrashHandler()

        val noise = NullPointerException(
            "Cannot invoke \"android.os.IMessenger.send(android.os.Message)\" " +
                "because \"this.mTarget\" is null",
        )
        noise.stackTrace = arrayOf(
            StackTraceElement(
                "com.google.firebase.sessions.SessionLifecycleClient",
                "sendMessageToServer",
                "SessionLifecycleClient.kt",
                175,
            ),
        )
        val firebaseThread = Thread("Firebase Background Thread #2")
        val handler = requireNotNull(Thread.getDefaultUncaughtExceptionHandler())
        handler.uncaughtException(firebaseThread, noise)

        assertTrue("sessions noise reached the fatal chain", delegated.isEmpty())
    }

    @Test
    fun `a real crash still delegates to the previous handler`() {
        val delegated = mutableListOf<Throwable>()
        Thread.setDefaultUncaughtExceptionHandler { _, error -> delegated.add(error) }
        Telemetry.installCrashHandler()

        val real = RuntimeException("boom")
        val handler = requireNotNull(Thread.getDefaultUncaughtExceptionHandler())
        handler.uncaughtException(Thread("main"), real)

        assertEquals(listOf(real), delegated)
    }
}
