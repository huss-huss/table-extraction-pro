"""
Helpers for optional dependencies.

Heavy backends (torch/transformers for TATR, camelot/tabula for the rule-based
fallbacks) are imported lazily so the CLI and API start on a base install and
fail with an actionable message only when a missing backend is actually used.
"""

import importlib
import importlib.util
from types import ModuleType

EXTRAS = {
    "torch": "ml",
    "transformers": "ml",
    "timm": "ml",
    "camelot": "fallback",
    "tabula": "fallback",
}


class MissingDependencyError(ImportError):
    """Raised when an optional backend is used without its extra installed."""

    def __init__(self, module: str, extra: str, purpose: str = ""):
        self.module = module
        self.extra = extra
        what = f" (needed for {purpose})" if purpose else ""
        super().__init__(
            f"Optional dependency '{module}' is not installed{what}. "
            f"Install it with: pip install 'table-extraction-pro[{extra}]'"
        )


def require(module: str, purpose: str = "") -> ModuleType:
    """Import ``module`` or raise :class:`MissingDependencyError`."""
    extra = EXTRAS.get(module.split(".")[0], "all")
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingDependencyError(module, extra, purpose) from exc


def is_available(module: str) -> bool:
    """Return True if ``module`` can be imported, without importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def available_backends() -> dict:
    """Report which extraction backends are importable in this environment."""
    return {
        "tatr": is_available("torch") and is_available("transformers"),
        "camelot": is_available("camelot"),
        "tabula": is_available("tabula"),
    }
