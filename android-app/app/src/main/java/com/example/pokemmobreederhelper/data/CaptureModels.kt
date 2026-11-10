package com.example.pokemmobreederhelper.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class CaptureLine(val text: String, val box: List<List<Int>>, val alternatives: List<String> = emptyList())

@Serializable
data class CaptureRecognition(
  val material: MonsterRecord? = null,
  val warnings: List<String> = emptyList(),
  @SerialName("raw_text") val rawText: String = "",
  val fingerprint: String = "",
)

@Serializable
data class CaptureDraft(
  val material: MonsterRecord,
  val warnings: List<String>,
  val rawText: String,
  val fingerprint: String,
  val imageName: String,
  val sourceLabel: String,
  val batchId: String,
  val firstMs: Long? = null,
  val lastMs: Long? = null,
  val frameCount: Int = 1,
) {
  fun canGroup(next: CaptureDraft): Boolean = firstMs != null && next.firstMs != null &&
    batchId == next.batchId && fingerprint.isNotBlank() && fingerprint == next.fingerprint &&
    next.firstMs - (lastMs ?: firstMs) in 1..1500
}

internal object CaptureLimits {
  const val MAX_IMAGES = 20
  const val MAX_DRAFTS = 200
  const val MAX_VIDEO_MS = 120_000L
  const val FRAME_INTERVAL_MS = 1000L
  const val MAX_IMAGE_EDGE = 2560

  fun videoTimes(durationMs: Long): List<Long> {
    require(durationMs in 1..MAX_VIDEO_MS) { "请先将录屏剪辑为 2 分钟以内，再导入识别。" }
    return (0L until durationMs step FRAME_INTERVAL_MS).toList()
  }
}
