package com.raddstream.relay

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Parser tests against representative merchant SMS bodies.
 *
 * The bodies below are shaped from the published JazzCash/EasyPaisa message
 * formats (amount first, transaction id after), not captured from a live SIM —
 * the operator's real messages are the final acceptance test, and the README
 * explains how to replay one with adb. What is pinned here is the contract:
 * whitelisted sender + amount + 10–12 digit TID, and nothing else.
 */
class SmsParserTest {

    private val jazzCashBody =
        "Rs.1,500.00 received from 0300-1234567 on 30-10-2026. " +
            "Your TID is TID: 1234567890. New balance is Rs.2,500.00. JazzCash"

    private val easyPaisaBody =
        "Rs 1,500 has been received from 03001234567. " +
            "Trx ID: 12345678901. Your new balance is Rs. 2,500.00. EasyPaisa"

    // ------------------------------------------------------------- happy path

    @Test
    fun jazzCashSmsGivesGatewayAmountAndTid() {
        val payment = SmsParser.parse("8558", jazzCashBody)!!
        assertEquals(SmsParser.JAZZCASH, payment.gateway)
        assertEquals("1500", payment.amount)
        assertEquals("1234567890", payment.tid)
    }

    @Test
    fun easyPaisaSmsGivesGatewayAmountAndTid() {
        val payment = SmsParser.parse("3737", easyPaisaBody)!!
        assertEquals(SmsParser.EASYPAISA, payment.gateway)
        assertEquals("1500", payment.amount)
        assertEquals("12345678901", payment.tid)
    }

    @Test
    fun easyPaisaAcceptsTheTidSpellingToo() {
        val body = "You have received PKR 2,000 from 03001234567. TID 9876543210."
        val payment = SmsParser.parse("3737", body)!!
        assertEquals("2000", payment.amount)
        assertEquals("9876543210", payment.tid)
    }

    @Test
    fun theAmountAndTidMayBeOnDifferentLines() {
        val body = "Rs.500 received from 03001234567.\nYour TID: 5556667778.\nJazzCash"
        val payment = SmsParser.parse("8558", body)!!
        assertEquals("500", payment.amount)
        assertEquals("5556667778", payment.tid)
    }

    @Test
    fun amountMatchingIsCaseInsensitive() {
        val body = "pkr 750 received. TID: 1234567890"
        assertEquals("750", SmsParser.parse("8558", body)!!.amount)
    }

    @Test
    fun aThirteenDigitTidIsNotTruncatedIntoAValidOne() {
        // Without the trailing (?!\d) guard the regex would take the first 12
        // digits and relay a TID that does not exist.
        val body = "Rs.100 received. TID: 1234567890123"
        assertNull(SmsParser.parse("8558", body))
    }

    @Test
    fun aNineDigitTidIsNotATid() {
        val body = "Rs.100 received. TID: 123456789"
        assertNull(SmsParser.parse("8558", body))
    }

    // -------------------------------------------------------------- rejections

    @Test
    fun aPersonalNumberIsNeverRead() {
        assertNull(SmsParser.parse("03001234567", jazzCashBody))
        assertNull(SmsParser.parse("+923001234567", easyPaisaBody))
    }

    @Test
    fun theWalletNameIsNotTheSender() {
        // Some phones show "JazzCash"; the whitelist is the shortcode only, and
        // a body is not trusted because it names the wallet.
        assertNull(SmsParser.parse("JazzCash", jazzCashBody))
        assertNull(SmsParser.parse("EasyPaisa", easyPaisaBody))
    }

    @Test
    fun aBankSmsWithAnAmountAndALongNumberIsNotParsed() {
        val body = "Rs.25,000 debited from your account 0123456789012 on 30-10-2026."
        assertNull(SmsParser.parse("8558", body))
    }

    @Test
    fun anEmptyBodyIsNotParsed() {
        assertNull(SmsParser.parse("8558", ""))
        assertNull(SmsParser.parse("8558", null))
        assertNull(SmsParser.parse(null, jazzCashBody))
    }

    @Test
    fun theWhitelistIsExactlyTwoSenders() {
        assertTrue(SmsParser.senderIsWhitelisted("8558"))
        assertTrue(SmsParser.senderIsWhitelisted("3737"))
        assertTrue(SmsParser.senderIsWhitelisted(" 8558 "))
        assertFalse(SmsParser.senderIsWhitelisted("8559"))
        assertFalse(SmsParser.senderIsWhitelisted("3738"))
        assertFalse(SmsParser.senderIsWhitelisted(""))
        assertFalse(SmsParser.senderIsWhitelisted(null))
    }
}
