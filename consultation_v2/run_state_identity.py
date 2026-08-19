from __future__ import annotations

import hashlib
import json
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
        legacy_scope: str = 'unscoped',
    ) -> None:
        self.request_id = request_id
        self.durable_run_id = durable_run_id
        self.mode = mode
        self.legacy_scope = legacy_scope
        self.record = dict(record)
        status = str(record.get('status') or 'unknown')
        super().__init__(
            f'legacy {legacy_scope} run-state has no trustworthy full-selection binding; '
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


def resolved_selection_profile(request: ConsultationRequest) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not has_selection_menus(request.platform):
        return ()
    resolved: dict[str, list[str]] = {}
    for step in build_selection_plan(request):
        menu = str(step.get('menu') or '').strip()
        if not menu:
            raise ValueError(f'{request.platform} selection step has no stable menu name')
        option = 'none' if step.get('skip') else str(step.get('option') or '').strip()
        if not option:
            raise ValueError(
                f'{request.platform} selection menu {menu!r} has no stable resolved option'
            )
        resolved.setdefault(menu, []).append(option)
    return tuple(
        (menu, tuple(sorted(options)))
        for menu, options in sorted(resolved.items())
    )


def selection_fingerprint(request: ConsultationRequest) -> str:
    profile = resolved_selection_profile(request)
    if not profile:
        return 'default'
    canonical = json.dumps(profile, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:32]


def durable_run_id(request: ConsultationRequest) -> str:
    return f'{request.request_id()}:selection:{selection_fingerprint(request)}'


def monitor_id(request: ConsultationRequest) -> str:
    return f'{request.platform}:{durable_run_id(request)}'


def durable_state_fields(request: ConsultationRequest) -> dict[str, Any]:
    profile = resolved_selection_profile(request)
    return {
        'base_request_id': request.request_id(),
        'durable_run_id': durable_run_id(request),
        'selection_fingerprint': selection_fingerprint(request),
        'selection_profile': [
            {'menu': menu, 'options': list(options)}
            for menu, options in profile
        ],
        'mode': resolved_mode(request),
    }


def read_durable_run_state(
    request: ConsultationRequest,
) -> dict[str, Any] | None:
    scoped_id = durable_run_id(request)
    scoped = primitives.read_run_state(scoped_id)
    if scoped is not None:
        return scoped
    legacy_mode_records = primitives.read_run_states_with_prefix(
        f'{request.request_id()}:mode:'
    )
    if legacy_mode_records:
        legacy_id = next(iter(legacy_mode_records))
        raise LegacyUnscopedRunState(
            request_id=legacy_id,
            durable_run_id=scoped_id,
            mode=resolved_mode(request),
            record=legacy_mode_records[legacy_id],
            legacy_scope='mode-scoped',
        )
    legacy_candidates = (('unscoped', request.request_id()),)
    for legacy_scope, legacy_id in legacy_candidates:
        legacy = primitives.read_run_state(legacy_id)
        if legacy is None:
            continue
        raise LegacyUnscopedRunState(
            request_id=legacy_id,
            durable_run_id=scoped_id,
            mode=resolved_mode(request),
            record=legacy,
            legacy_scope=legacy_scope,
        )
    return None


def assert_request_run_state_available(request: ConsultationRequest) -> str:
    record = read_durable_run_state(request)
    scoped_id = durable_run_id(request)
    if record is not None:
        primitives.assert_session_not_dead(scoped_id)
    return scoped_id
