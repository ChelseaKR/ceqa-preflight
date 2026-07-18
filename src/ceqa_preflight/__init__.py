"""CEQA Preflight package."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("ceqa-preflight")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.1.0"
