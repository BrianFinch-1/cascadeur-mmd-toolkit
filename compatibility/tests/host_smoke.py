"""Run with Cascadeur 2026.1.3 Windows -c after installing the legacy profile.

Command mode does not create Cascadeur's main GUI. This test creates real QML
windows/menus inside its QGuiApplication and exercises toolkit callbacks there.
It also uses the real csc scene/API and the host's command discovery rule.
Set MMD_SMOKE_OUTPUT to a writable result path before exec-ing this file.
"""
import importlib.util
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


def run():
    from PySide6 import QtCore, QtQml
    import csc

    host = Path(sys.executable).parent
    python_root = host / "resources/scripts/python"
    hook = python_root / "events/scene_activated/vmd_menu_inject.py"
    spec = importlib.util.spec_from_file_location("mmd_hook_test", hook)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    toolkit = module._load_product_package()
    sys.path.insert(0, str(Path(toolkit.__file__).parent / "deps"))
    from vmd_bridge import qt_compat, legacy_menu, menu, export_menu, dialogs, export_dialogs

    legacy = qt_compat.legacy_host()
    assert QtCore.qVersion() == "6.5.3"
    if legacy:
        assert "PySide6.QtGui" not in sys.modules and "PySide6.QtQuick" not in sys.modules
    checks = ["minimal Qt bindings load; exact package loaded by original event hook"]
    if legacy:
        import commands_rule
        commands = commands_rule.get_commands("commands.mmd_toolkit")
        assert "cascadeur MMD toolkit.Scene Clean" in commands, commands
        checks.append("Scene Clean discovered through real legacy commands_rule")
    else:
        import commands.mmd_toolkit.scene_clean as clean_command
        assert clean_command.name() == "cascadeur MMD toolkit.Scene Clean"
        checks.append("modern Scene Clean command name preserved")

    application = csc.app.get_application()
    assert application.get_data_source_manager().load_scene(str(host / "samples/Cascy.casc"))
    scene = application.get_scene_manager().current_scene()
    assert scene is not None
    from vmd_bridge.scene_guard import joint_inventory
    inventory = joint_inventory(scene.domain_scene())
    from vmd_bridge.bridge_adapter import AdapterReader
    from vmd_bridge.export_host import LiveReader
    domain = scene.domain_scene()
    snapshot = AdapterReader(scene, domain)._snapshot(domain)
    assert snapshot["records"]
    LiveReader(domain)
    checks.append("real scene/domain snapshot: %d objects, %d joints (%s)" %
                  (len(snapshot["records"]), len(inventory), scene.get_path_name()))

    with tempfile.TemporaryDirectory(prefix="mmd-qml-test-") as directory:
        folder = Path(directory)
        (folder / "CustomMenu.qml").write_text('''import QtQuick
import QtQuick.Controls
Menu {
    property string titleId: ""
    property var subNode: []
    function updateItems() {} // Native ActionManager path is intentionally absent.
}
''', encoding="utf-8")
        window_file = "MainWindow.qml" if legacy else "MmdSmokeWindow.qml"
        (folder / window_file).write_text('''import QtQuick
import QtQuick.Controls
ApplicationWindow {
    id: main
    property bool fixture: true
    objectName: "MainWindow"
    visible: true; width: 720; height: 480
    menuBar: MenuBar {
        CustomMenu {
            title: "Import"; titleId: "MenuBar.Import"
            subNode: ["File.Import.Fbx/Dae"]
            MenuItem { objectName: "File.Import.Fbx/Dae"; text: "FBX" }
        }
        CustomMenu {
            title: "Export"; titleId: "MenuBar.Export"
            subNode: ["File.Export.Fbx/Dae"]
            MenuItem { objectName: "File.Export.Fbx/Dae"; text: "FBX" }
        }
    }
}
''', encoding="utf-8")
        engine = QtQml.QQmlEngine()
        component = QtQml.QQmlComponent(engine, QtCore.QUrl.fromLocalFile(str(folder / window_file)))
        main = component.create()
        assert main is not None, [e.toString() for e in component.errors()]
        if legacy:
            assert menu.find_main_window() is not None, main.metaObject().className()
        else:
            main.setObjectName("MmdSmokeWindow")
        assert main in qt_compat.top_level_windows()
        for _ in range(1000):
            assert main in qt_compat.top_level_windows()
        checks.append("1000 native window-list enumerations with real QML window")

        if legacy:
            callbacks = []
            toolkit._on_import_vmd = lambda: callbacks.append("import")
            toolkit._on_export_vmd = lambda: callbacks.append("export")
            assert toolkit.install(scene)
            for _ in range(3):
                assert menu.install()
                assert export_menu.install()
            assert set(legacy_menu._records) == {menu.ACTION_KEY, export_menu.KEY}
            for key, record in legacy_menu._records.items():
                matches = [obj for obj in record["menu"].findChildren(QtCore.QObject)
                           if obj.objectName() == key]
                assert len(matches) == 1, (key, matches)
                assert record["item"].property("text") in ("Import VMD", "Export VMD")
                record["item"].triggered.emit()
            QtCore.QCoreApplication.processEvents()
            assert sorted(callbacks) == ["export", "import"], callbacks
            checks.append("Import/Export menu injection, repeated installation, queued callbacks")

            # Rebuilding a host menu may destroy its dynamic items. Refresh must
            # create exactly one replacement and keep the same callback.
            record = legacy_menu._records[menu.ACTION_KEY]
            item = record["item"]
            js = engine.evaluate("(function(m, i) { m.removeItem(i); })")
            js.call([engine.newQObject(record["menu"]), engine.newQObject(item)])
            item.deleteLater()
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            QtCore.QCoreApplication.processEvents()
            from shiboken6 import isValid
            assert not isValid(item)
            record["ensure"]()
            assert record["item"] is not item
            record["item"].triggered.emit()
            QtCore.QCoreApplication.processEvents()
            assert callbacks.count("import") == 2
            checks.append("menu item refreshed after host rebuild")

        else:
            assert qt_compat._window_api is None
            checks.append("modern window discovery uses host PySide6 GUI bindings")

        assert dialogs.show_message("Compatibility test", "测试 / test")
        assert dialogs._message_record["object"].property("visible")
        dialogs._message_record["object"].dismissed.emit()
        QtCore.QCoreApplication.processEvents()
        assert dialogs._message_record is None
        decisions = []
        assert dialogs.confirm("Test", "Continue?", lambda: decisions.append("yes"), lambda: decisions.append("no"))
        record = dialogs._confirm_record
        record["object"].confirmed.emit()
        record["object"].declined.emit()
        QtCore.QCoreApplication.processEvents()
        assert decisions == ["yes"], decisions
        selected = []
        record = dialogs.choose_model([{"label": "Model", "joint_count": 5}], selected.append,
                                      lambda: selected.append("cancel"), multiple=True)
        record["object"].modelSelected.emit([0])
        QtCore.QCoreApplication.processEvents()
        assert selected == [[0]], selected
        strategies = []
        record = dialogs.choose_export_strategy(False, strategies.append, lambda: strategies.append("cancel"))
        record["object"].strategySelected.emit("weight")
        QtCore.QCoreApplication.processEvents()
        assert strategies == ["weight"], strategies
        progress = export_dialogs.ExportProgress()
        progress.update(.5, "Test")
        progress.record["object"].cancelRequested.emit()
        assert progress.canceled
        progress.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        QtCore.QCoreApplication.processEvents()
        checks.append("message, confirmation, model chooser, export strategy and progress lifecycles")
        assert not dialogs._live, dialogs._live
        main.setProperty("visible", False)
        main.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    if legacy:
        assert "PySide6.QtGui" not in sys.modules and "PySide6.QtQuick" not in sys.modules
    return checks


result = {"ok": False}
try:
    result["checks"] = run()
    result["ok"] = True
except Exception:
    result["error"] = traceback.format_exc()
finally:
    Path(os.environ["MMD_SMOKE_OUTPUT"]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
