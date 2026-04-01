/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.test.trace

import android.content.Context
import android.graphics.Color as AndroidColor
import android.graphics.Typeface
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.viewinterop.AndroidView
import androidx.recyclerview.widget.RecyclerView
import androidx.recyclerview.widget.StaggeredGridLayoutManager
import kotlin.math.roundToInt

@Immutable
data class WaterfallCardItem(
    val id: Int,
    val title: String,
    val subtitle: String,
    val heightDp: Int,
    val colorHex: String
)

fun sampleWaterfallItems(): List<WaterfallCardItem> {
    val heights = listOf(148, 216, 184, 260, 172, 228, 196, 286, 154, 210, 178, 246)
    val colors = listOf(
        "#DDEBFF",
        "#FDE3D8",
        "#E6F7E8",
        "#F6E7FF",
        "#FFF0BF",
        "#DDF6F6"
    )

    return List(24) { index ->
        WaterfallCardItem(
            id = index,
            title = "卡片 ${index + 1}",
            subtitle = if (index % 2 == 0) "Compose / Native 共用数据源" else "用于模拟不同高度内容",
            heightDp = heights[index % heights.size],
            colorHex = colors[index % colors.size]
        )
    }
}

@Composable
fun NativeWaterfallView(
    items: List<WaterfallCardItem>,
    modifier: Modifier = Modifier
) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            RecyclerView(context).apply {
                layoutManager = StaggeredGridLayoutManager(2, StaggeredGridLayoutManager.VERTICAL)
                clipToPadding = false
                setPadding(dp(context, 12), dp(context, 12), dp(context, 12), dp(context, 24))
                adapter = NativeWaterfallAdapter(context, items)
                addItemDecoration(SpacingDecoration(dp(context, 12)))
            }
        },
        update = { view ->
            (view.adapter as? NativeWaterfallAdapter)?.submitList(items)
        }
    )
}

private class NativeWaterfallAdapter(
    private val context: Context,
    items: List<WaterfallCardItem>
) : RecyclerView.Adapter<NativeWaterfallAdapter.NativeWaterfallViewHolder>() {

    private var data: List<WaterfallCardItem> = items

    fun submitList(items: List<WaterfallCardItem>) {
        data = items
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): NativeWaterfallViewHolder {
        val container = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.BOTTOM
            setPadding(dp(context, 14), dp(context, 14), dp(context, 14), dp(context, 14))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            background = android.graphics.drawable.GradientDrawable().apply {
                cornerRadius = dp(context, 18).toFloat()
                setColor(AndroidColor.WHITE)
            }
            elevation = dp(context, 2).toFloat()
        }

        val badge = TextView(context).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            setTypeface(typeface, Typeface.BOLD)
            setPadding(dp(context, 10), dp(context, 4), dp(context, 10), dp(context, 4))
            setTextColor(AndroidColor.parseColor("#25324A"))
            background = android.graphics.drawable.GradientDrawable().apply {
                cornerRadius = dp(context, 999).toFloat()
                setColor(AndroidColor.parseColor("#F8F4E8"))
            }
        }

        val spacer = View(context).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
            )
        }

        val title = TextView(context).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
            setTypeface(typeface, Typeface.BOLD)
            setTextColor(AndroidColor.parseColor("#162033"))
        }

        val subtitle = TextView(context).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setLineSpacing(0f, 1.15f)
            setTextColor(AndroidColor.parseColor("#5B6578"))
        }

        container.addView(badge)
        container.addView(spacer)
        container.addView(title)
        container.addView(subtitle)

        return NativeWaterfallViewHolder(
            root = FrameLayout(context).apply {
                addView(
                    container,
                    FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                    )
                )
            },
            container = container,
            badge = badge,
            title = title,
            subtitle = subtitle
        )
    }

    override fun onBindViewHolder(holder: NativeWaterfallViewHolder, position: Int) {
        val item = data[position]
        holder.badge.text = "Native"
        holder.title.text = item.title
        holder.subtitle.text = item.subtitle
        holder.container.minimumHeight = dp(context, item.heightDp)
        holder.container.background = android.graphics.drawable.GradientDrawable().apply {
            cornerRadius = dp(context, 18).toFloat()
            colors = intArrayOf(AndroidColor.WHITE, AndroidColor.parseColor(item.colorHex))
        }
    }

    override fun getItemCount(): Int = data.size

    class NativeWaterfallViewHolder(
        root: View,
        val container: LinearLayout,
        val badge: TextView,
        val title: TextView,
        val subtitle: TextView
    ) : RecyclerView.ViewHolder(root)
}

private class SpacingDecoration(
    private val spacingPx: Int
) : RecyclerView.ItemDecoration() {
    override fun getItemOffsets(
        outRect: android.graphics.Rect,
        view: View,
        parent: RecyclerView,
        state: RecyclerView.State
    ) {
        outRect.left = spacingPx / 2
        outRect.right = spacingPx / 2
        outRect.top = spacingPx / 2
        outRect.bottom = spacingPx / 2
    }
}

private fun dp(context: Context, value: Int): Int {
    return TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP,
        value.toFloat(),
        context.resources.displayMetrics
    ).roundToInt()
}
