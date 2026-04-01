plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.compose.compiler)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.test.trace"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "com.test.trace"
        minSdk = 23
        targetSdk =libs.versions.targetSdk.get().toInt()
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a"/*, "x86_64", "x86"*/)
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }

        debug {
            isJniDebuggable = true
            isProfileable=true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.fromTarget(libs.versions.kotlinJvmTarget.get()))
        }
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    // libs 目录下的 JAR 参与编译并打进 APK
    implementation(fileTree(mapOf("dir" to "src/main/libs", "include" to listOf("*.jar"))))

    // ATrace SDK：debug 用 core 实现，release 用 noop 空实现（无 native 开销）
    implementation(project(":atrace-api"))
    implementation(project(":atrace-core"))
//    implementation("com.bytedance.btrace:rhea-inhouse:3.0.0")

    // AndroidX
    implementation(libs.core.ktx)
    implementation(libs.appcompat)
    implementation(libs.activity.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.ui)
    implementation(libs.material3)
    implementation(libs.foundation)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.recyclerview)
    debugImplementation(libs.ui.tooling)

    // Test
    testImplementation(libs.junit)
    androidTestImplementation(libs.ext.junit)
    androidTestImplementation(libs.espresso.core)
}
