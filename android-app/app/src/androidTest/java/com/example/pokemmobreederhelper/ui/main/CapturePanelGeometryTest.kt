package com.example.pokemmobreederhelper.ui.main

import android.graphics.*
import com.example.pokemmobreederhelper.data.*
import org.junit.Assert.*
import org.junit.Test

class CapturePanelGeometryTest {
  private fun row()=CaptureLine("Lv.50 伊布",listOf(listOf(40,200),listOf(300,200),listOf(300,226),listOf(40,226)))
  private fun icon(c:Canvas,x:Float,female:Boolean) {
    val p=Paint(Paint.ANTI_ALIAS_FLAG).apply { color=if(female)Color.rgb(232,94,201) else Color.rgb(87,191,242);strokeWidth=3f;style=Paint.Style.STROKE }
    c.drawOval(x,203f,x+11,217f,p)
    if(female) { c.drawLine(x+5.5f,217f,x+5.5f,229f,p);c.drawLine(x,224f,x+11,224f,p) }
    else { c.drawLine(x+9,205f,x+16,196f,p);c.drawLine(x+9,196f,x+16,196f,p);c.drawLine(x+16,196f,x+16,203f,p) }
  }
  @Test fun blueAndPinkSymbolsAreReadAtDifferentScales() {
    for(female in listOf(false,true))for(scale in listOf(1f,.75f,.5f)) {
      val image=Bitmap.createBitmap(500,500,Bitmap.Config.ARGB_8888)
      val canvas=Canvas(image);canvas.drawColor(Color.rgb(76,86,94));icon(canvas,314f,female)
      val small=Bitmap.createScaledBitmap(image,(500*scale).toInt(),(500*scale).toInt(),true)
      val anchor=row().let { it.copy(box=it.box.map { p -> p.map { n -> (n*scale).toInt() } }) }
      assertEquals("scale="+scale,if(female)"F" else "M",CapturePanelGeometry.gender(small,listOf(anchor)))
      if(small!==image)small.recycle();image.recycle()
    }
  }
  @Test fun badgesDiamondsAndUnanchoredColorsCannotAssignGender() {
    val image=Bitmap.createBitmap(500,500,Bitmap.Config.ARGB_8888);val c=Canvas(image)
    c.drawColor(Color.rgb(76,86,94))
    c.drawRect(280f,50f,360f,90f,Paint().apply { color=Color.MAGENTA })
    val diamond=Path().apply { moveTo(321f,203f);lineTo(328f,210f);lineTo(321f,217f);lineTo(314f,210f);close() }
    c.drawPath(diamond,Paint().apply { color=Color.CYAN })
    assertEquals("",CapturePanelGeometry.gender(image,listOf(row())))
    icon(c,342f,true)
    assertEquals("",CapturePanelGeometry.gender(image,emptyList()))
    image.recycle()
  }
  @Test fun conflictingIconsRemainUnknown() {
    val image=Bitmap.createBitmap(500,500,Bitmap.Config.ARGB_8888);val c=Canvas(image)
    c.drawColor(Color.rgb(76,86,94));icon(c,309f,false);icon(c,337f,true)
    assertEquals("",CapturePanelGeometry.gender(image,listOf(row())));image.recycle()
  }
}
