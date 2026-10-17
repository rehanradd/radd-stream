package com.raddstream.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val RaddColorScheme = darkColorScheme(
    primary          = AccentPrimary,
    secondary        = AccentSecondary,
    tertiary         = AccentGold,
    background       = BackgroundDark,
    surface          = SurfaceDark,
    surfaceVariant   = SurfaceVariantDark,
    onBackground     = OnBackground,
    onSurface        = OnSurface,
    onPrimary        = OnBackground,
    onSecondary      = OnBackground,
    error            = AccentRed,
)

@Composable
fun RaddStreamTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = RaddColorScheme,
        typography  = RaddTypography,
        content     = content,
    )
}
