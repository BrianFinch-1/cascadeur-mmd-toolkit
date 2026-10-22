# -*- coding: utf-8 -*-
"""Inject the VMD action into Cascadeur's live Import CustomMenu.

The Import menu is a QML object. Its QObject child tree is not a stable way
to identify it; Cascadeur 2026.2 exposes the action keys through the
``subNode`` QML property instead. This mirrors the host-validated
``tools/_inject_create4.py`` recipe.
"""
from PySide6 import QtCore
from . import qt_compat

from . import _logging

# ActionManager's untranslated fallback is the final key segment.  Using the
# desired label here keeps the native binding stable across lazy menu rebuilds
# and locales; spaces are already used by stock Cascadeur action keys.
ACTION_KEY = "File.Import.Import VMD"
DISPLAY_NAME = "Import VMD"
IMPORT_TITLE_ID = "MenuBar.Import"
IMPORT_ANCHORS = ("File.Import.Fbx/Dae", "File.Import.Sf3 animation...")
ORDER_ANCHOR = "File.Import.Fbx/Dae"
_retry_pending = False


def _to_variant(value):
    if value is not None and hasattr(value, "toVariant"):
        try:
            return value.toVariant()
        except Exception:
            return value
    return value


def _contains_action(value, predicate):
    """Search a QJSValue/QVariant tree without depending on its string form."""
    value = _to_variant(value)
    if isinstance(value, dict):
        return any(_contains_action(item, predicate)
                   for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_action(item, predicate) for item in value)
    return predicate(str(value)) if value is not None else False


def _direct_action_strings(value):
    """Return only direct string entries, excluding nested submenu dicts."""
    value = _to_variant(value)
    if not isinstance(value, (list, tuple, set)):
        return []
    actions = []
    for item in value:
        item = _to_variant(item)
        if isinstance(item, str):
            actions.append(item)
    return actions


def find_main_window():
    for window in qt_compat.top_level_windows():
        if "MainWindow" in window.metaObject().className():
            return window
    return None


def find_import_menu(main):
    """Return the exact Import menu, never File root or Import USD."""
    fallbacks = []
    for candidate in main.findChildren(QtCore.QObject):
        class_name = candidate.metaObject().className()
        # CustomMenuItem also contains the substring "CustomMenu". Avoid
        # touching thousands of transient item wrappers while QML is building.
        if not class_name.startswith("CustomMenu_QMLTYPE_"):
            continue
        try:
            title_id = str(_to_variant(candidate.property("titleId")) or "")
            if title_id == IMPORT_TITLE_ID:
                return candidate
            actions = _direct_action_strings(candidate.property("subNode"))
            anchor_score = sum(anchor in actions for anchor in IMPORT_ANCHORS)
            import_score = sum(action.startswith("File.Import.")
                               for action in actions)
            if anchor_score or import_score:
                fallbacks.append((anchor_score, import_score, candidate))
        except RuntimeError:
            # A QML object can be destroyed while findChildren's snapshot is
            # traversed during startup. Treat it as a transient candidate.
            continue
    if not fallbacks:
        return None
    return max(fallbacks, key=lambda item: (item[0], item[1]))[2]


def _find_action_item(menu):
    """Find the action only when it belongs to the selected Import menu."""
    for child in menu.findChildren(QtCore.QObject):
        if (child.objectName() == ACTION_KEY and
                "CustomMenuItem" in child.metaObject().className()):
            return child
    return None


def _ensure_display_name(item, log):
    current = str(_to_variant(item.property("text")) or "")
    if current == DISPLAY_NAME:
        return
    # QTranslator is the primary path. This writable QML property is a final
    # visual fallback if a host build uses a different translation context.
    if not item.setProperty("text", DISPLAY_NAME):
        log.warning("menu item text fallback failed: current=%r", current)
    else:
        log.info("menu item text fallback applied: %r -> %r",
                 current, DISPLAY_NAME)


def _install_in_order(menu, log):
    """Persist the action immediately below File.Import.Fbx/Dae.

    Mutating ``subNode`` is preferable to moving a transient MenuItem: the
    host's own onSubNodeChanged handler rebuilds the menu and preserves order
    across lazy menu materialization.
    """
    nodes = _to_variant(menu.property("subNode"))
    if not isinstance(nodes, (list, tuple)):
        log.warning("Import subNode is not convertible; ordered insert unavailable")
        return False
    ordered = [item for item in nodes if item != ACTION_KEY]
    try:
        anchor_index = ordered.index(ORDER_ANCHOR)
    except ValueError:
        log.warning("ordered insert anchor missing: %s", ORDER_ANCHOR)
        return False
    ordered.insert(anchor_index + 1, ACTION_KEY)
    if not menu.setProperty("subNode", ordered):
        log.warning("setting ordered Import subNode failed")
        return False
    QtCore.QMetaObject.invokeMethod(menu, "updateItems",
                                    QtCore.Qt.DirectConnection)
    log.info("menu action placed after %s via subNode rebuild", ORDER_ANCHOR)
    return True


def _schedule_retry(retries_left, retry_delay_ms):
    global _retry_pending
    if retries_left <= 0 or _retry_pending:
        return False
    _retry_pending = True

    def retry():
        global _retry_pending
        _retry_pending = False
        install(retries_left=retries_left - 1,
                retry_delay_ms=retry_delay_ms)

    QtCore.QTimer.singleShot(retry_delay_ms, retry)
    return True


def install(on_triggered=None, retries_left=180, retry_delay_ms=1000):
    """Install the menu item, returning True once present.

    ``on_triggered`` remains accepted for compatibility with the former
    Python QAction route. Clicks now travel through ActionManager to the DLL
    callback, so the value is intentionally unused.
    """
    del on_triggered
    log = _logging.logger()
    main = find_main_window()
    if main is None:
        if not _schedule_retry(retries_left, retry_delay_ms):
            log.error("menu injection failed: MainWindow not found")
        return False

    menu = find_import_menu(main)
    if menu is None:
        if not _schedule_retry(retries_left, retry_delay_ms):
            log.error("menu injection failed: Import CustomMenu not found")
        return False

    if qt_compat.legacy_host():
        from . import legacy_menu, _on_import_vmd
        return legacy_menu.install(menu, ACTION_KEY, DISPLAY_NAME, _on_import_vmd, ORDER_ANCHOR)

    ordered = _install_in_order(menu, log)
    existing = _find_action_item(menu)
    if existing is not None:
        _ensure_display_name(existing, log)
        log.info("menu item already present: %s", ACTION_KEY)
        return True

    # Older host builds may not accept a Python list for a QML var property.
    # Fall back to create(); this preserves functionality, and the verification
    # log makes any ordering regression explicit.
    result = ordered or QtCore.QMetaObject.invokeMethod(
            menu,
            "create",
            QtCore.Qt.DirectConnection,
            QtCore.Q_ARG("QVariant", ACTION_KEY),
        )
    if not result:
        if not _schedule_retry(retries_left, retry_delay_ms):
            log.error("CustomMenu.create('%s') returned false", ACTION_KEY)
        return False

    # invokeMethod(True) only means the QML function ran. create() itself has
    # a silent ActionManager.contains() gate, so verify materialization before
    # declaring success. This also closes the scene-before-action race.
    item = _find_action_item(menu)
    if item is not None:
        _ensure_display_name(item, log)
        log.info("menu item injected: %s via %s titleId=%s", ACTION_KEY,
                 menu.metaObject().className(),
                 str(_to_variant(menu.property("titleId")) or ""))
        return True
    if not _schedule_retry(retries_left, retry_delay_ms):
        log.error("CustomMenu.create ran but action gate never materialized %s",
                  ACTION_KEY)
    return False
