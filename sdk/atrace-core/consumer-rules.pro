# ATrace Core ProGuard rules
-keep class com.aspect.atrace.core.TraceEngineCore { *; }

# Keep native methods
-keepclasseswithmembernames class * {
    native <methods>;
}

