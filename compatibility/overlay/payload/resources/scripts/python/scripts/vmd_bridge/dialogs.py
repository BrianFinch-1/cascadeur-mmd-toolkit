"""Select a dialog implementation without changing the modern release code."""
from importlib import import_module
import sys

from .qt_compat import legacy_host

_implementation = import_module(
    ".legacy_dialogs" if legacy_host() else "._dialogs_modern", __package__)
# Preserve shared module state (_live, message/confirmation records) for all
# callers, including those accessing private lifecycle helpers.
sys.modules[__name__] = _implementation
