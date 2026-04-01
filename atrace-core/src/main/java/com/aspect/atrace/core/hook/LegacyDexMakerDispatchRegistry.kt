/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.hook

import com.aspect.atrace.ALog
import com.aspect.atrace.ATrace
import com.swift.sandhook.SandHook
import java.lang.reflect.Member
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * Public entry point for DexMaker-generated hook classes. They live in another dex
 * file and cannot invoke methods on [SandHookDexMakerBackend]'s private nested types.
 */
internal object LegacyDexMakerDispatchRegistry {
    private const val TAG = "LegacyDexMakerDispatch"

    private val idGen = AtomicInteger(1)
    private val entries = ConcurrentHashMap<Int, DispatchEntry>()

    private data class DispatchEntry(val target: Member, val sectionName: String)

    fun register(target: Member, sectionName: String): Int {
        val id = idGen.getAndIncrement()
        entries[id] = DispatchEntry(target, sectionName)
        return id
    }

    fun remove(id: Int) {
        entries.remove(id)
    }

    @JvmStatic
    fun dispatchInvoke(id: Int, receiver: Any?, args: Array<Any?>): Any? {
        val e = entries[id]
        if (e == null) {
            ALog.w(TAG, "dispatchInvoke: no entry for id=$id")
            return null
        }
        val argCount = args.size
        ALog.d(TAG, "dispatchInvoke begin id=$id section=${e.sectionName} args=$argCount")
        val token = ATrace.beginSection(e.sectionName)
        return try {
            SandHook.callOriginMethod(e.target, receiver, *args)
        } finally {
            if (token >= 0) ATrace.endSection(token)
            ALog.d(TAG, "dispatchInvoke end id=$id section=${e.sectionName}")
        }
    }
}
