#include "GCHook.h"
#include <shadowhook.h>
#include <cstring>
#include "include/atrace.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"

#define ATRACE_LOG_TAG "GCHook"

#include "utils/atrace_log.h"

namespace atrace {

    static std::atomic<bool> g_enabled{false};
    static void *g_stub = nullptr;

    static void *proxy_WaitForGcToComplete(void *heap, void *cause, void *thread_self) {
        SHADOWHOOK_STACK_SCOPE();
        if (g_enabled) {
            uint64_t begin = CurrentBootTimeNanos();
            uint64_t begin_cpu = CurrentCpuTimeNanos();
            void *result = SHADOWHOOK_CALL_PREV(proxy_WaitForGcToComplete, heap, cause, thread_self);
            ALOGE("RequestSampleWithDuration:kGCWait");
            RequestSampleWithDuration(SampleType::kGCWait, thread_self, begin, begin_cpu);
            return result;
        }
        return SHADOWHOOK_CALL_PREV(proxy_WaitForGcToComplete, heap, cause, thread_self);
    }

    GCHook &GCHook::Instance() {
        static GCHook instance;
        return instance;
    }

    bool GCHook::IsSupported(int sdk_version, const char *arch) const {
        return sdk_version >= 26 && strstr(arch, "arm") != nullptr;
    }

    bool GCHook::Init(JNIEnv *env) {

        //_ZN3art2gc4Heap19WaitForGcToCompleteENS0_7GcCauseEPNS_6ThreadE
        bool result = InstallPLTHook(
                "libart.so",
                "_ZN3art2gc4Heap25WaitForGcToCompleteLockedENS0_7GcCauseEPNS_6ThreadE",
                reinterpret_cast<void *>(proxy_WaitForGcToComplete),
                &g_stub);
        if (!result) {
            ALOGE("Failed to initialize retry _ZN3art2gc4Heap19WaitForGcToCompleteENS0_7GcCauseEPNS_6ThreadE");
            result = InstallPLTHook(
                    "libart.so",
                    "_ZN3art2gc4Heap19WaitForGcToCompleteENS0_7GcCauseEPNS_6ThreadE",
                    reinterpret_cast<void *>(proxy_WaitForGcToComplete),
                    &g_stub);
        }
        if (!result) {
            ALOGE("Failed to initialize===");
        }

        return result;
    }

    void GCHook::Enable() {
        g_enabled.store(true, std::memory_order_relaxed);
    }

    void GCHook::Disable() {
        g_enabled.store(false, std::memory_order_relaxed);
    }

    void GCHook::Destroy() {
        UninstallPLTHook(g_stub);
        g_stub = nullptr;
        g_enabled.store(false, std::memory_order_relaxed);
    }

} // namespace atrace
