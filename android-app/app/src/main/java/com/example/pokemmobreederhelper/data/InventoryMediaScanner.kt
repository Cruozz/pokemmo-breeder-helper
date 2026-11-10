package com.example.pokemmobreederhelper.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import androidx.core.graphics.scale
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine

class InventoryMediaScanner(private val context: Context, private val bridge: PlannerBridge) {
  suspend fun scan(
    uris: List<Uri>, video: Boolean,
    onFrame: suspend (CaptureRecognition?, Bitmap?, String, Long?, Int, Int, String?) -> Unit,
  ) = withContext(Dispatchers.IO) {
    val recognizer = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
    suspend fun recognize(bitmap: Bitmap): CaptureRecognition {
      // Wait for the current ML task to finish before recycling its bitmap, even on cancellation.
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
    suspend fun frame(bitmap: Bitmap?, label: String, ms: Long?, done: Int, total: Int) {
      if (bitmap == null) {
        onFrame(null, null, label, ms, done, total, "无法解码画面，可重新截图后导入。")
        return
      }
      try {
        currentCoroutineContext().ensureActive()
        // Consumer failures (e.g. full disk) must stop the scan, not be reported as an OCR miss.
        val recognition = try { recognize(bitmap) }
        catch (cancelled: kotlinx.coroutines.CancellationException) { throw cancelled }
        catch (error: Exception) {
          onFrame(null, null, label, ms, done, total, "识别失败：${error.message}")
          return
        }
        onFrame(recognition, bitmap, label, ms, done, total, null)
      } finally { bitmap.recycle() }
    }
    try {
      if (video) {
        require(uris.size == 1) { "每次请选择一段录屏。" }
        val retriever = MediaMetadataRetriever()
        try {
          retriever.setDataSource(context, uris.single())
          val duration = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
          val times = CaptureLimits.videoTimes(duration)
          val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 1920
          val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 1080
          require(Build.VERSION.SDK_INT >= 27 || width.toLong() * height <= 8_294_400L) { "Android 8.0 请导入 4K 以下录屏，或先导出较低分辨率。" }
          val scale = minOf(1.0, CaptureLimits.MAX_IMAGE_EDGE.toDouble() / maxOf(width, height).coerceAtLeast(1))
          for ((index, ms) in times.withIndex()) {
            currentCoroutineContext().ensureActive()
            val bitmap = try {
              if (Build.VERSION.SDK_INT >= 27) retriever.getScaledFrameAtTime(ms * 1000L, MediaMetadataRetriever.OPTION_CLOSEST,
                (width * scale).toInt().coerceAtLeast(1), (height * scale).toInt().coerceAtLeast(1))
              else retriever.getFrameAtTime(ms * 1000L, MediaMetadataRetriever.OPTION_CLOSEST)?.let { original ->
                if (scale < 1.0) original.scale((original.width * scale).toInt().coerceAtLeast(1),
                  (original.height * scale).toInt().coerceAtLeast(1)).also { if (it !== original) original.recycle() }
                else original
              }
            }
              catch (_: RuntimeException) { null }
            frame(bitmap, "录屏 ${ms / 1000} 秒", ms, index + 1, times.size)
          }
        } finally { retriever.release() }
      } else {
        require(uris.size in 1..CaptureLimits.MAX_IMAGES) { "每批最多导入 20 张截图。" }
        for ((index, uri) in uris.withIndex()) {
          currentCoroutineContext().ensureActive()
          val bitmap = try { decodeImage(uri) } catch (_: Exception) { null }
          frame(bitmap, "截图 ${index + 1}", null, index + 1, uris.size)
        }
      }
    } finally { recognizer.close() }
  }

  private fun decodeImage(uri: Uri): Bitmap? {
    if (Build.VERSION.SDK_INT >= 28) {
      return ImageDecoder.decodeBitmap(ImageDecoder.createSource(context.contentResolver, uri)) { decoder, info, _ ->
        val scale = minOf(1.0, CaptureLimits.MAX_IMAGE_EDGE.toDouble() / maxOf(info.size.width, info.size.height))
        decoder.setTargetSize((info.size.width * scale).toInt().coerceAtLeast(1), (info.size.height * scale).toInt().coerceAtLeast(1))
        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
      }
    }
    val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
    require(options.outWidth > 0 && options.outHeight > 0) { "无法读取截图。" }
    var sample = 1
    while (maxOf(options.outWidth, options.outHeight) / sample > CaptureLimits.MAX_IMAGE_EDGE) sample *= 2
    options.inJustDecodeBounds = false
    options.inSampleSize = sample
    val bitmap = context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) } ?: return null
    val orientation = runCatching { context.contentResolver.openInputStream(uri)?.use {
      ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
    } }.getOrNull()
    val matrix = Matrix().apply {
      when (orientation) {
        ExifInterface.ORIENTATION_ROTATE_90 -> postRotate(90f)
        ExifInterface.ORIENTATION_ROTATE_180 -> postRotate(180f)
        ExifInterface.ORIENTATION_ROTATE_270 -> postRotate(270f)
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> postScale(-1f, 1f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> postScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> { postRotate(90f); postScale(-1f, 1f) }
        ExifInterface.ORIENTATION_TRANSVERSE -> { postRotate(270f); postScale(-1f, 1f) }
      }
    }
    val rotated = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
    if (rotated !== bitmap) bitmap.recycle()
    return rotated
  }
}
