package com.raddstream.app.ui.theme

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.raddstream.app.brand.Brand
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

// ═════════════════════════════════════════════════════════════════════════════
//  RADD STREAM MARK — "the Source Ripple"
// ═════════════════════════════════════════════════════════════════════════════
//  Geometry of the identity (same construction as the launcher vector):
//    • A solid core dot — the SOURCE (this app is, literally, a resolver of
//      sources; the dot is the one true origin in the picture).
//    • Two open arc rings facing "forward" (east) — the CURRENT spreading out
//      of it; the opening to the right is a subliminal play affordance that
//      is NOT a literal play triangle (everyone ships triangles; nobody ships
//      a ripple with a rider).
//    • A small rider dot parked on the outer arc at the north-east crest —
//      the stream you are riding. It is the trademark detail and the thing
//      the eye finds at 43px before it finds anything else.
//  Stroke caps are round ("river stone"); widths scale with the canvas, so
//  the mark stays crisp from 16dp inline to 120dp empty-state.
//  Legal note: all geometry is original; no third-party marks anywhere.
// ═════════════════════════════════════════════════════════════════════════════

/** The Source Ripple brand mark. Tint it with any token; header default is the current. */
@Composable
fun RaddStreamMark(
    modifier: Modifier = Modifier,
    diameter: Dp = 28.dp,
    color: Color = RaddCurrent500,
) {
    Canvas(modifier = modifier.size(diameter)) {
        val w = min(size.width, size.height)
        val u = w / 100f                 // design units (synced to the 108-grid XML icon)
        val cx = size.width / 2f
        val cy = size.height / 2f

        val strokeInner = 9.3f * u
        val strokeOuter = 7.4f * u
        val r1 = 16.7f * u               // inner ring
        val r2 = 29.6f * u               // outer ring
        val sweep = 140f                 // rings span 140°, opening facing east
        val start = -sweep / 2f          // centered on 0° (east)

        // Core source dot
        drawCircle(color = color, radius = 7.4f * u, center = Offset(cx, cy))

        // Inner current ring — full alpha
        drawArc(
            color = color,
            startAngle = start,
            sweepAngle = sweep,
            useCenter = false,
            topLeft = Offset(cx - r1, cy - r1),
            size = Size(r1 * 2f, r1 * 2f),
            style = Stroke(width = strokeInner, cap = StrokeCap.Round),
        )

        // Outer ring — slightly faded, the ripple losing energy
        drawArc(
            color = color.copy(alpha = 0.62f),
            startAngle = start,
            sweepAngle = sweep,
            useCenter = false,
            topLeft = Offset(cx - r2, cy - r2),
            size = Size(r2 * 2f, r2 * 2f),
            style = Stroke(width = strokeOuter, cap = StrokeCap.Round),
        )

        // Rider dot just past the north-east crest of the outer ring (-79° on r2,
        // exactly like the launcher vector), always full alpha so it reads
        // brighter than the faded ring it rides.
        val riderAngle = Math.toRadians(-79.0)
        drawCircle(
            color = color,
            radius = 5f * u,
            center = Offset(
                cx + r2 * cos(riderAngle).toFloat(),
                cy + r2 * sin(riderAngle).toFloat(),
            ),
        )
    }
}

/** Horizontal lockup: mark + two-tone wordmark. Use in TopAppBar title slots
 *  and empty states (pass a bigger [size] there). */
@Composable
fun RaddBrandLockup(
    modifier: Modifier = Modifier,
    markSize: Dp = 26.dp,
    onName: Color = RaddPaperOnInk,
    onStream: Color = RaddCurrent500,
) {
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        RaddStreamMark(diameter = markSize)
        Text(
            text = Brand.wordmarkFirst,
            style = RaddTypography.headlineSmall.copy(color = onName),
        )
        Text(
            text = Brand.wordmarkSecond,
            style = RaddTypography.headlineSmall.copy(color = onStream),
        )
    }
}
