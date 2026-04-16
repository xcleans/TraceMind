#pragma once

#include "HookPlugin.h"

namespace atrace {

class LoadLibHook : public PLTHookPlugin {
public:
    static LoadLibHook& Instance();

    const char* GetId() const override { return "loadlib"; }
    const char* GetName() const override { return "Library Load Trace"; }
    bool IsSupported(int sdk_version, const char* arch) const override;

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

private:
    LoadLibHook() = default;
};

} // namespace atrace
