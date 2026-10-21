"""Use the host's Qt objects without loading incompatible GUI bindings.

Cascadeur 2026.1.3 ships Qt 6.5.3 with inline GUI exports disabled. The
official QtCore, QtNetwork and QtQml bindings work; QtGui/QtQuick do not.
Only window enumeration needs a native call. All UI work uses QObject's
public properties, signals and the host's existing QML engine.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6 import QtCore
from PySide6.QtQml import QQmlEngine


def legacy_host():
    root = Path(__file__).resolve().parents[2]
    return (root / "commands_rule.py").is_file() and not (
        root / "python_actions_rule.py").is_file()


class _WindowList(ctypes.Structure):
    # Qt 6.5 QArrayDataPointer<QWindow*> (qarraydatapointer.h).
    _fields_ = [("data", ctypes.c_void_p),
                ("items", ctypes.POINTER(ctypes.c_void_p)),
                ("size", ctypes.c_ssize_t)]


_window_api = None


def _legacy_windows():
    global _window_api
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8 or QtCore.qVersion() != "6.5.3":
        raise RuntimeError("Legacy window adapter requires Windows x64 Qt 6.5.3")
    if _window_api is None:
        from shiboken6 import wrapInstance
        gui = ctypes.CDLL("Qt6Gui.dll")
        core = ctypes.CDLL("Qt6Core.dll")
        windows = getattr(gui, "?allWindows@QGuiApplication@@SA?AV?$QList@PEAVQWindow@@@@XZ")
        windows.argtypes = []
        windows.restype = _WindowList
        deallocate = getattr(core, "?deallocate@QArrayData@@SAXPEAU1@_J1@Z")
        deallocate.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_ssize_t]
        deallocate.restype = None
        reference_api = ctypes.CDLL(str(Path(__file__).parent / "native" / "qt_list_ref.dll"))
        decrement = reference_api.mmd_atomic_deref
        decrement.argtypes = [ctypes.POINTER(ctypes.c_int32)]
        decrement.restype = ctypes.c_int32
        _window_api = (gui, core, windows, deallocate, decrement, wrapInstance, reference_api)
    _, _, windows, deallocate, decrement, wrap, _ = _window_api
    app = QtCore.QCoreApplication.instance()
    if app is None or QtCore.QThread.currentThread() != app.thread():
        raise RuntimeError("Window enumeration requires Cascadeur's UI thread")
    result = windows()
    try:
        if not 0 <= result.size <= 10000:
            raise RuntimeError("Invalid Qt window list")
        return [wrap(result.items[i], QtCore.QObject) for i in range(result.size)
                if result.items[i]]
    finally:
        # allWindows() returns a shared QList by value. Balance its reference,
        # including the last-owner case; never free or own the QWindow objects.
        if result.data and decrement(ctypes.cast(result.data, ctypes.POINTER(ctypes.c_int32))) == 0:
            deallocate(result.data, ctypes.sizeof(ctypes.c_void_p), 8)


def top_level_windows():
    if legacy_host():
        return [window for window in _legacy_windows()
                if not object_property(window, "parent")]
    from PySide6 import QtGui
    return list(QtGui.QGuiApplication.topLevelWindows())


def object_property(obj, name):
    """Read pointer properties through QML when no QtGui converter exists."""
    context = QQmlEngine.contextForObject(obj)
    if context is not None:
        value = context.engine().newQObject(obj).property(name)
        if value.isQObject():
            return value.toQObject()
        if value.isNull() or value.isUndefined():
            return None
        return value.toVariant()
    return obj.property(name)


def set_transient_parent(window, parent):
    if not legacy_host():
        window.setTransientParent(parent)
        return
    context = QQmlEngine.contextForObject(window)
    if context is None:
        raise RuntimeError("Window has no host QML context")
    engine = context.engine()
    engine.newQObject(window).setProperty("transientParent", engine.newQObject(parent))


def set_modality(window, value):
    if not legacy_host():
        window.setModality(value)
        return
    window.setProperty("modality", int(value.value))
