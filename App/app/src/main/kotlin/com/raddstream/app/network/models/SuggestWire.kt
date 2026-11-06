package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/**
 * GET /api/v2/suggest — cheap type-ahead over the works ledger.
 *
 * `id` is a WORK id (cat_works), not a post id: tapping a suggestion runs a
 * search for that title, it never opens a detail page, because there is no
 * post to open from here. The server matches normalised title prefixes
 * only, and the app shows at most five.
 */
data class SuggestItem(
    val id: Int = 0,
    val title: String = "",
    val year: Int? = null,
    @SerializedName("work_type")
    val workType: String? = null,
    @SerializedName("poster_url")
    val posterUrl: String? = null,
    @SerializedName("quality_max")
    val qualityMax: String? = null,
)

data class SuggestResponse(
    val ok: Boolean = false,
    val items: List<SuggestItem> = emptyList(),
)
