package com.raddstream.app.viewmodel

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VipTidTest {

    @Test
    fun `normalize drops the punctuation an SMS adds and canonicalises case`() {
        assertEquals("8123498172", VipTid.normalize("8123 498 172"))
        assertEquals("ABC123XYZ", VipTid.normalize("abc-123 xyz"))
        assertEquals("", VipTid.normalize("  -  "))
    }

    @Test
    fun `a pasted ten digit reference is valid`() {
        assertTrue(VipTid.isValid("8123498172"))
        assertNull(VipTid.validationError("8123498172"))
    }

    @Test
    fun `an alphanumeric reference at both length bounds is valid`() {
        assertTrue(VipTid.isValid("A1B2C3"))
        assertTrue(VipTid.isValid("A1B2C3D4E5F6G7H8I9J0K1L2"))
    }

    @Test
    fun `empty, short and long references are refused with a reason`() {
        assertNotNull(VipTid.validationError(""))
        assertNotNull(VipTid.validationError("A1B2C"))
        assertNotNull(VipTid.validationError("A1B2C3D4E5F6G7H8I9J0K1L2M3"))
        assertFalse(VipTid.isValid(""))
    }

    @Test
    fun `normalize removes symbols, so validation sees only the reference itself`() {
        val normalized = VipTid.normalize("TID: 9988-7766!")
        assertEquals("TID99887766", normalized)
        assertTrue(VipTid.isValid(normalized))
    }
}
