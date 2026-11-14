package com.example.pokemmobreederhelper.capture

import org.junit.Assert.*
import org.junit.Test

class PartialCaptureGateTest {
  @Test fun incompletePageIsReviewedOnceAfterBoundedRetries() {
    val gate=PartialCaptureGate()
    assertFalse(gate.observe("missing-ivs",0))
    assertFalse(gate.observe("missing-ivs",1000))
    assertTrue(gate.observe("missing-ivs",1900))
    gate.committed("missing-ivs")
    assertFalse(gate.observe("missing-ivs",5000))
    assertFalse(gate.observe("",6000))
    assertFalse(gate.observe("missing-ivs",9000))
    assertFalse(gate.observe("other",10000))
    assertFalse(gate.observe("other",11000))
    assertTrue(gate.observe("other",12000))
  }

  @Test fun transitionsAndOneBadObservationCannotCreateDrafts() {
    val gate=PartialCaptureGate()
    assertFalse(gate.observe("a",0));assertFalse(gate.observe("a",2000))
    assertFalse(gate.observe("",2100));assertFalse(gate.observe("a",4000))
    assertFalse(gate.observe("b",6000));assertFalse(gate.observe("a",8000))
  }
}
