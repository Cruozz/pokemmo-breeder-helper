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
        hasParticles = item.hasParticles || item.particles.isNotEmpty(), isCostume = item.isCostume || item.costumeId.isNotBlank(),
      )
    }
  }
}

enum class CaptureInsertResult { ADDED, ALREADY_PRESENT, SLOT_OCCUPIED }

/** Activities and the screen service share one atomic workspace per application directory. */
class InventoryRepository(context: Context) {
  private val directory = context.filesDir
  private val inventoryFile = File(directory, "inventory.json")
  private val planFile = File(directory, "plan-session.json")
  private val workspaceFile = AtomicFile(File(directory, "workspace-v2.json"))
  private class SharedState {
    var workspace = MobileWorkspace()
    var loadError = ""
    val inventory = MutableStateFlow<List<MonsterRecord>>(emptyList())
  }
  private companion object {
    val writeLock = Any()
    val stores = mutableMapOf<String, SharedState>()
  }
  private val shared = synchronized(writeLock) {
    stores.getOrPut(directory.canonicalPath) { SharedState() }.also { state ->
      runCatching { loadWorkspace() }.onSuccess {
        state.workspace = it; state.loadError = ""; state.inventory.value = it.current.inventory
      }.onFailure {
        state.loadError = "存档无法读取，已阻止覆盖并保留原文件。请勿卸载或清除数据：${it.message}"
      }
    }
  }
  val loadError: String get() = synchronized(writeLock) { shared.loadError }
  private val workspace: MobileWorkspace get() = shared.workspace
  val inventory: StateFlow<List<MonsterRecord>> = shared.inventory.asStateFlow()

  fun importInventory(raw: String): ImportSummary = synchronized(writeLock) {
    val decoded = AppJson.decodeInventory(raw)
    val unique = LinkedHashMap<String, MonsterRecord>()
    decoded.forEach { unique[it.id] = it }
    val items = unique.values.toList()
    replace(WorkspaceSnapshot(items, null))
    ImportSummary(items.size, items.map { it.account }.toSet().size, items.count { it.verified })
  }

  fun inventoryJson(): String = synchronized(writeLock) {
    check(loadError.isBlank()) { loadError }
    AppJson.codec.encodeToString(workspace.current.inventory)
  }
  fun loadPlanSession(): SavedPlanSession? = synchronized(writeLock) { workspace.current.session }
  fun loadTarget(): PlanRequest? = synchronized(writeLock) { workspace.current.session?.request ?: workspace.current.target }
  val canUndo: Boolean get() = synchronized(writeLock) { workspace.undo != null }

  fun replace(snapshot: WorkspaceSnapshot, checkpoint: Boolean = true, clearRoutes: Boolean = false,
    expectedInventory: List<MonsterRecord>? = null): Unit = synchronized(writeLock) {
    check(loadError.isBlank()) { loadError }
    check(expectedInventory == null || expectedInventory == workspace.current.inventory) {
      "库存刚刚发生变化，请重试；最新采集与原路线均已保留。"
    }
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
    shared.workspace = next
    shared.inventory.value = snapshot.inventory
  }

  fun undo(): Boolean = synchronized(writeLock) {
    val saved = workspace.undo ?: return@synchronized false
    replace(saved)
    true
  }
  fun savePlanSession(session: SavedPlanSession) = synchronized(writeLock) {
    replace(workspace.current.copy(session = session))
  }

  /** Transform the latest inventory under the same lock as capture and disk writes. */
  fun updateInventory(transform: (List<MonsterRecord>) -> List<MonsterRecord>) = synchronized(writeLock) {
    editInventory(transform(workspace.current.inventory))
  }
  fun insertCapture(material: MonsterRecord): CaptureInsertResult = synchronized(writeLock) {
    require(material.id.isNotBlank() && material.species.isNotBlank() && material.ivs.size == 6 &&
      material.ivs.all { it != null && it in 0..31 }) { "资料不完整，请先核对。" }
    require(material.account.isNotBlank() && (material.page.toIntOrNull() ?: 0) > 0 &&
      (material.slot.toIntOrNull() ?: 0) > 0) { "请填写有效的账号和仓库位置。" }
    val items = workspace.current.inventory
    val occupied = items.firstOrNull { it.account.trim() == material.account.trim() &&
      it.page.toIntOrNull() == material.page.toIntOrNull() && it.slot.toIntOrNull() == material.slot.toIntOrNull() }
    if (occupied != null) {
      return@synchronized if (occupied.species == material.species && occupied.ivs == material.ivs &&
        occupied.gender == material.gender && occupied.nature == material.nature &&
        occupied.isAlpha == material.isAlpha && occupied.hasHiddenAbility == material.hasHiddenAbility &&
        occupied.hasParticles == material.hasParticles && occupied.particles.toSet() == material.particles.toSet() &&
        occupied.isCostume == material.isCostume && occupied.costumeId == material.costumeId &&
        occupied.ability == material.ability && occupied.moves == material.moves && occupied.heldItem == material.heldItem)
        CaptureInsertResult.ALREADY_PRESENT else CaptureInsertResult.SLOT_OCCUPIED
    }
    require(items.none { it.id == material.id }) { "这条采集已保存。" }
    editInventory(items + material.copy(verified = false))
    CaptureInsertResult.ADDED
  }
  fun editInventory(items: List<MonsterRecord>): Unit = synchronized(writeLock) {
    require(items.map { it.id }.distinct().size == items.size) { "素材编号不能重复。" }
    val previous = workspace.current.inventory.associateBy { it.id }
    val next = items.associateBy { it.id }
    val changed = (previous.keys + next.keys).filter { previous[it] != next[it] }.toSet()
    val session = workspace.current.session
    val plan = session?.response?.plan
    val affected = plan?.steps?.any { !it.completed && (it.parentAId in changed || it.parentBId in changed) } == true ||
      plan?.retainedMaterials?.any { it.id in changed } == true
    val updatedSession = if (affected && plan != null && session != null) session.copy(
      response = session.response.copy(plan = plan.copy(needsReplan = true,
        replanReason = "路线使用的素材已修改或删除，请按原目标重新规划。"))) else session
    replace(workspace.current.copy(inventory = items, session = updatedSession))
  }
  fun clearPlanSession(target: PlanRequest? = loadTarget()) = synchronized(writeLock) {
    replace(workspace.current.copy(session = null, target = target), checkpoint = false, clearRoutes = true)
  }
  private fun loadInventory(): List<MonsterRecord> =
    if (!inventoryFile.exists()) emptyList() else AppJson.decodeInventory(inventoryFile.readText())
  private fun loadWorkspace(): MobileWorkspace {
    if (workspaceFile.baseFile.exists() || File(directory, "workspace-v2.json.bak").exists()) {
      return AppJson.codec.decodeFromString(workspaceFile.openRead().bufferedReader().use { it.readText() })
    }
    val legacy = if (planFile.exists()) AppJson.codec.decodeFromString<SavedPlanSession>(planFile.readText()) else null
    return MobileWorkspace(WorkspaceSnapshot(loadInventory(), legacy))
  }
}
