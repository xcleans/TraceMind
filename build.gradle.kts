// Top-level build file
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.jvm) apply false  // Kotlin JVM 插件（用于 atrace-tool）
    alias(libs.plugins.kotlin.android) apply false  // Kotlin Android 插件（用于 sample）
    alias(libs.plugins.compose.compiler) apply false  // Compose 编译器（用于 sample）
}


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

// ── MCP / provision 部署 ─────────────────────────────────────────────────────
// 构建 atrace-tool fat JAR 并复制到 atrace-provision/atrace_provision/bundled_bin/，
// 与 atrace-provision Python 包一起分发（AtraceToolProvider 解析）。
//
// 用法:
//   ./gradlew deployMcp
//
// 产物:
//   atrace-provision/atrace_provision/bundled_bin/atrace-tool.jar
//
// 分发 MCP 时需依赖已安装的 atrace-provision（wheel 含上述 JAR）。
tasks.register("deployMcp") {
    group = "distribution"
    description = "Build atrace-tool fat-JAR and deploy to atrace-provision bundled_bin/"
    dependsOn(":atrace-tool:deployToMcp")
}



