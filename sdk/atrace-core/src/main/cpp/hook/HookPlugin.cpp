/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "HookPlugin.h"

#include <shadowhook.h>
#define ATRACE_LOG_TAG "Hook"
#include "utils/atrace_log.h"

namespace atrace {

bool PLTHookPlugin::InstallPLTHook(const char* lib_name, const char* symbol,
                                    void* replacement, void** stub) {
    if (!lib_name || !symbol || !replacement || !stub) {
        return false;
    }

    *stub = shadowhook_hook_sym_name(lib_name, symbol, replacement, nullptr);
    
    if (*stub) {
        ALOGI("PLT Hook installed: %s @ %s", symbol, lib_name);
        return true;
    } else {
        ALOGE("PLT Hook failed: %s @ %s, error=%s", 
              symbol, lib_name, shadowhook_to_errmsg(shadowhook_get_errno()));
        return false;
    }
}

void PLTHookPlugin::UninstallPLTHook(void* stub) {
    if (stub) {
        shadowhook_unhook(stub);
    }
}

} // namespace atrace

