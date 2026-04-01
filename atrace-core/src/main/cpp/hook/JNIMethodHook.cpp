/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
#include "JNIMethodHook.h"

#include <atomic>
#include <android/api-level.h>
#define ATRACE_LOG_TAG "JNIHook"
#include "utils/atrace_log.h"

namespace atrace {
    namespace jni_hook {

// JNI 入口点在 ArtMethod 结构体中的偏移索引
        static int g_jni_entrance_index = -1;

/**
 * 获取 ArtMethod 指针
 * https://juejin.cn/post/7355798869109997587
 * Android 11+ 需要通过反射获取 artMethod 字段
 * Android 10 及以下可以直接使用 FromReflectedMethod
 */
        void **GetArtMethod(JNIEnv *env, jobject method) {
            if (!env || !method) return nullptr;

            if (android_get_device_api_level() >= __ANDROID_API_R__) {
                jclass executable_class = env->FindClass("java/lang/reflect/Executable");
                if (!executable_class || env->ExceptionCheck()) {
                    env->ExceptionClear();
                    return nullptr;
                }

                jfieldID art_method_field = env->GetFieldID(executable_class, "artMethod", "J");
                if (!art_method_field || env->ExceptionCheck()) {
                    env->ExceptionClear();
                    env->DeleteLocalRef(executable_class);
                    return nullptr;
                }

                jlong art_method = env->GetLongField(method, art_method_field);
                env->DeleteLocalRef(executable_class);
                if (env->ExceptionCheck()) {
                    env->ExceptionClear();
                    return nullptr;
                }
                if (art_method == 0) return nullptr;
                return reinterpret_cast<void **>(art_method);
            } else {
                jmethodID mid = env->FromReflectedMethod(method);
                if (!mid || env->ExceptionCheck()) {
                    env->ExceptionClear();
                    return nullptr;
                }
                return reinterpret_cast<void **>(mid);
            }
        }

/**
 * 获取 ArtMethod 指针 (通过 jmethodID)
 */
        static void **GetArtMethodFromId(JNIEnv *env, jclass cls, jmethodID method_id, bool is_static) {
            if (android_get_device_api_level() >= 30) {
                // Android 11+: 需要先转换为反射对象
                jobject method = env->ToReflectedMethod(cls, method_id, is_static);
                if (!method) {
                    return nullptr;
                }

                jclass executable_class = env->FindClass("java/lang/reflect/Executable");
                jfieldID art_method_field = env->GetFieldID(executable_class, "artMethod", "J");
                jlong art_method = env->GetLongField(method, art_method_field);

                env->DeleteLocalRef(method);
                return reinterpret_cast<void **>(art_method);
            } else {
                // Android 10 及以下: jmethodID 就是 ArtMethod*
                return reinterpret_cast<void **>(method_id);
            }
        }

        //https://github.com/sanfengAndroid/fake-linker
        //Java Native Hook
        bool Init(JNIEnv *env, jobject sample_method, void *sample_jni_func) {
            if (g_jni_entrance_index >= 0) {
                return true;  // 已初始化
            }
            //获取Native 方法对应的ART方法地址
            void **art_method = GetArtMethod(env, sample_method);
            if (!art_method) {
                ALOGE("Failed to get ArtMethod pointer");
                return false;
            }

            // 遍历 ArtMethod 结构体，查找 JNI 入口点的偏移
            // 通常在前 50 个指针大小的位置内
            for (int i = 0; i < 50; ++i) {
                //直接与我们自己注册的 native 方法地址相比较
                if (reinterpret_cast<void *>(art_method[i]) == sample_jni_func) {
                    g_jni_entrance_index = i;
                    ALOGI("JNI entrance index found: %d", i);
                    return true;
                }
            }

            ALOGE("Failed to find JNI entrance index");
            return false;
        }

        bool IsInitialized() {
            return g_jni_entrance_index >= 0;
        }

/**
 * 内部 Hook 实现
 */
        static void HookInternal(void **art_method, void *new_entrance, void **origin_entrance) {
            if (g_jni_entrance_index < 0 || !art_method || !origin_entrance) {
                ALOGE("HookInternal: invalid params, index=%d", g_jni_entrance_index);
                return;
            }

            void *old_entrance = art_method[g_jni_entrance_index];

            // 检查是否已经 Hook 或入口无效
            if (old_entrance == new_entrance || old_entrance == nullptr) {
                ALOGD("HookInternal: already hooked or null entrance");
                return;
            }

            // 使用原子操作替换入口点
            std::atomic<void *> *atomic_entry =
                    reinterpret_cast<std::atomic<void *> *>(art_method + g_jni_entrance_index);

            if (std::atomic_compare_exchange_weak_explicit(
                    atomic_entry,
                    &old_entrance,
                    new_entrance,
                    std::memory_order_relaxed,
                    std::memory_order_acquire)) {
                *origin_entrance = old_entrance;
                ALOGD("HookInternal: success, old=%p, new=%p", old_entrance, new_entrance);
            } else {
                ALOGD("HookInternal: CAS failed");
            }
        }

        void Hook(JNIEnv *env, jobject method, void *new_entrance, void **origin_entrance) {
            void **art_method = GetArtMethod(env, method);
            HookInternal(art_method, new_entrance, origin_entrance);
        }

        /**
         * Hook 一个 native 方法（已用 RegisterNatives 注册的 JNI 方法）。
         *
         * ⚠️ 仅适用于 native 方法（声明了 `native` 关键字且已完成 JNI 注册）。
         *    对纯 Java 方法（如 Object.wait、Unsafe.park），ART 的调用路径是
         *    quick_code → interpreter，不经过 jni_entrance 字段，
         *    直接替换 jni_entrance 会让 origin_entrance 保存一个 DEX 字节码地址，
         *    回调时执行不可执行内存 → SIGSEGV SEGV_ACCERR。
         *    纯 Java 方法请改用 RegisterNatives 重注册（见 HookJavaMethodViaRegisterNatives）。
         */
        void HookMethod(JNIEnv *env,
                const char *class_name,
                const char *method_name,
                const char *signature,
                void *new_entrance,
                void **origin_entrance) {
            jclass cls = env->FindClass(class_name);
            if (!cls) {
                env->ExceptionClear();
                ALOGE("HookMethod: class not found: %s", class_name);
                return;
            }

            jmethodID method_id = env->GetMethodID(cls, method_name, signature);
            if (!method_id) {
                env->ExceptionClear();
                ALOGE("HookMethod: method not found: %s#%s%s", class_name, method_name, signature);
                return;
            }

            void **art_method = GetArtMethodFromId(env, cls, method_id, false);
            if (!art_method) {
                ALOGE("HookMethod: cannot resolve ArtMethod for %s#%s%s", class_name, method_name, signature);
                return;
            }

            // 安全检查：jni_entrance 字段保存的地址应在 libart.so 或 libatrace.so
            // 范围内（即 native 代码）。DEX 字节码地址通常落在低地址区 /apex/**/*.jar，
            // 用 dladdr 可验证。简单地，若该字段为 null 则表示方法不是 native 方法。
            void *current = art_method[g_jni_entrance_index];
            if (current == nullptr) {
                ALOGE("HookMethod: %s#%s%s jni_entrance is null — this is not a native method. "
                      "Use HookJavaMethodViaRegisterNatives for pure Java methods.",
                      class_name, method_name, signature);
                return;
            }

            HookInternal(art_method, new_entrance, origin_entrance);

            ALOGI("HookMethod: %s#%s%s -> %p", class_name, method_name, signature, new_entrance);
        }

        /**
         * 通过 RegisterNatives 重注册来 hook 一个方法（适用于纯 Java 方法和 native 方法）。
         *
         * ART 规则：
         *   - native 方法通过 RegisterNatives 注册后，调用时 ART 经 jni_entrance 字段跳转。
         *   - 纯 Java 方法（如 Object.wait）本身不是 native，但可以把它"重新声明"为 native
         *     并用 RegisterNatives 注入，前提是目标类已经声明了同名 native 方法（如 core-oj.jar
         *     中 Object.wait 在 Android 8+ 已有 native 实现）。
         *
         * 对于 Object.wait / Unsafe.park / Object.notify 等方法，这是最安全的 hook 路径。
         *
         * @param origin_entrance  出参：保存原始 JNI 函数指针（可用于转发调用）。
         *                         注意：这里保存的是 JNI 函数指针，调用签名为
         *                         (JNIEnv*, jobject, ...) 而非 ART 内部 quick 签名。
         */
        bool HookJavaMethodViaRegisterNatives(JNIEnv *env,
                const char *class_name,
                const char *method_name,
                const char *signature,
                void *new_jni_func,
                void **origin_jni_func) {
            jclass cls = env->FindClass(class_name);
            if (!cls) {
                env->ExceptionClear();
                ALOGE("HookJavaNative: class not found: %s", class_name);
                return false;
            }

            bool is_static = false;
            jmethodID method_id = env->GetMethodID(cls, method_name, signature);
            if (!method_id) {
                env->ExceptionClear();
                // 也尝试静态方法
                method_id = env->GetStaticMethodID(cls, method_name, signature);
                if (!method_id) {
                    env->ExceptionClear();
                    ALOGE("HookJavaNative: method not found: %s#%s%s", class_name, method_name, signature);
                    return false;
                }
                is_static = true;
            }

            if (g_jni_entrance_index < 0) {
                ALOGE("HookJavaNative: JNI hook not initialized");
                return false;
            }

            void **art_method = GetArtMethodFromId(env, cls, method_id, is_static);
            if (!art_method) {
                ALOGE("HookJavaNative: cannot get ArtMethod for %s#%s", class_name, method_name);
                return false;
            }

            // 保存原始 jni_entrance（RegisterNatives 会更新这个字段）
            void *old_func = art_method[g_jni_entrance_index];
            if (origin_jni_func) {
                *origin_jni_func = old_func;
            }

            // RegisterNatives 替换：ART 会把 new_jni_func 写入 jni_entrance 字段
            JNINativeMethod method = { method_name, signature, new_jni_func };
            int ret = env->RegisterNatives(cls, &method, 1);
            if (ret != JNI_OK) {
                env->ExceptionClear();
                ALOGE("HookJavaNative: RegisterNatives failed for %s#%s%s (ret=%d)",
                      class_name, method_name, signature, ret);
                if (origin_jni_func) *origin_jni_func = nullptr;
                return false;
            }

            ALOGI("HookJavaNative: %s#%s%s -> %p (old=%p)",
                  class_name, method_name, signature, new_jni_func, old_func);
            return true;
        }

        void HookStaticMethod(JNIEnv *env,
                const char *class_name,
                const char *method_name,
                const char *signature,
                void *new_entrance,
                void **origin_entrance) {
            jclass cls = env->FindClass(class_name);
            if (!cls) {
                env->ExceptionClear();
                ALOGE("HookStaticMethod: class not found: %s", class_name);
                return;
            }

            jmethodID method_id = env->GetStaticMethodID(cls, method_name, signature);
            if (!method_id) {
                env->ExceptionClear();
                ALOGE("HookStaticMethod: method not found: %s#%s%s", class_name, method_name, signature);
                return;
            }

            void **art_method = GetArtMethodFromId(env, cls, method_id, true);
            HookInternal(art_method, new_entrance, origin_entrance);

            ALOGI("HookStaticMethod: %s#%s%s -> %p", class_name, method_name, signature, new_entrance);
        }

        void *GetStaticMethodEntrance(JNIEnv *env,
                const char *class_name,
                const char *method_name,
                const char *signature) {
            if (g_jni_entrance_index < 0) {
                return nullptr;
            }

            jclass cls = env->FindClass(class_name);
            if (!cls) {
                env->ExceptionClear();
                return nullptr;
            }

            jmethodID method_id = env->GetStaticMethodID(cls, method_name, signature);
            if (!method_id) {
                env->ExceptionClear();
                return nullptr;
            }

            void **art_method = GetArtMethodFromId(env, cls, method_id, true);
            if (!art_method) {
                return nullptr;
            }

            return art_method[g_jni_entrance_index];
        }

        void *GetMethodEntrance(JNIEnv *env,
                const char *class_name,
                const char *method_name,
                const char *signature) {
            if (g_jni_entrance_index < 0) {
                return nullptr;
            }

            jclass cls = env->FindClass(class_name);
            if (!cls) {
                env->ExceptionClear();
                return nullptr;
            }

            jmethodID method_id = env->GetMethodID(cls, method_name, signature);
            if (!method_id) {
                env->ExceptionClear();
                return nullptr;
            }

            void **art_method = GetArtMethodFromId(env, cls, method_id, false);
            if (!art_method) {
                return nullptr;
            }

            return art_method[g_jni_entrance_index];
        }

        int GetJniEntranceIndex() {
            return g_jni_entrance_index;
        }

        void **ResolveArtMethod(JNIEnv *env, const char *class_name,
                const char *method_name, const char *signature,
                bool is_static) {
            jclass cls = env->FindClass(class_name);
            if (!cls) {
                env->ExceptionClear();
                return nullptr;
            }
            jmethodID method_id = is_static
                    ? env->GetStaticMethodID(cls, method_name, signature)
                    : env->GetMethodID(cls, method_name, signature);
            if (!method_id) {
                env->ExceptionClear();
                return nullptr;
            }
            return GetArtMethodFromId(env, cls, method_id, is_static);
        }

    } // namespace jni_hook
} // namespace atrace

// ===== JNI 导出函数 =====

extern "C" {

// 占位函数，用于初始化时确定 JNI 入口偏移
JNIEXPORT void JNICALL
Java_com_aspect_atrace_core_JNIHookHelper_nativePlaceholder(JNIEnv *env, jclass clazz) {
    // 空函数，仅用于确定偏移
}

// 初始化 JNI Hook
JNIEXPORT jboolean JNICALL
Java_com_aspect_atrace_core_JNIHookHelper_nativeInit(JNIEnv *env, jclass clazz, jobject sample_method) {
    return atrace::jni_hook::Init(
            env,
            sample_method,
            reinterpret_cast<void *>(Java_com_aspect_atrace_core_JNIHookHelper_nativePlaceholder)
    );
}

} // extern "C"

