/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <unistd.h>
#include <sys/syscall.h>
#include <sys/system_properties.h>
#include <cstdlib>

namespace atrace {

/**
 * 获取当前线程 ID
 */
inline pid_t GetTid() {
    return gettid();
}

/**
 * 获取当前进程 ID
 */
inline pid_t GetPid() {
    return getpid();
}

/**
 * 检查是否在主线程
 */
inline bool IsMainThread() {
    static pid_t main_tid = GetPid();
    return GetTid() == main_tid;
}

/**
 * 获取 Android SDK 版本
 */
inline int GetAndroidSdkVersion() {
    static int sdk_version = ([]() {
        char value[128] = {0};
        __system_property_get("ro.build.version.sdk", value);
        return atoi(value);
    })();
    return sdk_version;
}

/**
 * 获取 CPU 架构
 */
inline const char* GetArch() {
#if defined(__aarch64__)
    return "arm64-v8a";
#elif defined(__arm__)
    return "armeabi-v7a";
#elif defined(__x86_64__)
    return "x86_64";
#elif defined(__i386__)
    return "x86";
#else
    return "unknown";
#endif
}

/**
 * 检查是否是 64 位架构
 */
inline bool Is64Bit() {
#if defined(__aarch64__) || defined(__x86_64__)
    return true;
#else
    return false;
#endif
}

/**
 * 检查是否是 ARM 架构
 */
inline bool IsArm() {
#if defined(__aarch64__) || defined(__arm__)
    return true;
#else
    return false;
#endif
}

} // namespace atrace

