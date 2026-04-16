/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "AllocHookPlugin.h"
#define ATRACE_LOG_TAG "AllocPlugin"
#include "utils/atrace_log.h"

namespace atrace {

AllocHookPlugin& AllocHookPlugin::Instance() {
    static AllocHookPlugin instance;
    return instance;
}

bool AllocHookPlugin::Init(JNIEnv* /* env */) {
    if (!alloc::InitAllocHook(sdk_version_)) {
        ALOGE("AllocHook init failed (sdk=%d)", sdk_version_);
        return false;
    }
    ALOGI("AllocHook initialized (sdk=%d)", sdk_version_);
    return true;
}

void AllocHookPlugin::Enable() {
    alloc::SetAllocHookEnabled(true);
}

void AllocHookPlugin::Disable() {
    alloc::SetAllocHookEnabled(false);
}

void AllocHookPlugin::Destroy() {
    alloc::DestroyAllocHook();
}

} // namespace atrace
