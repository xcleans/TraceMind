# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.

# Keep ATrace classes
-keep class com.aspect.atrace.** { *; }
-dontwarn com.aspect.atrace.**

# Keep sample classes
-keep class com.aspect.atrace.sample.** { *; }
