/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Java Object Allocation 公共定义
 */
#pragma once

#include <cstdint>
#include <string>

namespace atrace {
namespace alloc {

// ===== ART 符号名 =====

// Heap::SetAllocationListener
#define HEAP_SET_ALLOC_LISTENER \
    "_ZN3art2gc4Heap21SetAllocationListenerEPNS0_18AllocationListenerE"

// Heap::RemoveAllocationListener  
#define HEAP_REMOVE_ALLOC_LISTENER \
    "_ZN3art2gc4Heap24RemoveAllocationListenerEv"

// Heap::AddFinalizerReference (用于获取 Heap 指针)
#define HEAP_ADD_FINALIZER_REFERENCE \
    "_ZN3art2gc4Heap21AddFinalizerReferenceEPNS_6ThreadEPNS_6ObjPtrINS_6mirror6ObjectEEE"

// Thread::Init (用于获取 ThreadList 指针)
#define THREAD_INIT \
    "_ZN3art6Thread4InitEPNS_10ThreadListEPNS_9JavaVMExtEPNS_9JNIEnvExtE"

// ThreadList::RunCheckpoint
#define THREAD_LIST_RUN_CHECKPOINT \
    "_ZN3art10ThreadList13RunCheckpointEPNS_7ClosureES2_"

// ThreadList::RunCheckpoint (Android 15+)
#define THREAD_LIST_RUN_CHECKPOINT_15 \
    "_ZN3art10ThreadList13RunCheckpointEPNS_7ClosureES2_b"

//ThreadList::RunCheckpoint (Android 16+ 小米)

#define THREAD_LIST_RUN_CHECKPOINT_16 \
    "_ZN3art10ThreadList13RunCheckpointEPNS_7ClosureES2_bb"


// Thread::ResetQuickAllocEntryPointsForThread
#define THREAD_RESET_QUICK_ALLOC_ENTRY_POINTS \
    "_ZN3art6Thread35ResetQuickAllocEntryPointsForThreadEv"

// Thread::ResetQuickAllocEntryPointsForThread(bool)
#define THREAD_RESET_QUICK_ALLOC_ENTRY_POINTS_BOOL \
    "_ZN3art6Thread35ResetQuickAllocEntryPointsForThreadEb"

#define THREAD_RESET_QUICK_ALLOC_ENTRY_POINTS_16 \
    "_ZN3art6Thread35ResetQuickAllocEntryPointsForThreadEv"


// SetQuickAllocEntryPointsInstrumented — removed on Android 12+ (API 31+)
#define SET_QUICK_ALLOC_ENTRY_POINTS_INSTRUMENTED \
    "_ZN3art36SetQuickAllocEntryPointsInstrumentedEb"

// Instrumentation::SetEntrypointsInstrumented — may not exist on Android 12+
#define INSTRUMENTATION_SET_ENTRYPOINTS_INSTRUMENTED \
    "_ZN3art15instrumentation15Instrumentation26SetEntrypointsInstrumentedEb"

// ===== 函数类型定义 =====

// void (*)(void*)
using CallVoid = void (*)(void*);

// void (*)(void*, bool)
using CallVoidBool = void (*)(void*, bool);

// void (*)(void*, void*)
using SetPtr = void (*)(void*, void*);

// bool (*)(bool)
using SetBool = bool (*)(bool);

// void (*)(bool)  — SetQuickAllocEntryPointsInstrumented 实际返回 void
using SetVoidBool = void (*)(bool);

// size_t (*)(void*, void*, void*)
using RunCheckpointFunc = size_t (*)(void*, void*, void*);

// size_t (*)(void*, void*, void*, bool)  
using RunCheckpointFunc15 = size_t (*)(void*, void*, void*, bool);

//RunCheckpoint(Closure* checkpoint_function,
//                                 Closure* callback,
//                                 bool allow_lock_checking,
//                                 bool acquire_mutator_lock)
using RunCheckpointFunc16 = size_t (*)(void*, void*, bool, bool);

// ===== Closure 基类 =====

/**
 * ART Closure 基类
 * 用于 checkpoint 回调
 */
class Closure {
public:
    virtual ~Closure() = default;
    virtual void Run(void* thread) = 0;
};

// ===== 全局上下文 =====

struct AllocContext {
    void* heap = nullptr;           // Heap* 指针
    void* thread_list = nullptr;    // ThreadList* 指针
    bool initialized = false;
};

// 全局上下文
AllocContext& GetAllocContext();

} // namespace alloc
} // namespace atrace

