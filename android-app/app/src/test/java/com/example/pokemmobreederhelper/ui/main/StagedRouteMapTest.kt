package com.example.pokemmobreederhelper.ui.main

import com.example.pokemmobreederhelper.data.*
import org.junit.Assert.*
import org.junit.Test

class StagedRouteMapTest {
  @Test fun lowerGambleKeepsFiveVTargetMotherAndFourVHandInTree() {
    val mother = MonsterRecord(id = "body", species = "尼多兰", gender = "F", ivs = listOf(31, null, 31, 31, 31, 31))
    val upper = mother.copy(id = "upper", species = "长毛狗", gender = "M", ivs = listOf(31, null, 31, 31, 31, null))
    val lower = upper.copy(id = "lower", gender = "F", ivs = listOf(31, null, 31, 31, null, null))
    val step = ExecutionStepRecord(1, "buy:a", "buy:b", child = lower, isFinal = true)
    val plan = ExecutionPlanRecord("test", targetSpecies = "尼多王", targetIvCount = 5, targetNature = "内敛",
      naturePhase = "gamble_lower", steps = listOf(step), retainedMaterials = listOf(mother, upper),
      finalTarget = mother.copy(species = "尼多王", gender = "M", nature = "内敛"), needsReplan = true)
    val root = buildRouteRoot(plan, setOf(lower.id))
    assertEquals("最终目标 · 尼多王", root.title)
    assertEquals(mother.ivText, root.ivText)
    assertEquals("retained:body", root.children[0].key)
    assertEquals("future-hand", root.children[1].key)
    assertEquals("retained:upper", root.children[1].children[0].key)
    val current = root.children[1].children[1]
    assertEquals(step, current.step)
    assertTrue(current.children.isEmpty())
    assertNull(root.step)
    assertEquals(2, buildRouteRoot(plan, setOf(lower.id), true).children[1].children[1].children.size)
  }

  @Test fun finalMergeDoesNotAddAnExtraUnexecutableTargetStep() {
    val child = MonsterRecord(id = "final", species = "尼多朗", gender = "M")
    val step = ExecutionStepRecord(1, "mother", "hand", child = child, isFinal = true)
    val plan = ExecutionPlanRecord("test", steps = listOf(step), naturePhase = "guarantee", finalTarget = child)
    assertEquals(step, buildRouteRoot(plan, emptySet()).step)
  }
}
