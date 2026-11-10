package com.example.pokemmobreederhelper.ui.main

import android.graphics.*
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.data.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

/** Entirely synthetic page; no user screenshot or inventory is shipped. */
class WarehousePanelOcrTest {
  @Test fun coloredIconAndMoveColumnAreRecognizedTogether()=runBlocking {
    val image=Bitmap.createBitmap(560,780,Bitmap.Config.ARGB_8888)
    val c=Canvas(image);c.drawColor(Color.rgb(70,80,90))
    val p=Paint(Paint.ANTI_ALIAS_FLAG).apply { color=Color.WHITE;textSize=28f;typeface=Typeface.create("sans-serif",Typeface.BOLD) }
    c.drawText("Lv.50 伊布",70f,100f,p)
    p.color=Color.rgb(232,94,201);p.style=Paint.Style.STROKE;p.strokeWidth=4f
    c.drawOval(250f,76f,265f,94f,p);c.drawLine(257.5f,94f,257.5f,106f,p);c.drawLine(251f,101f,264f,101f,p)
    p.style=Paint.Style.FILL;p.color=Color.WHITE
    val rows=listOf("能力值:" to "121/97/66/71/83/99","个体值:" to "7/31/12/9/31/18",
      "努力值:" to "0/0/0/0/0/0","性格:" to "胆小(Timid)","特性:" to "适应力","标记:" to "")
    rows.forEachIndexed { n,row -> c.drawText(row.first,35f,170f+n*58,p);c.drawText(row.second,190f,170f+n*58,p) }
    val moves=listOf("电" to "十万伏特","一般" to "守住","超能力" to "光墙","一般" to "诱惑")
    moves.forEachIndexed { n,row ->
      p.color=if(n%2==0)Color.rgb(202,100,211) else Color.rgb(84,156,214)
      c.drawRect(20f,510f+n*48,171f,551f+n*48,p)
      p.color=Color.WHITE;c.drawText(row.first,35f,542f+n*48,p);c.drawText(row.second,190f,542f+n*48,p)
    }
    try { CaptureOcr(PlannerBridge(InstrumentationRegistry.getInstrumentation().targetContext)).use { ocr ->
      val result=ocr.recognize(image).material!!
      assertEquals("伊布",result.species);assertEquals("F",result.gender);assertEquals("胆小",result.nature)
      assertEquals(listOf(7,31,12,9,31,18),result.ivs)
      assertEquals(listOf("十万伏特","守住","光墙","诱惑"),result.moves)
      assertFalse(result.verified)
    } } finally { image.recycle() }
  }
}
