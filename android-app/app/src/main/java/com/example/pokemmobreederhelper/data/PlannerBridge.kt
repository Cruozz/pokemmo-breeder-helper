package com.example.pokemmobreederhelper.data

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.serialization.encodeToString

class PlannerBridge(context: Context) {
  private val python: Python
  private val module by lazy { python.getModule("mobile_bridge") }

  init {
    if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
    python = Python.getInstance()
  }

  fun searchSpecies(query: String, limit: Int = 12): List<SpeciesSuggestion> {
    if (query.isBlank()) return emptyList()
    val raw = module.callAttr("search_species", query, limit).toString()
    return AppJson.codec.decodeFromString<SpeciesSearchResponse>(raw).items
  }

  fun generatePlan(inventoryJson: String, request: PlanRequest): PlannerResponse {
    val requestJson = AppJson.codec.encodeToString(request)
    val raw = module.callAttr("generate_plan", inventoryJson, requestJson).toString()
    return AppJson.codec.decodeFromString(raw)
  }
}
