/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "TraceEngine.h"
#include "StackSampler.h"
#include "SymbolResolver.h"
#include "utils/time_utils.h"
#include "utils/thread_utils.h"

#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <dirent.h>
#include <cstring>

#define ATRACE_LOG_TAG "Engine"

#include "utils/atrace_log.h"

namespace atrace {

// 全局引擎指针
    std::atomic<TraceEngine *> g_engine{nullptr};

// 线程局部采样时间
    thread_local uint64_t TraceEngine::last_sample_time_ = 0;

    TraceEngine *GetEngine() {
        return g_engine.load(std::memory_order_acquire);
    }


    SampleResult RequestSample(SampleType type, bool force) {
        auto *engine = GetEngine();
        if (!engine) return SampleResult::kNotStarted;
        return engine->RequestSample(type, nullptr, force);
    }

    SampleResult RequestSampleWithDuration(SampleType type, uint64_t begin_nano, uint64_t begin_cpu_nano) {
        auto *engine = GetEngine();
        if (!engine) return SampleResult::kNotStarted;
        return engine->RequestSample(type, nullptr, false, true, begin_nano, begin_cpu_nano);
    }

    SampleResult RequestSampleWithDuration(SampleType type, void* thread_self, uint64_t begin_nano, uint64_t begin_cpu_nano) {
        auto *engine = GetEngine();
        if (!engine) return SampleResult::kNotStarted;
        return engine->RequestSample(type, thread_self, false, true, begin_nano, begin_cpu_nano);
    }

    std::unique_ptr<TraceEngine> TraceEngine::Create(JNIEnv *env, const Config &config) {
        // 初始化符号解析器
        int sdk_version = GetAndroidSdkVersion();
        ALOGD("TraceEngine#Create:sdk_version:%d", sdk_version);

        if (!SymbolResolver::Instance().Init(sdk_version)) {
            ALOGE("Failed to initialize symbol resolver");
            return nullptr;
        }

        ALOGD("StackSampler::Instance().Init()");
        // 初始化堆栈采样器
        if (!StackSampler::Instance().Init()) {
            ALOGE("Failed to initialize stack sampler");
            return nullptr;
        }

        // 创建缓冲区
        auto buffer = DoubleBuffer<SampleRecord>::Create(config.buffer_capacity, GetRecordTime);
        if (!buffer) {
            ALOGE("Failed to create sample buffer");
            return nullptr;
        }

        pid_t main_tid = getpid();
        auto engine = std::unique_ptr<TraceEngine>(
                new TraceEngine(config, std::move(buffer), main_tid));

        // 创建Hook管理器
        engine->hook_manager_ = HookManager::Create(engine.get());

        g_engine.store(engine.get(), std::memory_order_release);

        ALOGI("TraceEngine created, buffer_capacity=%u, main_tid=%d",
                config.buffer_capacity, main_tid);

        return engine;
    }

    TraceEngine::TraceEngine(const Config &config,
            std::unique_ptr<DoubleBuffer<SampleRecord>> buffer,
            pid_t main_thread_id)
            : config_(config), buffer_(std::move(buffer)), main_thread_id_(main_thread_id) {
    }

    TraceEngine::~TraceEngine() {
        if (tracing_.load()) {
            Stop();
        }

        hook_manager_.reset();

        if (g_engine.load() == this) {
            g_engine.store(nullptr, std::memory_order_release);
        }

        ALOGI("TraceEngine destroyed");
    }

    int64_t TraceEngine::Start() {
        if (tracing_.exchange(true)) {
            ALOGD("Already tracing");
            return buffer_->Mark();
        }

        // 安装Hook (如果未安装或非 Shadow Pause 模式)
        if (hook_manager_ && !hooks_installed_.load(std::memory_order_acquire)) {
            hook_manager_->InstallHooks();
            hooks_installed_.store(true, std::memory_order_release);
            ALOGI("Hooks installed");
        } else if (config_.shadow_pause) {
            ALOGI("Shadow Pause mode: reusing existing hooks");
        }

        // 恢复采样
        paused_.store(false, std::memory_order_release);

        int64_t token = buffer_->Mark();
        ALOGI("Tracing started, token=%lld", (long long) token);
        return token;
    }

    int64_t TraceEngine::Stop() {
        if (!tracing_.exchange(false)) {
            ALOGD("Not tracing");
            return -1;
        }

        int64_t token = buffer_->Mark();

        // Shadow Pause 模式：只暂停采样，不卸载 Hook
        if (config_.shadow_pause) {
            paused_.store(true, std::memory_order_release);
            ALOGI("Tracing paused (shadow mode), token=%lld", (long long) token);
        } else {
            // 正常模式：卸载 Hook
            if (hook_manager_ && hooks_installed_.exchange(false)) {
                hook_manager_->UninstallHooks();
                ALOGI("Hooks uninstalled");
            }
            ALOGI("Tracing stopped, token=%lld", (long long) token);
        }

        return token;
    }

    void TraceEngine::SetSamplingInterval(uint64_t main_interval_ns, uint64_t other_interval_ns) {
        if (main_interval_ns > 0) {
            config_.main_thread_interval_ns = main_interval_ns;
        }
        if (other_interval_ns > 0) {
            config_.other_thread_interval_ns = other_interval_ns;
        }
        ALOGI("Sampling interval updated: main=%llu ns, other=%llu ns",
              (unsigned long long) config_.main_thread_interval_ns,
              (unsigned long long) config_.other_thread_interval_ns);
    }

    bool TraceEngine::ShouldSample(bool force) {
        if (force) return true;

        uint64_t now = CurrentTimeNanos(config_.clock_type);
        uint64_t interval = IsMainThread()
                ? config_.main_thread_interval_ns
                : config_.other_thread_interval_ns;

        if (now - last_sample_time_ >= interval) {
            last_sample_time_ = now;
            return true;
        }

        return false;
    }

    SampleResult TraceEngine::RequestSample(SampleType type, void *thread_self,
            bool force, bool capture_at_end,
            uint64_t begin_nano, uint64_t begin_cpu_nano) {
        if (!tracing_.load(std::memory_order_acquire)) {
            return SampleResult::kNotStarted;
        }

        if (paused_.load(std::memory_order_acquire)) {
            return SampleResult::kSkipped;
        }

        if (StackSampler::IsWalkSuppressedOnThisThread()) {
            return SampleResult::kSkipped;
        }

        if (!ShouldSample(force)) {
            return SampleResult::kSkipped;
        }

        // 获取采样槽位
        SampleRecord &record = buffer_->Acquire();
        record.Reset();

        // 采样堆栈
        if (!StackSampler::Instance().Sample(record.stack, thread_self)) {
            return SampleResult::kError;
        }

        // 验证堆栈有效性
        if (!record.stack.IsValid()) {
            return SampleResult::kError;
        }

        // 填充基本信息
        record.type = type;
        record.tid = static_cast<uint16_t>(gettid());
        record.message_id = IsMainThread() ? message_id_.load() : 0;

        // 时间信息
        uint64_t now = CurrentTimeNanos(config_.clock_type);
        uint64_t cpu_now = CurrentCpuTimeNanos();

        if (capture_at_end) {
            record.nano_time = begin_nano;
            record.cpu_time = begin_cpu_nano;
            record.end_nano_time = now;
            record.end_cpu_time = cpu_now;
        } else {
            record.nano_time = now;
            record.cpu_time = cpu_now;
            record.end_nano_time = 0;
            record.end_cpu_time = 0;
        }

        // 资源统计
        if (config_.enable_rusage) {
            struct rusage ru;
            if (getrusage(RUSAGE_THREAD, &ru) == 0) {
                record.major_faults = ru.ru_majflt;
                record.voluntary_csw = ru.ru_nvcsw;
                record.involuntary_csw = ru.ru_nivcsw;
            }
        }

        return SampleResult::kSuccess;
    }

    void TraceEngine::Capture(bool force) {
        RequestSample(SampleType::kCustom, nullptr, force);
    }

    void TraceEngine::Mark(const char *name, SampleType type) {
        if (!tracing_.load()) return;

        SampleRecord &record = buffer_->Acquire();
        record.Reset();
        record.type = type;
        record.tid = static_cast<uint16_t>(gettid());
        record.nano_time = CurrentTimeNanos(config_.clock_type);
        record.SetArg(name);
    }

    int64_t TraceEngine::BeginSection(const char *name) {
        if (!tracing_.load()) return -1;

        Mark(name, SampleType::kSectionBegin);
        return buffer_->Mark();
    }

    void TraceEngine::EndSection(int64_t token) {
        if (!tracing_.load() || token < 0) return;

        SampleRecord &record = buffer_->Acquire();
        record.Reset();
        record.type = SampleType::kSectionEnd;
        record.tid = static_cast<uint16_t>(gettid());
        record.nano_time = CurrentTimeNanos(config_.clock_type);
    }

    void TraceEngine::OnMessageBegin() {
        message_id_.fetch_add(1, std::memory_order_relaxed);
    }

    void TraceEngine::OnMessageEnd() {
        // 可以在这里记录Message结束时间
    }

    int TraceEngine::Export(const char *path, int64_t start_token, int64_t end_token, const char *extra) {
        if (!path) return -1;

        // 创建输出文件
        int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0644);
        if (fd < 0) {
            ALOGE("Failed to open output file: %s", path);
            return -2;
        }

        // 创建mapping文件
        std::string mapping_path = std::string(path) + ".mapping";
        int mapping_fd = open(mapping_path.c_str(), O_CREAT | O_WRONLY | O_TRUNC, 0644);

        int result = ExportToFile(fd, mapping_fd, start_token, end_token, extra);

        close(fd);
        if (mapping_fd >= 0) close(mapping_fd);

        return result;
    }

    int TraceEngine::ExportToFile(int fd, int mapping_fd, int64_t start_token,
            int64_t end_token, const char *extra) {
        auto guard = buffer_->BeginDump();
        auto &buffer = guard.Buffer();

        // 计算有效范围
        int64_t capacity = static_cast<int64_t>(buffer.Capacity());
        int64_t actual_start = std::max(start_token, guard.StartTicket() - capacity);
        int64_t actual_end = std::min(end_token, guard.StartTicket());

        if (actual_start >= actual_end) {
            ALOGE("No valid records to export");
            return -3;
        }

        uint32_t count = static_cast<uint32_t>(actual_end - actual_start);
        ALOGI("Exporting %u records [%lld, %lld)", count,
                (long long) actual_start, (long long) actual_end);

        // 写入文件头
        uint32_t magic = 0x41545243;  // "ATRC"
        uint32_t version = 2;
        uint64_t timestamp = CurrentTimeNanos(ClockType::kRealtime);
        int32_t extra_len = extra ? strlen(extra) : 0;

        write(fd, &magic, sizeof(magic));
        write(fd, &version, sizeof(version));
        write(fd, &timestamp, sizeof(timestamp));
        write(fd, &count, sizeof(count));
        write(fd, &extra_len, sizeof(extra_len));
        if (extra_len > 0) {
            write(fd, extra, extra_len);
        }

        // 写入记录
        std::unordered_set<uint64_t> method_ids;
        char encode_buf[SampleRecord::Size() * 2];

        for (int64_t i = actual_start; i < actual_end; ++i) {
            const SampleRecord &record = buffer.At(i);
            size_t encoded_size = record.EncodeTo(encode_buf);
            write(fd, encode_buf, encoded_size);

            // 收集方法ID
            for (int j = 0; j < record.stack.saved_depth; ++j) {
                method_ids.insert(record.stack.frames[j].method_ptr);
            }
        }

        // 导出方法映射
        if (mapping_fd >= 0) {
            ExportMapping(mapping_fd, method_ids);
        }

        return 0;
    }

    bool TraceEngine::ExportMapping(int fd, const std::unordered_set<uint64_t> &method_ids) {
        auto &resolver = SymbolResolver::Instance();

        uint64_t magic = 0;
        uint32_t version = 1;
        uint32_t count = method_ids.size();

        write(fd, &magic, sizeof(magic));
        write(fd, &version, sizeof(version));
        write(fd, &count, sizeof(count));

        // 写入方法符号
        for (uint64_t method_ptr: method_ids) {
            write(fd, &method_ptr, sizeof(method_ptr));

            std::string symbol = resolver.MethodToString(reinterpret_cast<void *>(method_ptr));
            uint16_t len = static_cast<uint16_t>(symbol.length());
            write(fd, &len, sizeof(len));
            write(fd, symbol.c_str(), len);
        }

        // 写入线程名
        if (config_.enable_thread_names) {
            ExportThreadNames(fd);
        }

        return true;
    }

    void TraceEngine::ExportThreadNames(int fd) {
        uint64_t start_time = CurrentTimeNanos(ClockType::kBoottime);
        uint32_t thread_count = 0;

        const char *task_dir = "/proc/self/task";
        DIR *dir = opendir(task_dir);

        if (dir == nullptr) {
            ALOGE("Failed to open %s", task_dir);
            return;
        }

        struct dirent *entry;
        while ((entry = readdir(dir)) != nullptr) {
            // 跳过 . 和 ..
            if (entry->d_type != DT_DIR ||
                    strcmp(entry->d_name, ".") == 0 ||
                    strcmp(entry->d_name, "..") == 0) {
                continue;
            }

            pid_t tid = static_cast<pid_t>(atoi(entry->d_name));
            if (tid <= 0) continue;

            // 读取线程名
            char path[256];
            snprintf(path, sizeof(path), "/proc/self/task/%d/comm", tid);

            FILE *file = fopen(path, "r");
            if (file) {
                char thread_name[17] = {0};
                if (fgets(thread_name, sizeof(thread_name), file) != nullptr) {
                    // 移除末尾换行符
                    size_t len = strlen(thread_name);
                    if (len > 0 && thread_name[len - 1] == '\n') {
                        thread_name[len - 1] = '\0';
                        len--;
                    }

                    // 写入: tid(2字节) + len(1字节) + name
                    uint16_t tid_u16 = static_cast<uint16_t>(tid);
                    uint8_t name_len = static_cast<uint8_t>(len);

                    write(fd, &tid_u16, sizeof(tid_u16));
                    write(fd, &name_len, sizeof(name_len));
                    write(fd, thread_name, name_len);

                    thread_count++;
                }
                fclose(file);
            }
        }

        closedir(dir);

        uint64_t cost_ms = (CurrentTimeNanos(ClockType::kBoottime) - start_time) / 1000000;
        ALOGD("Exported %u thread names in %llu ms", thread_count, (unsigned long long) cost_ms);
    }

// ============== HookManager ==============

    std::unique_ptr<HookManager> HookManager::Create(TraceEngine *engine) {
        return std::unique_ptr<HookManager>(new HookManager(engine));
    }

    HookManager::HookManager(TraceEngine *engine) : engine_(engine) {
        // Hook条目将由插件注册
    }

    HookManager::~HookManager() {
        UninstallHooks();
    }

    bool HookManager::InstallHooks() {
        // Hook安装由各插件负责
        ALOGI("Installing hooks...");
        return true;
    }

    void HookManager::UninstallHooks() {
        ALOGI("Uninstalling hooks...");
        // Hook卸载由各插件负责
    }

    void HookManager::EnableHook(const char *name, bool enable) {
        for (auto &hook: hooks_) {
            if (strcmp(hook.name, name) == 0) {
                hook.enabled = enable;
                break;
            }
        }
    }

} // namespace atrace

