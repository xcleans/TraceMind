/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * 动态方法插桩：per-method entry_point_from_quick_compiled_code_ 替换。
 *
 * 三种使用方式：
 *   1. 精确 Hook — HookMethod(class, method, sig) 替换 entry_point
 *   2. WatchList — AddWatchedRule 注册规则 + ScanClassAndHook 按规则自动 hook 匹配方法
 *   3. 类扫描 — ScanClassAndHook(jclass) 枚举类方法，匹配 WatchList 规则后自动 hook
 *
 * 不使用 ShadowHook inline hook（在 MIUI/PAC 设备上会 SIGSEGV）。
 */
#pragma once

#include <jni.h>
#include <string>
#include <vector>

namespace atrace {

class ArtMethodInstrumentation {
public:
    /** 初始化：探测 ArtMethod 布局，不安装任何全局 hook */
    static bool Install(JNIEnv* env);

    /** 卸载所有 per-method hook，恢复原始 entry_point */
    static void Uninstall();

    static bool IsInstalled() { return installed_; }

    // ── WatchList API ─────────────────────────────────────────────────────────
    static void AddWatchedRule(const std::string& scope, const std::string& value);
    static void RemoveWatchedRule(const std::string& pattern);
    static void ClearWatchedRules();
    static int WatchedRuleCount();
    static std::vector<std::string> GetWatchedRules();

    // ── 精确 Hook API（直接替换目标方法 entry_point）──────────────────────────
    /**
     * Hook 指定方法：替换其 entry_point_from_quick_compiled_code_ 为 trampoline。
     * trampoline 在方法进入时记录事件，然后跳转到原始 entry。
     *
     * @param class_name  JNI 格式类名（如 "com/example/Foo"）
     * @param method_name 方法名
     * @param signature   JNI 方法签名（如 "(I)V"）
     * @param is_static   是否静态方法
     * @return 是否成功
     */
    static bool HookMethod(JNIEnv* env, const char* class_name,
                           const char* method_name, const char* signature,
                           bool is_static);

    /** 恢复指定方法的原始 entry_point */
    static void UnhookMethod(JNIEnv* env, const char* class_name,
                             const char* method_name, const char* signature,
                             bool is_static);

    // ── 类扫描自动 Hook API ──────────────────────────────────────────────────
    /**
     * 枚举 cls 的全部 declared methods，逐一与 WatchList 规则匹配，
     * 匹配的方法自动 HookMethodEntry。
     * @return 本次新增 hook 数量
     */
    static int ScanClassAndHook(JNIEnv* env, jclass cls);

private:
    static bool installed_;
};

} // namespace atrace
