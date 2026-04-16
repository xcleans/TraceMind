/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 堆栈采样器
 */
#pragma once

#include <cstdint>
#include "buffer/SampleRecord.h"
#include "SymbolResolver.h"

namespace atrace {

/**
 * 当前线程禁止 ART StackVisitor::WalkStack（用于安装 method hook / 类扫描期间）。
 * 若此时 WalkStack，栈上可能已有 entry 指向 app .so 内 trampoline/stub，
 * GetOatQuickMethodHeader 会按 OAT 布局解析 → SIGSEGV（Android 13+ 常见）。
 */
class ScopedStackWalkSuppress {
public:
    ScopedStackWalkSuppress();
    ~ScopedStackWalkSuppress();
    ScopedStackWalkSuppress(const ScopedStackWalkSuppress &) = delete;
    ScopedStackWalkSuppress &operator=(const ScopedStackWalkSuppress &) = delete;
};

/**
 * 堆栈遍历模式
 */
enum class StackWalkKind {
    kIncludeInlinedFrames = 0,
    kSkipInlinedFrames = 1,
};

/**
 * 堆栈采样器
 *
 * 通过调用ART内部的StackVisitor遍历Java堆栈
 */
class StackSampler {
public:
    /**
     * 获取单例
     */
    static StackSampler& Instance();

    /**
     * 初始化
     *
     * @return 是否成功
     */
    bool Init();

    /**
     * 是否已初始化
     */
    bool IsInitialized() const { return initialized_; }

    /** 当前线程是否处于「禁止 WalkStack」临界区（嵌套计数 > 0） */
    static bool IsWalkSuppressedOnThisThread();

    /**
     * 采样当前线程堆栈
     *
     * @param stack 输出堆栈
     * @param thread_self 当前线程对象指针，为空则自动获取
     * @param walk_kind 遍历模式
     * @return 是否成功
     */
    bool Sample(Stack& stack, void* thread_self = nullptr,
                StackWalkKind walk_kind = StackWalkKind::kIncludeInlinedFrames);

    /**
     * 将堆栈转换为字符串 (调试用)
     */
    std::string StackToString(const Stack& stack) const;

private:
    StackSampler() = default;
    ~StackSampler() = default;

    StackSampler(const StackSampler&) = delete;
    StackSampler& operator=(const StackSampler&) = delete;

    /**
     * 内部采样实现
     */
    bool SampleInternal(Stack& stack, void* thread, StackWalkKind walk_kind);

    /**
     * 获取当前线程对象
     */
    void* GetCurrentThread();

    bool initialized_ = false;
};

/**
 * RAII风格的采样辅助类
 *
 * 在构造时记录开始时间，析构时自动采样
 */
class ScopedSample {
public:
    /**
     * 构造函数
     *
     * @param type 采样类型
     * @param thread_self 线程对象指针
     */
    explicit ScopedSample(SampleType type, void* thread_self = nullptr);

    /**
     * 析构函数 - 自动进行采样
     */
    ~ScopedSample();

    // 禁止拷贝
    ScopedSample(const ScopedSample&) = delete;
    ScopedSample& operator=(const ScopedSample&) = delete;

    /**
     * 获取开始时间
     */
    uint64_t BeginNano() const { return begin_nano_; }
    uint64_t BeginCpuNano() const { return begin_cpu_nano_; }

private:
    SampleType type_;
    void* thread_self_;
    uint64_t begin_nano_;
    uint64_t begin_cpu_nano_;
};

} // namespace atrace

