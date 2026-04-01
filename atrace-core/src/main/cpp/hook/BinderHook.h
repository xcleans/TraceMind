#pragma once

#include "HookPlugin.h"

namespace atrace {

class BinderHook : public PLTHookPlugin {
public:
    static BinderHook& Instance();

    const char* GetId() const override { return "binder"; }
    const char* GetName() const override { return "Binder IPC Trace"; }
    bool IsSupported(int sdk_version, const char* arch) const override;

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

private:
    BinderHook() = default;
};

} // namespace atrace
