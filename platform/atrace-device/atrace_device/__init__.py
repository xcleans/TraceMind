"""atrace-device — Device gateway for TraceMind.

Provides ADB bridge, App HTTP client, file transfer, and
atrace-tool CLI dispatcher.
"""

from atrace_device.adb_bridge import AdbBridge
from atrace_device.app_client import AppHttpClient
from atrace_device.file_transfer import FileTransfer
from atrace_device.device_info import DeviceInfo, get_device_info, get_device_info_dict
from atrace_device.engine_cli import EngineCLI

__all__ = [
    "AdbBridge",
    "AppHttpClient",
    "FileTransfer",
    "DeviceInfo",
    "get_device_info",
    "get_device_info_dict",
    "EngineCLI",
]
