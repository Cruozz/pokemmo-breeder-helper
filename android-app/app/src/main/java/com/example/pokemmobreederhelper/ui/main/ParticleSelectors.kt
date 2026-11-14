package com.example.pokemmobreederhelper.ui.main

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.imageResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.pokemmobreederhelper.R
import com.example.pokemmobreederhelper.data.ParticleCatalog
import com.example.pokemmobreederhelper.data.ParticleDefinition

@Composable
private fun ParticleIcon(entry: ParticleDefinition) {
  val atlas = ImageBitmap.imageResource(R.drawable.particle_atlas)
  Canvas(Modifier.size(36.dp)) {
    drawImage(atlas, srcOffset = IntOffset(entry.iconIndex % 7 * 24, entry.iconIndex / 7 * 24),
      srcSize = IntSize(24, 24), dstSize = IntSize(size.width.toInt(), size.height.toInt()), filterQuality = FilterQuality.None)
  }
}

@Composable
internal fun ParticlePicker(selected: List<String>, onDismiss: () -> Unit, onConfirm: (List<String>) -> Unit) {
  val context = LocalContext.current
  val entries = remember(context) { ParticleCatalog.entries(context).filterNot { it.intrinsic } }
  var chosen by rememberSaveable { mutableStateOf(selected) }
  var query by rememberSaveable { mutableStateOf("") }
  val visible = remember(entries, query) { entries.filter { query.isBlank() || it.name.contains(query, true) || it.englishName.contains(query, true) } }
  Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
    Surface(Modifier.fillMaxSize().safeDrawingPadding().imePadding(), color = MaterialTheme.colorScheme.background) {
      Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
          TextButton(onClick = onDismiss) { Text("取消") }
          Text("选择粒子 · ${chosen.size}", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
          Button(onClick = { onConfirm(chosen); onDismiss() }) { Text("保存") }
        }
        OutlinedTextField(query, { query = it }, label = { Text("搜索中文或英文粒子名称") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
          items(visible, key = { it.id }) { entry ->
            val checked = entry.id in chosen
            Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).toggleable(checked, role = Role.Checkbox) {
              chosen = if (it) (chosen + entry.id).distinct() else chosen - entry.id
            }.padding(8.dp), verticalAlignment = Alignment.CenterVertically,
              horizontalArrangement = Arrangement.spacedBy(12.dp)) {
              ParticleIcon(entry)
              Column(Modifier.weight(1f)) {
                Text(entry.name)
                Text(entry.englishName, style = MaterialTheme.typography.bodySmall)
              }
              Checkbox(checked, onCheckedChange = null)
            }
          }
        }
      }
    }
  }
}

@Composable
internal fun CosmeticPlanningOptions(state: MainScreenUiState, vm: MainScreenViewModel) {
  var picker by remember { mutableStateOf(false) }
  Text("粒子使用", style = MaterialTheme.typography.titleSmall)
  FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    listOf("protect" to "默认保护", "target" to "指定粒子", "ignore" to "无视粒子", "unique" to "同种限一次").forEach { (key, label) ->
      FilterChip(selected = state.particleMode == key, onClick = { vm.setParticleMode(key) }, enabled = !state.isPlanning, label = { Text(label) })
    }
  }
  if (state.particleMode == "target") {
    OutlinedButton(onClick = { picker = true }, enabled = !state.isPlanning, modifier = Modifier.fillMaxWidth()) {
      Text("成品粒子：" + ParticleCatalog.names(state.targetParticles).ifBlank { "点击多选" })
    }
  }
  if (state.particleMode in listOf("target", "unique")) Text("双亲携带的全部粒子不得重复，包括未选作目标的粒子。", style = MaterialTheme.typography.bodySmall)
  Row(Modifier.fillMaxWidth().heightIn(min = 48.dp).toggleable(state.targetCostume,
    enabled = !state.isPlanning, role = Role.Checkbox, onValueChange = vm::setTargetCostume), verticalAlignment = Alignment.CenterVertically) {
    Checkbox(state.targetCostume, onCheckedChange = null)
    Column {
      Text("时装成品")
      Text("沿时装后代主线完成目标；本次取消 X 位 31 素材保护", style = MaterialTheme.typography.bodySmall)
    }
  }
  if (picker) ParticlePicker(state.targetParticles, { picker = false }, vm::setTargetParticles)
}
