"""Direct QML menu callbacks for hosts without the 2026.2 script server."""
from PySide6 import QtCore
from PySide6.QtQml import QQmlComponent, QQmlEngine

from . import _logging

_records = {}


def install(target, key, label, callback, anchor):
    context = QQmlEngine.contextForObject(target)
    if context is None:
        raise RuntimeError("Legacy menu has no QML context")
    record = _records.get(key)
    if record is not None and record["menu"] == target:
        _ensure(record)
        return True
    component = QQmlComponent(context.engine())
    component.setData(b'import QtQuick\nimport QtQuick.Controls\nMenuItem {}',
                      QtCore.QUrl("mmd_legacy_menu.qml"))
    if component.isError():
        raise RuntimeError("; ".join(e.toString() for e in component.errors()))
    record = {"menu": target, "key": key, "label": label, "callback": callback,
              "anchor": anchor, "component": component, "context": context,
              "item": None}

    def ensure():
        try:
            _ensure(record)
        except Exception:
            _logging.logger().exception("legacy menu refresh failed: %s", key)

    def destroyed(*_):
        if _records.get(key) is record:
            _records.pop(key, None)

    record.update(ensure=ensure, destroyed=destroyed)
    target.aboutToShow.connect(ensure)
    target.destroyed.connect(destroyed)
    _records[key] = record
    _ensure(record)
    return True


def _ensure(record):
    from shiboken6 import isValid
    item = record["item"]
    engine = record["context"].engine()
    js_menu = engine.newQObject(record["menu"])
    if item is None or not isValid(item):
        item = record["component"].create(record["context"])
        if item is None:
            raise RuntimeError("Unable to create legacy MenuItem")
        QQmlEngine.setObjectOwnership(item, QQmlEngine.CppOwnership)
        item.setParent(record["menu"])
        item.setObjectName(record["key"])
        item.setProperty("text", record["label"])

        def triggered():
            # Leave QML's triggered handler before starting a new dialog flow.
            QtCore.QTimer.singleShot(0, record["callback"])

        item.triggered.connect(triggered)
        record.update(item=item, triggered=triggered)
    # QML handles QQuickItem* values; no QtQuick Python binding is loaded.
    insert = engine.evaluate("""(function(menu, item, anchor) {
        for (var i = 0; i < menu.count; ++i)
            if (menu.itemAt(i) === item) return true;
        var index = menu.count;
        for (var j = 0; j < menu.count; ++j) {
            var other = menu.itemAt(j);
            if (other && other.objectName === anchor) { index = j + 1; break; }
        }
        menu.insertItem(index, item);
        for (var k = 0; k < menu.count; ++k)
            if (menu.itemAt(k) === item) return true;
        return false;
    })""")
    from PySide6.QtQml import QJSValue
    result = insert.call([js_menu, engine.newQObject(item), QJSValue(record["anchor"])])
    if result.isError() or not result.toBool():
        raise RuntimeError("Legacy menu insertion failed: " + result.toString())
    _logging.trace("legacy.menu_installed", action=record["key"])
