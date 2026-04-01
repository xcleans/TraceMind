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

// SDK 模块
include(":atrace-api")           // 公开API层
include(":atrace-core")          // 核心实现

// 工具模块
include(":atrace-tool")          // PC端命令行工具

// 示例应用
include(":sample")

// SandHook local source modules (offline/source dependency)
include(":sandhook-annotation")
project(":sandhook-annotation").projectDir = file("third_party/SandHook/annotation")

include(":sandhook-hooklib")
project(":sandhook-hooklib").projectDir = file("third_party/SandHook/hooklib")

include(":sandhook-nativehook")
project(":sandhook-nativehook").projectDir = file("third_party/SandHook/nativehook")

