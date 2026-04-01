/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "Checkpoint.h"
#include "utils/dl_utils.h"

#define ATRACE_LOG_TAG "Checkpoint"

#include "utils/atrace_log.h"

namespace atrace {
    namespace alloc {

// 函数指针
        static RunCheckpointFunc g_run_checkpoint_func = nullptr;
        static RunCheckpointFunc15 g_run_checkpoint_15_func = nullptr;
        static RunCheckpointFunc16 g_run_checkpoint_16_func = nullptr;
        static void *g_reset_quick_alloc_func = nullptr;
        // SetQuickAllocEntryPointsInstrumented 在 Android 12+ (API 31+) 已移除，可选
        static SetVoidBool g_set_quick_alloc_instrumented_func = nullptr;
        static bool g_use_reset_with_bool = false;

        bool InitCheckpoint(void *libart_handle) {
            if (!libart_handle) return false;

            // 1. ThreadList::RunCheckpoint
            g_run_checkpoint_func = reinterpret_cast<RunCheckpointFunc>(
                    dl_sym(libart_handle, THREAD_LIST_RUN_CHECKPOINT));

            if (!g_run_checkpoint_func) {
                // 尝试 Android 15+ 版本
                g_run_checkpoint_15_func = reinterpret_cast<RunCheckpointFunc15>(
                        dl_sym(libart_handle, THREAD_LIST_RUN_CHECKPOINT_15));
            }

            if (!g_run_checkpoint_func && !g_run_checkpoint_15_func) {
                // 尝试 Android 16+ 版本
                g_run_checkpoint_16_func = reinterpret_cast<RunCheckpointFunc16>(
                        dl_sym(libart_handle, THREAD_LIST_RUN_CHECKPOINT_16));
            }

            if (!g_run_checkpoint_func && !g_run_checkpoint_15_func && !g_run_checkpoint_16_func) {
                ALOGE("Cannot find ThreadList::RunCheckpoint");
                return false;
            }

            // 2. Thread::ResetQuickAllocEntryPointsForThread
            g_reset_quick_alloc_func = dl_sym(libart_handle, THREAD_RESET_QUICK_ALLOC_ENTRY_POINTS);

            if (!g_reset_quick_alloc_func) {
                g_reset_quick_alloc_func = dl_sym(libart_handle, THREAD_RESET_QUICK_ALLOC_ENTRY_POINTS_BOOL);
                g_use_reset_with_bool = true;
            }

            if (!g_reset_quick_alloc_func) {
                g_reset_quick_alloc_func = dl_sym(libart_handle, THREAD_RESET_QUICK_ALLOC_ENTRY_POINTS_16);
            }

            if (!g_reset_quick_alloc_func) {
                ALOGE("Cannot find Thread::ResetQuickAllocEntryPointsForThread");
                return false;
            }

            // 3. SetQuickAllocEntryPointsInstrumented（Android 12+ 已移除，可选）
            g_set_quick_alloc_instrumented_func = reinterpret_cast<SetVoidBool>(
                    dl_sym(libart_handle, SET_QUICK_ALLOC_ENTRY_POINTS_INSTRUMENTED));

            if (!g_set_quick_alloc_instrumented_func) {
                // Android 12+ 中该符号被移除，由 ART 内部在 SetAllocationListener 时自行管理
                // entry points，无需我们手动调用，降级为 warning 继续初始化
                ALOGW("SetQuickAllocEntryPointsInstrumented not found (Android 12+?), "
                      "relying on ART internal entry point update");
            }

            ALOGI("Checkpoint initialized (has_set_instrumented=%d)",
                  g_set_quick_alloc_instrumented_func != nullptr);
            return true;
        }

        size_t RunCheckpoint(Closure *closure) {
            auto &ctx = GetAllocContext();

            if (!ctx.thread_list) {
                ALOGE("ThreadList not available");
                return 0;
            }

            if (g_run_checkpoint_func) {
                return g_run_checkpoint_func(ctx.thread_list, closure, nullptr);
            } else if (g_run_checkpoint_15_func) {
                return g_run_checkpoint_15_func(ctx.thread_list, closure, nullptr, false);
            } else if (g_run_checkpoint_16_func) {
                return g_run_checkpoint_16_func(ctx.thread_list, closure, false, false);
            }

            return 0;
        }

        bool SetQuickAllocEntryPointsInstrumented(bool instrumented) {
            if (g_set_quick_alloc_instrumented_func) {
                g_set_quick_alloc_instrumented_func(instrumented);
                return true;
            }
            // 符号不存在（Android 12+）：返回 false，调用方应 fallthrough 到 ART 原始实现
            return false;
        }

        void *GetResetQuickAllocEntryPointsFunc() {
            return g_reset_quick_alloc_func;
        }

        bool UseResetQuickAllocEntryPointsWithBool() {
            return g_use_reset_with_bool;
        }

    } // namespace alloc
} // namespace atrace

