package com.example.pokemmobreederhelper.ui.main

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
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
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
  val importer =
    rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
      if (uri != null) viewModel.importInventory(uri)
    }

  Scaffold(
    modifier = modifier.fillMaxSize(),
    topBar = {
      TopAppBar(
        title = {
          Column {
            Text("PokeMMO 孵蛋助手", fontWeight = FontWeight.SemiBold)
            Text("手机版 · 离线库存与规划", style = MaterialTheme.typography.labelSmall)
          }
        }
      )
    },
  ) { innerPadding ->
    Column(Modifier.fillMaxSize().padding(innerPadding)) {
      TabRow(selectedTabIndex = if (state.tab == MainTab.Inventory) 0 else 1) {
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
          InventoryScreen(
            state = state,
            onImport = { importer.launch(arrayOf("application/json", "text/json", "text/plain")) },
            onQueryChange = viewModel::setInventoryQuery,
            onAccountChange = viewModel::setAccountFilter,
          )
        MainTab.Planner -> PlannerScreen(state, viewModel)
      }
    }
  }
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
private fun InventoryScreen(
  state: MainScreenUiState,
  onImport: () -> Unit,
  onQueryChange: (String) -> Unit,
  onAccountChange: (String) -> Unit,
) {
  val accounts = remember(state.inventory) { listOf("全部账号") + state.inventory.map { it.account }.distinct().sorted() }
  val query = state.inventoryQuery.trim().lowercase()
  val filtered =
    remember(state.inventory, query, state.accountFilter) {
      state.inventory.filter { monster ->
        val accountMatches = state.accountFilter == "全部账号" || monster.account == state.accountFilter
        val textMatches =
          query.isBlank() || listOf(
            monster.species,
            monster.nature,
            monster.account,
            monster.positionLabel,
            monster.ivText,
            monster.eggGroups.joinToString(" "),
          ).any { query in it.lowercase() }
        accountMatches && textMatches
      }
    }
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    contentPadding = PaddingValues(12.dp),
    verticalArrangement = Arrangement.spacedBy(10.dp),
  ) {
    item {
      InventoryHeader(state.inventory, filtered.size, onImport)
    }
    item {
      OutlinedTextField(
        value = state.inventoryQuery,
        onValueChange = onQueryChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("搜索精灵、账号、位置、性格或蛋组") },
        singleLine = true,
      )
    }
    item {
      LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(accounts) { account ->
          FilterChip(
            selected = state.accountFilter == account,
            onClick = { onAccountChange(account) },
            label = { Text(account, maxLines = 1) },
          )
        }
      }
    }
    if (filtered.isEmpty()) {
      item {
        EmptyInventory(hasInventory = state.inventory.isNotEmpty(), onImport = onImport)
      }
    } else {
      items(filtered, key = { it.id }) { monster -> MonsterCard(monster) }
    }
  }
}

@Composable
private fun InventoryHeader(inventory: List<MonsterRecord>, showing: Int, onImport: () -> Unit) {
  val verified = inventory.count { it.verified }
  val accounts = inventory.map { it.account }.distinct().size
  Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
          Text("手机库存", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
          Text("共 ${inventory.size} 只 · 已确认 $verified 只 · $accounts 个账号 · 当前显示 $showing 只")
        }
        Button(onClick = onImport, modifier = Modifier.heightIn(min = 48.dp)) { Text("导入电脑 JSON") }
      }
      Text("重新导入会以电脑文件覆盖手机库存，并清除旧规划进度。", style = MaterialTheme.typography.labelMedium)
    }
  }
}

@Composable
private fun EmptyInventory(hasInventory: Boolean, onImport: () -> Unit) {
  OutlinedCard {
    Column(
      Modifier.fillMaxWidth().padding(24.dp),
      horizontalAlignment = Alignment.CenterHorizontally,
      verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
      Text(if (hasInventory) "没有符合筛选条件的素材" else "手机里还没有素材库存", fontWeight = FontWeight.SemiBold)
      Text(if (hasInventory) "换个关键词或账号试试。" else "在电脑版素材库存中导出 JSON，再传到手机导入。")
      if (!hasInventory) Button(onClick = onImport, modifier = Modifier.heightIn(min = 48.dp)) { Text("选择 JSON 文件") }
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
private fun PlannerScreen(state: MainScreenUiState, viewModel: MainScreenViewModel) {
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    contentPadding = PaddingValues(12.dp),
    verticalArrangement = Arrangement.spacedBy(10.dp),
  ) {
    item {
      PlannerForm(state, viewModel)
    }
    if (state.isPlanning) {
      item {
        Card {
          Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
              CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 3.dp)
              Spacer(Modifier.width(12.dp))
              Text("正在使用 ${state.inventory.count { it.verified }} 只已确认素材计算最佳路线……")
            }
            LinearProgressIndicator(Modifier.fillMaxWidth())
          }
        }
      }
    }
    state.plannerResponse?.let { response ->
      val plan = response.plan
      if (plan != null) {
        item { PlanSummary(plan, response.candidateCount, state.completedChildIds) }
        items(plan.steps, key = { it.child.id }) { step ->
          val complete = step.child.id in state.completedChildIds
          val ready = !complete && state.completedChildIds.containsAll(step.dependencies)
          PlanStepCard(step, complete, ready) { viewModel.toggleStep(step) }
        }
        item { PlanReport(response.report) }
      } else if (response.report.isNotBlank()) {
        item { PlanReport(response.report, initiallyExpanded = true) }
      }
    }
  }
}

@Composable
private fun PlannerForm(state: MainScreenUiState, viewModel: MainScreenViewModel) {
  OutlinedCard {
    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
      Text("目标与规则", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
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
      }
      OutlinedTextField(
        value = state.nature,
        onValueChange = viewModel::setNature,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("目标性格（留空表示不指定）") },
        singleLine = true,
      )
      LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(listOf("固执", "内敛", "爽朗", "胆小")) { nature ->
          FilterChip(
            selected = state.nature == nature,
            onClick = { viewModel.setNature(if (state.nature == nature) "" else nature) },
            label = { Text("★ $nature") },
          )
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
      Button(
        onClick = viewModel::generatePlan,
        enabled = !state.isPlanning,
        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
      ) {
        Text(if (state.isPlanning) "正在生成规划" else "生成最佳孵蛋路线")
      }
      Text(
        "交易行素材会直接进入路线，无需在手机或电脑再次扫描入库。",
        style = MaterialTheme.typography.bodySmall,
      )
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
  Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
    labels.forEachIndexed { index, label ->
      Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(label, fontSize = 11.sp, maxLines = 1)
        OutlinedTextField(
          value = values.getOrElse(index) { "X" },
          onValueChange = { onChange(index, it) },
          singleLine = true,
          textStyle = MaterialTheme.typography.bodyMedium.copy(textAlign = androidx.compose.ui.text.style.TextAlign.Center),
          keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
          modifier = Modifier.fillMaxWidth(),
        )
      }
    }
  }
}

@Composable
private fun OptionSwitch(title: String, subtitle: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
  Row(
    Modifier.fillMaxWidth().clickable { onCheckedChange(!checked) }.padding(vertical = 3.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    Column(Modifier.weight(1f)) {
      Text(title, fontWeight = FontWeight.Medium)
      Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Spacer(Modifier.width(10.dp))
    Switch(checked = checked, onCheckedChange = onCheckedChange)
  }
}

@Composable
private fun PlanSummary(plan: ExecutionPlanRecord, candidateCount: Int, completed: Set<String>) {
  Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
      Text("${plan.targetSpecies} · ${plan.targetIvCount}V ${plan.targetNature}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
      Text("完成 ${completed.size}/${plan.steps.size} 步 · 可选方案 $candidateCount 个")
      Text("使用库存 ${plan.inventoryUsedCount} 只 · 交易行补充 ${plan.purchaseRequirements.size} 项")
      if (plan.steps.isEmpty()) Text("库存中已经有满足目标的素材，无需继续孵化。", color = MaterialTheme.colorScheme.secondary)
    }
  }
}

@Composable
private fun PlanStepCard(step: ExecutionStepRecord, complete: Boolean, ready: Boolean, onToggle: () -> Unit) {
  val background = when {
    complete -> MaterialTheme.colorScheme.secondaryContainer
    ready -> MaterialTheme.colorScheme.surface
    else -> MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)
  }
  val border = when {
    complete || ready -> MaterialTheme.colorScheme.secondary
    else -> MaterialTheme.colorScheme.outline
  }
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
            complete -> "已完成"
            ready -> "可执行"
            else -> "等待下层"
          },
          ready || complete,
        )
        Spacer(Modifier.weight(1f))
        if (step.requiresPurchase) Text("含采购", color = MaterialTheme.colorScheme.error, fontWeight = FontWeight.SemiBold)
      }
      Text("父母 A：${step.parentALabel}", maxLines = 3, overflow = TextOverflow.Ellipsis)
      Text("父母 B：${step.parentBLabel}", maxLines = 3, overflow = TextOverflow.Ellipsis)
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
      OutlinedButton(
        onClick = onToggle,
        enabled = ready || complete,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
      ) {
        Text(if (complete) "撤销本步完成" else if (ready) "标记本步已完成" else "完成下层后解锁")
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
        Text("规划说明与缺口", modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
        TextButton(onClick = { expanded = !expanded }, modifier = Modifier.heightIn(min = 44.dp)) {
          Text(if (expanded) "收起" else "展开")
        }
      }
      if (expanded) Text(report, style = MaterialTheme.typography.bodySmall)
    }
  }
}
