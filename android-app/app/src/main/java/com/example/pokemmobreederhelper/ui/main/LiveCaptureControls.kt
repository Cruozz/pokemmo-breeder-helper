package com.example.pokemmobreederhelper.ui.main

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.example.pokemmobreederhelper.capture.InventoryCaptureService
import com.example.pokemmobreederhelper.capture.LiveCaptureState

@Composable
internal fun LiveCaptureControls(enabled: Boolean) {
  val context=LocalContext.current
  val live by LiveCaptureState.state.collectAsState()
  var error by remember { mutableStateOf("") }
  val projection=rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
    if(result.resultCode==Activity.RESULT_OK && result.data!=null) {
      runCatching { ContextCompat.startForegroundService(context,Intent(context,InventoryCaptureService::class.java)
        .setAction(InventoryCaptureService.START).putExtra("result",result.resultCode).putExtra("token",result.data)) }
        .onFailure { error="无法启动采集：${it.message}" }
    } else error="已取消屏幕共享，未开始采集。"
  }
  fun authorize() { error="";projection.launch(context.getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent()) }
  val overlays=rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
    if(Settings.canDrawOverlays(context)) authorize() else error="需要允许显示悬浮窗，才能在游戏里控制采集。"
  }
  OutlinedCard {
    Column(Modifier.fillMaxWidth().padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
      Text("实时悬浮采集",style=MaterialTheme.typography.titleMedium)
      Text("在浮窗填写用户名、仓库和格位。自动模式下逐只打开个体值页，每只停留约 2 秒；结果持续保存到待核对列表。")
      Text("跳到其他格位时更新位置。两只画面完全相同时，手动点“下一只”区分。",style=MaterialTheme.typography.bodySmall)
      if(live.running) {
        Text("已保存 ${live.saved} 只 · ${live.message}")
        Button(onClick={ context.stopService(Intent(context,InventoryCaptureService::class.java)) }) { Text("结束采集并核对") }
      } else {
        Button(enabled=enabled,onClick={
          if(Settings.canDrawOverlays(context)) authorize()
          else overlays.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,Uri.parse("package:${context.packageName}")))
        }) { Text("开启实时采集浮窗") }
        if(live.message.isNotBlank())Text(live.message,style=MaterialTheme.typography.bodySmall)
      }
      if(error.isNotBlank())Text(error,color=MaterialTheme.colorScheme.error)
    }
  }
}
