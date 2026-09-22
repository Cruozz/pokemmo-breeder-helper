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
import com.example.pokemmobreederhelper.data.WorkspaceSnapshot
import com.example.pokemmobreederhelper.data.StepOutcome
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
  val targetMoves: List<String> = emptyList(),
  val availableMoves: List<String> = emptyList(),
  val ivs: List<String> = List(6) { "X" },
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
  val pendingResponse: PlannerResponse? = null,
  val planningFailure: PlannerResponse? = null,
  val pendingStep: ExecutionStepRecord? = null,
  val canUndo: Boolean = false,
)

private fun MainScreenUiState.withRequest(request: PlanRequest): MainScreenUiState = copy(
  speciesQuery = request.species, selectedSpecies = null, speciesSuggestions = emptyList(), nature = request.nature, ivs = request.ivs,
  strategy = request.strategy, targetAlpha = request.targetAlpha, allowDitto = request.allowDitto,
  allowAlphaMaterials = request.allowAlphaMaterials, needHiddenAbility = request.needHiddenAbility,
  convertMaternalWithDitto = request.convertMaternalWithDitto, lockGender = request.lockGender,
  targetGender = request.targetGender, targetMoves = request.targetMoves,
)

class MainScreenViewModel(application: Application) : AndroidViewModel(application) {
  private val repository = InventoryRepository(application.applicationContext)
  private val plannerBridge by lazy { PlannerBridge(application.applicationContext) }
  private var speciesSearchJob: Job? = null
  private var planningGeneration = 0
  private var planningJob: Job? = null
  private var lastPlanningRequest: PlanRequest? = null
  private val restoredSession = repository.loadPlanSession()
  private val _uiState =
    MutableStateFlow(
      MainScreenUiState(
        inventory = repository.inventory.value,
        plannerResponse = restoredSession?.response,
        completedChildIds = restoredSession?.completedChildIds.orEmpty(),
        canUndo = repository.canUndo,
        error = repository.loadError,
      ).let { state -> repository.loadTarget()?.let { state.withRequest(it) } ?: state }
    )
  val uiState: StateFlow<MainScreenUiState> = _uiState.asStateFlow()

  init {
    val species = _uiState.value.speciesQuery
    if (species.isNotBlank()) viewModelScope.launch {
      val match = withContext(Dispatchers.Default) {
        runCatching { plannerBridge.searchSpecies(species).firstOrNull { it.displayName == species } }.getOrNull()
      }
      if (match != null && _uiState.value.speciesQuery == species) {
        _uiState.update { it.copy(selectedSpecies = match, availableMoves = match.eggMoves) }
      }
    }
  }

  fun selectTab(tab: MainTab) = _uiState.update { it.copy(tab = tab) }

  fun setInventoryQuery(value: String) = _uiState.update { it.copy(inventoryQuery = value) }

  fun setAccountFilter(value: String) = _uiState.update { it.copy(accountFilter = value) }

  fun importInventory(uri: Uri) {
    if (_uiState.value.isPlanning) return
    _uiState.update { it.copy(isPlanning = true) }
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
            pendingResponse = null, planningFailure = null, isPlanning = false, canUndo = repository.canUndo,
          )
        }
      }.onFailure { throwable ->
        _uiState.update { it.copy(error = "导入失败：${throwable.message ?: "JSON 格式不正确"}", message = "", isPlanning = false) }
      }
    }
  }

  fun setSpeciesQuery(value: String) {
    _uiState.update {
      it.copy(
        speciesQuery = value,
        targetMoves = if (value == it.speciesQuery) it.targetMoves else emptyList(),
        availableMoves = if (value == it.speciesQuery) it.availableMoves else emptyList(),
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
      it.copy(speciesQuery = value.displayName, selectedSpecies = value, speciesSuggestions = emptyList(),
        availableMoves = value.eggMoves, targetMoves = if (it.speciesQuery == value.displayName) it.targetMoves.filter { move -> move in value.eggMoves } else emptyList())
    }
  }

  fun toggleTargetMove(move: String) {
    _uiState.update { state ->
      when {
        move in state.targetMoves -> state.copy(targetMoves = state.targetMoves - move)
        move !in state.availableMoves -> state
        state.targetMoves.size >= 4 -> state.copy(error = "最多选择 4 个遗传技能。")
        else -> state.copy(targetMoves = state.targetMoves + move, error = "")
      }
    }
  }

  fun clearPlanning() {
    // Completion/import writes must finish; only a pure search can be invalidated.
    if (_uiState.value.isPlanning && planningJob == null) return
    val state = _uiState.value
    val target = PlanRequest(species = state.speciesQuery, nature = state.nature, ivs = state.ivs,
      strategy = state.strategy, targetAlpha = state.targetAlpha, allowDitto = state.allowDitto,
      allowAlphaMaterials = state.allowAlphaMaterials, needHiddenAbility = state.needHiddenAbility,
      convertMaternalWithDitto = state.convertMaternalWithDitto, lockGender = state.lockGender,
      targetGender = state.targetGender, targetMoves = state.targetMoves)
    runCatching { repository.clearPlanSession(target) }.onSuccess {
      planningGeneration++
      planningJob?.cancel()
      planningJob = null
      lastPlanningRequest = null
      _uiState.update { it.copy(plannerResponse = null, pendingResponse = null,
        planningFailure = null, pendingStep = null, completedChildIds = emptySet(),
        isPlanning = false, canUndo = repository.canUndo, error = "",
        message = "当前规划与路线已清除，库存和已完成子代保留。") }
    }.onFailure { fail(it) }
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
    if (state.isPlanning) return
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
        preferredMaterialIds = state.plannerResponse?.plan?.planningOptions?.preferredMaterialIds.orEmpty(),
        excludedIds = state.plannerResponse?.plan?.planningOptions?.excludedIds.orEmpty(),
        targetMoves = state.targetMoves,
      )
    startPlanning(request)
  }

  private fun startPlanning(request: PlanRequest) {
    if (_uiState.value.isPlanning) return
    val generation = ++planningGeneration
    val inventoryJson = repository.inventoryJson()
    lastPlanningRequest = request
    _uiState.update { it.copy(isPlanning = true, error = "", message = "", speciesSuggestions = emptyList(),
      pendingResponse = null, planningFailure = null) }
    planningJob = viewModelScope.launch {
      val response = runCatching {
        withContext(Dispatchers.Default) { plannerBridge.generatePlan(inventoryJson, request) }
      }.getOrElse { throwable ->
        PlannerResponse(error = throwable.message ?: "规划器运行失败")
      }
      if (generation != planningGeneration) return@launch
      planningJob = null
      _uiState.update {
        it.copy(
          isPlanning = false,
          pendingResponse = response.takeIf { result -> result.ok },
          planningFailure = response.takeUnless { result -> result.ok },
          error = if (response.ok) "" else response.error.ifBlank { "没有找到可执行路线。" },
          message = if (response.ok) "建议已生成。确认启用前，原路线和库存不会改变。" else "",
        )
      }
    }
  }

  fun suggestNext() {
    if (_uiState.value.isPlanning) return
    val request = _uiState.value.plannerResponse?.plan?.planningOptions
    if (request != null) {
      _uiState.update { it.withRequest(request) }
      startPlanning(request)
    } else generatePlan()
  }

  fun retryPlanning() {
    lastPlanningRequest?.let(::startPlanning) ?: suggestNext()
  }

  fun dismissSuggestion() = _uiState.update { it.copy(pendingResponse = null) }

  fun activateSuggestion() {
    val state = _uiState.value
    if (state.isPlanning) return
    val response = state.pendingResponse ?: return
    runCatching {
      repository.savePlanSession(SavedPlanSession(response, request = response.plan?.planningOptions))
    }.onSuccess {
      _uiState.update { it.copy(plannerResponse = response, completedChildIds = emptySet(),
        pendingResponse = null, canUndo = repository.canUndo, error = "", message = "新路线已启用；点击可执行节点核对并完成。")
        .let { updated -> response.plan?.planningOptions?.let { request -> updated.withRequest(request) } ?: updated } }
    }.onFailure { fail(it) }
  }

  fun toggleStep(step: ExecutionStepRecord) {
    val state = _uiState.value
    if (state.isPlanning) return
    if (state.plannerResponse?.rulesVersion != "0.2.8") {
      _uiState.update { it.copy(error = "请重新生成并启用路线。") }; return
    }
    if (state.plannerResponse.plan?.needsReplan == true || step.child.id in state.completedChildIds ||
      !state.completedChildIds.containsAll(step.dependencies)) return
    _uiState.update { it.copy(pendingStep = step) }
  }

  fun dismissCompletion() = _uiState.update { it.copy(pendingStep = null) }

  fun completeStep(gender: String, natureHit: Boolean?) {
    val state = _uiState.value
    if (state.isPlanning) return
    val step = state.pendingStep ?: return
    val response = state.plannerResponse ?: return
    _uiState.update { it.copy(isPlanning = true, pendingStep = null) }
    viewModelScope.launch {
      runCatching {
        val result = withContext(Dispatchers.Default) {
          plannerBridge.completeStep(repository.inventoryJson(), response, StepOutcome(step.number, gender, natureHit))
        }
        check(result.ok) { result.error }
        val next = checkNotNull(result.response)
        val completed = next.plan?.steps.orEmpty().filter { it.completed }.map { it.child.id }.toSet()
        withContext(Dispatchers.IO) {
          repository.replace(WorkspaceSnapshot(result.inventory, SavedPlanSession(next, completed, next.plan?.planningOptions)))
        }
        _uiState.update { it.copy(inventory = result.inventory, plannerResponse = next,
          completedChildIds = completed, pendingResponse = null, planningFailure = null, isPlanning = false,
          canUndo = repository.canUndo, message = result.message, error = "") }
        // Save the completed egg first. Suggestion generation must not replace
        // the active route or overwrite the completion's undo checkpoint.
        if (next.plan?.needsReplan == true) suggestNext()
      }.onFailure { fail(it) }
    }
  }

  fun markInProgress() {
    val state = _uiState.value
    val step = state.pendingStep ?: return
    val response = state.plannerResponse ?: return
    val plan = response.plan ?: return
    val updated = response.copy(plan = plan.copy(steps = plan.steps.map {
      if (it.child.id == step.child.id) it.copy(inProgress = !it.inProgress) else it
    }))
    runCatching {
      repository.replace(WorkspaceSnapshot(state.inventory,
        SavedPlanSession(updated, state.completedChildIds, plan.planningOptions)), checkpoint = false)
      _uiState.update { it.copy(plannerResponse = updated, pendingStep = null,
        message = "孵化中标记仅作备忘，不核销、不解锁上层。") }
    }.onFailure { fail(it) }
  }

  fun undoLastAction() {
    if (_uiState.value.isPlanning) return
    runCatching {
      if (repository.undo()) {
        val session = repository.loadPlanSession()
        _uiState.update { it.copy(inventory = repository.inventory.value,
          plannerResponse = session?.response, completedChildIds = session?.completedChildIds.orEmpty(),
          pendingResponse = null, planningFailure = null, pendingStep = null, canUndo = repository.canUndo,
          message = "已恢复上次操作前的库存与路线。", error = "")
          .let { updated -> session?.request?.let { updated.withRequest(it) } ?: updated } }
      }
    }.onFailure { fail(it) }
  }

  fun exportInventory(uri: Uri) {
    if (_uiState.value.isPlanning) return
    viewModelScope.launch {
      runCatching {
        val raw = repository.inventoryJson()
        withContext(Dispatchers.IO) {
          getApplication<Application>().contentResolver.openOutputStream(uri, "wt")?.bufferedWriter(Charsets.UTF_8)?.use { it.write(raw) }
            ?: throw IOException("无法写入所选文件。")
        }
        _uiState.update { it.copy(message = "当前库存已导出，可备份或传回电脑。", error = "") }
      }.onFailure { fail(it) }
    }
  }

  private fun fail(error: Throwable) {
    _uiState.update { it.copy(isPlanning = false, error = error.message ?: "操作失败，原数据保留。", message = "") }
  }

  fun clearMessage() = _uiState.update { it.copy(message = "", error = "") }
}
