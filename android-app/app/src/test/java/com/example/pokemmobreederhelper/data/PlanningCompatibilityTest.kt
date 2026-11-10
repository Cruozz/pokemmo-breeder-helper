package com.example.pokemmobreederhelper.data

import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Test

class PlanningCompatibilityTest {
  @Test fun persistedRouteKeepsNatureCheckpointAndSkillPreparation() {
    val step = ExecutionStepRecord(1, "a", "b", "A", "B", child = MonsterRecord(id = "child"),
      preparations = listOf(SkillPreparation("a", "伊布", "祈愿", "回忆")))
    val route = ExecutionPlanRecord(id = "route", steps = listOf(step), maternalNatureMinIvs = 5,
      costSummary = "待报价", planningOptions = PlanRequest("伊布", maxPurchaseV = 3,
        costPricing = CostSettings(everstone = 8000, requireMarketAvailability = true)))
    val restored = AppJson.codec.decodeFromString<ExecutionPlanRecord>(AppJson.codec.encodeToString(route))
    assertEquals(route, restored)
    assertEquals(5, restored.maternalNatureMinIvs)
    assertEquals("回忆", restored.steps.single().preparations.single().method)
  }

  @Test fun legacyTargetAndRouteRemainReadable() {
    val old = AppJson.codec.decodeFromString<ExecutionPlanRecord>("""{"id":"old","target_species":"伊布"}""")
    assertEquals(0, old.maternalNatureMinIvs)
    val target = AppJson.codec.decodeFromString<PlanRequest>("""{"species":"伊布"}""")
    assertNull(target.maxPurchaseV)
    assertFalse(target.costPricing.includeInventoryValue)
  }
}
