package com.example.pokemmobreederhelper.ui.main

import android.graphics.*
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.R
import com.example.pokemmobreederhelper.data.*
import org.junit.Assert.*
import org.junit.Test

class ParticleRecognitionTest {
  @Test fun catalogueIconsRecognizeAtDesktopAndMobileScales() {
    val context = InstrumentationRegistry.getInstrumentation().targetContext
    val atlas = BitmapFactory.decodeResource(context.resources, R.drawable.particle_atlas,
      BitmapFactory.Options().apply { inScaled=false })
    val matcher = ParticleIconMatcher(context)
    val failures = mutableListOf<String>()
    val start = android.os.SystemClock.elapsedRealtime()
    try {
      for (entry in ParticleCatalog.entries(context)) for (size in listOf(24,48)) {
        val image=Bitmap.createBitmap(290,190,Bitmap.Config.ARGB_8888)
        val canvas=Canvas(image);canvas.drawColor(Color.rgb(75,84,92))
        val x=entry.iconIndex%7*24;val y=entry.iconIndex/7*24
        canvas.drawBitmap(atlas,Rect(x,y,x+24,y+24),Rect(220,100-size/2,220+size,100+size/2),Paint())
        val lines=listOf(CaptureLine("Lv.100 伊布",listOf(listOf(25,120),listOf(220,120),listOf(220,140),listOf(25,140))))
        val actual=matcher.recognize(image,lines)
        if(actual!=entry.id) failures.add("${entry.id} $size -> $actual")
        image.recycle()
      }
    } finally { atlas.recycle() }
    android.util.Log.i("ParticleRecognitionTest","84 icon matches took ${android.os.SystemClock.elapsedRealtime()-start} ms")
    assertTrue(failures.joinToString("\n"),failures.isEmpty())
  }

  @Test fun emptyBandAndMissingAnchorDoNotInventParticles() {
    val context=InstrumentationRegistry.getInstrumentation().targetContext
    val matcher=ParticleIconMatcher(context)
    val image=Bitmap.createBitmap(290,190,Bitmap.Config.ARGB_8888)
    Canvas(image).drawColor(Color.rgb(75,84,92))
    try {
      assertEquals("",matcher.recognize(image,emptyList()))
      assertEquals("",matcher.recognize(image,listOf(CaptureLine("Lv.100 伊布",
        listOf(listOf(25,120),listOf(220,120),listOf(220,140),listOf(25,140))))))
    } finally { image.recycle() }
  }
}
