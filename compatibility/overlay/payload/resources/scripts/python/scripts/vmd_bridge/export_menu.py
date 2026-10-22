"""Export action injection isolated from the stable Import menu installer."""
from PySide6 import QtCore
from . import menu, _logging, qt_compat

KEY = 'File.Export.Export VMD'
_retry_pending = False


def install(retries=180):
    global _retry_pending
    main = menu.find_main_window()
    target = None
    if main is not None:
        for obj in main.findChildren(QtCore.QObject):
            try:
                if not obj.metaObject().className().startswith('CustomMenu_QMLTYPE_'):
                    continue
                actions = menu._direct_action_strings(obj.property('subNode'))
                if str(obj.property('titleId')) == 'MenuBar.Export' or any(a.startswith('File.Export.') for a in actions):
                    target = obj
                    break
            except RuntimeError:
                continue
    if target is not None and qt_compat.legacy_host():
        from . import legacy_menu, _on_export_vmd
        return legacy_menu.install(target, KEY, 'Export VMD', _on_export_vmd, 'File.Export.Fbx/Dae')
    if target is not None:
        nodes = menu._to_variant(target.property('subNode'))
        if isinstance(nodes, (list, tuple)) and KEY not in nodes:
            ordered = list(nodes)
            insert_at = None
            for index, node in enumerate(ordered):
                text = str(node)
                if 'Fbx' in text and 'Dae' in text:
                    insert_at = index + 1
                    break
            if insert_at is None:
                insert_at = len(ordered)
            ordered.insert(insert_at, KEY)
            target.setProperty('subNode', ordered)
            QtCore.QMetaObject.invokeMethod(target, 'updateItems', QtCore.Qt.DirectConnection)
        elif isinstance(nodes, (list, tuple)):
            # Correct an older installation that placed the action elsewhere.
            # Rebuilding the list is idempotent and prevents duplicate entries.
            ordered = [node for node in nodes if str(node) != KEY]
            insert_at = None
            for index, node in enumerate(ordered):
                text = str(node)
                if 'Fbx' in text and 'Dae' in text:
                    insert_at = index + 1
                    break
            if insert_at is None:
                insert_at = len(ordered)
            ordered.insert(insert_at, KEY)
            target.setProperty('subNode', ordered)
            QtCore.QMetaObject.invokeMethod(target, 'updateItems', QtCore.Qt.DirectConnection)
        for child in target.findChildren(QtCore.QObject):
            if child.objectName() == KEY:
                child.setProperty('text', 'Export VMD')
                _logging.trace('export.menu_installed')
                return True
    if retries > 0 and not _retry_pending:
        _retry_pending = True
        def retry():
            global _retry_pending
            _retry_pending = False
            install(retries-1)
        QtCore.QTimer.singleShot(1000, retry)
    elif retries <= 0:
        _logging.logger().warning('Export VMD menu unavailable: native action/menu not ready')
    return False
