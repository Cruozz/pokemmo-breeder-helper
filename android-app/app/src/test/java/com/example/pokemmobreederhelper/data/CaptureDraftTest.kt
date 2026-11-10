package com.example.pokemmobreederhelper.data

import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.encodeToString

class CaptureDraftTest {
  private fun draft(ms: Long? = 0L, batch: String = "batch", hash: String = "abc") = CaptureDraft(
    material = MonsterRecord(id = "a", verified = false), warnings = listOf("核对"), rawText = "个体值", fingerprint = hash,
    imageName = "a.jpg", sourceLabel = "录屏", batchId = batch, firstMs = ms, lastMs = ms)

  @Test fun onlyAdjacentFramesInTheSameRecordingCanGroup() {
    val first = draft()
    assertTrue(first.canGroup(draft(1000)))
    assertFalse(first.canGroup(draft(2000)))
    assertFalse(first.canGroup(draft(0)))
    assertFalse(first.canGroup(draft(1000, "another-recording")))
    assertFalse(first.canGroup(draft(1000, hash = "different")))
    assertFalse(draft(null).canGroup(draft(null)))
    assertFalse(draft(hash = "").canGroup(draft(1000, hash = "")))
  }

  @Test fun samplingIsBoundedAndNeverSkipsTheStartOfShortVideos() {
    assertEquals(listOf(0L), CaptureLimits.videoTimes(100))
    assertEquals(listOf(0L, 1000L, 2000L), CaptureLimits.videoTimes(2500))
    assertEquals(120, CaptureLimits.videoTimes(120000).size)
    assertThrows(IllegalArgumentException::class.java) { CaptureLimits.videoTimes(120001) }
    assertThrows(IllegalArgumentException::class.java) { CaptureLimits.videoTimes(0) }
  }

  @Test fun persistedDraftsRetainReviewAndGroupingInformation() {
    val original = draft().copy(frameCount = 3, lastMs = 2000)
    val restored = AppJson.codec.decodeFromString<CaptureDraft>(AppJson.codec.encodeToString(original))
    assertEquals(original, restored)
    assertFalse(restored.material.verified)
    assertTrue(restored.canGroup(draft(3000)))
  }
}
