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
      Text("在浮窗选择用户名，填写仓库页和格位。逐只打开个体值页，看到“已入库”后切换下一只，位置会自动递增。")
      Text("默认直接存入库存并标为待确认，可修改、批量确认或导出电脑通用 JSON。跳格请改位置；同种同 IV 精灵请点“下一只”。",style=MaterialTheme.typography.bodySmall)
      if(live.running) {
        Text("已保存 ${live.saved} 只 · ${live.message}")
        Button(onClick={ context.stopService(Intent(context,InventoryCaptureService::class.java)) }) { Text("结束采集") }
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
