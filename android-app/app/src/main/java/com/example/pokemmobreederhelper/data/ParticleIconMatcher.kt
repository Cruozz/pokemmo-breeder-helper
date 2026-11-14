package com.example.pokemmobreederhelper.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import com.example.pokemmobreederhelper.R
import kotlin.math.*

/** Matches only the icon band of the detail panel, on the OCR worker thread. */
internal class ParticleIconMatcher(context: Context) {
  private val templates = ParticleCatalog.entries(context)
  private val images = run {
    val atlas=BitmapFactory.decodeResource(context.resources,R.drawable.particle_atlas,BitmapFactory.Options().apply { inScaled=false })
    try { templates.associate { template ->
      val data=IntArray(24*24)
      atlas.getPixels(data,0,24,template.iconIndex%7*24,template.iconIndex/7*24,24,24)
      template.id to data
    } } finally { atlas.recycle() }
  }
  fun recognize(bitmap: Bitmap, lines: List<CaptureLine>): String {
    val name = CapturePanelGeometry.levelLine(lines) ?: return ""
    val b = CapturePanelGeometry.box(name); val h = b.height().coerceAtLeast(8)
    val roi = Rect(b.right-h, b.top-(h*4.5f).toInt(), b.right+h*5, b.bottom+h/2)
    if (!roi.intersect(0,0,bitmap.width,bitmap.height)) return ""
    val width = roi.width(); val height = roi.height()
    val pixels = IntArray(width*height)
    bitmap.getPixels(pixels,0,width,roi.left,roi.top,width,height)
    if (pixels.none { it != pixels[0] }) return ""
    fun error(points: List<IntArray>, x: Int, y: Int, size: Int, stride: Int = 1, bound: Double = Double.POSITIVE_INFINITY): Double {
      var sum = 0.0; var count = 0
      for (i in points.indices step stride) {
        val p=points[i]; val px=x+((p[0]+.5f)*size/24).toInt(); val py=y+((p[1]+.5f)*size/24).toInt()
        if(px !in 0 until width || py !in 0 until height) return Double.POSITIVE_INFINITY
        val color=pixels[py*width+px]
        val dr=((color shr 16) and 255)-p[2]; val dg=((color shr 8) and 255)-p[3]; val db=(color and 255)-p[4]
        sum+=dr*dr+dg*dg+db*db; count++
        if(sum>bound*((points.size+stride-1)/stride)*3) return Double.POSITIVE_INFINITY
      }
      return sum/(count*3).coerceAtLeast(1)
    }
    val scores=templates.map { template ->
      var best=Double.POSITIVE_INFINITY; var bx=0; var by=0; var bs=24
      // Anchor on a distinctive opaque color, rather than skipping pixels on
      // a coarse grid (which loses thin 2x sprites between grid positions).
      val meanR=pixels.sumOf { ((it shr 16) and 255).toLong() }.toDouble()/pixels.size
      val meanG=pixels.sumOf { ((it shr 8) and 255).toLong() }.toDouble()/pixels.size
      val meanB=pixels.sumOf { (it and 255).toLong() }.toDouble()/pixels.size
      fun linearPoints(size: Int): List<IntArray> {
        val original=images.getValue(template.id)
        return template.samples.map { p ->
          val ox=((p[0]+.5f)*size/24).toInt();val oy=((p[1]+.5f)*size/24).toInt()
          val sx=(ox+.5)*24/size-.5;val sy=(oy+.5)*24/size-.5
          val lx=floor(sx).toInt();val ly=floor(sy).toInt();val fx=sx-lx;val fy=sy-ly
          var r=0.0;var g=0.0;var b=0.0;var alpha=0.0
          for(dy in 0..1)for(dx in 0..1) {
            val c=original[(ly+dy).coerceIn(0,23)*24+(lx+dx).coerceIn(0,23)]
            val weight=(if(dx==0)1-fx else fx)*(if(dy==0)1-fy else fy)
            val a=((c ushr 24) and 255)/255.0*weight
            alpha+=a;r+=((c shr 16) and 255)*a;g+=((c shr 8) and 255)*a;b+=(c and 255)*a
          }
          intArrayOf(p[0],p[1],(r+meanR*(1-alpha)).roundToInt(),(g+meanG*(1-alpha)).roundToInt(),(b+meanB*(1-alpha)).roundToInt())
        }
      }
      val anchor=template.samples.maxBy { (it[2]-meanR).pow(2)+(it[3]-meanG).pow(2)+(it[4]-meanB).pow(2) }
      val positions=pixels.indices.filter { i ->
        val color=pixels[i];val dr=((color shr 16) and 255)-anchor[2]
        val dg=((color shr 8) and 255)-anchor[3];val db=(color and 255)-anchor[4]
        dr*dr+dg*dg+db*db<95*95*3
      }
      val sizes=(h.coerceAtLeast(12)..minOf(h*4,112,minOf(width,height))).toList()+listOf(24)
      for(size in sizes.distinct()) {
        if(size>minOf(width,height))continue
        val linear=linearPoints(size)
        val dx=((anchor[0]+.5f)*size/24).toInt();val dy=((anchor[1]+.5f)*size/24).toInt()
        for(position in positions) {
          val x=position%width-dx;val y=position/width-dy
          if(x<0 || y<0 || x+size>width || y+size>height)continue
          val value=min(error(template.samples,x,y,size,3,best),error(linear,x,y,size,3,best))
          if(value<best) { best=value;bx=x;by=y;bs=size }
        }
        if(best==0.0)break
      }
      var refined=Double.POSITIVE_INFINITY
      val original=images.getValue(template.id)
      val emptyPoints=(2..20 step 2).flatMap { py -> (2..20 step 2).mapNotNull { px ->
        if((0..1).all { dy -> (0..1).all { dx -> original[(py+dy)*24+px+dx] ushr 24 == 0 } }) px to py else null
      } }
      fun backgroundPenalty(x: Int,y: Int,size: Int): Double {
        val colors=emptyPoints.map { (px,py) -> pixels[(y+((py+.5f)*size/24).toInt())*width+x+((px+.5f)*size/24).toInt()] }
        val observed=colors+template.samples.filterIndexed { index,_ -> index%8==0 }.map { p ->
          pixels[(y+((p[1]+.5f)*size/24).toInt())*width+x+((p[0]+.5f)*size/24).toInt()]
        }
        if(listOf(0,8,16).maxOf { shift -> observed.maxOf { (it shr shift) and 255 }-observed.minOf { (it shr shift) and 255 } }<20)
          return Double.POSITIVE_INFINITY
        if(colors.size<6)return 0.0
        val r=colors.map { (it shr 16) and 255 }.sorted()[colors.size/2]
        val g=colors.map { (it shr 8) and 255 }.sorted()[colors.size/2]
        val b=colors.map { it and 255 }.sorted()[colors.size/2]
        return colors.sumOf { color ->
          val dr=((color shr 16) and 255)-r;val dg=((color shr 8) and 255)-g;val db=(color and 255)-b
          (dr*dr+dg*dg+db*db).toDouble()
        }/(colors.size*3)
      }
      if(best<70.0*70) for(size in (bs-2).coerceAtLeast(8)..bs+2) {
        val linear=linearPoints(size)
        for(y in (by-2).coerceAtLeast(0)..minOf(by+2,height-size))
          for(x in (bx-2).coerceAtLeast(0)..minOf(bx+2,width-size))
            refined=min(refined,min(error(template.samples,x,y,size,bound=refined),error(linear,x,y,size,bound=refined))+3*backgroundPenalty(x,y,size))
      }
      sqrt(refined) to template.id
    }.sortedBy { it.first }
    return when {
      scores[0].first<=34 && scores[1].first-scores[0].first>=4 -> scores[0].second
      scores[0].first<43 -> "unknown"
      else -> ""
    }
  }
}
