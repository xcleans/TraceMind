# ATrace SDK 发布指南

本文档说明如何将 ATrace SDK 模块（**atrace-api**、**atrace-core** 及 **`sandhook-*` 依赖链**）发布到本地或远程仓库。

## 发布方式

支持两种本地发布方式：

| 方式 | 命令 | 输出位置 |
|------|------|----------|
| **Maven Local** | `./gradlew publishToMavenLocal` | `~/.m2/repository/` |
| **本地目录** | `./gradlew publishToLocalDir` | `build/maven-repo/` 或 `atraceLocalPublishDir` |

### 1. 发布到 Maven Local

发布到用户本地 Maven 仓库（`~/.m2/repository`），适用于：

- 本地开发调试
- 其他项目通过 `mavenLocal()` 依赖
- JitPack 等构建前的本地验证

```bash
./gradlew publishToMavenLocal
```

**发布产物路径：**

```
~/.m2/repository/com/aspect/atrace/
├── sandhook-annotation/1.0.0/   # JAR
├── sandhook-hooklib/1.0.0/
├── sandhook-nativehook/1.0.0/
├── atrace-api/1.0.0/
└── atrace-core/1.0.0/
```

**消费方式：**

```kotlin
repositories {
    mavenLocal()
}
dependencies {
    implementation("com.aspect.atrace:atrace-api:1.0.0")
}
```

### 2. 发布到本地目录

发布到项目目录或自定义路径，适用于：

- 不污染 `~/.m2/repository`
- 将产物打包分发
- CI 中指定输出目录

```bash
./gradlew publishToLocalDir
```

**默认输出路径：** `build/maven-repo/`

**自定义路径：** 在 `gradle.properties` 中设置：

```properties
atraceLocalPublishDir=/path/to/your/maven-repo
```

或命令行：

```bash
./gradlew publishToLocalDir -PatraceLocalPublishDir=/path/to/repo
```

**消费方式：**

```kotlin
repositories {
    maven { url = uri("/path/to/maven-repo") }
}
dependencies {
    implementation("com.aspect.atrace:atrace-api:1.0.0")
}
```

## 单模块发布

如需发布单个模块：

```bash
# Maven Local
./gradlew :atrace-api:publishReleasePublicationToMavenLocal

# 本地目录
./gradlew :atrace-api:publishReleasePublicationToLocalDirRepository
```

## 配置项

在 `gradle.properties` 中可配置：

| 属性 | 说明 | 默认值 |
|------|------|--------|
| `atraceGroup` | Maven groupId | `com.aspect.atrace` |
| `atraceVersion` | 版本号 | `1.0.0` |
| `atraceLocalPublishDir` | 本地目录发布路径 | `build/maven-repo` |
| `atracePomUrl` | POM 项目 URL | `https://github.com/your-org/ATrace` |
| `atraceScmUrl` | SCM 仓库 URL | `https://github.com/your-org/ATrace.git` |

## 发布模块

参与 **`publishToMavenLocal` / `publishToLocalDir`** 的模块如下（不包含 `sample`、`atrace-tool`）：

- **sandhook-annotation**：Java 库（`*.jar`）
- **sandhook-nativehook**、**sandhook-hooklib**：Android 库（`*.aar`）
- **atrace-api**、**atrace-core**：Android 库（`*.aar`）

内置插件位于 **`atrace-core`** 包 `com.aspect.atrace.plugins` 内，不单独发布 **`atrace-plugins`** 工件。

## 产物说明

每个 Android 库发布包含 **`*.aar`**、`*.pom`、`*.module`；**sandhook-annotation** 为 **`*.jar`** 及对应 POM。

---

## JitPack 发布（[docs.jitpack.io](https://docs.jitpack.io/)）

JitPack 从 **Git 仓库**按需构建，无需自己上传到 Maven Central。流程与多模块坐标见官方说明：[Building with JitPack](https://docs.jitpack.io/)、[Android 库](https://docs.jitpack.io/android/)。

### 1. 仓库内已配置

- 根目录 **`jitpack.yml`**：`install` 阶段执行 `./gradlew publishToMavenLocal`。
- **`publishToMavenLocal`** 会按顺序把 **本地工程依赖** 一并安装到 `~/.m2`，供 JitPack 与 **`atrace-core` 的 POM 传递依赖** 对齐：
  - `sandhook-annotation`（Java）
  - `sandhook-nativehook`、`sandhook-hooklib`（Android AAR）
  - `atrace-api`、`atrace-core`
- 上述模块与 `atrace-api` / `atrace-core` 使用同一 **`atraceGroup`**、**`atraceVersion`**（见 `gradle.properties`）。JitPack 的「版本」一般使用 **Git Tag** 或 **commit SHA**（见下文依赖写法）。

### 2. 你需要做的

1. 将工程推到 **GitHub**（或其它 [JitPack 支持的托管方](https://docs.jitpack.io/)）。
2. 打开 [jitpack.io](https://jitpack.io)，输入仓库 URL，点 **Look up**，确认 **Tag** 或分支能触发构建成功。
3. 建议为正式发布打 **Git Tag**（与 `atraceVersion` 对齐，便于对照），例如 `v1.0.5`。

### 3. 依赖坐标（多模块）

多模块产物形式为 **`com.github.<用户或组织>.<仓库名>:<模块名>:<版本>`**（模块名对应 `artifactId`，即 `atrace-api` / `atrace-core`）。示例（请替换为你的 GitHub 路径与 Tag）：

```kotlin
repositories {
    mavenCentral()
    maven { url = uri("https://jitpack.io") }
}

dependencies {
    implementation("com.github.YOUR_USER.TraceMind:atrace-api:v1.0.5")
    implementation("com.github.YOUR_USER.TraceMind:atrace-core:v1.0.5")
}
```

仅依赖 **`atrace-core`** 时，Gradle 会按 POM 解析 **`com.aspect.atrace`** 下的传递依赖（如 **`sandhook-hooklib`**、`sandhook-nativehook`、`sandhook-annotation`）；JitPack 一次构建执行全量 **`publishToMavenLocal`** 后，这些构件与 `atrace-core` 同版本一并产出。若业务需要直接依赖 SandHook 子模块，可使用多模块坐标，例如：

```kotlin
implementation("com.github.YOUR_USER.TraceMind:sandhook-hooklib:v1.0.5")
```

说明：

- **`YOUR_USER`** / **`TraceMind`** 与 GitHub 上 **`github.com/YOUR_USER/TraceMind`** 一致；组织仓库则为 `com.github.YOUR_ORG.RepoName`。
- **版本**可用 **Release Tag**、`main-SNAPSHOT`、**commit 短 SHA** 等，规则见 [JitPack 文档 · Building](https://docs.jitpack.io/#building-with-jitpack)。
- 建议为 `jitpack.io` 使用 **`content { includeGroup("com.github.xxx") }`** 等仓库过滤，见文档中的安全与解析顺序说明。

### 4. 构建可能失败的原因（本仓库）

- **`atrace-core` 含 CMake/NDK**（含本地 `sandhook` 子工程），云端需完整 Android SDK/NDK；`compileSdk`、**`ndkVersion`** 过新时，若镜像尚未就绪会失败，可适当降级或在 JitPack 文档中查阅 [Build environment](https://docs.jitpack.io/building/#build-environment)。
- **Gradle/AGP 较新**（如 Gradle 9.x）：已用 **`openjdk17`**；若仍失败可尝试在 `jitpack.yml` 中改为 `openjdk21` 并查阅 JitPack 日志。

首次发布请在 JitPack 页面查看 **Build log**，按日志调整 JDK、SDK 或 `install` 命令。
