package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Long-pressing a saved title used to delete it on the spot, so a slipping thumb cost the
 * viewer a row that had been synced to their account with nothing on screen to say it was about
 * to happen. The rule is now: hold arms the row, the dialog's Remove disarms it by deleting,
 * and everything else deletes nothing. That is four paths and one truth table, so the table is
 * what gets tested — the ViewModel only moves its own state through these same three calls.
 */
class MyListRemovalTest {

    @Test
    fun `a long press arms the row it names and deletes nothing`() {
        val step = MyListRemoval.step(armed = null, RemovalTrigger.LONG_PRESS, target = 7)
        assertEquals(7, step.armed)
        assertEquals(null, step.removeNow)
    }

    @Test
    fun `arming a second row moves the question instead of queueing a deletion`() {
        val step = MyListRemoval.step(armed = 7, RemovalTrigger.LONG_PRESS, target = 9)
        assertEquals(9, step.armed)
        assertEquals(null, step.removeNow)
    }

    @Test
    fun `confirming removes exactly the armed row and clears the arm`() {
        val step = MyListRemoval.step(armed = 7, RemovalTrigger.CONFIRM, target = null)
        assertEquals(null, step.armed)
        assertEquals(7, step.removeNow)
    }

    @Test
    fun `a confirm with nothing armed deletes nothing`() {
        // Reachable: a dialog that was dismissed by a rotating screen still has a button in the
        // accessibility tree, and the repository must not be handed a row nobody chose.
        val step = MyListRemoval.step(armed = null, RemovalTrigger.CONFIRM, target = null)
        assertEquals(null, step.armed)
        assertEquals(null, step.removeNow)
    }

    @Test
    fun `cancelling clears the arm and deletes nothing`() {
        val step = MyListRemoval.step(armed = 7, RemovalTrigger.CANCEL, target = null)
        assertEquals(null, step.armed)
        assertEquals(null, step.removeNow)
    }

    @Test
    fun `a cancel with nothing armed is a no-op`() {
        val step = MyListRemoval.step(armed = null, RemovalTrigger.CANCEL, target = 7)
        assertEquals(null, step.armed)
        assertEquals(null, step.removeNow)
    }

    @Test
    fun `a confirm deletes the armed row, never a target it was handed`() {
        // CONFIRM and CANCEL carry no id at all, so a caller cannot delete a row the dialog never
        // armed by passing one alongside the trigger.
        val confirmed = MyListRemoval.step(armed = 7, RemovalTrigger.CONFIRM, target = 99)
        assertEquals(7, confirmed.removeNow)
    }
}
