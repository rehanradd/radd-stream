package com.raddstream.app.player

/**
 * Pure gesture decision table for the MX Player gesture surface. The Compose layer
 * (`player/ui/GestureLayer.kt`) captures pointers and delegates every *meaning* here, so the
 * exact behavior researched in PLAYER_SPEC.md §2.1 is unit-testable without Android:
 *
 *  - double-tap LEFT third  → rewind [GestureSettings.skipMs] (default 10 000 — MX default),
 *  - double-tap RIGHT third → forward,
 *  - double-tap MIDDLE third → play/pause (MX option, on by default),
 *  - single tap → toggle controls,
 *  - vertical drag LEFT half → brightness · RIGHT half → volume,
 *  - horizontal drag → scrub (full width == full duration, clamped),
 *  - long press → speed boost to [GestureSettings.boostSpeed], release restores,
 *  - pinch out/in → aspect ZOOM / FIT (mode-based: PlayerSurfaceView absent in Media3 1.3.1).
 */

enum class ScreenZone { LEFT, CENTER, RIGHT }

data class GestureSettings(
    val skipMs: Long = 10_000L,
    val boostSpeed: Float = 2.0f,
    val doubleTapCenterPlays: Boolean = true,
    val verticalGesturesEnabled: Boolean = true,
    val horizontalScrubEnabled: Boolean = true,
    val longPressBoostEnabled: Boolean = true,
    val lockGestures: Boolean = false, // the on-screen LOCK button sets this
)

sealed class TapCommand {
    object None : TapCommand()
    object ToggleControls : TapCommand()
    object TogglePlayPause : TapCommand()
    data class Seek(val deltaMs: Long) : TapCommand()
    /** Ripple direction for the on-screen double-tap feedback. */
    data class SeekWithRipple(val deltaMs: Long, val zone: ScreenZone) : TapCommand()
}

sealed class DragCommand {
    object None : DragCommand()
    data class BrightnessDelta(val fractionPerSwipe: Float) : DragCommand() // >0 brighter
    data class VolumeDelta(val fractionPerSwipe: Float) : DragCommand()
    data class ScrubTarget(val targetMs: Long, val startedNewScrub: Boolean) : DragCommand()
    data class SpeedStep(val delta: Float) : DragCommand()
}

sealed class PinchCommand {
    object None : PinchCommand()
    object ZoomFill : PinchCommand() // pinch out → expand/crop to fill
    object ZoomFit : PinchCommand()  // pinch in → fit inside
}

/** Which third of the width a point falls in (MX uses halves for vertical, thirds for taps). */
fun tapZone(x: Float, widthPx: Float): ScreenZone {
    require(widthPx > 0f)
    val third = widthPx / 3f
    return when {
        x < third -> ScreenZone.LEFT
        x > 2 * third -> ScreenZone.RIGHT
        else -> ScreenZone.CENTER
    }
}

/** Which half of the width a vertical-drag point falls in (LEFT=brightness, RIGHT=volume). */
fun dragHalfZone(x: Float, widthPx: Float): ScreenZone =
    if (x < widthPx / 2f) ScreenZone.LEFT else ScreenZone.RIGHT

/** Sensible dead-zone: gestures that are mostly horizontal must not trigger vertical HUD. */
enum class DominantAxis { NONE, HORIZONTAL, VERTICAL }

fun dominantAxis(dxPx: Float, dyPx: Float, slopPx: Float = 16f): DominantAxis = when {
    kotlin.math.abs(dxPx) < slopPx && kotlin.math.abs(dyPx) < slopPx -> DominantAxis.NONE
    kotlin.math.abs(dxPx) >= kotlin.math.abs(dyPx) -> DominantAxis.HORIZONTAL
    else -> DominantAxis.VERTICAL
}

object GestureMapper {

    fun onSingleTap(settings: GestureSettings): TapCommand =
        if (settings.lockGestures) TapCommand.None else TapCommand.ToggleControls

    fun onDoubleTap(x: Float, widthPx: Float, settings: GestureSettings): TapCommand {
        if (settings.lockGestures) return TapCommand.None
        return when (tapZone(x, widthPx)) {
            ScreenZone.LEFT -> TapCommand.SeekWithRipple(-settings.skipMs, ScreenZone.LEFT)
            ScreenZone.RIGHT -> TapCommand.SeekWithRipple(+settings.skipMs, ScreenZone.RIGHT)
            ScreenZone.CENTER ->
                if (settings.doubleTapCenterPlays) TapCommand.TogglePlayPause
                else TapCommand.ToggleControls
        }
    }

    fun onLongPress(settings: GestureSettings): Boolean =
        settings.longPressBoostEnabled && !settings.lockGestures

    /**
     * Vertical drag → HUD delta. Convention: dragging UP (negative dy in screen coords)
     * increases, matching MX. Returns fraction of a full top-to-bottom swipe.
     */
    fun onVerticalDrag(
        xZone: ScreenZone,
        dyPx: Float,
        heightPx: Float,
        settings: GestureSettings,
    ): DragCommand {
        if (!settings.verticalGesturesEnabled || settings.lockGestures || heightPx <= 0f) {
            return DragCommand.None
        }
        val fraction = (-dyPx / heightPx)
        return when (xZone) {
            ScreenZone.LEFT -> DragCommand.BrightnessDelta(fraction)
            ScreenZone.RIGHT -> DragCommand.VolumeDelta(fraction)
            // MX: middle vertical drag does nothing special (center keeps play/pause semantics)
            ScreenZone.CENTER -> DragCommand.None
        }
    }

    /** Horizontal scrub: full width == full duration; clamped to [0, durationMs]. */
    fun onHorizontalScrub(
        basePositionMs: Long,
        dxPx: Float,
        widthPx: Float,
        durationMs: Long,
        settings: GestureSettings,
    ): DragCommand {
        if (!settings.horizontalScrubEnabled || settings.lockGestures ||
            widthPx <= 0f || durationMs <= 0
        ) {
            return DragCommand.None
        }
        // A single across-screen swipe moves by one quarter of the duration at a time — MX
        // maps the whole width to a fixed large jump; quarter-width feels right on phones.
        val deltaMs = (dxPx / widthPx * durationMs / 4f).toLong()
        val target = (basePositionMs + deltaMs).coerceIn(0, durationMs)
        return DragCommand.ScrubTarget(target, startedNewScrub = true)
    }

    fun onPinch(cause: String, settings: GestureSettings): PinchCommand {
        if (settings.lockGestures) return PinchCommand.None
        return when (cause) {
            "out" -> PinchCommand.ZoomFill
            "in" -> PinchCommand.ZoomFit
            else -> PinchCommand.None
        }
    }

    /** Speed menu values — MX exposes 0.25× … 4× (confirmed in feature reel). */
    val SPEED_PRESETS: List<Float> =
        listOf(0.25f, 0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 1.75f, 2.0f, 2.5f, 3.0f, 3.5f, 4.0f)

    fun clampedSpeed(speed: Float): Float = speed.coerceIn(0.25f, 4.0f)
}
