from __future__ import annotations

import re
from typing import Any

from consultation_v2 import primitives
from consultation_v2.planner import build_selection_plan, has_selection_menus
from consultation_v2.types import ConsultationRequest


_MODE_COMPONENT = re.compile(r'^[a-z0-9][a-z0-9_-]*$')


class LegacyUnscopedRunState(RuntimeError):
    def __init__(
        self,
        *,
        request_id: str,
        durable_run_id: str,
        mode: str,
        record: dict[str, Any],
    ) -> None:
        self.request_id = request_id
        self.durable_run_id = durable_run_id
        self.mode = mode
        self.record = dict(record)
        status = str(record.get('status') or 'unknown')
        super().__init__(
            'legacy unscoped run-state has no trustworthy mode binding; '
            f'refusing browser action until TTL expiry: request_id={request_id!r}, '
            f'mode={mode!r}, status={status!r}'
        )


def resolved_mode(request: ConsultationRequest) -> str:
    if not has_selection_menus(request.platform):
        return 'default'
    mode_steps = [
        step
        for step in build_selection_plan(request)
        if str(step.get('menu') or '') == 'mode'
    ]
    if not mode_steps:
        return 'default'
    step = mode_steps[-1]
    value = 'none' if step.get('skip') else step.get('option', step.get('value'))
    mode = str(value or '').strip().lower()
    if not _MODE_COMPONENT.fullmatch(mode):
        raise ValueError(
            f'{request.platform} resolved mode is not a stable key component: {mode!r}'
        )
    return mode


def durable_run_id(request: ConsultationRequest) -> str:
    return f'{request.request_id()}:mode:{resolved_mode(request)}'


def monitor_id(request: ConsultationRequest) -> str:
    return f'{request.platform}:{durable_run_id(request)}'


def durable_state_fields(request: ConsultationRequest) -> dict[str, str]:
    return {
        'base_request_id': request.request_id(),
        'durable_run_id': durable_run_id(request),
        'mode': resolved_mode(request),
    }


def read_durable_run_state(
    request: ConsultationRequest,
) -> dict[str, Any] | None:
    scoped_id = durable_run_id(request)
    scoped = primitives.read_run_state(scoped_id)
    if scoped is not None:
        return scoped
    legacy_id = request.request_id()
    legacy = primitives.read_run_state(legacy_id)
    if legacy is None:
        return None
    raise LegacyUnscopedRunState(
        request_id=legacy_id,
        durable_run_id=scoped_id,
        mode=resolved_mode(request),
        record=legacy,
    )


def assert_request_run_state_available(request: ConsultationRequest) -> str:
    record = read_durable_run_state(request)
    scoped_id = durable_run_id(request)
    if record is not None:
        primitives.assert_session_not_dead(scoped_id)
    return scoped_id
