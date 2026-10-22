# -*- coding: utf-8 -*-
"""Asynchronous dialogs created inside Cascadeur's existing QML engine."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore
from . import qt_compat
from PySide6.QtQml import QQmlComponent, QQmlEngine

from . import _logging
from .product_info import window_title


_live: list[dict[str, Any]] = []
_message_record: dict[str, Any] | None = None


def _variant(value):
    """Convert Qt/QML QVariant and QJSValue containers at the boundary."""
    converter = getattr(value, "toVariant", None)
    if callable(converter):
        try:
            converted = converter()
        except Exception:
            converted = value
        if converted is not value:
            return converted
    return value


def _indices(value):
    value = _variant(value)
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = [value]
    result = []
    for item in raw:
        item = _variant(item)
        if isinstance(item, bool):
            raise ValueError("model selection contains a boolean")
        if isinstance(item, int):
            result.append(item)
            continue
        # QML numeric values normally arrive as int, but some Cascadeur Qt
        # builds expose QVariant numbers as float-valued Python objects.
        if isinstance(item, float) and item.is_integer():
            result.append(int(item))
            continue
        raise ValueError("model selection contains a non-numeric value: %r" % (item,))
    return result


def _disconnect(record):
    for signal, callback in record.get("connections", ()):
        try:
            signal.disconnect(callback)
        except (RuntimeError, TypeError):
            pass
    record["connections"] = []


def _queue_callback(record, event, callback, *args):
    """Run a dialog callback on the next UI turn, then release its QML object."""
    if record.get("callback_scheduled"):
        _logging.trace(event + ".duplicate", dialog=record.get("name"))
        return
    record["callback_scheduled"] = True
    _disconnect(record)
    obj = record.get("object")
    if obj is not None:
        try:
            if obj.inherits("QWindow"):
                # Hide while still modal: Qt removes it from the modal stack.
                # Changing modality first leaves the host's input blocked in
                # Qt 6.5 even when modalWindow() subsequently returns None.
                obj.hide()
                qt_compat.set_modality(obj, QtCore.Qt.WindowModality.NonModal)
        except RuntimeError:
            pass
    _logging.trace(event + ".scheduled", dialog=record.get("name"))

    def run():
        _logging.trace(event + ".begin", dialog=record.get("name"))
        try:
            callback(*args)
        except Exception:
            _logging.logger().exception("dialog callback failed: %s", event)
            _logging.trace(event + ".exception", dialog=record.get("name"))
            cancel = record.get("on_cancel")
            if cancel is not None and callback is not cancel:
                try:
                    cancel()
                except Exception:
                    _logging.logger().exception("dialog cancel callback failed")
        finally:
            _release(record)
            _logging.trace(event + ".end", dialog=record.get("name"))

    QtCore.QTimer.singleShot(0, run)


def _main_window():
    # The host may expose only className=QQuickWindow. topLevelWindows()[0]
    # can be the progress window that has just been hidden/deleteLater'd.
    # Never parent a report (or the next chooser) to another plugin dialog.
    candidates = []
    plugin_objects = [r.get("object") for r in _live]
    for window in qt_compat.top_level_windows():
        try:
            if (window in plugin_objects or window.property("_vmdOwnedWindow")
                    or qt_compat.object_property(window, "transientParent") is not None):
                continue
            if not window.inherits("QQuickWindow"):
                continue
            context = QQmlEngine.contextForObject(window)
            if context is None or context.engine() is None:
                continue
            named_main = "mainwindow" in (
                window.metaObject().className() + window.objectName()).lower()
            candidates.append(((named_main, bool(window.property("visible")),
                                window.property("width")*window.property("height")), window))
        except RuntimeError:
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _create(qml: str, name: str, *, modality=None):
    parent = _main_window()
    if parent is None:
        raise RuntimeError("Cascadeur MainWindow is not available")
    context = QQmlEngine.contextForObject(parent)
    if context is None or context.engine() is None:
        raise RuntimeError("Cascadeur QML context is not available")
    component = QQmlComponent(context.engine())
    component.setData(qml.encode("utf-8"), QtCore.QUrl(name))
    if component.isError():
        raise RuntimeError("QML component error: " + "; ".join(
            error.toString() for error in component.errors()))
    obj = component.create(context)
    if obj is None:
        raise RuntimeError("QML object creation failed: " + "; ".join(
            error.toString() for error in component.errors()))
    # Objects returned by QQmlComponent.create() default to JavaScript
    # ownership. Python references do not prevent QML GC from deleting a
    # non-window wrapper while its native dialog is opening.
    QQmlEngine.setObjectOwnership(obj, QQmlEngine.CppOwnership)
    # A QML Window must remain a top-level QWindow and use transientParent.
    # Making it an ordinary QObject child of MainWindow leaves it visible=true
    # but absent from the native top-level window list, which produces an
    # unresponsive application-modal overlay. Popup dialogs such as FileDialog
    # are not QWindows and follow MainWindow.qml's QObject-parent pattern.
    if obj.inherits("QWindow"):
        obj.setProperty("_vmdOwnedWindow", True)
        qt_compat.set_transient_parent(obj, parent)
        # Keep the chooser as a normal transient dialog. WindowModal avoids a
        # global blocker while preserving Cascadeur's native window placement.
        try:
            qt_compat.set_modality(obj, QtCore.Qt.WindowModality.WindowModal if modality is None else modality)
        except (RuntimeError, AttributeError, TypeError) as exc:
            _logging.trace('dialog.modality_failed', name=name, error=str(exc))
    elif obj.inherits("QQuickItem") and parent.inherits("QQuickWindow"):
        context.engine().newQObject(obj).setProperty("parent", context.engine().newQObject(parent).property("contentItem"))
    else:
        obj.setParent(parent)
    record = {"component": component, "object": obj, "name": name,
              "connections": []}
    _live.append(record)
    return record


def _release(record: dict[str, Any]):
    if record.get("released"):
        return
    record["released"] = True
    if record in _live:
        _live.remove(record)
    timer = record.get("timer")
    if timer is not None:
        try:
            timer.stop()
            timer.deleteLater()
        except RuntimeError:
            pass
    _disconnect(record)
    obj = record.get("object")
    if obj is not None and record.get("delete_object", True):
        try:
            if obj.inherits("QWindow"):
                # Preserve the order used by _queue_callback; tested with
                # actual host Qt libraries and main-window mouse events.
                obj.hide()
                qt_compat.set_modality(obj, QtCore.Qt.WindowModality.NonModal)
            obj.deleteLater()
        except RuntimeError:
            pass


def _invoke(obj, method: str):
    if not QtCore.QMetaObject.invokeMethod(
            obj, method, QtCore.Qt.QueuedConnection):
        raise RuntimeError("QML method %s() is unavailable" % method)


def choose_model(models: list[dict[str, Any]],
                 on_selected: Callable[[Any], None],
                 on_cancel: Callable[[], None], *,
                 title: str = 'Import VMD / 导入 VMD',
                 multiple: bool = False) -> None:
    """A bounded, scrollable chooser; filtering never changes source identity."""
    from .model_picker import picker_entries
    qml = (Path(__file__).parent / 'data/model_picker.qml').read_text(encoding='utf-8')
    record = _create(qml, "vmd_model_picker.qml")
    _logging.trace('model_dialog.created', count=len(models))
    obj = record["object"]
    record["on_cancel"] = on_cancel

    def destroyed(*_args):
        _logging.trace('model_dialog.destroyed', released=record.get('released'),
                       decision=record.get('decision'))
        if not record.get('released') and not record.get('decision'):
            record['decision'] = True
            _queue_callback(record, 'model_dialog.destroyed_cancel', on_cancel)

    try:
        obj.destroyed.connect(destroyed)
        record["connections"].append((obj.destroyed, destroyed))
        obj.setProperty("title", window_title(title))
        obj.setProperty("multiSelect", bool(multiple))
        obj.setProperty("modelEntries", picker_entries(models))
    except Exception:
        _release(record)
        raise

    def selected(value):
        # QML emits a scalar in single-select mode and an array in multi-select
        # mode. Normalize at the boundary so import/export flows can share the
        # same dialog without changing the legacy single-model callback.
        if record.get('decision'):
            return
        _logging.trace('model_dialog.signal_received', value_type=type(value).__name__,
                       multiple=bool(multiple))
        try:
            indices = _indices(value)
            if not indices:
                raise ValueError('empty model selection')
            _logging.trace('model_dialog.signal_selected', indices=indices,
                           multiple=bool(multiple))
            record['decision'] = True
            result = indices if multiple else indices[0]
            _queue_callback(record, 'model_dialog.selected_callback', on_selected, result)
        except Exception as exc:
            record['decision'] = True
            _logging.trace('model_dialog.signal_exception', error=str(exc))
            _queue_callback(record, 'model_dialog.selection_error', on_cancel)

    def canceled():
        if record.get('decision'):
            return
        record['decision'] = True
        _logging.trace('model_dialog.signal_cancel')
        _queue_callback(record, 'model_dialog.cancel_callback', on_cancel)

    record.update({"selected": selected, "canceled": canceled})
    try:
        obj.modelSelected.connect(selected)
        record["connections"].append((obj.modelSelected, selected))
        obj.selectionCanceled.connect(canceled)
        record["connections"].append((obj.selectionCanceled, canceled))
        _invoke(obj, "show")
        _invoke(obj, "requestActivate")
    except Exception:
        _release(record)
        raise
    return record


def choose_export_strategy(has_ik: bool,
                           on_selected: Callable[[str], None],
                           on_cancel: Callable[[], None]) -> None:
    """Choose the source track policy without exposing host internals."""
    qml = (Path(__file__).parent / 'data/export_strategy.qml').read_text(encoding='utf-8')
    record = _create(qml, "vmd_export_strategy.qml")
    obj = record["object"]
    record["on_cancel"] = on_cancel

    def destroyed(*_args):
        _logging.trace('export_strategy.destroyed', released=record.get('released'),
                       decision=record.get('decision'))
        if not record.get('released') and not record.get('decision'):
            record['decision'] = True
            _queue_callback(record, 'export_strategy.destroyed_cancel', on_cancel)

    try:
        obj.destroyed.connect(destroyed)
        record["connections"].append((obj.destroyed, destroyed))
        obj.setProperty("hasIk", bool(has_ik))
    except Exception:
        _release(record)
        raise

    def selected(strategy):
        if record.get('decision'):
            return
        record['decision'] = True
        value = str(strategy)
        _logging.trace('export_strategy.selected', strategy=value, has_ik=bool(has_ik))
        _queue_callback(record, 'export_strategy.selected_callback', on_selected, value)

    def canceled():
        if record.get('decision'):
            return
        record['decision'] = True
        _logging.trace('export_strategy.canceled')
        _queue_callback(record, 'export_strategy.cancel_callback', on_cancel)

    record.update({"selected": selected, "canceled": canceled})
    try:
        obj.strategySelected.connect(selected)
        record["connections"].append((obj.strategySelected, selected))
        obj.selectionCanceled.connect(canceled)
        record["connections"].append((obj.selectionCanceled, canceled))
        _invoke(obj, "show")
        _invoke(obj, "requestActivate")
    except Exception:
        _release(record)
        raise
    return record


def _quick_file_dialogs():
    """Yield host-owned Qt Quick file dialogs without taking ownership."""
    roots = list(qt_compat.top_level_windows())
    app = QtCore.QCoreApplication.instance()
    if app is not None:
        roots.append(app)
    seen = set()
    for root in roots:
        try:
            children = root.findChildren(QtCore.QObject)
        except RuntimeError:
            continue
        for child in children:
            try:
                class_name = child.metaObject().className()
            except RuntimeError:
                continue
            if "FileDialog" not in class_name or id(child) in seen:
                continue
            seen.add(id(child))
            yield child


def pick_vmd_file(on_selected: Callable[[str], None],
                  on_cancel: Callable[[], None],
                  initial_dir: str | None = None) -> None:
    """Open VMD selection through Cascadeur's host-owned dialog manager.

    Cascadeur is a Qt Quick application (QGuiApplication/QQuickWindow), not a
    QWidget application.  Constructing QFileDialog therefore aborts the host
    before Python can catch an exception.  The public FileDialogManager is the
    same path used by Cascadeur's bundled import commands and owns its window,
    parent, native backend, and lifetime.
    """
    import csc

    qt_app = QtCore.QCoreApplication.instance()
    if qt_app is None:
        raise RuntimeError("Cascadeur Qt application is not available")
    if QtCore.QThread.currentThread() != qt_app.thread():
        raise RuntimeError("VMD file picker must be opened on Cascadeur's UI thread")

    application = csc.app.get_application()
    if application is None:
        raise RuntimeError("Cascadeur application is not available")
    manager = application.get_file_dialog_manager()
    if manager is None:
        raise RuntimeError("Cascadeur FileDialogManager is not available")

    folder = Path(initial_dir) if initial_dir else Path.home()
    if folder.is_file():
        folder = folder.parent
    folder = folder.resolve()
    already_visible = []
    for dialog in _quick_file_dialogs():
        try:
            if dialog.property('visible'):
                already_visible.append(dialog)
        except RuntimeError:
            pass
    record = {
        "object": None,
        "delete_object": False,
        "released": False,
        "manager": manager,
        "connections": [],
        "dialog": None,
        "discovery_attempts": 0,
        "already_visible": already_visible,
    }
    _live.append(record)
    _logging.trace("vmd_dialog.created", initial_dir=str(folder),
                   dialog_type="CascadeurFileDialogManager")

    def finish_selected(value):
        if record.get("released"):
            return
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        path = str(value or "")
        if not path:
            finish_cancel()
            return
        _logging.trace("vmd_dialog.signal_accepted", value=path,
                       dialog_type="CascadeurFileDialogManager")
        _release(record)
        QtCore.QTimer.singleShot(0, lambda: on_selected(path))

    def finish_cancel():
        if record.get("released"):
            return
        _logging.trace("vmd_dialog.signal_rejected",
                       dialog_type="CascadeurFileDialogManager")
        _release(record)
        QtCore.QTimer.singleShot(0, on_cancel)

    def dialog_accepted():
        # FileDialogManager invokes finish_selected with the selected path.
        # This trace distinguishes UI acceptance from its Python callback.
        _logging.trace("vmd_dialog.host_signal_accepted")
        record['accepted'] = True

    def dialog_destroyed(*_args):
        if not record.get('accepted'):
            finish_cancel()

    def attach_lifecycle():
        if record.get("released") or record.get("dialog") is not None:
            return
        record["discovery_attempts"] += 1
        for dialog in _quick_file_dialogs():
            try:
                visible = bool(dialog.property("visible"))
            except RuntimeError:
                continue
            if not visible or dialog in record['already_visible']:
                continue
            rejected_signal = getattr(dialog, "rejected", None)
            if rejected_signal is None:
                continue
            rejected_signal.connect(finish_cancel)
            record["connections"].append((rejected_signal, finish_cancel))
            dialog.destroyed.connect(dialog_destroyed)
            record['connections'].append((dialog.destroyed, dialog_destroyed))
            accepted_signal = getattr(dialog, "accepted", None)
            if accepted_signal is not None:
                accepted_signal.connect(dialog_accepted)
                record["connections"].append((accepted_signal, dialog_accepted))
            record["dialog"] = dialog
            timer = record.get("timer")
            if timer is not None:
                timer.stop()
            _logging.trace("vmd_dialog.visible",
                           qt_class=dialog.metaObject().className())
            return
        if record["discovery_attempts"] >= 100:
            timer = record.get("timer")
            if timer is not None:
                timer.stop()
            _logging.trace("vmd_dialog.lifecycle_unobserved")

    # Keep exactly one bounded discovery timer alive until the host-owned QML
    # object materializes.  It is stopped as soon as the rejected signal is
    # attached and never pumps a nested event loop.
    timer = QtCore.QTimer()
    timer.setInterval(50)
    timer.setSingleShot(False)
    timer.timeout.connect(attach_lifecycle)
    record["timer"] = timer
    record["manager_callback"] = finish_selected

    _logging.trace("vmd_dialog.open_requested",
                   dialog_type="CascadeurFileDialogManager")
    try:
        manager.show_open_file_dialog(
            window_title("Select VMD motion / 选择 VMD 动作"),
            folder.as_posix(),
            ["*.vmd"],
            finish_selected,
        )
    except Exception:
        _release(record)
        raise
    _logging.trace("vmd_dialog.open_returned",
                   dialog_type="CascadeurFileDialogManager")
    attach_lifecycle()
    if record.get("dialog") is None and not record.get("released"):
        timer.start()
    return

    # Legacy QML implementation retained below only as unreachable reference.
    qml = r'''
import QtQuick
import QtQuick.Window
import QtQuick.Dialogs

Window {
    id: root
    visible: true
    width: 1
    height: 1
    opacity: 0
    flags: Qt.Tool
    modality: Qt.NonModal
    property url initialFolder
    signal fileAccepted(string path)
    signal fileRejected()
    FileDialog {
        id: dialog
        title: "cascadeur MMD toolkit — Select VMD / 选择 VMD"
        modality: Qt.NonModal
        fileMode: FileDialog.OpenFile
        nameFilters: ["VMD Motion (*.vmd)", "All Files (*)"]
        onAccepted: root.fileAccepted(selectedFile.toString())
        onRejected: root.fileRejected()
    }
    function open() {
        dialog.currentFolder = root.initialFolder
        dialog.open()
    }
    function reject() {
        dialog.close()
        root.fileRejected()
    }
}
'''
    record = _create(qml, "vmd_file_picker.qml")
    _logging.trace('vmd_dialog.created', initial_dir=initial_dir)
    obj = record["object"]
    folder = Path(initial_dir) if initial_dir else Path.home()
    if folder.is_file():
        folder = folder.parent
    obj.setProperty("initialFolder", QtCore.QUrl.fromLocalFile(str(folder)))

    def accepted(value):
        _logging.trace('vmd_dialog.signal_accepted', value=str(value))
        url = QtCore.QUrl(str(value))
        path = url.toLocalFile() if url.isLocalFile() else str(value)
        _release(record)
        QtCore.QTimer.singleShot(0, lambda: on_selected(path))

    def rejected():
        _logging.trace('vmd_dialog.signal_rejected')
        _release(record)
        QtCore.QTimer.singleShot(0, on_cancel)

    record.update({"accepted": accepted, "rejected": rejected})
    obj.fileAccepted.connect(accepted)
    obj.fileRejected.connect(rejected)
    _logging.trace('vmd_dialog.open_requested')
    _invoke(obj, "open")


def show_message(title: str, text: str,
                 on_close: Callable[[], None] | None = None):
    """V1.1 Qt Quick Window notification, modeless for its entire lifetime."""
    global _message_record
    if _message_record and not _message_record.get("released"):
        try:
            obj = _message_record["object"]
            obj.setProperty("dialogTitle", window_title(str(title)))
            obj.setProperty("dialogText", str(text))
            if on_close:
                _message_record.setdefault("close_callbacks", []).append(on_close)
            obj.show()
            obj.requestActivate()
            return True
        except RuntimeError:
            _release(_message_record)
            _message_record = None
    qml = r'''
import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
Window {
    id: root
    objectName: "vmdMessageWindow"
    visible: false
    width: 640; height: 360
    minimumWidth: 420; minimumHeight: 240
    color: "#292929"
    flags: Qt.Dialog
    modality: Qt.NonModal
    property string dialogTitle: ""
    property string dialogText: ""
    property bool decisionMade: false
    title: dialogTitle
    signal dismissed()
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            TextArea {
                text: root.dialogText
                readOnly: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                color: "#eeeeee"
                background: Item {}
                selectByMouse: true
            }
        }
        Button {
            objectName: "vmdMessageOk"
            text: "OK / 确定"
            Layout.alignment: Qt.AlignRight
            onClicked: root.close()
        }
    }
    onClosing: function(event) {
        event.accepted = true
        if (!decisionMade) {
            decisionMade = true
            dismissed()
        }
    }
}
'''
    record = None
    try:
        record = _create(qml, "vmd_message.qml",
                         modality=QtCore.Qt.WindowModality.NonModal)
        _message_record = record
        obj = record["object"]
        record["close_callbacks"] = [on_close] if on_close else []
        obj.setProperty("dialogTitle", window_title(str(title)))
        obj.setProperty("dialogText", str(text))

        def dismissed():
            global _message_record
            if record.get("dismissal_pending"):
                return
            record["dismissal_pending"] = True
            if _message_record is record:
                _message_record = None
            _logging.trace("message.dismissed", dialog=record["name"])
            def release_and_callback():
                _release(record)
                for callback in record.pop("close_callbacks", []):
                    try:
                        callback()
                    except Exception:
                        _logging.logger().exception("message completion callback failed")
            QtCore.QTimer.singleShot(0, release_and_callback)

        obj.dismissed.connect(dismissed)
        record["connections"].append((obj.dismissed, dismissed))
        # A queued show can arrive after release/hide and resurrect a modal
        # surface. We are already on the UI thread; show synchronously.
        obj.show()
        obj.requestActivate()
        parent = qt_compat.object_property(obj, "transientParent")
        _logging.trace("message.shown", window_type=obj.metaObject().className(),
                       modality=str(obj.property("modality")), visible=bool(obj.property("visible")),
                       parent_title=parent.property("title") if parent else None)
        return True
    except Exception:
        _logging.logger().exception("Qt Quick message failed")
        if _message_record is record:
            _message_record = None
        if record:
            _release(record)
        _logging.trace("message.failed", title=str(title))
        print("=== %s ===\n%s" % (title, text))
        if on_close:
            QtCore.QTimer.singleShot(0, on_close)
        return False


_confirm_record: dict[str, Any] | None = None


def confirm(title: str, text: str,
            on_yes: Callable[[], None],
            on_no: Callable[[], None]) -> bool:
    """Bilingual two-button confirmation window.

    Same lifecycle rules as the other plugin windows: one live instance,
    decision is one-shot, every close path (button, title bar, destroy)
    releases the record and runs exactly one callback on the next UI turn.
    Returns False when another confirmation is pending or creation fails;
    the new caller's on_no is queued without replacing the pending action.
    """
    global _confirm_record
    if _confirm_record and not _confirm_record.get("released"):
        _logging.trace('confirm.rejected_pending', title=str(title))
        QtCore.QTimer.singleShot(0, on_no)
        return False
    qml = r'''
import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
Window {
    id: root
    objectName: "vmdConfirmWindow"
    visible: false
    width: 600; height: 320
    minimumWidth: 420; minimumHeight: 220
    color: "#292929"
    flags: Qt.Dialog
    modality: Qt.NonModal
    property string dialogTitle: ""
    property string dialogText: ""
    property bool decisionMade: false
    title: dialogTitle
    signal confirmed()
    signal declined()
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            TextArea {
                text: root.dialogText
                readOnly: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                color: "#eeeeee"
                background: Item {}
                selectByMouse: true
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: 12
            Button {
                objectName: "vmdConfirmYes"
                text: "Yes / 执行"
                onClicked: {
                    if (root.decisionMade) return
                    root.decisionMade = true
                    root.confirmed()
                    root.close()
                }
            }
            Button {
                objectName: "vmdConfirmNo"
                text: "Cancel / 取消"
                onClicked: {
                    if (root.decisionMade) return
                    root.decisionMade = true
                    root.declined()
                    root.close()
                }
            }
        }
    }
    onClosing: function(event) {
        event.accepted = true
        if (!decisionMade) {
            decisionMade = true
            declined()
        }
    }
}
'''
    record = None
    try:
        record = _create(qml, "vmd_confirm.qml",
                         modality=QtCore.Qt.WindowModality.NonModal)
        _confirm_record = record
        record["on_cancel"] = on_no
        obj = record["object"]
        obj.setProperty("dialogTitle", window_title(str(title)))
        obj.setProperty("dialogText", str(text))

        def decided(event_name, callback):
            if record.get("decision"):
                return
            record["decision"] = True
            _logging.trace(event_name, dialog=record["name"])
            _queue_callback(record, event_name + ".callback", callback)

        def confirmed():
            decided("confirm.yes", on_yes)

        def declined():
            decided("confirm.no", on_no)

        def destroyed(*_args):
            _logging.trace('confirm.destroyed', released=record.get('released'),
                           decision=record.get('decision'))
            if not record.get('released') and not record.get('decision'):
                record['decision'] = True
                _queue_callback(record, 'confirm.destroyed_no', on_no)

        obj.confirmed.connect(confirmed)
        record["connections"].append((obj.confirmed, confirmed))
        obj.declined.connect(declined)
        record["connections"].append((obj.declined, declined))
        obj.destroyed.connect(destroyed)
        record["connections"].append((obj.destroyed, destroyed))
        obj.show()
        obj.requestActivate()
        _logging.trace("confirm.shown",
                       window_type=obj.metaObject().className(),
                       visible=bool(obj.property("visible")))
        return True
    except Exception:
        _logging.logger().exception("Qt Quick confirm failed")
        if _confirm_record is record:
            _confirm_record = None
        if record:
            _release(record)
        print("=== %s (confirm unavailable; treating as No) ===\n%s" % (title, text))
        QtCore.QTimer.singleShot(0, on_no)
        return False
