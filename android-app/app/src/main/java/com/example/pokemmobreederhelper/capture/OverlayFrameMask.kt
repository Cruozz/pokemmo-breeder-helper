package com.example.pokemmobreederhelper.capture

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Point
import android.graphics.Rect

/** Match nearby background instead of inserting a high-contrast block into OCR input. */
internal object OverlayFrameMask {
  fun apply(bitmap: Bitmap, bounds: List<Rect>) {
    val canvas=Canvas(bitmap)
    val colors=bounds.map { rect ->
      val points=listOf(
        Point(rect.left-12,rect.top-12),Point(rect.right+12,rect.top-12),
        Point(rect.left-12,rect.bottom+12),Point(rect.right+12,rect.bottom+12),
        Point(rect.centerX(),rect.top-12),Point(rect.centerX(),rect.bottom+12),
        Point(rect.left-12,rect.centerY()),Point(rect.right+12,rect.centerY()))
      val pixels=points.filter { it.x in 0 until bitmap.width && it.y in 0 until bitmap.height &&
        bounds.none { area -> area.contains(it.x,it.y) } }.map { bitmap.getPixel(it.x,it.y) }
        .sortedBy { Color.red(it)*299+Color.green(it)*587+Color.blue(it)*114 }
      pixels.getOrNull(pixels.size/2) ?: Color.BLACK
    }
    bounds.forEachIndexed { index,rect -> canvas.drawRect(rect,Paint().apply { color=colors[index] }) }
  }
}
