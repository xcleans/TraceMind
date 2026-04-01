/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <cstdint>
#include <string>
#include <functional>

namespace atrace {

// 版本信息
constexpr int VERSION_MAJOR = 1;
constexpr int VERSION_MINOR = 0;
constexpr int VERSION_PATCH = 0;

// 采样类型枚举
enum class SampleType : uint16_t {
    kCustom = 1,
    kBinder = 2,
    kGCWait = 3,
    kMonitorEnter = 4,
    kObjectWait = 5,
    kUnsafePark = 6,
    kJNICall = 7,
    kLoadLibrary = 8,
    kObjectAlloc = 9,
    kIORead = 10,
    kIOWrite = 11,
    kNativePoll = 12,
    kWakeup = 20,
    kMessageBegin = 30,
    kMessageEnd = 31,
    kSectionBegin = 40,
    kSectionEnd = 41,
};

// 时钟类型
enum class ClockType : int {
    kRealtime = 0,    // CLOCK_REALTIME
    kMonotonic = 1,   // CLOCK_MONOTONIC
    kBoottime = 7,    // CLOCK_BOOTTIME
};

// 配置结构
struct Config {
    uint32_t buffer_capacity = 100000;
    uint64_t main_thread_interval_ns = 1000000;    // 1ms
    uint64_t other_thread_interval_ns = 5000000;   // 5ms
    uint16_t max_stack_depth = 64;
    ClockType clock_type = ClockType::kBoottime;
    bool enable_thread_names = true;
    bool enable_wakeup = false;
    bool enable_alloc = false;
    bool enable_rusage = true;
    bool debug_mode = false;
    bool shadow_pause = false;  // Shadow Pause 模式：stop 时不卸载 Hook，只停止采集
};

// 采样请求结果
enum class SampleResult {
    kSuccess,
    kSkipped,      // 间隔未到
    kNotStarted,   // 未开始追踪
    kBufferFull,   // 缓冲区满
    kError,        // 其他错误
};

// 前向声明
class TraceEngine;
class BufferManager;
class StackSampler;
class SymbolResolver;

// 全局引擎访问
TraceEngine* GetEngine();

// 便捷采样函数
SampleResult RequestSample(SampleType type, bool force = false);
SampleResult RequestSampleWithDuration(SampleType type, uint64_t begin_nano, uint64_t begin_cpu_nano);
SampleResult RequestSampleWithDuration(SampleType type, void* thread_self, uint64_t begin_nano, uint64_t begin_cpu_nano);

// 检查是否在主线程
bool IsMainThread();

// 获取当前时间
uint64_t CurrentTimeNanos(ClockType type);
uint64_t CurrentCpuTimeNanos();

} // namespace atrace

