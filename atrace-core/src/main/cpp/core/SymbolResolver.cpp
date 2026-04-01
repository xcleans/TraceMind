/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "SymbolResolver.h"
#include "utils/dl_utils.h"

#include <dlfcn.h>
#define ATRACE_LOG_TAG "Symbol"
#include "utils/atrace_log.h"
#include "shadowhook.h"

namespace atrace {

    SymbolResolver &SymbolResolver::Instance() {
        static SymbolResolver instance;
        return instance;
    }

    bool SymbolResolver::Init(int sdk_version) {
        ALOGD("========SymbolResolver#Init=============");
        if (initialized_) {
            return true;
        }

        sdk_version_ = sdk_version;
        //https://github.com/Rprop/ndk_dlopen
        //https://www.sunmoonblog.com/2019/06/04/fake-dlopen/
        //Android 7.0及以上版本对 dlopen() 和 dlsym() 函数的使用有限制。System.load() 和 System.loadLibrary() 是基于这两个函数实现的，所以也存在同样限制
        // 打开 libart.so
        libart_handle_ =shadowhook_dlopen("libart.so");//   dl_open("libart.so");
        if (!libart_handle_) {
            ALOGE("Failed to open libart.so");
            return false;
        }

        // 加载符号
        if (!LoadSymbols()) {
            shadowhook_dlclose(libart_handle_);// // dl_close(libart_handle_);
            libart_handle_ = nullptr;
            return false;
        }
        initialized_ = true;
        ALOGI("========SymbolResolver initialized========END, sdk=%d", sdk_version_);
        return true;
    }

    bool SymbolResolver::LoadSymbols() {
        // ===== StackVisitor 相关符号 =====
        ALOGD(" ##############LoadSymbols##########");

        // Thread::CurrentFromGdb
        void *CurrentFromGdb = FindSymbol(symbols::kThreadCurrentFromGdb);
        if (CurrentFromGdb) {
            current_thread_ = reinterpret_cast<CurrentThreadFn>(CurrentFromGdb);
            ALOGD("LoadSymbols:Thread::CurrentFromGdb(DONE): %p", CurrentFromGdb);
        } else {
            ALOGW("CurrentFromGdb not found, will rely on pthread_key_self_ fallback");
        }

        // Thread::pthread_key_self_ — direct TLS key, more reliable fallback
        void *keySym = FindSymbol(symbols::kThreadPthreadKeySelf);
        if (keySym) {
            thread_key_ = reinterpret_cast<pthread_key_t*>(keySym);
            ALOGD("LoadSymbols:Thread::pthread_key_self_(DONE): %p, key=%d",
                   keySym, static_cast<int>(*thread_key_));
        } else {
            ALOGW("Thread::pthread_key_self_ not found");
        }

        if (!current_thread_ && !thread_key_) {
            ALOGE("Failed to find any method to get current ART thread");
            return false;
        }


        // StackVisitor 构造函数 (多版本尝试)
        stack_visitor_ctor_ = reinterpret_cast<StackVisitorCtorFn>(
                FindSymbolWithFallback({
                        symbols::kStackVisitorCtor,
                        // Android 14+ 可能有新签名
                        "_ZN3art12StackVisitorC2EPNS_6ThreadEPNS_7ContextENS0_13StackWalkKindEbb",
                }));
        if (!stack_visitor_ctor_) {
            ALOGE("Failed to find StackVisitor constructor");
            return false;
        }
        ALOGD("LoadSymbols:StackVisitor(DONE)");

        // StackVisitor 析构函数 TODO 未定义
        stack_visitor_dtor_ = reinterpret_cast<StackVisitorDtorFn>(
                FindSymbol(symbols::kStackVisitorDtor));

        // Context::Create
        create_context_ = reinterpret_cast<CreateContextFn>(
                FindSymbol(symbols::kContextCreate));
        if (!create_context_) {
            ALOGE("Failed to find Context::Create");
            return false;
        }
        ALOGD("LoadSymbols:Context::Create(DONE)");

        // StackVisitor::GetMethod
        get_method_ = reinterpret_cast<GetMethodFn>(
                FindSymbol(symbols::kStackVisitorGetMethod));
        if (!get_method_) {
            ALOGE("Failed to find StackVisitor::GetMethod");
            return false;
        }
        ALOGE("LoadSymbols:StackVisitor::GetMethod(DONE)");

        // StackVisitor::WalkStack (模板函数，多版本)
        //000000000032d17c W _ZN3art12StackVisitor9WalkStackILNS0_16CountTransitionsE0EEEvb
        //000000000026024c W _ZN3art12StackVisitor9WalkStackILNS0_16CountTransitionsE1EEEvb
        walk_stack_ = reinterpret_cast<WalkStackFn>(
                FindSymbolWithFallback({
                        symbols::kStackVisitorWalkStack,
                        "_ZN3art12StackVisitor9WalkStackILNS0_16CountTransitionsE1EEEvb",
                        "_ZN3art12StackVisitor9WalkStackEb",
                }));
        if (!walk_stack_) {
            ALOGE("Failed to find StackVisitor::WalkStack");
            return false;
        }
        ALOGE("LoadSymbols:StackVisitor::WalkStack(DONE)");

        // ===== ArtMethod 相关符号 =====
        pretty_method_ = reinterpret_cast<PrettyMethodFn>(
                FindSymbol(symbols::kArtMethodPrettyMethod));

        if (!pretty_method_) {
            ALOGE("Failed to find ArtMethod::PrettyMethod");
            return false;
        }

        // ===== Heap 相关符号 (可选) =====

        set_alloc_listener_ = reinterpret_cast<SetAllocListenerFn>(
                FindSymbol(symbols::kHeapSetAllocListener));

        remove_alloc_listener_ = reinterpret_cast<RemoveAllocListenerFn>(
                FindSymbol(symbols::kHeapRemoveAllocListener));

        ALOGI("Symbols loaded successfully");
        ALOGD("  CurrentThread: %p (key: %p)", (void *) current_thread_, (void *) thread_key_);
        ALOGD("  StackVisitorCtor: %p", (void *) stack_visitor_ctor_);
        ALOGD("  CreateContext: %p", (void *) create_context_);
        ALOGD("  GetMethod: %p", (void *) get_method_);
        ALOGD("  WalkStack: %p", (void *) walk_stack_);
        ALOGD("  PrettyMethod: %p", (void *) pretty_method_);

        return true;
    }

    void *SymbolResolver::FindSymbol(const char *name) {
        if (!libart_handle_ || !name) {
            return nullptr;
        }
        ALOGD("FindSymbol:%s", name);

        // 检查缓存
        {
            std::lock_guard<std::mutex> lock(cache_mutex_);
            auto it = symbol_cache_.find(name);
            if (it != symbol_cache_.end()) {
                ALOGD("FindSymbol:hit cache %s", name);
                return it->second;
            }
        }
        // 查找符号
        void *sym = shadowhook_dlsym(libart_handle_, name);
        if (sym == nullptr) {
            sym = shadowhook_dlsym_dynsym(libart_handle_, name);
        }
        if (sym == nullptr) {
            sym = shadowhook_dlsym_symtab(libart_handle_, name);
        }
        // 缓存结果 (包括nullptr)
        {
            std::lock_guard<std::mutex> lock(cache_mutex_);
            symbol_cache_[name] = sym;
        }

        if (!sym) {
            ALOGE("Symbol not found: %s", name);
        } else {
            ALOGD("FindSymbol:find %s", name);
        }
        return sym;
    }

    void *SymbolResolver::FindSymbolWithFallback(const std::initializer_list<const char *> &names) {
        for (const char *name: names) {
            void *sym = FindSymbol(name);
            if (sym) {
                return sym;
            }
        }
        return nullptr;
    }

    std::string SymbolResolver::MethodToString(void *art_method) const {
        if (!pretty_method_ || !art_method) {
            return "";
        }

        try {
            return pretty_method_(art_method, true);
        } catch (...) {
            return "<error>";
        }
    }

} // namespace atrace

