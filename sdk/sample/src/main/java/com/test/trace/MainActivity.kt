/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.staggeredgrid.LazyVerticalStaggeredGrid
import androidx.compose.foundation.lazy.staggeredgrid.StaggeredGridCells
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.lazy.items as lazyItems
import androidx.compose.foundation.lazy.staggeredgrid.items as staggeredItems
import com.aspect.atrace.ATrace
import com.aspect.atrace.sample.test.*
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults

/**
 * Main Activity - 使用 Material3 默认容器和轻量页面管理器重构 demo。
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            ATraceSampleTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    DemoApp(showToast = ::showToast)
                }
            }
        }
    }

    private fun showToast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }
}

private enum class BottomTab(
    val label: String,
    val shortLabel: String
) {
    Home(label = "首页", shortLabel = "首"),
    Trace(label = "追踪", shortLabel = "追"),
    Tests(label = "压测", shortLabel = "测")
}

private sealed interface SecondaryPage {
    val title: String

    data object ComposeWaterfall : SecondaryPage {
        override val title: String = "Compose 瀑布流"
    }

    data object NativeWaterfall : SecondaryPage {
        override val title: String = "Native 瀑布流"
    }
}

private class DemoPageManager(initialTab: BottomTab = BottomTab.Home) {
    var currentTab by mutableStateOf(initialTab)
        private set

    private val backStack = mutableStateListOf<SecondaryPage>()

    val currentSecondaryPage: SecondaryPage?
        get() = backStack.lastOrNull()

    fun selectTab(tab: BottomTab) {
        currentTab = tab
        backStack.clear()
    }

    fun push(page: SecondaryPage) {
        backStack += page
    }

    fun pop() {
        if (backStack.isNotEmpty()) {
            backStack.removeAt(backStack.lastIndex)
        }
    }

    fun canGoBack(): Boolean = backStack.isNotEmpty()
}

@Composable
private fun rememberDemoPageManager(): DemoPageManager {
    return remember { DemoPageManager() }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DemoApp(showToast: (String) -> Unit) {
    val pageManager = rememberDemoPageManager()
    val waterfallItems = remember { sampleWaterfallItems() }
    val currentPage = pageManager.currentSecondaryPage
    val title = currentPage?.title ?: when (pageManager.currentTab) {
        BottomTab.Home -> "ATrace Demo"
        BottomTab.Trace -> "Trace 控制台"
        BottomTab.Tests -> "压测实验室"
    }

    BackHandler(enabled = pageManager.canGoBack()) {
        pageManager.pop()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = title) },
                navigationIcon = {
                    if (pageManager.canGoBack()) {
                        TextButton(onClick = pageManager::pop) {
                            Text("返回")
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface
                )
            )
        },
        bottomBar = {
            if (currentPage == null) {
                NavigationBar {
                    BottomTab.entries.forEach { tab ->
                        NavigationBarItem(
                            selected = pageManager.currentTab == tab,
                            onClick = { pageManager.selectTab(tab) },
                            icon = { Text(tab.shortLabel) },
                            label = { Text(tab.label) }
                        )
                    }
                }
            }
        }
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            when (currentPage) {
                SecondaryPage.ComposeWaterfall -> ComposeWaterfallScreen(waterfallItems)
                SecondaryPage.NativeWaterfall -> NativeWaterfallScreen(waterfallItems)
                null -> when (pageManager.currentTab) {
                    BottomTab.Home -> HomeTab(
                        onOpenComposeWaterfall = {
                            pageManager.push(SecondaryPage.ComposeWaterfall)
                        },
                        onOpenNativeWaterfall = {
                            pageManager.push(SecondaryPage.NativeWaterfall)
                        }
                    )

                    BottomTab.Trace -> TraceTab(showToast = showToast)
                    BottomTab.Tests -> TestsTab(showToast = showToast)
                }
            }
        }
    }
}

@Composable
private fun HomeTab(
    onOpenComposeWaterfall: () -> Unit,
    onOpenNativeWaterfall: () -> Unit
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer
                )
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    Text(
                        text = "默认容器 Demo",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "使用 Scaffold + Bottom Tabs + 轻量页面栈管理，演示 ATrace 控制、压测入口和二级页面跳转。",
                        style = MaterialTheme.typography.bodyLarge
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        FilledTonalButton(onClick = onOpenComposeWaterfall) {
                            Text("Compose 瀑布流")
                        }
                        OutlinedButton(onClick = onOpenNativeWaterfall) {
                            Text("Native 瀑布流")
                        }
                    }
                }
            }
        }

        item {
            FeatureCard(
                title = "新的页面管理器",
                description = "一级页面用底部 Tab 切换，二级页面通过页面栈 push/pop 管理，返回逻辑统一处理。"
            )
        }

        item {
            FeatureCard(
                title = "Compose 默认容器",
                description = "整体结构基于 Material3 Scaffold，顶部栏、底部栏、卡片和按钮都使用默认组件拼装。"
            )
        }

        item {
            FeatureCard(
                title = "瀑布流对比入口",
                description = "同一组数据分别用 Compose `LazyVerticalStaggeredGrid` 和 Native `RecyclerView` 实现。"
            )
        }
    }
}

@Composable
private fun FeatureCard(
    title: String,
    description: String
) {
    Card {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            Text(
                text = description,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun TraceTab(showToast: (String) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            SectionHeader(
                title = "基础控制",
                description = "ATrace 生命周期与导出能力。"
            )
        }

        lazyItems(
            listOf(
                ActionSpec("开始追踪", "启动当前进程的 trace 采样。"),
                ActionSpec("停止追踪", "停止但不导出数据。"),
                ActionSpec("停止并导出", "停止采样并导出 trace 文件。"),
                ActionSpec("手动捕获堆栈", "立即补采一份栈信息。")
            )
        ) { action ->
            ActionCard(
                action = action,
                buttonLabel = "执行",
                onClick = {
                    when (action.title) {
                        "开始追踪" -> {
                            val token = ATrace.start()
                            showToast(if (token >= 0) "追踪已开始 (token: $token)" else "追踪启动失败")
                        }

                        "停止追踪" -> {
                            val token = ATrace.stop()
                            showToast(if (token >= 0) "追踪已停止 (token: $token)" else "追踪停止失败")
                        }

                        "停止并导出" -> {
                            val file = ATrace.stopAndExport()
                            showToast(if (file != null) "已导出到: ${file.absolutePath}" else "导出失败")
                        }

                        "手动捕获堆栈" -> {
                            ATrace.capture(force = true)
                            showToast("已手动捕获堆栈")
                        }
                    }
                }
            )
        }
    }
}

@Composable
private fun TestsTab(showToast: (String) -> Unit) {
    val activity = LocalContext.current as? MainActivity ?: return

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            SectionHeader(
                title = "功能测试",
                description = "保留原 demo 中的压测与故障注入能力。"
            )
        }

        lazyItems(
            listOf(
                ActionSpec("测试 Binder IPC", "触发跨进程通信压力。"),
                ActionSpec("测试 GC", "制造对象并触发垃圾回收。"),
                ActionSpec("测试锁竞争", "模拟多线程锁竞争。"),
                ActionSpec("测试对象分配", "放大分配热点。"),
                ActionSpec("测试 IO", "执行文件读写测试。"),
                ActionSpec("测试 JNI", "走 JNI 调用链。"),
                ActionSpec("测试多线程", "创建多线程并发任务。"),
                ActionSpec("测试 MessageQueue", "模拟消息循环负载。"),
                ActionSpec("测试ART 方法拦截", "测试ART 方法拦截"),
                ActionSpec("综合测试（全部）", "批量执行所有测试入口。")
            )
        ) { action ->
            ActionCard(
                action = action,
                buttonLabel = "运行",
                onClick = {
                    when (action.title) {
                        "测试 Binder IPC" -> BinderTest.test(activity)
                        "测试 GC" -> GCTest.test()
                        "测试锁竞争" -> LockTest.test()
                        "测试对象分配" -> AllocTest.test()
                        "测试 IO" -> IOTest.test(activity)
                        "测试 JNI" -> JNITest.test()
                        "测试多线程" -> ThreadTest.test()
                        "测试 MessageQueue" -> MessageQueueTest.test(activity)
                        "测试ART 方法拦截" -> {
                            ArtInvokeCallTest().test()
                            ArtMethodCallTest.testStaticCall()
                        }

                        "综合测试（全部）" -> runAllTests(activity)
                    }
                    showToast("${action.title} 已启动")
                }
            )
        }
    }
}

@Composable
private fun SectionHeader(
    title: String,
    description: String
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = description,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun ActionCard(
    action: ActionSpec,
    buttonLabel: String,
    onClick: () -> Unit
) {
    Card {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = action.title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold
            )
            Text(
                text = action.description,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Button(onClick = onClick) {
                Text(buttonLabel)
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ComposeWaterfallScreen(items: List<WaterfallCardItem>) {
    LazyVerticalStaggeredGrid(
        columns = StaggeredGridCells.Fixed(2),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalItemSpacing = 12.dp,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        staggeredItems(items = items, key = { it.id }) { item ->
            WaterfallComposeCard(item = item)
        }
    }
}

/**
 * 瀑布流单卡：减少 Text 节点与每帧分配（remember 渐变、AnnotatedString 合并标题区文案），
 * 布局用单 Box + alignment，降低 measure 深度。
 */
@Composable
private fun WaterfallComposeCard(item: WaterfallCardItem) {
    val scheme = MaterialTheme.colorScheme
    val typography = MaterialTheme.typography
    val gradient = remember(item.id, item.colorHex) {
        Brush.verticalGradient(
            colors = listOf(
                Color.White,
                colorFromHex(item.colorHex)
            )
        )
    }
    val primary = scheme.primary
    val onSurface = scheme.onSurface
    val labelFontSize = typography.labelMedium.fontSize
    val titleFontSize = typography.titleLarge.fontSize
    val titleBlock =
        remember(item.id, item.title, primary, onSurface, labelFontSize, titleFontSize) {
            buildAnnotatedString {
                withStyle(
                    SpanStyle(
                        color = primary,
                        fontSize = labelFontSize,
                        fontWeight = FontWeight.Medium
                    )
                ) {
                    append("Compose")
                }
                append("\n")
                withStyle(
                    SpanStyle(
                        fontSize = titleFontSize,
                        fontWeight = FontWeight.Bold,
                        color = onSurface
                    )
                ) {
                    append(item.title)
                }
            }
        }

    Card(
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth()
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(item.heightDp.dp)
                .background(brush = gradient)
                .padding(14.dp)
        ) {
            Text(
                text = titleBlock,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.align(Alignment.TopStart)
            )
            Text(
                text = item.subtitle,
                style = typography.bodyMedium,
                color = scheme.onSurfaceVariant,
                modifier = Modifier.align(Alignment.BottomStart)
            )
        }
    }
}

@Composable
private fun NativeWaterfallScreen(items: List<WaterfallCardItem>) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        NativeWaterfallView(
            items = items,
            modifier = Modifier.fillMaxSize()
        )
    }
}

@Immutable
private data class ActionSpec(
    val title: String,
    val description: String
)

private fun runAllTests(activity: MainActivity) {
    Thread {
//        BinderTest.test(activity)
//        Thread.sleep(100)
//        GCTest.test()
//        Thread.sleep(100)
//        LockTest.test()
//        Thread.sleep(100)
//        AllocTest.test()
//        Thread.sleep(100)
//        IOTest.test(activity)
//        Thread.sleep(100)
//        JNITest.test()
//        Thread.sleep(100)
//        ThreadTest.test()
//        Thread.sleep(100)
//        MessageQueueTest.test(activity)
    }.start()
}

/**
 * 将 `#RGB` / `#RRGGBB` / `#AARRGGBB` 等字符串转为 Compose [Color]。
 *
 * **解析说明**：[android.graphics.Color.parseColor] 返回 **有符号** `Int`（位型为 0xAARRGGBB）。
 * 当 Alpha 较高时该 `Int` 常为**负数**；若直接 `colorInt.toLong()`，会做 **64 位符号扩展**，
 * 高 32 位非 0，而 [Color] 的 `Color(Long)` 只应携带 **低 32 位** ARGB，错误扩展会破坏打包格式。
 *
 * **正确做法**：先把 `Int` 按 **无符号 32 位** 理解再写入 `Long`（二选一即可）：
 * - `colorInt.toUInt().toLong()`（推荐，语义清晰）
 * - `colorInt.toLong() and 0xFFFFFFFFL`（与注释中「屏蔽符号扩展」等价）
 *
 * **异常**：非法 `hex` 时 `parseColor` 会抛 [IllegalArgumentException]。
 */
private fun colorFromHex(hex: String): Color {
    val argb = android.graphics.Color.parseColor(hex)
    return Color(argb.toUInt().toLong())
}
