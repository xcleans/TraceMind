# ATrace API ProGuard rules
-keep class com.aspect.atrace.ATrace { *; }
-keep class com.aspect.atrace.TraceConfig { *; }
-keep class com.aspect.atrace.TraceConfig$* { *; }
-keep interface com.aspect.atrace.TraceEngine { *; }
-keep interface com.aspect.atrace.plugin.TracePlugin { *; }
-keep interface com.aspect.atrace.plugin.PluginContext { *; }
-keep enum com.aspect.atrace.plugin.SampleType { *; }

