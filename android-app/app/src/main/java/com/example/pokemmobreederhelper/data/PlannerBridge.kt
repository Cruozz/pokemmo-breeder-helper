package com.example.pokemmobreederhelper.data

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.serialization.encodeToString

class PlannerBridge(context: Context) {
  internal val applicationContext: Context = context.applicationContext
  private companion object { val startupLock = Any() }
  private val python: Python
  private val module by lazy { python.getModule("mobile_bridge") }

  init {
    python = synchronized(startupLock) {
      if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
      Python.getInstance()
    }
  }

  fun searchSpecies(query: String, limit: Int = 12): List<SpeciesSuggestion> {
    if (query.isBlank()) return emptyList()
    val raw = module.callAttr("search_species", query, limit).toString()
    return AppJson.codec.decodeFromString<SpeciesSearchResponse>(raw).items
  }

  fun parseCapture(linesJson: String, visualGender: String = "", visualParticle: String = ""): CaptureRecognition =
    AppJson.codec.decodeFromString(python.getModule("mobile_capture").callAttr("parse_capture", linesJson, visualGender, visualParticle).toString())

  fun duplicateGroups(inventoryJson: String): List<List<String>> =
    AppJson.codec.decodeFromString(module.callAttr("inventory_duplicates", inventoryJson).toString())

  fun speciesIcons(): Map<String, Int> = AppJson.codec.decodeFromString(module.callAttr("species_icons").toString())
  fun speciesReference(species: String): List<String> = AppJson.codec.decodeFromString(module.callAttr("species_reference", species).toString())

  fun validateMaterial(material: MonsterRecord): MonsterRecord =
    AppJson.codec.decodeFromString(module.callAttr("validate_material", AppJson.codec.encodeToString(material)).toString())

  fun generatePlan(inventoryJson: String, request: PlanRequest): PlannerResponse {
    val requestJson = AppJson.codec.encodeToString(request)
    val raw = module.callAttr("generate_plan", inventoryJson, requestJson).toString()
    return AppJson.codec.decodeFromString(raw)
  }

  fun completeStep(inventoryJson: String, response: PlannerResponse, outcome: StepOutcome): CompletionResponse {
    val raw = module.callAttr("complete_step", inventoryJson,
      AppJson.codec.encodeToString(response), AppJson.codec.encodeToString(outcome)).toString()
    return AppJson.codec.decodeFromString(raw)
  }
}
