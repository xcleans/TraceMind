/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * TraceEngineCore JNI 实现
 */
#include <jni.h>
#include <shadowhook.h>

#include "core/TraceEngine.h"
#include "core/SymbolResolver.h"
#include "core/StackSampler.h"
#include "hook/ArtMethodInstrumentation.h"
#include "utils/thread_utils.h"
#include "include/atrace.h"
#define ATRACE_LOG_TAG "EngineJNI"
#include "utils/atrace_log.h"

using namespace atrace;

// 存储主线程引用
static jobject g_main_thread = nullptr;

extern "C" {

/**
 * 创建 TraceEngine
 */
JNIEXPORT jlong JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeCreate(
        JNIEnv *env,
        jobject /* thiz */,
        jobject mainThread,
        jint bufferCapacity,
        jlong mainThreadInterval,
        jlong otherThreadInterval,
        jint maxStackDepth,
        jint clockType,
        jboolean enableThreadNames,
        jboolean enableWakeup,
        jboolean enableAlloc,
        jboolean enableRusage,
        jboolean debugMode,
        jboolean shadowPause) {

    ALOGI("TraceEngineCore_nativeCreate");
    int shadow_result = shadowhook_init(SHADOWHOOK_MODE_SHARED, false);
    // 保存主线程引用
    g_main_thread = env->NewGlobalRef(mainThread);

    // 构建配置
    Config config;
    config.buffer_capacity = static_cast<uint32_t>(bufferCapacity);
    config.main_thread_interval_ns = static_cast<uint64_t>(mainThreadInterval);
    config.other_thread_interval_ns = static_cast<uint64_t>(otherThreadInterval);
    config.max_stack_depth = static_cast<uint16_t>(maxStackDepth);
    config.clock_type = static_cast<ClockType>(clockType);
    config.enable_thread_names = enableThreadNames;
    config.enable_wakeup = enableWakeup;
    config.enable_alloc = enableAlloc;
    config.enable_rusage = enableRusage;
    config.debug_mode = debugMode;
    config.shadow_pause = shadowPause;

    // 创建引擎
    auto engine = TraceEngine::Create(env, config);
    if (!engine) {
        ALOGE("Failed to create TraceEngine");
        return 0;
    }
    ALOGI("TraceEngineCore_nativeCreate SUCC");

    // 返回指针 (所有权转移给调用者)
    return reinterpret_cast<jlong>(engine.release());
}

/**
 * 开始追踪
 */
JNIEXPORT jlong JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeStart(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        return -1;
    }

    return engine->Start();
}

/**
 * 停止追踪
 */
JNIEXPORT jlong JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeStop(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        return -1;
    }

    return engine->Stop();
}

/**
 * 手动采样
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeCapture(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr,
        jboolean force) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (engine) {
        engine->Capture(force);
    }
}

/**
 * 记录标记
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeMark(
        JNIEnv *env,
        jobject /* thiz */,
        jlong ptr,
        jstring name,
        jstring args) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        return;
    }

    const char *name_str = env->GetStringUTFChars(name, nullptr);
    engine->Mark(name_str);
    env->ReleaseStringUTFChars(name, name_str);
}

/**
 * 开始自定义区间
 */
JNIEXPORT jlong JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeBeginSection(
        JNIEnv *env,
        jobject /* thiz */,
        jlong ptr,
        jstring name) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        return -1;
    }

    const char *name_str = env->GetStringUTFChars(name, nullptr);
    jlong token = engine->BeginSection(name_str);
    env->ReleaseStringUTFChars(name, name_str);

    return token;
}

/**
 * 结束自定义区间
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeEndSection(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr,
        jlong token) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (engine) {
        engine->EndSection(token);
    }
}

/**
 * 请求采样 (插件调用)
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeRequestSample(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr,
        jint type,
        jboolean force,
        jboolean captureAtEnd,
        jlong beginNano) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        return;
    }

    SampleType sample_type = static_cast<SampleType>(type);

    if (captureAtEnd && beginNano > 0) {
        engine->RequestSample(sample_type, nullptr, force, true,
                static_cast<uint64_t>(beginNano), 0);
    } else {
        engine->RequestSample(sample_type, nullptr, force);
    }
}

/**
 * 导出追踪数据
 */
JNIEXPORT jint JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeExport(
        JNIEnv *env,
        jobject /* thiz */,
        jlong ptr,
        jlong startToken,
        jlong endToken,
        jstring tracePath,
        jstring mappingPath,
        jstring extra) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        return -1;
    }

    const char *trace_path = env->GetStringUTFChars(tracePath, nullptr);
    const char *extra_str = env->GetStringUTFChars(extra, nullptr);

    int result = engine->Export(trace_path, startToken, endToken, extra_str);

    env->ReleaseStringUTFChars(tracePath, trace_path);
    env->ReleaseStringUTFChars(extra, extra_str);

    return result;
}

/**
 * 获取缓冲区信息: [currentTicket, capacity]
 */
JNIEXPORT jlongArray JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeGetBufferInfo(
        JNIEnv *env,
        jobject /* thiz */,
        jlong ptr) {

    jlongArray result = env->NewLongArray(2);
    if (!result) return nullptr;

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (!engine) {
        jlong zeros[2] = {0, 0};
        env->SetLongArrayRegion(result, 0, 2, zeros);
        return result;
    }

    jlong info[2] = {
        engine->GetCurrentTicket(),
        static_cast<jlong>(engine->GetBufferCapacity())
    };
    env->SetLongArrayRegion(result, 0, 2, info);
    return result;
}

/**
 * 暂停采样
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativePause(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr) {
    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (engine) {
        engine->Pause();
    }
}

/**
 * 恢复采样
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeResume(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr) {
    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (engine) {
        engine->Resume();
    }
}

/**
 * 查询暂停状态
 */
JNIEXPORT jboolean JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeIsPaused(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr) {
    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    return engine ? engine->IsPaused() : JNI_FALSE;
}

/**
 * 动态更新采样间隔
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeSetSamplingInterval(
        JNIEnv * /* env */,
        jobject /* thiz */,
        jlong ptr,
        jlong mainIntervalNs,
        jlong otherIntervalNs) {
    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    if (engine) {
        engine->SetSamplingInterval(
            static_cast<uint64_t>(mainIntervalNs),
            static_cast<uint64_t>(otherIntervalNs));
    }
}

/**
 * 安装 ArtMethod instrumentation（探测布局、准备 per-method hook）。
 * WatchList（AddWatchedRule）仅写入模式列表，**不会**自动 hook；
 * 实际拦截需调用 nativeHookMethod 或后续实现类加载自动匹配（见 ArtMethodInstrumentation.h）。
 */
JNIEXPORT jboolean JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeInstallArtMethodInstrumentation(
        JNIEnv *env,
        jobject /* thiz */) {
    return atrace::ArtMethodInstrumentation::Install(env) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeAddWatchedRule(
        JNIEnv *env,
        jobject /* thiz */,
        jstring scope,
        jstring value) {
    const char *s = env->GetStringUTFChars(scope, nullptr);
    const char *v = env->GetStringUTFChars(value, nullptr);
    if (s && v) {
        atrace::ArtMethodInstrumentation::AddWatchedRule(s, v);
    }
    if (s) env->ReleaseStringUTFChars(scope, s);
    if (v) env->ReleaseStringUTFChars(value, v);
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeRemoveWatchedRule(
        JNIEnv *env,
        jobject /* thiz */,
        jstring entry) {
    const char *p = env->GetStringUTFChars(entry, nullptr);
    if (p) {
        atrace::ArtMethodInstrumentation::RemoveWatchedRule(p);
        env->ReleaseStringUTFChars(entry, p);
    }
}

JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeClearWatchedRules(
        JNIEnv * /* env */,
        jobject /* thiz */) {
    atrace::ArtMethodInstrumentation::ClearWatchedRules();
}

JNIEXPORT jint JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeWatchedRuleCount(
        JNIEnv * /* env */,
        jobject /* thiz */) {
    return static_cast<jint>(atrace::ArtMethodInstrumentation::WatchedRuleCount());
}

/**
 * 精确 Hook 指定方法（替换 entry_point_from_quick_compiled_code_）
 */
JNIEXPORT jboolean JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeHookMethod(
        JNIEnv *env,
        jobject /* thiz */,
        jstring className,
        jstring methodName,
        jstring signature,
        jboolean isStatic) {
    const char *cls = env->GetStringUTFChars(className, nullptr);
    const char *mth = env->GetStringUTFChars(methodName, nullptr);
    const char *sig = env->GetStringUTFChars(signature, nullptr);
    jboolean ok = JNI_FALSE;
    if (cls && mth && sig) {
        ok = atrace::ArtMethodInstrumentation::HookMethod(env, cls, mth, sig, isStatic)
                ? JNI_TRUE : JNI_FALSE;
    }
    if (cls) env->ReleaseStringUTFChars(className, cls);
    if (mth) env->ReleaseStringUTFChars(methodName, mth);
    if (sig) env->ReleaseStringUTFChars(signature, sig);
    return ok;
}

/**
 * 恢复指定方法的原始 entry_point
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeUnhookMethod(
        JNIEnv *env,
        jobject /* thiz */,
        jstring className,
        jstring methodName,
        jstring signature,
        jboolean isStatic) {
    const char *cls = env->GetStringUTFChars(className, nullptr);
    const char *mth = env->GetStringUTFChars(methodName, nullptr);
    const char *sig = env->GetStringUTFChars(signature, nullptr);
    if (cls && mth && sig) {
        atrace::ArtMethodInstrumentation::UnhookMethod(env, cls, mth, sig, isStatic);
    }
    if (cls) env->ReleaseStringUTFChars(className, cls);
    if (mth) env->ReleaseStringUTFChars(methodName, mth);
    if (sig) env->ReleaseStringUTFChars(signature, sig);
}

/**
 * 扫描指定 class 的全部 declared methods，匹配 WatchList 规则并自动 hook。
 * @return 本次新增 hook 数量
 */
JNIEXPORT jint JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeScanClassAndHook(
        JNIEnv *env,
        jobject /* thiz */,
        jclass cls) {
    return static_cast<jint>(
            atrace::ArtMethodInstrumentation::ScanClassAndHook(env, cls));
}

JNIEXPORT jobjectArray JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeGetWatchedRules(
        JNIEnv *env,
        jobject /* thiz */) {
    const auto patterns = atrace::ArtMethodInstrumentation::GetWatchedRules();
    jclass string_class = env->FindClass("java/lang/String");
    if (!string_class) {
        return nullptr;
    }
    jobjectArray result = env->NewObjectArray(
            static_cast<jsize>(patterns.size()), string_class, nullptr);
    if (!result) {
        return nullptr;
    }
    for (size_t i = 0; i < patterns.size(); ++i) {
        jstring s = env->NewStringUTF(patterns[i].c_str());
        if (!s) {
            return nullptr;
        }
        env->SetObjectArrayElement(result, static_cast<jsize>(i), s);
        env->DeleteLocalRef(s);
    }
    return result;
}

/**
 * 释放引擎
 */
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_TraceEngineCore_nativeRelease(
        JNIEnv *env,
        jobject /* thiz */,
        jlong ptr) {

    auto *engine = reinterpret_cast<TraceEngine *>(ptr);
    delete engine;

    // 释放主线程引用
    if (g_main_thread) {
        env->DeleteGlobalRef(g_main_thread);
        g_main_thread = nullptr;
    }
}

} // extern "C"

