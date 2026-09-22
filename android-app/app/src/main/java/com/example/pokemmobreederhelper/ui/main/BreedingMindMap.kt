package com.example.pokemmobreederhelper.ui.main

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.imageResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.pokemmobreederhelper.R
import com.example.pokemmobreederhelper.data.ExecutionPlanRecord
import com.example.pokemmobreederhelper.data.ExecutionStepRecord
import kotlin.math.max
import kotlin.math.min

internal data class RouteNode(
  val key: String,
  val title: String,
  val ivText: String,
  val detail: String,
  val speciesId: Int?,
  val itemKey: String?,
  val step: ExecutionStepRecord? = null,
  val purchase: Boolean = false,
  val routeRole: String = "iv",
  val routeMoves: List<String> = emptyList(),
  val gender: String = "",
  val historical: Boolean = false,
  val children: List<RouteNode> = emptyList(),
  val materialId: String? = null,
)

private data class PlacedRouteNode(val node: RouteNode, val bounds: Rect)

private data class RouteLayout(
  val root: RouteNode,
  val nodes: List<PlacedRouteNode>,
  val width: Float,
  val height: Float,
  val nodeWidth: Float,
  val nodeHeight: Float,
)

@Composable
internal fun BreedingMindMap(
  plan: ExecutionPlanRecord,
  completed: Set<String>,
  onToggleStep: (ExecutionStepRecord) -> Unit,
  modifier: Modifier = Modifier,
  preview: Boolean = false,
  excludedMaterialAction: ((String) -> Unit)? = null,
  inventoryIds: Set<String> = emptySet(),
  onMarkInProgress: ((ExecutionStepRecord) -> Unit)? = null,
) {
  val density = LocalDensity.current
  val nodeWidth = with(density) { 320.dp.toPx() }
  val textMeasurer = rememberTextMeasurer()
  val textWidth = with(density) { (320.dp - 96.dp).roundToPx() }
  val fullRoot = remember(plan, completed) { buildRouteRoot(plan, completed, true) }
  fun textHeight(node: RouteNode): Float {
    val title = textMeasurer.measure(node.title, TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Bold),
      constraints = androidx.compose.ui.unit.Constraints(maxWidth = textWidth)).size.height
    val detail = textMeasurer.measure(routeDetail(node), TextStyle(fontSize = 12.sp),
      constraints = androidx.compose.ui.unit.Constraints(maxWidth = textWidth)).size.height
    return max((title + detail).toFloat(), node.children.maxOfOrNull { textHeight(it) } ?: 0f)
  }
  val nodeHeight = textHeight(fullRoot) + with(density) { 110.dp.toPx() }
  val horizontalGap = with(density) { 22.dp.toPx() }
  val verticalGap = with(density) { 58.dp.toPx() }
  var showSources by rememberSaveable(plan.id) { mutableStateOf(false) }
  val layout = remember(plan, completed, showSources, nodeWidth, nodeHeight) {
    buildRouteLayout(plan, nodeWidth, nodeHeight, horizontalGap, verticalGap, completed, showSources)
  }
  val pokemonAtlas = ImageBitmap.imageResource(R.drawable.pokemon_atlas)
  val itemAtlas = ImageBitmap.imageResource(R.drawable.item_atlas)
  var scale by remember(plan.id) { mutableFloatStateOf(0.8f) }
  var translation by remember(plan.id) { mutableStateOf(Offset.Zero) }
  var viewport by remember(plan.id) { mutableStateOf(IntSize.Zero) }
  var selected by remember(plan.id) { mutableStateOf<RouteNode?>(null) }
  var previousRootCenter by remember(plan.id) { mutableStateOf<Offset?>(null) }

  LaunchedEffect(layout) {
    val center = layout.nodes.first().bounds.center
    previousRootCenter?.let { previous -> translation += (previous - center) * scale }
    previousRootCenter = center
  }

  val minScale = 0.06f
  val maxScale = 2.2f
  fun rootView(targetViewport: IntSize = viewport) {
    if (targetViewport.width == 0) return
    scale = min(0.88f, (targetViewport.width - with(density) { 24.dp.toPx() }) / layout.nodeWidth)
      .coerceIn(minScale, maxScale)
    translation = Offset(
      x = targetViewport.width / 2f - (layout.nodes.first().bounds.center.x * scale),
      y = with(density) { 112.dp.toPx() } - layout.nodes.first().bounds.top * scale,
    )
  }
  fun fitAll() {
    if (viewport.width == 0 || viewport.height == 0) return
    val sideInset = with(density) { 12.dp.toPx() }
    val topInset = with(density) { 102.dp.toPx() }
    val bottomInset = with(density) { 10.dp.toPx() }
    val availableHeight = viewport.height - topInset - bottomInset
    scale = min(
      (viewport.width - sideInset * 2) / layout.width,
      availableHeight / layout.height,
    ).coerceIn(minScale, 1.1f)
    translation = Offset(
      (viewport.width - layout.width * scale) / 2f,
      topInset + (availableHeight - layout.height * scale) / 2f,
    )
  }
  fun zoomBy(multiplier: Float) {
    val oldScale = scale
    val newScale = (oldScale * multiplier).coerceIn(minScale, maxScale)
    if (newScale == oldScale || viewport == IntSize.Zero) return
    val focalPoint = Offset(viewport.width / 2f, viewport.height / 2f)
    translation = focalPoint - (focalPoint - translation) * (newScale / oldScale)
    scale = newScale
  }

  val transformableState = rememberTransformableState { zoomChange, panChange, _ ->
    zoomBy(zoomChange)
    translation += panChange
  }
  val colors = RouteColors(
    background = MaterialTheme.colorScheme.surfaceContainerLow,
    edge = MaterialTheme.colorScheme.outlineVariant,
    waiting = MaterialTheme.colorScheme.surfaceContainerHighest,
    ready = MaterialTheme.colorScheme.primaryContainer,
    complete = MaterialTheme.colorScheme.secondaryContainer,
    purchase = MaterialTheme.colorScheme.errorContainer,
    border = MaterialTheme.colorScheme.outline,
    readyBorder = MaterialTheme.colorScheme.primary,
    completeBorder = MaterialTheme.colorScheme.secondary,
    text = MaterialTheme.colorScheme.onSurface,
    mutedText = MaterialTheme.colorScheme.onSurfaceVariant,
    purchaseText = MaterialTheme.colorScheme.onErrorContainer,
  )

  Box(
    modifier = modifier
      .fillMaxSize()
      .clip(RoundedCornerShape(16.dp))
      .background(colors.background)
      .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(16.dp))
      .semantics {
        contentDescription = "${plan.targetSpecies}孵蛋路线思维导图，共${plan.steps.size}步。可单指拖动、双指缩放，点击节点查看详情。"
        stateDescription = "缩放${(scale * 100).toInt()}%"
      }
      .onSizeChanged { size ->
        val firstLayout = viewport == IntSize.Zero
        viewport = size
        if (firstLayout) rootView(size)
      },
  ) {
    Canvas(
      Modifier
        .fillMaxSize()
        .transformable(transformableState)
        .pointerInput(layout, scale, translation, preview, onMarkInProgress) {
          detectTapGestures(onDoubleTap = { point ->
            val logicalPoint = (point - translation) / scale
            val node = layout.nodes.lastOrNull { logicalPoint in it.bounds }?.node
            node?.step?.takeIf { !preview && !plan.needsReplan && it.child.id !in completed && completed.containsAll(it.dependencies) }
              ?.let { onMarkInProgress?.invoke(it) }
          }, onTap = { point ->
            val logicalPoint = (point - translation) / scale
            selected = layout.nodes.lastOrNull { logicalPoint in it.bounds }?.node
          })
        },
    ) {
      withTransform({
        translate(translation.x, translation.y)
        scale(scale, scale, Offset.Zero)
      }) {
        layout.nodes.forEach { placed ->
          val parentCenter = placed.bounds.center
          placed.node.children.forEach { child ->
            val childBounds = layout.nodes.first { it.node.key == child.key }.bounds
            val start = Offset(parentCenter.x, placed.bounds.bottom)
            val end = Offset(childBounds.center.x, childBounds.top)
            val middleY = (start.y + end.y) / 2f
            val edgeColor = routeColor(child.routeRole)
            drawLine(edgeColor, start, Offset(start.x, middleY), strokeWidth = 2.dp.toPx())
            drawLine(edgeColor, Offset(start.x, middleY), Offset(end.x, middleY), strokeWidth = 2.dp.toPx())
            drawLine(edgeColor, Offset(end.x, middleY), end, strokeWidth = 2.dp.toPx())
            if (hasSkillEdge(placed.node, child)) {
              val gap = 6.dp.toPx()
              val a = start + Offset(gap, gap)
              val b = end + Offset(gap, -gap)
              val middle = middleY + gap
              drawLine(routeColor("egg_move"), a, Offset(a.x, middle), strokeWidth = 2.dp.toPx())
              drawLine(routeColor("egg_move"), Offset(a.x, middle), Offset(b.x, middle), strokeWidth = 2.dp.toPx())
              drawLine(routeColor("egg_move"), Offset(b.x, middle), b, strokeWidth = 2.dp.toPx())
            }
          }
        }
        layout.nodes.asReversed().forEach { placed ->
          drawRouteNode(
            placed = placed,
            completed = completed,
            colors = colors,
            pokemonAtlas = pokemonAtlas,
            itemAtlas = itemAtlas,
            textMeasurer = textMeasurer,
            paused = plan.needsReplan,
            preview = preview,
          )
        }
      }
    }

    Surface(
      modifier = Modifier.align(Alignment.TopCenter).padding(top = 8.dp),
      color = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f),
      shape = RoundedCornerShape(50),
      tonalElevation = 2.dp,
    ) {
      TextButton(onClick = { showSources = !showSources }, enabled = completed.isNotEmpty()) {
        Text(if (completed.isEmpty()) "拖动 · 双指缩放 · 点节点看详情"
          else if (showSources) "收起已完成来源" else "查看已完成来源",
          style = MaterialTheme.typography.labelMedium)
      }
    }

    Surface(
      modifier = Modifier.align(Alignment.TopCenter).padding(top = 58.dp),
      color = MaterialTheme.colorScheme.surface.copy(alpha = 0.96f),
      shape = RoundedCornerShape(14.dp),
      tonalElevation = 3.dp,
    ) {
      Row(
        Modifier.padding(horizontal = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = Alignment.CenterVertically,
      ) {
        MapControl("−", "缩小思维导图") { zoomBy(1f / 1.2f) }
        MapControl("+", "放大思维导图") { zoomBy(1.2f) }
        MapControl("根节点", "回到最终成品节点") { rootView() }
        MapControl("全图", "让完整路线适应屏幕") { fitAll() }
      }
    }
  }

  selected?.let { node ->
    RouteNodeDialog(
      node = node,
      completed = node.step?.child?.id in completed,
      ready = !preview && !plan.needsReplan && node.step?.let { it.child.id !in completed && completed.containsAll(it.dependencies) } == true,
      onDismiss = { selected = null },
      onToggle = if (preview) null else node.step?.let { step -> { onToggleStep(step); selected = null } },
      onExclude = node.materialId?.takeIf { preview && !node.historical && !node.purchase && it in inventoryIds }
        ?.let { id -> excludedMaterialAction?.let { action -> { action(id); selected = null } } },
      onMemo = node.step?.takeIf { !preview && !plan.needsReplan && it.child.id !in completed && completed.containsAll(it.dependencies) }
        ?.let { step -> onMarkInProgress?.let { action -> { action(step); selected = null } } },
    )
  }
}

@Composable
private fun MapControl(label: String, description: String, onClick: () -> Unit) {
  TextButton(
    onClick = onClick,
    modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = description },
  ) { Text(label, fontWeight = FontWeight.Bold) }
}

@Composable
private fun RouteNodeDialog(
  node: RouteNode,
  completed: Boolean,
  ready: Boolean,
  onDismiss: () -> Unit,
  onToggle: (() -> Unit)?,
  onExclude: (() -> Unit)? = null,
  onMemo: (() -> Unit)? = null,
) {
  AlertDialog(
    onDismissRequest = onDismiss,
    title = { Text(node.title) },
    text = {
      Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("个体值：${node.ivText.ifBlank { "未记录" }}")
        if (node.itemKey != null) Text("携带道具：${itemLabel(node.itemKey)}")
        Text(routeDetail(node))
        node.step?.let { step ->
          Text("父母 A：${step.parentALabel}")
          Text("父母 B：${step.parentBLabel}")
          Text("本步道具：${step.itemText}", fontWeight = FontWeight.SemiBold)
        }
        if (onMemo != null) OutlinedButton(onClick = onMemo, modifier = Modifier.fillMaxWidth()) {
          Text(if (node.step?.inProgress == true) "取消正在孵化" else "标记正在孵化")
        }
      }
    },
    confirmButton = {
      if (onExclude != null) {
        Button(onClick = onExclude) { Text("本轮禁用并重算") }
      }
      if (onToggle != null) {
        Button(onClick = onToggle, enabled = ready) {
          Text(if (completed) "已核销" else if (ready) "核对并记录结果" else "尚不可执行")
        }
      }
    },
    dismissButton = { OutlinedButton(onClick = onDismiss) { Text("关闭") } },
  )
}

private data class RouteColors(
  val background: Color,
  val edge: Color,
  val waiting: Color,
  val ready: Color,
  val complete: Color,
  val purchase: Color,
  val border: Color,
  val readyBorder: Color,
  val completeBorder: Color,
  val text: Color,
  val mutedText: Color,
  val purchaseText: Color,
)

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawRouteNode(
  placed: PlacedRouteNode,
  completed: Set<String>,
  colors: RouteColors,
  pokemonAtlas: ImageBitmap,
  itemAtlas: ImageBitmap,
  textMeasurer: androidx.compose.ui.text.TextMeasurer,
  paused: Boolean = false,
  preview: Boolean = false,
) {
  val node = placed.node
  val step = node.step
  val isComplete = step?.child?.id in completed
  val isReady = !paused && step != null && !isComplete && completed.containsAll(step.dependencies)
  val fill = when (node.gender) {
    "M" -> Color(0xFFDBEAFE)
    "F" -> Color(0xFFFCE7F3)
    else -> Color(0xFFF8FAFC)
  }
  val border = routeColor(node.routeRole)
  if (node.routeMoves.isNotEmpty()) {
    val gap = 5.dp.toPx()
    drawRoundRect(routeColor("egg_move"), placed.bounds.topLeft - Offset(gap, gap),
      Size(placed.bounds.width + gap * 2, placed.bounds.height + gap * 2),
      cornerRadius = androidx.compose.ui.geometry.CornerRadius(20f), style = Stroke(2.dp.toPx()))
  }
  drawRoundRect(fill, placed.bounds.topLeft, placed.bounds.size, cornerRadius = androidx.compose.ui.geometry.CornerRadius(20f))
  drawRoundRect(border, placed.bounds.topLeft, placed.bounds.size, cornerRadius = androidx.compose.ui.geometry.CornerRadius(20f), style = Stroke(2.dp.toPx()))
  val left = placed.bounds.left + 12.dp.toPx()
  val textWidth = (placed.bounds.width - 96.dp.toPx()).toInt().coerceAtLeast(40)
  var y = placed.bounds.top + 10.dp.toPx()
  fun text(value: String, style: TextStyle) {
    val result = textMeasurer.measure(value, style, constraints = androidx.compose.ui.unit.Constraints(maxWidth = textWidth))
    drawText(result, topLeft = Offset(left, y))
    y += result.size.height + 6.dp.toPx()
  }
  val ink = Color(0xFF172033)
  text(node.title, TextStyle(color = ink, fontSize = 14.sp, fontWeight = FontWeight.Bold))
  text(node.ivText.ifBlank { "个体值未记录" }, TextStyle(color = ink, fontSize = 12.sp))
  text(routeDetail(node), TextStyle(color = Color(0xFF334155), fontSize = 12.sp))
  val status = when {
    preview && step != null -> "预览 · 未启用"
    isComplete -> "已完成"
    node.historical -> "历史来源 · 已消耗"
    step?.inProgress == true -> "孵化中"
    isReady -> "可执行"
    step != null -> if (paused) "已暂停" else "等待下层"
    node.purchase -> "待采购"
    else -> "素材 / 目标"
  }
  val statusLayout = textMeasurer.measure(status,
    TextStyle(color = ink, fontSize = 12.sp, fontWeight = FontWeight.Bold),
    constraints = androidx.compose.ui.unit.Constraints(maxWidth = textWidth))
  drawText(statusLayout, topLeft = Offset(left, placed.bounds.bottom - statusLayout.size.height - 10.dp.toPx()))

  val drawableSpeciesId = node.speciesId?.takeIf { it in 1..649 }
  drawableSpeciesId?.let { speciesId ->
    val column = (speciesId - 1) % 16
    val row = (speciesId - 1) / 16
    drawImage(
      image = pokemonAtlas,
      srcOffset = IntOffset(column * 96, row * 96),
      srcSize = IntSize(96, 96),
      dstOffset = IntOffset((placed.bounds.right - 70.dp.toPx()).toInt(), (placed.bounds.top + 8.dp.toPx()).toInt()),
      dstSize = IntSize(64.dp.toPx().toInt(), 64.dp.toPx().toInt()),
      filterQuality = FilterQuality.None,
    )
  }
  if (drawableSpeciesId == null) {
    val center = Offset(placed.bounds.right - 38.dp.toPx(), placed.bounds.top + 38.dp.toPx())
    drawCircle(colors.border, radius = 22.dp.toPx(), center = center, style = Stroke(2.dp.toPx()))
    drawLine(colors.border, Offset(center.x - 20.dp.toPx(), center.y), Offset(center.x + 20.dp.toPx(), center.y), strokeWidth = 2.dp.toPx())
    drawCircle(colors.background, radius = 6.dp.toPx(), center = center)
    drawCircle(colors.border, radius = 6.dp.toPx(), center = center, style = Stroke(1.5.dp.toPx()))
  }
  node.itemKey?.let { key ->
    val index = ITEM_KEYS.indexOf(key)
    if (index >= 0) {
      drawImage(
        image = itemAtlas,
        srcOffset = IntOffset(index * 32, 0),
        srcSize = IntSize(32, 32),
        dstOffset = IntOffset((placed.bounds.right - 50.dp.toPx()).toInt(), (placed.bounds.bottom - 38.dp.toPx()).toInt()),
        dstSize = IntSize(28.dp.toPx().toInt(), 28.dp.toPx().toInt()),
        filterQuality = FilterQuality.None,
      )
    }
  }
}

private fun buildRouteLayout(
  plan: ExecutionPlanRecord,
  nodeWidth: Float,
  nodeHeight: Float,
  horizontalGap: Float,
  verticalGap: Float,
  completed: Set<String>,
  showSources: Boolean,
): RouteLayout {
  val root = buildRouteRoot(plan, completed, showSources)
  val widthCache = mutableMapOf<String, Float>()
  fun measure(node: RouteNode): Float {
    return widthCache.getOrPut(node.key) {
      if (node.children.isEmpty()) nodeWidth else max(
        nodeWidth,
        node.children.sumOf { measure(it).toDouble() }.toFloat() + horizontalGap * (node.children.size - 1),
      )
    }
  }
  val placed = mutableListOf<PlacedRouteNode>()
  fun place(node: RouteNode, left: Float, top: Float) {
    val subtreeWidth = measure(node)
    val bounds = Rect(left + (subtreeWidth - nodeWidth) / 2f, top, left + (subtreeWidth + nodeWidth) / 2f, top + nodeHeight)
    placed += PlacedRouteNode(node, bounds)
    var childLeft = left
    node.children.forEach { child ->
      place(child, childLeft, top + nodeHeight + verticalGap)
      childLeft += measure(child) + horizontalGap
    }
  }
  val totalWidth = measure(root)
  place(root, 0f, 0f)
  val totalHeight = (placed.maxOfOrNull { it.bounds.bottom } ?: nodeHeight)
  return RouteLayout(root, placed, totalWidth, totalHeight, nodeWidth, nodeHeight)
}

internal fun buildRouteRoot(
  plan: ExecutionPlanRecord,
  completed: Set<String>,
  showSources: Boolean = false,
): RouteNode {
  val producers = plan.steps.associateBy { it.child.id }
  val finalStep = plan.steps.firstOrNull { it.isFinal } ?: plan.steps.maxByOrNull { it.number }
  val current = finalStep?.let { buildStepNode(it, producers, null, completed, showSources) }
    ?: RouteNode("target", plan.targetSpecies, "", "无需继续孵化", plan.finalTargetSpeciesId, null)
  val target = plan.finalTarget ?: return current
  if (plan.naturePhase !in setOf("maternal", "gamble_upper", "gamble_lower")) return current
  if (plan.steps.isNotEmpty() && plan.steps.all { it.child.id in completed } && !plan.needsReplan) return current
  fun retained(index: Int): RouteNode? = plan.retainedMaterials.getOrNull(index)?.let { material ->
    RouteNode("retained:${material.id}", "已保留 · ${material.species}", material.ivText,
      "${material.perfectIvCount}V · ${com.example.pokemmobreederhelper.data.genderLabel(material.gender)} · ${material.nature.ifBlank { "未命中目标性格" }}",
      null, null, routeRole = if (index == 0) "maternal" else "nature",
      gender = material.gender, routeMoves = material.moves.intersect(target.moves.toSet()).toList())
  }
  val hand = if (plan.naturePhase == "gamble_lower" && retained(1) != null) {
    RouteNode("future-hand", "${plan.targetIvCount - 1}V性格手 · 待合成", plan.retainedMaterials[1].ivText,
      plan.targetNature, null, null, routeRole = "nature", children = listOfNotNull(retained(1), current))
  } else current
  return RouteNode("final-target", "最终目标 · ${target.species}", target.ivText,
    "${target.perfectIvCount}V · ${target.nature} · 待合成", plan.finalTargetSpeciesId, null,
    routeRole = "maternal", routeMoves = target.moves, gender = target.gender,
    children = listOfNotNull(retained(0), hand))
}

private fun buildStepNode(
  step: ExecutionStepRecord,
  producers: Map<String, ExecutionStepRecord>,
  itemKey: String?,
  completed: Set<String>,
  showSources: Boolean,
): RouteNode {
  fun parentNode(
    id: String,
    label: String,
    species: String,
    speciesId: Int?,
    item: String,
    side: String,
    record: com.example.pokemmobreederhelper.data.MonsterRecord?,
    role: String,
    moves: List<String>,
  ): RouteNode {
    val key = itemKey(item)
    return producers[id]?.let { buildStepNode(it, producers, key, completed, showSources) }
      ?: RouteNode(
        key = "leaf:${step.child.id}:$side:$id",
        title = species.ifBlank { compactParentLabel(label) },
        ivText = record?.ivText ?: extractIvText(label),
        detail = record?.let { "${it.account} · ${it.positionLabel.ifBlank { "未定位" }}\n${com.example.pokemmobreederhelper.data.genderLabel(it.gender)} · ${it.nature.ifBlank { "性格未知" }}" } ?: label,
        routeRole = role, routeMoves = moves, gender = record?.gender.orEmpty(),
        historical = step.child.id in completed,
        speciesId = speciesId,
        itemKey = key,
        purchase = id.startsWith("buy:"),
        materialId = id,
      )
  }
  val children = listOf(
    parentNode(step.parentAId, step.parentALabel, step.parentASpecies, step.parentASpeciesId, step.itemA, "a", step.parentARecord, step.parentARole, step.parentAMoves),
    parentNode(step.parentBId, step.parentBLabel, step.parentBSpecies, step.parentBSpeciesId, step.itemB, "b", step.parentBRecord, step.parentBRole, step.parentBMoves),
  )
  return RouteNode(
    key = "step:${step.child.id}",
    title = "步骤 ${step.number} · ${step.child.species}",
    ivText = step.child.ivText,
    detail = step.genderInstruction,
    routeRole = step.routeRole, routeMoves = step.routeMoves, gender = step.displayGender,
    speciesId = step.childSpeciesId,
    itemKey = itemKey,
    step = step,
    children = if (step.child.id in completed && !showSources) emptyList() else children,
  )
}

private fun compactParentLabel(label: String): String =
  label.substringBefore(" · ").substringBefore("（").take(24).ifBlank { "未知素材" }

private fun extractIvText(label: String): String =
  Regex("(?:31|[0-9]{1,2}|[Xx])(?:/(?:31|[0-9]{1,2}|[Xx])){5}")
    .find(label)?.value?.uppercase() ?: ""

private fun itemKey(item: String): String? = when {
  "HP" in item || "体力" in item -> "power-weight"
  "攻击" in item && "特攻" !in item -> "power-bracer"
  "防御" in item && "特防" !in item -> "power-belt"
  "特攻" in item -> "power-lens"
  "特防" in item -> "power-band"
  "速度" in item -> "power-anklet"
  "不变" in item -> "everstone"
  else -> null
}

private fun itemLabel(key: String): String = when (key) {
  "power-weight" -> "HP 护腕"
  "power-bracer" -> "攻击护腕"
  "power-belt" -> "防御护腕"
  "power-lens" -> "特攻护腕"
  "power-band" -> "特防护腕"
  "power-anklet" -> "速度护腕"
  "everstone" -> "不变之石"
  else -> "未知道具"
}

private val ITEM_KEYS = listOf(
  "power-weight",
  "power-bracer",
  "power-belt",
  "power-lens",
  "power-band",
  "power-anklet",
  "everstone",
)

internal fun hasSkillEdge(parent: RouteNode, child: RouteNode): Boolean =
  parent.routeMoves.any { it in child.routeMoves }

internal fun routeColor(role: String): Color = when (role) {
  "maternal" -> Color(0xFF2563EB)
  "nature" -> Color(0xFF7C3AED)
  "egg_move" -> Color(0xFFC2410C)
  else -> Color(0xFF64748B)
}

private fun routeDetail(node: RouteNode): String {
  val role = when (node.routeRole) {
    "maternal" -> "母体主线"
    "nature" -> "性格手"
    "egg_move" -> "遗传技能"
    else -> "IV 素材"
  }
  return role + (if (node.routeMoves.isEmpty()) "" else "＋遗传技能：${node.routeMoves.joinToString("、")}") +
    "\n" + node.detail + (node.itemKey?.let { "\n携带：${itemLabel(it)}" } ?: "")
}
