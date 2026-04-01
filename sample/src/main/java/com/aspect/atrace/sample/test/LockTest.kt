/*
 * Copyright (c) 2024 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.sample.test

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.LockSupport

/**
 * 锁竞争测试
 *
 * 测试 synchronized, Object.wait, Unsafe.park 等
 */
object LockTest {
    private val lock = Object()
    private val waitLock =Object()

    fun test() {
        // 测试 synchronized
        testSynchronized()

        // 测试 Object.wait
        testObjectWait()

        // 测试 Unsafe.park
        testUnsafePark()
    }

    /**
     * 测试 synchronized 锁竞争
     */
    private fun testSynchronized() {
        Thread {
            synchronized(lock) {
                Thread.sleep(1000)
            }
        }.start()

        Thread {
            Thread.sleep(50) // 让第一个线程先获取锁
            synchronized(lock) {
                // 第二个线程会等待
            }
        }.start()
    }

    /**
     * 测试 Object.wait/notify
     */
    private fun testObjectWait() {
        val latch = CountDownLatch(1)

        // 等待线程
        Thread {
            synchronized(waitLock) {
                try {
                    waitLock.wait(1000)
                } catch (e: InterruptedException) {
                    e.printStackTrace()
                }
            }
            latch.countDown()
        }.start()

        // 通知线程
        Thread {
            Thread.sleep(100)
            synchronized(waitLock) {
                waitLock.notify()
            }
        }.start()

        try {
            latch.await(2, TimeUnit.SECONDS)
        } catch (e: InterruptedException) {
            e.printStackTrace()
        }
    }

    /**
     * 测试 Unsafe.park (LockSupport)
     */
    private fun testUnsafePark() {
        val thread = Thread {
            LockSupport.parkNanos(TimeUnit.MILLISECONDS.toNanos(200))
        }
        thread.start()

        Thread {
            Thread.sleep(100)
            LockSupport.unpark(thread)
        }.start()

        try {
            thread.join(1000)
        } catch (e: InterruptedException) {
            e.printStackTrace()
        }
    }
}
