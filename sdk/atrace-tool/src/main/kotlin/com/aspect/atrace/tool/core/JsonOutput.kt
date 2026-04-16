package com.aspect.atrace.tool.core

import org.json.JSONArray
import org.json.JSONObject

/**
 * Machine-readable JSON output for MCP integration.
 *
 * When --json is active, every command MUST print exactly one JSON object to
 * stdout and nothing else.  All Log.* calls are silenced automatically.
 */
object JsonOutput {

    fun success(data: Map<String, Any?>): String {
        val obj = JSONObject()
        obj.put("status", "success")
        data.forEach { (k, v) -> put(obj, k, v) }
        return obj.toString(2)
    }

    fun error(message: String, hint: String? = null): String {
        val obj = JSONObject()
        obj.put("status", "error")
        obj.put("message", message)
        hint?.let { obj.put("hint", it) }
        return obj.toString(2)
    }

    @Suppress("UNCHECKED_CAST")
    private fun put(obj: JSONObject, key: String, value: Any?) {
        when (value) {
            null        -> obj.put(key, JSONObject.NULL)
            is List<*>  -> {
                val arr = JSONArray()
                value.forEach { item ->
                    when (item) {
                        is Map<*, *> -> {
                            val inner = JSONObject()
                            (item as Map<String, Any?>).forEach { (k, v) -> put(inner, k, v) }
                            arr.put(inner)
                        }
                        else -> arr.put(item)
                    }
                }
                obj.put(key, arr)
            }
            else        -> obj.put(key, value)
        }
    }
}
