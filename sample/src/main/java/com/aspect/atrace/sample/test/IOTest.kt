/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import android.content.Context
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

/**
 * IO 测试
 *
 * 测试文件读写操作
 */
object IOTest {
    fun test(context: Context) {
        Thread {
            val file = File(context.cacheDir, "test_io.txt")

            // 写入测试
            try {
                FileOutputStream(file).use { fos ->
                    val data = "Hello ATrace IO Test\n".repeat(1000).toByteArray()
                    fos.write(data)
                    fos.flush()
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }

            // 读取测试
            try {
                FileInputStream(file).use { fis ->
                    val buffer = ByteArray(1024)
                    while (fis.read(buffer) > 0) {
                        // 读取数据
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }

            // 多次读写
            repeat(10) {
                try {
                    FileOutputStream(file).use { fos ->
                        fos.write("Test $it\n".toByteArray())
                    }

                    FileInputStream(file).use { fis ->
                        val buffer = ByteArray(1024)
                        fis.read(buffer)
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                }
            }

            // 清理
            file.delete()
        }.start()
    }
}
