/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Java Object Allocation Hook
 */
#pragma once

#include <jni.h>
#include <atomic>

namespace atrace {
namespace alloc {

/**
 * 对象分配统计
 */
struct AllocStats {
    std::atomic<uint64_t> total_bytes{0};
    std::atomic<uint64_t> total_objects{0};
    
    void Add(size_t bytes) {
        total_bytes.fetch_add(bytes, std::memory_order_relaxed);
        total_objects.fetch_add(1, std::memory_order_relaxed);
    }
    
    void Reset() {
        total_bytes.store(0, std::memory_order_relaxed);
        total_objects.store(0, std::memory_order_relaxed);
    }
};

/**
 * 初始化 Alloc Hook
 * 
 * @param sdk_version Android SDK 版本
 * @return 是否成功
 */
bool InitAllocHook(int sdk_version);

/**
 * 启用/禁用 Alloc Hook
 */
void SetAllocHookEnabled(bool enabled);

/**
 * 是否已启用
 */
bool IsAllocHookEnabled();

/**
 * 获取分配统计
 */
AllocStats& GetAllocStats();

/**
 * 线程局部分配统计
 */
struct ThreadAllocStats {
    uint64_t bytes = 0;
    uint64_t objects = 0;
    
    void Add(size_t b) {
        bytes += b;
        objects++;
    }
    
    void Reset() {
        bytes = 0;
        objects = 0;
    }
};

/**
 * 获取当前线程的分配统计
 */
ThreadAllocStats& GetThreadAllocStats();

/**
 * 销毁 Alloc Hook
 */
void DestroyAllocHook();

} // namespace alloc
} // namespace atrace

