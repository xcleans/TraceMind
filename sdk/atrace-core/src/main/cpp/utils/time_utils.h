/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <cstdint>
#include <time.h>
#include "include/atrace.h"

namespace atrace {

/**
 * 获取当前时间 (纳秒)
 */
inline uint64_t CurrentTimeNanos(ClockType type) {
    struct timespec ts;
    clock_gettime(static_cast<clockid_t>(type), &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
}

/**
 * 获取当前 Boot 时间 (纳秒)
 */
inline uint64_t CurrentBootTimeNanos() {
    return CurrentTimeNanos(ClockType::kBoottime);
}

/**
 * 获取当前 Boot 时间 (毫秒)
 */
inline uint64_t CurrentBootTimeMillis() {
    return CurrentBootTimeNanos() / 1000000ULL;
}

/**
 * 获取当前线程 CPU 时间 (纳秒)
 */
inline uint64_t CurrentCpuTimeNanos() {
    struct timespec ts;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
}

/**
 * 获取时钟分辨率 (纳秒)
 */
inline uint64_t GetClockResolution(ClockType type) {
    struct timespec ts;
    clock_getres(static_cast<clockid_t>(type), &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL + ts.tv_nsec;
}

} // namespace atrace

