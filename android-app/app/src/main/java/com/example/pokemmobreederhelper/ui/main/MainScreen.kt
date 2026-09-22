package com.example.pokemmobreederhelper.ui.main

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.ui.platform.LocalConfiguration
import android.net.Uri
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.example.pokemmobreederhelper.data.ExecutionPlanRecord
import com.example.pokemmobreederhelper.data.ExecutionStepRecord
import com.example.pokemmobreederhelper.data.MonsterRecord
import com.example.pokemmobreederhelper.data.SpeciesSuggestion
import com.example.pokemmobreederhelper.data.genderLabel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
  modifier: Modifier = Modifier,
  viewModel: MainScreenViewModel = viewModel(),
) {
  val state by viewModel.uiState.collectAsStateWithLifecycle()
  var pendingImport by rememberSaveable { mutableStateOf<String?>(null) }
  var confirmUndo by rememberSaveable { mutableStateOf(false) }
  val importer =
    rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
      if (uri != null) pendingImport = uri.toString()
    }
  val exporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
    if (uri != null) viewModel.exportInventory(uri)
  }
  var showMenu by remember { mutableStateOf(false) }

  Scaffold(
    modifier = modifier.fillMaxSize(),
    topBar = {
      TopAppBar(
        title = {
          Row(verticalAlignment = Alignment.CenterVertically) {
            PokemonPortrait(null, Modifier.size(28.dp))
            Spacer(Modifier.width(10.dp))
            Text("PokeMMO 孵蛋助手", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
          }
        },
        actions = {
          Box {
            TextButton(onClick = { showMenu = true }) { Text("更多") }
            androidx.compose.material3.DropdownMenu(expanded = showMenu, onDismissRequest = { showMenu = false }) {
              androidx.compose.material3.DropdownMenuItem(text = { Text("导出库存") }, enabled = !state.isPlanning, onClick = { showMenu = false; exporter.launch("pokemmo-inventory.json") })
              androidx.compose.material3.DropdownMenuItem(text = { Text("撤销上次操作") }, enabled = state.canUndo && !state.isPlanning, onClick = { showMenu = false; confirmUndo = true })
            }
          }
        },
      )
    },
  ) { innerPadding ->
    Column(Modifier.fillMaxSize().padding(innerPadding).imePadding()) {
      PrimaryTabRow(selectedTabIndex = if (state.tab == MainTab.Inventory) 0 else 1) {
        Tab(
          selected = state.tab == MainTab.Inventory,
          onClick = { viewModel.selectTab(MainTab.Inventory) },
          text = { Text("素材库存 ${state.inventory.size}") },
        )
        Tab(
          selected = state.tab == MainTab.Planner,
          onClick = { viewModel.selectTab(MainTab.Planner) },
          text = { Text("孵蛋规划") },
        )
      }
      if (state.message.isNotBlank() || state.error.isNotBlank()) {
        MessageBanner(
          text = state.error.ifBlank { state.message },
          isError = state.error.isNotBlank(),
          onDismiss = viewModel::clearMessage,
        )
      }
      when (state.tab) {
        MainTab.Inventory ->
          PokedexInventory(state, viewModel) { if (!state.isPlanning) importer.launch(arrayOf("application/json", "text/json", "text/plain")) }
        MainTab.Planner -> PlannerScreen(state, viewModel)
      }
    }
  }
  pendingImport?.let { selected ->
    AlertDialog(onDismissRequest = { pendingImport = null }, title = { Text("导入电脑库存") },
      text = { Text("将替换手机库存并清除当前路线。建议先导出库存；本次替换可用“撤销上次操作”恢复。原电脑 JSON 文件不会修改。") },
      confirmButton = { TextButton(onClick = { pendingImport = null; viewModel.importInventory(Uri.parse(selected)) }) { Text("确认导入") } },
      dismissButton = { TextButton(onClick = { pendingImport = null }) { Text("取消") } })
  }
  if (confirmUndo) {
    AlertDialog(onDismissRequest = { confirmUndo = false }, title = { Text("恢复上次操作前的状态？") },
      text = { Text("同时恢复库存与路线，包括核销前的父母及步骤；游戏中的操作不会撤销。再次使用可恢复刚才的状态。") },
      confirmButton = { TextButton(onClick = { confirmUndo = false; viewModel.undoLastAction() }) { Text("确认恢复") } },
      dismissButton = { TextButton(onClick = { confirmUndo = false }) { Text("取消") } })
  }
  state.pendingStep?.let { step ->
    CompletionDialog(step, state.plannerResponse?.plan?.targetNature.orEmpty(),
      viewModel::dismissCompletion, viewModel::completeStep, viewModel::markInProgress)
  }
  state.editingMaterial?.let { MaterialEditor(it, state.materialError, state.isPlanning, viewModel::dismissMaterialEditor, viewModel::saveMaterial, viewModel::searchMaterialSpecies) }
  DuplicateReview(state, viewModel)
  state.referenceLines?.let { lines ->
    AlertDialog(onDismissRequest = viewModel::dismissReference, title = { Text("精灵资料") },
      text = { LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) { items(lines) { Text(it) } } },
      confirmButton = { TextButton(onClick = viewModel::dismissReference) { Text("关闭") } })
  }
}

@Composable
internal fun CompletionDialog(step: ExecutionStepRecord, targetNature: String,
  onDismiss: () -> Unit, onComplete: (String, Boolean?) -> Unit, onMemo: () -> Unit) {
  var gender by rememberSaveable(step.child.id) { mutableStateOf("") }
  var natureChoice by rememberSaveable(step.child.id) { mutableStateOf("") }
  val canConfirm = (step.genderPolicy != "random" || gender.isNotEmpty()) &&
    (!step.shouldCheckNature || natureChoice.isNotEmpty())
  AlertDialog(onDismissRequest = onDismiss, title = { Text("完成步骤 ${step.number} 并核销") },
    text = {
      Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("仅在游戏中实际孵完后确认。父母会从手机库存核销；中间代入库，最终成品不入库。")
        Text("父母 A：${step.parentALabel}\n携带：${step.itemA.ifBlank { "无" }}")
        Text("父母 B：${step.parentBLabel}\n携带：${step.itemB.ifBlank { "无" }}")
        if (step.requiresPurchase) Text("请确认交易行素材已购买并用于孵化，无需另行扫描入库。", color = MaterialTheme.colorScheme.error)
        Text(step.genderInstruction)
        if (step.genderPolicy == "random") {
          Text("实际孵出的性别（必选）")
          FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("F", "M").forEach { value -> FilterChip(selected = gender == value,
              onClick = { gender = value }, label = { Text(genderLabel(value)) }) }
          }
        }
        if (step.shouldCheckNature) {
          Text("是否爆出 $targetNature？（必选）")
          FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = natureChoice == "hit", onClick = { natureChoice = "hit" }, label = { Text("已爆目标性格") })
            FilterChip(selected = natureChoice == "miss", onClick = { natureChoice = "miss" }, label = { Text("没有爆性格") })
          }
        }
        OutlinedButton(onClick = onMemo, modifier = Modifier.fillMaxWidth()) {
          Text(if (step.inProgress) "取消孵化中备注" else "只标记孵化中，不核销")
        }
      }
    },
    confirmButton = { Button(enabled = canConfirm, onClick = {
      onComplete(gender, if (step.shouldCheckNature) natureChoice == "hit" else null)
    }) { Text("确认已孵完") } },
    dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } })
}

@Composable
private fun MessageBanner(text: String, isError: Boolean, onDismiss: () -> Unit) {
  Surface(color = if (isError) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.secondaryContainer) {
    Row(
      modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
      verticalAlignment = Alignment.CenterVertically,
    ) {
      Text(
        text,
        modifier = Modifier.weight(1f),
        color = if (isError) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onSecondaryContainer,
        style = MaterialTheme.typography.bodyMedium,
      )
      TextButton(onClick = onDismiss, modifier = Modifier.heightIn(min = 44.dp)) { Text("知道了") }
    }
  }
}

@Composable
private fun MonsterCard(monster: MonsterRecord) {
  OutlinedCard {
    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
          monster.species.ifBlank { "未知精灵" },
          modifier = Modifier.weight(1f),
          style = MaterialTheme.typography.titleMedium,
          fontWeight = FontWeight.SemiBold,
        )
        StatusPill(if (monster.isAlpha) "头目" else "普通", monster.isAlpha)
        Spacer(Modifier.width(6.dp))
        StatusPill(genderLabel(monster.gender), monster.gender.uppercase() == "F")
      }
      Row(verticalAlignment = Alignment.CenterVertically) {
        Text("${monster.perfectIvCount}V", color = MaterialTheme.colorScheme.secondary, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(8.dp))
        Text(monster.ivText, fontWeight = FontWeight.Medium)
        if (monster.hasHiddenAbility) {
          Spacer(Modifier.width(8.dp))
          Text("梦特", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
        }
      }
      Text("${monster.account} · ${monster.positionLabel.ifBlank { "未记录位置" }} · ${monster.nature.ifBlank { "性格未知" }}")
      if (monster.eggGroups.isNotEmpty()) {
        Text("蛋组：${monster.eggGroups.joinToString(" / ")}", style = MaterialTheme.typography.bodySmall)
      }
    }
  }
}

@Composable
private fun StatusPill(text: String, accent: Boolean) {
  Surface(
    color = if (accent) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceVariant,
    shape = RoundedCornerShape(50),
  ) {
    Text(text, modifier = Modifier.padding(horizontal = 9.dp, vertical = 4.dp), fontSize = 12.sp)
  }
}

@Composable
internal fun PlannerScreen(state: MainScreenUiState, viewModel: MainScreenViewModel) {
  val preview = state.showingSuggestion
  val displayedResponse = if (preview) state.pendingResponse else state.plannerResponse
  val plan = displayedResponse?.plan
  val displayedCompleted = if (preview) emptySet() else state.completedChildIds
  val listState = rememberLazyListState()
  var formExpanded by rememberSaveable { mutableStateOf(plan == null) }
  var stepFilter by rememberSaveable { mutableStateOf(PlanStepFilter.Actionable) }
  var planView by rememberSaveable { mutableStateOf(PlanViewMode.MindMap) }
  var showColorGuide by rememberSaveable { mutableStateOf(false) }
  var showMaterials by rememberSaveable { mutableStateOf(false) }
  val mapHeight = (LocalConfiguration.current.screenHeightDp * 0.6f).coerceIn(300f, 560f).dp
  LaunchedEffect(state.pendingResponse?.plan?.id) {
    if (state.pendingResponse != null) listState.scrollToItem(0)
  }
  LaunchedEffect(state.planningFailure, state.isPlanning) {
    if (state.planningFailure != null || state.isPlanning) listState.scrollToItem(0)
  }

  LaunchedEffect(plan?.id) {
    if (plan != null) {
      formExpanded = false
      stepFilter = if (preview) PlanStepFilter.All else PlanStepFilter.Actionable
      planView = PlanViewMode.MindMap
      listState.scrollToItem(0)
    }
  }

  LazyColumn(
    state = listState,
    modifier = Modifier.fillMaxSize(),
    contentPadding = PaddingValues(12.dp),
    verticalArrangement = Arrangement.spacedBy(10.dp),
  ) {
    item {
      OutlinedButton(onClick = viewModel::clearPlanning, modifier = Modifier.fillMaxWidth()) {
        Text("清除当前规划与路线")
      }
    }
    if (state.plannerResponse != null && state.previewRequest != null) {
      item {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
          FilterChip(selected = preview, onClick = { viewModel.showSuggestion(true) }, label = { Text("预览建议") })
          FilterChip(selected = !preview, onClick = { viewModel.showSuggestion(false) }, label = { Text("执行路线") })
        }
      }
    }
    if (preview && state.pendingResponse != null) {
      item {
        OutlinedCard {
          Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("新路线建议 · 尚未启用", style = MaterialTheme.typography.titleMedium)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
              Button(onClick = viewModel::activateSuggestion, enabled = !state.isPlanning) { Text("确认启用建议") }
              TextButton(onClick = viewModel::dismissSuggestion, enabled = !state.isPlanning) { Text(if (state.plannerResponse != null) "保留原路线" else "放弃建议") }
            }
          }
        }
      }
    }
    if (preview && state.previewRequest?.excludedIds?.isNotEmpty() == true) {
      item {
        Column {
          Text("本轮已禁用 ${state.previewRequest.excludedIds.size} 只素材")
          Text(state.inventory.filter { it.id in state.previewRequest.excludedIds }
            .joinToString("、") { "${it.species} ${it.positionLabel}" }, style = MaterialTheme.typography.bodySmall)
          TextButton(onClick = viewModel::restorePreviewMaterials, enabled = !state.isPlanning) { Text("恢复全部并重算") }
        }
      }
    }
    state.planningFailure?.let { failure ->
      item {
        Column(Modifier.fillMaxWidth().padding(4.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
          Text("本次规划未生成", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.error)
          Text(failure.error)
          Text("库存与已完成步骤保留")
          if (failure.report.isNotBlank()) PlanReport(failure.report, initiallyExpanded = true)
          Button(onClick = viewModel::retryPlanning, enabled = !state.isPlanning) { Text("重试本次规划") }
        }
      }
    }
    if (state.isPlanning) {
      item {
        Card {
          Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
              CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 3.dp)
              Spacer(Modifier.width(12.dp))
              Text("正在规划……")
            }
            LinearProgressIndicator(Modifier.fillMaxWidth())
          }
        }
      }
    }
    if (formExpanded || plan == null) {
      item { PlannerForm(state, viewModel) }
    }
    displayedResponse?.let { response ->
      val responsePlan = response.plan
      if (responsePlan != null) {
        val visibleSteps = responsePlan.steps.filter { step ->
          val complete = step.child.id in displayedCompleted
          val ready = !preview && !state.isPlanning && !responsePlan.needsReplan && !complete && displayedCompleted.containsAll(step.dependencies)
          when (stepFilter) {
            PlanStepFilter.All -> true
            PlanStepFilter.Actionable -> ready
            PlanStepFilter.Incomplete -> !complete
            PlanStepFilter.Completed -> complete
          }
        }
        item {
          PlanSummary(
            plan = responsePlan,
            candidateCount = response.candidateCount,
            completed = displayedCompleted,
            onEdit = { formExpanded = !formExpanded },
            preview = preview,
          )
        }
        if (!preview && (responsePlan.needsReplan || response.rulesVersion != "0.2.8")) {
          item {
            OutlinedCard {
              Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("路线已暂停", style = MaterialTheme.typography.titleMedium)
                Text(responsePlan.replanReason.ifBlank { "请重新生成路线。" })
                Button(onClick = viewModel::suggestNext, enabled = !state.isPlanning) { Text("按原目标生成建议") }
              }
            }
          }
        }
        if (responsePlan.retainedMaterials.isNotEmpty()) {
          item { Text("已保留的母体 / 性格手", style = MaterialTheme.typography.titleMedium) }
          items(responsePlan.retainedMaterials, key = { "retained-${it.id}" }) { MonsterCard(it) }
        }
        if (responsePlan.steps.isNotEmpty()) {
          item { PlanViewChooser(planView) { planView = it } }
        }
        if (preview) {
          val materialIds = responsePlan.steps.flatMap { listOf(it.parentAId, it.parentBId) }.toSet()
          val materials = state.inventory.filter { it.id in materialIds }
          if (materials.isNotEmpty()) {
            item { TextButton(onClick = { showMaterials = !showMaterials }) { Text(if (showMaterials) "收起本轮素材" else "本轮素材 · ${materials.size} 只") } }
            if (showMaterials) items(materials, key = { "preview-material-${it.id}" }) { material ->
              OutlinedCard {
                Column(Modifier.padding(12.dp)) {
                  Text("${material.species} · ${material.ivText}")
                  Text("${material.account} · ${material.positionLabel.ifBlank { "未定位" }} · ${material.nature}", style = MaterialTheme.typography.bodySmall)
                  TextButton(onClick = { viewModel.excludePreviewMaterial(material.id) }, enabled = !state.isPlanning) { Text("本轮禁用并重算") }
                }
              }
            }
          }
        }
        if (responsePlan.steps.isNotEmpty() && planView == PlanViewMode.MindMap) {
          item {
            Column {
              TextButton(onClick = { showColorGuide = !showColorGuide }) {
                Text(if (showColorGuide) "收起颜色说明" else "颜色说明")
              }
              if (showColorGuide) {
                Text("边框 / 连线：蓝＝母体，紫＝性格手，灰蓝＝IV素材；橙色双框 / 双线＝遗传技能。底色：蓝＝公，粉＝母，灰＝无性别或未锁定。", style = MaterialTheme.typography.bodySmall)
              }
            }
          }
          item {
            BreedingMindMap(
              plan = responsePlan,
              completed = displayedCompleted,
              onToggleStep = viewModel::toggleStep,
              modifier = Modifier.fillMaxWidth().height(mapHeight),
              preview = preview,
              excludedMaterialAction = if (preview && !state.isPlanning) viewModel::excludePreviewMaterial else null,
              inventoryIds = state.inventory.map { it.id }.toSet(),
              onMarkInProgress = if (!preview && !state.isPlanning) viewModel::toggleInProgress else null,
            )
          }
        }
        if (!preview && responsePlan.steps.isNotEmpty() && planView == PlanViewMode.Steps) {
          item {
            PlanStepFilters(
              selected = stepFilter,
              plan = responsePlan,
              completed = displayedCompleted,
              onSelect = { stepFilter = it },
            )
          }
        }
        if (!preview && visibleSteps.isEmpty() && responsePlan.steps.isNotEmpty() && planView == PlanViewMode.Steps) {
          item { EmptyStepFilter(stepFilter) }
        }
        if (planView == PlanViewMode.Steps) {
          items(if (preview) responsePlan.steps else visibleSteps, key = { it.child.id }) { step ->
            val complete = step.child.id in displayedCompleted
            val ready = !preview && !state.isPlanning && !responsePlan.needsReplan && !complete && displayedCompleted.containsAll(step.dependencies)
            PlanStepCard(step, complete, ready, preview = preview) { viewModel.toggleStep(step) }
          }
        }
        item { PlanReport(response.report) }
      } else if (response.report.isNotBlank()) {
        item { PlanReport(response.report, initiallyExpanded = true) }
      }
    }
  }
}

private enum class PlanStepFilter { All, Actionable, Incomplete, Completed }

private enum class PlanViewMode { MindMap, Steps }

@Composable
private fun PlanViewChooser(selected: PlanViewMode, onSelect: (PlanViewMode) -> Unit) {
  Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    FilterChip(
      selected = selected == PlanViewMode.MindMap,
      onClick = { onSelect(PlanViewMode.MindMap) },
      label = { Text("思维导图") },
      modifier = Modifier.weight(1f),
    )
    FilterChip(
      selected = selected == PlanViewMode.Steps,
      onClick = { onSelect(PlanViewMode.Steps) },
      label = { Text("步骤清单") },
      modifier = Modifier.weight(1f),
    )
  }
}

@Composable
private fun PlannerForm(state: MainScreenUiState, viewModel: MainScreenViewModel) {
  var advancedExpanded by rememberSaveable { mutableStateOf(false) }
  val activeAdvancedOptions = listOf(
    state.natureStrategy == "chain",
    state.intermediateGenderStrategy != "lock_all",
    state.targetAlpha,
    state.allowDitto,
    state.convertMaternalWithDitto,
    state.allowAlphaMaterials,
    state.needHiddenAbility,
    state.lockGender,
  ).count { it }
  OutlinedCard {
    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        PokemonPortrait(state.selectedSpecies?.id ?: 447)
        Column(Modifier.weight(1f)) {
          Text("目标与规则", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
          Text("${state.ivs.count { it == "31" }}V · ${state.nature.ifBlank { "性格不限" }}", color = MaterialTheme.colorScheme.secondary)
        }
      }
      OutlinedTextField(
        value = state.speciesQuery,
        onValueChange = viewModel::setSpeciesQuery,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("目标精灵（中文、英文或图鉴编号）") },
        singleLine = true,
      )
      if (state.speciesSuggestions.isNotEmpty()) {
        SpeciesSuggestions(state.speciesSuggestions, viewModel::chooseSpecies)
      }
      state.selectedSpecies?.let { selected ->
        Text(
          "已选 #${selected.id} ${selected.displayName} · 蛋组 ${selected.eggGroups.joinToString(" / ")}"
            + if (selected.offspringSpecies != selected.displayName) " · 实际孵出 ${selected.offspringSpecies}" else "",
          color = MaterialTheme.colorScheme.secondary,
          style = MaterialTheme.typography.bodySmall,
        )
        TextButton(onClick = viewModel::showSpeciesReference) { Text("查看分布与遗传来源") }
      }
      NaturePicker(state.nature, viewModel::setNature)
      Text("遗传技能（${state.targetMoves.size}/4）", fontWeight = FontWeight.SemiBold)
      if (state.availableMoves.isEmpty() && state.targetMoves.isEmpty()) {
        Text("选择搜索结果中的精灵后，可查看可遗传技能。", style = MaterialTheme.typography.bodySmall)
      }
      FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        (state.availableMoves + state.targetMoves).distinct().forEach { move ->
          FilterChip(selected = move in state.targetMoves, onClick = { viewModel.toggleTargetMove(move) },
            label = { Text(move) })
        }
      }
      Text("目标个体值", fontWeight = FontWeight.SemiBold)
      IvFields(state.ivs, viewModel::setIv)
      Text("计算策略", fontWeight = FontWeight.SemiBold)
      Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(
          selected = state.strategy == "inventory",
          onClick = { viewModel.setStrategy("inventory") },
          label = { Text("库存优先") },
        )
        FilterChip(
          selected = state.strategy == "steps",
          onClick = { viewModel.setStrategy("steps") },
          label = { Text("步骤优先") },
        )
      }
      HorizontalDivider()
      Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
          Text("高级规则", fontWeight = FontWeight.SemiBold)
          Text(
            "已启用 $activeAdvancedOptions 项",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
        }
        TextButton(onClick = { advancedExpanded = !advancedExpanded }, modifier = Modifier.heightIn(min = 48.dp)) {
          Text(if (advancedExpanded) "收起" else "展开")
        }
      }
      if (advancedExpanded) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
          OptionSwitch("全程锁性格", "不变石链；关闭时逐级尝试目标性格", state.natureStrategy == "chain") {
            viewModel.setNatureStrategy(if (it) "chain" else "late")
          }
          Text("中间代性别", fontWeight = FontWeight.SemiBold)
          FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("lock_all" to "全程锁定", "smart" to "智能锁定", "minimal" to "尽量不锁").forEach { (key, label) ->
              FilterChip(selected = state.intermediateGenderStrategy == key,
                onClick = { viewModel.setIntermediateGenderStrategy(key) }, label = { Text(label) })
            }
          }
          OptionSwitch("孵化头目成品", "关闭时只规划普通成品", state.targetAlpha, viewModel::setTargetAlpha)
          OptionSwitch("允许使用百变怪", "可参与母体或其他支线", state.allowDitto, viewModel::setAllowDitto)
          OptionSwitch(
            "使用百变怪转换母体",
            "即使关闭上项，也允许一次目标公体转母体",
            state.convertMaternalWithDitto,
            viewModel::setConvertMaternal,
          )
          OptionSwitch(
            "普通目标允许使用头目素材",
            "最终仍为普通，但会消耗头目库存",
            state.allowAlphaMaterials,
            viewModel::setAllowAlphaMaterials,
          )
          OptionSwitch("成品保留梦特", "要求目标母系携带梦特潜力", state.needHiddenAbility, viewModel::setNeedHiddenAbility)
          OptionSwitch("锁定成品性别", "不勾选表示公母都可以；特殊进化会自动锁定", state.lockGender, viewModel::setLockGender)
          if (state.lockGender) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
              FilterChip(selected = state.targetGender == "F", onClick = { viewModel.setTargetGender("F") }, label = { Text("母") })
              FilterChip(selected = state.targetGender == "M", onClick = { viewModel.setTargetGender("M") }, label = { Text("公") })
            }
          }
        }
      }
      Button(
        onClick = viewModel::generatePlan,
        enabled = !state.isPlanning,
        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
      ) {
        Text(if (state.isPlanning) "正在生成规划" else "生成最佳孵蛋路线")
      }
    }
  }
}

@Composable
private fun SpeciesSuggestions(items: List<SpeciesSuggestion>, onChoose: (SpeciesSuggestion) -> Unit) {
  OutlinedCard {
    Column(Modifier.fillMaxWidth()) {
      items.take(8).forEachIndexed { index, item ->
        Row(
          Modifier.fillMaxWidth().clickable { onChoose(item) }.padding(horizontal = 12.dp, vertical = 11.dp),
          verticalAlignment = Alignment.CenterVertically,
        ) {
          Text("#${item.id}", color = MaterialTheme.colorScheme.primary, modifier = Modifier.width(54.dp))
          Column(Modifier.weight(1f)) {
            Text(item.displayName, fontWeight = FontWeight.SemiBold)
            Text(item.eggGroups.joinToString(" / ").ifBlank { "未发现蛋组" }, style = MaterialTheme.typography.bodySmall)
          }
        }
        if (index < items.take(8).lastIndex) HorizontalDivider()
      }
    }
  }
}

@Composable
private fun IvFields(values: List<String>, onChange: (Int, String) -> Unit) {
  val labels = listOf("HP", "攻击", "防御", "特攻", "特防", "速度")
  val largeText = LocalConfiguration.current.fontScale > 1.3f
  BoxWithConstraints(Modifier.fillMaxWidth()) {
    val columns = if (largeText && maxWidth < 600.dp) 2 else 3
    if (maxWidth < 600.dp || largeText) {
      Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        labels.indices.chunked(columns).forEach { rowIndices ->
          Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            rowIndices.forEach { index ->
              IvField(index, labels[index], values.getOrElse(index) { "X" }, onChange, Modifier.weight(1f))
            }
          }
        }
      }
    } else {
      Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        labels.forEachIndexed { index, label ->
          IvField(index, label, values.getOrElse(index) { "X" }, onChange, Modifier.weight(1f))
        }
      }
    }
  }
}

@Composable
private fun IvField(index: Int, label: String, value: String, onChange: (Int, String) -> Unit, modifier: Modifier) {
  IvSelector(label, value, { onChange(index, it) }, modifier)
}

@Composable
private fun OptionSwitch(title: String, subtitle: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
  Row(
    Modifier
      .fillMaxWidth()
      .heightIn(min = 64.dp)
      .toggleable(value = checked, role = Role.Switch, onValueChange = onCheckedChange)
      .padding(vertical = 4.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    Column(Modifier.weight(1f)) {
      Text(title, fontWeight = FontWeight.Medium)
      Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Spacer(Modifier.width(10.dp))
    Switch(checked = checked, onCheckedChange = null)
  }
}

@Composable
private fun PlanSummary(plan: ExecutionPlanRecord, candidateCount: Int, completed: Set<String>, onEdit: () -> Unit, preview: Boolean = false) {
  val completedCount = plan.steps.count { it.child.id in completed }
  val readyCount = if (plan.needsReplan) 0 else plan.steps.count { it.child.id !in completed && completed.containsAll(it.dependencies) }
  val progress = if (plan.steps.isEmpty()) 1f else completedCount.toFloat() / plan.steps.size
  Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        PokemonPortrait(plan.finalTargetSpeciesId, Modifier.size(48.dp))
        Spacer(Modifier.width(8.dp))
        Text(
          "${plan.targetSpecies} · ${plan.targetIvCount}V ${plan.targetNature}",
          modifier = Modifier.weight(1f),
          style = MaterialTheme.typography.titleMedium,
          fontWeight = FontWeight.Bold,
        )
        TextButton(onClick = onEdit, modifier = Modifier.heightIn(min = 48.dp)) { Text("修改目标") }
      }
      if (!preview) LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
      if (plan.phaseLabel.isNotBlank()) Text("当前阶段：${plan.phaseLabel}", fontWeight = FontWeight.SemiBold)
      Text(if (preview) "本阶段 ${plan.steps.size} 步 · 可选方案 $candidateCount 个" else "本阶段 $completedCount/${plan.steps.size} 步 · 可执行 $readyCount 步 · 可选方案 $candidateCount 个")
      Text("使用库存 ${plan.inventoryUsedCount} 只 · 交易行补充 ${plan.purchaseRequirements.size} 项")
      if (plan.steps.isEmpty()) Text("库存中已经有满足目标的素材，无需继续孵化。", color = MaterialTheme.colorScheme.secondary)
    }
  }
}

@Composable
private fun PlanStepFilters(
  selected: PlanStepFilter,
  plan: ExecutionPlanRecord,
  completed: Set<String>,
  onSelect: (PlanStepFilter) -> Unit,
) {
  val completedCount = plan.steps.count { it.child.id in completed }
  val readyCount = if (plan.needsReplan) 0 else plan.steps.count { it.child.id !in completed && completed.containsAll(it.dependencies) }
  val labels = listOf(
    PlanStepFilter.All to "全部 ${plan.steps.size}",
    PlanStepFilter.Actionable to "可执行 $readyCount",
    PlanStepFilter.Incomplete to "待完成 ${plan.steps.size - completedCount}",
    PlanStepFilter.Completed to "完成 $completedCount",
  )
  LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    items(labels) { (filter, label) ->
      FilterChip(selected = selected == filter, onClick = { onSelect(filter) }, label = { Text(label) })
    }
  }
}

@Composable
private fun EmptyStepFilter(filter: PlanStepFilter) {
  OutlinedCard {
    Text(
      when (filter) {
        PlanStepFilter.Actionable -> "暂时没有可执行步骤，请先查看未完成步骤的依赖关系。"
        PlanStepFilter.Completed -> "还没有已完成步骤。"
        else -> "这个筛选条件下没有步骤。"
      },
      modifier = Modifier.fillMaxWidth().padding(16.dp),
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
  }
}

@Composable
private fun PlanStepCard(step: ExecutionStepRecord, complete: Boolean, ready: Boolean, preview: Boolean = false, onToggle: () -> Unit) {
  val background = when {
    complete -> MaterialTheme.colorScheme.secondaryContainer
    ready -> MaterialTheme.colorScheme.surface
    else -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)
  }
  val border = routeColor(step.routeRole)
  Card(
    colors = CardDefaults.cardColors(containerColor = background),
    border = BorderStroke(if (ready || complete) 1.5.dp else 1.dp, border),
  ) {
    Column(Modifier.fillMaxWidth().padding(13.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        Text("步骤 ${step.number}", fontWeight = FontWeight.Bold, color = if (ready || complete) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.onSurface)
        Spacer(Modifier.width(8.dp))
        StatusPill(
          when {
            preview -> "预览 · 未启用"
            complete -> "已完成"
            step.inProgress -> "孵化中（备注）"
            ready -> "可执行"
            else -> "等待下层"
          },
          ready || complete,
        )
        Spacer(Modifier.weight(1f))
        if (step.requiresPurchase) Text("含采购", color = MaterialTheme.colorScheme.error, fontWeight = FontWeight.SemiBold)
      }
      Text(when (step.routeRole) { "maternal" -> "母体主线"; "nature" -> "性格手"; else -> "IV 素材" })
      if (step.routeMoves.isNotEmpty()) Text("遗传技能：${step.routeMoves.joinToString("、")}")
      Text("父母 A：${step.parentALabel}\n携带：${step.itemA.ifBlank { "无需道具" }}")
      Text("父母 B：${step.parentBLabel}\n携带：${step.itemB.ifBlank { "无需道具" }}")
      HorizontalDivider()
      Text("道具：${step.itemText}")
      Text("子代：${step.child.species} · ${step.child.ivText} · ${step.genderInstruction}", fontWeight = FontWeight.SemiBold)
      if (step.shouldCheckNature) {
        Surface(color = MaterialTheme.colorScheme.tertiaryContainer, shape = RoundedCornerShape(8.dp)) {
          Text(
            "本步需要记录是否爆出目标性格",
            Modifier.fillMaxWidth().padding(9.dp),
            color = MaterialTheme.colorScheme.onTertiaryContainer,
          )
        }
      }
      if (!preview) OutlinedButton(
        onClick = onToggle,
        enabled = ready,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
      ) {
        Text(if (complete) "已核销 · 可用顶部撤销恢复" else if (ready) "核对本步并记录结果" else "尚不可执行")
      }
    }
  }
}

@Composable
private fun PlanReport(report: String, initiallyExpanded: Boolean = false) {
  var expanded by rememberSaveable(report) { mutableStateOf(initiallyExpanded) }
  OutlinedCard {
    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        Text("初始方案说明与缺口", modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
        TextButton(onClick = { expanded = !expanded }, modifier = Modifier.heightIn(min = 44.dp)) {
          Text(if (expanded) "收起" else "展开")
        }
      }
      if (expanded) Text(report, style = MaterialTheme.typography.bodySmall)
    }
  }
}
