"""Mock-Test für local_worker/worker.keep_awake.

Kein Netz, kein Server. Prüft das Verhalten ausschließlich mit gefaktem
ctypes.windll (SetThreadExecutionState) und os.name = 'nt'.
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

WORKER_PATH = Path(__file__).resolve().parents[2] / "local_worker" / "worker.py"


def _load_keep_awake():
    """Lädt NUR die Funktion keep_awake aus worker.py, ohne das Modul auszuführen
    (worker.py startet beim Import interaktiv Config-Prompts). Wir ziehen den
    Funktionsquelltext per AST raus und kompilieren ihn eigenständig."""
    import ast

    src = WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "keep_awake")
    mod = ast.Module(body=[fn], type_ignores=[])
    code = compile(mod, str(WORKER_PATH), "exec")
    ns = {"os": os}
    exec(code, ns)  # noqa: S102
    return ns["keep_awake"]


class _FakeK32:
    def __init__(self, first_call_ret=1, second_call_ret=1, raise_exc=None):
        self.calls = []
        self._first = first_call_ret
        self._second = second_call_ret
        self._raise = raise_exc

    def SetThreadExecutionState(self, flags):  # noqa: N802
        self.calls.append(flags)
        if self._raise and len(self.calls) == 1:
            raise self._raise
        return self._first if len(self.calls) == 1 else self._second


def _install_fake_ctypes(k32):
    """Install a minimal ctypes-module replacement with ctypes.windll.kernel32."""
    fake = types.SimpleNamespace()
    fake.windll = types.SimpleNamespace(kernel32=k32)
    sys.modules["ctypes"] = fake
    return fake


@pytest.fixture
def keep_awake():
    return _load_keep_awake()


@pytest.fixture
def restore_ctypes():
    original = sys.modules.get("ctypes")
    yield
    if original is not None:
        sys.modules["ctypes"] = original
    else:
        sys.modules.pop("ctypes", None)


# --- Verhalten auf Nicht-Windows ---------------------------------------------
def test_returns_false_on_non_windows(monkeypatch, keep_awake):
    monkeypatch.setattr(os, "name", "posix", raising=False)
    monkeypatch.delenv("WORKER_KEEP_AWAKE", raising=False)
    assert keep_awake() is False


# --- WORKER_KEEP_AWAKE=0 schaltet ab ------------------------------------------
def test_disabled_via_env(monkeypatch, keep_awake):
    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.setenv("WORKER_KEEP_AWAKE", "0")
    assert keep_awake() is False


# --- Erfolgsfall Windows: erster Aufruf reicht --------------------------------
def test_windows_success_first_call(monkeypatch, restore_ctypes, keep_awake):
    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.delenv("WORKER_KEEP_AWAKE", raising=False)
    k32 = _FakeK32(first_call_ret=1)
    _install_fake_ctypes(k32)
    assert keep_awake() is True
    assert len(k32.calls) == 1
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED = 0x80000041
    assert k32.calls[0] == (0x80000000 | 0x1 | 0x40)


# --- Fallback: AWAYMODE abgelehnt (0), zweiter Aufruf OK ----------------------
def test_windows_fallback_without_awaymode(monkeypatch, restore_ctypes, keep_awake):
    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.delenv("WORKER_KEEP_AWAKE", raising=False)
    k32 = _FakeK32(first_call_ret=0, second_call_ret=1)
    _install_fake_ctypes(k32)
    assert keep_awake() is True
    assert len(k32.calls) == 2
    assert k32.calls[0] == (0x80000000 | 0x1 | 0x40)
    assert k32.calls[1] == (0x80000000 | 0x1)  # ohne ES_AWAYMODE_REQUIRED


# --- Beide Aufrufe liefern 0 -> False -----------------------------------------
def test_windows_both_calls_fail(monkeypatch, restore_ctypes, keep_awake):
    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.delenv("WORKER_KEEP_AWAKE", raising=False)
    k32 = _FakeK32(first_call_ret=0, second_call_ret=0)
    _install_fake_ctypes(k32)
    assert keep_awake() is False
    assert len(k32.calls) == 2


# --- Exception darf nie nach aussen dringen -----------------------------------
def test_windows_exception_swallowed(monkeypatch, restore_ctypes, keep_awake):
    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.delenv("WORKER_KEEP_AWAKE", raising=False)
    k32 = _FakeK32(raise_exc=OSError("simulated"))
    _install_fake_ctypes(k32)
    # Darf keine Exception raisen, Rückgabe ist False
    assert keep_awake() is False


# --- ctypes selbst fehlt -> False, keine Exception ----------------------------
def test_windows_ctypes_import_error(monkeypatch, restore_ctypes, keep_awake):
    monkeypatch.setattr(os, "name", "nt", raising=False)
    monkeypatch.delenv("WORKER_KEEP_AWAKE", raising=False)
    # ctypes so kaputt machen, dass windll.kernel32 nicht existiert
    sys.modules["ctypes"] = types.SimpleNamespace()  # ohne .windll
    assert keep_awake() is False
