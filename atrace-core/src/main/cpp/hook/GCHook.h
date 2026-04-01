#pragma once

#include "HookPlugin.h"

namespace atrace {

class GCHook : public PLTHookPlugin {
public:
    static GCHook& Instance();

    const char* GetId() const override { return "gc"; }
    const char* GetName() const override { return "GC Wait Trace"; }
    bool IsSupported(int sdk_version, const char* arch) const override;

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

private:
    GCHook() = default;
};

} // namespace atrace
