from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from consultation_v2 import atspi, input as input_core
from consultation_v2.linkedin_jobs_contract import (
    ENGAGEMENT_SIGNAL_SCHEMA,
    SELECTED_JOB_SCHEMA,
    canonical_json_bytes,
    read_owned_private_bytes,
    sha256_hex,
    write_new_private_json,
)
from consultation_v2.platforms import routing as platform_routing
from consultation_v2.snapshot import build_snapshot
from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


class LinkedInSelectedJobUnavailable(RuntimeError):
    def __init__(self, message: str, match_counts: Mapping[str, int]) -> None:
        super().__init__(message)
        self.match_counts = dict(match_counts)


class LinkedInJobCardUnavailable(RuntimeError):
    def __init__(self, message: str, match_count: int) -> None:
        super().__init__(message)
        self.match_count = match_count


class LinkedInJobCardActionFailed(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        verdict: str,
        action_name: str,
        action_index: int | None,
        action_match_count: int,
    ) -> None:
        super().__init__(message)
        self.verdict = verdict
        self.action_name = action_name
        self.action_index = action_index
        self.action_match_count = action_match_count


@dataclass(frozen=True, slots=True)
class SelectedJobObservation:
    record: Mapping[str, Any]
    content_digest: str
    match_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SinkWriteResult:
    records_written: int
    artifact_sha256: str


@dataclass(frozen=True, slots=True)
class JobSelectionObservation:
    target_match_count: int
    detail_title_match_count: int
    detail_company_match_count: int
    action_name: str | None = None
    action_index: int | None = None
    action_match_count: int = 0


_REQUIRED_KEYS = (
    'about_job_heading',
    'selected_job_description_path',
)


class _DescriptionPathMismatch(RuntimeError):
    pass


def _job_selection_contract() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    contract = workflow.get('job_selection')
    if not isinstance(contract, dict):
        raise RuntimeError('LinkedIn job selection is not configured')
    return dict(contract)


def _exact_private_element(
    snapshot: Snapshot,
    exact_name: str,
    contract_key: str,
) -> tuple[ElementRef | None, int]:
    contract = _job_selection_contract().get(contract_key)
    if not isinstance(contract, dict):
        raise RuntimeError(f'LinkedIn {contract_key} contract is unavailable')
    role = contract.get('role')
    states = contract.get('states_include')
    if not isinstance(role, str) or not role:
        raise RuntimeError(f'LinkedIn {contract_key} role is invalid')
    if not isinstance(states, list) or not states or not all(
        isinstance(state, str) and state for state in states
    ):
        raise RuntimeError(f'LinkedIn {contract_key} states are invalid')
    elements = [
        *snapshot.unknown,
        *snapshot.sidebar,
        *snapshot.menu_items,
        *[
            element
            for mapped in snapshot.mapped.values()
            for element in mapped
        ],
    ]
    matches: list[ElementRef] = []
    seen: set[int] = set()
    for element in elements:
        identity = id(element.atspi_obj)
        if identity in seen:
            continue
        seen.add(identity)
        if (
            element.name == exact_name
            and element.role == role
            and set(states).issubset(element.states)
        ):
            matches.append(element)
    return (matches[0] if len(matches) == 1 else None), len(matches)


def activate_private_job_card(
    snapshot: Snapshot,
    target_card_name: str,
) -> JobSelectionObservation:
    target, target_count = _exact_private_element(
        snapshot,
        target_card_name,
        'target_card',
    )
    if target is None:
        raise LinkedInJobCardUnavailable(
            'job selection requires exactly one private exact target card',
            target_count,
        )
    action_contract = _job_selection_contract().get('action')
    if not isinstance(action_contract, dict) or action_contract.get('interface') != 'atspi_action':
        raise RuntimeError('LinkedIn job-card action interface is invalid')
    action_name = action_contract.get('name')
    if not isinstance(action_name, str) or not action_name:
        raise RuntimeError('LinkedIn job-card action name is invalid')
    try:
        action_iface = target.atspi_obj.get_action_iface()
        action_count = int(action_iface.get_n_actions()) if action_iface is not None else 0
        action_indexes = [
            index
            for index in range(action_count)
            if str(action_iface.get_action_name(index) or '') == action_name
        ]
    except Exception as exc:
        raise RuntimeError('cannot inspect LinkedIn job-card Action interface') from exc
    if len(action_indexes) != 1:
        raise LinkedInJobCardActionFailed(
            'LinkedIn authorized job-card action is not exact',
            verdict='action_not_exact',
            action_name=action_name,
            action_index=None,
            action_match_count=len(action_indexes),
        )
    action_index = action_indexes[0]
    try:
        action_succeeded = bool(action_iface.do_action(action_index))
    except Exception as exc:
        raise LinkedInJobCardActionFailed(
            'LinkedIn exact job-card action raised',
            verdict='action_failed',
            action_name=action_name,
            action_index=action_index,
            action_match_count=1,
        ) from exc
    if not action_succeeded:
        raise LinkedInJobCardActionFailed(
            'LinkedIn exact job-card action returned false',
            verdict='action_failed',
            action_name=action_name,
            action_index=action_index,
            action_match_count=1,
        )
    return JobSelectionObservation(
        target_match_count=target_count,
        detail_title_match_count=0,
        detail_company_match_count=0,
        action_name=action_name,
        action_index=action_index,
        action_match_count=1,
    )


def observe_private_selected_job(
    snapshot: Snapshot,
    detail_title_name: str,
    detail_company_name: str,
) -> JobSelectionObservation:
    _title, title_count = _exact_private_element(
        snapshot,
        detail_title_name,
        'detail_title',
    )
    _company, company_count = _exact_private_element(
        snapshot,
        detail_company_name,
        'detail_company',
    )
    if title_count != 1 or company_count != 1:
        raise LinkedInJobCardUnavailable(
            'selected-job detail does not match the private exact title and company',
            0,
        )
    return JobSelectionObservation(
        target_match_count=0,
        detail_title_match_count=title_count,
        detail_company_match_count=company_count,
    )


def job_selection_barrier_policy() -> tuple[int, float, float]:
    barrier = _job_selection_contract().get('observation_barrier')
    if not isinstance(barrier, dict):
        raise RuntimeError('LinkedIn job-selection observation barrier is unavailable')
    stable_cycles = barrier.get('stable_cycles')
    interval_ms = barrier.get('interval_ms')
    timeout_ms = barrier.get('timeout_ms')
    if (
        isinstance(stable_cycles, bool)
        or not isinstance(stable_cycles, int)
        or stable_cycles < 1
        or isinstance(interval_ms, bool)
        or not isinstance(interval_ms, int)
        or interval_ms < 1
        or isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or timeout_ms < interval_ms
    ):
        raise RuntimeError('LinkedIn job-selection observation barrier is invalid')
    return stable_cycles, interval_ms / 1000.0, timeout_ms / 1000.0


def _description_traversal() -> list[dict[str, Any]]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    selected_job_read = workflow.get('selected_job_read') or {}
    traversal = selected_job_read.get('description_traversal')
    if not isinstance(traversal, list) or not traversal:
        raise RuntimeError('LinkedIn description traversal is not configured')
    if not all(isinstance(step, dict) for step in traversal):
        raise RuntimeError('LinkedIn description traversal steps must be mappings')
    return [dict(step) for step in traversal]


def _relative_node(anchor: ElementRef) -> Any:
    node = anchor.atspi_obj
    if node is None:
        raise RuntimeError('About heading has no AT-SPI object')
    for step in _description_traversal():
        relation = step.get('relation')
        if relation == 'parent' and set(step) == {'relation', 'role'}:
            try:
                node = node.get_parent()
            except Exception as exc:
                raise RuntimeError('cannot read LinkedIn description parent') from exc
        elif relation == 'child' and set(step) == {'relation', 'index', 'role'}:
            index = step.get('index')
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise RuntimeError('LinkedIn description child index is invalid')
            try:
                child_count = int(node.get_child_count())
                node = node.get_child_at_index(index) if index < child_count else None
            except Exception as exc:
                raise RuntimeError('cannot read LinkedIn description child') from exc
        else:
            raise RuntimeError('LinkedIn description traversal step is invalid')
        if node is None:
            raise _DescriptionPathMismatch('LinkedIn description path is absent')
        try:
            role = str(node.get_role_name() or '')
        except Exception as exc:
            raise RuntimeError('cannot read LinkedIn description role') from exc
        if role != step['role']:
            raise _DescriptionPathMismatch('LinkedIn description role differs from YAML')
    return node


def _description_text(node: Any) -> str:
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        text_iface = node.get_text_iface()
        if text_iface is None:
            raise _DescriptionPathMismatch('LinkedIn description has no Text interface')
        character_count = int(Atspi.Text.get_character_count(text_iface))
        if character_count < 1:
            raise _DescriptionPathMismatch('LinkedIn description Text interface is empty')
        text = str(Atspi.Text.get_text(text_iface, 0, character_count) or '').strip()
    except _DescriptionPathMismatch:
        raise
    except Exception as exc:
        raise RuntimeError('cannot read LinkedIn description Text interface') from exc
    if not text:
        raise _DescriptionPathMismatch('LinkedIn description text is empty')
    return text


def _exact_elements(snapshot: Snapshot) -> tuple[ElementRef, Any, dict[str, int]]:
    heading_matches = snapshot.mapped.get('about_job_heading') or []
    match_counts = {
        'about_job_heading': len(heading_matches),
        'selected_job_description_path': 0,
    }
    if len(heading_matches) != 1:
        raise LinkedInSelectedJobUnavailable(
            'selected-job mapping requires exactly one About heading',
            match_counts,
        )
    heading = heading_matches[0]
    try:
        description_node = _relative_node(heading)
    except _DescriptionPathMismatch as exc:
        raise LinkedInSelectedJobUnavailable(str(exc), match_counts) from exc
    match_counts['selected_job_description_path'] = 1
    return heading, description_node, match_counts


def observe_selected_job(snapshot: Snapshot, search_ref: str) -> SelectedJobObservation:
    if snapshot.platform != 'linkedin':
        raise LinkedInSelectedJobUnavailable(
            'snapshot platform is not linkedin',
            {key: 0 for key in _REQUIRED_KEYS},
        )
    heading, description_node, match_counts = _exact_elements(snapshot)
    source_url = str(snapshot.url or '').strip()
    try:
        detail_text = _description_text(description_node)
    except _DescriptionPathMismatch as exc:
        raise LinkedInSelectedJobUnavailable(str(exc), match_counts) from exc
    if not source_url or heading.name != 'About the job' or heading.role != 'heading':
        raise LinkedInSelectedJobUnavailable(
            'selected job detail is not fully observable',
            match_counts,
        )
    record = {
        'schema': SELECTED_JOB_SCHEMA,
        'search_ref': search_ref,
        'source_url': source_url,
        'detail_heading': heading.name,
        'detail_text': detail_text,
    }
    return SelectedJobObservation(
        record=record,
        content_digest=sha256_hex(canonical_json_bytes(record)),
        match_counts=match_counts,
    )


def write_selected_job_once(
    observation: SelectedJobObservation,
    sink_root: Path,
) -> SinkWriteResult:
    artifact = sink_root / f'linkedin-job-{observation.content_digest}.json'
    if artifact.exists():
        raw_bytes = read_owned_private_bytes(artifact, 'selected-job artifact')
        if sha256_hex(raw_bytes) != observation.content_digest:
            raise RuntimeError('existing selected-job artifact digest mismatch')
        return SinkWriteResult(records_written=0, artifact_sha256=observation.content_digest)
    raw_bytes = write_new_private_json(artifact, observation.record)
    artifact_sha256 = sha256_hex(raw_bytes)
    if artifact_sha256 != observation.content_digest:
        raise RuntimeError('selected-job sink readback digest mismatch')
    if sha256_hex(read_owned_private_bytes(artifact, 'selected-job artifact')) != artifact_sha256:
        raise RuntimeError('selected-job sink readback changed after write')
    return SinkWriteResult(records_written=1, artifact_sha256=artifact_sha256)


def selected_job_postcondition(
    before: SelectedJobObservation,
    after: SelectedJobObservation,
) -> bool:
    exact_counts = {key: 1 for key in _REQUIRED_KEYS}
    return (
        before.content_digest == after.content_digest
        and dict(before.match_counts) == exact_counts
        and dict(after.match_counts) == exact_counts
    )


class LinkedInEngagementActionFailed(RuntimeError):
    def __init__(self, stage: str, receipt: Mapping[str, Any]) -> None:
        super().__init__(f'{stage} exact action failed')
        self.stage = stage
        self.receipt = dict(receipt)


class LinkedInEngagementRestoreFailed(RuntimeError):
    def __init__(self, substep: str, receipt: Mapping[str, Any]) -> None:
        super().__init__(f'exact return navigation failed at {substep}')
        self.receipt = dict(receipt)


@dataclass(frozen=True, slots=True)
class EngagementSignalObservation:
    candidate_count: int
    candidate_set_digest: str
    record: Mapping[str, Any] | None
    content_digest: str | None


@dataclass(frozen=True, slots=True)
class StableEngagementObservation:
    snapshot: Snapshot | None
    signal: EngagementSignalObservation | None
    receipt: Mapping[str, Any]


def _engagement_workflow() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    contract = workflow.get('engagement_signal_capture')
    if not isinstance(contract, dict):
        raise RuntimeError('LinkedIn engagement workflow is not configured')
    return dict(contract)


def _all_elements(snapshot: Snapshot) -> list[ElementRef]:
    candidates = [
        *snapshot.unknown,
        *snapshot.sidebar,
        *snapshot.menu_items,
        *(element for values in snapshot.mapped.values() for element in values),
    ]
    elements: list[ElementRef] = []
    seen: set[int] = set()
    for element in candidates:
        identity = id(element.atspi_obj)
        if identity not in seen:
            seen.add(identity)
            elements.append(element)
    return elements


def _element_uri(element: ElementRef) -> str | None:
    if element.atspi_obj is None:
        return None
    try:
        hyperlink = element.atspi_obj.get_hyperlink()
        uri = str(hyperlink.get_uri(0) if hyperlink is not None else '').strip()
    except Exception:
        return None
    return uri or None


def _exact_engagement_route(url: str | None, route_key: str) -> bool:
    if not isinstance(url, str) or not url:
        return False
    route = (_engagement_workflow().get('routes') or {}).get(route_key)
    if not isinstance(route, dict):
        raise RuntimeError(f'LinkedIn engagement route {route_key!r} is invalid')
    parsed = urlsplit(url)
    if (
        parsed.scheme != route.get('scheme')
        or parsed.hostname != route.get('host')
        or parsed.port is not None
        or (parsed.path.rstrip('/') or '/') != route.get('normalized_path')
        or parsed.fragment
    ):
        return False
    expected_query = route.get('exact_query')
    return expected_query is None or parse_qs(
        parsed.query,
        keep_blank_values=True,
    ) == {str(key): [str(value)] for key, value in expected_query.items()}


def _states_match(element: ElementRef, required: Any) -> bool:
    if not isinstance(required, list) or not required or not all(
        isinstance(state, str) and state for state in required
    ):
        raise RuntimeError('LinkedIn engagement states contract is invalid')
    return set(required).issubset(set(element.states))


def _uri_matches(url: str | None, contract: Mapping[str, Any]) -> bool:
    if not isinstance(url, str) or not url:
        return False
    parsed = urlsplit(url)
    if not (
        parsed.scheme == contract.get('scheme')
        and parsed.hostname == contract.get('host')
        and parsed.port is None
        and (parsed.path.rstrip('/') or '/') == contract.get('normalized_path')
        and not parsed.fragment
    ):
        return False
    expected_query = contract.get('exact_query')
    query_variants = contract.get('exact_query_variants')
    if expected_query is not None and query_variants is not None:
        raise RuntimeError('LinkedIn URI query authority is ambiguous')
    observed_query = parse_qs(parsed.query, keep_blank_values=True)
    if expected_query is not None:
        if not isinstance(expected_query, Mapping):
            raise RuntimeError('LinkedIn exact URI query authority is invalid')
        return observed_query == {
            str(key): [str(value)] for key, value in expected_query.items()
        }
    if query_variants is None:
        return True
    if (
        not isinstance(query_variants, list)
        or not query_variants
        or any(
            not isinstance(variant, dict)
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                for key, value in variant.items()
            )
            for variant in query_variants
        )
    ):
        raise RuntimeError('LinkedIn exact URI query variants are invalid')
    canonical_variants = [
        tuple(sorted(variant.items())) for variant in query_variants
    ]
    if len(canonical_variants) != len(set(canonical_variants)):
        raise RuntimeError('LinkedIn exact URI query variants are duplicated')
    return observed_query in [
        {key: [value] for key, value in variant.items()}
        for variant in query_variants
    ]


def _nearest_document_url(element: ElementRef) -> str | None:
    ancestor = element.atspi_obj
    if ancestor is None:
        return None
    for _depth in range(64):
        try:
            ancestor = ancestor.get_parent()
        except Exception as exc:
            raise RuntimeError('cannot read LinkedIn Notifications ancestry') from exc
        if ancestor is None:
            return None
        try:
            role = str(ancestor.get_role_name() or '')
        except Exception as exc:
            raise RuntimeError('cannot read LinkedIn Notifications ancestor role') from exc
        if role == 'document web':
            return atspi.get_document_url(ancestor)
    raise RuntimeError('LinkedIn Notifications ancestry exceeds the bounded document search')


def _notifications_target(snapshot: Snapshot) -> tuple[ElementRef | None, int]:
    navigation = _engagement_workflow().get('navigation') or {}
    target = navigation.get('target') or {}
    action = navigation.get('action') or {}
    action_name = action.get('name')
    action_names_exact = target.get('action_names_exact')
    states_required = target.get('states_required')
    allowed_optional_states = target.get('allowed_optional_states')
    ancestor_document = target.get('ancestor_document')
    if (
        snapshot.platform != 'linkedin'
        or target.get('scope') != 'exact_linkedin_navigation_preload_document'
        or not isinstance(ancestor_document, dict)
        or not isinstance(states_required, list)
        or not states_required
        or len(states_required) != len(set(states_required))
        or not all(isinstance(state, str) and state for state in states_required)
        or not isinstance(allowed_optional_states, list)
        or len(allowed_optional_states) != len(set(allowed_optional_states))
        or not all(
            isinstance(state, str) and state
            for state in allowed_optional_states
        )
        or set(states_required).intersection(allowed_optional_states)
        or not isinstance(action_names_exact, list)
        or action_names_exact != [action_name]
        or not isinstance(action_name, str)
        or not action_name
        or action.get('index') != 0
    ):
        raise RuntimeError('LinkedIn Notifications authority is invalid')

    def action_names(element: ElementRef) -> list[str] | None:
        if element.atspi_obj is None:
            return None
        try:
            action_iface = element.atspi_obj.get_action_iface()
            action_count = int(action_iface.get_n_actions()) if action_iface else 0
            return [
                str(action_iface.get_action_name(index) or '')
                for index in range(action_count)
            ]
        except Exception as exc:
            raise RuntimeError('cannot read LinkedIn Notifications actions') from exc

    matches = [
        element
        for element in _all_elements(snapshot)
        if (
            element.role == target.get('role')
            and set(states_required).issubset(element.states)
            and set(element.states).issubset(
                set(states_required).union(allowed_optional_states)
            )
            and _uri_matches(_element_uri(element), target.get('uri') or {})
            and _uri_matches(_nearest_document_url(element), ancestor_document)
            and action_names(element) == action_names_exact
        )
    ]
    return (matches[0] if len(matches) == 1 else None), len(matches)


def _notifications_target_state_digest(
    snapshot: Snapshot,
    target: ElementRef,
    match_count: int,
) -> str:
    navigation = _engagement_workflow().get('navigation') or {}
    authority = navigation.get('target') or {}
    return sha256_hex(canonical_json_bytes({
        'current_document_url': snapshot.url,
        'ancestor_document_url': _nearest_document_url(target),
        'target_uri': _element_uri(target),
        'role': target.role,
        'states_observed': sorted(target.states),
        'action_names_exact': authority.get('action_names_exact'),
        'authority': authority,
        'match_count': match_count,
    }))


def _exact_mapped_engagement_element(
    snapshot: Snapshot,
    key: str,
) -> tuple[ElementRef | None, int]:
    contract = (
        (load_platform_yaml('linkedin').get('tree') or {})
        .get('element_map', {})
        .get(key, {})
    )
    matches = [
        element
        for element in (snapshot.mapped.get(key) or [])
        if (
            element.name == contract.get('name')
            and element.role == contract.get('role')
            and _states_match(element, contract.get('states_include'))
        )
    ]
    return (matches[0] if len(matches) == 1 else None), len(matches)


def _perform_engagement_action(
    element: ElementRef | None,
    target_count: int,
    action: Mapping[str, Any],
    stage: str,
) -> dict[str, Any]:
    action_name = action.get('name')
    if not isinstance(action_name, str) or not action_name or action.get('index') != 0:
        raise RuntimeError(f'{stage} action contract is invalid')
    receipt = {
        'stage': stage,
        'target_match_count': target_count,
        'action_name': action_name,
        'action_index': None,
        'action_match_count': 0,
        'verdict': 'target_not_exact',
    }
    if element is None or target_count != 1 or element.atspi_obj is None:
        raise LinkedInEngagementActionFailed(stage, receipt)
    try:
        action_iface = element.atspi_obj.get_action_iface()
        action_count = int(action_iface.get_n_actions()) if action_iface else 0
        indexes = [
            index
            for index in range(action_count)
            if str(action_iface.get_action_name(index) or '') == action_name
        ]
    except Exception as exc:
        receipt['verdict'] = 'action_enumeration_failed'
        raise LinkedInEngagementActionFailed(stage, receipt) from exc
    receipt['action_match_count'] = len(indexes)
    if indexes != [0]:
        receipt['verdict'] = 'action_not_exact'
        raise LinkedInEngagementActionFailed(stage, receipt)
    receipt['action_index'] = 0
    try:
        executed = bool(action_iface.do_action(0))
    except Exception as exc:
        receipt['verdict'] = 'action_raised'
        raise LinkedInEngagementActionFailed(stage, receipt) from exc
    if not executed:
        receipt['verdict'] = 'action_returned_false'
        raise LinkedInEngagementActionFailed(stage, receipt)
    receipt['verdict'] = 'executed'
    return receipt


def observe_engagement_start(
    snapshot: Snapshot,
    return_url: str,
) -> dict[str, Any]:
    target, count = _notifications_target(snapshot)
    state_digest = (
        _notifications_target_state_digest(snapshot, target, count)
        if target is not None
        else None
    )
    return {
        'route_exact': snapshot.url == return_url,
        'route_kind_exact': _exact_engagement_route(snapshot.url, 'jobs'),
        'notifications_target_match_count': count,
        'notifications_target_state_digest': state_digest,
    }


def observe_engagement_restore(
    snapshot: Snapshot,
    return_url: str,
) -> dict[str, Any]:
    target, count = _notifications_target(snapshot)
    state_digest = (
        _notifications_target_state_digest(snapshot, target, count)
        if target is not None
        else None
    )
    return {
        'route_exact': snapshot.url == return_url,
        'route_kind_exact': _exact_engagement_route(snapshot.url, 'jobs'),
        'notifications_target_match_count': count,
        'notifications_target_state_digest': state_digest,
    }


def activate_notifications(
    snapshot: Snapshot,
) -> dict[str, Any]:
    target, count = _notifications_target(snapshot)
    action = (_engagement_workflow().get('navigation') or {}).get('action') or {}
    return _perform_engagement_action(target, count, action, 'notifications_navigation')


def _barrier_settings(section: Mapping[str, Any], projection: str) -> tuple[int, float, float]:
    barrier = section.get('observation_barrier') or {}
    stable_cycles = barrier.get('stable_cycles')
    interval_ms = barrier.get('interval_ms')
    timeout_ms = barrier.get('timeout_ms')
    if (
        barrier.get('projection') != projection
        or barrier.get('refresh_policy') != 'invalidate_reacquire'
        or stable_cycles != 2
        or isinstance(interval_ms, bool)
        or not isinstance(interval_ms, int)
        or interval_ms < 1
        or isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or timeout_ms < interval_ms
    ):
        raise RuntimeError('LinkedIn engagement observation barrier is invalid')
    return stable_cycles, interval_ms / 1000.0, timeout_ms / 1000.0


def stable_notifications_observation(deadline_at: float) -> StableEngagementObservation:
    navigation = _engagement_workflow().get('navigation') or {}
    required, interval, timeout = _barrier_settings(
        navigation,
        'exact_route_and_my_posts_state',
    )
    barrier_deadline = min(deadline_at, time.monotonic() + timeout)
    prior: tuple[int, str | None] | None = None
    cycles = 0
    last_snapshot: Snapshot | None = None
    receipt: dict[str, Any] = {}
    while time.monotonic() < barrier_deadline:
        _firefox, _document, snapshot = build_snapshot('linkedin')
        target, count = _exact_mapped_engagement_element(snapshot, 'my_posts_filter')
        state_digest = sha256_hex(canonical_json_bytes({
            'name': target.name,
            'role': target.role,
            'states': sorted(target.states),
        })) if target is not None else None
        exact = (
            _exact_engagement_route(snapshot.url, 'notifications_all')
            and count == 1
            and state_digest is not None
        )
        projection = (count, state_digest)
        cycles = cycles + 1 if exact and projection == prior else (1 if exact else 0)
        prior = projection if exact else None
        last_snapshot = snapshot
        receipt = {
            'route_exact': _exact_engagement_route(snapshot.url, 'notifications_all'),
            'my_posts_match_count': count,
            'my_posts_state_digest': state_digest,
            'stable_cycles_required': required,
            'stable_cycles_observed': cycles,
        }
        if cycles >= required:
            return StableEngagementObservation(snapshot, None, receipt)
        time.sleep(interval)
    return StableEngagementObservation(last_snapshot, None, receipt)


def activate_my_posts(snapshot: Snapshot) -> dict[str, Any]:
    target, count = _exact_mapped_engagement_element(snapshot, 'my_posts_filter')
    contract = (
        (load_platform_yaml('linkedin').get('tree') or {})
        .get('element_map', {})
        .get('my_posts_filter', {})
    )
    return _perform_engagement_action(
        target,
        count,
        contract.get('action') or {},
        'my_posts_filter',
    )


def observe_engagement_signal(snapshot: Snapshot) -> EngagementSignalObservation:
    contract = _engagement_workflow().get('candidate_observation') or {}
    prefix = contract.get('observation_name_prefix')
    allowed_paths = contract.get('allowed_uri_normalized_path_prefixes')
    if (
        contract.get('authority') != 'observation_classification_only'
        or not isinstance(prefix, str)
        or not isinstance(allowed_paths, list)
        or not allowed_paths
    ):
        raise RuntimeError('LinkedIn engagement candidate contract is invalid')
    candidates: list[tuple[ElementRef, str]] = []
    for element in _all_elements(snapshot):
        uri = _element_uri(element)
        if (
            element.role == contract.get('role')
            and element.name.startswith(prefix)
            and _states_match(element, contract.get('states_include'))
            and isinstance(uri, str)
        ):
            parsed = urlsplit(uri)
            if (
                parsed.scheme == 'https'
                and parsed.hostname == 'www.linkedin.com'
                and parsed.port is None
                and any(parsed.path.startswith(str(path)) for path in allowed_paths)
                and not parsed.fragment
            ):
                candidates.append((element, uri))
    projection = sorted(
        ({'notification_name': element.name, 'notification_uri': uri}
         for element, uri in candidates),
        key=canonical_json_bytes,
    )
    candidate_set_digest = sha256_hex(canonical_json_bytes(projection))
    if len(candidates) != 1:
        return EngagementSignalObservation(
            len(candidates),
            candidate_set_digest,
            None,
            None,
        )
    element, uri = candidates[0]
    record = {
        'schema': ENGAGEMENT_SIGNAL_SCHEMA,
        'notification_name': element.name,
        'notification_uri': uri,
    }
    return EngagementSignalObservation(
        1,
        candidate_set_digest,
        record,
        sha256_hex(canonical_json_bytes(record)),
    )


def stable_my_posts_observation(deadline_at: float) -> StableEngagementObservation:
    workflow = _engagement_workflow()
    required, interval, timeout = _barrier_settings(
        workflow,
        'exact_route_marker_and_candidate_set',
    )
    barrier_deadline = min(deadline_at, time.monotonic() + timeout)
    prior: tuple[int, str] | None = None
    cycles = 0
    last_snapshot: Snapshot | None = None
    last_signal: EngagementSignalObservation | None = None
    receipt: dict[str, Any] = {}
    while time.monotonic() < barrier_deadline:
        _firefox, _document, snapshot = build_snapshot('linkedin')
        marker, marker_count = _exact_mapped_engagement_element(
            snapshot,
            'selected_filter_marker',
        )
        signal = observe_engagement_signal(snapshot)
        route_exact = _exact_engagement_route(snapshot.url, 'notifications_my_posts')
        exact = route_exact and marker_count == 1 and marker is not None
        projection = (signal.candidate_count, signal.candidate_set_digest)
        cycles = cycles + 1 if exact and projection == prior else (1 if exact else 0)
        prior = projection if exact else None
        last_snapshot = snapshot
        last_signal = signal
        receipt = {
            'route_exact': route_exact,
            'selected_filter_marker_match_count': marker_count,
            'candidate_count': signal.candidate_count,
            'candidate_set_digest': signal.candidate_set_digest,
            'stable_cycles_required': required,
            'stable_cycles_observed': cycles,
        }
        if cycles >= required:
            return StableEngagementObservation(snapshot, signal, receipt)
        time.sleep(interval)
    return StableEngagementObservation(last_snapshot, last_signal, receipt)


def write_engagement_signal_once(
    observation: EngagementSignalObservation,
    sink_root: Path,
) -> SinkWriteResult:
    if observation.record is None or observation.content_digest is None:
        raise RuntimeError('exact engagement signal is unavailable')
    artifact = sink_root / f'linkedin-engagement-{observation.content_digest}.json'
    if artifact.exists():
        existing = read_owned_private_bytes(artifact, 'engagement artifact')
        if sha256_hex(existing) != observation.content_digest:
            raise RuntimeError('existing engagement artifact digest mismatch')
        return SinkWriteResult(records_written=0, artifact_sha256=observation.content_digest)
    raw_bytes = write_new_private_json(artifact, observation.record)
    digest = sha256_hex(raw_bytes)
    if digest != observation.content_digest:
        raise RuntimeError('engagement sink readback digest mismatch')
    readback = read_owned_private_bytes(artifact, 'engagement artifact')
    if sha256_hex(readback) != observation.content_digest:
        raise RuntimeError('engagement sink persisted digest mismatch')
    return SinkWriteResult(records_written=1, artifact_sha256=digest)


def engagement_signal_postcondition(
    before: EngagementSignalObservation,
    after: EngagementSignalObservation,
) -> bool:
    return (
        before.candidate_count == 1
        and after.candidate_count == 1
        and before.content_digest is not None
        and before.content_digest == after.content_digest
    )


def _restore_contract() -> dict[str, Any]:
    contract = (_engagement_workflow().get('restore') or {})
    expected = {
        'navigation_key': 'ctrl+l',
        'address_bar': {
            'key': 'address_bar',
            'name': 'Search with Google or enter address',
            'role': 'entry',
            'states_include': ['editable', 'focusable'],
        },
        'submit_key': 'Return',
        'observation_barrier': {
            'projection': 'exact_return_route_and_current_notifications_state',
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
    }
    if contract != expected:
        raise RuntimeError('LinkedIn engagement restore contract is invalid')
    return dict(contract)


def _exact_address_bar(snapshot: Snapshot) -> ElementRef | None:
    contract = _restore_contract()['address_bar']
    key = contract.get('key')
    matches = [
        element
        for element in (snapshot.mapped.get(key) or [])
        if (
            element.name == contract.get('name')
            and element.role == contract.get('role')
            and _states_match(element, contract.get('states_include'))
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _select_full_address_text(snapshot: Snapshot) -> bool:
    entry = _exact_address_bar(snapshot)
    if entry is None or entry.atspi_obj is None or 'focused' not in entry.states:
        return False
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        text_iface = entry.atspi_obj.get_text_iface()
        character_count = int(Atspi.Text.get_character_count(text_iface))
        selections = int(Atspi.Text.get_n_selections(text_iface))
        if character_count < 1 or selections > 1:
            return False
        return bool(
            Atspi.Text.add_selection(text_iface, 0, character_count)
            if selections == 0
            else Atspi.Text.set_selection(text_iface, 0, 0, character_count)
        )
    except Exception:
        return False


def _full_address_selection_proven(snapshot: Snapshot) -> bool:
    entry = _exact_address_bar(snapshot)
    selections = entry.raw.get('text_selections') if entry is not None else None
    text = str(entry.text or '') if entry is not None else ''
    return (
        entry is not None
        and 'focused' in entry.states
        and bool(text)
        and isinstance(selections, list)
        and len(selections) == 1
        and selections[0].get('start') == 0
        and selections[0].get('end') == len(text)
    )


def exact_engagement_return(
    display: str,
    return_url: str,
    deadline_at: float,
) -> dict[str, Any]:
    restore = _restore_contract()
    receipt = {
        'verdict': 'not_executed',
        'failed_substep': None,
        'firefox_pid_sha256': None,
        'stable_cycles_required': 0,
        'stable_cycles_observed': 0,
        'return_url_sha256': sha256_hex(return_url.encode('utf-8')),
    }

    def fail(substep: str) -> None:
        receipt['verdict'] = 'indeterminate'
        receipt['failed_substep'] = substep
        raise LinkedInEngagementRestoreFailed(substep, receipt)

    input_core.set_display(display)
    try:
        firefox = platform_routing.find_firefox_for_platform('linkedin')
        pid = int(firefox.get_process_id()) if firefox is not None else 0
    except Exception:
        pid = 0
    if pid < 1:
        fail('firefox_process_identity')
    receipt['firefox_pid_sha256'] = sha256_hex(str(pid).encode('utf-8'))
    if not input_core.focus_firefox_pid(pid):
        fail('focus_firefox_pid')
    if restore.get('navigation_key') != 'ctrl+l' or not input_core.press_key_cleared('ctrl+l'):
        fail('navigation_key')
    _firefox, _document, snapshot = build_snapshot('linkedin')
    address = _exact_address_bar(snapshot)
    if address is None or 'focused' not in address.states:
        fail('address_bar_focus')
    if not _select_full_address_text(snapshot):
        fail('selection_action')
    _firefox, _document, snapshot = build_snapshot('linkedin')
    if not _full_address_selection_proven(snapshot):
        fail('selection_proof')
    if not input_core.clipboard_paste(return_url):
        fail('paste')
    _firefox, _document, snapshot = build_snapshot('linkedin')
    address = _exact_address_bar(snapshot)
    if address is None or 'focused' not in address.states or str(address.text or '') != return_url:
        fail('pasted_text_proof')
    if restore.get('submit_key') != 'Return' or not input_core.press_key_cleared('Return'):
        fail('submit')
    required, interval, timeout = _barrier_settings(
        restore,
        'exact_return_route_and_current_notifications_state',
    )
    receipt['stable_cycles_required'] = required
    barrier_deadline = min(deadline_at, time.monotonic() + timeout)
    prior: str | None = None
    cycles = 0
    while time.monotonic() < barrier_deadline:
        _firefox, _document, snapshot = build_snapshot('linkedin')
        restored = observe_engagement_restore(snapshot, return_url)
        digest = restored['notifications_target_state_digest']
        exact = (
            restored['route_exact'] is True
            and restored['route_kind_exact'] is True
            and restored['notifications_target_match_count'] == 1
            and isinstance(digest, str)
        )
        cycles = cycles + 1 if exact and digest == prior else (1 if exact else 0)
        prior = digest if exact else None
        receipt['stable_cycles_observed'] = cycles
        if cycles >= required:
            receipt['verdict'] = 'satisfied'
            return receipt
        time.sleep(interval)
    fail('return_postcondition')
    raise AssertionError('unreachable')
