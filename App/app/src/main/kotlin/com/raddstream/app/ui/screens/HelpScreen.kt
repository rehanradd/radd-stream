package com.raddstream.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * One short static Help screen: how to watch, download, and use VIP and coins.
 *
 * Every sentence is a fact the app already proves elsewhere — the free 720p cap, the
 * direct downloads, the VIP prices, the coin sources — so this screen never has to be
 * re-checked against the server. It is static on purpose: no ViewModel, no network call,
 * nothing that can fail while a viewer is stuck. The one thing it cannot answer itself
 * is a person's own problem, so the last section sends them to the Contact form in
 * Settings rather than inventing an address.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HelpScreen(
    onBackClick: () -> Unit,
) {
    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = { Text("Help") },
                navigationIcon = {
                    IconButton(onClick = onBackClick) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            HelpSection(
                title = "Watch",
                body = "Tap a title, then Play. Free viewers play up to 720p. 1080p and 4K need VIP. " +
                    "A title keeps playing where you left it — find it again under Continue watching on Home.",
            )
            HelpSection(
                title = "Download",
                body = "Tap Download on a title to save it on this phone and watch it offline. " +
                    "Downloads are direct files — nothing extra is installed.",
            )
            HelpSection(
                title = "VIP and coins",
                body = "VIP is PKR 200 a month or PKR 1,500 a year, paid by JazzCash, EasyPaisa or Raast. " +
                    "Coins come from checking in every day, sharing a title, and finishing one. " +
                    "Coins buy a 24-hour VIP pass, a direct download, a player theme, or a movie request — " +
                    "see the VIP screen for the prices.",
            )
            HelpSection(
                title = "Need more help?",
                body = "Use the Contact form in Settings — write to us and the team will answer. " +
                    "To ask for a title to be taken down, use the same form.",
            )
        }
    }
}

/** One headed paragraph: a title, then the plain answer under it. */
@Composable
private fun HelpSection(
    title: String,
    body: String,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
