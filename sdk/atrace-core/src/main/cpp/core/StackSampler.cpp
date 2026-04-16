/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Stack sampling via ART's StackVisitor.
 * Approach inspired by btrace/rhea: use a real C++ class with virtual
 * destructor + virtual VisitFrame() so the compiler generates the correct
 * vtable layout for the Itanium ABI. A 2048-byte placeholder reserves
 * space for ART's StackVisitor internal members; our own fields live
 * after the placeholder so ART's constructor cannot clobber them.
 */
#include "StackSampler.h"
#include "SymbolResolver.h"
#include "utils/time_utils.h"
#include "include/atrace.h"

#include <cstring>
#include <sstream>
#include <algorithm>
#include <pthread.h>
#define ATRACE_LOG_TAG "Sampler"
#include "utils/atrace_log.h"

namespace atrace {

namespace {

thread_local int g_stack_walk_suppress_depth = 0;

} // namespace

ScopedStackWalkSuppress::ScopedStackWalkSuppress() {
    ++g_stack_walk_suppress_depth;
}

ScopedStackWalkSuppress::~ScopedStackWalkSuppress() {
    if (g_stack_walk_suppress_depth > 0) {
        --g_stack_walk_suppress_depth;
    }
}

// ---------------------------------------------------------------------------
// ART StackVisitor wrapper
//
// Memory layout:
//   [0..8)        vtable pointer  (overwritten by ART ctor, restored after)
//   [8..2056)     mSpaceHolder    (ART StackVisitor internals write here)
//   [2056..)      mCurIndex, mStack  (safe — beyond ART's reach)
//
// The class declares `virtual ~Wrapper()` and `virtual bool VisitFrame()`
// so the compiler emits the vtable with correct slot count / ordering.
// We never actually destruct through the vtable — the destructor only
// exists to occupy the correct vtable slots.
// ---------------------------------------------------------------------------
class StackVisitorWrapper {
public:
    explicit StackVisitorWrapper(Stack &stack)
            : mCurIndex(0), mStack(stack) {
        memset(mSpaceHolder, 0, sizeof(mSpaceHolder));
    }

    virtual ~StackVisitorWrapper() = default;

    virtual bool VisitFrame() {
        auto *method = SymbolResolver::Instance().GetGetMethod()(
                reinterpret_cast<void *>(this));
        if (method) {
            if (mCurIndex < kMaxStackDepth) {
                mStack.frames[mCurIndex].method_ptr =
                        reinterpret_cast<uint64_t>(method);
            }
            mCurIndex++;
        }
        return true;
    }

    void Walk() {
        SymbolResolver::Instance().GetWalkStack()(reinterpret_cast<void *>(this), false);
    }

    uint32_t GetIndex() const { return mCurIndex; }

private:
    // ART StackVisitor internal fields write into this region.
    // 2048 bytes covers all known Android versions (actual ~160-400 bytes).
    char mSpaceHolder[2048]; //给 ART StackVisitor 内部成员预留的空间

    // Our fields — placed AFTER mSpaceHolder so ART ctor cannot clobber them.
    uint32_t mCurIndex; //我们自己的帧计数器
    Stack &mStack;  //我们自己的输出 Stack 引用
};

// ---------------------------------------------------------------------------
// Context helper
// ---------------------------------------------------------------------------
static void DestroyContext(void *context) {
    if (!context) return;
    void **vptr = *reinterpret_cast<void ***>(context);
    if (vptr) {
        using Dtor = void (*)(void *);
        auto deleting_dtor = reinterpret_cast<Dtor>(vptr[1]);
        if (deleting_dtor) {
            deleting_dtor(context);
        }
    }
}

// ---------------------------------------------------------------------------
// StackSampler
// ---------------------------------------------------------------------------

StackSampler &StackSampler::Instance() {
    static StackSampler instance;
    return instance;
}

bool StackSampler::Init() {
    if (initialized_) return true;

    auto &resolver = SymbolResolver::Instance();
    if (!resolver.IsInitialized()) {
        ALOGE("SymbolResolver not initialized");
        return false;
    }

    if (!resolver.GetStackVisitorCtor() ||
        !resolver.GetCreateContext() ||
        !resolver.GetGetMethod() ||
        !resolver.GetWalkStack()) {
        ALOGE("Missing required symbols for stack sampling");
        return false;
    }

    initialized_ = true;

    // Verify GetCurrentThread works on the main thread (which is always an ART thread)
    void *self = GetCurrentThread();
    if (self) {
        ALOGI("StackSampler initialized, main thread self=%p", self);
    } else {
        ALOGW("StackSampler initialized, but GetCurrentThread returned null on main thread!");
        ALOGW("  CurrentFromGdb fn=%p, pthread_key=%p",
              (void *) resolver.GetCurrentThread(), (void *) resolver.GetThreadKey());
    }
    return true;
}

bool StackSampler::IsWalkSuppressedOnThisThread() {
    return g_stack_walk_suppress_depth > 0;
}

bool StackSampler::Sample(Stack &stack, void *thread_self, StackWalkKind walk_kind) {
    if (!initialized_) return false;

    stack.Reset();

    if (g_stack_walk_suppress_depth > 0) {
        return false;
    }

    if (!thread_self) {
        thread_self = GetCurrentThread();
    }
    if (!thread_self) {
        // Expected for non-ART threads (native threads not attached to Java VM)
        return false;
    }

    return SampleInternal(stack, thread_self, walk_kind);
}

void *StackSampler::GetCurrentThread() {
    auto &resolver = SymbolResolver::Instance();

    // Strategy 1: art::Thread::CurrentFromGdb()
    auto fn = resolver.GetCurrentThread();
    if (fn) {
        void *thread = fn();
        if (thread) return thread;
    }

    // Strategy 2: direct pthread_getspecific(Thread::pthread_key_self_)
    // More reliable — avoids potential issues with cross-library function calls
    auto *key = resolver.GetThreadKey();
    if (key) {
        void *thread = pthread_getspecific(*key);
        if (thread) return thread;
    }

    // Both failed: current thread is not attached to ART (native-only thread)
    return nullptr;
}

//用一个"冒充"ART StackVisitor 的 C++ 对象，
// 骗 ART 的 WalkStack 把每一帧都回调到我们的 VisitFrame() 中，从而收集 Java 调用栈
bool StackSampler::SampleInternal(Stack &stack, void *thread, StackWalkKind walk_kind) {
    auto &resolver = SymbolResolver::Instance();

    auto ctor          = resolver.GetStackVisitorCtor();
    auto dtor          = resolver.GetStackVisitorDtor();
    auto create_context = resolver.GetCreateContext();

    // ART 内部用于保存 CPU 寄存器状态的对象，WalkStack 遍历栈帧时需要它来恢复每一帧的寄存器上下文
    void *context = create_context();
    if (!context) {
        ALOGE("Failed to create Context");
        return false;
    }

    StackVisitorWrapper visitor(stack);

    // Save our vtable pointer — ART ctor will overwrite it
    void *our_vptr = *reinterpret_cast<void **>(&visitor);

    //调用 ART ctor — ART 的 StackVisitor::StackVisitor()
    // 会初始化 thread_、context_、walk_kind_ 等内部字段到 mSpaceHolder 区域。但它也会把 vtable 指针覆写为 ART 自己的 vtable
    //把 &visitor 当作 this 传给 ART 的构造函数。
    // ART 的 ctor 不知道（也不在乎）这块内存实际是什么类型，它只管往 this 指向的内存里写入 StackVisitor 的内部字段。
    ctor(reinterpret_cast<void *>(&visitor),
         thread, context,
         static_cast<int>(walk_kind),
         false);

    // Restore our vtable so VisitFrame() dispatches to our override
    *reinterpret_cast<void **>(&visitor) = our_vptr;

    visitor.Walk();

    stack.saved_depth = static_cast<uint8_t>(
            std::min(visitor.GetIndex(), static_cast<uint32_t>(kMaxStackDepth)));
    stack.actual_depth = static_cast<uint8_t>(visitor.GetIndex());

    if (dtor) {
        dtor(reinterpret_cast<void *>(&visitor));
    }

    DestroyContext(context);

    return stack.saved_depth > 0;
}

std::string StackSampler::StackToString(const Stack &stack) const {
    if (stack.saved_depth == 0) {
        return "<empty stack>";
    }

    auto &resolver = SymbolResolver::Instance();
    std::ostringstream oss;

    for (int i = 0; i < stack.saved_depth; ++i) {
        void *method = reinterpret_cast<void *>(stack.frames[i].method_ptr);
        std::string symbol = resolver.MethodToString(method);

        if (!symbol.empty() && symbol.find("<runtime method>") == std::string::npos) {
            oss << "  at " << symbol << "\n";
        }
    }

    return oss.str();
}

// ===== ScopedSample =====

ScopedSample::ScopedSample(SampleType type, void *thread_self)
        : type_(type),
          thread_self_(thread_self),
          begin_nano_(CurrentTimeNanos(ClockType::kBoottime)),
          begin_cpu_nano_(CurrentCpuTimeNanos()) {
}

ScopedSample::~ScopedSample() {
    RequestSampleWithDuration(type_, begin_nano_, begin_cpu_nano_);
}

} // namespace atrace
