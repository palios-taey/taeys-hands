from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from consultation_v2.native_dialog_snapshot import build_native_dialog_snapshot
from consultation_v2.platforms import routing as platform_routing
from consultation_v2.snapshot import (
    build_app_root_snapshot,
    build_menu_snapshot,
    build_snapshot,
)
from consultation_v2.yaml_contract import load_platform_yaml, platform_yaml_path


_POLICY_BY_SCOPE = {
    'snapshot': 'invalidate_reacquire',
    'menu_snapshot': 'invalidate_reacquire_menu',
    'app_root_snapshot': 'live_reacquire_no_clear',
    'native_dialog_snapshot': 'native_invalidate_reacquire',
}
_TRANSITION_KEYS = frozenset({'observation', 'source_exception'})
_OBSERVATION_KEYS = frozenset({
    'consecutive_matches',
    'interval_ms',
    'refresh_policy',
    'scope',
    'surface',
    'timeout_ms',
})
_ACTION_RECEIPT_KEYS = frozenset({
    'action',
    'element',
    'mutation_count',
    'outcome',
    'ref',
    'revision',
})


class PostActionContractError(ValueError):
    pass


class PostActionObservationError(RuntimeError):
    def __init__(self, message: str, refresh_outcomes: Sequence[Mapping[str, Any]] = ()) -> None:
        super().__init__(message)
        self.refresh_outcomes = tuple(dict(item) for item in refresh_outcomes)


@dataclass(frozen=True, slots=True)
class PostActionLineage:
    seat_id: str
    turn_id: str
    process_generation: str
    display: str
    atspi_bus_address: str
    pre_action_revision: str

    def serializable(self) -> dict[str, Any]:
        values = {
            'seat_id': self.seat_id,
            'turn_id': self.turn_id,
            'process_generation': self.process_generation,
            'display': self.display,
            'atspi_bus_address': self.atspi_bus_address,
            'pre_action_revision': self.pre_action_revision,
        }
        for key, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise PostActionContractError(f'lineage.{key} must be a non-empty string')
        return values


@dataclass(frozen=True, slots=True)
class PostActionTransition:
    platform: str
    transition_id: str
    source_exception: str
    action: str
    element: str
    max_attempts: int
    success_element: str
    alternate_elements: tuple[str, ...]
    url_prefix: str
    surface: str
    scope: str
    refresh_policy: str
    consecutive_matches: int
    timeout_ms: int
    interval_ms: int
    element_specs: Mapping[str, Mapping[str, Any]]
    yaml_sha256: str

    def postcondition(self) -> dict[str, Any]:
        return {
            'happy': {
                'element': self.success_element,
                'match_count': 1,
                'spec': dict(self.element_specs[self.success_element]),
                'url_prefix': self.url_prefix,
            },
            'alternate': {
                'exception': self.source_exception,
                'elements': [
                    {
                        'element': key,
                        'match_count': 1,
                        'spec': dict(self.element_specs[key]),
                    }
                    for key in self.alternate_elements
                ],
            },
        }

    @property
    def postcondition_sha256(self) -> str:
        return _canonical_sha256(self.postcondition())


@dataclass(frozen=True, slots=True)
class PostActionSample:
    snapshot: Any
    refresh_outcomes: tuple[Mapping[str, Any], ...]


SampleReader = Callable[[PostActionTransition], PostActionSample]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PostActionContractError(f'{path} must be a mapping')
    return value


def _exact_keys(value: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise PostActionContractError(f'{path} has unsupported keys: {unexpected}')


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PostActionContractError(f'{path} must be a positive integer')
    return value


def _element_key(value: Any, element_map: Mapping[str, Any], path: str) -> str:
    if not isinstance(value, str) or value not in element_map:
        raise PostActionContractError(f'{path} must name an element_map key')
    return value


def resolve_post_action_transition(platform: str, transition_id: str) -> PostActionTransition:
    cfg = load_platform_yaml(platform)
    workflow = _mapping(cfg.get('workflow'), f'{platform}.workflow')
    declarations = _mapping(
        workflow.get('post_action_transitions'),
        f'{platform}.workflow.post_action_transitions',
    )
    declaration = _mapping(
        declarations.get(transition_id),
        f'{platform}.workflow.post_action_transitions.{transition_id}',
    )
    _exact_keys(
        declaration,
        _TRANSITION_KEYS,
        f'{platform}.workflow.post_action_transitions.{transition_id}',
    )

    source_exception = declaration.get('source_exception')
    if not isinstance(source_exception, str) or not source_exception:
        raise PostActionContractError(
            f'{platform}.workflow.post_action_transitions.{transition_id}.source_exception '
            'must be a non-empty string'
        )
    post_send = _mapping(workflow.get('post_send'), f'{platform}.workflow.post_send')
    exceptions = _mapping(post_send.get('exceptions'), f'{platform}.workflow.post_send.exceptions')
    exception = _mapping(
        exceptions.get(source_exception),
        f'{platform}.workflow.post_send.exceptions.{source_exception}',
    )
    recovery = _mapping(
        exception.get('recovery'),
        f'{platform}.workflow.post_send.exceptions.{source_exception}.recovery',
    )
    element_map = _mapping(
        (cfg.get('tree') or {}).get('element_map'),
        f'{platform}.tree.element_map',
    )

    action = recovery.get('action')
    if action != 'click':
        raise PostActionContractError(
            f'{platform} transition {transition_id} recovery.action must be click'
        )
    element = _element_key(recovery.get('element'), element_map, f'{platform}.recovery.element')
    max_attempts = _positive_int(recovery.get('max_attempts'), f'{platform}.recovery.max_attempts')
    if max_attempts != 1:
        raise PostActionContractError(
            f'{platform} transition {transition_id} authorizes exactly one mutation'
        )
    success_element = _element_key(
        recovery.get('success_element'),
        element_map,
        f'{platform}.recovery.success_element',
    )
    url_prefix = recovery.get('url_prefix')
    if not isinstance(url_prefix, str) or not url_prefix.startswith('https://'):
        raise PostActionContractError(f'{platform}.recovery.url_prefix must be an https URL prefix')

    raw_alternate = exception.get('detect')
    if not isinstance(raw_alternate, list) or not raw_alternate:
        raise PostActionContractError(
            f'{platform} exception {source_exception}.detect must be a list'
        )
    alternate_elements = tuple(
        _element_key(value, element_map, f'{platform}.exception.detect')
        for value in raw_alternate
    )
    if element not in alternate_elements:
        raise PostActionContractError(
            f'{platform} recovery element {element!r} must be part of its exception detection set'
        )
    if len(set(alternate_elements)) != len(alternate_elements):
        raise PostActionContractError(
            f'{platform} exception {source_exception}.detect has duplicates'
        )

    observation = _mapping(
        declaration.get('observation'),
        f'{platform}.workflow.post_action_transitions.{transition_id}.observation',
    )
    _exact_keys(
        observation,
        _OBSERVATION_KEYS,
        f'{platform}.workflow.post_action_transitions.{transition_id}.observation',
    )
    scope = observation.get('scope')
    if scope not in _POLICY_BY_SCOPE:
        raise PostActionContractError(f'{platform} transition {transition_id} has invalid scope')
    refresh_policy = observation.get('refresh_policy')
    if refresh_policy != _POLICY_BY_SCOPE[scope]:
        raise PostActionContractError(
            f'{platform} transition {transition_id} scope {scope!r} requires '
            f'refresh_policy {_POLICY_BY_SCOPE[scope]!r}'
        )
    surface = observation.get('surface')
    expected_surface = 'native_dialog' if scope == 'native_dialog_snapshot' else 'browser'
    if surface != expected_surface:
        raise PostActionContractError(
            f'{platform} transition {transition_id} scope {scope!r} requires surface '
            f'{expected_surface!r}'
        )
    consecutive_matches = _positive_int(
        observation.get('consecutive_matches'),
        f'{platform}.observation.consecutive_matches',
    )
    if consecutive_matches < 2:
        raise PostActionContractError(
            f'{platform} transition {transition_id} requires at least two independent matches'
        )
    timeout_ms = _positive_int(observation.get('timeout_ms'), f'{platform}.observation.timeout_ms')
    interval_ms = _positive_int(
        observation.get('interval_ms'),
        f'{platform}.observation.interval_ms',
    )
    if interval_ms >= timeout_ms:
        raise PostActionContractError(
            f'{platform} transition {transition_id} interval_ms must be below timeout_ms'
        )

    relevant_keys = (success_element, *alternate_elements)
    element_specs = {
        key: dict(_mapping(element_map[key], f'{platform}.tree.element_map.{key}'))
        for key in relevant_keys
    }
    yaml_source = platform_yaml_path(platform).read_bytes()
    return PostActionTransition(
        platform=platform,
        transition_id=transition_id,
        source_exception=source_exception,
        action=action,
        element=element,
        max_attempts=max_attempts,
        success_element=success_element,
        alternate_elements=alternate_elements,
        url_prefix=url_prefix,
        surface=surface,
        scope=scope,
        refresh_policy=refresh_policy,
        consecutive_matches=consecutive_matches,
        timeout_ms=timeout_ms,
        interval_ms=interval_ms,
        element_specs=element_specs,
        yaml_sha256=hashlib.sha256(yaml_source).hexdigest(),
    )


def _refresh_target(target: Any, name: str, outcomes: list[dict[str, Any]]) -> None:
    try:
        target.clear_cache_single()
    except Exception as exc:
        outcomes.append({
            'target': name,
            'outcome': 'failed',
            'error': f'{type(exc).__name__}: {exc}',
        })
        raise PostActionObservationError(
            f'cache invalidation failed for {name}',
            outcomes,
        ) from exc
    outcomes.append({'target': name, 'outcome': 'invalidated'})


def _strict_atspi_refresh(
    platform: str,
    *,
    include_document: bool,
) -> list[dict[str, Any]]:
    outcomes: list[dict[str, Any]] = []
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
        desktop = Atspi.get_desktop(0)
    except Exception as exc:
        outcomes.append({
            'target': 'desktop',
            'outcome': 'failed',
            'error': f'{type(exc).__name__}: {exc}',
        })
        raise PostActionObservationError('AT-SPI desktop reacquisition failed', outcomes) from exc
    _refresh_target(desktop, 'desktop', outcomes)

    firefox = platform_routing.find_firefox_for_platform(platform)
    if firefox is None:
        outcomes.append({'target': 'firefox', 'outcome': 'missing'})
        raise PostActionObservationError(f'Firefox not found for {platform}', outcomes)
    outcomes.append({'target': 'firefox', 'outcome': 'reacquired'})
    _refresh_target(firefox, 'firefox', outcomes)

    if include_document:
        document = platform_routing.get_platform_document(firefox, platform)
        if document is None:
            outcomes.append({'target': 'document', 'outcome': 'missing'})
            raise PostActionObservationError(f'document not found for {platform}', outcomes)
        outcomes.append({'target': 'document', 'outcome': 'reacquired'})
        _refresh_target(document, 'document', outcomes)
    return outcomes


def acquire_post_action_sample(transition: PostActionTransition) -> PostActionSample:
    if _POLICY_BY_SCOPE.get(transition.scope) != transition.refresh_policy:
        raise PostActionContractError(
            f'{transition.scope!r} cannot use refresh policy {transition.refresh_policy!r}'
        )

    if transition.refresh_policy in {
        'invalidate_reacquire',
        'invalidate_reacquire_menu',
    }:
        outcomes = _strict_atspi_refresh(transition.platform, include_document=True)
        try:
            if transition.scope == 'snapshot':
                _, _, snapshot = build_snapshot(transition.platform)
            else:
                _, _, snapshot = build_menu_snapshot(transition.platform)
        except Exception as exc:
            outcomes.append({
                'target': transition.scope,
                'outcome': 'failed',
                'error': f'{type(exc).__name__}: {exc}',
            })
            raise PostActionObservationError(
                f'{transition.scope} reacquisition failed for {transition.platform}',
                outcomes,
            ) from exc
        outcomes.append({'target': transition.scope, 'outcome': 'reacquired'})
        return PostActionSample(snapshot=snapshot, refresh_outcomes=tuple(outcomes))

    if transition.refresh_policy == 'live_reacquire_no_clear':
        outcomes: list[dict[str, Any]] = []
        firefox = platform_routing.find_firefox_for_platform(transition.platform)
        if firefox is None:
            outcomes.append({'target': 'firefox', 'outcome': 'missing'})
            raise PostActionObservationError(
                f'Firefox not found for {transition.platform}',
                outcomes,
            )
        outcomes.append({'target': 'firefox', 'outcome': 'live_reacquired_no_clear'})
        try:
            snapshot = build_app_root_snapshot(transition.platform)
        except Exception as exc:
            outcomes.append({
                'target': transition.scope,
                'outcome': 'failed',
                'error': f'{type(exc).__name__}: {exc}',
            })
            raise PostActionObservationError(
                f'{transition.scope} reacquisition failed for {transition.platform}',
                outcomes,
            ) from exc
        outcomes.append({'target': transition.scope, 'outcome': 'live_reacquired_no_clear'})
        return PostActionSample(snapshot=snapshot, refresh_outcomes=tuple(outcomes))

    outcomes = _strict_atspi_refresh(transition.platform, include_document=False)
    try:
        snapshot = build_native_dialog_snapshot(transition.platform)
    except Exception as exc:
        outcomes.append({
            'target': transition.scope,
            'outcome': 'failed',
            'error': f'{type(exc).__name__}: {exc}',
        })
        raise PostActionObservationError(
            f'{transition.scope} reacquisition failed for {transition.platform}',
            outcomes,
        ) from exc
    outcomes.append({'target': transition.scope, 'outcome': 'reacquired'})
    return PostActionSample(snapshot=snapshot, refresh_outcomes=tuple(outcomes))


def _element_observation(element: Any) -> dict[str, Any]:
    return {
        'key': str(getattr(element, 'key', '') or ''),
        'name': str(getattr(element, 'name', '') or ''),
        'role': str(getattr(element, 'role', '') or ''),
        'states': sorted(str(value).lower() for value in (getattr(element, 'states', ()) or ())),
    }


def _mapped_projection(snapshot: Any, key: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    mapped = getattr(snapshot, 'mapped', {}) or {}
    items = tuple(mapped.get(key) or ())
    observed = [_element_observation(item) for item in items]
    declared_match = len(items) == 1
    if declared_match:
        item = observed[0]
        declared_match = item['key'] == key
        if 'name' in spec:
            declared_match = declared_match and item['name'] == str(spec['name'])
        if declared_match and 'names_any_of' in spec:
            declared_match = item['name'] in {str(value) for value in spec['names_any_of']}
        if declared_match and 'role' in spec:
            declared_match = item['role'] == str(spec['role'])
        if declared_match and 'states_include' in spec:
            declared_match = {
                str(value).lower() for value in spec['states_include']
            }.issubset(set(item['states']))
    return {
        'element': key,
        'expected_match_count': 1,
        'observed_match_count': len(items),
        'expected_spec': dict(spec),
        'observed': observed,
        'classification_authority': 'snapshot.mapped',
        'declared_match': declared_match,
    }


def _snapshot_revision(snapshot: Any) -> str:
    revision = getattr(snapshot, 'revision', None)
    if isinstance(revision, str) and revision:
        return revision
    serializable = getattr(snapshot, 'serializable', None)
    if not callable(serializable):
        raise PostActionObservationError('post-action snapshot is not serializable')
    return _canonical_sha256(serializable())


def project_post_action_sample(
    transition: PostActionTransition,
    sample: PostActionSample,
) -> dict[str, Any]:
    snapshot = sample.snapshot
    happy_element = _mapped_projection(
        snapshot,
        transition.success_element,
        transition.element_specs[transition.success_element],
    )
    alternates = [
        _mapped_projection(snapshot, key, transition.element_specs[key])
        for key in transition.alternate_elements
    ]
    observed_url = getattr(snapshot, 'url', None)
    observed_platform = getattr(snapshot, 'platform', None)
    platform_matches = observed_platform == transition.platform
    url_matches = isinstance(observed_url, str) and observed_url.startswith(transition.url_prefix)
    happy_matches = happy_element['declared_match'] and url_matches
    alternate_matches = all(item['declared_match'] for item in alternates)

    relevant = (happy_element, *alternates)
    terminal_drift = any(
        item['observed_match_count'] > 1
        or (item['observed_match_count'] == 1 and not item['declared_match'])
        for item in relevant
    )
    terminal_drift = terminal_drift or (
        isinstance(observed_url, str) and not url_matches
    )
    terminal_drift = terminal_drift or not platform_matches
    if happy_matches and alternate_matches:
        state = 'ambiguous'
    elif terminal_drift:
        state = 'drift'
    elif happy_matches:
        state = 'happy'
    elif alternate_matches:
        state = 'alternate'
    else:
        state = 'pending'
    projection = {
        'state': state,
        'platform': {
            'expected': transition.platform,
            'observed': observed_platform,
            'matches': platform_matches,
        },
        'url': {
            'expected_prefix': transition.url_prefix,
            'observed': observed_url,
            'matches': url_matches,
        },
        'happy': happy_element,
        'alternate': {
            'exception': transition.source_exception,
            'elements': alternates,
            'matches': alternate_matches,
        },
    }
    projection['sha256'] = _canonical_sha256(projection)
    return projection


def _validate_action_receipt(
    transition: PostActionTransition,
    action_receipt: Mapping[str, Any],
    lineage: PostActionLineage,
) -> dict[str, Any]:
    if not isinstance(action_receipt, dict):
        raise PostActionContractError('action_receipt must be a mapping')
    missing = sorted(_ACTION_RECEIPT_KEYS - set(action_receipt))
    unexpected = sorted(set(action_receipt) - _ACTION_RECEIPT_KEYS)
    if missing or unexpected:
        raise PostActionContractError(
            f'action_receipt keys mismatch: missing={missing} unexpected={unexpected}'
        )
    if action_receipt['action'] != transition.action:
        raise PostActionContractError('action_receipt.action does not match the transition')
    if action_receipt['element'] != transition.element:
        raise PostActionContractError('action_receipt.element does not match the transition')
    if action_receipt['outcome'] != 'applied':
        raise PostActionContractError('action_receipt.outcome must be applied')
    if action_receipt['mutation_count'] != 1:
        raise PostActionContractError('action_receipt.mutation_count must be exactly 1')
    if not isinstance(action_receipt['ref'], str) or not action_receipt['ref']:
        raise PostActionContractError('action_receipt.ref must be a non-empty string')
    if action_receipt['revision'] != lineage.pre_action_revision:
        raise PostActionContractError('action_receipt.revision does not match lineage')
    return dict(action_receipt)


def _run_resolved_post_action_barrier(
    transition: PostActionTransition,
    *,
    lineage: PostActionLineage,
    action_receipt: Mapping[str, Any],
    sample_reader: SampleReader = acquire_post_action_sample,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    lineage_payload = lineage.serializable()
    action_payload = _validate_action_receipt(transition, action_receipt, lineage)
    action_receipt_sha256 = _canonical_sha256(action_payload)
    started = monotonic()
    deadline = started + (transition.timeout_ms / 1000.0)
    samples: list[dict[str, Any]] = []
    consecutive = 0
    last_happy_sha256: str | None = None
    verdict = 'HALT'
    reason = 'postcondition_timeout'

    while True:
        try:
            sample = sample_reader(transition)
            projection = project_post_action_sample(transition, sample)
            revision = _snapshot_revision(sample.snapshot)
        except PostActionObservationError as exc:
            samples.append({
                'index': len(samples) + 1,
                'elapsed_ms': round((monotonic() - started) * 1000, 3),
                'refresh_outcomes': [dict(item) for item in exc.refresh_outcomes],
                'outcome': 'observation_failed',
                'error': str(exc),
            })
            reason = 'observation_failed'
            break
        except Exception as exc:
            samples.append({
                'index': len(samples) + 1,
                'elapsed_ms': round((monotonic() - started) * 1000, 3),
                'refresh_outcomes': [],
                'outcome': 'observation_failed',
                'error': f'{type(exc).__name__}: {exc}',
            })
            reason = 'observation_failed'
            break

        sample_record = {
            'index': len(samples) + 1,
            'elapsed_ms': round((monotonic() - started) * 1000, 3),
            'revision': revision,
            'refresh_outcomes': [dict(item) for item in sample.refresh_outcomes],
            'projection': projection,
            'outcome': projection['state'],
        }
        samples.append(sample_record)

        if projection['state'] == 'happy':
            if projection['sha256'] == last_happy_sha256:
                consecutive += 1
            else:
                consecutive = 1
                last_happy_sha256 = projection['sha256']
            if consecutive >= transition.consecutive_matches:
                verdict = 'PASS'
                reason = 'postcondition_confirmed'
                break
        else:
            consecutive = 0
            last_happy_sha256 = None
            if projection['state'] == 'alternate':
                reason = f'mapped_exception:{transition.source_exception}'
                break
            if projection['state'] in {'ambiguous', 'drift'}:
                reason = f'postcondition_{projection["state"]}'
                break

        now = monotonic()
        if now >= deadline:
            break
        sleeper(min(transition.interval_ms / 1000.0, deadline - now))

    receipt = {
        'schema': 'post_action_barrier_receipt.v1',
        'platform': transition.platform,
        'transition_id': transition.transition_id,
        'lineage': lineage_payload,
        'action_receipt': action_payload,
        'action_receipt_sha256': action_receipt_sha256,
        'yaml_sha256': transition.yaml_sha256,
        'postcondition': transition.postcondition(),
        'postcondition_sha256': transition.postcondition_sha256,
        'observation_policy': {
            'surface': transition.surface,
            'scope': transition.scope,
            'refresh_policy': transition.refresh_policy,
            'consecutive_matches': transition.consecutive_matches,
            'timeout_ms': transition.timeout_ms,
            'interval_ms': transition.interval_ms,
        },
        'samples': samples,
        'duration_ms': round((monotonic() - started) * 1000, 3),
        'verdict': verdict,
        'reason': reason,
        'next_mutation_authorized': verdict == 'PASS',
    }
    receipt['receipt_sha256'] = _canonical_sha256(receipt)
    return receipt


def run_post_action_barrier(
    platform: str,
    transition_id: str,
    *,
    lineage: PostActionLineage,
    action_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    transition = resolve_post_action_transition(platform, transition_id)
    return run_resolved_post_action_barrier(
        transition,
        lineage=lineage,
        action_receipt=action_receipt,
    )


def run_resolved_post_action_barrier(
    transition: PostActionTransition,
    *,
    lineage: PostActionLineage,
    action_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    return _run_resolved_post_action_barrier(
        transition,
        lineage=lineage,
        action_receipt=action_receipt,
        sample_reader=acquire_post_action_sample,
        monotonic=time.monotonic,
        sleeper=time.sleep,
    )
