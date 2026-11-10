package com.example.pokemmobreederhelper.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

private val LightColorScheme = lightColorScheme(
  primary = Color(0xFF4F46E5), onPrimary = Color.White,
  primaryContainer = Color(0xFFE8EBFF), onPrimaryContainer = Color(0xFF292564),
  secondary = Color(0xFF475E91), onSecondary = Color.White,
  secondaryContainer = Color(0xFFE3ECFC), onSecondaryContainer = Color(0xFF233957),
  tertiary = Color(0xFF7952A2), onTertiary = Color.White,
  tertiaryContainer = Color(0xFFF0E6FC), onTertiaryContainer = Color(0xFF4C2C6E),
  background = Color(0xFFF5F7FD), onBackground = Color(0xFF24324A),
  surface = Color.White, onSurface = Color(0xFF24324A),
  surfaceContainerLow = Color(0xFFF8F9FF), surfaceContainer = Color(0xFFF0F2FC),
  surfaceContainerHigh = Color(0xFFE9EDF8), surfaceContainerHighest = Color(0xFFE1E6F4),
  surfaceVariant = Color(0xFFE9EDF8), onSurfaceVariant = Color(0xFF505E77),
  outline = Color(0xFF74819B), outlineVariant = Color(0xFFD2DAED),
)
private val DarkColorScheme = darkColorScheme(
  primary = Color(0xFFC4C0FF), onPrimary = Color(0xFF292564),
  primaryContainer = Color(0xFF393477), onPrimaryContainer = Color(0xFFE8EBFF),
  secondary = Color(0xFFBCCDF0), onSecondary = Color(0xFF233957),
  secondaryContainer = Color(0xFF33486A), onSecondaryContainer = Color(0xFFE3ECFC),
  tertiary = Color(0xFFE0B9F3), onTertiary = Color(0xFF4C2C6E),
  background = Color(0xFF1D2438), onBackground = Color(0xFFF0F2FC),
  surface = Color(0xFF252D43), onSurface = Color(0xFFF0F2FC),
  onSurfaceVariant = Color(0xFFCBD0E5), outlineVariant = Color(0xFF47516C),
)
/** The default stays light even on a dark phone, matching the floating controls. */
@Composable
fun PokeMMOBreederHelperTheme(darkTheme: Boolean = false, content: @Composable () -> Unit) {
  MaterialTheme(colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme,
    typography = Typography,
    shapes = Shapes(small = RoundedCornerShape(10.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(22.dp)),
    content = content)
}
