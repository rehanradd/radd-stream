package com.raddstream.app.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.platform.LocalContext
import android.provider.Settings
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * Shared page-level building blocks: section headers, empty/error/loading states,
 * skeleton placeholders, a horizontal rail, and grid paging detection.
 *
 * Motion respects the system "remove animations" / animator-duration-scale setting
 * so the shimmer does not run for users who asked for reduced motion.
 */

@Composable
fun rememberReduceMotion(): Boolean {
    val context = LocalContext.current
    return remember {
        try {
            Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
        } catch (_: Exception) {
            false
        }
    }
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    action: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onBackground,
            )
            if (!subtitle.isNullOrBlank()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (action != null) {
            Spacer(Modifier.width(8.dp))
            action()
        }
    }
}

/**
 * A true shimmer: a soft highlight band swept across a dim base rather than an opacity
 * pulse. Used for every placeholder — poster tiles, hero slides, rail skeletons — so a
 * loading screen reads as "artwork is on its way" instead of a row of blank boxes.
 *
 * The band travels at a constant speed ([SHIMMER_PERIOD_MS] per pass), which is what makes
 * it feel calm rather than throb. With reduced motion on, the same box is painted as a
 * static block, so the placeholder never disappears and nothing moves.
 */
@Composable
fun ShimmerBox(
    modifier: Modifier = Modifier,
    shape: Shape = RectangleShape,
) {
    val reduceMotion = rememberReduceMotion()
    val base = MaterialTheme.colorScheme.surfaceVariant
    if (reduceMotion) {
        Box(modifier.clip(shape).background(base.copy(alpha = 0.5f)))
        return
    }
    val highlight = MaterialTheme.colorScheme.onSurfaceVariant
    val transition = rememberInfiniteTransition(label = "shimmer")
    val progress by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(SHIMMER_PERIOD_MS, easing = LinearEasing),
        ),
        label = "shimmerProgress",
    )
    Box(
        modifier
            .clip(shape)
            .background(base)
            .drawWithContent {
                drawContent()
                val band = size.width * 0.55f
                val travel = size.width + band * 2f
                val x = -band + travel * progress
                drawRect(
                    Brush.linearGradient(
                        colors = listOf(Color.Transparent, highlight.copy(alpha = 0.16f), Color.Transparent),
                        start = Offset(x, 0f),
                        end = Offset(x + band, size.height),
                    )
                )
            },
    )
}

/**
 * Lazy placeholder that shimmers when motion is allowed, or draws a static block when
 * the user reduced motion — never a blank gap during load.
 */
@Composable
fun SkeletonBox(
    modifier: Modifier = Modifier,
    aspectRatioValue: Float? = null,
) {
    val boxModifier = if (aspectRatioValue != null) {
        modifier.fillMaxWidth().aspectRatio(aspectRatioValue)
    } else {
        modifier
    }
    ShimmerBox(boxModifier, shape = RoundedCornerShape(12.dp))
}

private const val SHIMMER_PERIOD_MS = 1_400

@Composable
fun PosterGridSkeleton(
    modifier: Modifier = Modifier,
    columns: Int = 3,
    rows: Int = 3,
) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(columns),
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp, start = 16.dp, end = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        userScrollEnabled = false,
    ) {
        items(columns * rows) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                SkeletonBox(aspectRatioValue = 0.68f)
                SkeletonBox(Modifier.height(14.dp))
                SkeletonBox(Modifier.height(10.dp).width(60.dp))
            }
        }
    }
}

@Composable
fun EmptyState(
    title: String,
    modifier: Modifier = Modifier,
    message: String? = null,
    icon: @Composable (() -> Unit)? = null,
    action: @Composable (() -> Unit)? = null,
) {
    Box(modifier.fillMaxSize().padding(32.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (icon != null) {
                icon()
                Spacer(Modifier.height(12.dp))
            }
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center,
            )
            if (!message.isNullOrBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
            if (action != null) {
                Spacer(Modifier.height(16.dp))
                action()
            }
        }
    }
}

@Composable
fun ErrorState(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    secondaryLabel: String? = null,
    onSecondary: (() -> Unit)? = null,
) {
    EmptyState(
        title = "Something went wrong",
        modifier = modifier,
        message = message,
        icon = {
            Icon(
                Icons.Default.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
                modifier = Modifier.size(40.dp),
            )
        },
        action = {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                OutlinedButton(onClick = onRetry) {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("Retry")
                }
                // A server that is down has two honest answers: try again, or go
                // talk to a different server. Without the second one a person whose
                // configured address is simply wrong can only retry forever.
                if (secondaryLabel != null && onSecondary != null) {
                    Spacer(Modifier.height(8.dp))
                    TextButton(onClick = onSecondary) { Text(secondaryLabel) }
                }
            }
        },
    )
}

@Composable
fun LoadingState(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
    }
}

/**
 * The compact cousin of [ErrorState]: a page that already shows content but could not
 * finish loading — a failed next page, a detail reload that came back empty — says so in
 * one line with a retry, instead of replacing the content the viewer can already see.
 *
 * This exists because `ErrorState` is a full-screen placeholder, and every screen here
 * only reached for it when its list was EMPTY. A load that failed on page 3 therefore
 * rendered nothing at all: the viewer saw a shorter list than the server has and no way
 * to know the difference.
 */
@Composable
fun InlineLoadFailure(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            Icons.Default.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.error,
            modifier = Modifier.size(20.dp),
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text = message,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
        )
        TextButton(
            onClick = onRetry,
            modifier = Modifier.heightIn(min = 48.dp),
        ) {
            Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("Retry")
        }
    }
}

/**
 * A horizontal content rail. Kept generic so Home can render every row (newly
 * added, per-type, continue watching) with one keyed, recycled, lazily-composed
 * strip — cheap on low-RAM devices.
 */
@Composable
fun <T> MediaRail(
    items: List<T>,
    key: (T) -> Any,
    itemContent: @Composable (T) -> Unit,
) {
    LazyRow(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(items, key = key) { item ->
            Box(Modifier.width(132.dp)) { itemContent(item) }
        }
    }
}

/**
 * Emits [onLoadMore] when the user is within [buffer] rows of the bottom of a grid.
 * Cancelled automatically with the composition. Only fires once per page because the
 * caller gates on an `isLoadingMore` flag in its ViewModel.
 */
@Composable
fun rememberGridEndlessPaging(
    gridState: LazyGridState,
    buffer: Int = 4,
    onLoadMore: () -> Unit,
) {
    val total = gridState.layoutInfo.totalItemsCount
    val lastVisible = gridState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
    LaunchedEffect(total, lastVisible) {
        if (total > 0 && lastVisible >= total - buffer) onLoadMore()
    }
}

/** A small text button used as a section "See all" affordance. */
@Composable
fun SeeAllButton(onClick: () -> Unit, label: String = "See all") {
    Button(
        onClick = onClick,
        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.primary),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
        modifier = Modifier.heightIn(min = 40.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge)
    }
}
