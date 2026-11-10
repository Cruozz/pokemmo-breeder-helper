package com.example.pokemmobreederhelper.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.example.pokemmobreederhelper.data.SkillPreparation

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun PlanningCosts(state: MainScreenUiState, viewModel: MainScreenViewModel) {
  var expanded by rememberSaveable { mutableStateOf(false) }
  Text("补购最高 V 数", fontWeight = FontWeight.SemiBold)
  FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    FilterChip(selected = state.maxPurchaseV == null, onClick = { viewModel.setMaxPurchaseV(null) },
      enabled = !state.isPlanning, label = { Text("自动 "+state.defaultPurchaseLimit()+"V") }, modifier = Modifier.heightIn(min = 48.dp))
    (1..6).forEach { limit ->
      FilterChip(selected = state.maxPurchaseV == limit, onClick = { viewModel.setMaxPurchaseV(limit) },
        enabled = !state.isPlanning, label = { Text("${limit}V") }, modifier = Modifier.heightIn(min = 48.dp))
    }
  }
  Text("只限制补购；已有高 V 库存可正常使用。", style = MaterialTheme.typography.bodySmall)
  TextButton(onClick = { expanded = !expanded }, modifier = Modifier.heightIn(min = 48.dp)) {
    Text(if (expanded) "收起费用设置" else "费用设置")
  }
  if (expanded) {
    PriceInput("护腕单价", state.bracePrice, false, !state.isPlanning, viewModel::setBracePrice)
    PriceInput("指定性别费用", state.genderPrice, false, !state.isPlanning, viewModel::setGenderPrice)
    PriceInput("不变之石单价", state.everstonePrice, true, !state.isPlanning, viewModel::setEverstonePrice)
    Text("默认只比较新增支出。采购先核验公开挂牌；缺价显示待报价。特殊性别比例需单独报价。",
      style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
  }
}

@Composable
private fun PriceInput(label: String, value: String, optional: Boolean, enabled: Boolean, onChange: (String) -> Unit) {
  val invalid = !(optional && value.isBlank()) && (value.toLongOrNull()?.let { it in 0..1_000_000_000_000L } != true)
  OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) },
    modifier = Modifier.fillMaxWidth(), singleLine = true, enabled = enabled, isError = invalid,
    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    supportingText = { if (invalid) Text("请填写 0–1,000,000,000,000 的整数") else if (optional) Text("留空使用行情；无有效行情时待报价") })
}

@Composable
internal fun SkillPreparationList(preparations: List<SkillPreparation>) {
  if (preparations.isEmpty()) return
  Surface(color = MaterialTheme.colorScheme.tertiaryContainer, shape = MaterialTheme.shapes.medium) {
    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
      Text("配种前技能准备", fontWeight = FontWeight.Bold)
      preparations.forEach { preparation ->
        Text(preparation.species + " · " + preparation.move + "：" + preparation.method)
      }
    }
  }
}
