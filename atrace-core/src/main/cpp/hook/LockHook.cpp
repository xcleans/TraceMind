#include "LockHook.h"
#include <shadowhook.h>
#include <unistd.h>
#include "include/atrace.h"
#include "hook/JNIMethodHook.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "LockHook"
#include "utils/atrace_log.h"

namespace atrace {

static std::atomic<bool> g_enabled{false};
static std::atomic<bool> g_wakeup_enabled{false};
static void* g_monitor_enter_stub = nullptr;
static void* g_monitor_exit_stub = nullptr;
static jobject g_main_thread = nullptr;
static pid_t g_main_tid = 0;

static void (*g_origin_wait)(JNIEnv*, jobject, jlong, jint) = nullptr;
static void (*g_origin_notify)(JNIEnv*, jobject) = nullptr;
static void (*g_origin_notify_all)(JNIEnv*, jobject) = nullptr;
static void (*g_origin_park)(JNIEnv*, jobject, jboolean, jlong) = nullptr;
static void (*g_origin_unpark)(JNIEnv*, jobject, jobject) = nullptr;

static jint (*g_identity_hash_code)(JNIEnv*, jclass, jobject) = nullptr;
static jint fallback_identity_hash_code(JNIEnv*, jclass, jobject) {
    return 0;
}

static std::atomic<jint> g_current_wait_hash{0};
static std::atomic<uint64_t> g_current_wait_nano{0};
static std::atomic<bool> g_current_park{false};
static std::atomic<uint64_t> g_current_park_nano{0};
static std::atomic<void*> g_current_monitor{nullptr};
static std::atomic<uint64_t> g_current_monitor_nano{0};

// ===== Monitor Proxies =====

static void* proxy_MonitorEnter(void* thread_self, void* obj, bool trylock) {
    SHADOWHOOK_STACK_SCOPE();

    if (!g_enabled.load(std::memory_order_relaxed)) {
        return SHADOWHOOK_CALL_PREV(proxy_MonitorEnter, thread_self, obj, trylock);
    }

    bool is_main = IsMainThread();
    uint64_t begin_nano = CurrentBootTimeNanos();
    uint64_t begin_cpu_nano = CurrentCpuTimeNanos();

    if (g_wakeup_enabled.load(std::memory_order_relaxed) && is_main) {
        g_current_monitor.store(obj, std::memory_order_relaxed);
        g_current_monitor_nano.store(begin_nano, std::memory_order_relaxed);
    }

    void* result = SHADOWHOOK_CALL_PREV(proxy_MonitorEnter, thread_self, obj, trylock);

    if (is_main) {
        g_current_monitor.store(nullptr, std::memory_order_relaxed);
    }

//    RequestSampleWithDuration(SampleType::kMonitorEnter, thread_self, begin_nano, begin_cpu_nano);
    return result;
}

static bool proxy_MonitorExit(void* thread_self, void* obj) {
    SHADOWHOOK_STACK_SCOPE();

    if (g_wakeup_enabled.load(std::memory_order_relaxed) && !IsMainThread()) {
        void* current_monitor = g_current_monitor.load(std::memory_order_relaxed);
        if (current_monitor != nullptr && current_monitor == obj) {
            uint64_t monitor_nano = g_current_monitor_nano.load(std::memory_order_relaxed);
//            RequestSampleWithDuration(SampleType::kWakeup, thread_self, monitor_nano, 0);
            ALOGD("Monitor unlock wakeup main thread");
        }
    }

    return SHADOWHOOK_CALL_PREV(proxy_MonitorExit, thread_self, obj);
}

// ===== Object.wait/notify Proxies =====
//
// 这些代理通过 RegisterNatives 注入（HookJavaMethodViaRegisterNatives），
// 签名必须与标准 JNI 函数一致：第一个参数是 JNIEnv*，第二个是 jobject（接收者）。
// g_origin_* 保存的是 RegisterNatives 前的旧 JNI 函数指针，调用时直接传 (env, this)。

static void proxy_Object_wait(JNIEnv* env, jobject java_this, jlong ms, jint ns) {
    if (!g_enabled.load(std::memory_order_relaxed) || !g_origin_wait) {
        if (g_origin_wait) g_origin_wait(env, java_this, ms, ns);
        return;
    }

    bool is_main = IsMainThread();
    uint64_t begin_nano = CurrentBootTimeNanos();

    if (g_wakeup_enabled.load(std::memory_order_relaxed) && is_main && g_identity_hash_code) {
        g_current_wait_hash.store(g_identity_hash_code(env, nullptr, java_this), std::memory_order_relaxed);
        g_current_wait_nano.store(begin_nano, std::memory_order_relaxed);
    }

    g_origin_wait(env, java_this, ms, ns);

    if (is_main) {
        g_current_wait_hash.store(0, std::memory_order_relaxed);
    }
}

static void proxy_Object_notify(JNIEnv* env, jobject java_this) {
    if (g_wakeup_enabled.load(std::memory_order_relaxed) && g_identity_hash_code) {
        jint wait_hash = g_current_wait_hash.load(std::memory_order_relaxed);
        if (wait_hash != 0) {
            jint hash = g_identity_hash_code(env, nullptr, java_this);
            if (hash == wait_hash) {
                // wakeup 追踪点（预留）
                ALOGD("notify wakes main wait: hash=%d", hash);
            }
        }
    }
    if (g_origin_notify) g_origin_notify(env, java_this);
}

static void proxy_Object_notifyAll(JNIEnv* env, jobject java_this) {
    if (g_wakeup_enabled.load(std::memory_order_relaxed) && g_identity_hash_code) {
        jint wait_hash = g_current_wait_hash.load(std::memory_order_relaxed);
        if (wait_hash != 0) {
            jint hash = g_identity_hash_code(env, nullptr, java_this);
            if (hash == wait_hash) {
                // wakeup 追踪点（预留）
                ALOGD("notifyAll wakes main wait: hash=%d", hash);
            }
        }
    }
    if (g_origin_notify_all) g_origin_notify_all(env, java_this);
}

// ===== Unsafe.park/unpark Proxies =====

static void proxy_Unsafe_park(JNIEnv* env, jobject java_this, jboolean is_absolute, jlong time) {
    if (!g_enabled.load(std::memory_order_relaxed) || !g_origin_park) {
        if (g_origin_park) g_origin_park(env, java_this, is_absolute, time);
        return;
    }

    bool is_main = IsMainThread();
    uint64_t begin_nano = CurrentBootTimeNanos();

    if (g_wakeup_enabled.load(std::memory_order_relaxed) && is_main) {
        g_current_park.store(true, std::memory_order_relaxed);
        g_current_park_nano.store(begin_nano, std::memory_order_relaxed);
    }

    g_origin_park(env, java_this, is_absolute, time);

    if (is_main) {
        g_current_park.store(false, std::memory_order_relaxed);
    }
}

static void proxy_Unsafe_unpark(JNIEnv* env, jobject java_this, jobject target) {
    if (g_wakeup_enabled.load(std::memory_order_relaxed) &&
        g_current_park.load(std::memory_order_relaxed) &&
        g_main_thread && target) {
        if (env->IsSameObject(target, g_main_thread)) {
            // wakeup 追踪点（预留）
            ALOGD("unpark wakes main park: ts=%llu",
                  static_cast<unsigned long long>(
                      g_current_park_nano.load(std::memory_order_relaxed)));
        }
    }
    if (g_origin_unpark) g_origin_unpark(env, java_this, target);
}

// ===== LockHook Implementation =====

LockHook& LockHook::Instance() {
    static LockHook instance;
    return instance;
}

bool LockHook::Init(JNIEnv* env) {
    bool enableWakeup = g_wakeup_enabled.load(std::memory_order_relaxed);
    ALOGI("Init begin: wakeup=%d, enabled=%d", enableWakeup ? 1 : 0,
          g_enabled.load(std::memory_order_relaxed) ? 1 : 0);

    if (!g_monitor_enter_stub) {
        static const char* monitor_symbols[] = {
            "_ZN3art7Monitor12MonitorEnterEPNS_6ThreadENS_6ObjPtrINS_6mirror6ObjectEEEb",
            "_ZN3art7Monitor12MonitorEnterEPNS_6ThreadEPNS_6mirror6ObjectEb",
            nullptr
        };
        for (int i = 0; monitor_symbols[i]; ++i) {
            g_monitor_enter_stub = shadowhook_hook_sym_name(
                "libart.so", monitor_symbols[i],
                reinterpret_cast<void*>(proxy_MonitorEnter), nullptr);
            if (g_monitor_enter_stub) {
                ALOGI("MonitorEnter hook: %p (symbol[%d])", g_monitor_enter_stub, i);
                break;
            }
        }
        if (!g_monitor_enter_stub) {
            ALOGW("MonitorEnter hook failed: symbol not found in libart.so");
        }
    }

    if (enableWakeup && !g_monitor_exit_stub) {
        static const char* exit_symbols[] = {
            "_ZN3art7Monitor11MonitorExitEPNS_6ThreadENS_6ObjPtrINS_6mirror6ObjectEEE",
            "_ZN3art7Monitor11MonitorExitEPNS_6ThreadEPNS_6mirror6ObjectE",
            nullptr
        };
        for (int i = 0; exit_symbols[i]; ++i) {
            g_monitor_exit_stub = shadowhook_hook_sym_name(
                "libart.so", exit_symbols[i],
                reinterpret_cast<void*>(proxy_MonitorExit), nullptr);
            if (g_monitor_exit_stub) {
                ALOGI("MonitorExit hook: %p (symbol[%d])", g_monitor_exit_stub, i);
                break;
            }
        }
        if (!g_monitor_exit_stub) {
            ALOGW("MonitorExit hook failed: symbol not found in libart.so");
        }
    }

    if (!jni_hook::IsInitialized()) {
        ALOGE("JNI Hook not initialized, skipping wait/park hooks");
        return true;
    }

    // Object.wait / notify / notifyAll / Unsafe.park / unpark 都是纯 Java 方法（或已有
    // native 实现的方法），必须通过 RegisterNatives 注入，不能直接替换 jni_entrance 字段。
    // 直接替换 jni_entrance 会保存 DEX 字节码地址作为 orig，回调时执行不可执行内存 →
    // SIGSEGV SEGV_ACCERR（fault addr 在 core-oj.jar 地址空间，如 0x77bcb16a04）。

    if (!g_origin_wait) {
        jni_hook::HookJavaMethodViaRegisterNatives(
            env, "java/lang/Object", "wait", "(JI)V",
            reinterpret_cast<void*>(proxy_Object_wait),
            reinterpret_cast<void**>(&g_origin_wait));
        if (g_origin_wait) ALOGI("Hooked Object.wait via RegisterNatives");
        else ALOGW("Hook Object.wait failed");
    }

    if (enableWakeup) {
        if (!g_origin_notify) {
            jni_hook::HookJavaMethodViaRegisterNatives(
                env, "java/lang/Object", "notify", "()V",
                reinterpret_cast<void*>(proxy_Object_notify),
                reinterpret_cast<void**>(&g_origin_notify));
            if (g_origin_notify) ALOGI("Hooked Object.notify via RegisterNatives");
            else ALOGW("Hook Object.notify failed");
        }
        if (!g_origin_notify_all) {
            jni_hook::HookJavaMethodViaRegisterNatives(
                env, "java/lang/Object", "notifyAll", "()V",
                reinterpret_cast<void*>(proxy_Object_notifyAll),
                reinterpret_cast<void**>(&g_origin_notify_all));
            if (g_origin_notify_all) ALOGI("Hooked Object.notifyAll via RegisterNatives");
            else ALOGW("Hook Object.notifyAll failed");
        }
    }

    if (!g_origin_park) {
        jni_hook::HookJavaMethodViaRegisterNatives(
            env, "sun/misc/Unsafe", "park", "(ZJ)V",
            reinterpret_cast<void*>(proxy_Unsafe_park),
            reinterpret_cast<void**>(&g_origin_park));
    }
    if (!g_origin_park) {
        // Android 9+ 迁移到 jdk.internal.misc.Unsafe
        jni_hook::HookJavaMethodViaRegisterNatives(
            env, "jdk/internal/misc/Unsafe", "park", "(ZJ)V",
            reinterpret_cast<void*>(proxy_Unsafe_park),
            reinterpret_cast<void**>(&g_origin_park));
    }
    if (g_origin_park) ALOGI("Hooked Unsafe.park via RegisterNatives");
    else ALOGW("Hook Unsafe.park failed for both sun/misc and jdk/internal/misc");

    if (enableWakeup) {
        if (!g_origin_unpark) {
            jni_hook::HookJavaMethodViaRegisterNatives(
                env, "sun/misc/Unsafe", "unpark", "(Ljava/lang/Object;)V",
                reinterpret_cast<void*>(proxy_Unsafe_unpark),
                reinterpret_cast<void**>(&g_origin_unpark));
        }
        if (!g_origin_unpark) {
            jni_hook::HookJavaMethodViaRegisterNatives(
                env, "jdk/internal/misc/Unsafe", "unpark", "(Ljava/lang/Object;)V",
                reinterpret_cast<void*>(proxy_Unsafe_unpark),
                reinterpret_cast<void**>(&g_origin_unpark));
        }
        if (g_origin_unpark) ALOGI("Hooked Unsafe.unpark via RegisterNatives");
        else ALOGW("Hook Unsafe.unpark failed for both sun/misc and jdk/internal/misc");
    }

    if (enableWakeup && !g_identity_hash_code) {
        // Align with rhea behavior: prefer native Object.identityHashCodeNative,
        // then fallback to System.identityHashCode native entrance if available.
        g_identity_hash_code = reinterpret_cast<jint(*)(JNIEnv*, jclass, jobject)>(
            jni_hook::GetStaticMethodEntrance(
                env, "java/lang/Object", "identityHashCodeNative", "(Ljava/lang/Object;)I"));
        if (!g_identity_hash_code) {
            g_identity_hash_code = reinterpret_cast<jint(*)(JNIEnv*, jclass, jobject)>(
                jni_hook::GetStaticMethodEntrance(
                    env, "java/lang/System", "identityHashCode", "(Ljava/lang/Object;)I"));
        }
        if (!g_identity_hash_code) {
            ALOGW("identityHashCode native entrance not found, wakeup correlation disabled");
            g_identity_hash_code = fallback_identity_hash_code;
        }
        ALOGI("identityHashCode entrance=%p", reinterpret_cast<void*>(g_identity_hash_code));
    }

    ALOGI("Init done: monitor_enter=%p monitor_exit=%p wait=%p notify=%p notifyAll=%p park=%p unpark=%p",
          g_monitor_enter_stub, g_monitor_exit_stub,
          reinterpret_cast<void*>(g_origin_wait),
          reinterpret_cast<void*>(g_origin_notify),
          reinterpret_cast<void*>(g_origin_notify_all),
          reinterpret_cast<void*>(g_origin_park),
          reinterpret_cast<void*>(g_origin_unpark));
    return true;
}

void LockHook::SetMainThread(JNIEnv* env, jobject mainThread) {
    if (mainThread && !g_main_thread) {
        g_main_thread = env->NewGlobalRef(mainThread);
        g_main_tid = getpid();
        ALOGI("Main thread set: tid=%d", g_main_tid);
    }
}

void LockHook::SetWakeupEnabled(bool enabled) {
    g_wakeup_enabled.store(enabled, std::memory_order_relaxed);
    ALOGI("SetWakeupEnabled: %d", enabled ? 1 : 0);
}

void LockHook::Enable() {
    g_enabled.store(true, std::memory_order_relaxed);
    ALOGI("Enable");
}

void LockHook::Disable() {
    g_enabled.store(false, std::memory_order_relaxed);
    ALOGI("Disable");
}

void LockHook::Destroy() {
    ALOGI("Destroy begin");
    g_enabled.store(false, std::memory_order_relaxed);
    g_wakeup_enabled.store(false, std::memory_order_relaxed);

    if (g_monitor_enter_stub) {
        shadowhook_unhook(g_monitor_enter_stub);
        g_monitor_enter_stub = nullptr;
    }
    if (g_monitor_exit_stub) {
        shadowhook_unhook(g_monitor_exit_stub);
        g_monitor_exit_stub = nullptr;
    }

    g_origin_wait = nullptr;
    g_origin_notify = nullptr;
    g_origin_notify_all = nullptr;
    g_origin_park = nullptr;
    g_origin_unpark = nullptr;
    g_identity_hash_code = nullptr;
    g_main_thread = nullptr;
    g_main_tid = 0;

    g_current_wait_hash.store(0, std::memory_order_relaxed);
    g_current_wait_nano.store(0, std::memory_order_relaxed);
    g_current_park.store(false, std::memory_order_relaxed);
    g_current_park_nano.store(0, std::memory_order_relaxed);
    g_current_monitor.store(nullptr, std::memory_order_relaxed);
    g_current_monitor_nano.store(0, std::memory_order_relaxed);
    ALOGI("Destroy done");
}

} // namespace atrace
