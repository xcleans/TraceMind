/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Plugin JNI 桥接层
 *
 * 所有 Hook 实现已拆分到独立文件，本文件仅负责:
 * 1. nativeInstallHooks: 批量安装 Hook (单次 JNI 调用)
 * 2. nativeEnable: 各 Plugin 的启用/禁用控制
 * 3. Alloc 统计查询
 */
#include <jni.h>

#include "hook/BinderHook.h"
#include "hook/GCHook.h"
#include "hook/LockHook.h"
#include "hook/JNICallHook.h"
#include "hook/LoadLibHook.h"
#include "hook/IOHook.h"
#include "hook/MsgQueueHook.h"
#include "hook/alloc/AllocHookPlugin.h"
#include "core/TraceEngine.h"
#include "include/atrace.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "PluginJNI"
#include "utils/atrace_log.h"

using namespace atrace;

static constexpr jlong FLAG_BINDER   = 1L << 0;
static constexpr jlong FLAG_GC       = 1L << 1;
static constexpr jlong FLAG_LOCK     = 1L << 2;
static constexpr jlong FLAG_JNI_CALL = 1L << 3;
static constexpr jlong FLAG_LOADLIB  = 1L << 4;
static constexpr jlong FLAG_ALLOC    = 1L << 5;
static constexpr jlong FLAG_MSGQUEUE = 1L << 6;
static constexpr jlong FLAG_IO       = 1L << 7;

static void install_and_log(HookPlugin& plugin, JNIEnv* env) {
    if (!plugin.Init(env)) {
        ALOGE("Hook init failed: %s", plugin.GetId());
    }
}

extern "C" {

JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeInstallHooks(
        JNIEnv* env, jobject, jlong, jlong flags,
        jint sdkVersion, jboolean enableWakeup, jobject mainThread) {

    auto now = CurrentBootTimeNanos();
    ALOGI("Installing hooks: flags=0x%llx, sdk=%d, wakeup=%d",
          static_cast<unsigned long long>(flags), sdkVersion, enableWakeup);

    if (flags & FLAG_BINDER)   install_and_log(BinderHook::Instance(), env);
    if (flags & FLAG_GC)       install_and_log(GCHook::Instance(), env);

    if (flags & FLAG_LOCK) {
        auto& lock = LockHook::Instance();
        lock.SetWakeupEnabled(enableWakeup);
        if (mainThread) lock.SetMainThread(env, mainThread);
        install_and_log(lock, env);
    }

    if (flags & FLAG_JNI_CALL) {
        auto& jni = JNICallHook::Instance();
        jni.SetSdkVersion(sdkVersion);
        install_and_log(jni, env);
    }

    if (flags & FLAG_LOADLIB)  install_and_log(LoadLibHook::Instance(), env);

    if (flags & FLAG_ALLOC) {
        auto& alloc = AllocHookPlugin::Instance();
        alloc.SetSdkVersion(sdkVersion);
        install_and_log(alloc, env);
    }

    if (flags & FLAG_MSGQUEUE) install_and_log(MsgQueueHook::Instance(), env);
    if (flags & FLAG_IO)       install_and_log(IOHook::Instance(), env);

    auto elapsed = (CurrentBootTimeNanos() - now) / 1000000;
    ALOGI("All hooks installed in %llums", static_cast<unsigned long long>(elapsed));
}

// ===== Plugin nativeEnable JNI =====

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_BinderPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = BinderHook::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_GCPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = GCHook::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_LockPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = LockHook::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_JNIPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = JNICallHook::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_LoadLibraryPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = LoadLibHook::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_IOPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = IOHook::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_AllocPlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = AllocHookPlugin::Instance();
    enable ? h.Enable() : h.Disable();
}

JNIEXPORT jlongArray JNICALL
Java_com_aspect_atrace_plugins_AllocPlugin_nativeGetStats(JNIEnv* env, jobject) {
    auto& stats = AllocHookPlugin::Instance().GetStats();
    jlongArray result = env->NewLongArray(2);
    jlong data[2] = {
        static_cast<jlong>(stats.total_bytes.load(std::memory_order_relaxed)),
        static_cast<jlong>(stats.total_objects.load(std::memory_order_relaxed))
    };
    env->SetLongArrayRegion(result, 0, 2, data);
    return result;
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_AllocPlugin_nativeResetStats(JNIEnv*, jobject) {
    AllocHookPlugin::Instance().ResetStats();
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_MessageQueuePlugin_nativeEnable(JNIEnv*, jobject, jboolean enable) {
    auto& h = MsgQueueHook::Instance();
    enable ? h.Enable() : h.Disable();
}

/**
 * 在 Handler.dispatchMessage 入口处采一次样（由 Looper setMessageLogging 回调触发）
 * 采到的堆栈为「即将执行当前 Message/Handler」时的调用栈
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_MessageQueuePlugin_nativeSampleAtDispatchMessage(JNIEnv*, jobject) {
    auto* engine = GetEngine();
    if (!engine || !engine->IsTracing()) return;
    engine->RequestSample(SampleType::kMessageBegin, nullptr, true, false, 0, 0);
}

/**
 * 在 Handler.dispatchMessage 返回后采一次样（"<<<<< Finished to" 时触发）
 * 采到的堆栈为「刚执行完当前 Message/Handler」时的调用栈
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_plugins_MessageQueuePlugin_nativeSampleAtMessageEnd(JNIEnv*, jobject) {
    auto* engine = GetEngine();
    if (!engine || !engine->IsTracing()) return;
    engine->RequestSample(SampleType::kMessageEnd, nullptr, true, false, 0, 0);
}

} // extern "C"
