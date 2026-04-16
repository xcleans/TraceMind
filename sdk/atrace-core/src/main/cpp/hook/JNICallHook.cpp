#include "JNICallHook.h"
#include <shadowhook.h>
#include <cstring>
#include "core/StackSampler.h"
#include "include/atrace.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "JNICallHook"
#include "utils/atrace_log.h"

namespace atrace {

static std::atomic<bool> g_enabled{false};
static void* g_stub = nullptr;
static int g_sdk = 0;

struct TwoWordReturn {
    uintptr_t lo;
    uintptr_t hi;
};

//触发JNI
//从调用栈拿到 ArtMethod*
//获取：
//JNI 函数指针
//shorty（参数签名）
//返回类型

static TwoWordReturn proxy_artQuickGenericJniTrampoline_8to10(void* self, void** managed_sp) {
    SHADOWHOOK_STACK_SCOPE();
    // 必须覆盖 CALL_PREV 之后的 RequestSample：JNI 返回时 ScanClassAndHook 等已析构
    // ScopedStackWalkSuppress，但栈上仍有 entry→trampoline 的帧；此时 WalkStack 会
    // 在 GetOatQuickMethodHeader / OatQuickMethodHeader::Contains 崩溃（Android 13+）。
    ScopedStackWalkSuppress suppress_walk;
    auto result = SHADOWHOOK_CALL_PREV(proxy_artQuickGenericJniTrampoline_8to10, self, managed_sp);
//    if (g_enabled) RequestSample(SampleType::kJNICall);
    return result;
}

static void* proxy_artQuickGenericJniTrampoline_11(void* self, void** managed_sp, uintptr_t* reserved) {
    SHADOWHOOK_STACK_SCOPE();
    ScopedStackWalkSuppress suppress_walk;
    auto result = SHADOWHOOK_CALL_PREV(proxy_artQuickGenericJniTrampoline_11, self, managed_sp, reserved);
//    if (g_enabled) RequestSample(SampleType::kJNICall);
    return result;
}

JNICallHook& JNICallHook::Instance() {
    static JNICallHook instance;
    return instance;
}

bool JNICallHook::IsSupported(int sdk_version, const char* arch) const {
    return sdk_version >= 26 && sdk_version <= 33 && strstr(arch, "arm") != nullptr;
}

void JNICallHook::SetSdkVersion(int sdk) {
    g_sdk = sdk;
}

bool JNICallHook::Init(JNIEnv* env) {
    void* proxy;
    if (g_sdk < 30) {
        proxy = reinterpret_cast<void*>(proxy_artQuickGenericJniTrampoline_8to10);
    } else {
        proxy = reinterpret_cast<void*>(proxy_artQuickGenericJniTrampoline_11);
    }

    bool result = InstallPLTHook(
            "libart.so",
            "artQuickGenericJniTrampoline",
            proxy,
            &g_stub);
    if (result) {
        ALOGI("Initialized successfully (sdk=%d)", g_sdk);
    } else {
        ALOGE("Failed to initialize");
    }
    return result;
}

void JNICallHook::Enable() {
    g_enabled.store(true, std::memory_order_relaxed);
}

void JNICallHook::Disable() {
    g_enabled.store(false, std::memory_order_relaxed);
}

void JNICallHook::Destroy() {
    UninstallPLTHook(g_stub);
    g_stub = nullptr;
    g_enabled.store(false, std::memory_order_relaxed);
}

} // namespace atrace
