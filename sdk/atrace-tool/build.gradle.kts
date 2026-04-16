plugins {
    alias(libs.plugins.kotlin.jvm)
    application
}

group = "com.aspect.atrace"
version = "1.0.0"

//repositories {
//    mavenCentral()
//}

dependencies {
    implementation(libs.kotlin.stdlib)

    implementation("org.json:json:20251224")
    implementation("commons-io:commons-io:2.15.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-cli:0.3.6")
    implementation("com.google.protobuf:protobuf-java:4.29.3")
}

application {
    mainClass.set("com.aspect.atrace.tool.MainKt")
}

tasks.jar {
    manifest {
        attributes(
            "Main-Class" to "com.aspect.atrace.tool.MainKt",
            "Manifest-Version" to version
        )
    }
    
    // 打包所有依赖到 fat jar
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(configurations.runtimeClasspath.get().map { if (it.isDirectory) it else zipTree(it) })
}

kotlin {
    jvmToolchain(21)
}

sourceSets {
    main {
        java.exclude("perfetto/protos/PerfettoTrace.java")
    }
}

// ── provision 部署任务 ─────────────────────────────────────────────────────────
// 将 fat JAR 复制到 atrace-provision/atrace_provision/bundled_bin/atrace-tool.jar
// （与 Python 包一起分发，由 AtraceToolProvider 解析）。
// 用法:
//   ./gradlew :atrace-tool:deployToMcp          # 仅复制 JAR
//   ./gradlew deployMcp                         # 根项目便捷任务（同上）
val provisionBundledBin = rootProject.file("platform/atrace-provision/atrace_provision/bundled_bin")

tasks.register<Copy>("deployToMcp") {
    group = "distribution"
    description = "Copy atrace-tool fat-JAR to atrace-provision bundled_bin for distribution"
    dependsOn(tasks.jar)

    from(tasks.jar.get().archiveFile)
    into(provisionBundledBin)
    // 固定文件名：去掉版本号，便于 AtraceToolProvider 定位
    rename { "atrace-tool.jar" }

    doFirst {
        provisionBundledBin.mkdirs()
    }
    doLast {
        val jar = provisionBundledBin.resolve("atrace-tool.jar")
        println("✅ atrace-tool deployed → ${jar.absolutePath} (${jar.length() / 1024}KB)")
        println("   Shipped with atrace-provision (bundled_bin/)")
    }
}

