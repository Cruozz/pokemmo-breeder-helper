package com.example.pokemmobreederhelper.ui.main

import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.example.pokemmobreederhelper.data.CaptureDraft
import com.example.pokemmobreederhelper.data.CaptureLimits
import com.example.pokemmobreederhelper.data.genderLabel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun InventoryCaptureDialog(state: CaptureUiState, vm: InventoryCaptureViewModel,
  inventoryBusy: Boolean, onDismiss: () -> Unit, onReview: (CaptureDraft) -> Unit) {
  val images = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(CaptureLimits.MAX_IMAGES)) {
    if (it.isNotEmpty()) vm.scan(it, false)
  }
  val video = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) {
    if (it != null) vm.scan(listOf(it), true)
  }
  var confirmClear by rememberSaveable { mutableStateOf(false) }
  val canEdit = !state.busy && !state.liveActive && !inventoryBusy
  Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
    Surface(Modifier.fillMaxSize().safeDrawingPadding(), color = MaterialTheme.colorScheme.background) {
      Column {
        Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
          Text("精灵库存采集", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
          TextButton(onClick = onDismiss) { Text("返回") }
        }
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
          item { LiveCaptureControls(enabled = canEdit) }
          item {
            Text("也可以先用手机系统录屏，在游戏中逐只打开精灵详情与个体值页，每只停留至少 2 秒，再回到这里导入。")
            Text("每批 20 张截图，或 2 分钟以内的录屏；每秒取一帧。采集结果先存为草稿，核对入库后参与规划。",
              style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
          }
          item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
              Button(onClick = { images.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, enabled = canEdit) { Text("导入截图") }
              OutlinedButton(onClick = { video.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.VideoOnly)) }, enabled = canEdit) { Text("导入录屏") }
            }
          }
          if (state.busy || state.message.isNotBlank() || state.error.isNotBlank()) item {
            OutlinedCard {
              Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.busy) {
                  if (state.total > 0) LinearProgressIndicator(progress = { state.processed.toFloat() / state.total }, modifier = Modifier.fillMaxWidth())
                  else LinearProgressIndicator(Modifier.fillMaxWidth())
                }
                if (state.message.isNotBlank()) Text(state.message)
                Text("处理 ${state.processed}/${state.total} · 跳过 ${state.skipped} · 折叠 ${state.grouped} · 失败 ${state.failures}", style = MaterialTheme.typography.bodySmall)
                if (state.error.isNotBlank()) Text(state.error, color = MaterialTheme.colorScheme.error)
                if (state.busy) TextButton(onClick = vm::cancel) { Text("停止识别并保留草稿") }
              }
            }
          }
          item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
              Text("待核对 ${state.drafts.size} 只", style = MaterialTheme.typography.titleMedium)
              TextButton(onClick = { confirmClear = true }, enabled = canEdit && state.drafts.isNotEmpty()) { Text("清空草稿") }
            }
          }
          if (state.drafts.isEmpty()) item { Text("还没有待核对素材。画面需清楚显示精灵名称和个体值；模糊、过场或空白画面可能被跳过。") }
          items(state.drafts, key = { it.material.id }) { draft ->
            OutlinedCard {
              Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(draft.material.species.ifBlank { "名称待确认" } + " · " + genderLabel(draft.material.gender), style = MaterialTheme.typography.titleMedium)
                Text(draft.material.ivText + " · " + draft.material.nature.ifBlank { "性格未知" })
                Text(draft.sourceLabel, style = MaterialTheme.typography.bodySmall)
                if (draft.frameCount > 1) Text("连续 ${draft.frameCount} 帧识别相同（${(draft.firstMs ?: 0) / 1000}–${(draft.lastMs ?: 0) / 1000} 秒）。如包含多只相同属性精灵，请按实际数量复制。", style = MaterialTheme.typography.bodySmall)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                  Button(onClick = { onReview(draft) }, enabled = canEdit) { Text("核对入库") }
                  TextButton(onClick = { vm.copyDraft(draft.material.id) }, enabled = canEdit) { Text("复制一只") }
                  TextButton(onClick = { vm.discard(draft.material.id) }, enabled = canEdit) { Text("忽略") }
                }
              }
            }
          }
        }
      }
    }
  }
  if (confirmClear) AlertDialog(onDismissRequest = { confirmClear = false }, title = { Text("清空待核对草稿？") },
    text = { Text("草稿及预览图将删除。已入库的精灵、原始截图和录屏保留。") },
    confirmButton = { TextButton(onClick = { confirmClear = false; vm.clearDrafts() }) { Text("清空草稿") } },
    dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("取消") } })
}

@Composable
internal fun CaptureReviewPreview(draft: CaptureDraft, path: String) {
  var preview by remember(path) { mutableStateOf<ImageBitmap?>(null) }
  var showText by rememberSaveable(draft.material.id) { mutableStateOf(false) }
  LaunchedEffect(path) {
    preview = withContext(Dispatchers.IO) { runCatching { BitmapFactory.decodeFile(path)?.asImageBitmap() }.getOrNull() }
  }
  OutlinedCard {
    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
      Text("对照原画面核对", style = MaterialTheme.typography.titleMedium)
      preview?.let { Image(it, contentDescription = "采集时的精灵详情画面", modifier = Modifier.fillMaxWidth().heightIn(max = 360.dp), contentScale = ContentScale.Fit) }
        ?: Text("预览无法读取，请对照原截图或录屏核对。")
      draft.warnings.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
      TextButton(onClick = { showText = !showText }) { Text(if (showText) "收起识别文字" else "查看识别文字") }
      if (showText) Text(draft.rawText.ifBlank { "未识别到文字" }, style = MaterialTheme.typography.bodySmall)
    }
  }
}
