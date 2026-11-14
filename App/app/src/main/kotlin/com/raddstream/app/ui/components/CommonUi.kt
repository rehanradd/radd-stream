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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import android.provider.Settings
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.raddstream.app.ui.layout.CardGeometry
import com.raddstream.app.ui.theme.RaddEmphasized
import com.raddstream.app.ui.theme.RaddStreamTheme

/**
 * Shared page-level building blocks: section headers, empty/error/loading states,
 * skeleton placeholders, a horizontal rail, and grid paging detection.
 *
 * Motion respects the system "remove animations" / animator-duration-scale setting
 * so the shimmer does not run for users who asked for reduced motion.
 */

/**
 * Session 121 (P-16): the app's filter chips, in the accent. `FilterChip`'s default
 * selected container is `secondaryContainer` — a dark red-brown in this brand — so
 * a selected chip read as an error state next to the jade accent. Selected chips use
 * the jade `primaryContainer` (with its `onPrimaryContainer` label and check) instead;
 * everything unselected keeps the default. Every `FilterChip` in the app uses this.
 * Session 123: the brand value itself moved from maroon toward the coral secondary
 * (same dark container role, warmer hue) so a chip that misses this override still
 * reads as coral family, not an error.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun raddFilterChipColors() = FilterChipDefaults.filterChipColors(
    selectedContainerColor = MaterialTheme.colorScheme.primaryContainer,
    selectedLabelColor = MaterialTheme.colorScheme.onPrimaryContainer,
    selectedLeadingIconColor = MaterialTheme.colorScheme.onPrimaryContainer,
    selectedTrailingIconColor = MaterialTheme.colorScheme.onPrimaryContainer,
)

/**
 * F25 (Batch B): the chip states as Android Studio sees them — selected
 * beside unselected, on the shared token. A future change to the selected
 * fill, the check or the border shows up here before it ships; the
 * screenshot test in ScreenSnapshotTest pins the same two states in CI.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Preview(name = "Filter chip states", showBackground = true)
@Composable
private fun FilterChipStatesPreview() {
    RaddStreamTheme {
        Row(
            modifier = Modifier.padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FilterChip(
                selected = true,
                onClick = {},
                label = { Text("Hindi") },
                colors = raddFilterChipColors(),
                modifier = Modifier.heightIn(min = 48.dp),
            )
            FilterChip(
                selected = false,
                onClick = {},
                label = { Text("English") },
                colors = raddFilterChipColors(),
                modifier = Modifier.heightIn(min = 48.dp),
            )
        }
    }
}

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

/**
 * One title style for every dialog (D-2): the display family, semibold,
 * 24sp (M3 headlineSmall) — the same face screen titles use, so a dialog headline never renders
 * in the thin, faint face the video audit caught on the give-up, consent and
 * volume dialogs. Every `AlertDialog` title goes through here; the colour
 * defaults to the surface's own, and the player dialogs pass white for their
 * dark container.
 */
@Composable
fun RaddDialogTitle(
    text: String,
    color: Color = MaterialTheme.colorScheme.onSurface,
) {
    Text(
        text = text,
        style = MaterialTheme.typography.headlineSmall,
        color = color,
    )
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
            // Restyle: section heads are the emphasized titleLarge (22sp,
            // bold) — a rail head that reads at a glance without shouting
            // over the posters below it.
            // F30 (Batch B): a heading, not bare paint — TalkBack users
            // navigate by headings, and Robo flagged the "Your library"
            // strip as having no screen-reader label at all.
            Text(
                text = title,
                style = RaddEmphasized.titleLarge,
                color = MaterialTheme.colorScheme.onBackground,
                modifier = Modifier.semantics { heading() },
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
 *
 * Robo run 7: the Home skeleton bars were read as low-contrast text (1.09:1) in
 * runs 6 and 7 — the run-6 "sampling artifact" reading changed nothing, so the
 * flag came back identical. The bars are decorative: they carry no words, so
 * they leave the accessibility tree entirely ([clearAndSetSemantics]) instead
 * of standing in it as something a contrast check can sample.
 *
 * [highlightAlpha] is the band's strength: the shared 0.16f default is a
 * calm sweep for small tiles, and a caller whose placeholder fills the
 * screen (the hero skeleton) may ask for a stronger band so the wait reads
 * as loading instead of a blank grey box (Samsung RTL v1.1.2, Issue 3).
 */
@Composable
fun ShimmerBox(
    modifier: Modifier = Modifier,
    shape: Shape = RectangleShape,
    highlightAlpha: Float = SHIMMER_HIGHLIGHT_ALPHA,
) {
    val reduceMotion = rememberReduceMotion()
    val base = MaterialTheme.colorScheme.surfaceVariant
    if (reduceMotion) {
        Box(modifier.clip(shape).background(base.copy(alpha = 0.5f)).clearAndSetSemantics { })
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
                        colors = listOf(Color.Transparent, highlight.copy(alpha = highlightAlpha), Color.Transparent),
                        start = Offset(x, 0f),
                        end = Offset(x + band, size.height),
                    )
                )
            }
            // Robo run 7: decorative placeholder — no words, no node in the
            // accessibility tree (see the KDoc above).
            .clearAndSetSemantics { },
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

/** The shimmer band's default strength; the hero skeleton asks for more. */
private const val SHIMMER_HIGHLIGHT_ALPHA = 0.16f

/**
 * The catalog grid's one column rule: a tile is never narrower than 120dp, so a phone gets
 * three columns and a tablet gets more without any screen saying so. Every real grid and
 * [PosterGridSkeleton] draw from this single value — a skeleton with its own column count is
 * a placeholder whose cells jump sideways the moment the cards replace them.
 */
val CatalogGridColumns: GridCells = GridCells.Adaptive(minSize = 120.dp)

/**
 * The loading stand-in for a poster grid: the same [CatalogGridColumns], the same gutters and
 * the same tile shape as the cards that replace it, so nothing reflows when data arrives.
 * [SKELETON_CELLS] is a fixed handful rather than `columns * rows` because an adaptive grid
 * does not know its column count until it is measured.
 *
 * F21 (Batch B): the column count and the padding are parameters now, because a skeleton
 * must match the grid it stands in for — Search results are a fixed 2-wide grid inside an
 * already-padded column, and the 3-wide adaptive skeleton with its own 16dp sides would
 * reflow sideways the moment the cards landed.
 */
@Composable
fun PosterGridSkeleton(
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(top = 8.dp, bottom = 24.dp, start = 16.dp, end = 16.dp),
) {
    LazyVerticalGrid(
        // F21 (Batch B): the columns stay the shared CatalogGridColumns rule,
        // written out here — a `columns` parameter would pass `columns =
        // columns` and the grid-rule test (a text scan) would read it as a
        // grid that does not draw from the shared rule.
        columns = CatalogGridColumns,
        modifier = modifier.fillMaxSize(),
        contentPadding = contentPadding,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
        userScrollEnabled = false,
    ) {
        items(SKELETON_CELLS) {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                SkeletonBox(aspectRatioValue = CardGeometry.POSTER_ASPECT)
                SkeletonBox(Modifier.height(14.dp))
                SkeletonBox(Modifier.height(10.dp).width(60.dp))
            }
        }
    }
}

/**
 * The loading stand-in for a horizontal rail: the same tile width, the same poster box and the
 * same two text lines as the [PosterCard]s that replace it, so a row that fills in does not
 * change height under the viewer's thumb. [cells] is a fixed handful for the same reason
 * [PosterGridSkeleton] uses [SKELETON_CELLS] — a rail does not know how many tiles fit until it
 * is measured.
 */
@Composable
fun PosterRailSkeleton(
    modifier: Modifier = Modifier,
    cells: Int = 4,
) {
    Row(
        modifier = modifier.padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        repeat(cells) {
            Column(
                modifier = Modifier.width(CardGeometry.RAIL_CARD_WIDTH_DP.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                SkeletonBox(
                    Modifier
                        .fillMaxWidth()
                        .aspectRatio(CardGeometry.POSTER_ASPECT)
                )
                SkeletonBox(Modifier.height(14.dp))
                SkeletonBox(Modifier.height(10.dp).width(60.dp))
            }
        }
    }
}

/**
 * The loading stand-in for the detail header: poster box on the left, the title and metadata
 * lines on the right, and the shape of the action row underneath. Detail used to answer a tap
 * on a tile with one spinner floating in the middle of an empty screen, which told the viewer
 * nothing about what was arriving and left the whole page to be re-laid out when it did.
 */
@Composable
fun DetailSkeleton(modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            SkeletonBox(
                Modifier
                    .width(CardGeometry.DETAIL_POSTER_WIDTH_DP.dp)
                    .aspectRatio(CardGeometry.POSTER_ASPECT)
            )
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                SkeletonBox(Modifier.fillMaxWidth().height(22.dp))
                SkeletonBox(Modifier.width(140.dp).height(14.dp))
                SkeletonBox(Modifier.width(96.dp).height(14.dp))
            }
        }
        Spacer(Modifier.height(16.dp))
        SkeletonBox(Modifier.fillMaxWidth().height(44.dp))
        Spacer(Modifier.height(8.dp))
        SkeletonBox(Modifier.fillMaxWidth().height(14.dp))
        SkeletonBox(Modifier.fillMaxWidth().height(14.dp))
        SkeletonBox(Modifier.width(200.dp).height(14.dp))
    }
}

private const val SKELETON_CELLS = 12

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
    // UI-fix P2-2: one headline for every failure read the same — a dead
    // server, an empty search and a failed page all said "Something went
    // wrong". Callers name the context; the default stays for Home's fatal.
    title: String = "Something went wrong",
    secondaryLabel: String? = null,
    onSecondary: (() -> Unit)? = null,
) {
    EmptyState(
        title = title,
        modifier = modifier,
        message = message,
        icon = {
            // F9 (Batch A): the icon wears the brand tint, not the error red.
            // Every caller of this state is a retryable load failure — a dead
            // server, a failed page — not a destructive mistake, and red says
            // "you did something wrong" where nothing the viewer did was wrong.
            Icon(
                Icons.Default.Info,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
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
            Box(Modifier.width(CardGeometry.RAIL_CARD_WIDTH_DP.dp)) { itemContent(item) }
        }
    }
}

/**
 * Emits [onLoadMore] when the user is within [buffer] rows of the bottom of a grid.
 * Cancelled automatically with the composition.
 *
 * The trigger arms on the viewer's own advance into the bottom window, once per depth:
 * it never re-arms on a total-items change alone. A load-more footer (or an inline
 * failure row) toggling changes `totalItemsCount` without any new cells arriving —
 * and since a de-duplicated page can legitimately add zero visible cells, keying the
 * re-arm on the total would walk the remaining catalog one request at a time while
 * the viewer stands still at the bottom.
 */
@Composable
fun rememberGridEndlessPaging(
    gridState: LazyGridState,
    buffer: Int = 4,
    onLoadMore: () -> Unit,
) {
    val total = gridState.layoutInfo.totalItemsCount
    val lastVisible = gridState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
    var lastTriggerAt by remember { mutableIntStateOf(-1) }
    LaunchedEffect(total, lastVisible) {
        if (total > 0 && lastVisible >= total - buffer && lastVisible > lastTriggerAt) {
            lastTriggerAt = total - 1
            onLoadMore()
        }
    }
}

/** A small text button used as a section "See all" affordance. */
@Composable
fun SeeAllButton(
    onClick: () -> Unit,
    label: String = "See all",
    /**
     * The spoken name. Every Home rail renders one of these, so the bare
     * "See all" repeats once per rail and a screen reader cannot tell the
     * Movies link from the Series one (Robo run 6). Callers pass their
     * section — "See all Movies" — and the button speaks that; the painted
     * text stays the short "See all". Defaults to the label, so a lone
     * button still speaks its own words. The button carries the name (the
     * SwitchRow pattern) and the painted text is silent, so it is heard
     * exactly once.
     */
    contentDescription: String = label,
) {
    Button(
        onClick = onClick,
        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.primary),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
        // E-T5: the button was 40dp tall. 48dp is the touch-target floor.
        modifier = Modifier.heightIn(min = 48.dp).semantics { this.contentDescription = contentDescription },
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clearAndSetSemantics { })
    }
}
