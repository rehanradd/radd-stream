package com.raddstream.app.share

import com.raddstream.app.data.RemoteFeatures
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Two switches gate one socket: the row on the Settings screen and the operators
 * `feature_flags.sharing`. The AND is the whole policy, and it is the kind of rule that a later
 * refactor inverts into an OR — which would make a server-side kill switch decorative.
 */
class LanShareGateTest {

    @Test
    fun `a viewer who asks and a server that allows is the only serving case`() {
        assertTrue(LanShareRunner.shouldServe(wantedByViewer = true, allowedByOperator = true))
    }

    @Test
    fun `the operator can close a socket a viewer already opened`() {
        assertFalse(LanShareRunner.shouldServe(wantedByViewer = true, allowedByOperator = false))
    }

    @Test
    fun `the viewer can stop serving without the server doing anything`() {
        assertFalse(LanShareRunner.shouldServe(wantedByViewer = false, allowedByOperator = true))
    }

    @Test
    fun `nothing is served when nobody asked`() {
        assertFalse(LanShareRunner.shouldServe(wantedByViewer = false, allowedByOperator = false))
    }

    @Test
    fun `a board that has not answered yet allows sharing`() {
        // The default the app paints before DataStore replies must not be a silent lock-out:
        // every switch here defaults to on, matching a deployment that never set the key.
        assertTrue(LanShareRunner.shouldServe(wantedByViewer = true, allowedByOperator = RemoteFeatures().sharing))
    }
}
