"""
End-to-end tests for App HTTP Control MCP tools.
Stack: server.py tool fn → DeviceController method → HTTP params → JSON output.
"""
import sys
import json
import unittest.mock as mock

# ── Block all native / heavy deps before any import ──────────────────────────
for _mod in [
    "httpx", "fastmcp", "tool_provisioner",
    "perfetto", "perfetto.trace_processor", "perfetto.trace_processor.api",
]:
    sys.modules[_mod] = mock.MagicMock()

# Intercept FastMCP so @mcp.tool just stores each bare function
import fastmcp  # noqa: E402

_mcp_inst = mock.MagicMock()
_registered: dict = {}


def _tool_deco(fn):
    _registered[fn.__name__] = fn
    return fn


_mcp_inst.tool = _tool_deco
fastmcp.FastMCP.return_value = _mcp_inst

# Now import modules under test — server.py runs @mcp.tool decorations on import
import device_controller as dc_mod  # noqa: E402
import server as srv  # noqa: E402  — side-effect: registers all @mcp.tool functions

# ── Harness ───────────────────────────────────────────────────────────────────
PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    sym = "[PASS]" if cond else "[FAIL]"
    suffix = f"  ← {detail}" if (not cond and detail) else ""
    print(f"  {sym} {label}{suffix}")
    if cond:
        PASS += 1
    else:
        FAIL += 1


def parse(s: str) -> dict:
    return json.loads(s)


# ── FakeCtrl — returns real dicts, no ADB/HTTP ────────────────────────────────
RESPONSES = {
    "status":   {"initialized": True, "tracing": False, "pid": 1234},
    "debug":    {"sampling": {"capacity": 10000, "start": 0, "end": 500}},
    "pause":    {"ok": True, "paused": True},
    "resume":   {"ok": True, "paused": False},
    "plugins":  {"plugins": [{"id": "binder", "enabled": True},
                              {"id": "gc",     "enabled": False}]},
    "sampling": {"mainThreadInterval": 1_000_000, "otherThreadInterval": 2_000_000},
    "threads":  {"threads": [{"tid": 1234, "name": "main", "is_main": True}]},
}


class FakeCtrl:
    _created: list = []

    def __init__(self, serial=None, port=9090, package=None):
        self.serial = serial
        self.port = port
        self.package = package
        FakeCtrl._created.append({"serial": serial, "port": port, "package": package})

    def app_status(self):
        return dict(RESPONSES["status"])

    def app_debug_info(self):
        return dict(RESPONSES["debug"])

    def pause_trace(self):
        return dict(RESPONSES["pause"])

    def resume_trace(self):
        return dict(RESPONSES["resume"])

    def list_plugins(self):
        return {"plugins": [dict(p) for p in RESPONSES["plugins"]["plugins"]]}

    def toggle_plugin(self, plugin_id: str, enable: bool):
        return {"ok": True, "id": plugin_id, "enabled": enable}

    def get_sampling_config(self):
        return dict(RESPONSES["sampling"])

    def set_sampling_interval(self, main_interval_ns: int = 0, other_interval_ns: int = 0):
        return {"ok": True, "main": main_interval_ns, "other": other_interval_ns}

    def list_threads(self):
        return {"threads": [dict(t) for t in RESPONSES["threads"]["threads"]]}

    def add_mark(self, name: str):
        return {"ok": True, "mark": name}

    def capture_stack(self, force: bool = False):
        return {"ok": True, "force": force}


def run(tool_name: str, **kwargs):
    FakeCtrl._created.clear()
    # Patch the name in server's namespace (server does `from device_controller import DeviceController`)
    with mock.patch.object(srv, "DeviceController", FakeCtrl):
        return _registered[tool_name](**kwargs)


PKG = "com.example.app"

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 1. query_app_status ───────────────────────────────────────────────")
r = parse(run("query_app_status", package=PKG))
check("keys: status + debug",        set(r) >= {"status", "debug"})
check("status.initialized=True",      r["status"].get("initialized") is True)
check("status.pid=1234",              r["status"].get("pid") == 1234)
check("debug.sampling present",       "sampling" in r["debug"])

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 2. pause_tracing ──────────────────────────────────────────────────")
r = parse(run("pause_tracing", package=PKG))
check("ok=True",     r.get("ok") is True)
check("paused=True", r.get("paused") is True)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 3. resume_tracing ─────────────────────────────────────────────────")
r = parse(run("resume_tracing", package=PKG))
check("ok=True",      r.get("ok") is True)
check("paused=False", r.get("paused") is False)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 4. list_plugins ───────────────────────────────────────────────────")
r = parse(run("list_plugins", package=PKG))
check("plugins is list",   isinstance(r.get("plugins"), list))
check("2 plugins returned", len(r["plugins"]) == 2)
ids = {p["id"] for p in r["plugins"]}
check("binder present",    "binder" in ids)
check("gc present",        "gc" in ids)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 5. toggle_plugin ──────────────────────────────────────────────────")
for pid in ["binder", "gc", "lock", "jni", "loadlib", "alloc", "msgqueue", "io"]:
    r = parse(run("toggle_plugin", plugin_id=pid, enable=True, package=PKG))
    check(f"enable {pid}: id correct",    r.get("id") == pid)
    check(f"enable {pid}: enabled=True",  r.get("enabled") is True)

r = parse(run("toggle_plugin", plugin_id="binder", enable=False, package=PKG))
check("disable binder: enabled=False", r.get("enabled") is False)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 6. get_sampling_config ────────────────────────────────────────────")
r = parse(run("get_sampling_config", package=PKG))
check("mainThreadInterval=1_000_000",  r.get("mainThreadInterval")  == 1_000_000)
check("otherThreadInterval=2_000_000", r.get("otherThreadInterval") == 2_000_000)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 7. set_sampling_interval ──────────────────────────────────────────")
r = parse(run("set_sampling_interval",
              main_interval_ns=500_000, other_interval_ns=1_000_000, package=PKG))
check("ok=True",        r.get("ok") is True)
check("main=500_000",   r.get("main") == 500_000)
check("other=1_000_000",r.get("other") == 1_000_000)

r = parse(run("set_sampling_interval", main_interval_ns=2_000_000, package=PKG))
check("only-main: main=2_000_000",  r.get("main") == 2_000_000)
check("only-main: other=0",         r.get("other") == 0)

r = parse(run("set_sampling_interval", other_interval_ns=5_000_000, package=PKG))
check("only-other: main=0",          r.get("main") == 0)
check("only-other: other=5_000_000", r.get("other") == 5_000_000)

r = parse(run("set_sampling_interval", package=PKG))  # both default 0
check("zero-both: ok=True", r.get("ok") is True)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 8. query_threads ──────────────────────────────────────────────────")
r = parse(run("query_threads", package=PKG))
check("threads is list",           isinstance(r.get("threads"), list))
check("1 thread returned",         len(r["threads"]) == 1)
t = r["threads"][0]
check("tid=1234",                  t.get("tid") == 1234)
check("name=main",                 t.get("name") == "main")
check("is_main=True",              t.get("is_main") is True)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 9. add_trace_mark ─────────────────────────────────────────────────")
for mark in ["user_login_start", "api_response_ok", "diag_frame_drop"]:
    r = parse(run("add_trace_mark", name=mark, package=PKG))
    check(f"'{mark}': ok=True",      r.get("ok") is True)
    check(f"'{mark}': name echoed",  r.get("mark") == mark)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 10. capture_stack ─────────────────────────────────────────────────")
r = parse(run("capture_stack", force=False, package=PKG))
check("force=False: ok=True",   r.get("ok") is True)
check("force=False: echoed",    r.get("force") is False)

r = parse(run("capture_stack", force=True, package=PKG))
check("force=True: echoed",     r.get("force") is True)

# ══════════════════════════════════════════════════════════════════════════════
print()
print("── 11. package / port / serial propagation ───────────────────────────")

HTTP_TOOLS = [
    ("query_app_status",     {"package": "com.foo", "port": 9191}),
    ("pause_tracing",        {"package": "com.foo", "port": 9191}),
    ("resume_tracing",       {"package": "com.foo", "port": 9191}),
    ("list_plugins",         {"package": "com.foo", "port": 9191}),
    ("toggle_plugin",        {"plugin_id": "gc", "enable": True, "package": "com.foo", "port": 9191}),
    ("get_sampling_config",  {"package": "com.foo", "port": 9191}),
    ("set_sampling_interval",{"main_interval_ns": 1000, "package": "com.foo", "port": 9191}),
    ("query_threads",        {"package": "com.foo", "port": 9191}),
    ("add_trace_mark",       {"name": "x", "package": "com.foo", "port": 9191}),
    ("capture_stack",        {"package": "com.foo", "port": 9191}),
]

for tname, kwargs in HTTP_TOOLS:
    run(tname, **kwargs)
    c = FakeCtrl._created[-1]
    check(f"{tname}: package=com.foo",  c["package"] == "com.foo")
    check(f"{tname}: port=9191",         c["port"] == 9191)

# serial defaults to None
run("pause_tracing", package="com.foo")
check("serial defaults None",            FakeCtrl._created[-1]["serial"] is None)

# custom serial
run("list_plugins", package="com.foo", serial="emulator-5554")
check("serial=emulator-5554",            FakeCtrl._created[-1]["serial"] == "emulator-5554")

# ── Error path: exception becomes "Error: ..." string ─────────────────────────
print()
print("── 12. error handling ────────────────────────────────────────────────")


class BrokenCtrl(FakeCtrl):
    def app_status(self):
        raise RuntimeError("device disconnected")

    def pause_trace(self):
        raise RuntimeError("timeout")


with mock.patch.object(srv, "DeviceController", BrokenCtrl):
    r = _registered["query_app_status"](package=PKG)
check("exception → 'Error: ...' string",  r.startswith("Error:"))
check("error message included",           "device disconnected" in r)

with mock.patch.object(srv, "DeviceController", BrokenCtrl):
    r = _registered["pause_tracing"](package=PKG)
check("pause exception → Error string",   r.startswith("Error:"))

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 62)
print(f"Result: {PASS} passed, {FAIL} failed")
if FAIL > 0:
    sys.exit(1)
else:
    print("All App HTTP Control tests passed.")
