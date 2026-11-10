package com.example.pokemmobreederhelper.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.pokemmobreederhelper.capture.CaptureColors
import com.example.pokemmobreederhelper.capture.OverlayAppearance
import kotlin.math.roundToInt

@Composable
internal fun OverlayAppearanceSettings(onDismiss: () -> Unit) {
  val context = LocalContext.current
  var value by remember { mutableStateOf(OverlayAppearance.load(context)) }
  fun change(updated: OverlayAppearance) { value = updated.bounded(); value.save(context) }
  AlertDialog(onDismissRequest=onDismiss, title={ Text("浮窗外观") },
    text={ Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(6.dp)) {
      Text("调整后立即生效。默认按字号适配宽高；最小化按钮保持小尺寸。",style=MaterialTheme.typography.bodySmall)
      Text("不透明度 "+(value.opacity*100).roundToInt()+"%")
      Slider(value=value.opacity,onValueChange={change(value.copy(opacity=it))},valueRange=.35f..1f)
      Text("字体大小 "+value.fontSp.roundToInt()+" sp")
      Slider(value=value.fontSp,onValueChange={change(value.copy(fontSp=it.roundToInt().toFloat()))},valueRange=8f..18f,steps=9)
      Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
        Text("按字号自适应宽高",Modifier.weight(1f)); Switch(checked=value.autoSize,onCheckedChange={change(value.copy(autoSize=it))})
      }
      if(!value.autoSize) {
        Text("宽度 "+value.widthDp+" dp")
        Slider(value=value.widthDp.toFloat(),onValueChange={change(value.copy(widthDp=it.roundToInt()))},valueRange=200f..480f)
        Text("高度 "+value.heightDp+" dp")
        Slider(value=value.heightDp.toFloat(),onValueChange={change(value.copy(heightDp=it.roundToInt()))},valueRange=180f..600f)
        Text("尺寸会限制在当前屏幕内，内容放不下时可滚动。",style=MaterialTheme.typography.bodySmall)
      }
      Surface(color=Color(CaptureColors.surface),shape=MaterialTheme.shapes.small,modifier=Modifier.fillMaxWidth().alpha(value.opacity)) {
        Column(Modifier.padding(8.dp)) {
          Text(buildAnnotatedString {
            append("皮卡丘  ");withStyle(SpanStyle(color=Color(CaptureColors.male))){append("公")};append(" · 固执")
          },fontSize=value.fontSp.sp,color=Color(CaptureColors.ink))
          Text(buildAnnotatedString {
            append("HP ");withStyle(SpanStyle(color=Color(CaptureColors.perfect))){append("31")};append("   攻 28   防 20\n特攻 0   特防 15   速 6")
          },fontSize=(value.fontSp-1).coerceAtLeast(8f).sp,color=Color(CaptureColors.ink))
        }
      }
      Text("结果提示显示 5 秒，点击游戏立即关闭。提示区域支持穿透点击，不透明度最高 80%。",style=MaterialTheme.typography.bodySmall)
    } }, confirmButton={TextButton(onClick=onDismiss){Text("完成")}},
    dismissButton={TextButton(onClick={change(OverlayAppearance())}){Text("恢复默认")}})
}
