# ATrace SDK 发布指南

本文档说明如何将 ATrace SDK 模块（atrace-api、atrace-core、atrace-noop、atrace-plugins）发布到本地或远程仓库。

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
├── atrace-api/1.0.0/
├── atrace-core/1.0.0/
├── atrace-noop/1.0.0/
└── atrace-plugins/1.0.0/
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

仅以下模块参与发布，不包含 sample、atrace-tool：

- **atrace-api**：公开 API
- **atrace-core**：核心实现
- **atrace-noop**：空实现（Release 优化）
- **atrace-plugins**：内置插件

## 产物说明

每个模块发布包含：

- `*.aar`：Android 库产物
- `*.pom`：Maven 元数据
- `*.module`：Gradle 模块元数据
