package com.raddstream.app.ui.theme

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import com.raddstream.app.ui.components.rememberReduceMotion

/**
 * The motion system's press feedback (UI-fix P1-X1): [RaddTokens.Motion.PressScale]
 * (0.97) + a light haptic tick, wired to the same [MutableInteractionSource] the
 * control's own clickable/button already owns — so the scale tracks the real
 * press state instead of a second gesture detector fighting it. Reduced-motion
 * users get the haptic only, never the scale.
 *
 * Restyle 2026-11-13: the scale rides the M3 Expressive default-effects
 * spring (critically damped, stiffness 1600) instead of a fixed 80/120 ms
 * tween, so a press settles instead of cutting — the same press, alive.
 *
 * Usage: create the source once in the composable, pass it to the clickable /
 * Button's `interactionSource`, apply [pressScale] to the same node, and call
 * [PressHaptics] once in the body.
 */
@Composable
fun Modifier.pressScale(
    interactionSource: MutableInteractionSource,
    enabled: Boolean = true,
): Modifier {
    val pressed by interactionSource.collectIsPressedAsState()
    val reduceMotion = rememberReduceMotion()
    val target = if (pressed && enabled && !reduceMotion) RaddTokens.Motion.PressScale else 1f
    val scale by animateFloatAsState(
        targetValue = target,
        animationSpec = RaddMotion.defaultEffects(),
        label = "pressScale",
    )
    return this.graphicsLayer(scaleX = scale, scaleY = scale)
}

/** The haptic half of press feedback: one light tick on press-down. */
@Composable
fun PressHaptics(interactionSource: MutableInteractionSource, enabled: Boolean = true) {
    val pressed by interactionSource.collectIsPressedAsState()
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(pressed) {
        if (pressed && enabled) haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove)
    }
}
