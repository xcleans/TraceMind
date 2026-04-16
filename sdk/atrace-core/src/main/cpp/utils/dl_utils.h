/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 动态库加载工具
 * 绕过 Android N+ 的 dlopen 限制
 */
#pragma once

#include <dlfcn.h>

namespace atrace {

/**
 * 打开动态库 (绕过 linker namespace 限制)
 *
 * @param name 库名称 (如 "libart.so")
 * @return 库句柄，失败返回 nullptr
 */
void* dl_open(const char* name);

/**
 * 查找符号
 *
 * @param handle 库句柄
 * @param symbol 符号名称
 * @return 符号地址，失败返回 nullptr
 */
void* dl_sym(void* handle, const char* symbol);

/**
 * 关闭动态库
 */
void dl_close(void* handle);

/**
 * 获取错误信息
 */
const char* dl_error();

} // namespace atrace

