/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * JNI 方法级 Hook 工具
 * 用于 Hook Java 层声明的 native 方法
 */
#pragma once

#include <jni.h>

namespace atrace {
namespace jni_hook {

/**
 * 初始化 JNI Hook 机制
 *
 * 需要传入一个已知的 JNI 方法及其对应的 native 函数指针，
 * 用于确定 ArtMethod 中 entry_point_from_jni 的偏移量
 *
 * @param env JNI 环境
 * @param sample_method 一个已知的 native 方法的反射对象
 * @param sample_jni_func 该方法对应的 native 函数指针
 * @return 是否初始化成功
 */
bool Init(JNIEnv* env, jobject sample_method, void* sample_jni_func);

/**
 * 检查是否已初始化
 */
bool IsInitialized();

/**
 * Hook 一个 Java 方法 (通过反射对象)
 *
 * @param env JNI 环境
 * @param method Java 方法的反射对象
 * @param new_entrance 新的入口函数
 * @param origin_entrance 输出原始入口函数
 */
void Hook(JNIEnv* env, jobject method, void* new_entrance, void** origin_entrance);

/**
 * Hook 一个已注册的 JNI native 方法（通过 jni_entrance 字段替换）。
 *
 * ⚠️  仅限 native 方法（ArtMethod.jni_entrance != null）。
 *     纯 Java 方法（如 Object.wait、Unsafe.park）请使用
 *     HookJavaMethodViaRegisterNatives，否则会产生 SIGSEGV SEGV_ACCERR。
 */
void HookMethod(JNIEnv* env, 
                const char* class_name, 
                const char* method_name,
                const char* signature, 
                void* new_entrance, 
                void** origin_entrance);

/**
 * 通过 RegisterNatives 重注册来 hook 方法（适用于纯 Java 方法和 native 方法）。
 *
 * 对 Object.wait / Object.notify / Unsafe.park / Unsafe.unpark 等在
 * Android 8+ 已有 native 实现的方法，这是唯一安全的 hook 路径：
 *   ART 调用路径：quick_code → jni_entrance（由 RegisterNatives 填充）
 *
 * @param new_jni_func     新的 JNI 函数指针，签名必须匹配 (JNIEnv*, jobject/jclass, ...)
 * @param origin_jni_func  出参：旧的 JNI 函数指针（来自 jni_entrance 字段）
 * @return true 表示 RegisterNatives 成功
 */
bool HookJavaMethodViaRegisterNatives(JNIEnv* env,
                                      const char* class_name,
                                      const char* method_name,
                                      const char* signature,
                                      void* new_jni_func,
                                      void** origin_jni_func);

/**
 * Hook 一个静态方法
 *
 * @param env JNI 环境
 * @param class_name 类名
 * @param method_name 方法名
 * @param signature 方法签名
 * @param new_entrance 新的入口函数
 * @param origin_entrance 输出原始入口函数
 */
void HookStaticMethod(JNIEnv* env, 
                      const char* class_name, 
                      const char* method_name,
                      const char* signature, 
                      void* new_entrance, 
                      void** origin_entrance);

/**
 * 获取静态方法的入口点
 *
 * @param env JNI 环境
 * @param class_name 类名
 * @param method_name 方法名
 * @param signature 方法签名
 * @return 方法入口点，失败返回 nullptr
 */
void* GetStaticMethodEntrance(JNIEnv* env, 
                              const char* class_name,
                              const char* method_name, 
                              const char* signature);

/**
 * 获取实例方法的入口点
 */
void* GetMethodEntrance(JNIEnv* env, 
                        const char* class_name,
                        const char* method_name, 
                        const char* signature);

/**
 * 获取 entry_point_from_jni_ 在 ArtMethod 中的偏移索引（void** 步长）
 * @return >= 0 表示已初始化，-1 表示未初始化
 */
int GetJniEntranceIndex();

/**
 * 从反射 Method/Constructor 对象获取 ArtMethod 指针。
 * Android 11+ 读取 Executable.artMethod 字段；10 及以下用 FromReflectedMethod。
 */
void** GetArtMethod(JNIEnv* env, jobject reflected_method);

/**
 * 获取 ArtMethod 指针（通过类名+方法名+签名）
 * @return ArtMethod 指针（void**），失败返回 nullptr
 */
void** ResolveArtMethod(JNIEnv* env, const char* class_name,
                        const char* method_name, const char* signature,
                        bool is_static);

} // namespace jni_hook
} // namespace atrace

