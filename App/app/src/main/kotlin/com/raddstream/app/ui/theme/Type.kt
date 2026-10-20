package com.raddstream.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val RaddTypography = Typography(
    displayLarge   = TextStyle(fontSize = 32.sp, fontWeight = FontWeight.Bold,     letterSpacing = (-0.5).sp),
    displayMedium  = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.Bold),
    headlineLarge  = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.SemiBold),
    headlineMedium = TextStyle(fontSize = 18.sp, fontWeight = FontWeight.SemiBold),
    titleLarge     = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Medium),
    titleMedium    = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium),
    bodyLarge      = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Normal,   lineHeight = 24.sp),
    bodyMedium     = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Normal,   lineHeight = 20.sp),
    bodySmall      = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Normal),
    labelLarge     = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium,   letterSpacing = 0.1.sp),
    labelMedium    = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium,   letterSpacing = 0.5.sp),
    labelSmall     = TextStyle(fontSize = 10.sp, fontWeight = FontWeight.Medium,   letterSpacing = 0.5.sp),
)
