package com.example.pokemmobreederhelper.data

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect
import kotlin.math.*

/** Locate detail fields from OCR anchors, never from a fixed phone resolution. */
internal object CapturePanelGeometry {
  private val level = Regex("""(?i)\bL(?:[vw][.,，·]?|[.,，·])\s*\d+""")
  fun box(line: CaptureLine) = Rect(line.box.minOf { it[0] },line.box.minOf { it[1] },
    line.box.maxOf { it[0] },line.box.maxOf { it[1] })
  private fun compact(text: String) = text.filterNot { it.isWhitespace() }
  fun levelLine(lines: List<CaptureLine>) = lines.firstOrNull { level.containsMatchIn(it.text) }

  fun gender(bitmap: Bitmap, lines: List<CaptureLine>): String {
    val name = levelLine(lines) ?: return ""
    val b = box(name); val h = b.height().coerceAtLeast(8)
    val roi = Rect(max(b.left + h*2,b.right-(h*1.6f).toInt()),b.top-h/4,b.right+h*2,b.bottom+h/4)
    if (!roi.intersect(0,0,bitmap.width,bitmap.height)) return ""
    val pixels = IntArray(roi.width()*roi.height())
    bitmap.getPixels(pixels,0,roi.width(),roi.left,roi.top,roi.width(),roi.height())
    fun color(p: Int): Int {
      val r=Color.red(p);val g=Color.green(p);val blue=Color.blue(p)
      return if(r>=120 && blue>=80 && r-g>=35 && blue-g>=20) 1
        else if(blue>=120 && blue-r>=25 && g-r>=10) 2 else 0
    }
    val kinds=IntArray(pixels.size) { color(pixels[it]) };val queue=IntArray(pixels.size)
    val found=mutableSetOf<String>()
    for (start in kinds.indices) {
      val kind=kinds[start];if(kind==0)continue
      var head=0;var tail=1;queue[0]=start;kinds[start]=0
      var left=roi.width();var right=0;var top=roi.height();var bottom=0
      while(head<tail) {
        val p=queue[head++];val x=p%roi.width();val y=p/roi.width()
        left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)
        for(dy in -1..1)for(dx in -1..1) {
          val nx=x+dx;val ny=y+dy
          if(nx !in 0 until roi.width() || ny !in 0 until roi.height())continue
          val n=ny*roi.width()+nx
          if(kinds[n]==kind) { kinds[n]=0;queue[tail++]=n }
        }
      }
      val w=right-left+1;val ch=bottom-top+1;val density=tail.toFloat()/(w*ch)
      // A tall, small symbol on the name row; reject badges, diamonds and sprite fragments.
      if(w>=h*.18f && w<=h*.95f && ch>=h*.60f && ch<=h*1.45f &&
        ch>=w*1.08f && density in .12f.. .85f && tail>=max(8f,h*h*.025f))
        found.add(if(kind==1)"F" else "M")
    }
    return found.singleOrNull().orEmpty()
  }

  fun movesRegion(lines: List<CaptureLine>, elements: List<CaptureLine>, width: Int, height: Int): Rect? {
    val marker=(elements+lines).firstOrNull { compact(it.text).startsWith("标记") || compact(it.text).startsWith("標記") } ?: return null
    val iv=(elements+lines).firstOrNull { item -> listOf("个体值","個體值","个休值","個休值","个体直","個體直").any { compact(item.text).startsWith(it) } } ?: return null
    val ib=box(iv);val mb=box(marker);val h=ib.height().coerceAtLeast(8)
    val value=(elements+lines).filter {
      it.text.count { c -> c=='/' || c=='／' }>=3 &&
        abs(box(it).centerY()-ib.centerY())<=h*.8f && box(it).left>ib.left+h
    }.minByOrNull { box(it).left } ?: return null
    val column=(elements+lines).filter {
      it.text.count { c -> c=='/' || c=='／' }>=3 &&
        box(it).centerY() in (ib.top-h*4)..mb.top && box(it).left>ib.left+h && box(it).left<ib.left+h*12
    }.minOfOrNull { box(it).left } ?: box(value).left
    val left=column-(h*.35f).roundToInt()
    val rect=Rect(left,mb.bottom+(h*.15f).toInt(),left+h*11,mb.bottom+(h*8.5f).toInt())
    return rect.takeIf { it.intersect(0,0,width,height) && it.width()>h*2 && it.height()>h }
  }
}
