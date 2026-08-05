"""Isolated consultation workflow drivers.

Consultation V2 intentionally keeps platform workflow logic separate.
Shared code in this package is limited to AT-SPI/YAML plumbing and result
data structures.
"""

from importlib import import_module
from typing import Any

__all__ = [
    'Choice',
    'ConsultationRequest',
    'ConsultationResult',
    'primitives',
    'run_consultation',
]

_EXPORTS = {
    'Choice': ('.types', 'Choice'),
    'ConsultationRequest': ('.types', 'ConsultationRequest'),
    'ConsultationResult': ('.types', 'ConsultationResult'),
    'primitives': ('.primitives', None),
    'run_consultation': ('.orchestrator', 'run_consultation'),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}') from exc
    module = import_module(module_name, __name__)
    value = module if attribute_name is None else getattr(module, attribute_name)
    globals()[name] = value
    return value
