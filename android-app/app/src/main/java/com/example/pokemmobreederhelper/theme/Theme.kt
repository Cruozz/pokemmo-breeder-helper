package com.example.pokemmobreederhelper.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

private val DarkColorScheme = darkColorScheme(
  primary = Color(0xFFFF9CA4), onPrimary = Color(0xFF660D26),
  primaryContainer = Color(0xFF542033), onPrimaryContainer = Color(0xFFFFE5E7),
  secondary = Color(0xFF68DFD0), onSecondary = Color(0xFF003C36),
  secondaryContainer = Color(0xFF074D49), onSecondaryContainer = Color(0xFFAFF9EE),
  tertiary = Color(0xFFFFD177), onTertiary = Color(0xFF422C00),
  tertiaryContainer = Color(0xFF58421A), onTertiaryContainer = Color(0xFFFFE5AF),
  background = Color(0xFF101923), onBackground = Color(0xFFEFF5FD),
  surface = Color(0xFF182533), onSurface = Color(0xFFEFF5FD),
  surfaceContainerLow = Color(0xFF14202E), surfaceContainer = Color(0xFF1A2B3C),
  surfaceContainerHigh = Color(0xFF23374A), surfaceContainerHighest = Color(0xFF2C4054),
  surfaceVariant = Color(0xFF2C4054), onSurfaceVariant = Color(0xFFBACCDD),
  outline = Color(0xFF8296AA), outlineVariant = Color(0xFF3C5369),
)
private val LightColorScheme = lightColorScheme(
  primary = Color(0xFFB82446), onPrimary = Color.White,
  primaryContainer = Color(0xFFFFE4E8), onPrimaryContainer = Color(0xFF681329),
  secondary = Color(0xFF006C63), onSecondary = Color.White,
  secondaryContainer = Color(0xFFC4F4E7), onSecondaryContainer = Color(0xFF004B42),
  tertiary = Color(0xFF805200), onTertiary = Color.White,
  tertiaryContainer = Color(0xFFFFE5AC), onTertiaryContainer = Color(0xFF543500),
  background = Color(0xFFF0F4FA), onBackground = Color(0xFF14283C),
  surface = Color.White, onSurface = Color(0xFF14283C),
  surfaceContainerLow = Color(0xFFF7F9FD), surfaceContainer = Color(0xFFEAF0F7),
  surfaceContainerHigh = Color(0xFFE3EAF4), surfaceContainerHighest = Color(0xFFDCE5F1),
  surfaceVariant = Color(0xFFE3EAF4), onSurfaceVariant = Color(0xFF485C70),
  outline = Color(0xFF73859B), outlineVariant = Color(0xFFC1CDDD),
)
@Composable
fun PokeMMOBreederHelperTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
  MaterialTheme(colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme,
    typography = Typography,
    shapes = Shapes(small = RoundedCornerShape(10.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(22.dp)),
    content = content)
}
