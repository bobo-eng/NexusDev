"""Platform adapters for OpenClaw and OpenWork integration."""

from .openclaw.adapter import OpenClawAdapter
from .openwork.adapter import OpenWorkAdapter

__all__ = [
    "OpenClawAdapter",
    "OpenWorkAdapter",
]
