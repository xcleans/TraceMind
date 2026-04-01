/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 通过 per-method entry_point_from_quick_compiled_code_ 替换实现动态方法拦截。
 *
 * 不使用 ShadowHook inline hook —— 手写汇编函数（art_quick_invoke_stub）和
 * 带 PAC 的 C++ 函数（ArtMethod::Invoke）在 ShadowHook 指令重定位后均会崩溃
 * （SIGSEGV: 跳转到 DEX 字节码地址）。
 *
 * 替代方案：直接修改目标 ArtMethod 的 entry_point，指向 per-method stub
 * 或共享 trampoline。Per-method stub 将 orig_entry / name / handler 指针
 * 嵌入数据区，热路径零锁、零 HashMap 查找；共享 trampoline 仅做回退。
 */
#include "ArtMethodInstrumentation.h"
#include "hook/JNIMethodHook.h"
#include "core/TraceEngine.h"
#include "core/SymbolResolver.h"
#include "core/StackSampler.h"
#include "include/atrace.h"
#include "utils/atrace_log.h"

#include <android/api-level.h>
#include <atomic>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <shared_mutex>
#include <string>
#include <sys/mman.h>
#include <unordered_map>
#include <vector>

#define ATRACE_LOG_TAG "ArtMethodInstr"

namespace atrace {

    bool ArtMethodInstrumentation::installed_ = false;

    namespace {

        static JavaVM *g_java_vm = nullptr;

        // entry_point_from_quick_compiled_code_ 在 ArtMethod (void**) 中的索引
        static int g_quick_code_index = -1;

        static thread_local int g_in_hook = 0;

// ── 已 hook 的方法信息 ──────────────────────────────────────────────────────
        struct HookedMethodInfo {
            void *orig_entry;
            const char *cached_name;
            uint16_t orig_hotness;
            bool had_compile_dont_bother;  // hook 前是否已有 kAccCompileDontBother
            uint32_t saved_jit_hint_bits;  // P1/P2：清除前为 1 的位，unhook 时 fetch_or 还原
            void *stub;                    // per-method stub 地址，nullptr 时走共享 trampoline
        };

        // shared_mutex: OnQuickEntry 只需读锁（仅共享 trampoline 回退路径），hook/unhook 写锁
        static std::unordered_map<void *, HookedMethodInfo> g_hooked_methods;
        static std::shared_mutex g_hook_mutex;

// ── Per-method stub 分配器 ──────────────────────────────────────────────────
        static bool g_stubs_available = false;

        class StubAllocator {
            static constexpr size_t kPageSize = 4096;
            std::vector<void *> pages_;
            size_t stub_size_ = 0;
            size_t page_offset_ = 0;
        public:
            void Init(size_t stub_size) {
                stub_size_ = (stub_size + 15u) & ~15u;
            }

            void *Allocate() {
                if (stub_size_ == 0) return nullptr;
                if (pages_.empty() || page_offset_ + stub_size_ > kPageSize) {
                    void *page = mmap(nullptr, kPageSize,
                            PROT_READ | PROT_WRITE | PROT_EXEC,
                            MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
                    if (page == MAP_FAILED) return nullptr;
                    pages_.push_back(page);
                    page_offset_ = 0;
                }
                void *slot = static_cast<char *>(pages_.back()) + page_offset_;
                page_offset_ += stub_size_;
                return slot;
            }

            void Cleanup() {
                for (void *p: pages_) munmap(p, kPageSize);
                pages_.clear();
                page_offset_ = 0;
            }
        };

        static StubAllocator g_stub_allocator;

// ── WatchList（模式暂存）──────────────────────────────────────────────────────
        static std::vector<std::string> g_watched_entries;
        static std::mutex g_watch_mutex;
        static std::atomic<int> g_watch_count{0};

// ── ArtMethod 布局 ──────────────────────────────────────────────────────────
// Android 8-15 (40B arm64):              Android 16+ (32B arm64):
//   0: declaring_class_   4B               0: declaring_class_   4B
//   4: access_flags_      4B               4: access_flags_      4B (atomic)
//   8: dex_code_item_off  4B               8: dex_method_index_  4B
//  12: dex_method_index_  4B              12: method_index_      2B
//  16: method_index_      2B              14: hotness_count_     2B
//  18: hotness_count_     2B              16: data_              8B (ptr)
//  20: [padding]          4B              24: entry_point_       8B (ptr)
//  24: data_              8B (ptr)
//  32: entry_point_       8B (ptr)
//
// Android 16 移除了 dex_code_item_offset_，所有后续字段前移 4 字节。
// hotness_count_ 的偏移通过 data_ 的字节偏移反推（动态探测，无硬编码版本号）。
// data_ / entry_point_ 的偏移通过 JNI 动态发现，不受影响。

        static constexpr int kAccessFlagsByteOffset = 4; // 所有版本一致
        static constexpr uint32_t kAccNative = 0x00000100;
        static constexpr uint32_t kAccCompileDontBother = 0x02000000;
        static constexpr uint32_t kAccPreCompiled = 0x00800000;
        // P2：单实现虚调用去虚化（JIT 可能内联直达实现，绕过 entry_point）
        static constexpr uint32_t kAccSingleImplementation = 0x08000000;
        // P1：Android Q+ 解释器「快速路径」缓存，可能跳过 entry_point 刷新
        static constexpr uint32_t kAccFastInterpreterToInterpreterInvoke = 0x40000000;

        static int g_device_api_level = -1;

        static bool g_access_flags_verified = false;
        static int g_hotness_byte_offset = -1; // 动态探测，-1 表示未知/禁用
        static void *g_interpreter_bridge = nullptr;

        static bool VerifyAccessFlagsOffset(JNIEnv *env) {
            void **sample = jni_hook::ResolveArtMethod(
                    env, "com/aspect/atrace/core/JNIHookHelper",
                    "nativePlaceholder", "()V", true);
            if (!sample) return false;

            auto *bytes = reinterpret_cast<uint8_t *>(sample);
            uint32_t flags;
            memcpy(&flags, bytes + kAccessFlagsByteOffset, sizeof(flags));

            if (!(flags & kAccNative)) {
                ALOGW("ArtMethodInstr: access_flags verify failed: 0x%08x at offset %d",
                        flags, kAccessFlagsByteOffset);
                return false;
            }

            g_access_flags_verified = true;
            ALOGI("ArtMethodInstr: access_flags verified at offset %d (flags=0x%08x)",
                    kAccessFlagsByteOffset, flags);

            // 验证 kAccCompileDontBother 原子读写一致性
            auto *atomic_flags = reinterpret_cast<std::atomic<uint32_t> *>(
                    bytes + kAccessFlagsByteOffset);
            uint32_t before = atomic_flags->load(std::memory_order_acquire);
            atomic_flags->fetch_or(kAccCompileDontBother, std::memory_order_release);
            uint32_t after = atomic_flags->load(std::memory_order_acquire);
            atomic_flags->store(before, std::memory_order_release); // 还原

            if ((after & kAccCompileDontBother) != 0) {
                ALOGI("ArtMethodInstr: kAccCompileDontBother (0x%08x) "
                      "atomic set/clear verified (before=0x%08x, after=0x%08x)",
                        kAccCompileDontBother, before, after);
            } else {
                ALOGW("ArtMethodInstr: kAccCompileDontBother atomic verify failed "
                      "(before=0x%08x, after=0x%08x)", before, after);
            }
            return true;
        }

        /**
         * 通过已动态发现的 g_quick_code_index 反推 ArtMethod 布局版本，
         * 确定 hotness_count_ 的字节偏移。
         *
         * 推导链：
         *   data_ 的 void** index = g_quick_code_index - 1
         *   data_ 字节偏移 = index * sizeof(void*)
         *   hotness_count_ 紧邻 data_ 之前（可能有对齐 padding）：
         *     data_ 在 24 → Android 8-15 → hotness 在 18
         *     data_ 在 16 → Android 16+  → hotness 在 14
         */
        static void DetectHotnessOffset() {
            if (g_quick_code_index < 2) {
                g_hotness_byte_offset = -1;
                return;
            }
            int data_byte_offset =
                    (g_quick_code_index - 1) * static_cast<int>(sizeof(void *));

            if (data_byte_offset == 24) {
                g_hotness_byte_offset = 18;  // Android 8-15
            } else if (data_byte_offset == 16) {
                g_hotness_byte_offset = 14;  // Android 16+
            } else {
                g_hotness_byte_offset = -1;  // 未知布局，禁用
            }

            ALOGI("ArtMethodInstr: layout detect — data_offset=%d, "
                  "hotness_offset=%d, art_method_size=%d",
                    data_byte_offset, g_hotness_byte_offset,
                    (g_quick_code_index + 1) * static_cast<int>(sizeof(void *)));
        }

        /**
         * 通过探测验证 hotness_count_ 偏移的正确性。
         * 对一个已知的非 native 方法读取候选偏移处的 uint16_t，
         * hotness 值应该在合理范围内（0 ~ 几千）。
         */
        static bool VerifyHotnessOffset(JNIEnv *env) {
            if (g_hotness_byte_offset < 0) return false;

            void **sample = jni_hook::ResolveArtMethod(
                    env, "com/aspect/atrace/core/JNIHookHelper",
                    "nativePlaceholder", "()V", true);
            if (!sample) return false;

            auto *bytes = reinterpret_cast<uint8_t *>(sample);
            uint16_t val;
            memcpy(&val, bytes + g_hotness_byte_offset, sizeof(val));

            // native 方法的 hotness_count_ 与 imt_index_ 共用联合体，
            // 对 native 方法该值通常为 0 或很小
            if (val <= 10000) {
                ALOGI("ArtMethodInstr: hotness_offset %d verified (val=%u)",
                        g_hotness_byte_offset, val);
                return true;
            }
            ALOGW("ArtMethodInstr: hotness_offset %d suspect (val=%u), disabling",
                    g_hotness_byte_offset, val);
            g_hotness_byte_offset = -1;
            return false;
        }

        static uint16_t ReadHotness(void **art_method) {
            if (g_hotness_byte_offset < 0) return 0;
            auto *bytes = reinterpret_cast<uint8_t *>(art_method);
            auto *hotness = reinterpret_cast<std::atomic<uint16_t> *>(
                    bytes + g_hotness_byte_offset);
            return hotness->load(std::memory_order_relaxed);
        }

        static void ClearHotness(void **art_method) {
            if (g_hotness_byte_offset < 0) return;
            auto *bytes = reinterpret_cast<uint8_t *>(art_method);
            auto *hotness = reinterpret_cast<std::atomic<uint16_t> *>(
                    bytes + g_hotness_byte_offset);
            hotness->store(0, std::memory_order_release);
        }

        static void RestoreHotness(void **art_method, uint16_t value) {
            if (g_hotness_byte_offset < 0) return;
            auto *bytes = reinterpret_cast<uint8_t *>(art_method);
            auto *hotness = reinterpret_cast<std::atomic<uint16_t> *>(
                    bytes + g_hotness_byte_offset);
            hotness->store(value, std::memory_order_release);
        }

// ── access_flags_ 原子操作（kAccCompileDontBother） ─────────────────────────
        static std::atomic<uint32_t> *GetAccessFlagsAtomic(void **art_method) {
            auto *bytes = reinterpret_cast<uint8_t *>(art_method);
            return reinterpret_cast<std::atomic<uint32_t> *>(
                    bytes + kAccessFlagsByteOffset);
        }

        static uint32_t ReadAccessFlags(void **art_method) {
            return GetAccessFlagsAtomic(art_method)->load(std::memory_order_acquire);
        }

        static bool HasCompileDontBother(void **art_method) {
            return (ReadAccessFlags(art_method) & kAccCompileDontBother) != 0;
        }

        /**
         * 设置 kAccCompileDontBother，同时清除 kAccPreCompiled。
         * kAccPreCompiled 与 kAccCompileDontBother 组合表示"JIT 预编译"，
         * 我们需要的是"禁止编译"，必须单独设 kAccCompileDontBother。
         */
        static void SetCompileDontBother(void **art_method) {
            auto *flags = GetAccessFlagsAtomic(art_method);
            flags->fetch_and(~kAccPreCompiled, std::memory_order_relaxed);
            flags->fetch_or(kAccCompileDontBother, std::memory_order_release);
        }

        static void ClearCompileDontBother(void **art_method) {
            auto *flags = GetAccessFlagsAtomic(art_method);
            flags->fetch_and(~kAccCompileDontBother, std::memory_order_release);
        }

        /**
         * Hook 时需清除的 access_flags 掩码（与 Pine / SandHook 对齐）。
         * - P2：始终清除 kAccSingleImplementation（位为 0 时无影响）。
         * - P1：API 29+ 清除 kAccFastInterpreterToInterpreterInvoke。
         */
        static uint32_t HookJitHintClearMask() {
            int api = g_device_api_level;
            if (api < 0) api = android_get_device_api_level();
            uint32_t mask = kAccSingleImplementation;
            if (api >= __ANDROID_API_Q__) {
                mask |= kAccFastInterpreterToInterpreterInvoke;
            }
            return mask;
        }

        /**
         * 清除 P1/P2 位；返回 hook 前这些位中为 1 的部分，供 unhook 时还原。
         */
        static uint32_t ClearJitHookAccessHints(void **art_method) {
            const uint32_t mask = HookJitHintClearMask();
            if (mask == 0) return 0;
            uint32_t before = ReadAccessFlags(art_method);
            uint32_t had = before & mask;
            if (had != 0) {
                GetAccessFlagsAtomic(art_method)->fetch_and(~mask, std::memory_order_release);
            }
            return had;
        }

        static void RestoreJitHookAccessHints(void **art_method, uint32_t saved_bits) {
            if (saved_bits == 0) return;
            GetAccessFlagsAtomic(art_method)->fetch_or(saved_bits, std::memory_order_release);
        }

// ── Per-thread exit tracing ──────────────────────────────────────────────────
        struct SavedFrame {
            void *real_lr;
            const char *method_name;
        };

        static constexpr int kMaxFrameDepth = 128;

        struct ExitFrameStack {
            SavedFrame frames[kMaxFrameDepth];
            int depth = 0;

            bool Push(void *lr, const char *name) {
                if (depth >= kMaxFrameDepth) return false;
                frames[depth++] = {lr, name};
                return true;
            }

            SavedFrame Pop() {
                if (depth <= 0) return {nullptr, nullptr};
                return frames[--depth];
            }
        };

        static thread_local ExitFrameStack t_exit_stack;

// ── Bridge / Trampoline 识别 ─────────────────────────────────────────────────
// 用于 hook 前和运行时检查 entry_point 是否指向 ART 内部 bridge/trampoline。
// 必须在 OnQuickEntry / OnQuickEntryFast 之前定义。
//
// Android 16+：大部分方法的 entry_point 指向 nterp（ExecuteNterpImpl），
// 这些方法可以 hook（替换 entry_point），但不能做 exit tracing（LR 替换不安全）。
// 因此需区分"是否可 hook"与"是否可做 exit tracing"。

        static uintptr_t s_libart_base = 0;
        static uintptr_t s_libart_end = 0;

        static void *s_generic_jni_tramp = nullptr;
        static void *s_resolution_tramp = nullptr;
        static void *s_nterp_impl = nullptr;
        static void *s_nterp_with_clinit = nullptr;
        static bool s_bridges_resolved = false;

        enum class EntryType {
            kNull,
            kInterpreterBridge,
            kGenericJniTrampoline,
            kResolutionTrampoline,
            kNterp,
            kLibartOther,
            kCompiledCode,
            kOurTrampoline,
        };

        static const char *EntryTypeName(EntryType t) {
            switch (t) {
                case EntryType::kNull:
                    return "null";
                case EntryType::kInterpreterBridge:
                    return "interpreter_bridge";
                case EntryType::kGenericJniTrampoline:
                    return "generic_jni_trampoline";
                case EntryType::kResolutionTrampoline:
                    return "resolution_trampoline";
                case EntryType::kNterp:
                    return "nterp";
                case EntryType::kLibartOther:
                    return "libart_other";
                case EntryType::kCompiledCode:
                    return "compiled_code";
                case EntryType::kOurTrampoline:
                    return "our_trampoline";
            }
            return "unknown";
        }

        static void ResolveLibartRange() {
            if (s_libart_base) return;

            // 优先使用 /proc/self/maps 获取精确的 libart.so 地址范围
            FILE *maps = fopen("/proc/self/maps", "r");
            if (maps) {
                char line[512];
                uintptr_t min_addr = UINTPTR_MAX, max_addr = 0;
                while (fgets(line, sizeof(line), maps)) {
                    if (!strstr(line, "libart.so") && !strstr(line, "libart-"))
                        continue;
                    char *dash = strchr(line, '-');
                    if (!dash) continue;
                    uintptr_t start = strtoull(line, nullptr, 16);
                    uintptr_t end = strtoull(dash + 1, nullptr, 16);
                    if (start < min_addr) min_addr = start;
                    if (end > max_addr) max_addr = end;
                }
                fclose(maps);
                if (min_addr < max_addr) {
                    s_libart_base = min_addr;
                    s_libart_end = max_addr;
                    ALOGI("ArtMethodInstr: libart range from /proc/self/maps: "
                          "[%p, %p) size=%zuKB",
                            reinterpret_cast<void *>(min_addr),
                            reinterpret_cast<void *>(max_addr),
                            (max_addr - min_addr) / 1024);
                    return;
                }
            }

            // Fallback: dladdr + 估算
            Dl_info info;
            void *sym = SymbolResolver::Instance().FindSymbol(
                    "art_quick_to_interpreter_bridge");
            if (!sym)
                sym = SymbolResolver::Instance().FindSymbol(
                        "art_quick_generic_jni_trampoline");
            if (!sym)
                sym = reinterpret_cast<void *>(
                        SymbolResolver::Instance().GetPrettyMethod());
            if (sym && dladdr(sym, &info) && info.dli_fbase) {
                s_libart_base = reinterpret_cast<uintptr_t>(info.dli_fbase);
                s_libart_end = s_libart_base + 32u * 1024 * 1024;
                ALOGW("ArtMethodInstr: libart range via dladdr fallback: "
                      "[%p, %p) (estimated 32MB)",
                        reinterpret_cast<void *>(s_libart_base),
                        reinterpret_cast<void *>(s_libart_end));
            }
        }

        static void ResolveBridgeSymbols() {
            if (s_bridges_resolved) return;
            auto &resolver = SymbolResolver::Instance();
            s_generic_jni_tramp = resolver.FindSymbol("art_quick_generic_jni_trampoline");
            s_resolution_tramp = resolver.FindSymbol("art_quick_resolution_trampoline");
            s_nterp_impl = resolver.FindSymbol("ExecuteNterpImpl");
            s_nterp_with_clinit = resolver.FindSymbol("ExecuteNterpWithClinitImpl");
            if (!s_nterp_with_clinit) {
                s_nterp_with_clinit = resolver.FindSymbol("NterpWithClinitImpl");
            }
            ResolveLibartRange();
            s_bridges_resolved = true;
            ALOGI("ArtMethodInstr: bridge symbols — interp_bridge=%p, generic_jni=%p, "
                  "resolution=%p, nterp=%p, nterp_clinit=%p",
                    g_interpreter_bridge, s_generic_jni_tramp, s_resolution_tramp,
                    s_nterp_impl, s_nterp_with_clinit);
        }

        extern "C" void atrace_quick_entry_trampoline();

        static EntryType ClassifyEntryPoint(void *entry) {
            if (!entry) return EntryType::kNull;

            void *shared_tramp = reinterpret_cast<void *>(atrace_quick_entry_trampoline);
            if (entry == shared_tramp) return EntryType::kOurTrampoline;

            if (g_interpreter_bridge && entry == g_interpreter_bridge)
                return EntryType::kInterpreterBridge;
            if (s_generic_jni_tramp && entry == s_generic_jni_tramp)
                return EntryType::kGenericJniTrampoline;
            if (s_resolution_tramp && entry == s_resolution_tramp)
                return EntryType::kResolutionTrampoline;
            if (s_nterp_impl && entry == s_nterp_impl)
                return EntryType::kNterp;
            if (s_nterp_with_clinit && entry == s_nterp_with_clinit)
                return EntryType::kNterp;

            if (s_libart_base) {
                auto addr = reinterpret_cast<uintptr_t>(entry);
                if (addr >= s_libart_base && addr < s_libart_end)
                    return EntryType::kLibartOther;
            }
            return EntryType::kCompiledCode;
        }

        /**
         * exit tracing 决策：LR 替换不安全时返回 true。
         *
         * 已知不安全（使用 callee-save frame / DoGetCalleeSaveMethodCaller）：
         *   - art_quick_to_interpreter_bridge
         *   - art_quick_generic_jni_trampoline
         *   - art_quick_resolution_trampoline
         *   - null
         *
         * kLibartOther（libart 内未匹配到已知符号的地址）分版本处理：
         *   - API 36+（Android 16）：nterp 是默认执行模式，libart_other
         *     几乎都是 nterp 变体（符号名变化），exit tracing 安全。
         *   - API < 36（Android 13-15）：libart_other 可能是 interpreter bridge
         *     变体（PAC 签名 / 偏移导致符号不匹配），LR 替换会
         *     在 DoGetCalleeSaveMethodCaller 中 SIGSEGV。
         */
        static bool ShouldSkipExitTracing(void *entry) {
            if (!s_bridges_resolved) ResolveBridgeSymbols();
            EntryType type = ClassifyEntryPoint(entry);
            switch (type) {
                case EntryType::kNull:
                case EntryType::kInterpreterBridge:
                case EntryType::kGenericJniTrampoline:
                case EntryType::kResolutionTrampoline:
                    return true;
                case EntryType::kLibartOther:
                    return g_device_api_level < 36;
                default:
                    return false;
            }
        }

        /**
         * 是否为不可 hook 的 entry point。
         * nterp / interpreter_bridge / generic_jni 等均可 hook，
         * 仅 null / resolution_trampoline / 已是我们的 trampoline 不可 hook。
         */
        static bool IsUnhookableEntry(void *entry) {
            EntryType type = ClassifyEntryPoint(entry);
            switch (type) {
                case EntryType::kNull:
                case EntryType::kResolutionTrampoline:
                case EntryType::kOurTrampoline:
                    return true;
                default:
                    return false;
            }
        }

// ── ARM64 Trampoline (entry + exit) ─────────────────────────────────────────
// Quick ABI: x0=ArtMethod*, x1-x7=args, d0-d7=float args
//
// Entry：保存参数 → OnQuickEntry(x0=ArtMethod*, x1=caller_lr)
//   返回 x0=orig_entry, x1=exit_trampoline（0 表示不追踪退出）
//   若 x1!=0，LR 替换为 exit_trampoline → 方法返回时经过 exit 拦截
//
// Exit：保存返回值 → OnQuickExit() → 返回 real_lr → 跳转回真正调用者

        struct EntryResult {
            void *orig_entry;
            void *exit_trampoline;
        };

        extern "C" EntryResult OnQuickEntry(void *art_method, void *caller_lr);
        extern "C" void *OnQuickExit();

#if defined(__aarch64__)
        __attribute__((naked))
        extern "C" void atrace_quick_entry_trampoline() {
            __asm__ __volatile__(
                    "stp x29, x30, [sp, #-0xA0]!\n"
                    "mov x29, sp\n"
                    "stp x0,  x1,  [sp, #0x10]\n"
                    "stp x2,  x3,  [sp, #0x20]\n"
                    "stp x4,  x5,  [sp, #0x30]\n"
                    "stp x6,  x7,  [sp, #0x40]\n"
                    "str x8,        [sp, #0x50]\n"
                    "stp d0,  d1,  [sp, #0x60]\n"
                    "stp d2,  d3,  [sp, #0x70]\n"
                    "stp d4,  d5,  [sp, #0x80]\n"
                    "stp d6,  d7,  [sp, #0x90]\n"
                    "ldr x1,  [sp, #0x08]\n"        // x1 = caller LR (saved x30)
                    "bl  OnQuickEntry\n"              // → x0=orig, x1=exit_tramp
                    "mov x16, x0\n"
                    "mov x17, x1\n"
                    "ldp d6,  d7,  [sp, #0x90]\n"
                    "ldp d4,  d5,  [sp, #0x80]\n"
                    "ldp d2,  d3,  [sp, #0x70]\n"
                    "ldp d0,  d1,  [sp, #0x60]\n"
                    "ldr x8,        [sp, #0x50]\n"
                    "ldp x6,  x7,  [sp, #0x40]\n"
                    "ldp x4,  x5,  [sp, #0x30]\n"
                    "ldp x2,  x3,  [sp, #0x20]\n"
                    "ldp x0,  x1,  [sp, #0x10]\n"
                    "ldp x29, x30, [sp], #0xA0\n"
                    "cbz x17, 1f\n"
                    "mov x30, x17\n"                  // replace LR → exit trampoline
                    "1:\n"
                    "br  x16\n"
                    );
        }

        __attribute__((naked))
        extern "C" void atrace_quick_exit_trampoline() {
            __asm__ __volatile__(
                    "sub sp,  sp,  #0x20\n"
                    "stp x0,  x1,  [sp, #0x00]\n"
                    "stp d0,  d1,  [sp, #0x10]\n"
                    "bl  OnQuickExit\n"
                    "mov x16, x0\n"
                    "ldp d0,  d1,  [sp, #0x10]\n"
                    "ldp x0,  x1,  [sp, #0x00]\n"
                    "add sp,  sp,  #0x20\n"
                    "br  x16\n"
                    );
        }
#elif defined(__arm__)
        __attribute__((naked))
        extern "C" void atrace_quick_entry_trampoline() {
            __asm__ __volatile__(
                "push {r0-r3, r9, lr}\n"
                "vpush {d0-d7}\n"
                "mov  r1, lr\n"
                "bl   OnQuickEntry\n"
                "mov  r12, r0\n"
                "vpop {d0-d7}\n"
                "pop  {r0-r3, r9, lr}\n"
                "bx   r12\n"
            );
        }

        __attribute__((naked))
        extern "C" void atrace_quick_exit_trampoline() {
            __asm__ __volatile__(
                "push {r0-r1}\n"
                "vpush {d0-d1}\n"
                "bl   OnQuickExit\n"
                "mov  r12, r0\n"
                "vpop {d0-d1}\n"
                "pop  {r0-r1}\n"
                "bx   r12\n"
            );
        }
#else
        extern "C" void atrace_quick_entry_trampoline() {}
        extern "C" void atrace_quick_exit_trampoline() {}
#endif

// ── Per-method stub template ────────────────────────────────────────────────
// 每个被 hook 方法拥有独立 stub，orig_entry / name / 函数指针
// 嵌入 stub 数据区，热路径零锁、零 HashMap 查找。
//
// stub layout (ARM64):  128 bytes code + 24 bytes data = 152 bytes
// data[0]: orig_entry   data[1]: name   data[2]: &OnQuickEntryFast
//
// adr 是 PC-relative，模板整体 memcpy 后偏移仍正确；
// blr 间接调用，无需 patch 分支偏移。

        extern "C" void *OnQuickEntryFast(void *art_method, void *caller_lr,
                void *orig_entry, const char *name);

#if defined(__aarch64__)
        // 32 条 ARM64 指令 = 128 字节 code, 紧跟 3×8 = 24 字节 data
        static constexpr size_t kStubCodeSize = 32 * 4;  // 128
        static constexpr size_t kStubDataOffset = kStubCodeSize; // 128
        static constexpr size_t kStubDataSize = 3 * sizeof(void *); // 24
        static constexpr size_t kStubTotalSize = kStubCodeSize + kStubDataSize; // 152

        __attribute__((naked, used))
        static void atrace_stub_template() {
            __asm__ __volatile__(
                // ── save frame + Quick ABI regs (11 insns) ──
                    "stp x29, x30, [sp, #-0xA0]!\n"        // 1
                    "mov x29, sp\n"                          // 2
                    "stp x0,  x1,  [sp, #0x10]\n"           // 3
                    "stp x2,  x3,  [sp, #0x20]\n"           // 4
                    "stp x4,  x5,  [sp, #0x30]\n"           // 5
                    "stp x6,  x7,  [sp, #0x40]\n"           // 6
                    "str x8,        [sp, #0x50]\n"           // 7
                    "stp d0,  d1,  [sp, #0x60]\n"            // 8
                    "stp d2,  d3,  [sp, #0x70]\n"            // 9
                    "stp d4,  d5,  [sp, #0x80]\n"            // 10
                    "stp d6,  d7,  [sp, #0x90]\n"            // 11
                    // ── load embedded data & call (5 insns) ──
                    "ldr x1,  [sp, #0x08]\n"                 // 12  caller LR
                    "adr x9,  99f\n"                         // 13  → data area
                    "ldp x2,  x3,  [x9]\n"                  // 14  x2=orig, x3=name
                    "ldr x10, [x9, #16]\n"                   // 15  x10=FastHandler
                    "blr x10\n"                              // 16  → x0=exit|0
                    // ── save result, reload orig (3 insns) ──
                    "mov x17, x0\n"                          // 17
                    "adr x9,  99f\n"                         // 18
                    "ldr x16, [x9]\n"                        // 19  x16 = orig_entry
                    // ── restore all regs (10 insns) ──
                    "ldp d6,  d7,  [sp, #0x90]\n"            // 20
                    "ldp d4,  d5,  [sp, #0x80]\n"            // 21
                    "ldp d2,  d3,  [sp, #0x70]\n"            // 22
                    "ldp d0,  d1,  [sp, #0x60]\n"            // 23
                    "ldr x8,        [sp, #0x50]\n"           // 24
                    "ldp x6,  x7,  [sp, #0x40]\n"           // 25
                    "ldp x4,  x5,  [sp, #0x30]\n"           // 26
                    "ldp x2,  x3,  [sp, #0x20]\n"           // 27
                    "ldp x0,  x1,  [sp, #0x10]\n"           // 28
                    "ldp x29, x30, [sp], #0xA0\n"           // 29
                    // ── exit dispatch (3 insns) ──
                    "cbz x17, 1f\n"                          // 30
                    "mov x30, x17\n"                         // 31  LR → exit tramp
                    "1:\n"
                    "br  x16\n"                              // 32  → orig method
                    // ── embedded data (patched per-stub) ──
                    ".balign 8\n"
                    "99:\n"
                    ".quad 0\n"                              // [0] orig_entry
                    ".quad 0\n"                              // [1] name
                    ".quad 0\n"                              // [2] &OnQuickEntryFast
                    );
        }

#endif // __aarch64__

        extern "C" void *OnQuickEntryFast(void *art_method, void *caller_lr,
                void *orig_entry, const char *name) {
            bool skip_exit = ShouldSkipExitTracing(orig_entry);

            if (g_in_hook == 0 && name) {
                ++g_in_hook;
                TraceEngine *engine = GetEngine();
                if (engine && engine->IsTracing()) {
                    engine->Mark(name, SampleType::kSectionBegin);
                    ALOGD("ArtMethodInstr: SectionBegin %s (skip_exit=%d)", name, skip_exit);
                    if (!skip_exit && t_exit_stack.Push(caller_lr, name)) {
                        --g_in_hook;
                        return reinterpret_cast<void *>(atrace_quick_exit_trampoline);
                    }
                }
                --g_in_hook;
            }
            return nullptr;
        }

        static void *CreateMethodStub(void *orig_entry, const char *name) {
#if defined(__aarch64__)
            void *stub = g_stub_allocator.Allocate();
            if (!stub) return nullptr;

            memcpy(stub, reinterpret_cast<void *>(atrace_stub_template),
                    kStubTotalSize);

            auto *data = reinterpret_cast<void **>(
                    static_cast<char *>(stub) + kStubDataOffset);
            data[0] = orig_entry;
            data[1] = const_cast<char *>(name);
            data[2] = reinterpret_cast<void *>(OnQuickEntryFast);

            __builtin___clear_cache(static_cast<char *>(stub),
                    static_cast<char *>(stub) + kStubTotalSize);
            return stub;
#else
            return nullptr;
#endif
        }

// ── OnQuickEntry：共享 trampoline 回退路径（stub 分配失败时使用）──────────────

        extern "C" EntryResult OnQuickEntry(void *art_method, void *caller_lr) {
            void *orig = nullptr;
            const char *name = nullptr;

            if (!art_method || reinterpret_cast<uintptr_t>(art_method) < 0x1000) {
                ALOGE("ArtMethodInstr: OnQuickEntry — invalid art_method %p", art_method);
                return {reinterpret_cast<void *>(
                        atrace_quick_entry_trampoline), nullptr};
            }

            {
                std::shared_lock<std::shared_mutex> lock(g_hook_mutex);
                auto it = g_hooked_methods.find(art_method);
                if (it != g_hooked_methods.end()) {
                    orig = it->second.orig_entry;
                    name = it->second.cached_name;
                }
            }

            if (!orig) {
                ALOGE("ArtMethodInstr: OnQuickEntry un-tracked %p", art_method);
                if (g_quick_code_index >= 0) {
                    auto **am = reinterpret_cast<void **>(art_method);
                    void *live = am[g_quick_code_index];
                    void *tramp = reinterpret_cast<void *>(
                            atrace_quick_entry_trampoline);
                    if (live && live != tramp) return {live, nullptr};
                }
                return {reinterpret_cast<void *>(
                        atrace_quick_entry_trampoline), nullptr};
            }

            bool skip_exit = ShouldSkipExitTracing(orig);

            void *exit_tramp = nullptr;
            if (g_in_hook == 0 && name) {
                ++g_in_hook;
                TraceEngine *engine = GetEngine();
                if (engine && engine->IsTracing()) {
                    engine->Mark(name, SampleType::kSectionBegin);
                    ALOGD("ArtMethodInstr: SectionBegin %s (skip_exit=%d)", name, skip_exit);
                    if ((!skip_exit || g_device_api_level >= 36) && t_exit_stack.Push(caller_lr, name)) {
                        exit_tramp = reinterpret_cast<void *>(
                                atrace_quick_exit_trampoline);
                    }
                }
                --g_in_hook;
            }

            return {orig, exit_tramp};
        }

        extern "C" void *OnQuickExit() {
            SavedFrame frame = t_exit_stack.Pop();
            ALOGD("ArtMethodInstr: OnQuickExit");
            if (g_in_hook == 0 && frame.method_name) {
                ++g_in_hook;
                TraceEngine *engine = GetEngine();
                if (engine && engine->IsTracing()) {
                    engine->Mark(frame.method_name, SampleType::kSectionEnd);
                    ALOGD("ArtMethodInstr: SectionEnd %s",
                            frame.method_name);
                }
                --g_in_hook;
            }

            if (!frame.real_lr) {
                // 禁止跳转到 art_quick_to_interpreter_bridge / entry trampoline：
                // exit 路径上 x0 已是被 hook 方法的返回值，而 interpreter bridge
                // 期望 x0=ArtMethod*，会在 DoGetCalleeSaveMethodCaller 等处 SIGSEGV
                // （Android 13+ PAC 设备上常见，fault addr 接近错误「方法指针」）。
                // Android 16 abort 时 WalkStack 级联 CHECK 是另一问题；错误分支比 abort 更糟。
                ALOGE("ArtMethodInstr: OnQuickExit real_lr is null — "
                      "exit stack underflow / desync (e.g. exception unwind); aborting");
                abort();
            }
            return frame.real_lr;
        }

// ── 工具函数 ─────────────────────────────────────────────────────────────────

        static std::string Trim(const std::string &s) {
            size_t a = 0;
            while (a < s.size() && std::isspace(static_cast<unsigned char>(s[a]))) ++a;
            size_t b = s.size();
            while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;
            return s.substr(a, b - a);
        }

        static std::string ToLower(std::string s) {
            for (char &c: s) {
                c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            }
            return s;
        }

        static char *DupMethodName(void *art_method) {
            std::string pretty;
            try {
                pretty = SymbolResolver::Instance().MethodToString(art_method);
            } catch (...) {
                return nullptr;
            }
            if (pretty.empty()) return nullptr;
            std::string tag = "ArtHook:" + pretty;
            char *buf = new(std::nothrow) char[tag.size() + 1];
            if (buf) {
                memcpy(buf, tag.c_str(), tag.size() + 1);
            }
            return buf;
        }

// ── WatchRule 匹配 ──────────────────────────────────────────────────────────
        /**
         * 判断 PrettyMethod 名是否匹配任一 watch rule。
         * 规则前缀: pkg: / cls: / mth: / 无前缀(子串)
         * PrettyMethod 格式: "void com.foo.Bar.baz(int, java.lang.String)"
         */
        static bool MatchesAnyWatchRule(const std::string &pretty,
                const std::vector<std::string> &rules) {
            for (const auto &rule: rules) {
                if (rule.compare(0, 4, "pkg:") == 0) {
                    if (pretty.find(rule.substr(4)) != std::string::npos) return true;
                } else if (rule.compare(0, 4, "cls:") == 0) {
                    std::string cls = rule.substr(4) + ".";
                    if (pretty.find(cls) != std::string::npos) return true;
                } else if (rule.compare(0, 4, "mth:") == 0) {
                    std::string mth = rule.substr(4) + "(";
                    if (pretty.find(mth) != std::string::npos) return true;
                } else {
                    if (pretty.find(rule) != std::string::npos) return true;
                }
            }
            return false;
        }

// ── Per-method hook 内部实现 ─────────────────────────────────────────────────

        static bool HookMethodEntry(void **art_method) {
            if (g_quick_code_index < 0 || !art_method) return false;
            auto addr = reinterpret_cast<uintptr_t>(art_method);
            if (addr < 0x1000) {
                ALOGE("ArtMethodInstr: HookMethodEntry — invalid ArtMethod* %p", art_method);
                return false;
            }

            // ① 锁外：保存 hotness + 解析方法名（JNI 调用，不可持锁）
            uint16_t saved_hotness = ReadHotness(art_method);
            char *name = DupMethodName(art_method);

            // ② 写锁：read entry → bridge 检查 → 分配 stub → CAS → 写 map
            std::unique_lock<std::shared_mutex> lock(g_hook_mutex);

            if (g_hooked_methods.count(art_method)) {
                delete[] name;
                return true;
            }

            void *old_entry = art_method[g_quick_code_index];
            void *shared_tramp = reinterpret_cast<void *>(atrace_quick_entry_trampoline);

            ALOGI("ArtMethodInstr: HookMethodEntry %p, old_entry=%p, interp_bridge=%p",
                    art_method, old_entry, g_interpreter_bridge);

            if (old_entry == shared_tramp || old_entry == nullptr) {
                delete[] name;
                return false;
            }

            EntryType entry_type = ClassifyEntryPoint(old_entry);
            if (IsUnhookableEntry(old_entry)) {
                ALOGW("ArtMethodInstr: skip %p — entry %p is %s (unhookable)",
                        art_method, old_entry, EntryTypeName(entry_type));
                delete[] name;
                return false;
            }
            bool is_nterp_or_bridge = (entry_type != EntryType::kCompiledCode);
            if (is_nterp_or_bridge) {
                ALOGI("ArtMethodInstr: hooking %p with %s entry %p (entry-only tracing)",
                        art_method, EntryTypeName(entry_type), old_entry);
            }

            // ③ 尝试分配 per-method stub（零 HashMap 查找热路径）
            void *stub = nullptr;
            if (g_stubs_available && name) {
                stub = CreateMethodStub(old_entry, name);
            }
            void *new_entry = stub ? stub : shared_tramp;

            // ④ CAS 替换 entry_point
            std::atomic<void *> *atomic_entry =
                    reinterpret_cast<std::atomic<void *> *>(art_method + g_quick_code_index);
            void *expected = old_entry;
            if (!atomic_entry->compare_exchange_strong(expected, new_entry,
                    std::memory_order_release, std::memory_order_acquire)) {
                old_entry = expected;
                if (old_entry == shared_tramp || old_entry == nullptr ||
                        IsUnhookableEntry(old_entry)) {
                    delete[] name;
                    return false;
                }
                // stub 数据区需更新 orig_entry（JIT 可能已重编译）
                if (stub) {
#if defined(__aarch64__)
                    auto *data = reinterpret_cast<void **>(
                            static_cast<char *>(stub) + kStubDataOffset);
                    data[0] = old_entry;
                    __builtin___clear_cache(static_cast<char *>(stub),
                            static_cast<char *>(stub) + kStubDataOffset + sizeof(void *));
#endif
                }
                expected = old_entry;
                if (!atomic_entry->compare_exchange_strong(expected, new_entry,
                        std::memory_order_release, std::memory_order_acquire)) {
                    ALOGE("ArtMethodInstr: CAS failed twice for %p", art_method);
                    delete[] name;
                    return false;
                }
            }

            // ⑤ CAS 成功：回读验证，确认 entry_point 已写入
            void *readback = art_method[g_quick_code_index];
            if (readback != new_entry) {
                ALOGE("ArtMethodInstr: post-CAS verify failed for %p "
                      "(expected %p, got %p) — reverting", art_method, new_entry, readback);
                // 尝试恢复原始 entry_point
                std::atomic<void *> *rb =
                        reinterpret_cast<std::atomic<void *> *>(art_method + g_quick_code_index);
                rb->store(old_entry, std::memory_order_release);
                delete[] name;
                return false;
            }

            // ⑥ P1/P2：清解释器快路径与单实现去虚化位，避免绕过 trampoline
            uint32_t saved_jit = ClearJitHookAccessHints(art_method);

            // ⑦ 彻底阻止 JIT 重编译、写入管理 map
            bool had_flag = HasCompileDontBother(art_method);
            SetCompileDontBother(art_method);
            ClearHotness(art_method);
            g_hooked_methods[art_method] = {
                    old_entry, name, saved_hotness, had_flag, saved_jit, stub};

            ALOGI("ArtMethodInstr: hooked %p, old_entry=%p, stub=%s, "
                  "hotness=%u→0, CompileDontBother=%s→set, jitHintsCleared=0x%08x, name=%s",
                    art_method, old_entry, stub ? "yes" : "no(fallback)",
                    saved_hotness, had_flag ? "already" : "newly",
                    saved_jit, name ? name : "(null)");
            return true;
        }

        static void UnhookMethodEntry(void **art_method) {
            if (g_quick_code_index < 0 || !art_method) return;

            void *orig = nullptr;
            const char *name = nullptr;
            uint16_t orig_hotness = 0;
            bool had_compile_dont_bother = false;
            uint32_t saved_jit = 0;
            void *stub = nullptr;
            {
                std::unique_lock<std::shared_mutex> lock(g_hook_mutex);
                auto it = g_hooked_methods.find(art_method);
                if (it == g_hooked_methods.end()) return;
                orig = it->second.orig_entry;
                name = it->second.cached_name;
                orig_hotness = it->second.orig_hotness;
                had_compile_dont_bother = it->second.had_compile_dont_bother;
                saved_jit = it->second.saved_jit_hint_bits;
                stub = it->second.stub;
                g_hooked_methods.erase(it);
            }

            std::atomic<void *> *atomic_entry =
                    reinterpret_cast<std::atomic<void *> *>(art_method + g_quick_code_index);
            void *current = stub ? stub
                    : reinterpret_cast<void *>(atrace_quick_entry_trampoline);
            atomic_entry->compare_exchange_strong(current, orig,
                    std::memory_order_release, std::memory_order_acquire);

            if (!had_compile_dont_bother) {
                ClearCompileDontBother(art_method);
            }
            RestoreJitHookAccessHints(art_method, saved_jit);
            RestoreHotness(art_method, orig_hotness);
            ALOGI("ArtMethodInstr: unhooked %p", art_method);
            delete[] name;
            // stub 内存不立即回收（可能仍有线程在执行），由 Uninstall 统一释放
        }

    } // anonymous namespace

// ── Public API ────────────────────────────────────────────────────────────────

    bool ArtMethodInstrumentation::Install(JNIEnv *env) {
//        return true;
        if (installed_) return true;

        if (!GetEngine()) {
            ALOGE("ArtMethodInstrumentation: TraceEngine not created yet");
            return false;
        }

        env->GetJavaVM(&g_java_vm);

        g_device_api_level = android_get_device_api_level();
        ALOGI("ArtMethodInstr: device API level %d", g_device_api_level);

        int jni_idx = jni_hook::GetJniEntranceIndex();
        if (jni_idx < 0) {
            ALOGE("ArtMethodInstrumentation: JNIMethodHook not initialized");
            return false;
        }

        // entry_point_from_quick_compiled_code_ 紧跟 data_ (entry_point_from_jni_)
        g_quick_code_index = jni_idx + 1;

        // 验证：JNI placeholder 是 native 方法，其 quick code entry 应指向
        // art_quick_generic_jni_trampoline（libart.so 内地址）。
        // Android 16+：ART 可能为已注册的 native 方法使用不同的 trampoline
        // （如 art_quick_generic_jni_trampoline 的优化变体），此时 entry_point
        // 仍在 libart.so 内但不等于 art_quick_generic_jni_trampoline。
        void *jni_trampoline = SymbolResolver::Instance().FindSymbol(
                "art_quick_generic_jni_trampoline");
        if (jni_trampoline) {
            void **sample = jni_hook::ResolveArtMethod(
                    env, "com/aspect/atrace/core/JNIHookHelper",
                    "nativePlaceholder", "()V", true);
            if (sample) {
                void *actual = sample[g_quick_code_index];
                if (actual != jni_trampoline) {
                    // 检查 actual 是否在同一个库（libart.so）内 —— 如果是，
                    // 说明 quick_code_index 正确，只是 trampoline 不同（Android 16+）
                    Dl_info actual_info, tramp_info;
                    bool same_lib = false;
                    if (actual &&
                            dladdr(actual, &actual_info) && actual_info.dli_fbase &&
                            dladdr(jni_trampoline, &tramp_info) && tramp_info.dli_fbase &&
                            actual_info.dli_fbase == tramp_info.dli_fbase) {
                        same_lib = true;
                    }

                    if (same_lib) {
                        ALOGI("ArtMethodInstr: quick_code_index %d accepted — "
                              "entry %p is libart trampoline (expected %p, sym=%s, API %d)",
                                g_quick_code_index, actual, jni_trampoline,
                                actual_info.dli_sname ? actual_info.dli_sname : "unknown",
                                g_device_api_level);
                    } else {
                        ALOGW("ArtMethodInstr: quick_code_index %d verification mismatch: "
                              "expected %p, got %p — scanning fallback",
                                g_quick_code_index, jni_trampoline, actual);
                        g_quick_code_index = -1;
                        for (int i = 0; i < 20; ++i) {
                            if (sample[i] == jni_trampoline) {
                                g_quick_code_index = i;
                                ALOGI("ArtMethodInstr: found quick_code_index=%d via scan", i);
                                break;
                            }
                        }
                        // 如果精确扫描也失败，尝试查找任何 libart 内地址
                        if (g_quick_code_index < 0) {
                            for (int i = 0; i < 20; ++i) {
                                void *val = sample[i];
                                if (!val) continue;
                                Dl_info di;
                                if (dladdr(val, &di) && di.dli_fbase &&
                                        di.dli_fbase == tramp_info.dli_fbase) {
                                    // 候选 slot：排除 data_ (jni_idx) 本身
                                    if (i == jni_idx) continue;
                                    ALOGI("ArtMethodInstr: slot[%d]=%p is libart (sym=%s)",
                                            i, val, di.dli_sname ? di.dli_sname : "unknown");
                                }
                            }
                        }
                    }

                    // dump ArtMethod slots for debugging
                    if (sample) {
                        ALOGI("ArtMethodInstr: [DIAG] nativePlaceholder ArtMethod "
                              "(jni_idx=%d, quick_idx=%d):", jni_idx, g_quick_code_index);
                        for (int i = 0; i < 10; ++i) {
                            Dl_info si;
                            const char *sym_name = "";
                            if (sample[i] && dladdr(sample[i], &si) && si.dli_sname) {
                                sym_name = si.dli_sname;
                            }
                            ALOGI("  slot[%d] = %p  %s", i, sample[i], sym_name);
                        }
                    }
                }
            }
        }

        if (g_quick_code_index < 0) {
            ALOGE("ArtMethodInstrumentation: cannot determine quick code index");
            return false;
        }

        // 验证 access_flags_ 偏移
        VerifyAccessFlagsOffset(env);

        // 动态探测 hotness_count_ 偏移（兼容 Android 8-15 / 16+）
        DetectHotnessOffset();
        VerifyHotnessOffset(env);

        // 解析 interpreter bridge 地址（用于检测未编译方法）
        g_interpreter_bridge = SymbolResolver::Instance().FindSymbol(
                "art_quick_to_interpreter_bridge");
        ALOGI("ArtMethodInstr: interpreter_bridge=%p (symbol)", g_interpreter_bridge);

        // 符号解析失败时（OEM 构建可能剥离 .dynsym 中的汇编符号），
        // 通过探测 abstract 方法的 entry_point 获取 bridge 地址。
        // ART 对所有 abstract 方法设置 entry_point = art_quick_to_interpreter_bridge。
        if (!g_interpreter_bridge && g_quick_code_index >= 0) {
            void **probe_am = jni_hook::ResolveArtMethod(
                    env, "java/lang/Runnable", "run", "()V", false);
            if (probe_am) {
                void *probe_entry = probe_am[g_quick_code_index];
                if (probe_entry) {
                    g_interpreter_bridge = probe_entry;
                    ALOGI("ArtMethodInstr: interpreter_bridge=%p (probed from "
                          "Runnable.run abstract method)", g_interpreter_bridge);
                }
            }
            if (!g_interpreter_bridge) {
                ALOGW("ArtMethodInstr: interpreter_bridge is null — "
                      "bridge detection will rely on libart range fallback");
            }
        }

        // 预解析所有 bridge/nterp 符号 + libart.so 地址范围
        ResolveBridgeSymbols();
        ALOGI("ArtMethodInstr: libart range=[%p, %p) size=%zuKB",
                reinterpret_cast<void *>(s_libart_base),
                reinterpret_cast<void *>(s_libart_end),
                s_libart_end > s_libart_base ? (s_libart_end - s_libart_base) / 1024 : 0);

        // Android 16+ 诊断：探测一个普通 Java 方法的 entry_point 类型
        {
            void **probe = jni_hook::ResolveArtMethod(
                    env, "java/lang/Object", "toString",
                    "()Ljava/lang/String;", false);
            if (probe) {
                void *probe_entry = probe[g_quick_code_index];
                EntryType probe_type = ClassifyEntryPoint(probe_entry);
                ALOGI("ArtMethodInstr: [DIAG] Object.toString entry=%p type=%s",
                        probe_entry, EntryTypeName(probe_type));

                // 打印 ArtMethod 前 8 个 slot 的原始值
                ALOGI("ArtMethodInstr: [DIAG] Object.toString ArtMethod dump:");
                int dump_count = g_quick_code_index + 2;
                if (dump_count > 10) dump_count = 10;
                for (int i = 0; i < dump_count; ++i) {
                    ALOGI("  slot[%d] = %p", i, probe[i]);
                }
            }

            void **probe2 = jni_hook::ResolveArtMethod(
                    env, "java/lang/String", "length", "()I", false);
            if (probe2) {
                void *p2_entry = probe2[g_quick_code_index];
                EntryType p2_type = ClassifyEntryPoint(p2_entry);
                ALOGI("ArtMethodInstr: [DIAG] String.length entry=%p type=%s",
                        p2_entry, EntryTypeName(p2_type));
            }
        }

        // 初始化 per-method stub：探测 mmap(RWX) 可用性
        g_stubs_available = false;
#if defined(__aarch64__)
        {
            g_stub_allocator.Init(kStubTotalSize);
            void *probe = mmap(nullptr, 4096,
                    PROT_READ | PROT_WRITE | PROT_EXEC,
                    MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
            if (probe != MAP_FAILED) {
                munmap(probe, 4096);
                g_stubs_available = true;
                ALOGI("ArtMethodInstr: per-method stubs enabled (template=%zu bytes)",
                        kStubTotalSize);
            } else {
                ALOGW("ArtMethodInstr: mmap(RWX) failed, falling back to shared trampoline");
            }
        }
#endif

        installed_ = true;
        ALOGI("ArtMethodInstrumentation installed (quick_code_index=%d, "
              "hotness_offset=%d, flags_verified=%s, interp_bridge=%p, stubs=%s)",
                g_quick_code_index, g_hotness_byte_offset,
                g_access_flags_verified ? "yes" : "no",
                g_interpreter_bridge,
                g_stubs_available ? "yes" : "no(fallback)");
        return true;
    }

    void ArtMethodInstrumentation::Uninstall() {
        if (!installed_) return;

        ScopedStackWalkSuppress suppress_walk;
        std::unique_lock<std::shared_mutex> lock(g_hook_mutex);
        for (auto &[method, info]: g_hooked_methods) {
            auto *am = reinterpret_cast<void **>(method);
            std::atomic<void *> *entry =
                    reinterpret_cast<std::atomic<void *> *>(am + g_quick_code_index);
            entry->store(info.orig_entry, std::memory_order_release);
            if (!info.had_compile_dont_bother) {
                ClearCompileDontBother(am);
            }
            RestoreJitHookAccessHints(am, info.saved_jit_hint_bits);
            RestoreHotness(am, info.orig_hotness);
            delete[] info.cached_name;
        }
        g_hooked_methods.clear();

        g_stub_allocator.Cleanup();
        g_stubs_available = false;

        installed_ = false;
        ALOGI("ArtMethodInstrumentation uninstalled");
    }

// ── WatchList API ────────────────────────────────────────────────────────────

    static void PushEntryUnlocked(const std::string &entry) {
        for (const auto &p: g_watched_entries) {
            if (p == entry) return;
        }
        g_watched_entries.push_back(entry);
        g_watch_count.store(static_cast<int>(g_watched_entries.size()),
                std::memory_order_release);
        ALOGI("ArtMethodInstrumentation: watch add [%s] total=%d",
                entry.c_str(), static_cast<int>(g_watched_entries.size()));
    }

    void ArtMethodInstrumentation::AddWatchedRule(const std::string &scope,
            const std::string &value) {
        const std::string sc = ToLower(Trim(scope));
        const std::string v0 = Trim(value);
        if (v0.empty()) return;

        if (sc.empty() || sc == "substring" || sc == "legacy" || sc == "sub") {
            std::lock_guard<std::mutex> lock(g_watch_mutex);
            PushEntryUnlocked(v0);
            return;
        }

        std::string entry;
        if (sc == "package" || sc == "pkg") {
            std::string pkg = v0;
            std::replace(pkg.begin(), pkg.end(), '/', '.');
            if (!pkg.empty() && pkg.back() != '.') {
                pkg.push_back('.');
            }
            entry = "pkg:" + pkg;
        } else if (sc == "class" || sc == "cls") {
            std::string cls = v0;
            std::replace(cls.begin(), cls.end(), '/', '.');
            entry = "cls:" + cls;
        } else if (sc == "method" || sc == "mth") {
            std::string m = v0;
            std::replace(m.begin(), m.end(), '/', '.');
            const size_t last_dot = m.find_last_of('.');
            if (last_dot == std::string::npos || last_dot == 0) {
                ALOGE("ArtMethodInstrumentation: method rule needs Fqcn.methodName, got [%s]",
                        m.c_str());
                return;
            }
            entry = "mth:" + m;
        } else {
            ALOGE("ArtMethodInstrumentation: unknown watch scope [%s]", sc.c_str());
            return;
        }

        std::lock_guard<std::mutex> lock(g_watch_mutex);
        PushEntryUnlocked(entry);
    }

    void ArtMethodInstrumentation::RemoveWatchedRule(const std::string &pattern) {
        std::lock_guard<std::mutex> lock(g_watch_mutex);
        g_watched_entries.erase(
                std::remove(g_watched_entries.begin(), g_watched_entries.end(), pattern),
                g_watched_entries.end());
        g_watch_count.store(static_cast<int>(g_watched_entries.size()),
                std::memory_order_release);
        ALOGI("ArtMethodInstrumentation: watch remove [%s] total=%d",
                pattern.c_str(), static_cast<int>(g_watched_entries.size()));
    }

    void ArtMethodInstrumentation::ClearWatchedRules() {
        Uninstall();
        std::lock_guard<std::mutex> lock(g_watch_mutex);
        g_watched_entries.clear();
        g_watch_count.store(0, std::memory_order_release);
        installed_ = true;
        ALOGI("ArtMethodInstrumentation: watch list cleared");
    }

    int ArtMethodInstrumentation::WatchedRuleCount() {
        return g_watch_count.load(std::memory_order_acquire);
    }

    std::vector<std::string> ArtMethodInstrumentation::GetWatchedRules() {
        std::lock_guard<std::mutex> lock(g_watch_mutex);
        return g_watched_entries;
    }

// ── 精确方法 hook（通过 class/method/sig 直接定位 ArtMethod）────────────────

    bool ArtMethodInstrumentation::HookMethod(JNIEnv *env,
            const char *class_name,
            const char *method_name,
            const char *signature,
            bool is_static) {
        if (!installed_ || g_quick_code_index < 0) {
            ALOGE("ArtMethodInstr: not installed");
            return false;
        }
        ScopedStackWalkSuppress suppress_walk;
        void **am = jni_hook::ResolveArtMethod(env, class_name, method_name,
                signature, is_static);
        if (!am) {
            ALOGE("ArtMethodInstr: cannot resolve %s#%s%s", class_name, method_name, signature);
            return false;
        }
        return HookMethodEntry(am);
    }

    void ArtMethodInstrumentation::UnhookMethod(JNIEnv *env,
            const char *class_name,
            const char *method_name,
            const char *signature,
            bool is_static) {
        if (!installed_ || g_quick_code_index < 0) return;
        ScopedStackWalkSuppress suppress_walk;
        void **am = jni_hook::ResolveArtMethod(env, class_name, method_name,
                signature, is_static);
        if (am) {
            UnhookMethodEntry(am);
        }
    }

// ── 类扫描自动 hook ─────────────────────────────────────────────────────────

    int ArtMethodInstrumentation::ScanClassAndHook(JNIEnv *env, jclass cls) {
        if (!env || !installed_ || g_quick_code_index < 0 || !cls) return 0;

        std::vector<std::string> rules;
        {
            std::lock_guard<std::mutex> lock(g_watch_mutex);
            rules = g_watched_entries;
        }
        if (rules.empty()) return 0;

        // 扫描 + hook 期间禁止本线程 StackVisitor::WalkStack：否则采样器与栈上
        // trampoline/stub 并存时，ART 会 GetOatQuickMethodHeader 解析失败 → SIGSEGV。
        ScopedStackWalkSuppress suppress_walk;

        // ① 先获取类名做预过滤，避免对无关类执行昂贵的 getDeclaredMethods / MethodToString
        jclass classClass = env->FindClass("java/lang/Class");
        if (env->ExceptionCheck()) {
            env->ExceptionClear();
            return 0;
        }
        if (!classClass) return 0;

        jmethodID getName = env->GetMethodID(classClass, "getName",
                "()Ljava/lang/String;");
        if (env->ExceptionCheck()) {env->ExceptionClear();}
        if (!getName) {
            env->DeleteLocalRef(classClass);
            return 0;
        }

        auto jname = reinterpret_cast<jstring>(
                env->CallObjectMethod(cls, getName));
        if (env->ExceptionCheck()) {env->ExceptionClear();}
        if (!jname) {
            env->DeleteLocalRef(classClass);
            return 0;
        }

        const char *cname = env->GetStringUTFChars(jname, nullptr);
        if (!cname) {
            env->DeleteLocalRef(jname);
            env->DeleteLocalRef(classClass);
            return 0;
        }
        std::string className(cname);
        env->ReleaseStringUTFChars(jname, cname);
        env->DeleteLocalRef(jname);

        // 类级预过滤：只有 className 可能匹配某条规则才继续
        bool classRelevant = false;
        for (const auto &rule: rules) {
            if (rule.compare(0, 4, "pkg:") == 0) {
                if (className.compare(0, rule.size() - 4, rule, 4) == 0 ||
                        className.find(rule.substr(4)) != std::string::npos)
                    classRelevant = true;
            } else if (rule.compare(0, 4, "cls:") == 0) {
                if (className == rule.substr(4)) classRelevant = true;
            } else if (rule.compare(0, 4, "mth:") == 0) {
                std::string cls_part = rule.substr(4, rule.find_last_of('.') - 4);
                if (className == cls_part) classRelevant = true;
            } else {
                if (className.find(rule) != std::string::npos) classRelevant = true;
            }
            if (classRelevant) break;
        }
        if (!classRelevant) {
            env->DeleteLocalRef(classClass);
            return 0;
        }

        // ② 类匹配 → 获取方法列表
        jmethodID getDeclaredMethods = env->GetMethodID(
                classClass, "getDeclaredMethods",
                "()[Ljava/lang/reflect/Method;");
        if (env->ExceptionCheck()) {env->ExceptionClear();}
        if (!getDeclaredMethods) {
            env->DeleteLocalRef(classClass);
            return 0;
        }

        auto methods = reinterpret_cast<jobjectArray>(
                env->CallObjectMethod(cls, getDeclaredMethods));
        if (env->ExceptionCheck()) {env->ExceptionClear();}
        if (!methods) {
            env->DeleteLocalRef(classClass);
            return 0;
        }

        jsize count = env->GetArrayLength(methods);
        int hooked = 0;

        // 诊断统计：按跳过原因分类
        int stat_total = 0, stat_null_am = 0, stat_unhookable = 0;
        int stat_no_name = 0, stat_ctor = 0, stat_no_match = 0;
        int stat_hook_fail = 0;
        int stat_by_type[8] = {}; // 按 EntryType 统计 entry_point 分布

        for (jsize i = 0; i < count; ++i) {
            jobject method = env->GetObjectArrayElement(methods, i);
            if (env->ExceptionCheck()) {
                env->ExceptionClear();
                continue;
            }
            if (!method) continue;

            void **art_method = jni_hook::GetArtMethod(env, method);
            if (env->ExceptionCheck()) {env->ExceptionClear();}
            env->DeleteLocalRef(method);
            if (!art_method) {
                ++stat_null_am;
                continue;
            }

            auto addr = reinterpret_cast<uintptr_t>(art_method);
            if (addr < 0x1000) {
                ++stat_null_am;
                continue;
            }

            ++stat_total;

            void *cur_entry = art_method[g_quick_code_index];
            EntryType etype = ClassifyEntryPoint(cur_entry);
            int etype_idx = static_cast<int>(etype);
            if (etype_idx >= 0 && etype_idx < 8) stat_by_type[etype_idx]++;

            if (IsUnhookableEntry(cur_entry)) {
                ++stat_unhookable;
                continue;
            }

            std::string pretty;
            try {
                pretty = SymbolResolver::Instance().MethodToString(art_method);
            } catch (...) {
                ++stat_no_name;
                continue;
            }
            if (pretty.empty()) {
                ++stat_no_name;
                continue;
            }

            if (pretty.find(".<init>(") != std::string::npos ||
                    pretty.find(".<clinit>(") != std::string::npos) {
                ++stat_ctor;
                continue;
            }

            if (MatchesAnyWatchRule(pretty, rules)) {
                if (HookMethodEntry(art_method)) {
                    hooked++;
                } else {
                    ++stat_hook_fail;
                }
            } else {
                ++stat_no_match;
            }
        }

        ALOGI("ArtMethodInstr: ScanClass %s — total=%d, hooked=%d, "
              "unhookable=%d, no_name=%d, ctor=%d, no_match=%d, hook_fail=%d",
                className.c_str(), stat_total, hooked,
                stat_unhookable, stat_no_name, stat_ctor, stat_no_match, stat_hook_fail);
        ALOGI("ArtMethodInstr: ScanClass %s — entry distribution: "
              "null=%d, interp_bridge=%d, generic_jni=%d, resolution=%d, "
              "nterp=%d, libart_other=%d, compiled=%d, our_tramp=%d",
                className.c_str(),
                stat_by_type[0], stat_by_type[1], stat_by_type[2], stat_by_type[3],
                stat_by_type[4], stat_by_type[5], stat_by_type[6], stat_by_type[7]);

        env->DeleteLocalRef(methods);
        env->DeleteLocalRef(classClass);
        return hooked;
    }

} // namespace atrace
