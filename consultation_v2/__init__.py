"""Isolated consultation workflow drivers.

Consultation V2 intentionally keeps platform workflow logic separate.
Shared code in this package is limited to AT-SPI/YAML plumbing and result
data structures.
"""

from . import primitives
from .orchestrator import run_consultation
from .types import Choice, ConsultationRequest, ConsultationResult

__all__ = [
    'Choice',
    'ConsultationRequest',
    'ConsultationResult',
    'primitives',
    'run_consultation',
]
