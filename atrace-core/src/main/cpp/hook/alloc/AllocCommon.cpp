/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "AllocCommon.h"

namespace atrace {
namespace alloc {

static AllocContext g_alloc_context;

AllocContext& GetAllocContext() {
    return g_alloc_context;
}

} // namespace alloc
} // namespace atrace

