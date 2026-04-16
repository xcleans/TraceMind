#include "MsgQueueHook.h"
#include <shadowhook.h>
#include "include/atrace.h"
#include "core/TraceEngine.h"
#include "hook/JNIMethodHook.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "MsgQueueHook"
#include "utils/atrace_log.h"

namespace atrace {

static std::atomic<bool> g_enabled{false};
static void* g_stub = nullptr;
static void (*g_origin_nativePollOnce)(JNIEnv*, jobject, jlong, jint) = nullptr;

static void proxy_nativePollOnce(JNIEnv* env, jobject thiz, jlong ptr, jint timeout) {
    if (!g_origin_nativePollOnce) return;

    if (g_enabled.load(std::memory_order_relaxed)) {
        auto* engine = GetEngine();
        if (engine) engine->OnMessageBegin();

        uint64_t begin = CurrentBootTimeNanos();
        uint64_t begin_cpu = CurrentCpuTimeNanos();

        g_origin_nativePollOnce(env, thiz, ptr, timeout);

        RequestSampleWithDuration(SampleType::kNativePoll, begin, begin_cpu);
        return;
    }

    g_origin_nativePollOnce(env, thiz, ptr, timeout);
}

MsgQueueHook& MsgQueueHook::Instance() {
    static MsgQueueHook instance;
    return instance;
}

bool MsgQueueHook::Init(JNIEnv* env) {
    if (g_stub) return true;

    if (!jni_hook::IsInitialized()) {
        ALOGE("JNI Hook not initialized, MessageQueue hook failed");
        return false;
    }

    void* origin = nullptr;
    jni_hook::HookMethod(
        env, "android/os/MessageQueue", "nativePollOnce", "(JI)V",
        reinterpret_cast<void*>(proxy_nativePollOnce), &origin);

    if (origin) {
        g_origin_nativePollOnce = reinterpret_cast<void(*)(JNIEnv*, jobject, jlong, jint)>(origin);
        g_stub = origin;
        ALOGI("MessageQueue hook installed");
    }

    return g_origin_nativePollOnce != nullptr;
}

void MsgQueueHook::Enable() {
    g_enabled.store(true, std::memory_order_relaxed);
}

void MsgQueueHook::Disable() {
    g_enabled.store(false, std::memory_order_relaxed);
}

void MsgQueueHook::Destroy() {
    g_enabled.store(false, std::memory_order_relaxed);
    g_origin_nativePollOnce = nullptr;
}

} // namespace atrace
