// Top-level build file
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.jvm) apply false  // Kotlin JVM 插件（用于 atrace-tool）
    alias(libs.plugins.kotlin.android) apply false  // Kotlin Android 插件（用于 sample）
    alias(libs.plugins.compose.compiler) apply false  // Compose 编译器（用于 sample）
}


//composeCompiler {
//    reportsDestination = layout.buildDirectory.dir("compose_compiler")
//    stabilityConfigurationFile = rootProject.layout.projectDirectory.file("stability_config.conf")
//}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}

// 发布 ATrace SDK 库（atrace-api, core, noop, plugins），不包含 sample / atrace-tool
tasks.register("publishToMavenLocal") {
    group = "publishing"
    description = "Publishes ATrace SDK to Maven local (~/.m2/repository)"
    dependsOn(
        ":atrace-api:publishReleasePublicationToMavenLocal",
        ":atrace-core:publishReleasePublicationToMavenLocal"
    )
}

tasks.register("publishToLocalDir") {
    group = "publishing"
    description = "Publishes ATrace SDK to local directory (build/maven-repo or atraceLocalPublishDir)"
    dependsOn(
        ":atrace-api:publishReleasePublicationToLocalDirRepository",
        ":atrace-core:publishReleasePublicationToLocalDirRepository",
        ":atrace-noop:publishReleasePublicationToLocalDirRepository"
    )
}

// ── MCP 独立部署 ──────────────────────────────────────────────────────────────
// 构建 atrace-tool fat JAR 并复制到 atrace-mcp/bin/，使 MCP 服务器可独立分发。
//
// 用法:
//   ./gradlew deployMcp
//
// 产物:
//   atrace-mcp/bin/atrace-tool.jar  ← MCP 运行时依赖的 JVM 工具
//
// 分发 MCP 时只需打包 atrace-mcp/ 目录（包含 bin/atrace-tool.jar）。
tasks.register("deployMcp") {
    group = "distribution"
    description = "Build atrace-tool fat-JAR and deploy to atrace-mcp/bin/ for standalone MCP distribution"
    dependsOn(":atrace-tool:deployToMcp")
}



