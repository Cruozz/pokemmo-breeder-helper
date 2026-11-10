package com.example.pokemmobreederhelper.data

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.serialization.encodeToString
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine

/** One recognizer per scanner; a task retains its bitmap until ML Kit has actually finished. */
class CaptureOcr(private val bridge: PlannerBridge) : AutoCloseable {
  private val recognizer = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
  suspend fun recognize(bitmap: Bitmap): CaptureRecognition {
    val text = suspendCoroutine { continuation ->
      recognizer.process(InputImage.fromBitmap(bitmap, 0))
        .addOnSuccessListener { continuation.resume(it) }
        .addOnFailureListener { continuation.resumeWithException(it) }
        .addOnCanceledListener { continuation.resumeWithException(java.util.concurrent.CancellationException()) }
    }
    currentCoroutineContext().ensureActive()
    val lines = text.textBlocks.flatMap { it.lines }.mapNotNull { line ->
      val box = line.boundingBox ?: return@mapNotNull null
      CaptureLine(line.text, listOf(listOf(box.left, box.top), listOf(box.right, box.top),
        listOf(box.right, box.bottom), listOf(box.left, box.bottom)))
    }
    return bridge.parseCapture(AppJson.codec.encodeToString(lines))
  }
  override fun close() = recognizer.close()
}
