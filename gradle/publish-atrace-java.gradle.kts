/**
 * 纯 Java 库模块的 Maven 发布（如 sandhook-annotation）。
 * 与 publish-atrace.gradle.kts 使用相同 groupId / version / 仓库，便于 JitPack 一次构建多模块。
 */
project.pluginManager.apply("maven-publish")

val atraceGroup: String = rootProject.findProperty("atraceGroup")?.toString() ?: "com.aspect.atrace"
val atraceVersion: String = rootProject.findProperty("atraceVersion")?.toString() ?: "1.0.1"
val atracePomUrl: String = rootProject.findProperty("atracePomUrl")?.toString() ?: "https://github.com/your-org/ATrace"
val atraceScmUrl: String = rootProject.findProperty("atraceScmUrl")?.toString() ?: "https://github.com/your-org/ATrace.git"
val atraceLocalPublishDir: String = rootProject.findProperty("atraceLocalPublishDir")?.toString()
    ?: rootProject.layout.buildDirectory.get().asFile.resolve("maven-repo").absolutePath

afterEvaluate {
    project.extensions.configure<org.gradle.api.publish.PublishingExtension>("publishing") {
        publications {
            create<MavenPublication>("release") {
                from(project.components["java"])
                groupId = atraceGroup
                artifactId = project.name
                version = atraceVersion
                pom {
                    name.set(project.name)
                    description.set("ATrace / SandHook - ${project.name}")
                    url.set(atracePomUrl)
                    licenses {
                        license {
                            name.set("MIT License")
                            url.set("https://opensource.org/licenses/MIT")
                        }
                    }
                    scm {
                        url.set(atraceScmUrl)
                        connection.set("scm:git:$atraceScmUrl")
                        developerConnection.set("scm:git:$atraceScmUrl")
                    }
                    developers {
                        developer {
                            name.set("ATrace Authors")
                        }
                    }
                }
            }
        }
        repositories {
            mavenLocal()
            maven {
                name = "localDir"
                url = uri(atraceLocalPublishDir)
            }
        }
    }
}
