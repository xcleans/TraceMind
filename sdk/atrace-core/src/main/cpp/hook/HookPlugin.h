/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Hook 插件基础设施
 * 
 * 设计原则:
 * 1. 每个 Plugin 对应一个 Hook 功能
 * 2. 通过 Init/Enable/Disable/Destroy 生命周期管理
 * 3. 统一的采样请求接口
 */
#pragma once

#include <jni.h>
#include <cstdint>

namespace atrace {

/**
 * Hook 插件基类
 * 
 * 所有 Hook 插件都应该继承此类，通过 Init/Enable/Disable/Destroy 管理生命周期
 */
class HookPlugin {
public:
    virtual ~HookPlugin() = default;

    virtual const char* GetId() const = 0;
    virtual const char* GetName() const = 0;
    virtual bool IsSupported(int sdk_version, const char* arch) const = 0;

    /**
     * 初始化 Hook
     * 
     * @param env JNI 环境 (可为 nullptr)
     * @return 是否成功
     */
    virtual bool Init(JNIEnv* env) = 0;

    /**
     * 启用 Hook
     */
    virtual void Enable() = 0;

    /**
     * 禁用 Hook
     */
    virtual void Disable() = 0;

    /**
     * 销毁 Hook
     */
    virtual void Destroy() = 0;
};

/**
 * PLT Hook 插件基类
 * 
 * 用于 Hook 动态库中的函数
 */
class PLTHookPlugin : public HookPlugin {
protected:
    /**
     * 安装 PLT Hook
     * 
     * @param lib_name 库名 (如 "libart.so")
     * @param symbol 符号名 (mangled)
     * @param replacement 替换函数
     * @param[out] stub Hook stub 用于调用原函数
     * @return 是否成功
     */
    bool InstallPLTHook(const char* lib_name, const char* symbol, 
                        void* replacement, void** stub);

    /**
     * 卸载 PLT Hook
     */
    void UninstallPLTHook(void* stub);
};

} // namespace atrace

