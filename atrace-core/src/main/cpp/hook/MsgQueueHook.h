#pragma once

#include "HookPlugin.h"

namespace atrace {

class MsgQueueHook : public HookPlugin {
public:
    static MsgQueueHook& Instance();

    const char* GetId() const override { return "msgqueue"; }
    const char* GetName() const override { return "MessageQueue Trace"; }
    bool IsSupported(int sdk_version, const char* /*arch*/) const override {
        return sdk_version >= 26;
    }

    bool Init(JNIEnv* env) override;
    void Enable() override;
    void Disable() override;
    void Destroy() override;

private:
    MsgQueueHook() = default;
};

} // namespace atrace
