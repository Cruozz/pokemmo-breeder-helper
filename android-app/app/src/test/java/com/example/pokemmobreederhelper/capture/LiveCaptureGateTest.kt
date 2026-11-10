package com.example.pokemmobreederhelper.capture

import com.example.pokemmobreederhelper.data.MonsterRecord
import org.junit.Assert.*
import org.junit.Test

class LiveCaptureGateTest {
  @Test fun stableFramesSaveOnceAndDifferentSpecimensWaitAgain() {
    val gate=LiveCaptureGate()
    assertFalse(gate.observe("a",0));assertFalse(gate.observe("a",250));assertTrue(gate.observe("a",500))
    assertFalse(gate.observe("a",1950));gate.committed("a")
    assertFalse(gate.observe("a",2600));assertFalse(gate.observe("b",3250));assertTrue(gate.observe("b",4550))
  }
  @Test fun interruptionAndRotationDoNotDuplicateTheSameSpecimen() {
    val gate=LiveCaptureGate();gate.observe("a",0);assertTrue(gate.observe("a",1000));gate.committed("a")
    gate.resetObservation();gate.observe(null,2000);gate.observe("a",3000);assertFalse(gate.observe("a",4500))
    gate.next();gate.observe("a",5000);assertTrue(gate.observe("a",6500))
  }
  @Test fun failedSaveCanRetryAndUnstableFramesNeverAdvance() {
    val gate=LiveCaptureGate();gate.observe("a",0);gate.observe("b",600);assertFalse(gate.observe("a",1200))
    assertTrue(gate.observe("a",2400));gate.failed();assertTrue(gate.observe("a",3000))
  }
  @Test fun completeIvRequiredAndMissingGenderDoesNotCreateDuplicate() {
    val pet=MonsterRecord(species="伊布",ivs=listOf(31,31,1,2,3,4))
    assertNotNull(LiveCaptureGate.key(pet));assertNull(LiveCaptureGate.key(pet.copy(ivs=listOf(31,null,1,2,3,4))))
    assertEquals(LiveCaptureGate.key(pet),LiveCaptureGate.key(pet.copy(gender="F")))
  }
  @Test fun metadataMustSettleAndLateGenderCannotCreateAnotherPet() {
    val gate=LiveCaptureGate()
    assertFalse(gate.observe("pet",0,"unknown"))
    assertFalse(gate.observe("pet",250,"female"))
    assertFalse(gate.observe("pet",500,"female"))
    assertTrue(gate.observe("pet",750,"female"))
    gate.committed("pet")
    assertFalse(gate.observe("pet",1000,"nature-added"))
    assertFalse(gate.observe("pet",1500,"nature-added"))
  }
  @Test fun positionsRollOverUsingConfiguredBoxSize() {
    assertEquals(CapturePosition("账号",2,1,30),CapturePosition("账号",1,30,30).next())
    assertEquals(CapturePosition("账号",1,2),CapturePosition("账号",1,1).next())
  }
  @Test(expected=IllegalArgumentException::class) fun invalidSlotRejected() { CapturePosition("账号",1,61) }
}
