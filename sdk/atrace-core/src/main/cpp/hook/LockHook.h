#pragma once

#include "HookPlugin.h"

namespace atrace {

class LockHook : public HookPlugin {
public:
    static LockHook& Instance();

    const char* GetId() const override { return "lock"; }
    const char* GetName() const override { return "Lock Contention Trace"; }
    bool IsSupported(int sdk_version, const char* /*arch*/) const override {
        return sdk_version >= 26;
    }

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

    void SetWakeupEnabled(bool enabled);
    void SetMainThread(JNIEnv* env, jobject mainThread);

private:
    LockHook() = default;
};

} // namespace atrace
