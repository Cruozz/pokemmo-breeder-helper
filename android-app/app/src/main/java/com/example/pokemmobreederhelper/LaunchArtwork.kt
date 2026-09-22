package com.example.pokemmobreederhelper

import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
internal fun LaunchArtwork(onContinue: () -> Unit) {
  Surface(color = MaterialTheme.colorScheme.background) {
    BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding()
      .clickable(role = Role.Button, onClickLabel = "进入库存", onClick = onContinue), contentAlignment = Alignment.Center) {
      val artWidth = minOf(maxWidth, ((maxHeight - 88.dp).coerceAtLeast(1.dp)) * (4f / 3f), 640.dp)
      Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(24.dp)) {
        Image(painterResource(R.drawable.launch_art), contentDescription = "孵蛋助手开屏画面",
          modifier = Modifier.width(artWidth).aspectRatio(4f / 3f), contentScale = ContentScale.Fit)
        Text("让孵蛋更简单", modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp),
          style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
      }
    }
  }
}
