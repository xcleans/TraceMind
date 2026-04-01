import com.android.build.api.dsl.LibraryExtension

plugins {
    id("com.android.library")
    alias(libs.plugins.kotlin.android)
}
android {
    namespace = "com.aspect.atrace.core"
    compileSdk = libs.versions.compileSdk.get().toInt()
    ndkVersion = libs.versions.ndkVersion.get()

    defaultConfig {
        minSdk = libs.versions.minSdk.get().toInt()
        consumerProguardFiles("consumer-rules.pro")

        externalNativeBuild {
            cmake {
                arguments(
                    "-DANDROID_STL=c++_shared",
                    "-DANDROID_TOOLCHAIN=clang"
                )
                cppFlags("-std=c++20", "-fvisibility=hidden")
                // 支持所有架构
                abiFilters("arm64-v8a", "armeabi-v7a"/*, "x86_64", "x86"*/)
            }
        }
    }

    publishing {
        singleVariant("release")
    }
    buildTypes {
        release {
            isMinifyEnabled = false
        }
        debug {
            isJniDebuggable = true
            externalNativeBuild {
                cmake {
                    cppFlags("-DATRACE_DEBUG")
                }
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = libs.versions.cmake.get()
        }
    }

    compileOptions {
        val javaVersion = JavaVersion.toVersion(libs.versions.javaVersion.get())
        sourceCompatibility = javaVersion
        targetCompatibility = javaVersion
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.fromTarget(libs.versions.kotlinJvmTarget.get()))
        }
    }

    packaging {
        jniLibs {
            excludes += "**/libshadowhook.so"
        }
    }

    buildFeatures {
        prefab = true
    }
}

dependencies {
    api(project(":atrace-api"))
    implementation(libs.annotation)
    api(libs.shadowhook)
    implementation(libs.nanohttpd)
    implementation(project(":sandhook-hooklib"))
    implementation(project(":sandhook-nativehook"))
    implementation(libs.dexmaker)
}

apply(from = rootProject.file("gradle/publish-atrace.gradle.kts"))

