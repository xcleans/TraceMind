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

// ── MCP 部署任务 ──────────────────────────────────────────────────────────────
// 将 fat JAR 复制到 atrace-mcp/bin/atrace-tool.jar，使 MCP 服务器可以独立分发。
// 用法:
//   ./gradlew :atrace-tool:deployToMcp          # 仅复制 JAR
//   ./gradlew deployMcp                         # 根项目便捷任务（同上）
val mcpBinDir = rootProject.file("atrace-mcp/bin")

tasks.register<Copy>("deployToMcp") {
    group = "distribution"
    description = "Copy atrace-tool fat-JAR to atrace-mcp/bin/ for standalone MCP distribution"
    dependsOn(tasks.jar)

    from(tasks.jar.get().archiveFile)
    into(mcpBinDir)
    // 固定文件名：去掉版本号，让 tool_provisioner.py 直接定位
    rename { "atrace-tool.jar" }

    doFirst {
        mcpBinDir.mkdirs()
    }
    doLast {
        val jar = mcpBinDir.resolve("atrace-tool.jar")
        println("✅ atrace-tool deployed → ${jar.absolutePath} (${jar.length() / 1024}KB)")
        println("   MCP can now be distributed independently from atrace-mcp/")
    }
}

