"""atrace-mcp tool modules — register MCP tools by concern."""

from tools.query_tools import register_query_tools
from tools.analysis_tools import register_analysis_tools
from tools.control_tools import register_control_tools
from tools.profiling_tools import register_profiling_tools
from tools.resources import register_resources


def register_all_tools(mcp, analyzer, controller) -> None:
    """Register all tool groups on the FastMCP instance."""
    register_query_tools(mcp, analyzer)
    register_analysis_tools(mcp, analyzer)
    register_control_tools(mcp, controller, analyzer)
    register_profiling_tools(mcp, controller, analyzer)
    register_resources(mcp)
