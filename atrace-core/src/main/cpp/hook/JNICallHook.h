#pragma once

#include "HookPlugin.h"

namespace atrace {

class JNICallHook : public PLTHookPlugin {
public:
    static JNICallHook& Instance();

    const char* GetId() const override { return "jni"; }
    const char* GetName() const override { return "JNI Call Trace"; }
    bool IsSupported(int sdk_version, const char* arch) const override;

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

    void SetSdkVersion(int sdk);

private:
    JNICallHook() = default;
};

} // namespace atrace
