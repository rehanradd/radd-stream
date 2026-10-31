package com.raddstream.relay

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/**
 * Receives SMS_RECEIVED, keeps only the two merchant senders, and hands the
 * parsed payment to the relay service.
 *
 * The receiver does no network work: Android gives a broadcast receiver about
 * ten seconds, and the service owns the queue, so a dead connection never
 * loses a TID.
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val payments = when (intent.action) {
            Telephony.Sms.Intents.SMS_RECEIVED_ACTION -> fromSms(intent)
            ACTION_DEBUG -> fromDebug(intent)
            else -> return
        }
        for (payment in payments) {
            RelayService.accept(context, payment)
        }
    }

    /**
     * Multipart SMS arrive as several parts in one broadcast. They are joined
     * per sender before parsing, because the amount and the TID are routinely
     * split across the part boundary.
     */
    private fun fromSms(intent: Intent): List<SmsParser.Payment> {
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return emptyList()
        val bodies = LinkedHashMap<String, StringBuilder>()
        for (part in parts) {
            val sender = part.originatingAddress ?: continue
            if (!SmsParser.senderIsWhitelisted(sender)) continue
            bodies.getOrPut(sender) { StringBuilder() }.append(part.messageBody ?: "")
        }
        return bodies.mapNotNull { (sender, body) ->
            SmsParser.parse(sender, body.toString())
        }
    }

    /**
     * Debug-only injection, so the operator can exercise the whole path without
     * sending real money:
     *
     *   adb shell am broadcast -n com.raddstream.relay/.SmsReceiver \
     *     -a com.raddstream.relay.DEBUG_SMS \
     *     --es sender 8558 --es body "Rs.1 ... TID: 1234567890"
     *
     * Release builds ignore the action entirely.
     */
    private fun fromDebug(intent: Intent): List<SmsParser.Payment> {
        if (!BuildConfig.DEBUG) return emptyList()
        val payment = SmsParser.parse(
            intent.getStringExtra(EXTRA_SENDER),
            intent.getStringExtra(EXTRA_BODY),
        )
        return listOfNotNull(payment)
    }

    companion object {
        const val ACTION_DEBUG = "com.raddstream.relay.DEBUG_SMS"
        const val EXTRA_SENDER = "sender"
        const val EXTRA_BODY = "body"
    }
}
