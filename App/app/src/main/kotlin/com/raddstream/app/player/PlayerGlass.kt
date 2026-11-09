package com.raddstream.app.player

/**
 * BM rule 9: frosted glass on the player chrome — the honest version.
 *
 * True backdrop blur is not achievable in Compose over live video: `RenderEffect`
 * and `Modifier.blur` blur the element's own content, not what sits behind it, so
 * a "blurred" top bar over a playing video is a lie the framework cannot keep.
 * What IS achievable is the frosted TREATMENT — a translucent tint, a 1dp border,
 * and a specular highlight — which reads as glass on the dark video surface and
 * degrades gracefully. The decision is pure and pinned here: low-RAM devices get
 * the solid fallback (no translucency to composite every frame), everything else
 * gets the frosted bars. Glass is never nested — the bars sit directly on the video,
 * never on another glass surface — and never on a scrolling list.
 */
data class GlassSpec(
    /** True when the bars may use the frosted treatment; false means solid chrome. */
    val useGlass: Boolean,
    /** Tint alpha for the bar background when glass is on; 1f when solid. */
    val tintAlpha: Float,
    /** Border alpha for the 1dp edge; 0f when solid. */
    val borderAlpha: Float,
)

object PlayerGlass {

    fun spec(isLowRamDevice: Boolean): GlassSpec =
        if (isLowRamDevice) {
            GlassSpec(useGlass = false, tintAlpha = 1f, borderAlpha = 0f)
        } else {
            GlassSpec(useGlass = true, tintAlpha = 0.55f, borderAlpha = 0.18f)
        }
}
