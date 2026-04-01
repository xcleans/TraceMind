/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include "../HookPlugin.h"
#include "AllocHook.h"

namespace atrace {

class AllocHookPlugin : public HookPlugin {
public:
    static AllocHookPlugin& Instance();

    const char* GetId() const override { return "alloc"; }
    const char* GetName() const override { return "Object Allocation Trace"; }

    bool IsSupported(int sdk_version, const char* arch) const override {
        return sdk_version >= 26;
    }

    void SetSdkVersion(int sdk) { sdk_version_ = sdk; }

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

    alloc::AllocStats& GetStats() { return alloc::GetAllocStats(); }
    void ResetStats() { alloc::GetAllocStats().Reset(); }

private:
    AllocHookPlugin() = default;
    int sdk_version_ = 0;
};

} // namespace atrace
