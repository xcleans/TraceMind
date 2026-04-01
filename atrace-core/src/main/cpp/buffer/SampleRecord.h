/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 采样记录数据结构
 */
#pragma once

#include <cstdint>
#include <cstring>
#include "include/atrace.h"

namespace atrace {

// 最大堆栈深度
constexpr int kMaxStackDepth = 64;

/**
 * 堆栈帧
 */
struct StackFrame {
    uint64_t method_ptr;  // ArtMethod指针
};

/**
 * 堆栈信息
 */
struct Stack {
    uint8_t saved_depth;     // 保存的深度
    uint8_t actual_depth;    // 实际深度
    StackFrame frames[kMaxStackDepth];

    void Reset() {
        saved_depth = 0;
        actual_depth = 0;
    }

    bool IsValid() const {
        return saved_depth > 0 && saved_depth == actual_depth;
    }
};

/**
 * 采样记录
 *
 * 内存布局优化：按访问频率和对齐要求排列字段
 */
struct alignas(8) SampleRecord {
    // 时间信息 (最常访问)
    uint64_t nano_time;           // 采样时间 (纳秒)
    uint64_t cpu_time;            // CPU时间 (纳秒)
    uint64_t end_nano_time;       // 结束时间 (用于duration类型)
    uint64_t end_cpu_time;        // 结束CPU时间

    // 标识信息
    SampleType type;              // 采样类型
    uint16_t tid;                 // 线程ID
    uint32_t message_id;          // Message ID (主线程)

    // 统计信息
    uint64_t allocated_objects;   // 已分配对象数
    uint64_t allocated_bytes;     // 已分配字节数
    uint32_t major_faults;        // 主缺页次数
    uint32_t voluntary_csw;       // 自愿上下文切换
    uint32_t involuntary_csw;     // 非自愿上下文切换

    // 额外信息
    uint16_t wakeup_tid;          // 唤醒线程ID
    uint16_t arg_length;          // 附加参数长度
    char arg[64];                 // 附加参数 (如方法名)

    // 堆栈信息
    Stack stack;

    // 获取记录大小
    static constexpr size_t Size() {
        return sizeof(SampleRecord);
    }

    // 重置记录
    void Reset() {
        memset(this, 0, sizeof(SampleRecord));
    }

    // 设置附加参数
    void SetArg(const char* value) {
        if (value) {
            size_t len = strlen(value);
            if (len > sizeof(arg) - 1) {
                len = sizeof(arg) - 1;
            }
            memcpy(arg, value, len);
            arg[len] = '\0';
            arg_length = static_cast<uint16_t>(len);
        }
    }

    // 编码为二进制 (用于导出)
    size_t EncodeTo(char* out) const {
        size_t offset = 0;

        auto write = [&out, &offset](const auto& value) {
            memcpy(out + offset, &value, sizeof(value));
            offset += sizeof(value);
        };

        write(static_cast<uint16_t>(type));
        write(tid);
        write(message_id);
        write(nano_time);
        write(end_nano_time);
        write(cpu_time);
        write(end_cpu_time);
        write(allocated_objects);
        write(allocated_bytes);
        write(major_faults);
        write(voluntary_csw);
        write(involuntary_csw);
        write(wakeup_tid);
        write(arg_length);

        if (arg_length > 0) {
            memcpy(out + offset, arg, arg_length);
            offset += arg_length;
        }

        write(stack.saved_depth);
        write(stack.actual_depth);

        for (int i = 0; i < stack.saved_depth; ++i) {
            write(stack.frames[i].method_ptr);
        }

        return offset;
    }
};

// 获取记录时间的函数 (用于环形缓冲区排序)
inline uint64_t GetRecordTime(const SampleRecord& record) {
    return record.end_nano_time > 0 ? record.end_nano_time : record.nano_time;
}

} // namespace atrace

