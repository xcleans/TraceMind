"""Abstract base for tool providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ToolProvider(ABC):
    """Strategy for discovering and provisioning a single external tool."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable tool name (e.g. 'perfetto')."""

    @abstractmethod
    def resolve_host(self) -> Path | None:
        """Return a host-side binary path, downloading if necessary.

        Returns None when the tool is device-only or unavailable on the host.
        """

    @abstractmethod
    def resolve_device(self, serial: str | None = None) -> str | None:
        """Return the remote path on a connected Android device.

        May push the binary to the device as a side effect.
        Returns None when the tool cannot be provisioned on the device.
        """
