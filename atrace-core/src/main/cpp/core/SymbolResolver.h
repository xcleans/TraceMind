/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * ART符号动态解析器
 *
 * 优化点:
 * 1. 延迟加载符号，只在需要时解析
 * 2. 多版本符号自动适配
 * 3. 符号缓存，避免重复查找
 */
#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>
#include <functional>
#include <mutex>
#include <pthread.h>

namespace atrace {

/**
 * ART符号解析器
 *
 * 负责动态解析libart.so中的私有符号，支持多版本Android自动适配
 */
class SymbolResolver {
public:
    /**
     * 获取单例
     */
    static SymbolResolver& Instance();

    /**
     * 初始化
     *
     * @param sdk_version Android SDK版本
     * @return 是否成功
     */
    bool Init(int sdk_version);

    /**
     * 是否已初始化
     */
    bool IsInitialized() const { return initialized_; }

    /**
     * 获取SDK版本
     */
    int GetSdkVersion() const { return sdk_version_; }

    // ===== StackVisitor 相关符号 =====

    /** Thread::CurrentFromGdb() */
    using CurrentThreadFn = void* (*)();
    CurrentThreadFn GetCurrentThread() const { return current_thread_; }

    /** Thread::pthread_key_self_ (direct TLS key for fallback) */
    pthread_key_t* GetThreadKey() const { return thread_key_; }

    /** StackVisitor 构造函数 */
    using StackVisitorCtorFn = void (*)(void* visitor, void* thread, void* context, 
                                        int walk_kind, bool check_suspended);
    StackVisitorCtorFn GetStackVisitorCtor() const { return stack_visitor_ctor_; }

    /** StackVisitor 析构函数 */
    using StackVisitorDtorFn = void (*)(void* visitor);
    StackVisitorDtorFn GetStackVisitorDtor() const { return stack_visitor_dtor_; }

    /** Context::Create() */
    using CreateContextFn = void* (*)();
    CreateContextFn GetCreateContext() const { return create_context_; }

    /** StackVisitor::GetMethod() */
    using GetMethodFn = void* (*)(void* visitor);
    GetMethodFn GetGetMethod() const { return get_method_; }

    /** StackVisitor::WalkStack() */
    using WalkStackFn = void (*)(void* visitor, bool include_transitions);
    WalkStackFn GetWalkStack() const { return walk_stack_; }

    // ===== ArtMethod 相关符号 =====

    /** ArtMethod::PrettyMethod() */
    using PrettyMethodFn = std::string (*)(void* art_method, bool with_signature);
    PrettyMethodFn GetPrettyMethod() const { return pretty_method_; }

    // ===== Heap 相关符号 =====

    /** Heap::SetAllocationListener() */
    using SetAllocListenerFn = void (*)(void* heap, void* listener);
    SetAllocListenerFn GetSetAllocListener() const { return set_alloc_listener_; }

    /** Heap::RemoveAllocationListener() */
    using RemoveAllocListenerFn = void (*)(void* heap);
    RemoveAllocListenerFn GetRemoveAllocListener() const { return remove_alloc_listener_; }

    /**
     * 将ArtMethod指针转换为可读方法名
     */
    std::string MethodToString(void* art_method) const;

    /**
     * 查找 libart.so 中的符号（带缓存）
     */
    void* FindSymbol(const char* name);

private:
    SymbolResolver() = default;
    ~SymbolResolver() = default;

    SymbolResolver(const SymbolResolver&) = delete;
    SymbolResolver& operator=(const SymbolResolver&) = delete;

    bool LoadSymbols();
    void* FindSymbolWithFallback(const std::initializer_list<const char*>& names);

    bool initialized_ = false;
    int sdk_version_ = 0;
    void* libart_handle_ = nullptr;

    // 符号缓存
    std::unordered_map<std::string, void*> symbol_cache_;
    mutable std::mutex cache_mutex_;

    // StackVisitor 符号
    CurrentThreadFn current_thread_ = nullptr;
    pthread_key_t* thread_key_ = nullptr;
    StackVisitorCtorFn stack_visitor_ctor_ = nullptr;
    StackVisitorDtorFn stack_visitor_dtor_ = nullptr;
    CreateContextFn create_context_ = nullptr;
    GetMethodFn get_method_ = nullptr;
    WalkStackFn walk_stack_ = nullptr;

    // ArtMethod 符号
    PrettyMethodFn pretty_method_ = nullptr;

    // Heap 符号
    SetAllocListenerFn set_alloc_listener_ = nullptr;
    RemoveAllocListenerFn remove_alloc_listener_ = nullptr;
};

/**
 * 符号名称常量
 *
 * 按Android版本分组，便于维护
 */
namespace symbols {

// StackVisitor 相关 (Android 8.0+)
//_ZN3art6Thread14CurrentFromGdbEv
constexpr const char* kThreadCurrentFromGdb = "_ZN3art6Thread14CurrentFromGdbEv";
constexpr const char* kThreadPthreadKeySelf = "_ZN3art6Thread17pthread_key_self_E";
constexpr const char* kStackVisitorCtor = "_ZN3art12StackVisitorC2EPNS_6ThreadEPNS_7ContextENS0_13StackWalkKindEb";
constexpr const char* kStackVisitorDtor = "_ZN3art12StackVisitorD2Ev";
constexpr const char* kContextCreate = "_ZN3art7Context6CreateEv";
//_ZNK3art12StackVisitor9GetMethodEv
constexpr const char* kStackVisitorGetMethod = "_ZNK3art12StackVisitor9GetMethodEv";
constexpr const char* kStackVisitorWalkStack = "_ZN3art12StackVisitor9WalkStackILNS0_16CountTransitionsE0EEEvb";

// ArtMethod 相关
constexpr const char* kArtMethodPrettyMethod = "_ZN3art9ArtMethod12PrettyMethodEb";
constexpr const char* kArtMethodInvoke = "_ZN3art9ArtMethod6InvokeEPNS_6ThreadEPjjPNS_6JValueEPKc";

// Heap 相关 (Android 8.0+)
constexpr const char* kHeapSetAllocListener = "_ZN3art2gc4Heap21SetAllocationListenerEPNS0_18AllocationListenerE";
constexpr const char* kHeapRemoveAllocListener = "_ZN3art2gc4Heap24RemoveAllocationListenerEv";

// GC 相关
constexpr const char* kHeapWaitForGcToComplete = "_ZN3art2gc4Heap25WaitForGcToCompleteLockedENS0_7GcCauseEPNS_6ThreadE";

// Monitor 相关
constexpr const char* kMonitorEnter = "_ZN3art7Monitor12MonitorEnterEPNS_6ThreadENS_6ObjPtrINS_6mirror6ObjectEEEb";
constexpr const char* kMonitorExit = "_ZN3art7Monitor11MonitorExitEPNS_6ThreadENS_6ObjPtrINS_6mirror6ObjectEEE";

// JNI 相关
constexpr const char* kArtQuickGenericJniTrampoline = "artQuickGenericJniTrampoline";

} // namespace symbols

} // namespace atrace

