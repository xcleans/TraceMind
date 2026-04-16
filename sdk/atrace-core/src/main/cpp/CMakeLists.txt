cmake_minimum_required(VERSION 3.22)
project(atrace VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# JVMTI 相关路径
#set(ATRACE_JVMTI_INCLUDES ${CMAKE_CURRENT_SOURCE_DIR}/third_party/jvmti)

# JvmtiDebugHelper.cpp 编译进 libatrace.so（debuggable bypass，供其他调试场景使用）
#set(ATRACE_JVMTI_HELPER_SOURCES
#    jvmti/JvmtiDebugHelper.cpp
#)

# 源文件
set(ATRACE_SOURCES
    # 核心模块
    core/TraceEngine.cpp
    core/BufferManager.cpp
    core/StackSampler.cpp
    core/SymbolResolver.cpp
    
    # 数据结构
    buffer/LockFreeRingBuffer.cpp
    buffer/SampleRecord.cpp
    
    # Hook 框架
    hook/HookPlugin.cpp
    hook/JNIMethodHook.cpp
    hook/BinderHook.cpp
    hook/GCHook.cpp
    hook/LockHook.cpp
    hook/JNICallHook.cpp
    hook/LoadLibHook.cpp
    hook/IOHook.cpp
    hook/MsgQueueHook.cpp
    hook/ArtMethodInstrumentation.cpp
    
    # Alloc Hook
    hook/alloc/AllocCommon.cpp
    hook/alloc/Checkpoint.cpp
    hook/alloc/ThreadListHook.cpp
    hook/alloc/AllocHook.cpp
    hook/alloc/AllocHookPlugin.cpp
    
    # 工具类
    utils/time_utils.cpp
    utils/thread_utils.cpp
    utils/dl_utils.cpp
    
    # JNI接口
    jni/atrace_jni.cpp
    jni/engine_jni.cpp
    jni/plugin_jni.cpp
)

# 创建共享库
add_library(atrace SHARED ${ATRACE_SOURCES})

# 头文件路径
target_include_directories(atrace PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${ATRACE_JVMTI_INCLUDES}
)

# 链接ShadowHook
find_package(shadowhook REQUIRED CONFIG)

# 链接库
target_link_libraries(atrace
    log
    android
    shadowhook::shadowhook
)

# 编译选项
target_compile_options(atrace PRIVATE
    -Wall
    -Wextra
    -Werror=return-type
    -fvisibility=hidden
    -fexceptions        # 启用 C++ 异常
    -frtti              # 启用 RTTI (异常需要)
)

# Debug 配置
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    target_compile_definitions(atrace PRIVATE ATRACE_DEBUG=1)
endif()

# 动态插桩已改为 Hook ArtMethod（ArtMethodInstrumentation），不再构建 libatrace_agent.so

