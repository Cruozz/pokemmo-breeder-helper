package com.example.pokemmobreederhelper.ui.main

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.graphics.*
import androidx.compose.ui.res.imageResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.*
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.pokemmobreederhelper.R
import com.example.pokemmobreederhelper.data.*

@Composable
internal fun PokemonPortrait(speciesId: Int?, modifier: Modifier = Modifier) {
  val atlas = ImageBitmap.imageResource(R.drawable.pokemon_atlas)
  val tint = MaterialTheme.colorScheme.primary
  Canvas(modifier.size(72.dp)) {
    if (speciesId != null && speciesId in 1..649) {
      drawImage(atlas, srcOffset = IntOffset((speciesId - 1) % 16 * 96, (speciesId - 1) / 16 * 96),
        srcSize = IntSize(96,96), dstSize = IntSize(size.width.toInt(),size.height.toInt()), filterQuality = FilterQuality.None)
    } else {
      drawCircle(tint.copy(alpha = 0.15f))
      drawCircle(tint, radius = size.minDimension * 0.25f, style = androidx.compose.ui.graphics.drawscope.Stroke(3.dp.toPx()))
      drawLine(tint, androidx.compose.ui.geometry.Offset(0f, center.y), androidx.compose.ui.geometry.Offset(size.width, center.y), 3.dp.toPx())
    }
  }
}

@Composable
internal fun PokedexInventory(state: MainScreenUiState, vm: MainScreenViewModel, onImport: () -> Unit) {
  var selected by remember { mutableStateOf(emptySet<String>()) }
  var status by rememberSaveable { mutableStateOf("全部状态") }
  var category by rememberSaveable { mutableStateOf("全部类别") }
  var showFilters by rememberSaveable { mutableStateOf(false) }
  var confirmDelete by remember { mutableStateOf<Set<String>?>(null) }
  var confirmClear by remember { mutableStateOf(false) }
  LaunchedEffect(state.inventory) { selected = selected.intersect(state.inventory.map { it.id }.toSet()) }
  val accounts = remember(state.inventory) { listOf("全部账号") + state.inventory.map { it.account }.distinct().sorted() }
  val filtered = remember(state.inventory, state.inventoryQuery, state.accountFilter, status, category) {
    val query = state.inventoryQuery.trim().lowercase()
    state.inventory.filter { m ->
      (state.accountFilter == "全部账号" || m.account == state.accountFilter) &&
      (status == "全部状态" || m.verified == (status == "已确认")) &&
      (category == "全部类别" || m.isAlpha == (category == "头目")) &&
      (query.isBlank() || listOf(m.species,m.nature,m.account,m.positionLabel,m.ivText,m.ability,m.notes,
        m.moves.joinToString(" "),m.eggGroups.joinToString(" ")).any { query in it.lowercase() })
    }
  }
  LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
    item {
      Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
          Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
              Text("素材图鉴", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.ExtraBold)
              Text("${state.inventory.size} 只素材 · ${state.inventory.count { it.verified }} 只已确认", style = MaterialTheme.typography.bodyMedium)
            }
            PokemonPortrait(state.inventory.firstOrNull()?.species?.let { state.speciesIcons[it] } ?: 133)
          }
          Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.editMaterial() }, enabled = !state.isPlanning, modifier = Modifier.weight(1f)) { Text("新增素材") }
            OutlinedButton(onClick = onImport, enabled = !state.isPlanning, modifier = Modifier.weight(1f)) { Text("导入 JSON") }
          }
        }
      }
    }
    item {
      OutlinedTextField(state.inventoryQuery, vm::setInventoryQuery, Modifier.fillMaxWidth(),
        label = { Text("搜索精灵、性格、技能或位置") }, singleLine = true, shape = RoundedCornerShape(16.dp))
    }
    item {
      FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(selected = showFilters, onClick = { showFilters = !showFilters }, label = { Text("筛选 · ${filtered.size}") })
        TextButton(onClick = vm::checkDuplicates, enabled = !state.isPlanning) { Text("重复检查") }
        TextButton(onClick = { confirmClear = true }, enabled = state.inventory.isNotEmpty() && !state.isPlanning) { Text("清空库存", color = MaterialTheme.colorScheme.error) }
      }
    }
    if (showFilters) {
      item { FilterStrip(accounts, state.accountFilter, vm::setAccountFilter) }
      item { FilterStrip(listOf("全部状态","已确认","待核对"), status) { status = it } }
      item { FilterStrip(listOf("全部类别","普通","头目"), category) { category = it } }
    }
    if (state.isPlanning) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
    item {
      FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        TextButton(onClick = { selected = if (filtered.all { it.id in selected }) selected - filtered.map { it.id }.toSet() else selected + filtered.map { it.id } }, enabled = filtered.isNotEmpty()) {
          Text(if (filtered.isNotEmpty() && filtered.all { it.id in selected }) "取消全选" else "全选当前结果")
        }
        if (selected.isNotEmpty()) {
          TextButton(onClick = { vm.verifyMaterials(selected) }, enabled = !state.isPlanning) { Text("确认 ${selected.size} 只") }
          TextButton(onClick = { confirmDelete = selected }, enabled = !state.isPlanning) { Text("删除选中", color = MaterialTheme.colorScheme.error) }
        }
      }
    }
    if (filtered.isEmpty()) item {
      Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        PokemonPortrait(175)
        Text(if (state.inventory.isEmpty()) "从第一只素材开始" else "没有符合条件的素材", style = MaterialTheme.typography.titleMedium)
        Text(if (state.inventory.isEmpty()) "手动新增，或导入电脑库存" else "调整搜索和筛选条件", color = MaterialTheme.colorScheme.onSurfaceVariant)
      }
    }
    items(filtered, key = { it.id }) { monster ->
      Card(onClick = { vm.editMaterial(monster) }, enabled = !state.isPlanning,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(if (monster.id in selected) 2.dp else 1.dp,
          if (monster.id in selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant)) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
          Row(verticalAlignment = Alignment.CenterVertically) {
            PokemonPortrait(state.speciesIcons[monster.species])
            Column(Modifier.weight(1f)) {
              Text(monster.species, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
              Text("${genderLabel(monster.gender)} · ${monster.nature.ifBlank { "性格未知" }}", style = MaterialTheme.typography.bodyMedium)
              Text("${monster.account} · ${monster.positionLabel.ifBlank { "未定位" }}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Checkbox(checked = monster.id in selected, modifier = Modifier.semantics { contentDescription = "选择${monster.species}，${monster.positionLabel}" }, onCheckedChange = { checked -> selected = if (checked) selected + monster.id else selected - monster.id })
          }
          FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            monster.ivs.forEachIndexed { index, value ->
              Surface(color = if (value == 31) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceContainerHigh, shape = RoundedCornerShape(8.dp)) {
                Column(Modifier.widthIn(min = 40.dp).padding(5.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                  Text(listOf("HP","攻击","防御","特攻","特防","速度")[index], style = MaterialTheme.typography.labelSmall)
                  Text(value?.toString() ?: "X", fontWeight = FontWeight.Bold)
                }
              }
            }
          }
          FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("${monster.perfectIvCount}V", color = MaterialTheme.colorScheme.secondary, fontWeight = FontWeight.Bold)
            if (monster.isAlpha) Text("头目", color = MaterialTheme.colorScheme.tertiary)
            if (monster.hasHiddenAbility) Text("梦特", color = MaterialTheme.colorScheme.primary)
            if (!monster.verified) Text("待核对", color = MaterialTheme.colorScheme.error)
            Text(monster.moves.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
          }
        }
      }
    }
  }
  if (confirmClear || confirmDelete != null) {
    AlertDialog(onDismissRequest = { confirmClear = false; confirmDelete = null }, title = { Text(if (confirmClear) "清空全部库存？" else "删除 ${confirmDelete!!.size} 只素材？") },
      text = { Text("本次操作可撤销。如果影响正在执行的路线，该路线会暂停并提示重算。") },
      confirmButton = { TextButton(enabled = !state.isPlanning, onClick = {
        if (confirmClear) vm.clearInventory() else vm.deleteMaterials(confirmDelete!!)
        selected = emptySet(); confirmClear = false; confirmDelete = null
      }) { Text("确认删除") } }, dismissButton = { TextButton(onClick = { confirmClear = false; confirmDelete = null }) { Text("取消") } })
  }
}

@Composable
private fun FilterStrip(options: List<String>, selected: String, choose: (String) -> Unit) {
  LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) { items(options) { item ->
    FilterChip(selected = item == selected, onClick = { choose(item) }, label = { Text(item) })
  } }
}

@Composable
internal fun MaterialEditor(material: MonsterRecord, error: String, busy: Boolean, onDismiss: () -> Unit, onSave: (MonsterRecord) -> Unit,
  searchSpecies: suspend (String) -> List<SpeciesSuggestion>) {
  var species by rememberSaveable(material.id) { mutableStateOf(material.species) }
  var gender by rememberSaveable(material.id) { mutableStateOf(material.gender) }
  var nature by rememberSaveable(material.id) { mutableStateOf(material.nature) }
  var ivs by rememberSaveable(material.id) { mutableStateOf(material.ivs.map { it?.toString() ?: "X" }) }
  var moves by rememberSaveable(material.id) { mutableStateOf(material.moves.joinToString("、")) }
  var ability by rememberSaveable(material.id) { mutableStateOf(material.ability) }
  var heldItem by rememberSaveable(material.id) { mutableStateOf(material.heldItem) }
  var account by rememberSaveable(material.id) { mutableStateOf(material.account) }
  var page by rememberSaveable(material.id) { mutableStateOf(material.page) }
  var slot by rememberSaveable(material.id) { mutableStateOf(material.slot) }
  var notes by rememberSaveable(material.id) { mutableStateOf(material.notes) }
  var alpha by rememberSaveable(material.id) { mutableStateOf(material.isAlpha) }
  var hidden by rememberSaveable(material.id) { mutableStateOf(material.hasHiddenAbility) }
  var verified by rememberSaveable(material.id) { mutableStateOf(material.verified) }
  var localError by remember { mutableStateOf("") }
  var chooseNature by remember { mutableStateOf(false) }
  var speciesMatches by remember { mutableStateOf(emptyList<SpeciesSuggestion>()) }
  var acceptedSpecies by rememberSaveable(material.id) { mutableStateOf(material.species) }
  LaunchedEffect(species) {
    speciesMatches = emptyList()
    if (species.isNotBlank() && species != acceptedSpecies) {
      kotlinx.coroutines.delay(250)
      speciesMatches = runCatching { searchSpecies(species) }.getOrDefault(emptyList())
    }
  }
  Dialog(onDismissRequest = { if (!busy) onDismiss() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
    Surface(Modifier.fillMaxSize().safeDrawingPadding().imePadding(), color = MaterialTheme.colorScheme.background) {
      Column {
        val largeText = LocalDensity.current.fontScale > 1.3f
        if (largeText) Text(if (material.species.isBlank()) "新增素材" else "编辑素材", Modifier.padding(horizontal = 16.dp), style = MaterialTheme.typography.titleLarge)
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
          TextButton(onClick = onDismiss, enabled = !busy) { Text("取消") }
          if (largeText) Spacer(Modifier.weight(1f)) else Text(if (material.species.isBlank()) "新增素材" else "编辑素材", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
          Button(enabled = !busy, onClick = {
            val invalid = ivs.any { it.uppercase() != "X" && it.isNotBlank() && it.toIntOrNull()?.let { v -> v in 0..31 } != true }
            when {
              invalid -> localError = "个体值请填写 0–31 或 X。"
              page.isNotBlank() && (page.toIntOrNull() ?: 0) < 1 -> localError = "页码必须为正整数。"
              slot.isNotBlank() && (slot.toIntOrNull() ?: 0) < 1 -> localError = "格号必须为正整数。"
              else -> { localError = ""; onSave(material.copy(species = species.trim(), gender = gender, nature = nature,
                ivs = ivs.map { it.toIntOrNull() }, moves = moves.split(Regex("[、,，;；\\n]+")).map { it.trim() }.filter { it.isNotEmpty() }.distinct(),
                ability = ability.trim(), heldItem = heldItem.trim(), account = account.trim(), page = page, slot = slot, notes = notes,
                isAlpha = alpha, hasHiddenAbility = hidden, verified = verified, updatedAt = java.time.Instant.now().toString())) }
            }
          }) { Text(if (busy) "保存中" else "保存素材") }
        }
        if (localError.isNotBlank() || error.isNotBlank()) Text(localError.ifBlank { error }, Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.error)
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
          OutlinedTextField(species, { species = it }, label = { Text("精灵名称（中文、英文或编号）") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
          speciesMatches.forEach { match -> TextButton(onClick = {
            acceptedSpecies = match.displayName; species = match.displayName; speciesMatches = emptyList()
            if (match.allowedGenders.size == 1) gender = match.allowedGenders.first()
          }) { Text("#${match.id} ${match.displayName} · ${match.eggGroups.joinToString(" / ")}") } }
          FilterStrip(listOf("性别未知","母","公","无性别"), genderLabel(gender)) { gender = when(it) { "母" -> "F"; "公" -> "M"; "无性别" -> "N"; else -> "" } }
          OutlinedButton(onClick = { chooseNature = true }, modifier = Modifier.fillMaxWidth()) { Text("性格：${nature.ifBlank { "未知" }}") }
          Text("个体值", style = MaterialTheme.typography.titleMedium)
          for (row in 0..1) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (index in row * 3 until row * 3 + 3) OutlinedTextField(ivs[index], { value -> ivs = ivs.toMutableList().also { it[index] = value.take(2).uppercase() } },
              label = { Text(listOf("HP","攻击","防御","特攻","特防","速度")[index]) }, modifier = Modifier.weight(1f), singleLine = true)
          }
          OutlinedTextField(moves, { moves = it }, label = { Text("技能（最多 4 个，用顿号分隔）") }, modifier = Modifier.fillMaxWidth())
          OutlinedTextField(ability, { ability = it }, label = { Text("特性") }, modifier = Modifier.fillMaxWidth())
          OutlinedTextField(heldItem, { heldItem = it }, label = { Text("携带道具") }, modifier = Modifier.fillMaxWidth())
          Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(alpha, { alpha = it; if (it) hidden = true }); Text("头目"); Checkbox(hidden, { hidden = it }); Text("梦特") }
          Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(verified, { verified = it }); Text("已核对，可参与规划") }
          OutlinedTextField(account, { account = it }, label = { Text("账号 / 角色") }, modifier = Modifier.fillMaxWidth())
          Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(page, { page = it }, label = { Text("页码") }, modifier = Modifier.weight(1f))
            OutlinedTextField(slot, { slot = it }, label = { Text("格号") }, modifier = Modifier.weight(1f))
          }
          OutlinedTextField(notes, { notes = it }, label = { Text("备注") }, modifier = Modifier.fillMaxWidth())
        }
      }
    }
  }
  if (chooseNature) NatureSelectionDialog(nature, { chooseNature = false }) { nature = it; chooseNature = false }
}

@Composable
internal fun DuplicateReview(state: MainScreenUiState, vm: MainScreenViewModel) {
  val groups = state.duplicateGroups ?: return
  var deleting by remember { mutableStateOf<MonsterRecord?>(null) }
  AlertDialog(onDismissRequest = vm::dismissDuplicates, title = { Text("重复检查 · ${groups.size} 组") },
    text = {
      LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text(if (groups.isEmpty()) "未发现高度重复的素材。" else "疑似重复需人工核对，不会自动删除。") }
        item { Text("名字、性别、性格、六项 IV 和技能一致；也包含少识别一个技能的疑似项。缺少关键资料的记录不参与判断。", style = MaterialTheme.typography.bodySmall) }
        groups.forEachIndexed { index, ids ->
          item { Text("第 ${index + 1} 组", fontWeight = FontWeight.Bold) }
          items(state.inventory.filter { it.id in ids }, key = { "duplicate-$index-${it.id}" }) { m ->
            OutlinedCard(onClick = { vm.dismissDuplicates(); vm.editMaterial(m) }) {
              Column(Modifier.fillMaxWidth().padding(12.dp)) {
                Text("${m.species} · ${genderLabel(m.gender)} · ${m.nature}")
                Text(m.ivText)
                Text("${m.account} · ${m.positionLabel.ifBlank { "未定位" }} · ${if(m.isAlpha) "头目" else "普通"}")
                Text(m.moves.joinToString("、"), style = MaterialTheme.typography.bodySmall)
                Text("点击查看 / 修改", color = MaterialTheme.colorScheme.primary)
                TextButton(onClick = { deleting = m }, enabled = !state.isPlanning) { Text("删除此记录", color = MaterialTheme.colorScheme.error) }
              }
            }
          }
        }
      }
    }, confirmButton = { TextButton(onClick = vm::dismissDuplicates) { Text("关闭") } })
  deleting?.let { record -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("删除这条记录？") },
    text = { Text("${record.species} · ${record.account} · ${record.positionLabel}\n可从更多菜单撤销恢复。") },
    confirmButton = { TextButton(enabled = !state.isPlanning, onClick = { vm.deleteMaterials(setOf(record.id)); deleting = null }) { Text("确认删除") } },
    dismissButton = { TextButton(onClick = { deleting = null }) { Text("取消") } }) }
}
