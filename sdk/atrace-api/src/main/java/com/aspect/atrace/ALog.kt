package com.aspect.atrace

import android.util.Log

object ALog {
    fun d(tag: String, msg: String) {
        Log.d(tag, msg)
    }

    fun v(tag: String, msg: String) {
        Log.v(tag, msg)
    }

    fun e(tag: String, msg: String) {
        Log.e(tag, msg)
    }

    fun w(tag: String, msg: String) {
        Log.w(tag, msg)
    }

    fun i(tag: String, msg: String) {
        Log.i(tag, msg)
    }

    fun wtf(tag: String, msg: String) {
        Log.wtf(tag, msg)
    }

    fun e(tag: String, msg: String, e: Throwable) {
        Log.e(tag, msg,e)
    }
}