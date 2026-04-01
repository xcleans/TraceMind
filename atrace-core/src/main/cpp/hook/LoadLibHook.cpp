#include "LoadLibHook.h"
#include <shadowhook.h>
#include "include/atrace.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "LoadLibHook"
#include "utils/atrace_log.h"

namespace atrace {

static std::atomic<bool> g_enabled{false};
static void* g_stub = nullptr;

static void* proxy_dlopen(const char* filename, int flags) {
    SHADOWHOOK_STACK_SCOPE();
    if (g_enabled.load(std::memory_order_relaxed) && filename) {
        uint64_t begin = CurrentBootTimeNanos();
        uint64_t begin_cpu = CurrentCpuTimeNanos();
        void* result = SHADOWHOOK_CALL_PREV(proxy_dlopen, filename, flags);
        RequestSampleWithDuration(SampleType::kLoadLibrary, begin, begin_cpu);
        return result;
    }
    return SHADOWHOOK_CALL_PREV(proxy_dlopen, filename, flags);
}

LoadLibHook& LoadLibHook::Instance() {
    static LoadLibHook instance;
    return instance;
}

bool LoadLibHook::IsSupported(int sdk_version, const char* arch) const {
    return sdk_version >= 26;
}

bool LoadLibHook::Init(JNIEnv* env) {
    bool result = InstallPLTHook(
            "libdl.so",
            "dlopen",
            reinterpret_cast<void*>(proxy_dlopen),
            &g_stub);
    if (!result) ALOGE("Failed to initialize");
    return result;
}

void LoadLibHook::Enable() {
    g_enabled.store(true, std::memory_order_relaxed);
}

void LoadLibHook::Disable() {
    g_enabled.store(false, std::memory_order_relaxed);
}

void LoadLibHook::Destroy() {
    UninstallPLTHook(g_stub);
    g_stub = nullptr;
    g_enabled.store(false, std::memory_order_relaxed);
}

} // namespace atrace
