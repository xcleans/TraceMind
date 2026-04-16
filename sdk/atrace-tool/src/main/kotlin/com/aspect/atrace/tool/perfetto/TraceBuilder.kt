package com.aspect.atrace.tool.perfetto

import java.io.OutputStream
import perfetto.protos.DebugAnnotationOuterClass
import perfetto.protos.ProcessDescriptorOuterClass
import perfetto.protos.ProcessTreeOuterClass
import perfetto.protos.ThreadDescriptorOuterClass
import perfetto.protos.TraceOuterClass
import perfetto.protos.TracePacketOuterClass
import perfetto.protos.TrackDescriptorOuterClass
import perfetto.protos.TrackEventOuterClass

class TraceBuilder {

    private val perfettoTrace = TraceOuterClass.Trace.newBuilder()
    private val processes = mutableMapOf<Int, ProcessInfo>()
    private val trackUuids = mutableMapOf<String, Long>()
    private var trackUuidGen = 1000L
    private var trackAssigned = false

    data class ProcessInfo(
        val pid: Int,
        val name: String,
        val threads: MutableList<ThreadInfo> = mutableListOf()
    )

    data class ThreadInfo(
        val tid: Int,
        val name: String
    )

    fun setProcess(pid: Int, name: String) {
        processes[pid] = ProcessInfo(pid, name)
    }

    fun setThread(pid: Int, tid: Int, name: String) {
        processes[pid]?.threads?.add(ThreadInfo(tid, name))
    }

    fun addSliceBegin(pid: Int, tid: Int, name: String, ts: Long, debug: Map<String, Any>?) {
        ensureTrackAssigned()

        val trackUuid = getTrackUuid(pid, tid)
        val event = TrackEventOuterClass.TrackEvent.newBuilder()
            .setType(TrackEventOuterClass.TrackEvent.Type.TYPE_SLICE_BEGIN)
            .setName(name)
        if (trackUuid >= 0) {
            event.trackUuid = trackUuid
        }
        debug?.forEach { (key, value) ->
            event.addDebugAnnotations(
                setDebugValue(DebugAnnotationOuterClass.DebugAnnotation.newBuilder().setName(key), value)
            )
        }

        perfettoTrace.addPacket(
            TracePacketOuterClass.TracePacket.newBuilder()
                .setTimestamp(ts)
                .setTrackEvent(event)
                .setTrustedPacketSequenceId(0)
        )
    }

    fun addSliceEnd(pid: Int, tid: Int, name: String, ts: Long) {
        val trackUuid = getTrackUuid(pid, tid)
        val event = TrackEventOuterClass.TrackEvent.newBuilder()
            .setType(TrackEventOuterClass.TrackEvent.Type.TYPE_SLICE_END)
        if (trackUuid >= 0) {
            event.trackUuid = trackUuid
        }

        perfettoTrace.addPacket(
            TracePacketOuterClass.TracePacket.newBuilder()
                .setTimestamp(ts)
                .setTrackEvent(event)
                .setTrustedPacketSequenceId(0)
        )
    }

    fun marshal(out: OutputStream) {
        injectProcessTreePacket()
        perfettoTrace.build().writeTo(out)
    }

    /**
     * Writes one length-prefixed Trace chunk: [varint size][Trace bytes].
     *
     * NOTE: Do NOT use this for system+app merge. System trace in this project is raw Trace
     * protobuf bytes, so merge must use [system raw bytes] + marshal(raw Trace bytes), which is
     * the same strategy used by rhea-trace-processor.
     */
    fun marshalAsChunk(out: OutputStream) {
        injectProcessTreePacket()
        perfettoTrace.build().writeDelimitedTo(out)
    }

    /** Stream format: [varint][packet] per packet. Use for standalone app-only trace. */
    fun marshalAsStream(out: OutputStream) {
        injectProcessTreePacket()
        for (packet in perfettoTrace.packetList) {
            packet.writeDelimitedTo(out)
        }
    }

    private fun ensureTrackAssigned() {
        if (trackAssigned) return

        for ((pid, process) in processes) {
            val pUuid = trackUuidGen++
            trackUuids[getTrackKey(pid, 0)] = pUuid

            val processDesc = ProcessDescriptorOuterClass.ProcessDescriptor.newBuilder()
                .setPid(process.pid)
                .setProcessName(process.name)
                .build()
            val td = TrackDescriptorOuterClass.TrackDescriptor.newBuilder()
                .setUuid(pUuid)
                .setName(process.name)
                .setProcess(processDesc)
            perfettoTrace.addPacket(
                TracePacketOuterClass.TracePacket.newBuilder().setTrackDescriptor(td)
            )

            for (thread in process.threads) {
                val tUuid = trackUuidGen++
                trackUuids[getTrackKey(pid, thread.tid)] = tUuid

                val threadDesc = ThreadDescriptorOuterClass.ThreadDescriptor.newBuilder()
                    .setPid(process.pid)
                    .setTid(thread.tid)
                    .setThreadName(thread.name)
                    .build()
                val ttd = TrackDescriptorOuterClass.TrackDescriptor.newBuilder()
                    .setUuid(tUuid)
                    .setParentUuid(pUuid)
                    .setName(thread.name)
                    .setThread(threadDesc)
                    .setDisallowMergingWithSystemTracks(true)

                perfettoTrace.addPacket(
                    TracePacketOuterClass.TracePacket.newBuilder().setTrackDescriptor(ttd)
                )
            }
        }

        trackAssigned = true
    }

    private var processTreeInjected = false

    private fun injectProcessTreePacket() {
        if (processTreeInjected) return
        processTreeInjected = true

        val processTree = ProcessTreeOuterClass.ProcessTree.newBuilder()
        for ((_, process) in processes) {
            processTree.addProcesses(
                ProcessTreeOuterClass.ProcessTree.Process.newBuilder()
                    .setPid(process.pid)
                    .addCmdline(process.name)
            )
            for (thread in process.threads) {
                processTree.addThreads(
                    ProcessTreeOuterClass.ProcessTree.Thread.newBuilder()
                        .setTid(thread.tid)
                        .setTgid(process.pid)
                        .setName(thread.name)
                )
            }
        }

        perfettoTrace.addPacket(
            TracePacketOuterClass.TracePacket.newBuilder().setProcessTree(processTree)
        )
    }

    private fun getTrackUuid(pid: Int, tid: Int): Long {
        return trackUuids[getTrackKey(pid, tid)] ?: -1L
    }

    private fun setDebugValue(
        builder: DebugAnnotationOuterClass.DebugAnnotation.Builder,
        value: Any
    ): DebugAnnotationOuterClass.DebugAnnotation.Builder {
        return when (value) {
            is Double -> builder.setDoubleValue(value)
            is Float -> builder.setDoubleValue(value.toDouble())
            is Long -> builder.setIntValue(value)
            is Int -> builder.setIntValue(value.toLong())
            is Short -> builder.setIntValue(value.toLong())
            is Byte -> builder.setIntValue(value.toLong())
            is Boolean -> builder.setBoolValue(value)
            else -> builder.setStringValue(value.toString())
        }
    }

    private fun getTrackKey(pid: Int, tid: Int) = "${pid}_$tid"
}
