pluginManagement {
    repositories {
        google()
        mavenCentral()
//        maven(url = "https://repo.spring.io/libs-release/")
        gradlePluginPortal()
    }
    plugins {
        id("org.jetbrains.kotlin.android") version "2.3.10"
    }
}
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://jitpack.io") }
    }
}


rootProject.name = "TraceMind"

fun sdkModuleDir(name: String) =
    file("sdk/$name").takeIf { it.isDirectory } ?: file(name)

// SDK 模块
include(":atrace-api")           // 公开API层
project(":atrace-api").projectDir = sdkModuleDir("atrace-api")
include(":atrace-core")          // 核心实现
project(":atrace-core").projectDir = sdkModuleDir("atrace-core")

// 工具模块
include(":atrace-tool")          // PC端命令行工具
project(":atrace-tool").projectDir = sdkModuleDir("atrace-tool")

// 示例应用
include(":sample")
project(":sample").projectDir = sdkModuleDir("sample")

// SandHook local source modules (offline/source dependency)
include(":sandhook-annotation")
project(":sandhook-annotation").projectDir = file("sdk/third_party/SandHook/annotation")

include(":sandhook-hooklib")
project(":sandhook-hooklib").projectDir = file("sdk/third_party/SandHook/hooklib")

include(":sandhook-nativehook")
project(":sandhook-nativehook").projectDir = file("sdk/third_party/SandHook/nativehook")

