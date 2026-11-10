package com.example.pokemmobreederhelper.capture

import com.example.pokemmobreederhelper.data.MonsterRecord

/** A confirmed/previewed specimen stays excluded until a different complete result settles. */
internal class LiveCaptureGate(private val settleMs: Long = 500L) {
  private var candidate = ""
  private var since = 0L
  private var observations = 0
  private var last: MonsterRecord? = null
  private var pending = false

  fun observe(material: MonsterRecord?, now: Long): Boolean {
    val key = key(material)
    if (key == null) { resetObservation(); return false }
    if (key != candidate) { candidate = key; since = now; observations = 1; return false }
    observations++
    if (pending || observations < 2 || now - since < settleMs) return false
    if (sameSpecimen(last, material)) return false
    pending = true
    return true
  }
  fun committed(material: MonsterRecord) { last = material; pending = false }
  fun failed() { resetObservation() }
  fun resetObservation() { candidate = ""; observations = 0; pending = false }
  // Next, pause, rotation and blank transition frames must not erase the previous specimen.
  fun next() { resetObservation() }
  fun isPrevious(material: MonsterRecord?) = sameSpecimen(last, material)

  companion object {
    fun key(material: MonsterRecord?): String? = material?.takeIf {
      it.species.isNotBlank() && it.ivs.size == 6 && it.ivs.all { value -> value != null && value in 0..31 }
    }?.let {
      listOf(it.species, it.gender, it.nature, it.ivs.joinToString(","), it.ability,
        it.isAlpha, it.hasHiddenAbility, it.heldItem, it.moves.joinToString(",")).joinToString("|")
    }
    // Missing optional OCR fields must not turn a late recognition into a second inventory entry.
    fun sameSpecimen(a: MonsterRecord?, b: MonsterRecord?): Boolean {
      if (a == null || b == null || a.species != b.species || a.ivs != b.ivs) return false
      fun compatible(x: String, y: String) = x.isBlank() || y.isBlank() || x == y
      return compatible(a.gender, b.gender) && compatible(a.nature, b.nature) &&
        compatible(a.ability, b.ability) && compatible(a.heldItem, b.heldItem) &&
        a.isAlpha == b.isAlpha && a.hasHiddenAbility == b.hasHiddenAbility &&
        (a.moves.isEmpty() || b.moves.isEmpty() || a.moves == b.moves)
    }
  }
}

internal data class CapturePosition(val account: String, val box: Int, val slot: Int, val slotsPerBox: Int = 60) {
  init { require(account.isNotBlank() && box > 0 && slotsPerBox in 1..999 && slot in 1..slotsPerBox) }
  fun next() = if (slot == slotsPerBox) copy(box = box + 1, slot = 1) else copy(slot = slot + 1)
}
