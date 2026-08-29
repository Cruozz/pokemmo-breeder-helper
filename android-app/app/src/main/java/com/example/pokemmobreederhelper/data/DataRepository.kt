package com.example.pokemmobreederhelper.data

import android.content.Context
import java.io.File
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

object AppJson {
  val codec = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
  }

  fun decodeInventory(raw: String): List<MonsterRecord> {
    val decoded = codec.decodeFromString<List<MonsterRecord>>(raw)
    return decoded.map { item ->
      val normalizedIvs = item.ivs.take(6) + List((6 - item.ivs.size).coerceAtLeast(0)) { null }
      item.copy(
        id = item.id.ifBlank { UUID.randomUUID().toString() },
        account = item.account.ifBlank { "主账号" },
        ivs = normalizedIvs,
      )
    }
  }
}

class InventoryRepository(private val context: Context) {
  private val inventoryFile = File(context.filesDir, "inventory.json")
  private val planFile = File(context.filesDir, "plan-session.json")
  private val _inventory = MutableStateFlow(loadInventory())
  val inventory: StateFlow<List<MonsterRecord>> = _inventory.asStateFlow()

  fun importInventory(raw: String): ImportSummary {
    val decoded = AppJson.decodeInventory(raw)
    val unique = LinkedHashMap<String, MonsterRecord>()
    decoded.forEach { unique[it.id] = it }
    val items = unique.values.toList()
    atomicWrite(inventoryFile, AppJson.codec.encodeToString(items))
    _inventory.value = items
    clearPlanSession()
    return ImportSummary(
      count = items.size,
      accountCount = items.map { it.account }.toSet().size,
      verifiedCount = items.count { it.verified },
    )
  }

  fun inventoryJson(): String = AppJson.codec.encodeToString(_inventory.value)

  fun loadPlanSession(): SavedPlanSession? =
    runCatching {
      if (!planFile.exists()) null else AppJson.codec.decodeFromString<SavedPlanSession>(planFile.readText())
    }.getOrNull()

  fun savePlanSession(session: SavedPlanSession) {
    atomicWrite(planFile, AppJson.codec.encodeToString(session))
  }

  fun clearPlanSession() {
    if (planFile.exists()) planFile.delete()
  }

  private fun loadInventory(): List<MonsterRecord> =
    runCatching {
      if (!inventoryFile.exists()) emptyList() else AppJson.decodeInventory(inventoryFile.readText())
    }.getOrElse { emptyList() }

  private fun atomicWrite(target: File, value: String) {
    val temporary = File(target.parentFile, "${target.name}.tmp")
    temporary.writeText(value, Charsets.UTF_8)
    if (target.exists() && !target.delete()) error("无法更新 ${target.name}")
    if (!temporary.renameTo(target)) error("无法保存 ${target.name}")
  }
}
