from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class EpicsUnavailableError(RuntimeError):
    """Raised when pyepics is unavailable."""


class ReadOnlyViolationError(RuntimeError):
    """Raised when a write is attempted in Stage 0 read-only mode."""


def _import_epics():
    try:
        import epics  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on host packages
        raise EpicsUnavailableError("pyepics is required for live SSMB logging.") from exc
    return epics


@dataclass
class PVHandle:
    pv: Any
    name: str
    timeout: float

    def get(self):
        return self.pv.get(timeout=self.timeout, use_monitor=False)

    def put(self, value):
        return self.pv.put(value)


class ReadOnlyEpicsAdapter:
    """Minimal cached EPICS adapter for passive logging."""

    def __init__(self, timeout: float = 0.5):
        self.timeout = timeout
        self._epics = _import_epics()
        self._cache: Dict[str, PVHandle] = {}

    def pv(self, name: str) -> PVHandle:
        handle = self._cache.get(name)
        if handle is None:
            pv = self._epics.PV(name, connection_timeout=self.timeout)
            handle = PVHandle(pv=pv, name=name, timeout=self.timeout)
            self._cache[name] = handle
        return handle

    def get(self, name: str, default=None):
        if not name:
            return default
        value = self.pv(name).get()
        if value is None:
            return default
        return value

    def put(self, name: str, value):
        raise ReadOnlyViolationError("Stage 0 SSMB logging is read-only; refusing write to %s." % name)


class FakeEpicsAdapter:
    """Simple in-memory adapter for tests."""

    def __init__(self, values: Optional[Dict[str, Any]] = None):
        self.values = dict(values or {})
        self.put_calls = []

    def get(self, name: str, default=None):
        return self.values.get(name, default)

    def put(self, name: str, value):
        self.put_calls.append((name, value))
        raise ReadOnlyViolationError("Fake adapter is read-only in tests.")
