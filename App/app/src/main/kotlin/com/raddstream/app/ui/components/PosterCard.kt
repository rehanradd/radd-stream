package com.raddstream.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.theme.AccentGold
import com.raddstream.app.ui.theme.OnBackground
import com.raddstream.app.ui.theme.OnSurfaceMuted
import com.raddstream.app.ui.theme.SurfaceDark
import com.raddstream.app.ui.theme.SurfaceVariantDark

@Composable
fun PosterCard(
    post: Post,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
) {
    val cardModifier = if (onClick != null) {
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
    } else {
        modifier.fillMaxWidth()
    }

    Card(
        modifier = cardModifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceDark),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(0.68f)
                    .clip(RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp))
                    .background(SurfaceVariantDark),
                contentAlignment = Alignment.Center,
            ) {
                val posterUrl = post.posterUrl?.takeIf(String::isNotBlank)
                if (posterUrl == null) {
                    Text("No poster", color = OnSurfaceMuted, style = MaterialTheme.typography.labelMedium)
                } else {
                    AsyncImage(
                        model = posterUrl,
                        contentDescription = "${post.title} poster",
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Crop,
                    )
                }
            }
            Column(
                modifier = Modifier.padding(start = 10.dp, end = 10.dp, bottom = 11.dp),
                verticalArrangement = Arrangement.spacedBy(3.dp),
            ) {
                Text(
                    text = post.cleanTitle?.takeIf(String::isNotBlank) ?: post.title,
                    color = OnBackground,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                val details = listOfNotNull(
                    post.year?.takeIf(String::isNotBlank),
                    post.contentType?.takeIf(String::isNotBlank)?.replaceFirstChar { it.uppercase() },
                ).joinToString(" · ")
                if (details.isNotEmpty()) {
                    Text(details, color = OnSurfaceMuted, style = MaterialTheme.typography.labelSmall)
                }
                post.imdbRating?.takeIf(String::isNotBlank)?.let { rating ->
                    Text("★ $rating", color = AccentGold, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}
