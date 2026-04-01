/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 */
package com.aspect.atrace.core.hook

import android.content.Context
import com.android.dx.Code
import com.android.dx.Comparison
import com.android.dx.DexMaker
import com.android.dx.Label
import com.android.dx.Local
import com.android.dx.MethodId
import com.android.dx.TypeId
import com.aspect.atrace.ALog
import com.swift.sandhook.SandHook
import com.swift.sandhook.wrapper.HookWrapper
import com.swift.sandhook.wrapper.StubMethodsFactory
import java.io.File
import java.lang.reflect.Method
import java.lang.reflect.Modifier
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

/**
 * Legacy backend for SDK < 33.
 *
 * Uses SandHook with DexMaker generated hook methods to support universal
 * method signatures while preserving the existing watched-rule and exact-hook
 * contracts.
 */
internal class SandHookDexMakerBackend : ArtHookBackend {
    private lateinit var appContext: Context
    private val watchedRules = CopyOnWriteArrayList<String>()
    private val hooked = ConcurrentHashMap<String, HookHandle>()
    private val classSerial = AtomicInteger(1)

    private data class HookHandle(
        val target: Method,
        val hookMethod: Method,
        val backupMethod: Method,
        val sectionName: String,
        val dispatchId: Int,
    )

    override fun install(context: Context): Boolean {
        return try {
            appContext = context.applicationContext
            SandHook.passApiCheck()
            // Best-effort optimization for legacy Android, do not fail install.
            runCatching { SandHook.disableVMInline() }
            ALog.i(TAG, "SandHook backend installed (DexMaker universal hook enabled)")
            true
        } catch (t: Throwable) {
            ALog.w(TAG, "SandHook backend install failed: ${t.message}")
            false
        }
    }

    override fun addWatchedRule(scope: String, value: String) {
        val key = normalizeRule(scope, value) ?: return
        if (!watchedRules.contains(key)) watchedRules.add(key)
        ALog.i(TAG, "watch add [$key] total=${watchedRules.size}")
    }

    override fun removeWatchedRule(entry: String) {
        watchedRules.remove(entry)
        ALog.i(TAG, "watch remove [$entry] total=${watchedRules.size}")
    }

    override fun clearWatchedRules() {
        watchedRules.clear()
        ALog.i(TAG, "watch list cleared")
    }

    override fun watchedRuleCount(): Int = watchedRules.size

    override fun getWatchedRules(): List<String> = watchedRules.toList()

    override fun hookMethod(
        className: String,
        methodName: String,
        signature: String,
        isStatic: Boolean,
    ): Boolean {
        return try {
            if (!::appContext.isInitialized) {
                ALog.w(TAG, "hookMethod before install: $className#$methodName$signature")
                return false
            }
            val resolved = resolveTargetMethod(className, methodName, signature, isStatic)
            if (resolved == null) {
                ALog.w(
                    TAG,
                    "resolve failed for $className#$methodName$signature static=$isStatic"
                )
                return false
            }
            hookResolvedMethod(resolved)
        } catch (t: Throwable) {
            ALog.e(
                TAG,
                "hookMethod failed: $className#$methodName$signature static=$isStatic, err=${t.message}",
                t
            )
            false
        }
    }

    override fun unhookMethod(className: String, methodName: String, signature: String, isStatic: Boolean) {
        val key = "$className#$methodName$signature#$isStatic"
        val handle = hooked.remove(key)
        if (handle != null) {
            LegacyDexMakerDispatchRegistry.remove(handle.dispatchId)
            ALog.i(TAG, "unhook registry removed for $key (SandHook runtime unhook unavailable)")
        }
    }

    override fun scanAndHookClass(clazz: Class<*>): Int {
        if (watchedRules.isEmpty()) return 0
        val className = clazz.name
        val methods = try {
            clazz.declaredMethods
        } catch (t: Throwable) {
            // Android low API may fail resolving newer framework symbols referenced
            // by method signatures (e.g. android.window.BackEvent on old devices).
            ALog.w(TAG, "scan skip class $className: cannot enumerate methods (${t.javaClass.simpleName})")
            return 0
        }
        val pending = ArrayList<Method>()
        for (m in methods) {
            if (m.isSynthetic || m.isBridge) continue
            try {
                if (!matchesAnyWatchRule(m, className, watchedRules)) continue
                if (hooked.containsKey(hookKey(m))) continue
                pending.add(m)
            } catch (t: Throwable) {
                ALog.e(
                    TAG,
                    "scan skip method $className.${m.name}: ${t.javaClass.simpleName}: ${t.message}",
                    t
                )
            }
        }
        val count = if (pending.isEmpty()) 0 else hookResolvedMethodsBatch(pending)
        if (count > 0) {
            ALog.i(TAG, "ScanClass $className auto-hooked $count methods")
        }
        return count
    }

    private fun normalizeRule(scope: String, value: String): String? {
        val sc = scope.trim().lowercase()
        val v = value.trim()
        if (v.isEmpty()) return null
        return when (sc) {
            "", "substring", "legacy", "sub" -> v
            "package", "pkg" -> {
                val pkg = v.replace('/', '.').let { if (it.endsWith('.')) it else "$it." }
                "pkg:$pkg"
            }
            "class", "cls" -> "cls:${v.replace('/', '.')}"
            "method", "mth" -> "mth:${v.replace('/', '.')}"
            else -> null
        }
    }

    private fun resolveTargetMethod(
        className: String,
        methodName: String,
        signature: String,
        isStatic: Boolean,
    ): Method? {
        val dotName = className.replace('/', '.')
        val cl = appContext.classLoader ?: SandHookDexMakerBackend::class.java.classLoader
        val targetClass = Class.forName(dotName, false, cl)
        val sig = parseMethodSignature(signature, cl)
        val m = targetClass.getDeclaredMethod(methodName, *sig.paramTypes)
        if (Modifier.isStatic(m.modifiers) != isStatic) {
            ALog.w(
                TAG,
                "static mismatch for $dotName#$methodName$signature: requested=$isStatic actual=${Modifier.isStatic(m.modifiers)}"
            )
            return null
        }
        if (m.returnType != sig.returnType) {
            ALog.w(TAG, "return mismatch for $dotName#$methodName$signature")
            return null
        }
        m.isAccessible = true
        return m
    }

    private data class ParsedSignature(val paramTypes: Array<Class<*>>, val returnType: Class<*>)

    private fun parseMethodSignature(signature: String, cl: ClassLoader): ParsedSignature {
        require(signature.startsWith("(")) { "invalid signature: $signature" }
        var idx = 1
        val params = mutableListOf<Class<*>>()
        while (signature[idx] != ')') {
            val (type, next) = parseDescriptorType(signature, idx, cl)
            params += type
            idx = next
        }
        val (ret, end) = parseDescriptorType(signature, idx + 1, cl)
        require(end == signature.length) { "trailing signature chars: $signature" }
        return ParsedSignature(params.toTypedArray(), ret)
    }

    private fun parseDescriptorType(sig: String, start: Int, cl: ClassLoader): Pair<Class<*>, Int> {
        return when (sig[start]) {
            'V' -> Void.TYPE to (start + 1)
            'Z' -> Boolean::class.javaPrimitiveType!! to (start + 1)
            'B' -> Byte::class.javaPrimitiveType!! to (start + 1)
            'C' -> Char::class.javaPrimitiveType!! to (start + 1)
            'S' -> Short::class.javaPrimitiveType!! to (start + 1)
            'I' -> Int::class.javaPrimitiveType!! to (start + 1)
            'J' -> Long::class.javaPrimitiveType!! to (start + 1)
            'F' -> Float::class.javaPrimitiveType!! to (start + 1)
            'D' -> Double::class.javaPrimitiveType!! to (start + 1)
            'L' -> {
                val end = sig.indexOf(';', start)
                require(end > start) { "bad object descriptor in $sig" }
                val clsName = sig.substring(start + 1, end).replace('/', '.')
                Class.forName(clsName, false, cl) to (end + 1)
            }
            '[' -> {
                var i = start
                while (sig[i] == '[') i++
                val (elem, endPos) = parseDescriptorType(sig, i, cl)
                val desc = sig.substring(start, endPos)
                Class.forName(desc.replace('/', '.'), false, cl) to endPos
            }
            else -> error("bad descriptor ${sig[start]} in $sig")
        }
    }

    private data class DexBatchItem(
        val serial: Int,
        val target: Method,
        val dispatchId: Int,
        val registryKey: String,
        val sectionName: String,
    )

    private val dexGenerationLock = Any()

    private fun hookKey(target: Method): String =
        "${target.declaringClass.name}#${target.name}#${toJvmSignature(target)}#${Modifier.isStatic(target.modifiers)}"

    /**
     * One [DexMaker.generateAndLoad] for all items — avoids one dex2oat per method on class scan.
     */
    private fun hookResolvedMethodsBatch(targets: List<Method>): Int {
        if (targets.isEmpty()) return 0
        synchronized(dexGenerationLock) {
            val items = ArrayList<DexBatchItem>(targets.size)
            for (target in targets) {
                val key = hookKey(target)
                if (hooked.containsKey(key)) continue
                val serial = classSerial.getAndIncrement()
                val sectionName = "ArtHook:${target.declaringClass.name}.${target.name}"
                val dispatchId = LegacyDexMakerDispatchRegistry.register(target, sectionName)
                items.add(DexBatchItem(serial, target, dispatchId, key, sectionName))
            }
            if (items.isEmpty()) return 0

            val loader = try {
                DexHookGenerator.generateHookMethodsBatch(appContext, items)
            } catch (t: Throwable) {
                for (item in items) LegacyDexMakerDispatchRegistry.remove(item.dispatchId)
                ALog.e(TAG, "DexMaker batch generation failed: ${t.message}", t)
                return 0
            }

            if (items.size > 1) {
                ALog.i(TAG, "DexMaker: ${items.size} hook classes in one jar (single dex2oat)")
            }

            var count = 0
            for (item in items) {
                val generated = try {
                    DexHookGenerator.reflectHookMethod(loader, item.serial, item.target)
                } catch (t: Throwable) {
                    LegacyDexMakerDispatchRegistry.remove(item.dispatchId)
                    ALog.e(TAG, "reflect hook method failed ${item.sectionName}: ${t.message}", t)
                    continue
                }
                val entity = HookWrapper.HookEntity(
                    item.target,
                    generated,
                    StubMethodsFactory.getStubMethod(),
                    false,
                )
                entity.backupIsStub = true
                entity.resolveDexCache = false
                try {
                    SandHook.hook(entity)
                    hooked[item.registryKey] = HookHandle(
                        item.target,
                        generated,
                        entity.backup,
                        item.sectionName,
                        item.dispatchId,
                    )
                    count++
                    ALog.i(TAG, "hooked legacy method: ${item.sectionName}")
                } catch (t: Throwable) {
                    LegacyDexMakerDispatchRegistry.remove(item.dispatchId)
                    ALog.e(TAG, "SandHook hook failed for ${item.sectionName}: ${t.message}", t)
                }
            }
            return count
        }
    }

    private fun hookResolvedMethod(target: Method): Boolean {
        if (hooked.containsKey(hookKey(target))) return true
        return hookResolvedMethodsBatch(listOf(target)) == 1
    }

    private fun toJvmSignature(m: Method): String {
        val sb = StringBuilder()
        sb.append('(')
        for (p in m.parameterTypes) sb.append(toDesc(p))
        sb.append(')')
        sb.append(toDesc(m.returnType))
        return sb.toString()
    }

    private fun toDesc(c: Class<*>): String {
        if (c.isPrimitive) {
            return when (c) {
                java.lang.Void.TYPE -> "V"
                java.lang.Boolean.TYPE -> "Z"
                java.lang.Byte.TYPE -> "B"
                java.lang.Character.TYPE -> "C"
                java.lang.Short.TYPE -> "S"
                java.lang.Integer.TYPE -> "I"
                java.lang.Long.TYPE -> "J"
                java.lang.Float.TYPE -> "F"
                java.lang.Double.TYPE -> "D"
                else -> error("unknown primitive $c")
            }
        }
        if (c.isArray) return c.name.replace('.', '/')
        return "L${c.name.replace('.', '/')};"
    }

    private fun matchesAnyWatchRule(method: Method, className: String, rules: List<String>): Boolean {
        val pretty = method.toString()
        val fullMethod = "$className.${method.name}"
        for (rule in rules) {
            when {
                rule.startsWith("pkg:") -> {
                    val pkg = rule.removePrefix("pkg:")
                    if (className.startsWith(pkg) || className.contains(pkg)) return true
                }
                rule.startsWith("cls:") -> {
                    if (className == rule.removePrefix("cls:")) return true
                }
                rule.startsWith("mth:") -> {
                    val m = rule.removePrefix("mth:")
                    if (fullMethod == m || pretty.contains("$m(")) return true
                }
                else -> {
                    if (pretty.contains(rule) || fullMethod.contains(rule)) return true
                }
            }
        }
        return false
    }

    private object DexHookGenerator {
        private val INT = TypeId.INT
        private val OBJ = TypeId.get(Any::class.java)
        private val OBJ_ARRAY = TypeId.get(Array<Any>::class.java)
        private val DISPATCHER = TypeId.get(LegacyDexMakerDispatchRegistry::class.java)
        private val DISPATCH_METHOD = DISPATCHER.getMethod(
            OBJ, "dispatchInvoke", INT, OBJ, OBJ_ARRAY
        )

        fun generateHookMethodsBatch(context: Context, items: List<DexBatchItem>): ClassLoader {
            val dex = DexMaker()
            for (item in items) {
                val typeName = "Lcom/aspect/atrace/core/hook/generated/Hook_${item.serial};"
                val t: TypeId<Any> = TypeId.get(typeName)
                dex.declare(t, "Hook_${item.serial}.generated", Modifier.PUBLIC or Modifier.FINAL, TypeId.OBJECT)

                val ctor = t.getConstructor()
                val c: Code = dex.declare(ctor, Modifier.PUBLIC)
                val thisRef = c.getThis(t)
                c.invokeDirect(TypeId.OBJECT.getConstructor(), null, thisRef)
                c.returnVoid()

                declareHookMethod(dex, t, item.target, item.dispatchId)
            }
            val cacheDir = File(context.codeCacheDir, "atrace_dexmaker").apply { mkdirs() }
            return dex.generateAndLoad(context.classLoader ?: javaClass.classLoader, cacheDir)
        }

        fun reflectHookMethod(loader: ClassLoader, serial: Int, target: Method): Method {
            val cls = loader.loadClass("com.aspect.atrace.core.hook.generated.Hook_$serial")
            val hookParamClasses = mutableListOf<Class<*>>()
            if (!Modifier.isStatic(target.modifiers)) {
                hookParamClasses += target.declaringClass
            }
            hookParamClasses.addAll(target.parameterTypes)
            return cls.getDeclaredMethod("hook", *hookParamClasses.toTypedArray())
        }

        private fun declareHookMethod(
            dex: DexMaker,
            owner: TypeId<*>,
            target: Method,
            dispatchId: Int,
        ): Method {
            val isStatic = Modifier.isStatic(target.modifiers)
            val retType = typeIdOf(target.returnType)
            val hookParamTypes = mutableListOf<TypeId<*>>()
            if (!isStatic) hookParamTypes += typeIdOf(target.declaringClass)
            target.parameterTypes.forEach { hookParamTypes += typeIdOf(it) }
            val methodId = owner.getMethod(retType, "hook", *hookParamTypes.toTypedArray())
            val code = dex.declare(methodId, Modifier.PUBLIC or Modifier.STATIC)

            // DexMaker constraint: all locals must be allocated before first instruction.
            val hookIdLocal = code.newLocal(INT)
            val nullObj = code.newLocal(OBJ)
            val receiverLocal = code.newLocal(OBJ)
            val arrLocal = code.newLocal(OBJ_ARRAY)
            val arrSize = code.newLocal(INT)
            val indexLocal = code.newLocal(INT)
            val resultLocal = code.newLocal(OBJ)

            val boxedLocals = Array(target.parameterTypes.size) { code.newLocal(OBJ) }

            val objectRetLocal: Local<*>? =
                if (!target.returnType.isPrimitive && target.returnType != Void.TYPE) {
                    code.newLocal(typeIdOf(target.returnType))
                } else {
                    null
                }

            val boolWrap = if (target.returnType == java.lang.Boolean.TYPE) code.newLocal(TypeId.get(java.lang.Boolean::class.java)) else null
            val boolRet = if (target.returnType == java.lang.Boolean.TYPE) code.newLocal(TypeId.BOOLEAN) else null
            val boolDef = if (target.returnType == java.lang.Boolean.TYPE) code.newLocal(TypeId.BOOLEAN) else null
            val byteWrap = if (target.returnType == java.lang.Byte.TYPE) code.newLocal(TypeId.get(java.lang.Byte::class.java)) else null
            val byteRet = if (target.returnType == java.lang.Byte.TYPE) code.newLocal(TypeId.BYTE) else null
            val byteDef = if (target.returnType == java.lang.Byte.TYPE) code.newLocal(TypeId.BYTE) else null
            val charWrap = if (target.returnType == java.lang.Character.TYPE) code.newLocal(TypeId.get(java.lang.Character::class.java)) else null
            val charRet = if (target.returnType == java.lang.Character.TYPE) code.newLocal(TypeId.CHAR) else null
            val charDef = if (target.returnType == java.lang.Character.TYPE) code.newLocal(TypeId.CHAR) else null
            val shortWrap = if (target.returnType == java.lang.Short.TYPE) code.newLocal(TypeId.get(java.lang.Short::class.java)) else null
            val shortRet = if (target.returnType == java.lang.Short.TYPE) code.newLocal(TypeId.SHORT) else null
            val shortDef = if (target.returnType == java.lang.Short.TYPE) code.newLocal(TypeId.SHORT) else null
            val intWrap = if (target.returnType == java.lang.Integer.TYPE) code.newLocal(TypeId.get(java.lang.Integer::class.java)) else null
            val intRet = if (target.returnType == java.lang.Integer.TYPE) code.newLocal(TypeId.INT) else null
            val intDef = if (target.returnType == java.lang.Integer.TYPE) code.newLocal(TypeId.INT) else null
            val longWrap = if (target.returnType == java.lang.Long.TYPE) code.newLocal(TypeId.get(java.lang.Long::class.java)) else null
            val longRet = if (target.returnType == java.lang.Long.TYPE) code.newLocal(TypeId.LONG) else null
            val longDef = if (target.returnType == java.lang.Long.TYPE) code.newLocal(TypeId.LONG) else null
            val floatWrap = if (target.returnType == java.lang.Float.TYPE) code.newLocal(TypeId.get(java.lang.Float::class.java)) else null
            val floatRet = if (target.returnType == java.lang.Float.TYPE) code.newLocal(TypeId.FLOAT) else null
            val floatDef = if (target.returnType == java.lang.Float.TYPE) code.newLocal(TypeId.FLOAT) else null
            val doubleWrap = if (target.returnType == java.lang.Double.TYPE) code.newLocal(TypeId.get(java.lang.Double::class.java)) else null
            val doubleRet = if (target.returnType == java.lang.Double.TYPE) code.newLocal(TypeId.DOUBLE) else null
            val doubleDef = if (target.returnType == java.lang.Double.TYPE) code.newLocal(TypeId.DOUBLE) else null

            code.loadConstant(hookIdLocal, dispatchId)
            code.loadConstant(nullObj, null)

            if (isStatic) {
                code.loadConstant(receiverLocal, null)
            } else {
                val thisLocal = code.getParameter(0, typeIdOf(target.declaringClass))
                code.cast(receiverLocal, thisLocal)
            }

            val argCount = target.parameterTypes.size
            code.loadConstant(arrSize, argCount)
            code.newArray(arrLocal, arrSize)

            for (i in 0 until argCount) {
                val paramType = target.parameterTypes[i]
                val argIndex = if (isStatic) i else i + 1
                code.loadConstant(indexLocal, i)
                if (!paramType.isPrimitive) {
                    @Suppress("UNCHECKED_CAST")
                    val p = code.getParameter(argIndex, typeIdOf(paramType)) as Local<Any>
                    code.cast(boxedLocals[i], p)
                } else {
                    when (paramType) {
                        java.lang.Boolean.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.BOOLEAN)
                            code.invokeStatic(
                                TypeId.get(java.lang.Boolean::class.java).getMethod(
                                    TypeId.get(java.lang.Boolean::class.java), "valueOf", TypeId.BOOLEAN
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Byte.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.BYTE)
                            code.invokeStatic(
                                TypeId.get(java.lang.Byte::class.java).getMethod(
                                    TypeId.get(java.lang.Byte::class.java), "valueOf", TypeId.BYTE
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Character.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.CHAR)
                            code.invokeStatic(
                                TypeId.get(java.lang.Character::class.java).getMethod(
                                    TypeId.get(java.lang.Character::class.java), "valueOf", TypeId.CHAR
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Short.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.SHORT)
                            code.invokeStatic(
                                TypeId.get(java.lang.Short::class.java).getMethod(
                                    TypeId.get(java.lang.Short::class.java), "valueOf", TypeId.SHORT
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Integer.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.INT)
                            code.invokeStatic(
                                TypeId.get(java.lang.Integer::class.java).getMethod(
                                    TypeId.get(java.lang.Integer::class.java), "valueOf", TypeId.INT
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Long.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.LONG)
                            code.invokeStatic(
                                TypeId.get(java.lang.Long::class.java).getMethod(
                                    TypeId.get(java.lang.Long::class.java), "valueOf", TypeId.LONG
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Float.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.FLOAT)
                            code.invokeStatic(
                                TypeId.get(java.lang.Float::class.java).getMethod(
                                    TypeId.get(java.lang.Float::class.java), "valueOf", TypeId.FLOAT
                                ),
                                boxedLocals[i], p
                            )
                        }
                        java.lang.Double.TYPE -> {
                            val p = code.getParameter(argIndex, TypeId.DOUBLE)
                            code.invokeStatic(
                                TypeId.get(java.lang.Double::class.java).getMethod(
                                    TypeId.get(java.lang.Double::class.java), "valueOf", TypeId.DOUBLE
                                ),
                                boxedLocals[i], p
                            )
                        }
                    }
                }
                code.aput(arrLocal, indexLocal, boxedLocals[i])
            }

            code.invokeStatic(DISPATCH_METHOD, resultLocal, hookIdLocal, receiverLocal, arrLocal)

            if (target.returnType == Void.TYPE) {
                code.returnVoid()
                return target
            }
            if (!target.returnType.isPrimitive) {
                @Suppress("UNCHECKED_CAST")
                val ret = objectRetLocal as Local<Any>
                code.cast(ret, resultLocal)
                code.returnValue(ret)
                return target
            }

            val isNull = Label()
            code.compare(Comparison.EQ, isNull, resultLocal, nullObj)

            when (target.returnType) {
                java.lang.Boolean.TYPE -> {
                    code.cast(boolWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Boolean::class.java).getMethod(TypeId.BOOLEAN, "booleanValue"), boolRet, boolWrap)
                    code.returnValue(boolRet)
                }
                java.lang.Byte.TYPE -> {
                    code.cast(byteWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Byte::class.java).getMethod(TypeId.BYTE, "byteValue"), byteRet, byteWrap)
                    code.returnValue(byteRet)
                }
                java.lang.Character.TYPE -> {
                    code.cast(charWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Character::class.java).getMethod(TypeId.CHAR, "charValue"), charRet, charWrap)
                    code.returnValue(charRet)
                }
                java.lang.Short.TYPE -> {
                    code.cast(shortWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Short::class.java).getMethod(TypeId.SHORT, "shortValue"), shortRet, shortWrap)
                    code.returnValue(shortRet)
                }
                java.lang.Integer.TYPE -> {
                    code.cast(intWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Integer::class.java).getMethod(TypeId.INT, "intValue"), intRet, intWrap)
                    code.returnValue(intRet)
                }
                java.lang.Long.TYPE -> {
                    code.cast(longWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Long::class.java).getMethod(TypeId.LONG, "longValue"), longRet, longWrap)
                    code.returnValue(longRet)
                }
                java.lang.Float.TYPE -> {
                    code.cast(floatWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Float::class.java).getMethod(TypeId.FLOAT, "floatValue"), floatRet, floatWrap)
                    code.returnValue(floatRet)
                }
                java.lang.Double.TYPE -> {
                    code.cast(doubleWrap, resultLocal)
                    code.invokeVirtual(TypeId.get(java.lang.Double::class.java).getMethod(TypeId.DOUBLE, "doubleValue"), doubleRet, doubleWrap)
                    code.returnValue(doubleRet)
                }
            }

            code.mark(isNull)
            when (target.returnType) {
                java.lang.Boolean.TYPE -> { code.loadConstant(boolDef, false); code.returnValue(boolDef) }
                java.lang.Byte.TYPE -> { code.loadConstant(byteDef, 0.toByte()); code.returnValue(byteDef) }
                java.lang.Character.TYPE -> { code.loadConstant(charDef, 0.toChar()); code.returnValue(charDef) }
                java.lang.Short.TYPE -> { code.loadConstant(shortDef, 0.toShort()); code.returnValue(shortDef) }
                java.lang.Integer.TYPE -> { code.loadConstant(intDef, 0); code.returnValue(intDef) }
                java.lang.Long.TYPE -> { code.loadConstant(longDef, 0L); code.returnValue(longDef) }
                java.lang.Float.TYPE -> { code.loadConstant(floatDef, 0f); code.returnValue(floatDef) }
                java.lang.Double.TYPE -> { code.loadConstant(doubleDef, 0.0); code.returnValue(doubleDef) }
            }
            return target
        }

        private fun typeIdOf(c: Class<*>): TypeId<*> {
            return when (c) {
                java.lang.Boolean.TYPE -> TypeId.BOOLEAN
                java.lang.Byte.TYPE -> TypeId.BYTE
                java.lang.Character.TYPE -> TypeId.CHAR
                java.lang.Short.TYPE -> TypeId.SHORT
                java.lang.Integer.TYPE -> TypeId.INT
                java.lang.Long.TYPE -> TypeId.LONG
                java.lang.Float.TYPE -> TypeId.FLOAT
                java.lang.Double.TYPE -> TypeId.DOUBLE
                java.lang.Void.TYPE -> TypeId.VOID
                else -> TypeId.get(c)
            }
        }
    }

    private companion object {
        private const val TAG = "SandHookBackend"
    }
}

