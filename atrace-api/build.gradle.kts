plugins {
    id("com.android.library")
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.aspect.atrace.api"
    compileSdk = libs.versions.compileSdk.get().toInt()

    defaultConfig {
        minSdk = libs.versions.minSdk.get().toInt()
        consumerProguardFiles("consumer-rules.pro")
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
    buildTypes {
        getByName("debug") {
            isJniDebuggable = true
        }
    }
    publishing {
        singleVariant("release")
    }
}

dependencies {
    implementation(libs.annotation)
    implementation(libs.androidx.core.ktx)
}

apply(from = rootProject.file("gradle/publish-atrace.gradle.kts"))

