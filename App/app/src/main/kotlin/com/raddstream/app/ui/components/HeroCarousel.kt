package com.raddstream.app.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.raddstream.app.brand.Brand
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.WireText
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The banner rail on Home: [HERO_HEIGHT] tall, a rounded card floating on a soft
 * ambient glow, one work at a time, advancing on its own.
 *
 * Layout of one slide, back to front:
 *  - the ambient glow ([HeroAmbientGlow]): two low-alpha radial blooms tinted from the
 *    theme, drifting to a new hue as the active page changes — light spilling into the
 *    inset around the card, which is what gives the banner depth instead of a pasted-on
 *    rectangle;
 *  - the widest artwork the row carries, cropped to fill;
 *  - a vertical scrim that goes from clear at the top to the page background at the
 *    bottom, so the title and buttons stay readable over any poster;
 *  - the title, a year badge and up to [MAX_LANGUAGE_PILLS] language pills;
 *  - a prominent Watch Now button (the slide's own tap target is the same action, so the
 *    whole banner is tappable and the button is the part that says so);
 *  - page dots, which double as the manual affordance — tapping a dot jumps to that slide.
 *
 * WHAT THE HERO PAINTS (App/AGENTS.md §5): `GET /api/v1/posts` projects a
 * `backdrop_urls` column alongside `poster_url` (`Fast_Fetch/viewer.py` `_art_pair()`),
 * and that is the wide TMDB artwork this banner is built for — so the default image is the
 * first backdrop, and the poster is only the fallback for a row that has no backdrop, or a
 * server whose list projection predates the column. The hero never invents a URL from
 * `tmdb_id`: a TMDB image path is not derivable from the id, and guessing one would be a
 * 404 on every tile. [backdropFor] is the seam if that policy ever changes.
 *
 * Auto-advance is motion, so it respects the same system switch as the skeletons
 * ([rememberReduceMotion]): with animations off the banner still paginates by hand, it just
 * never moves on its own, and the glow cuts instead of cross-fading. A drag also gets the
 * pager back immediately — the loop waits for `isScrollInProgress` to clear before it takes
 * the page away again.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun HeroCarousel(
    posts: List<Post>,
    onPostClick: (Int) -> Unit,
    modifier: Modifier = Modifier,
    backdropFor: (Post) -> String? = { it.heroArtUrl },
) {
    if (posts.isEmpty()) return
    val reduceMotion = rememberReduceMotion()
    val pagerState = rememberPagerState(pageCount = { posts.size })
    val scrollScope = rememberCoroutineScope()

    LaunchedEffect(posts.size, reduceMotion) {
        if (posts.size < 2 || reduceMotion) return@LaunchedEffect
        while (true) {
            delay(AUTO_ADVANCE_MS)
            if (pagerState.isScrollInProgress) continue
            val next = (pagerState.currentPage + 1) % posts.size
            pagerState.animateScrollToPage(next)
        }
    }

    Box(modifier.fillMaxWidth().height(HERO_HEIGHT)) {
        HeroAmbientGlow(
            currentPage = pagerState.currentPage,
            modifier = Modifier.fillMaxSize(),
        )

        HorizontalPager(
            state = pagerState,
            modifier = Modifier.fillMaxSize().padding(heroInset),
        ) { page ->
            val post = posts.getOrNull(page) ?: return@HorizontalPager
            HeroSlide(
                post = post,
                backdropUrl = backdropFor(post),
                onClick = { onPostClick(post.id) },
                modifier = Modifier.clip(RoundedCornerShape(HERO_CORNER)),
            )
        }

        if (posts.size > 1) {
            HeroIndicator(
                count = posts.size,
                current = pagerState.currentPage,
                // Scrolling is a suspending pager call, so the dot's click launches it on the
                // composition's scope instead of pretending the tap can wait for it inline.
                onSelect = { index -> scrollScope.launch { pagerState.animateScrollToPage(index) } },
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(end = 16.dp, bottom = 20.dp),
            )
        }
    }
}

/**
 * The banner's own placeholder while the first rail is still in flight. It keeps the real
 * hero's footprint ([HERO_HEIGHT]) so the page does not jump when artwork lands, and a few
 * shimmering bars stand in for the title, badges and Watch Now button.
 */
@Composable
fun HeroSkeleton(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(HERO_HEIGHT)) {
        Box(Modifier.fillMaxSize().padding(heroInset).clip(RoundedCornerShape(HERO_CORNER))) {
            ShimmerBox(Modifier.fillMaxSize())
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
                    .padding(bottom = 20.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                ShimmerBox(
                    Modifier.fillMaxWidth(0.55f).height(26.dp),
                    shape = RoundedCornerShape(8.dp),
                )
                ShimmerBox(
                    Modifier.width(120.dp).height(16.dp),
                    shape = RoundedCornerShape(8.dp),
                )
                ShimmerBox(
                    Modifier.width(150.dp).height(52.dp),
                    shape = RoundedCornerShape(24.dp),
                )
            }
        }
    }
}

/**
 * Two soft radial blooms behind the banner, tinted from the theme's accent trio and
 * cross-fading to the next hue as the pager moves. The card is inset by [heroInset], so
 * this light spills out around it — depth without a single extra image.
 */
@Composable
private fun HeroAmbientGlow(currentPage: Int, modifier: Modifier = Modifier) {
    val scheme = MaterialTheme.colorScheme
    val accents = remember(scheme.primary, scheme.secondary, scheme.tertiary) {
        listOf(scheme.primary, scheme.secondary, scheme.tertiary)
    }
    val reduceMotion = rememberReduceMotion()
    val fade = if (reduceMotion) snap<Color>() else tween<Color>(durationMillis = 900)
    val leading by animateColorAsState(accents[currentPage % accents.size], fade, label = "heroGlowLeading")
    val trailing by animateColorAsState(accents[(currentPage + 1) % accents.size], fade, label = "heroGlowTrailing")

    Box(
        modifier.drawBehind {
            drawRect(
                Brush.radialGradient(
                    colors = listOf(leading.copy(alpha = 0.34f), leading.copy(alpha = 0f)),
                    center = Offset(size.width * 0.30f, size.height * 0.20f),
                    radius = size.maxDimension * 0.72f,
                ),
            )
            drawRect(
                Brush.radialGradient(
                    colors = listOf(trailing.copy(alpha = 0.24f), trailing.copy(alpha = 0f)),
                    center = Offset(size.width * 0.84f, size.height * 0.66f),
                    radius = size.maxDimension * 0.58f,
                ),
            )
        },
    )
}

@Composable
private fun HeroSlide(
    post: Post,
    backdropUrl: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val title = post.displayTitle
    val languages = remember(post.language) { heroLanguagePills(post.language) }
    // The slide merges its children, so TalkBack reads this line and then the Watch Now button
    // inside it. Saying "watch now" here as well would announce the same action twice.
    val a11y = buildString {
        append(title)
        post.yearLabel?.let { append(", ").append(it) }
        if (languages.isNotEmpty()) append(", languages ").append(languages.joinToString())
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .semantics { contentDescription = a11y }
            .clickable(onClick = onClick),
    ) {
        // 1 — artwork, or the branded fallback card when there is nothing to paint.
        if (backdropUrl.isNullOrBlank()) {
            ImageFallbackCard()
        } else {
            CatalogImage(
                url = backdropUrl,
                contentDescription = null, // the merged description above already tells it
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                fallbackLabel = title.take(2).uppercase(),
            )
        }

        // 2 — vertical scrim: clear at the crest, page background under the text.
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        0f to MaterialTheme.colorScheme.background.copy(alpha = 0f),
                        0.45f to MaterialTheme.colorScheme.background.copy(alpha = 0.15f),
                        1f to MaterialTheme.colorScheme.background.copy(alpha = 0.92f),
                    )
                ),
        )

        // 3 — the words.
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onBackground,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )

            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                post.yearLabel?.let { HeroBadge(it) }
                post.typeLabel?.let { HeroBadge(it) }
                languages.forEach { HeroBadge(it, subdued = true) }
            }

            Button(
                onClick = onClick,
                shape = RoundedCornerShape(24.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = MaterialTheme.colorScheme.onPrimary,
                ),
                modifier = Modifier.height(52.dp),
            ) {
                Icon(
                    imageVector = Icons.Default.PlayArrow,
                    contentDescription = null,
                    modifier = Modifier.size(22.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(Brand.copy("hero_watch_now", "Watch Now"), fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** One small pill: the year badge and the language badges share this exact shape. */
@Composable
private fun HeroBadge(text: String, subdued: Boolean = false) {
    val scheme = MaterialTheme.colorScheme
    Box(
        Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (subdued) scheme.scrim.copy(alpha = 0.35f) else scheme.surface.copy(alpha = 0.55f)
            )
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (subdued) scheme.onBackground.copy(alpha = 0.85f) else scheme.onBackground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * Page dots that are also buttons: the active one stretches into a short bar, so the state
 * reads at a glance, and each dot jumps the pager to its slide.
 *
 * The painted dot is 7dp tall and used to be the only thing a finger could aim at. Each one now
 * sits inside the [DOT_TOUCH_WIDTH] by [DOT_TOUCH_HEIGHT] box — 44dp of vertical room, which the
 * artwork has to spare, and 24dp of width, the WCAG 2.2 AA minimum. Wider is not better here:
 * six of these banners at a 44dp square would run into the Watch Now button, and a dot whose hit
 * box covers another control does not help anyone. Each dot also says what it is in words and
 * carries a `selected` state, because the visual stretch was the only thing that used to show
 * which slide is up.
 */
@Composable
private fun HeroIndicator(
    count: Int,
    current: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(count) { index ->
            val active = index == current
            Box(
                modifier = Modifier
                    .size(width = DOT_TOUCH_WIDTH, height = DOT_TOUCH_HEIGHT)
                    .clickable(onClickLabel = "Show banner ${index + 1} of $count") { onSelect(index) }
                    .semantics {
                        contentDescription = "Banner ${index + 1} of $count"
                        selected = active
                    },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier
                        .size(width = if (active) 18.dp else 7.dp, height = 7.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(scheme.onBackground.copy(alpha = if (active) 0.95f else 0.45f)),
                )
            }
        }
    }
}

/**
 * Language pills, trimmed to what a banner can show. `posts.language` is free TEXT —
 * "Hindi + English + Japanese", a bare "English", sometimes nothing — so [WireText.listOf]
 * is the only sanctioned reader, and a single long value is cut rather than allowed to
 * push the title off the slide.
 */
internal fun heroLanguagePills(raw: String?, max: Int = MAX_LANGUAGE_PILLS): List<String> =
    WireText.listOf(raw)
        .map { it.trim() }
        .filter { it.isNotEmpty() && it.length <= MAX_PILL_LENGTH }
        .distinct()
        .take(max)

private const val MAX_LANGUAGE_PILLS = 3
private const val MAX_PILL_LENGTH = 18
private const val AUTO_ADVANCE_MS = 5_000L

/**
 * The page dot's hit box: 44dp of height is room the artwork can spare, and 24dp of width is
 * the WCAG 2.2 AA minimum. The painted dot inside it stays 7dp.
 */
private val DOT_TOUCH_HEIGHT: Dp = 44.dp
private val DOT_TOUCH_WIDTH: Dp = 24.dp

/**
 * The banner's height. A rounded, inset hero wants ~16:9 of a phone screen plus the text
 * block; 400dp keeps the first rail's posters peeking over the fold, so the page still
 * reads as a catalog and not as a single poster.
 */
private val HERO_HEIGHT: Dp = 400.dp

/** The glow shows through this gutter — enough to read, not enough to look like a border. */
private val heroInset = PaddingValues(start = 14.dp, end = 14.dp, top = 10.dp, bottom = 10.dp)

private val HERO_CORNER: Dp = 24.dp
