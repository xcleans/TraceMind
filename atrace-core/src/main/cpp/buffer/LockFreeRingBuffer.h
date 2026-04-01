/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 无锁环形缓冲区 - 支持多生产者单消费者 (MPSC)
 */
#pragma once

#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>
#include <sys/mman.h>

namespace atrace {

/**
 * 无锁环形缓冲区
 *
 * 优化点:
 * 1. 使用mmap分配对齐内存，提高缓存效率
 * 2. 原子操作仅用于ticket分配，写入无锁
 * 3. 双缓冲设计，dump时自动切换
 * 4. 支持按时间范围导出
 *
 * @tparam T 记录类型
 */
template<typename T>
class LockFreeRingBuffer {
public:
    using TimeGetter = uint64_t(*)(const T&);

    /**
     * 创建缓冲区
     *
     * @param capacity 容量
     * @param time_getter 获取记录时间的函数
     * @return 缓冲区实例
     */
    static std::unique_ptr<LockFreeRingBuffer> Create(uint64_t capacity, TimeGetter time_getter) {
        size_t buffer_size = sizeof(T) * capacity;
        size_t alloc_size = (buffer_size + INNER_PAGE_SIZE - 1) & ~(INNER_PAGE_SIZE - 1);
        
        void* memory = mmap(nullptr, alloc_size, PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (memory == MAP_FAILED) {
            return nullptr;
        }
        
        return std::unique_ptr<LockFreeRingBuffer>(
            new LockFreeRingBuffer(capacity, memory, alloc_size, time_getter));
    }

    ~LockFreeRingBuffer() {
        if (buffer_) {
            munmap(buffer_, alloc_size_);
        }
    }

    // 禁止拷贝
    LockFreeRingBuffer(const LockFreeRingBuffer&) = delete;
    LockFreeRingBuffer& operator=(const LockFreeRingBuffer&) = delete;

    /**
     * 获取一个写入槽位
     *
     * @return 记录引用
     */
    T& Acquire() {
        int64_t ticket = ticket_.fetch_add(1, std::memory_order_relaxed);
        return buffer_[ticket % capacity_];
    }

    /**
     * 写入记录
     *
     * @param record 记录
     * @return 写入的ticket
     */
    int64_t Write(const T& record) {
        int64_t ticket = ticket_.fetch_add(1, std::memory_order_relaxed);
        buffer_[ticket % capacity_] = record;
        return ticket;
    }

    /**
     * 获取当前ticket (用于标记时间点)
     */
    int64_t CurrentTicket() const {
        return ticket_.load(std::memory_order_acquire);
    }

    /**
     * 获取指定位置的记录
     */
    const T& At(int64_t ticket) const {
        return buffer_[ticket % capacity_];
    }

    T& At(int64_t ticket) {
        return buffer_[ticket % capacity_];
    }

    /**
     * 获取容量
     */
    uint64_t Capacity() const { return capacity_; }

    /**
     * 计算有效记录数量
     */
    uint32_t AvailableCount(int64_t end_ticket) const {
        int64_t start = end_ticket > static_cast<int64_t>(capacity_) 
                       ? end_ticket - capacity_ : 0;
        return static_cast<uint32_t>(end_ticket - start);
    }

    /**
     * 清空缓冲区
     */
    void Clear() {
        ticket_.store(0, std::memory_order_release);
    }

    /**
     * 按时间范围查找起始ticket
     *
     * @param start_time_ns 起始时间(纳秒)
     * @param end_ticket 结束ticket
     * @param out_start_ticket 输出起始ticket
     * @return 是否找到
     */
    bool FindTimeRange(uint64_t start_time_ns, int64_t end_ticket, int64_t* out_start_ticket) const {
        if (!time_getter_ || end_ticket <= 0) {
            return false;
        }

        int64_t start = end_ticket > static_cast<int64_t>(capacity_) 
                       ? end_ticket - capacity_ : 0;

        // 二分查找
        int64_t left = start;
        int64_t right = end_ticket;

        while (left < right) {
            int64_t mid = left + (right - left) / 2;
            uint64_t time = time_getter_(buffer_[mid % capacity_]);
            if (time < start_time_ns) {
                left = mid + 1;
            } else {
                right = mid;
            }
        }

        *out_start_ticket = left;
        return left < end_ticket;
    }

private:
    static constexpr size_t INNER_PAGE_SIZE = 4096;

    LockFreeRingBuffer(uint64_t capacity, void* memory, size_t alloc_size, TimeGetter time_getter)
        : capacity_(capacity)
        , buffer_(static_cast<T*>(memory))
        , alloc_size_(alloc_size)
        , time_getter_(time_getter)
        , ticket_(0) {}

    const uint64_t capacity_;
    T* buffer_;
    const size_t alloc_size_;
    TimeGetter time_getter_;
    std::atomic<int64_t> ticket_;
};

/**
 * 双缓冲管理器
 *
 * 在dump期间自动切换到备份缓冲区，保证数据不丢失
 */
template<typename T>
class DoubleBuffer {
public:
    using TimeGetter = typename LockFreeRingBuffer<T>::TimeGetter;

    static std::unique_ptr<DoubleBuffer> Create(uint64_t capacity, TimeGetter time_getter) {
        auto major = LockFreeRingBuffer<T>::Create(capacity, time_getter);
        auto backup = LockFreeRingBuffer<T>::Create(capacity, time_getter);
        
        if (!major || !backup) {
            return nullptr;
        }

        return std::unique_ptr<DoubleBuffer>(
            new DoubleBuffer(std::move(major), std::move(backup)));
    }

    T& Acquire() {
        return GetCurrentBuffer().Acquire();
    }

    int64_t Write(const T& record) {
        return GetCurrentBuffer().Write(record);
    }

    int64_t Mark() {
        return GetCurrentBuffer().CurrentTicket();
    }

    uint64_t Capacity() const {
        return major_->Capacity();
    }

    /**
     * RAII风格的Dump保护
     * 在dump期间切换到备份缓冲区
     */
    class DumpGuard {
    public:
        explicit DumpGuard(DoubleBuffer& db) : db_(db), start_ticket_(db.Mark()) {
            db.backup_->Clear();
            db.use_backup_.store(true, std::memory_order_release);
        }

        ~DumpGuard() {
            db_.use_backup_.store(false, std::memory_order_release);
            // 将备份缓冲区的数据合并回主缓冲区
            MergeBackup();
        }

        int64_t StartTicket() const { return start_ticket_; }

        LockFreeRingBuffer<T>& Buffer() { return *db_.major_; }

    private:
        void MergeBackup() {
            int64_t backup_count = db_.backup_->CurrentTicket();
            for (int64_t i = 0; i < backup_count; ++i) {
                db_.major_->Write(db_.backup_->At(i));
            }
        }

        DoubleBuffer& db_;
        int64_t start_ticket_;
    };

    DumpGuard BeginDump() {
        return DumpGuard(*this);
    }

private:
    DoubleBuffer(std::unique_ptr<LockFreeRingBuffer<T>> major,
                 std::unique_ptr<LockFreeRingBuffer<T>> backup)
        : major_(std::move(major))
        , backup_(std::move(backup))
        , use_backup_(false) {}

    LockFreeRingBuffer<T>& GetCurrentBuffer() {
        if (use_backup_.load(std::memory_order_acquire)) {
            return *backup_;
        }
        return *major_;
    }

    std::unique_ptr<LockFreeRingBuffer<T>> major_;
    std::unique_ptr<LockFreeRingBuffer<T>> backup_;
    std::atomic<bool> use_backup_;
};

} // namespace atrace

