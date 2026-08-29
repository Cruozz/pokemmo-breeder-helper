package com.example.pokemmobreederhelper.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class MonsterRecord(
  val id: String = "",
  val species: String = "",
  val gender: String = "",
  val nature: String = "",
  val ivs: List<Int?> = List(6) { null },
  val ability: String = "",
  @SerialName("held_item") val heldItem: String = "",
  val moves: List<String> = emptyList(),
  @SerialName("egg_groups") val eggGroups: List<String> = emptyList(),
  @SerialName("is_alpha") val isAlpha: Boolean = false,
  @SerialName("has_hidden_ability") val hasHiddenAbility: Boolean = false,
  val account: String = "主账号",
  val page: String = "",
  val slot: String = "",
  val source: String = "",
  val confidence: Double? = null,
  val notes: String = "",
  @SerialName("breeding_target_key") val breedingTargetKey: String = "",
  @SerialName("breeding_role") val breedingRole: String = "",
  @SerialName("nature_attempt_level") val natureAttemptLevel: Int = 0,
  @SerialName("nature_attempt_result") val natureAttemptResult: String = "",
  @SerialName("gender_unconfirmed") val genderUnconfirmed: Boolean = false,
  val verified: Boolean = true,
  @SerialName("scan_fingerprint") val scanFingerprint: String = "",
  @SerialName("created_at") val createdAt: String = "",
  @SerialName("updated_at") val updatedAt: String = "",
) {
  val ivText: String
    get() = ivs.take(6).joinToString("/") { it?.toString() ?: "X" }

  val perfectIvCount: Int
    get() = ivs.count { it == 31 }

  val positionLabel: String
    get() {
      val pageValue = page.trim()
      val slotValue = slot.toIntOrNull() ?: return ""
      if (pageValue.isBlank() || slotValue < 1) return ""
      val row = (slotValue - 1) / 10 + 1
      val column = (slotValue - 1) % 10 + 1
      return "$pageValue-$row,$column"
    }
}

@Serializable
data class SpeciesSuggestion(
  val id: Int,
  @SerialName("display_name") val displayName: String,
  val identifier: String = "",
  @SerialName("egg_groups") val eggGroups: List<String> = emptyList(),
  @SerialName("allowed_genders") val allowedGenders: List<String> = emptyList(),
  @SerialName("female_percent") val femalePercent: Double? = null,
  @SerialName("required_gender") val requiredGender: String = "",
  @SerialName("offspring_species") val offspringSpecies: String = "",
)

@Serializable
data class SpeciesSearchResponse(val items: List<SpeciesSuggestion> = emptyList())

@Serializable
data class PlanRequest(
  val species: String,
  val nature: String = "",
  val ivs: List<String> = listOf("31", "31", "31", "31", "31", "31"),
  @SerialName("target_alpha") val targetAlpha: Boolean = false,
  @SerialName("allow_ditto") val allowDitto: Boolean = true,
  val strategy: String = "inventory",
  @SerialName("allow_alpha_materials") val allowAlphaMaterials: Boolean = false,
  @SerialName("need_hidden_ability") val needHiddenAbility: Boolean = false,
  @SerialName("convert_maternal_with_ditto") val convertMaternalWithDitto: Boolean = false,
  @SerialName("lock_gender") val lockGender: Boolean = false,
  @SerialName("target_gender") val targetGender: String = "",
)

@Serializable
data class ExecutionStepRecord(
  val number: Int,
  @SerialName("parent_a_id") val parentAId: String,
  @SerialName("parent_b_id") val parentBId: String,
  @SerialName("parent_a_label") val parentALabel: String = "",
  @SerialName("parent_b_label") val parentBLabel: String = "",
  val child: MonsterRecord,
  @SerialName("item_a") val itemA: String = "",
  @SerialName("item_b") val itemB: String = "",
  val completed: Boolean = false,
  @SerialName("planned_gender") val plannedGender: String = "",
  @SerialName("gender_policy") val genderPolicy: String = "locked",
  @SerialName("gender_override") val genderOverride: String = "",
  @SerialName("in_progress") val inProgress: Boolean = false,
  @SerialName("nature_check_role") val natureCheckRole: String = "",
  @SerialName("gender_instruction") val genderInstruction: String = "",
  @SerialName("requires_purchase") val requiresPurchase: Boolean = false,
  @SerialName("should_check_nature") val shouldCheckNature: Boolean = false,
  @SerialName("is_final") val isFinal: Boolean = false,
  val dependencies: List<String> = emptyList(),
) {
  val itemText: String
    get() = listOf(itemA, itemB).filter { it.isNotBlank() }.joinToString("、").ifBlank { "无锁定道具" }
}

@Serializable
data class ExecutionPlanRecord(
  val id: String,
  @SerialName("target_species") val targetSpecies: String = "",
  val steps: List<ExecutionStepRecord> = emptyList(),
  @SerialName("purchase_requirements") val purchaseRequirements: List<String> = emptyList(),
  @SerialName("target_nature") val targetNature: String = "",
  @SerialName("target_iv_count") val targetIvCount: Int = 0,
  @SerialName("target_gender") val targetGender: String = "",
  @SerialName("nature_phase") val naturePhase: String = "",
  @SerialName("status_text") val statusText: String = "",
  @SerialName("candidate_description") val candidateDescription: String = "",
  @SerialName("inventory_used_count") val inventoryUsedCount: Int = 0,
)

@Serializable
data class PlannerResponse(
  val ok: Boolean = false,
  val error: String = "",
  val report: String = "",
  @SerialName("candidate_count") val candidateCount: Int = 0,
  val plan: ExecutionPlanRecord? = null,
  val debug: String = "",
)

@Serializable
data class SavedPlanSession(
  val response: PlannerResponse,
  val completedChildIds: Set<String> = emptySet(),
)

data class ImportSummary(val count: Int, val accountCount: Int, val verifiedCount: Int)

fun genderLabel(gender: String): String =
  when (gender.uppercase()) {
    "M" -> "公"
    "F" -> "母"
    "N" -> "无性别"
    else -> "性别未知"
  }
