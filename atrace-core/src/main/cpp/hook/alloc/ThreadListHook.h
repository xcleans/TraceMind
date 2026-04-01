/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * ThreadList 和 Heap 指针获取
 */
#pragma once

#include <functional>

namespace atrace {
namespace alloc {

// ThreadList 获取回调
using OnThreadListReady = std::function<void(void* thread_list)>;

/**
 * 初始化 ThreadList Hook
 * 
 * Hook Thread::Init 和 Heap::AddFinalizerReference 来获取
 * ThreadList 和 Heap 指针
 * 
 * @return 是否成功
 */
bool InitThreadListHook();

/**
 * 设置 ThreadList 就绪回调
 * 
 * 当同时获取到 ThreadList 和 Heap 时调用
 */
void SetThreadListReadyCallback(OnThreadListReady callback);

/**
 * 销毁 ThreadList Hook
 */
void DestroyThreadListHook();

} // namespace alloc
} // namespace atrace

