package com.raddstream.app.data

import android.content.Context

/**
 * The phone-side half of Tracking A: counters the app folds into the `usage`
 * block of the next progress report, and nothing else.
 *
 * A counter is a whole number under one of the server's eleven field names
 * (`usage_stats.CLIENT_FIELDS`); anything else is ignored at the door, so a
 * typo'd call site cannot invent a metric the operator will read as real.
 * Counts are recorded only while the [gate] says the viewer consented — a
 * declined or unanswered consent records nothing, so a later "yes" never
 * flushes counts from before the answer.
 *
 * Storage is SharedPreferences, not DataStore, on purpose: the player and
 * the crash handler call [record] from threads that cannot suspend, and the
 * crash handler in particular needs a synchronous commit on a dying process.
 * The values are plain counters, never identifiers, so the simpler store
 * costs nothing in privacy. [acknowledge] subtracts exactly the counts a
 * report carried, so increments that land between the snapshot and the
 * acknowledgement survive instead of being eaten.
 */
class UsageCounters(
    private val store: UsageCounterStore,
    private val gate: () -> Boolean,
) {
    companion object {
        val FIELDS: Set<String> = Telemetry.USAGE_FIELDS
    }

    fun record(field: String, count: Int = 1) {
        if (!gate() || field !in FIELDS || count <= 0) return
        store.add(field, count)
    }

    fun snapshot(): Map<String, Int> =
        store.snapshot().filterKeys { it in FIELDS }.filterValues { it > 0 }

    fun acknowledge(sent: Map<String, Int>) {
        val known = sent.filterKeys { it in FIELDS }.filterValues { it > 0 }
        if (known.isNotEmpty()) store.subtract(known)
    }
}

/** Synchronous counter storage: add, read, subtract. */
interface UsageCounterStore {
    fun add(field: String, count: Int)
    fun snapshot(): Map<String, Int>
    fun subtract(sent: Map<String, Int>)
}

/**
 * The counters, one integer per field, in a private preferences file.
 * Every write is a synchronous `commit()`: the crash handler depends on it,
 * and a counter is small enough that the disk write is not a jank risk.
 * Totals are capped at one million per field so a runaway call site cannot
 * grow the file without bound; the server clamps each submission to 1000
 * anyway, so the cap only bounds storage, never a real report.
 */
class SharedPreferencesUsageCounterStore(context: Context) : UsageCounterStore {
    private val prefs = context.getSharedPreferences(
        "radd_usage_counters",
        Context.MODE_PRIVATE,
    )

    override fun add(field: String, count: Int) {
        prefs.edit()
            .putInt(field, (prefs.getInt(field, 0) + count).coerceAtMost(MAX_TOTAL))
            .commit()
    }

    override fun snapshot(): Map<String, Int> =
        UsageCounters.FIELDS.associateWith { prefs.getInt(it, 0) }
            .filterValues { it > 0 }

    override fun subtract(sent: Map<String, Int>) {
        prefs.edit().apply {
            sent.forEach { (field, count) ->
                putInt(field, (prefs.getInt(field, 0) - count).coerceAtLeast(0))
            }
        }.commit()
    }

    companion object {
        const val MAX_TOTAL = 1_000_000
    }
}
