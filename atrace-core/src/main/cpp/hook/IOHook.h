#pragma once

#include "HookPlugin.h"

namespace atrace {

class IOHook : public PLTHookPlugin {
public:
    static IOHook& Instance();

    const char* GetId() const override { return "io"; }
    const char* GetName() const override { return "IO Trace"; }
    bool IsSupported(int sdk_version, const char* /*arch*/) const override {
        return sdk_version >= 26;
    }

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

private:
    IOHook() = default;
};

} // namespace atrace
