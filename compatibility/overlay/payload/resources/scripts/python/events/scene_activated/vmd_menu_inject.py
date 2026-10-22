# -*- coding: utf-8 -*-
"""Cascadeur scene_activated hook for the VMD importer.

The event handler itself only queues work. This avoids doing imports, socket
setup or QML traversal inside Cascadeur's event callback iteration.
"""
from __future__ import print_function

import importlib.util
import os
import sys


def _product_package_init():
    """Return the shipped package, independent of cwd/sys.path ordering."""
    hook_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        os.path.join(hook_dir, "vmd_bridge", "__init__.py"),
        os.path.join(os.path.dirname(os.path.dirname(hook_dir)),
                     "scripts", "vmd_bridge", "__init__.py"),
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.normcase(os.path.abspath(candidate))
    raise ImportError("shipped vmd_bridge package not found; tried %r" %
                      (candidates,))


def _load_product_package():
    """Load the exact shipped package and evict same-name shadow packages."""
    init_path = _product_package_init()
    current = sys.modules.get("vmd_bridge")
    current_path = getattr(current, "__file__", "") if current else ""
    if current_path and os.path.normcase(os.path.abspath(current_path)) == init_path:
        return current

    for name in list(sys.modules):
        if name == "vmd_bridge" or name.startswith("vmd_bridge."):
            del sys.modules[name]

    package_dir = os.path.dirname(init_path)
    spec = importlib.util.spec_from_file_location(
        "vmd_bridge", init_path,
        submodule_search_locations=[package_dir],
    )
    if spec is None or spec.loader is None:
        raise ImportError("cannot create loader for %s" % init_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["vmd_bridge"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop("vmd_bridge", None)
        raise
    print("VMD product package loaded from: %s" % init_path)
    return module


def _install_product(vmd_bridge, scene):
    try:
        vmd_bridge.install(scene)
    except Exception as exc:
        try:
            vmd_bridge._logging.logger().exception(
                "delayed VMD menu injection failed")
        except Exception:
            print("VMD delayed menu injection failed: %s: %s" %
                  (type(exc).__name__, exc))


def _activate(scene):
    try:
        vmd_bridge = _load_product_package()
        from vmd_bridge import qt_compat
        if not qt_compat.legacy_host():
            # Modern hosts provide the callback transport used by D3D11.dll.
            try:
                import scripts.mcp.script_server.server as script_server
                if not script_server.is_running():
                    script_server.start(scene)
            except Exception as exc:
                print("VMD callback server start failed: %s: %s" %
                      (type(exc).__name__, exc))
        # scene_activated can precede the DLL's ActionManager registration by
        # a fraction of a second. CustomMenu.create silently rejects unknown
        # actions, so wait until both the QML tree and native action exist.
        from PySide6 import QtCore
        QtCore.QTimer.singleShot(
            2000, lambda: _install_product(vmd_bridge, scene))
    except Exception as exc:
        print("VMD menu injection failed: %s: %s" %
              (type(exc).__name__, exc))


def run(scene):
    try:
        from PySide6 import QtCore
        QtCore.QTimer.singleShot(0, lambda: _activate(scene))
    except Exception as exc:
        print("VMD menu activation queue failed: %s: %s" %
              (type(exc).__name__, exc))
