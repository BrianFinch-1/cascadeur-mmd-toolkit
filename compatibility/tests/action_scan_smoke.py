"""Exercise real host action discovery before toolkit install()/menu callbacks.

Run in a fresh Windows Cascadeur -c process with the toolkit installed.
Set MMD_SCAN_OUTPUT to the result JSON path. No scene or UI is modified.
"""
import importlib
import json
import logging
import os
import sys
import traceback
from pathlib import Path


class Errors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.messages = []

    def emit(self, record):
        if "vmd_bridge" in record.getMessage():
            self.messages.append(record.getMessage())


result = {"ok": False}
capture = Errors()
logging.getLogger().addHandler(capture)
try:
    # Assert this is a real early-import test, not a warmed install() path.
    result["initial_package_names"] = [name for name in ("vmd_bridge", "scripts.vmd_bridge")
                                       if name in sys.modules]
    for name in result["initial_package_names"]:
        assert sys.modules[name]._translator is None, "install() already ran"
    python_root = Path(sys.executable).parent / "resources/scripts/python"
    # Host startup may already have scanned the package (and logged failures).
    # Recreate cold dependency imports in this isolated, scene-free process so
    # a later successful retry cannot hide the initialization-order defect.
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".")
               for prefix in ("vmd_bridge", "scripts.vmd_bridge", "cascadeur_vmd")):
            del sys.modules[name]
    vendor = os.path.normcase(str((python_root / "scripts/vmd_bridge/deps").resolve()))
    sys.path[:] = [entry for entry in sys.path
                   if os.path.normcase(str(Path(entry).resolve())) != vendor]
    result["cold_import_cache_reset"] = True
    modern = (python_root / "python_actions_rule.py").is_file()
    rule = importlib.import_module("python_actions_rule" if modern else "commands_rule")
    discover = rule.get_actions if modern else rule.get_commands
    discover("scripts.vmd_bridge" if modern else "commands.mmd_toolkit")
    assert not capture.messages, capture.messages
    # Both package spellings must import the full helper tree successfully.
    import importlib.util
    hook = python_root / "events/scene_activated/vmd_menu_inject.py"
    spec = importlib.util.spec_from_file_location("mmd_scan_hook", hook)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._load_product_package()
    for prefix in ("scripts.vmd_bridge", "vmd_bridge"):
        for name in ("export_core", "export_host", "export_ik", "export_validate",
                     "gen_controller_bake", "relative_controller", "twist_position"):
            importlib.import_module(prefix + "." + name)
    assert not capture.messages, capture.messages
    result.update(ok=True, checks=["early host action scan has no toolkit import errors",
                                   "helper imports work under both package names"])
except Exception:
    result["error"] = traceback.format_exc()
finally:
    result["logged_errors"] = capture.messages
    logging.getLogger().removeHandler(capture)
    Path(os.environ["MMD_SCAN_OUTPUT"]).write_text(json.dumps(result, indent=2), encoding="utf-8")
