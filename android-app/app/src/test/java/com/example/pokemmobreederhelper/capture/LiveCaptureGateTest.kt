package com.example.pokemmobreederhelper.capture

import com.example.pokemmobreederhelper.data.MonsterRecord
import org.junit.Assert.*
import org.junit.Test

class LiveCaptureGateTest {
  private val first = MonsterRecord(species="伊布", gender="F", nature="固执", ivs=listOf(31,31,1,2,3,4))
  private val second = first.copy(ivs=listOf(31,30,1,2,3,4))
  @Test fun stableCompleteResultsSaveOnce() {
    val gate=LiveCaptureGate()
    assertFalse(gate.observe(first,0));assertFalse(gate.observe(first,250));assertTrue(gate.observe(first,500))
    assertFalse(gate.observe(first,1000));gate.committed(first)
    assertFalse(gate.observe(first,1600));assertFalse(gate.observe(second,1700));assertTrue(gate.observe(second,2200))
  }
  @Test fun nextBeforeGameChangeCannotReadTheOldPageAgain() {
    val gate=LiveCaptureGate();gate.committed(first);gate.next()
    assertFalse(gate.observe(first,0));assertFalse(gate.observe(first,1000));assertFalse(gate.observe(first,5000))
    assertFalse(gate.observe(second,5100));assertTrue(gate.observe(second,5600))
  }
  @Test fun gameChangeBeforeNextStillAllowsTheNewPage() {
    val gate=LiveCaptureGate();gate.committed(first)
    gate.observe(second,100);gate.next()
    assertFalse(gate.observe(second,700));assertTrue(gate.observe(second,1200))
  }
  @Test fun identicalResultsRemainExcludedAcrossBlankFramesPauseAndRotation() {
    val gate=LiveCaptureGate();gate.committed(first)
    repeat(3) { gate.resetObservation();gate.observe(null,0);gate.observe(first,100);assertFalse(gate.observe(first,1600)) }
    gate.next();gate.observe(first,2000);assertFalse(gate.observe(first.copy(id="other",account="new",slot="9"),3000))
  }
  @Test fun natureAndGenderChangesAreDifferentSpecimensEvenWithTheSameIvs() {
    for (changed in listOf(first.copy(nature="胆小"),first.copy(gender="M"),first.copy(ability="逃跑"),first.copy(isAlpha=true))) {
      val baseline=if(changed.ability.isNotBlank())first.copy(ability="适应力") else first
      val gate=LiveCaptureGate();gate.committed(baseline)
      assertFalse(gate.observe(changed,0));assertTrue(gate.observe(changed,500))
    }
  }
  @Test fun missingOptionalFieldsDoNotProduceDuplicatesWhenOcrCatchesUp() {
    val gate=LiveCaptureGate();gate.committed(first.copy(gender="",nature=""))
    gate.observe(first,0);assertFalse(gate.observe(first,1000))
    assertTrue(gate.isPrevious(first))
  }
  @Test fun unstableFramesAndMissingIvsNeverAdvance() {
    val gate=LiveCaptureGate();gate.observe(first,0);gate.observe(second,500)
    assertFalse(gate.observe(first,1000));assertTrue(gate.observe(first,1500))
    gate.failed();assertFalse(gate.observe(first.copy(ivs=listOf(31,null,1,2,3,4)),2000))
    assertFalse(gate.observe(first,2500));assertTrue(gate.observe(first,3000))
  }
  @Test fun positionsRollOverUsingConfiguredBoxSize() {
    assertEquals(CapturePosition("账号",2,1,30),CapturePosition("账号",1,30,30).next())
    assertEquals(CapturePosition("账号",1,2),CapturePosition("账号",1,1).next())
  }
  @Test(expected=IllegalArgumentException::class) fun invalidSlotRejected() { CapturePosition("账号",1,61) }
}
