from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from consultation_v2.linkedin_jobs_contract import (
    SELECTED_JOB_SCHEMA,
    canonical_json_bytes,
    read_owned_private_bytes,
    sha256_hex,
    write_new_private_json,
)
from consultation_v2.interact import atspi_activate
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
    pass


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
    if not atspi_activate({
        'atspi_obj': target.atspi_obj,
        'name': target.name,
        'role': target.role,
    }):
        raise LinkedInJobCardActionFailed('LinkedIn exact job-card activation failed')
    return JobSelectionObservation(
        target_match_count=target_count,
        detail_title_match_count=0,
        detail_company_match_count=0,
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
