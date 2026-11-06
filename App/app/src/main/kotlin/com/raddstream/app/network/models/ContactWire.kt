package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/**
 * Body of POST api/v1/contact. `category` is one of the panel's five
 * (bug, payment, content, takedown, other); `account_hint` is an email the
 * viewer may leave so the operator can reply — the server stores it masked,
 * never the full address.
 */
data class ContactRequest(
    val category: String,
    val subject: String,
    val body: String,
    @SerializedName("account_hint")
    val accountHint: String? = null,
)

/** The intake answer. No id comes back: the message is the operator's, not the viewer's, to track. */
data class ContactResponse(
    val success: Boolean = false,
)
