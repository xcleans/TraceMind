/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * JNI 入口和初始化
 */
#include <jni.h>
#define ATRACE_LOG_TAG "JNI"
#include "utils/atrace_log.h"

namespace atrace {

/**
 * 绕过 Hidden API 限制
 */
static void exempt_hidden_api(JNIEnv* env) {
    // 获取 VMRuntime
    jclass vmRuntimeClass = env->FindClass("dalvik/system/VMRuntime");
    if (!vmRuntimeClass) {
        env->ExceptionClear();
        ALOGE("VMRuntime class not found");
        return;
    }

    jmethodID getRuntime = env->GetStaticMethodID(
        vmRuntimeClass, "getRuntime", "()Ldalvik/system/VMRuntime;");
    if (!getRuntime) {
        env->ExceptionClear();
        return;
    }

    jobject runtime = env->CallStaticObjectMethod(vmRuntimeClass, getRuntime);
    if (!runtime) {
        env->ExceptionClear();
        return;
    }

    // 调用 setHiddenApiExemptions
    jmethodID setExemptions = env->GetMethodID(
        vmRuntimeClass, "setHiddenApiExemptions", "([Ljava/lang/String;)V");
    if (!setExemptions) {
        env->ExceptionClear();
        return;
    }

    // 设置豁免前缀 "L" (所有类)
    jclass stringClass = env->FindClass("java/lang/String");
    jobjectArray exemptions = env->NewObjectArray(1, stringClass, nullptr);
    jstring prefix = env->NewStringUTF("L");
    env->SetObjectArrayElement(exemptions, 0, prefix);

    env->CallVoidMethod(runtime, setExemptions, exemptions);
    
    if (env->ExceptionCheck()) {
        env->ExceptionClear();
        ALOGE("setHiddenApiExemptions failed");
    } else {
        ALOGI("Hidden API exemptions set");
    }

    env->DeleteLocalRef(prefix);
    env->DeleteLocalRef(exemptions);
    env->DeleteLocalRef(runtime);
    env->DeleteLocalRef(vmRuntimeClass);
}

} // namespace atrace

/**
 * JNI_OnLoad
 */
JNIEXPORT jint JNI_OnLoad(JavaVM* vm, void* /*reserved*/) {
    JNIEnv* env;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) {
        return JNI_ERR;
    }

    // 绕过 Hidden API 限制
    atrace::exempt_hidden_api(env);

    ALOGI("ATrace native library loaded");
    return JNI_VERSION_1_6;
}

