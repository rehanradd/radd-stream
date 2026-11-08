package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/**
 * One live TV channel, as `GET /api/v1/live-tv/channels` serves it.
 *
 * The upstream HLS URL never leaves the server: [streamId] is the signed
 * handle the player presses at `/api/v1/stream?id=…`, exactly like a movie
 * handle. No raw URL and no host name is ever shown or stored on the device.
 */
data class LiveTvChannel(
    val id: Int,
    val name: String,
    val category: String,
    val country: String,
    val language: String,
    @SerializedName("logo_url")
    val logoUrl: String,
    @SerializedName("stream_id")
    val streamId: String,
)

data class LiveTvChannelsResponse(
    val success: Boolean = true,
    val channels: List<LiveTvChannel> = emptyList(),
    val categories: List<String> = emptyList(),
)
