"""Isolated consultation workflow drivers.

Consultation V2 intentionally keeps platform workflow logic separate.
Shared code in this package is limited to AT-SPI/YAML plumbing and result
data structures.
"""

from .orchestrator import run_consultation
from .types import ConsultationRequest, ConsultationResult

__all__ = [
    'ConsultationRequest',
    'ConsultationResult',
    'run_consultation',
]
