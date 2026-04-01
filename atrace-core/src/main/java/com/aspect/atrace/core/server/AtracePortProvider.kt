/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.server

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri

/**
 * 通过 ContentProvider 暴露 ATrace HTTP 监听端口，便于 Release 等无法读取
 * `Android/data/.../files/atrace-port` 时由 PC 侧执行：
 *
 * ```
 * adb shell content query --uri content://<applicationId>.atrace/atrace/port
 * ```
 *
 * 返回单列 [port]：服务未启动时为 -1。
 *
 * Authority 与清单中 `android:authorities` 一致，一般为 `<applicationId>.atrace`。
 */
class AtracePortProvider : ContentProvider() {

    override fun onCreate(): Boolean = true

    override fun query(
        uri: Uri,
        projection: Array<out String>?,
        selection: String?,
        selectionArgs: Array<out String>?,
        sortOrder: String?,
    ): Cursor? {
        val segs = uri.pathSegments
        if (segs.size != 2 || segs[0] != PATH_ATRACE || segs[1] != PATH_PORT) {
            throw IllegalArgumentException("Unsupported URI: $uri (expected .../atrace/port)")
        }
        val port = ServerManager.getPort()
        val cols = projection?.takeIf { it.isNotEmpty() } ?: DEFAULT_PROJECTION
        val matrix = MatrixCursor(cols, 1)
        val row = Array<Any?>(cols.size) { i ->
            when (cols[i]) {
                COLUMN_PORT -> port
                else -> null
            }
        }
        matrix.addRow(row)
        return matrix
    }

    override fun getType(uri: Uri): String? {
        val segs = uri.pathSegments
        if (segs.size == 2 && segs[0] == PATH_ATRACE && segs[1] == PATH_PORT) {
            return "vnd.android.cursor.item/vnd.${uri.authority}.port"
        }
        return null
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun update(
        uri: Uri,
        values: ContentValues?,
        selection: String?,
        selectionArgs: Array<out String>?,
    ): Int = 0

    companion object {
        private const val PATH_ATRACE = "atrace"
        private const val PATH_PORT = "port"
        private const val COLUMN_PORT = "port"

        private val DEFAULT_PROJECTION = arrayOf(COLUMN_PORT)

        /**
         * 构建查询 URI（与 [AtracePortProvider] 清单 authority 一致时使用）。
         */
        @JvmStatic
        fun buildPortUri(authority: String): Uri =
            Uri.Builder()
                .scheme("content")
                .authority(authority)
                .appendPath(PATH_ATRACE)
                .appendPath(PATH_PORT)
                .build()
    }
}
