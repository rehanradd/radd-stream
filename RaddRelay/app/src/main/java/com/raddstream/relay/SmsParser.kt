package com.raddstream.relay

/**
 * Parses merchant payment SMS from the two Pakistani wallet shortcodes.
 *
 * Only two senders are read: JazzCash (8558) and EasyPaisa (3737). Anything
 * else — personal numbers, banks, promotions — returns null, and the receiver
 * drops it before the service is involved.
 *
 * The patterns are the ones specified for this app. Two deliberate patches:
 *
 *  1. `(?![0-9])` after the transaction id. Without it, a 13-digit id would
 *     match its first 12 digits and be relayed as a valid — but wrong — TID.
 *  2. RegexOption.DOT_MATCHES_ALL, because carrier SMS is routinely delivered
 *     with the amount on one line and "TID: ..." on the next.
 */
object SmsParser {

    const val JAZZCASH = "8558"
    const val EASYPAISA = "3737"

    data class Payment(val gateway: String, val tid: String, val amount: String)

    private val JAZZCASH_RE = Regex(
        pattern = """(?:Rs\.?|PKR)\s*([0-9,]+).*?TID:?\s*([0-9]{10,12})(?![0-9])""",
        options = setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )

    private val EASYPAISA_RE = Regex(
        pattern = """(?:Rs\.?|PKR)\s*([0-9,]+).*?(?:Trx ID|TID):?\s*([0-9]{10,12})(?![0-9])""",
        options = setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )

    /** The gateway for a sender, or null when the sender is not whitelisted. */
    fun gatewayFor(sender: String?): String? = when (sender?.trim()) {
        JAZZCASH -> JAZZCASH
        EASYPAISA -> EASYPAISA
        else -> null
    }

    fun senderIsWhitelisted(sender: String?): Boolean = gatewayFor(sender) != null

    /** The amount, tid and gateway for one SMS body, or null if it is not one. */
    fun parse(sender: String?, body: String?): Payment? {
        val gateway = gatewayFor(sender) ?: return null
        val text = body?.trim().orEmpty()
        if (text.isEmpty()) return null

        val pattern = if (gateway == JAZZCASH) JAZZCASH_RE else EASYPAISA_RE
        val match = pattern.find(text) ?: return null

        // Commas are thousands separators in the SMS; the server wants the
        // plain digits, and a decimal part (if the carrier adds one) stays.
        val amount = match.groupValues[1].replace(",", "")
        val tid = match.groupValues[2]
        if (amount.isEmpty() || tid.isEmpty()) return null
        return Payment(gateway, tid, amount)
    }
}
