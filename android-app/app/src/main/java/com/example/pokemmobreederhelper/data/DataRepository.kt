package com.example.pokemmobreederhelper.data

import android.content.Context
import android.util.AtomicFile
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
    require(decoded.all { item -> item.ivs.all { it == null || it in 0..31 } }) { "库存包含不在 0–31 范围内的个体值。" }
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
  private val workspaceFile = AtomicFile(File(context.filesDir, "workspace-v2.json"))
  var loadError: String = ""
    private set
  private var workspace: MobileWorkspace = runCatching { loadWorkspace() }.getOrElse {
    loadError = "存档无法读取，已阻止覆盖并保留原文件。请勿卸载或清除数据：${it.message}"
    MobileWorkspace()
  }
  private val _inventory = MutableStateFlow(workspace.current.inventory)
  val inventory: StateFlow<List<MonsterRecord>> = _inventory.asStateFlow()

  fun importInventory(raw: String): ImportSummary {
    val decoded = AppJson.decodeInventory(raw)
    val unique = LinkedHashMap<String, MonsterRecord>()
    decoded.forEach { unique[it.id] = it }
    val items = unique.values.toList()
    replace(WorkspaceSnapshot(items, null))
    return ImportSummary(
      count = items.size,
      accountCount = items.map { it.account }.toSet().size,
      verifiedCount = items.count { it.verified },
    )
  }

  fun inventoryJson(): String {
    check(loadError.isBlank()) { loadError }
    return AppJson.codec.encodeToString(_inventory.value)
  }

  fun loadPlanSession(): SavedPlanSession? = workspace.current.session
  fun loadTarget(): PlanRequest? = workspace.current.session?.request ?: workspace.current.target
  val canUndo: Boolean get() = workspace.undo != null

  @Synchronized
  fun replace(snapshot: WorkspaceSnapshot, checkpoint: Boolean = true, clearRoutes: Boolean = false) {
    check(loadError.isBlank()) { loadError }
    val next = MobileWorkspace(snapshot, if (clearRoutes) workspace.undo?.copy(session = null)
      else if (checkpoint) workspace.current else workspace.undo)
    val stream = workspaceFile.startWrite()
    try {
      stream.write(AppJson.codec.encodeToString(next).toByteArray(Charsets.UTF_8))
      workspaceFile.finishWrite(stream)
    } catch (error: Throwable) {
      workspaceFile.failWrite(stream)
      throw error
    }
    workspace = next
    _inventory.value = snapshot.inventory
  }

  @Synchronized
  fun undo(): Boolean {
    val saved = workspace.undo ?: return false
    replace(saved) // One-level undo/redo keeps an escape path after restoration.
    return true
  }

  fun savePlanSession(session: SavedPlanSession) {
    replace(workspace.current.copy(session = session))
  }

  fun clearPlanSession(target: PlanRequest? = loadTarget()) {
    replace(workspace.current.copy(session = null, target = target), checkpoint = false, clearRoutes = true)
  }

  private fun loadInventory(): List<MonsterRecord> =
    if (!inventoryFile.exists()) emptyList() else AppJson.decodeInventory(inventoryFile.readText())

  private fun loadWorkspace(): MobileWorkspace {
    if (workspaceFile.baseFile.exists() || File(context.filesDir, "workspace-v2.json.bak").exists()) {
      // Do not silently discard a corrupt active workspace as an empty box.
      return AppJson.codec.decodeFromString(workspaceFile.openRead().bufferedReader().use { it.readText() })
    }
    val legacy = if (planFile.exists()) AppJson.codec.decodeFromString<SavedPlanSession>(planFile.readText()) else null
    return MobileWorkspace(WorkspaceSnapshot(loadInventory(), legacy))
  }
}
