package com.example.pokemmobreederhelper.capture

import android.content.Context
import android.content.SharedPreferences
import kotlin.math.roundToInt

internal data class OverlayAppearance(
  val opacity: Float = .95f,
  val fontSp: Float = 10f,
  val autoSize: Boolean = true,
  val widthDp: Int = 264,
  val heightDp: Int = 300,
) {
  fun bounded() = copy(opacity = opacity.coerceIn(.35f, 1f), fontSp = fontSp.coerceIn(8f, 18f),
    widthDp = widthDp.coerceIn(200, 480), heightDp = heightDp.coerceIn(180, 600))
  fun panelWidth(fontScale: Float): Int = if (autoSize)
    (264 * (fontSp / 10f) * fontScale).roundToInt().coerceAtLeast(220) else widthDp
  fun save(context: Context) = preferences(context).edit().putFloat("opacity", opacity)
    .putFloat("font", fontSp).putBoolean("auto-size", autoSize)
    .putInt("width", widthDp).putInt("height", heightDp).apply()
  companion object {
    fun preferences(context: Context): SharedPreferences = context.getSharedPreferences("capture-appearance", Context.MODE_PRIVATE)
    fun load(context: Context): OverlayAppearance = preferences(context).let {
      OverlayAppearance(it.getFloat("opacity", .95f), it.getFloat("font", 10f),
        it.getBoolean("auto-size", true), it.getInt("width", 264), it.getInt("height", 300)).bounded()
    }
  }
}
