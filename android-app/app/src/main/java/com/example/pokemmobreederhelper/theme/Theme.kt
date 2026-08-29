package com.example.pokemmobreederhelper.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColorScheme =
  darkColorScheme(
    primary = SlatePrimaryDark,
    secondary = StockGreenDark,
    secondaryContainer = StockGreenContainerDark,
    onSecondaryContainer = OnStockGreenContainerDark,
    tertiary = WarningOrangeDark,
    tertiaryContainer = WarningContainerDark,
    onTertiaryContainer = OnWarningContainerDark,
    background = DarkBackground,
    surface = DarkSurface,
    onPrimary = DarkBackground,
    onSecondary = DarkBackground,
    onBackground = Color(0xFFF8FAFC),
    onSurface = Color(0xFFF8FAFC),
  )

private val LightColorScheme =
  lightColorScheme(
    primary = SlatePrimary,
    secondary = StockGreen,
    secondaryContainer = StockGreenContainer,
    onSecondaryContainer = OnStockGreenContainer,
    tertiary = WarningOrange,
    tertiaryContainer = WarningContainer,
    onTertiaryContainer = OnWarningContainer,
    background = AppBackground,
    surface = AppSurface,
    onPrimary = Color.White,
    onSecondary = Color.White,
    onBackground = AppInk,
    onSurface = AppInk,
    outline = AppBorder,
  )

@Composable
fun PokeMMOBreederHelperTheme(
  darkTheme: Boolean = isSystemInDarkTheme(),
  content: @Composable () -> Unit,
) {
  val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme

  MaterialTheme(colorScheme = colorScheme, typography = Typography, content = content)
}
