#!/usr/bin/env python3
"""Serve a trace file with CORS so https://ui.perfetto.dev can fetch it.

Usage:
  python serve_trace_for_perfetto.py /tmp/atrace/heap_1773048826.perfetto

Recommended: open https://ui.perfetto.dev → "Open trace file" → select the
trace file (no CORS issues). Or use the URL below if serving with CORS.
"""
import http.server
import os
import socketserver
import sys

PORT = 9001


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format, *args):
        print("[%s] %s" % (self.log_date_time_string(), format % args))


def main():
    if len(sys.argv) < 2:
        print("Usage: python serve_trace_for_perfetto.py <trace_file>")
        sys.exit(1)
    trace_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(trace_path):
        print("Not a file:", trace_path)
        sys.exit(1)
    os.chdir(os.path.dirname(trace_path))
    fname = os.path.basename(trace_path)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), CORSRequestHandler) as httpd:
        url = f"https://ui.perfetto.dev/#!/?url=http://127.0.0.1:{PORT}/{fname}&referrer=record_android_trace"
        print(f"Serving trace with CORS on http://127.0.0.1:{PORT}/")
        print(f"Open in browser:\n  {url}")
        print("Press Ctrl+C to stop.")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
