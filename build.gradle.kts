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

// 发布 ATrace SDK + 本地依赖链（SandHook），供 JitPack install 与 mavenLocal 消费
tasks.register("publishToMavenLocal") {
    group = "publishing"
    description =
        "Publishes sandhook-* → atrace-api → atrace-core to Maven local (~/.m2/repository)"
    dependsOn(
        ":sandhook-annotation:publishReleasePublicationToMavenLocal",
        ":sandhook-nativehook:publishReleasePublicationToMavenLocal",
        ":sandhook-hooklib:publishReleasePublicationToMavenLocal",
        ":atrace-api:publishReleasePublicationToMavenLocal",
        ":atrace-core:publishReleasePublicationToMavenLocal",
    )
}

gradle.projectsEvaluated {
    val pubAnn =
        rootProject.project(":sandhook-annotation").tasks.named("publishReleasePublicationToMavenLocal")
    rootProject.project(":sandhook-hooklib").tasks.named("publishReleasePublicationToMavenLocal") {
        mustRunAfter(pubAnn)
    }
    val pubNat =
        rootProject.project(":sandhook-nativehook").tasks.named("publishReleasePublicationToMavenLocal")
    val pubHook =
        rootProject.project(":sandhook-hooklib").tasks.named("publishReleasePublicationToMavenLocal")
    val pubApi = rootProject.project(":atrace-api").tasks.named("publishReleasePublicationToMavenLocal")
    rootProject.project(":atrace-core").tasks.named("publishReleasePublicationToMavenLocal") {
        mustRunAfter(pubAnn)
        mustRunAfter(pubNat)
        mustRunAfter(pubHook)
        mustRunAfter(pubApi)
    }

    val dirAnn =
        rootProject.project(":sandhook-annotation").tasks.named(
            "publishReleasePublicationToLocalDirRepository",
        )
    rootProject.project(":sandhook-hooklib").tasks.named(
        "publishReleasePublicationToLocalDirRepository",
    ) {
        mustRunAfter(dirAnn)
    }
    val dirNat =
        rootProject.project(":sandhook-nativehook").tasks.named(
            "publishReleasePublicationToLocalDirRepository",
        )
    val dirHook =
        rootProject.project(":sandhook-hooklib").tasks.named(
            "publishReleasePublicationToLocalDirRepository",
        )
    val dirApi =
        rootProject.project(":atrace-api").tasks.named(
            "publishReleasePublicationToLocalDirRepository",
        )
    rootProject.project(":atrace-core").tasks.named(
        "publishReleasePublicationToLocalDirRepository",
    ) {
        mustRunAfter(dirAnn)
        mustRunAfter(dirNat)
        mustRunAfter(dirHook)
        mustRunAfter(dirApi)
    }
}

tasks.register("publishToLocalDir") {
    group = "publishing"
    description =
        "Publishes sandhook-* → atrace-api → atrace-core to local dir (atraceLocalPublishDir)"
    dependsOn(
        ":sandhook-annotation:publishReleasePublicationToLocalDirRepository",
        ":sandhook-nativehook:publishReleasePublicationToLocalDirRepository",
        ":sandhook-hooklib:publishReleasePublicationToLocalDirRepository",
        ":atrace-api:publishReleasePublicationToLocalDirRepository",
        ":atrace-core:publishReleasePublicationToLocalDirRepository",
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



