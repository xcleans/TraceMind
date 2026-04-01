#include "BinderHook.h"
#include <shadowhook.h>
#include <cstring>
#include "include/atrace.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "BinderHook"
#include "utils/atrace_log.h"

namespace atrace {

static std::atomic<bool> g_enabled{false};
static void* g_stub = nullptr;

static int32_t proxy_IPCThreadState_transact(
        void* ipc_thread_state, int32_t handle, uint32_t code,
        void* data, void* reply, uint32_t flags) {
    SHADOWHOOK_STACK_SCOPE();
    if (g_enabled.load(std::memory_order_relaxed) && !(flags & 0x01)) {
        uint64_t begin = CurrentBootTimeNanos();
        uint64_t begin_cpu = CurrentCpuTimeNanos();
        auto result = SHADOWHOOK_CALL_PREV(proxy_IPCThreadState_transact,
                                           ipc_thread_state, handle, code, data, reply, flags);
        RequestSampleWithDuration(SampleType::kBinder, begin, begin_cpu);
        return result;
    }
    return SHADOWHOOK_CALL_PREV(proxy_IPCThreadState_transact,
                                ipc_thread_state, handle, code, data, reply, flags);
}

BinderHook& BinderHook::Instance() {
    static BinderHook instance;
    return instance;
}

bool BinderHook::IsSupported(int sdk_version, const char* arch) const {
    return sdk_version >= 26 &&
           (strstr(arch, "arm64") != nullptr || strstr(arch, "arm") != nullptr);
}

bool BinderHook::Init(JNIEnv* env) {
    bool result = InstallPLTHook(
            "libbinder.so",
            "_ZN7android14IPCThreadState8transactEijRKNS_6ParcelEPS1_j",
            reinterpret_cast<void*>(proxy_IPCThreadState_transact),
            &g_stub);
    if (!result) ALOGE("Failed to initialize");
    return result;
}

void BinderHook::Enable() {
    g_enabled.store(true, std::memory_order_relaxed);
}

void BinderHook::Disable() {
    g_enabled.store(false, std::memory_order_relaxed);
}

void BinderHook::Destroy() {
    UninstallPLTHook(g_stub);
    g_stub = nullptr;
    g_enabled.store(false, std::memory_order_relaxed);
}

} // namespace atrace
