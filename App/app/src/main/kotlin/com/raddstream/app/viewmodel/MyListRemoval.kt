package com.raddstream.app.viewmodel

/** What the viewer just did to a row in My List. */
enum class RemovalTrigger {
    /** Held a tile down — the wish to remove, not the removal. */
    LONG_PRESS,

    /** Tapped Remove in the notice that just opened. */
    CONFIRM,

    /** Backed out of the notice, or tapped outside it. */
    CANCEL,
}

/**
 * The outcome of one trigger: which row is now armed, and which row (if any) to delete.
 *
 * `removeNow` is null for every trigger except a confirmation of an armed row, and an
 * unconfirmed arm never deletes anything — that is the whole promise the dialog makes.
 */
data class RemovalStep(val armed: Int?, val removeNow: Int?)

/**
 * The long-press rule in My List, as one pure step function.
 *
 * A tile's long-press used to delete the row immediately, which makes a slipping thumb and a
 * deliberate removal the same gesture with no way back: the row is gone from the device and
 * from the synced library, and nothing on screen said it would be. The screen now arms the row
 * and asks. Only the answer to that question is this object — the dialog renders whatever
 * [armed] is, and the repository runs whatever [removeNow] names, so no composable can invent
 * a fourth path.
 *
 * Arming a second row re-arms the dialog onto it and deletes nothing: a viewer who long-presses
 * A, changes their mind, then long-presses B is choosing B, not queueing two removals.
 */
object MyListRemoval {

    fun step(armed: Int?, trigger: RemovalTrigger, target: Int?): RemovalStep = when (trigger) {
        RemovalTrigger.LONG_PRESS -> RemovalStep(armed = target, removeNow = null)
        RemovalTrigger.CONFIRM -> RemovalStep(armed = null, removeNow = armed)
        RemovalTrigger.CANCEL -> RemovalStep(armed = null, removeNow = null)
    }
}
