#include "IOHook.h"
#include <shadowhook.h>
#include "include/atrace.h"
#include "utils/thread_utils.h"
#include "utils/time_utils.h"
#define ATRACE_LOG_TAG "IOHook"
#include "utils/atrace_log.h"

namespace atrace {

static std::atomic<bool> g_enabled{false};
static void* g_read_stub = nullptr;
static void* g_write_stub = nullptr;

static ssize_t proxy_read(int fd, void* buf, size_t count) {
    SHADOWHOOK_STACK_SCOPE();

    if (g_enabled.load(std::memory_order_relaxed)) {
        uint64_t begin = CurrentBootTimeNanos();
        uint64_t begin_cpu = CurrentCpuTimeNanos();

        ssize_t result = SHADOWHOOK_CALL_PREV(proxy_read, fd, buf, count);

        if (result > 0) {
            RequestSampleWithDuration(SampleType::kIORead, begin, begin_cpu);
        }
        return result;
    }

    return SHADOWHOOK_CALL_PREV(proxy_read, fd, buf, count);
}

static ssize_t proxy_write(int fd, const void* buf, size_t count) {
    SHADOWHOOK_STACK_SCOPE();

    if (g_enabled.load(std::memory_order_relaxed)) {
        uint64_t begin = CurrentBootTimeNanos();
        uint64_t begin_cpu = CurrentCpuTimeNanos();

        ssize_t result = SHADOWHOOK_CALL_PREV(proxy_write, fd, buf, count);

        if (result > 0) {
            RequestSampleWithDuration(SampleType::kIOWrite, begin, begin_cpu);
        }
        return result;
    }

    return SHADOWHOOK_CALL_PREV(proxy_write, fd, buf, count);
}

IOHook& IOHook::Instance() {
    static IOHook instance;
    return instance;
}

bool IOHook::Init(JNIEnv* /*env*/) {
    if (!g_read_stub) {
        InstallPLTHook("libc.so", "read",
                        reinterpret_cast<void*>(proxy_read), &g_read_stub);
        ALOGI("IO read hook: %p", g_read_stub);
    }
    if (!g_write_stub) {
        InstallPLTHook("libc.so", "write",
                        reinterpret_cast<void*>(proxy_write), &g_write_stub);
        ALOGI("IO write hook: %p", g_write_stub);
    }
    return g_read_stub != nullptr || g_write_stub != nullptr;
}

void IOHook::Enable() {
    g_enabled.store(true, std::memory_order_relaxed);
}

void IOHook::Disable() {
    g_enabled.store(false, std::memory_order_relaxed);
}

void IOHook::Destroy() {
    g_enabled.store(false, std::memory_order_relaxed);
    if (g_read_stub) {
        UninstallPLTHook(g_read_stub);
        g_read_stub = nullptr;
    }
    if (g_write_stub) {
        UninstallPLTHook(g_write_stub);
        g_write_stub = nullptr;
    }
}

} // namespace atrace
