"""atrace-analyzer — Trace analysis engine for TraceMind."""


def __getattr__(name: str):
    if name in ("TraceAnalyzer", "TraceSession"):
        from atrace_analyzer.analyzer import TraceAnalyzer, TraceSession
        globals()["TraceAnalyzer"] = TraceAnalyzer
        globals()["TraceSession"] = TraceSession
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["TraceAnalyzer", "TraceSession"]
