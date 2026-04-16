/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "AllocHook.h"
#include "AllocCommon.h"
#include "Checkpoint.h"
#include "ThreadListHook.h"
#include "include/atrace.h"
#include "utils/dl_utils.h"

#include <shadowhook.h>
#include <android/api-level.h>
#include <dlfcn.h>
#include <unistd.h>
#include <mutex>
#include <condition_variable>
#define ATRACE_LOG_TAG "Alloc"
#include "utils/atrace_log.h"

namespace atrace {
namespace alloc {

// ===== 全局状态 =====
static std::atomic<bool> g_enabled{false};
static AllocStats g_stats;
static thread_local ThreadAllocStats g_thread_stats;
static int g_sdk_version = 0;

// ===== ART 函数指针 =====
static SetPtr g_set_allocation_listener = nullptr;
static CallVoid g_remove_allocation_listener = nullptr;
static void* g_set_entrypoints_stub = nullptr;
static thread_local bool g_in_self_set = false;

// ===== AllocationListener 实现 =====

/**
 * AllocationListener for Android 8.0 - 10 (API 26-29)
 */
class AllocationListener26 {
public:
    virtual ~AllocationListener26() = default;
    virtual void ObjectAllocated(void* self, void** obj, size_t byte_count) = 0;
};

/**
 * AllocationListener for Android 11+ (API 30+)
 */
class AllocationListener30 {
public:
    virtual ~AllocationListener30() = default;
    
    virtual void PreObjectAllocated(void* self, void* type, size_t* byte_count) {}
    virtual bool HasPreAlloc() const { return false; }
    virtual void ObjectAllocated(void* self, void** obj, size_t byte_count) = 0;
};

/**
 * 对象分配回调
 */
static void OnObjectAllocated(void* /* self */, void** /* obj */, size_t byte_count) {
    if (!g_enabled.load(std::memory_order_relaxed)) {
        return;
    }
    
    // 更新统计
    g_stats.Add(byte_count);
    g_thread_stats.Add(byte_count);
    
    // 请求采样
    RequestSample(SampleType::kObjectAlloc);
}

/**
 * Android 8.0 - 10 的 Listener 实现
 */
class MyAllocationListener26 : public AllocationListener26 {
public:
    void ObjectAllocated(void* self, void** obj, size_t byte_count) override {
        OnObjectAllocated(self, obj, byte_count);
    }
};

/**
 * Android 11+ 的 Listener 实现
 */
class MyAllocationListener30 : public AllocationListener30 {
public:
    bool HasPreAlloc() const override { return false; }
    
    void ObjectAllocated(void* self, void** obj, size_t byte_count) override {
        OnObjectAllocated(self, obj, byte_count);
    }
};

static void* g_listener = nullptr;

// ===== Checkpoint Closure 实现 =====

/**
 * Checkpoint 回调
 * 
 * 在每个线程上重置分配入口点
 */
class CheckpointClosure : public Closure {
public:
    static CheckpointClosure* Create() {
        return new CheckpointClosure();
    }
    
    void Run(void* thread) override {
        void* reset_func = GetResetQuickAllocEntryPointsFunc();
        if (reset_func) {
            if (UseResetQuickAllocEntryPointsWithBool()) {
                reinterpret_cast<CallVoidBool>(reset_func)(thread, false);
            } else {
                reinterpret_cast<CallVoid>(reset_func)(thread);
            }
        }
        
        Increment();
    }
    
    void SetTarget(size_t target) {
        std::lock_guard<std::mutex> lock(mutex_);
        target_ = target;
    }
    
private:
    CheckpointClosure() = default;
    
    void Increment() {
        bool finished;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            count_++;
            ALOGD("Checkpoint thread %d, count=%zu", gettid(), count_);
            finished = (count_ >= target_) && (target_ > 0);
        }
        
        if (finished) {
            delete this;
        }
    }
    
    std::mutex mutex_;
    size_t count_ = 0;
    size_t target_ = 0;
};

// ===== SetEntrypointsInstrumented Hook =====

/**
 * Instrumentation::SetEntrypointsInstrumented 代理
 * 
 * 使用 checkpoint 机制在所有线程上重置分配入口点
 */
static bool Proxy_SetEntrypointsInstrumented(void* thiz, bool enable) {
    SHADOWHOOK_STACK_SCOPE();
    
    if (!g_in_self_set) {
        return SHADOWHOOK_CALL_PREV(Proxy_SetEntrypointsInstrumented, thiz, enable);
    }
    
    if (SetQuickAllocEntryPointsInstrumented(enable)) {
        // Android 8-11: 手动通过 Checkpoint 将 entry points 更新广播到所有线程
        CheckpointClosure* closure = CheckpointClosure::Create();
        size_t target = RunCheckpoint(closure);
        if (target > 0) {
            closure->SetTarget(target);
            ALOGD("Checkpoint started, target=%zu", target);
            return true;
        } else {
            ALOGD("Checkpoint failed");
            delete closure;
        }
    } else {
        // Android 12+: SetQuickAllocEntryPointsInstrumented 不存在，
        // 回调 ART 原始实现，由 ART 内部自行完成 entry points 更新
        ALOGD("SetQuickAllocEntryPointsInstrumented unavailable, calling ART original");
        return SHADOWHOOK_CALL_PREV(Proxy_SetEntrypointsInstrumented, thiz, enable);
    }
    
    return false;
}

// ===== 注册 Allocation Listener =====

static void RegisterAllocationListener() {
    auto& ctx = GetAllocContext();
    
    if (!ctx.heap) {
        ALOGE("Heap not available");
        return;
    }
    
    if (!g_set_allocation_listener) {
        ALOGE("SetAllocationListener not available");
        return;
    }
    
    // 创建 Listener
    if (!g_listener) {
        if (g_sdk_version >= __ANDROID_API_R__) {
            g_listener = new MyAllocationListener30();
        } else {
            g_listener = new MyAllocationListener26();
        }
    }
    
    // 注册 Listener
    g_in_self_set = true;
    g_set_allocation_listener(ctx.heap, g_listener);
    g_in_self_set = false;
    
    ALOGI("AllocationListener registered");
}

// ===== 公开接口实现 =====

bool InitAllocHook(int sdk_version) {
    g_sdk_version = sdk_version;

    return false;
    if (sdk_version < __ANDROID_API_O__) {
        ALOGE("Alloc hook requires Android 8.0+");
        return false;
    }
    
    // 打开 libart.so
    void* libart = dl_open("libart.so");
    if (!libart) {
        ALOGE("Cannot open libart.so");
        return false;
    }
    
    // 初始化 Checkpoint
    if (!InitCheckpoint(libart)) {
        ALOGE("Failed to init checkpoint");
        dl_close(libart);
        return false;
    }
    
    // 获取 SetAllocationListener
    g_set_allocation_listener = reinterpret_cast<SetPtr>(
        dl_sym(libart, HEAP_SET_ALLOC_LISTENER));
    
    if (!g_set_allocation_listener) {
        ALOGE("Cannot find SetAllocationListener");
        dl_close(libart);
        return false;
    }
    
    // 获取 RemoveAllocationListener
    g_remove_allocation_listener = reinterpret_cast<CallVoid>(
        dl_sym(libart, HEAP_REMOVE_ALLOC_LISTENER));
    
    // Hook SetEntrypointsInstrumented（Android 12+ 可能符号名变化或不存在，降级 warning）
    g_set_entrypoints_stub = shadowhook_hook_sym_name(
        "libart.so",
        INSTRUMENTATION_SET_ENTRYPOINTS_INSTRUMENTED,
        reinterpret_cast<void*>(Proxy_SetEntrypointsInstrumented),
        nullptr);
    
    if (!g_set_entrypoints_stub) {
        // Android 12+: ART 内部 SetAllocationListener 已自行管理 entry points，
        // 此 hook 非必须，降级为 warning 继续初始化（alloc count 统计仍可用）
        ALOGW("Failed to hook SetEntrypointsInstrumented (Android 12+?), "
              "allocation tracking may have reduced accuracy");
    }
    
    // 初始化 ThreadList Hook
    if (!InitThreadListHook()) {
        ALOGE("Failed to init ThreadList hook");
        dl_close(libart);
        return false;
    }
    
    // 设置回调，当 ThreadList 就绪时注册 Listener
    SetThreadListReadyCallback([](void* /* thread_list */) {
        RegisterAllocationListener();
    });
    
    dl_close(libart);
    
    auto& ctx = GetAllocContext();
    ctx.initialized = true;
    
    ALOGI("AllocHook initialized (SDK %d)", sdk_version);
    return true;
}

void SetAllocHookEnabled(bool enabled) {
    g_enabled.store(enabled, std::memory_order_release);
}

bool IsAllocHookEnabled() {
    return g_enabled.load(std::memory_order_acquire);
}

AllocStats& GetAllocStats() {
    return g_stats;
}

ThreadAllocStats& GetThreadAllocStats() {
    return g_thread_stats;
}

void DestroyAllocHook() {
    g_enabled.store(false);
    
    // 移除 Listener
    auto& ctx = GetAllocContext();
    if (ctx.heap && g_remove_allocation_listener) {
        g_remove_allocation_listener(ctx.heap);
    }
    
    // 卸载 Hook
    if (g_set_entrypoints_stub) {
        shadowhook_unhook(g_set_entrypoints_stub);
        g_set_entrypoints_stub = nullptr;
    }
    
    DestroyThreadListHook();
    
    // 释放 Listener
    if (g_listener) {
        if (g_sdk_version >= __ANDROID_API_R__) {
            delete static_cast<MyAllocationListener30*>(g_listener);
        } else {
            delete static_cast<MyAllocationListener26*>(g_listener);
        }
        g_listener = nullptr;
    }
    
    ctx.initialized = false;
    ALOGI("AllocHook destroyed");
}

} // namespace alloc
} // namespace atrace

