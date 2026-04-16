/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 统一日志管理
 *
 * 使用方式:
 *   #define ATRACE_LOG_TAG "Hook"       // 自定义子标签
 *   #include "utils/atrace_log.h"       // 最终 tag: "ATrace:Hook"
 *
 * 如不定义 ATRACE_LOG_TAG，则使用默认 tag: "ATrace"
 *
 * 日志开关:
 *   运行时通过 atrace::Log::SetEnabled(false) 全局关闭
 *   编译期通过 ATRACE_LOG_LEVEL 控制最低输出级别
 */

// Log 类和基础设施只定义一次
#ifndef ATRACE_LOG_H
#define ATRACE_LOG_H

#include <android/log.h>
#include <atomic>

#define ATRACE_LOG_PREFIX "ATrace"

#ifndef ATRACE_LOG_LEVEL
#define ATRACE_LOG_LEVEL 0
#endif

namespace atrace {

class Log {
public:
    static bool IsEnabled() { return enabled_.load(std::memory_order_relaxed); }
    static void SetEnabled(bool enabled) { enabled_.store(enabled, std::memory_order_relaxed); }

private:
    static inline std::atomic<bool> enabled_{true};
};

} // namespace atrace

#endif // ATRACE_LOG_H

// 以下宏每次 include 都重新定义，以适配不同的 ATRACE_LOG_TAG
#undef ATRACE_FULL_TAG
#ifdef ATRACE_LOG_TAG
#define ATRACE_FULL_TAG ATRACE_LOG_PREFIX ":" ATRACE_LOG_TAG
#else
#define ATRACE_FULL_TAG ATRACE_LOG_PREFIX
#endif

#undef ALOGV
#undef ALOGD
#undef ALOGI
#undef ALOGW
#undef ALOGE

#if ATRACE_LOG_LEVEL <= 1
#define ALOGV(fmt, ...) \
    do { if (atrace::Log::IsEnabled()) \
        __android_log_print(ANDROID_LOG_VERBOSE, ATRACE_FULL_TAG, fmt, ##__VA_ARGS__); \
    } while (0)
#else
#define ALOGV(...) ((void)0)
#endif

#if ATRACE_LOG_LEVEL <= 2
#define ALOGD(fmt, ...) \
    do { if (atrace::Log::IsEnabled()) \
        __android_log_print(ANDROID_LOG_DEBUG, ATRACE_FULL_TAG, fmt, ##__VA_ARGS__); \
    } while (0)
#else
#define ALOGD(...) ((void)0)
#endif

#if ATRACE_LOG_LEVEL <= 3
#define ALOGI(fmt, ...) \
    do { if (atrace::Log::IsEnabled()) \
        __android_log_print(ANDROID_LOG_INFO, ATRACE_FULL_TAG, fmt, ##__VA_ARGS__); \
    } while (0)
#else
#define ALOGI(...) ((void)0)
#endif

#if ATRACE_LOG_LEVEL <= 4
#define ALOGW(fmt, ...) \
    do { if (atrace::Log::IsEnabled()) \
        __android_log_print(ANDROID_LOG_WARN, ATRACE_FULL_TAG, fmt, ##__VA_ARGS__); \
    } while (0)
#else
#define ALOGW(...) ((void)0)
#endif

#define ALOGE(fmt, ...) \
    __android_log_print(ANDROID_LOG_ERROR, ATRACE_FULL_TAG, fmt, ##__VA_ARGS__)
