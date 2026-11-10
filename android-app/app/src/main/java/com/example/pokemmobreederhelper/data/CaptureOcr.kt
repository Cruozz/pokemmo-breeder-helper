package com.example.pokemmobreederhelper.data

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.serialization.encodeToString
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine
import kotlin.math.roundToInt

/** One recognizer per scanner; a task retains its bitmap until ML Kit has actually finished. */
class CaptureOcr(private val bridge: PlannerBridge) : AutoCloseable {
  private val recognizer = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
  private suspend fun read(bitmap: Bitmap): Text {
    val text = suspendCoroutine { continuation ->
      recognizer.process(InputImage.fromBitmap(bitmap, 0))
        .addOnSuccessListener { continuation.resume(it) }
        .addOnFailureListener { continuation.resumeWithException(it) }
        .addOnCanceledListener { continuation.resumeWithException(java.util.concurrent.CancellationException()) }
    }
    currentCoroutineContext().ensureActive()
    return text
  }
  private fun line(text: String, box: android.graphics.Rect) = CaptureLine(text,
    listOf(listOf(box.left,box.top),listOf(box.right,box.top),listOf(box.right,box.bottom),listOf(box.left,box.bottom)))
  suspend fun recognize(bitmap: Bitmap): CaptureRecognition {
    val text=read(bitmap)
    var lines=text.textBlocks.flatMap { it.lines }.mapNotNull { it.boundingBox?.let { b -> line(it.text,b) } }
    val elements=text.textBlocks.flatMap { it.lines }.flatMap { it.elements }
      .mapNotNull { it.boundingBox?.let { b -> line(it.text,b) } }
    val gender=CapturePanelGeometry.gender(bitmap,lines)
    val region=CapturePanelGeometry.movesRegion(lines,elements,bitmap.width,bitmap.height)
    if(region!=null) {
      // Read only the move names, excluding the colorful type badges to their left.
      val crop=Bitmap.createBitmap(bitmap,region.left,region.top,region.width(),region.height())
      val scale=if(region.height()<160) 3f else 2f
      val enlarged=Bitmap.createScaledBitmap(crop,(crop.width*scale).roundToInt(),(crop.height*scale).roundToInt(),true)
      try {
        val moves=read(enlarged).textBlocks.flatMap { it.lines }.mapNotNull { item ->
          item.boundingBox?.let { b -> line(item.text,android.graphics.Rect(
            region.left+(b.left/scale).roundToInt(),region.top+(b.top/scale).roundToInt(),
            region.left+(b.right/scale).roundToInt(),region.top+(b.bottom/scale).roundToInt())).let { refined ->
              val rb=CapturePanelGeometry.box(refined)
              refined.copy(alternatives=lines.filter {
                val old=CapturePanelGeometry.box(it)
                kotlin.math.abs(old.centerY()-rb.centerY())<=rb.height()*.6f && old.left>=region.left
              }.map { it.text }.distinct())
            } }
        }
        if(moves.isNotEmpty()) lines=lines.filterNot {
          val b=CapturePanelGeometry.box(it);b.centerY() in region.top..region.bottom
        }+moves
      } finally { if(enlarged!==crop)enlarged.recycle();if(crop!==bitmap)crop.recycle() }
    }
    val result=bridge.parseCapture(AppJson.codec.encodeToString(lines),gender)
    if(result.material?.species?.isBlank()==true) {
      // Retry just the small name row once. Exact-frame caching must not freeze
      // a missed glyph forever, and a full-screen upscale would waste work.
      val anchor=CapturePanelGeometry.levelLine(lines)
      if(anchor!=null) {
        val b=CapturePanelGeometry.box(anchor);val h=b.height().coerceAtLeast(8)
        val cropBox=android.graphics.Rect(b.left-h,b.top-h/2,b.right+h*2,b.bottom+h/2)
        if(cropBox.intersect(0,0,bitmap.width,bitmap.height)) {
          val crop=Bitmap.createBitmap(bitmap,cropBox.left,cropBox.top,cropBox.width(),cropBox.height())
          val enlarged=Bitmap.createScaledBitmap(crop,crop.width*2,crop.height*2,true)
          try {
            val retry=read(enlarged).textBlocks.flatMap { it.lines }.mapNotNull { item -> item.boundingBox?.let { bb ->
              line(item.text,android.graphics.Rect(cropBox.left+bb.left/2,cropBox.top+bb.top/2,cropBox.left+bb.right/2,cropBox.top+bb.bottom/2))
            } }
            val replacement=retry.firstOrNull { CapturePanelGeometry.levelLine(listOf(it))!=null }
            if(replacement!=null) {
              val revised=lines.map { if(it===anchor) replacement else it }
              val improved=bridge.parseCapture(AppJson.codec.encodeToString(revised),gender)
              if(improved.material?.species?.isNotBlank()==true)return improved
            }
          } finally { enlarged.recycle();if(crop!==bitmap)crop.recycle() }
        }
      }
    }
    return result
  }
  override fun close() = recognizer.close()
}
