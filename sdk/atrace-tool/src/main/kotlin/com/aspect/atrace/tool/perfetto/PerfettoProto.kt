package com.aspect.atrace.tool.perfetto

import java.io.OutputStream

/**
 * Manual Perfetto protobuf encoding — field numbers match the official .proto definitions.
 * Produces binary output identical to protoc-generated classes, but with zero dependency
 * on protobuf-java. Compatible with Perfetto UI's pbzero decoder.
 *
 * Proto source reference:
 *   https://android.googlesource.com/platform/external/perfetto/+/refs/heads/main/protos/perfetto/trace/
 */
object PerfettoProto {

    // -- Trace (top-level container) ----------------------------------------
    // message Trace { repeated TracePacket packet = 1; }
    object Trace {
        const val PACKET = 1

        fun encode(packets: List<ByteArray>): ByteArray {
            val w = ProtoWriter()
            for (packet in packets) {
                w.writeBytes(PACKET, packet)
            }
            return w.toByteArray()
        }

        fun writeTo(out: OutputStream, packets: List<ByteArray>) {
            val w = ProtoWriter()
            for (packet in packets) {
                w.writeBytes(PACKET, packet)
            }
            w.writeTo(out)
        }

        /**
         * Write packets as a single length-prefixed Trace chunk: [varint size][serialized Trace].
         * Perfetto trace files are a sequence of such chunks. Use this when appending app data
         * to a system trace so the merged file is valid for ui.perfetto.dev.
         */
        fun writeAsChunk(out: OutputStream, packets: List<ByteArray>) {
            val traceBytes = encode(packets)
            writeVarintToStream(out, traceBytes.size.toLong())
            out.write(traceBytes)
        }

        /**
         * Write packets in packet stream format: [varint len][packet] per packet.
         * Use only when the consumer expects raw packet stream (e.g. some Perfetto variants).
         */
        fun writePacketsAsStream(out: OutputStream, packets: List<ByteArray>) {
            for (packet in packets) {
                writeVarintToStream(out, packet.size.toLong())
                out.write(packet)
            }
        }

        internal fun writeVarintToStream(out: OutputStream, value: Long) {
            var v = value
            while (true) {
                if (v and 0x7FL.inv() == 0L) {
                    out.write(v.toInt())
                    return
                }
                out.write(((v and 0x7F).toInt()) or 0x80)
                v = v ushr 7
            }
        }
    }

    // -- TracePacket --------------------------------------------------------
    object TracePacket {
        const val PROCESS_TREE = 2
        const val TIMESTAMP = 8
        const val TRUSTED_PACKET_SEQUENCE_ID = 10
        const val TRACK_EVENT = 11
        const val TRACK_DESCRIPTOR = 60

        fun encode(block: ProtoWriter.() -> Unit): ByteArray {
            val w = ProtoWriter()
            w.block()
            return w.toByteArray()
        }
    }

    // -- TrackEvent ---------------------------------------------------------
    object TrackEvent {
        const val TYPE = 9
        const val NAME_IID = 10
        const val TRACK_UUID = 11
        const val NAME = 23
        const val DEBUG_ANNOTATIONS = 4

        object Type {
            const val TYPE_SLICE_BEGIN = 1
            const val TYPE_SLICE_END = 2
            const val TYPE_INSTANT = 3
            const val TYPE_COUNTER = 4
        }

        fun encode(block: ProtoWriter.() -> Unit): ProtoWriter {
            val w = ProtoWriter()
            w.block()
            return w
        }
    }

    // -- TrackDescriptor ----------------------------------------------------
    object TrackDescriptor {
        const val UUID = 1
        const val NAME = 2
        const val PROCESS = 3
        const val THREAD = 4
        const val PARENT_UUID = 5
        const val DISALLOW_MERGING_WITH_SYSTEM_TRACKS = 9

        fun encode(block: ProtoWriter.() -> Unit): ProtoWriter {
            val w = ProtoWriter()
            w.block()
            return w
        }
    }

    // -- ProcessDescriptor --------------------------------------------------
    // message ProcessDescriptor { int32 pid = 1; ... string process_name = 6; }
    object ProcessDescriptor {
        const val PID = 1
        const val PROCESS_NAME = 6

        fun encode(pid: Int, processName: String): ProtoWriter {
            val w = ProtoWriter()
            w.writeInt32(PID, pid)
            w.writeString(PROCESS_NAME, processName)
            return w
        }
    }

    // -- ThreadDescriptor ---------------------------------------------------
    // message ThreadDescriptor { int32 pid = 1; int32 tid = 2; string thread_name = 5; }
    object ThreadDescriptor {
        const val PID = 1
        const val TID = 2
        const val THREAD_NAME = 5

        fun encode(pid: Int, tid: Int, threadName: String): ProtoWriter {
            val w = ProtoWriter()
            w.writeInt32(PID, pid)
            w.writeInt32(TID, tid)
            w.writeString(THREAD_NAME, threadName)
            return w
        }
    }

    // -- ProcessTree --------------------------------------------------------
    object ProcessTree {
        const val PROCESSES = 1
        const val THREADS = 2

        fun encode(block: ProtoWriter.() -> Unit): ProtoWriter {
            val w = ProtoWriter()
            w.block()
            return w
        }

        // message Process { int32 pid = 1; int32 ppid = 2; repeated string cmdline = 3; }
        object Process {
            const val PID = 1
            const val PPID = 2
            const val CMDLINE = 3

            fun encode(pid: Int, cmdline: String): ProtoWriter {
                val w = ProtoWriter()
                w.writeInt32(PID, pid)
                w.writeString(CMDLINE, cmdline)
                return w
            }
        }

        // message Thread { int32 tid = 1; string name = 2; int32 tgid = 3; }
        object Thread {
            const val TID = 1
            const val NAME = 2
            const val TGID = 3

            fun encode(tid: Int, tgid: Int, name: String): ProtoWriter {
                val w = ProtoWriter()
                w.writeInt32(TID, tid)
                w.writeString(NAME, name)
                w.writeInt32(TGID, tgid)
                return w
            }
        }
    }

    // -- DebugAnnotation ----------------------------------------------------
    // message DebugAnnotation { ... string name = 10; bool bool_value = 2; uint64 uint_value = 3;
    //   int64 int_value = 4; double double_value = 5; string string_value = 6; ... }
    object DebugAnnotation {
        const val NAME = 10
        const val BOOL_VALUE = 2
        const val INT_VALUE = 4
        const val DOUBLE_VALUE = 5
        const val STRING_VALUE = 6

        fun encode(name: String, value: Any): ProtoWriter {
            val w = ProtoWriter()
            w.writeString(NAME, name)
            when (value) {
                is Boolean -> w.writeBool(BOOL_VALUE, value)
                is Int -> w.writeVarInt(INT_VALUE, value.toLong())
                is Long -> w.writeVarInt(INT_VALUE, value)
                is Float -> w.writeDouble(DOUBLE_VALUE, value.toDouble())
                is Double -> w.writeDouble(DOUBLE_VALUE, value)
                else -> w.writeString(STRING_VALUE, value.toString())
            }
            return w
        }
    }
}
