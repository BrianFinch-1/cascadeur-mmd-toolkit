"""Isolate host event dispatch; run in a separate Cascadeur Windows -c process.

Use an unmodified host without the toolkit for a clean baseline. Set
MMD_DISPATCH_OUTPUT to a writable JSON path. The default mode retains the GIL.
MMD_DISPATCH_MODE=unsafe deliberately reproduces the crashing PySide call;
do not run that mode in an application with user work open.
"""
import ctypes
import faulthandler
import json
import os
import sys
import time
from pathlib import Path

output = Path(os.environ["MMD_DISPATCH_OUTPUT"])
fault = output.with_suffix(".fault.log").open("w")
faulthandler.enable(file=fault, all_threads=True)
mode = os.environ.get("MMD_DISPATCH_MODE", "safe")
if mode not in ("safe", "unsafe"):
    raise ValueError("MMD_DISPATCH_MODE must be safe or unsafe")
from PySide6 import QtCore
import csc

host = Path(sys.executable).parent
result = {"mode": mode, "qt": QtCore.qVersion(), "python": sys.version,
          "step": "started"}


def checkpoint(step):
    result["step"] = step
    result["toolkit_modules"] = sorted(
        name for name in sys.modules
        if name == "vmd_bridge" or name.startswith("vmd_bridge.")
        or name == "scripts.vmd_bridge" or name.startswith("scripts.vmd_bridge."))
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")


checkpoint("started")
app = csc.app.get_application()
assert app.get_data_source_manager().load_scene(str(host / "samples/Cascy.casc"))
checkpoint("scene loaded")
time.sleep(1)  # Let the host's native scripting timer become due.
checkpoint("before event dispatch")
if mode == "unsafe":
    # PySide calls PyEval_SaveThread before Qt dispatch. A native host timer
    # reenters Python without acquiring the GIL, with a null thread state.
    QtCore.QCoreApplication.processEvents()
else:
    assert sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8
    assert QtCore.qVersion() == "6.5.3"
    qt = ctypes.PyDLL(str(host / "Qt6Core.dll"))
    process = getattr(qt, "?processEvents@QCoreApplication@@SAXV?$QFlags@W4ProcessEventsFlag@QEventLoop@@@@@Z")
    process.argtypes = [ctypes.c_int]
    process.restype = None
    process(0)
checkpoint("event dispatch passed")
