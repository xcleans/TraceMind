package com.aspect.atrace.tool.perfetto

import java.io.ByteArrayOutputStream
import java.io.OutputStream

/**
 * Lightweight protobuf wire-format encoder compatible with pbzero / standard protobuf.
 *
 * Supports varint, fixed64, length-delimited (bytes/string/nested message) encoding.
 * No dependency on protobuf-java; produces identical binary output.
 */
class ProtoWriter(private val buffer: ByteArrayOutputStream = ByteArrayOutputStream(4096)) {

    companion object {
        const val WIRETYPE_VARINT = 0
        const val WIRETYPE_FIXED64 = 1
        const val WIRETYPE_LENGTH_DELIMITED = 2
        const val WIRETYPE_FIXED32 = 5
    }

    fun writeVarInt(fieldNumber: Int, value: Long) {
        writeTag(fieldNumber, WIRETYPE_VARINT)
        writeRawVarint(value)
    }

    fun writeUInt32(fieldNumber: Int, value: Int) {
        writeTag(fieldNumber, WIRETYPE_VARINT)
        writeRawVarint(value.toLong() and 0xFFFFFFFFL)
    }

    fun writeInt32(fieldNumber: Int, value: Int) {
        writeTag(fieldNumber, WIRETYPE_VARINT)
        writeRawVarint(value.toLong())
    }

    fun writeUInt64(fieldNumber: Int, value: Long) {
        writeTag(fieldNumber, WIRETYPE_VARINT)
        writeRawVarint(value)
    }

    fun writeBool(fieldNumber: Int, value: Boolean) {
        writeTag(fieldNumber, WIRETYPE_VARINT)
        buffer.write(if (value) 1 else 0)
    }

    fun writeFixed64(fieldNumber: Int, value: Long) {
        writeTag(fieldNumber, WIRETYPE_FIXED64)
        writeRawFixed64(value)
    }

    fun writeDouble(fieldNumber: Int, value: Double) {
        writeFixed64(fieldNumber, java.lang.Double.doubleToRawLongBits(value))
    }

    fun writeString(fieldNumber: Int, value: String) {
        val bytes = value.toByteArray(Charsets.UTF_8)
        writeTag(fieldNumber, WIRETYPE_LENGTH_DELIMITED)
        writeRawVarint(bytes.size.toLong())
        buffer.write(bytes)
    }

    fun writeBytes(fieldNumber: Int, value: ByteArray) {
        writeTag(fieldNumber, WIRETYPE_LENGTH_DELIMITED)
        writeRawVarint(value.size.toLong())
        buffer.write(value)
    }

    fun writeNested(fieldNumber: Int, nested: ProtoWriter) {
        val data = nested.toByteArray()
        writeTag(fieldNumber, WIRETYPE_LENGTH_DELIMITED)
        writeRawVarint(data.size.toLong())
        buffer.write(data)
    }

    fun toByteArray(): ByteArray = buffer.toByteArray()

    fun size(): Int = buffer.size()

    fun writeTo(out: OutputStream) {
        buffer.writeTo(out)
    }

    fun reset() {
        buffer.reset()
    }

    private fun writeTag(fieldNumber: Int, wireType: Int) {
        writeRawVarint(((fieldNumber shl 3) or wireType).toLong())
    }

    private fun writeRawVarint(value: Long) {
        var v = value
        while (true) {
            if (v and 0x7FL.inv() == 0L) {
                buffer.write(v.toInt())
                return
            }
            buffer.write(((v.toInt() and 0x7F) or 0x80))
            v = v ushr 7
        }
    }

    private fun writeRawFixed64(value: Long) {
        buffer.write((value and 0xFF).toInt())
        buffer.write(((value shr 8) and 0xFF).toInt())
        buffer.write(((value shr 16) and 0xFF).toInt())
        buffer.write(((value shr 24) and 0xFF).toInt())
        buffer.write(((value shr 32) and 0xFF).toInt())
        buffer.write(((value shr 40) and 0xFF).toInt())
        buffer.write(((value shr 48) and 0xFF).toInt())
        buffer.write(((value shr 56) and 0xFF).toInt())
    }
}
