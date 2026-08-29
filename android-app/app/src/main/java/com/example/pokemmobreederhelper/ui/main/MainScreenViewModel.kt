package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.pokemmobreederhelper.data.ExecutionStepRecord
import com.example.pokemmobreederhelper.data.InventoryRepository
import com.example.pokemmobreederhelper.data.MonsterRecord
import com.example.pokemmobreederhelper.data.PlanRequest
import com.example.pokemmobreederhelper.data.PlannerBridge
import com.example.pokemmobreederhelper.data.PlannerResponse
import com.example.pokemmobreederhelper.data.SavedPlanSession
import com.example.pokemmobreederhelper.data.SpeciesSuggestion
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class MainTab { Inventory, Planner }

data class MainScreenUiState(
  val tab: MainTab = MainTab.Inventory,
  val inventory: List<MonsterRecord> = emptyList(),
  val inventoryQuery: String = "",
  val accountFilter: String = "全部账号",
  val speciesQuery: String = "",
  val speciesSuggestions: List<SpeciesSuggestion> = emptyList(),
  val selectedSpecies: SpeciesSuggestion? = null,
  val nature: String = "",
  val ivs: List<String> = listOf("31", "31", "31", "X", "31", "31"),
  val strategy: String = "inventory",
  val targetAlpha: Boolean = false,
  val allowDitto: Boolean = true,
  val allowAlphaMaterials: Boolean = false,
  val needHiddenAbility: Boolean = false,
  val convertMaternalWithDitto: Boolean = true,
  val lockGender: Boolean = false,
  val targetGender: String = "F",
  val isPlanning: Boolean = false,
  val plannerResponse: PlannerResponse? = null,
  val completedChildIds: Set<String> = emptySet(),
  val message: String = "",
  val error: String = "",
)

class MainScreenViewModel(application: Application) : AndroidViewModel(application) {
  private val repository = InventoryRepository(application.applicationContext)
  private val plannerBridge by lazy { PlannerBridge(application.applicationContext) }
  private var speciesSearchJob: Job? = null
  private val restoredSession = repository.loadPlanSession()
  private val _uiState =
    MutableStateFlow(
      MainScreenUiState(
        inventory = repository.inventory.value,
        plannerResponse = restoredSession?.response,
        completedChildIds = restoredSession?.completedChildIds.orEmpty(),
      )
    )
  val uiState: StateFlow<MainScreenUiState> = _uiState.asStateFlow()

  fun selectTab(tab: MainTab) = _uiState.update { it.copy(tab = tab) }

  fun setInventoryQuery(value: String) = _uiState.update { it.copy(inventoryQuery = value) }

  fun setAccountFilter(value: String) = _uiState.update { it.copy(accountFilter = value) }

  fun importInventory(uri: Uri) {
    viewModelScope.launch {
      runCatching {
        val raw = withContext(Dispatchers.IO) {
          getApplication<Application>().contentResolver.openInputStream(uri)?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }
            ?: throw IOException("无法读取所选文件。")
        }
        withContext(Dispatchers.IO) { repository.importInventory(raw) }
      }.onSuccess { summary ->
        _uiState.update {
          it.copy(
            inventory = repository.inventory.value,
            plannerResponse = null,
            completedChildIds = emptySet(),
            message = "已导入 ${summary.count} 只素材，${summary.accountCount} 个账号；已确认 ${summary.verifiedCount} 只。",
            error = "",
          )
        }
      }.onFailure { throwable ->
        _uiState.update { it.copy(error = "导入失败：${throwable.message ?: "JSON 格式不正确"}", message = "") }
      }
    }
  }

  fun setSpeciesQuery(value: String) {
    _uiState.update {
      it.copy(
        speciesQuery = value,
        selectedSpecies = it.selectedSpecies?.takeIf { selected -> selected.displayName == value },
        speciesSuggestions = if (value.isBlank()) emptyList() else it.speciesSuggestions,
      )
    }
    speciesSearchJob?.cancel()
    if (value.isBlank()) return
    speciesSearchJob = viewModelScope.launch {
      delay(250)
      val suggestions = runCatching {
        withContext(Dispatchers.Default) { plannerBridge.searchSpecies(value) }
      }.getOrElse { emptyList() }
      if (_uiState.value.speciesQuery == value) {
        _uiState.update { it.copy(speciesSuggestions = suggestions) }
      }
    }
  }

  fun chooseSpecies(value: SpeciesSuggestion) {
    _uiState.update {
      it.copy(speciesQuery = value.displayName, selectedSpecies = value, speciesSuggestions = emptyList())
    }
  }

  fun setNature(value: String) = _uiState.update { it.copy(nature = value) }

  fun setIv(index: Int, value: String) {
    if (index !in 0..5) return
    val normalized = value.uppercase().take(2)
    _uiState.update { state ->
      state.copy(ivs = state.ivs.toMutableList().also { it[index] = normalized })
    }
  }

  fun setStrategy(value: String) = _uiState.update { it.copy(strategy = value) }
  fun setTargetAlpha(value: Boolean) = _uiState.update { it.copy(targetAlpha = value) }
  fun setAllowDitto(value: Boolean) = _uiState.update { it.copy(allowDitto = value) }
  fun setAllowAlphaMaterials(value: Boolean) = _uiState.update { it.copy(allowAlphaMaterials = value) }
  fun setNeedHiddenAbility(value: Boolean) = _uiState.update { it.copy(needHiddenAbility = value) }
  fun setConvertMaternal(value: Boolean) = _uiState.update { it.copy(convertMaternalWithDitto = value) }
  fun setLockGender(value: Boolean) = _uiState.update { it.copy(lockGender = value) }
  fun setTargetGender(value: String) = _uiState.update { it.copy(targetGender = value) }

  fun generatePlan() {
    val state = _uiState.value
    val species = state.selectedSpecies?.displayName ?: state.speciesQuery.trim()
    if (species.isBlank()) {
      _uiState.update { it.copy(error = "请先输入并选择目标精灵。") }
      return
    }
    val invalidIv = state.ivs.firstOrNull { value ->
      value.isNotBlank() && value.uppercase() != "X" && value.toIntOrNull()?.let { it !in 0..31 } != false
    }
    if (invalidIv != null) {
      _uiState.update { it.copy(error = "个体值只能填写 0–31 或 X。") }
      return
    }
    val request =
      PlanRequest(
        species = species,
        nature = state.nature.trim(),
        ivs = state.ivs.map { it.ifBlank { "X" } },
        targetAlpha = state.targetAlpha,
        allowDitto = state.allowDitto,
        strategy = state.strategy,
        allowAlphaMaterials = state.allowAlphaMaterials,
        needHiddenAbility = state.needHiddenAbility,
        convertMaternalWithDitto = state.convertMaternalWithDitto,
        lockGender = state.lockGender,
        targetGender = state.targetGender,
      )
    _uiState.update { it.copy(isPlanning = true, error = "", message = "", speciesSuggestions = emptyList()) }
    viewModelScope.launch {
      val response = runCatching {
        withContext(Dispatchers.Default) { plannerBridge.generatePlan(repository.inventoryJson(), request) }
      }.getOrElse { throwable ->
        PlannerResponse(error = throwable.message ?: "规划器运行失败")
      }
      _uiState.update {
        it.copy(
          isPlanning = false,
          plannerResponse = response,
          completedChildIds = emptySet(),
          error = if (response.ok) "" else response.error.ifBlank { "没有找到可执行路线。" },
          message = if (response.ok) "已生成最佳路线，可从绿色的可执行步骤开始。" else "",
        )
      }
      repository.savePlanSession(SavedPlanSession(response, emptySet()))
    }
  }

  fun toggleStep(step: ExecutionStepRecord) {
    val state = _uiState.value
    val response = state.plannerResponse ?: return
    val completed = state.completedChildIds
    val childId = step.child.id
    val updated = if (childId in completed) {
      val hasCompletedDependent = response.plan?.steps.orEmpty().any { other ->
        other.child.id in completed && childId in other.dependencies
      }
      if (hasCompletedDependent) {
        _uiState.update { it.copy(error = "请先撤销依赖这一步的上层步骤。") }
        return
      }
      completed - childId
    } else {
      if (!completed.containsAll(step.dependencies)) {
        _uiState.update { it.copy(error = "这一步的下层素材还没有完成。") }
        return
      }
      completed + childId
    }
    _uiState.update {
      it.copy(
        completedChildIds = updated,
        error = "",
        message = if (childId in updated) "步骤 ${step.number} 已完成。" else "已撤销步骤 ${step.number}。",
      )
    }
    repository.savePlanSession(SavedPlanSession(response, updated))
  }

  fun clearMessage() = _uiState.update { it.copy(message = "", error = "") }
}
