/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Checkpoint 机制
 * 用于在所有线程上执行回调，重置分配入口点
 */
#pragma once

#include "AllocCommon.h"

namespace atrace {
namespace alloc {

/**
 * 初始化 Checkpoint 机制
 * 
 * @param libart_handle libart.so 的 dlopen 句柄
 * @return 是否成功
 */
bool InitCheckpoint(void* libart_handle);

/**
 * 在所有线程上运行 Checkpoint
 * 
 * @param closure Closure 回调对象
 * @return 运行的线程数，0 表示失败
 */
size_t RunCheckpoint(Closure* closure);

/**
 * 设置 QuickAllocEntryPoints 是否已检测
 */
bool SetQuickAllocEntryPointsInstrumented(bool instrumented);

/**
 * 获取 Thread::ResetQuickAllocEntryPointsForThread 函数指针
 */
void* GetResetQuickAllocEntryPointsFunc();

/**
 * 是否使用带 bool 参数的版本
 */
bool UseResetQuickAllocEntryPointsWithBool();

} // namespace alloc
} // namespace atrace

