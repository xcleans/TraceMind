/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 追踪引擎核心
 */
#pragma once

#include <atomic>
#include <memory>
#include <string>
#include <vector>
#include <unordered_set>
#include <jni.h>

#include "include/atrace.h"
#include "buffer/LockFreeRingBuffer.h"
#include "buffer/SampleRecord.h"
#include "StackSampler.h"
#include "SymbolResolver.h"

namespace atrace {

// 前向声明
class HookManager;

/**
 * 追踪引擎
 *
 * 核心职责:
 * 1. 管理采样生命周期
 * 2. 协调各组件工作
 * 3. 导出追踪数据
 */
class TraceEngine {
public:
    /**
     * 创建引擎实例
     *
     * @param env JNI环境
     * @param config 配置
     * @return 引擎实例
     */
    static std::unique_ptr<TraceEngine> Create(JNIEnv* env, const Config& config);

    ~TraceEngine();

    // 禁止拷贝
    TraceEngine(const TraceEngine&) = delete;
    TraceEngine& operator=(const TraceEngine&) = delete;

    /**
     * 开始追踪
     *
     * @return 开始token
     */
    int64_t Start();

    /**
     * 停止追踪
     *
     * @return 结束token
     */
    int64_t Stop();

    /**
     * 是否正在追踪
     */
    bool IsTracing() const { return tracing_.load(std::memory_order_acquire); }

    /**
     * 是否暂停
     */
    bool IsPaused() const { return paused_.load(std::memory_order_acquire); }

    /**
     * 暂停采样
     */
    void Pause() { paused_.store(true, std::memory_order_release); }

    /**
     * 恢复采样
     */
    void Resume() { paused_.store(false, std::memory_order_release); }

    /**
     * 检查是否为 Shadow Pause 模式
     */
    bool IsShadowPauseMode() const { return config_.shadow_pause; }

    /**
     * 请求一次采样
     *
     * @param type 采样类型
     * @param thread_self 线程对象指针
     * @param force 强制采样
     * @param capture_at_end 在结束时捕获
     * @param begin_nano 开始时间
     * @param begin_cpu_nano 开始CPU时间
     * @return 采样结果
     */
    SampleResult RequestSample(SampleType type, void* thread_self = nullptr,
                               bool force = false, bool capture_at_end = false,
                               uint64_t begin_nano = 0, uint64_t begin_cpu_nano = 0);

    /**
     * 手动捕获堆栈
     */
    void Capture(bool force);

    /**
     * 记录标记
     */
    void Mark(const char* name, SampleType type = SampleType::kCustom);

    /**
     * 开始自定义区间
     */
    int64_t BeginSection(const char* name);

    /**
     * 结束自定义区间
     */
    void EndSection(int64_t token);

    /**
     * 导出追踪数据
     *
     * @param path 输出路径
     * @param start_token 开始token
     * @param end_token 结束token
     * @param extra 附加信息
     * @return 错误码 (0表示成功)
     */
    int Export(const char* path, int64_t start_token, int64_t end_token, const char* extra);

    /**
     * 动态更新采样间隔（线程安全）
     *
     * @param main_interval_ns 主线程间隔（纳秒），0 表示不修改
     * @param other_interval_ns 其他线程间隔（纳秒），0 表示不修改
     */
    void SetSamplingInterval(uint64_t main_interval_ns, uint64_t other_interval_ns);

    /**
     * 获取配置
     */
    const Config& GetConfig() const { return config_; }

    /**
     * 获取当前缓冲区写入位置 (ticket)
     */
    int64_t GetCurrentTicket() const { return buffer_->Mark(); }

    /**
     * 获取缓冲区容量
     */
    uint64_t GetBufferCapacity() const { return buffer_->Capacity(); }

    /**
     * 获取主线程ID
     */
    pid_t GetMainThreadId() const { return main_thread_id_; }

    /**
     * 获取当前Message ID (主线程)
     */
    uint32_t GetCurrentMessageId() const { return message_id_.load(std::memory_order_relaxed); }

    /**
     * Message开始 (由MessageQueue Hook调用)
     */
    void OnMessageBegin();

    /**
     * Message结束 (由MessageQueue Hook调用)
     */
    void OnMessageEnd();

private:
    TraceEngine(const Config& config, 
                std::unique_ptr<DoubleBuffer<SampleRecord>> buffer,
                pid_t main_thread_id);

    /**
     * 检查是否应该采样
     */
    bool ShouldSample(bool force);

    /**
     * 写入采样记录
     */
    void WriteSample(SampleRecord& record);

    /**
     * 导出到文件
     */
    int ExportToFile(int fd, int mapping_fd, int64_t start_token, int64_t end_token, const char* extra);

    /**
     * 导出方法映射
     */
    bool ExportMapping(int fd, const std::unordered_set<uint64_t>& method_ids);

    /**
     * 导出线程名
     */
    void ExportThreadNames(int fd);

    Config config_;
    std::unique_ptr<DoubleBuffer<SampleRecord>> buffer_;
    std::unique_ptr<HookManager> hook_manager_;

    pid_t main_thread_id_;
    std::atomic<bool> tracing_{false};
    std::atomic<bool> paused_{false};
    std::atomic<bool> hooks_installed_{false};  // Hook 是否已安装
    std::atomic<uint32_t> message_id_{0};

    // 线程局部采样间隔控制
    static thread_local uint64_t last_sample_time_;
};

/**
 * Hook管理器
 *
 * 负责管理所有Hook点的安装和卸载
 */
class HookManager {
public:
    static std::unique_ptr<HookManager> Create(TraceEngine* engine);

    ~HookManager();

    /**
     * 安装所有Hook
     */
    bool InstallHooks();

    /**
     * 卸载所有Hook
     */
    void UninstallHooks();

    /**
     * 启用/禁用特定Hook
     */
    void EnableHook(const char* name, bool enable);

private:
    explicit HookManager(TraceEngine* engine);

    struct HookEntry {
        const char* name;
        const char* lib;
        const char* symbol;
        void* replacement;
        void* stub;
        bool enabled;
    };

    TraceEngine* engine_;
    std::vector<HookEntry> hooks_;
};

// 全局引擎指针 (线程安全)
extern std::atomic<TraceEngine*> g_engine;

} // namespace atrace

