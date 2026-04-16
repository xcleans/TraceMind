/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "ThreadListHook.h"
#include "AllocCommon.h"

#include <shadowhook.h>
#define ATRACE_LOG_TAG "ThreadList"
#include "utils/atrace_log.h"

namespace atrace {
namespace alloc {

static void* g_thread_init_stub = nullptr;
static void* g_finalizer_stub = nullptr;
static OnThreadListReady g_callback = nullptr;

/**
 * 检查是否都就绪，触发回调
 */
static void CheckAndNotify() {
    auto& ctx = GetAllocContext();
    if (ctx.heap && ctx.thread_list && g_callback) {
        ALOGI("ThreadList and Heap ready");
        g_callback(ctx.thread_list);
    }
}

/**
 * Thread::Init 代理
 * 
 * 从这里获取 ThreadList 指针
 */
static bool Proxy_Thread_Init(void* thread, void* thread_list, 
                               void* java_vm_ext, void* jni_env_ext) {
    SHADOWHOOK_STACK_SCOPE();
    
    auto& ctx = GetAllocContext();
    ctx.thread_list = thread_list;
    ALOGI("Got ThreadList: %p", thread_list);
    
    bool result = SHADOWHOOK_CALL_PREV(Proxy_Thread_Init, 
                                        thread, thread_list, java_vm_ext, jni_env_ext);
    
    CheckAndNotify();
    
    // 只需要 Hook 一次
    if (g_thread_init_stub) {
        shadowhook_unhook(g_thread_init_stub);
        g_thread_init_stub = nullptr;
    }
    
    return result;
}

/**
 * Heap::AddFinalizerReference 代理
 * 
 * 从这里获取 Heap 指针
 */
static void Proxy_AddFinalizerReference(void* heap, void* self, void* object) {
    SHADOWHOOK_STACK_SCOPE();
    
    auto& ctx = GetAllocContext();
    ctx.heap = heap;
    ALOGI("Got Heap: %p", heap);
    
    // 只需要 Hook 一次
    if (g_finalizer_stub) {
        shadowhook_unhook(g_finalizer_stub);
        g_finalizer_stub = nullptr;
    }
    
    CheckAndNotify();
    
    SHADOWHOOK_CALL_PREV(Proxy_AddFinalizerReference, heap, self, object);
}

bool InitThreadListHook() {
    auto& ctx = GetAllocContext();
    
    // 如果已经有了，直接返回
    if (ctx.thread_list && ctx.heap) {
        return true;
    }
    
    // Hook Thread::Init
    if (!g_thread_init_stub && !ctx.thread_list) {
        g_thread_init_stub = shadowhook_hook_sym_name(
            "libart.so",
            THREAD_INIT,
            reinterpret_cast<void*>(Proxy_Thread_Init),
            nullptr);
        
        if (!g_thread_init_stub) {
            ALOGE("Failed to hook Thread::Init");
            return false;
        }
        ALOGI("Hooked Thread::Init");
    }
    
    // Hook Heap::AddFinalizerReference
    if (!g_finalizer_stub && !ctx.heap) {
        g_finalizer_stub = shadowhook_hook_sym_name(
            "libart.so",
            HEAP_ADD_FINALIZER_REFERENCE,
            reinterpret_cast<void*>(Proxy_AddFinalizerReference),
            nullptr);
        
        if (!g_finalizer_stub) {
            ALOGE("Failed to hook Heap::AddFinalizerReference");
            return false;
        }
        ALOGI("Hooked Heap::AddFinalizerReference");
    }
    
    return true;
}

void SetThreadListReadyCallback(OnThreadListReady callback) {
    g_callback = std::move(callback);
    
    // 如果已经就绪，立即回调
    auto& ctx = GetAllocContext();
    if (ctx.heap && ctx.thread_list && g_callback) {
        g_callback(ctx.thread_list);
    }
}

void DestroyThreadListHook() {
    if (g_thread_init_stub) {
        shadowhook_unhook(g_thread_init_stub);
        g_thread_init_stub = nullptr;
    }
    if (g_finalizer_stub) {
        shadowhook_unhook(g_finalizer_stub);
        g_finalizer_stub = nullptr;
    }
    g_callback = nullptr;
}

} // namespace alloc
} // namespace atrace

