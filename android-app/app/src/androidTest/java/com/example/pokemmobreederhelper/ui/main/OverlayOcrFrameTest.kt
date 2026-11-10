package com.example.pokemmobreederhelper.ui.main

import android.graphics.*
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.capture.OverlayFrameMask
import com.example.pokemmobreederhelper.data.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class OverlayOcrFrameTest {
  @Test fun maskedSyntheticPageKeepsNameGenderNatureAndIvsReadable() = runBlocking {
    val i=InstrumentationRegistry.getInstrumentation()
    val image=i.context.assets.open("overlay-name-frame.png").use { BitmapFactory.decodeStream(it) }
    val frame=image.copy(Bitmap.Config.ARGB_8888,true);image.recycle()
    try {
      OverlayFrameMask.apply(frame,listOf(Rect(18,123,558,678)))
      CaptureOcr(PlannerBridge(i.targetContext)).use { ocr ->
        val result=ocr.recognize(frame).material!!
        assertEquals("皮卡丘",result.species);assertEquals("F",result.gender);assertEquals("坦率",result.nature)
        assertEquals(listOf(31,2,19,0,16,6),result.ivs)
      }
    } finally { frame.recycle() }
  }
}
