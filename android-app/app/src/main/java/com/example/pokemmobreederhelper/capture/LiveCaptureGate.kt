package com.example.pokemmobreederhelper.capture

import com.example.pokemmobreederhelper.data.MonsterRecord

/** A stable OCR observation is a candidate, never proof that two identical pets are one. */
internal class LiveCaptureGate(private val settleMs: Long = 500L) {
  private var candidate = ""
  private var since = 0L
  private var observations = 0
  private var saved = ""
  private var pending = false

  fun observe(key: String?, now: Long, observation: String? = key): Boolean {
    if (key.isNullOrBlank()) { candidate = ""; observations = 0; return false }
    if (observation != candidate) { candidate = observation.orEmpty(); since = now; observations = 1; return false }
    observations++
    if (pending || key == saved || observations < 2 || now - since < settleMs) return false
    pending = true
    return true
  }
  fun committed(key: String) { saved = key; pending = false }
  fun failed() { pending = false }
  fun resetObservation() { candidate = ""; observations = 0; pending = false }
  fun next() { candidate = ""; saved = ""; observations = 0; pending = false }

  companion object {
    fun observationKey(material: MonsterRecord?): String? = key(material)?.let {
      listOf(it, material?.gender, material?.nature, material?.ability, material?.isAlpha,
        material?.hasHiddenAbility, material?.moves?.joinToString(",")).joinToString("|")
    }
    fun key(material: MonsterRecord?): String? = material?.takeIf {
      it.species.isNotBlank() && it.ivs.size == 6 && it.ivs.all { value -> value != null && value in 0..31 }
    }?.let { "${it.species}|${it.ivs.joinToString(",")}" }
  }
}

internal data class CapturePosition(val account: String, val box: Int, val slot: Int, val slotsPerBox: Int = 60) {
  init { require(account.isNotBlank() && box > 0 && slotsPerBox in 1..999 && slot in 1..slotsPerBox) }
  fun next() = if (slot == slotsPerBox) copy(box = box + 1, slot = 1) else copy(slot = slot + 1)
}
