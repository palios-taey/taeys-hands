from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from consultation_v2.linkedin_job_search_contract import (
    SEARCH_BATCH_SCHEMA,
    canonical_json_bytes,
    sha256_hex,
)
from consultation_v2.linkedin_jobs_contract import (
    read_owned_private_bytes,
    write_new_private_json,
)
from consultation_v2.types import ElementRef, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


class LinkedInMountedJobSearchUnavailable(RuntimeError):
    def __init__(self, message: str, match_counts: Mapping[str, int]) -> None:
        super().__init__(message)
        self.match_counts = dict(match_counts)


@dataclass(frozen=True, slots=True)
class MountedJobSearchObservation:
    record: Mapping[str, Any]
    content_digest: str
    card_count: int
    match_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SearchSinkWriteResult:
    batches_written: int
    artifact_sha256: str


def _workflow() -> dict[str, Any]:
    workflow = load_platform_yaml('linkedin').get('workflow') or {}
    contract = workflow.get('mounted_job_search_read')
    if not isinstance(contract, dict):
        raise RuntimeError('LinkedIn mounted job-search read is not configured')
    return dict(contract)


def observation_barrier_policy() -> tuple[int, float, float]:
    barrier = _workflow().get('observation_barrier')
    if not isinstance(barrier, dict):
        raise RuntimeError('LinkedIn mounted job-search barrier is unavailable')
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
        raise RuntimeError('LinkedIn mounted job-search barrier is invalid')
    return stable_cycles, interval_ms / 1000.0, timeout_ms / 1000.0


def _all_elements(snapshot: Snapshot) -> list[ElementRef]:
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
    unique: list[ElementRef] = []
    seen: set[int] = set()
    for element in elements:
        identity = id(element.atspi_obj)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(element)
    return unique


def _text(node: Any, context: str) -> str:
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi

        text_iface = node.get_text_iface()
        if text_iface is None:
            raise RuntimeError(f'{context} has no AT-SPI Text interface')
        character_count = int(Atspi.Text.get_character_count(text_iface))
        value = str(Atspi.Text.get_text(text_iface, 0, character_count) or '').strip()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'cannot read {context} AT-SPI Text interface') from exc
    if not value:
        raise RuntimeError(f'{context} AT-SPI Text is empty')
    return value


def _route_matches(snapshot: Snapshot, route: Mapping[str, Any]) -> bool:
    parsed = urlsplit(str(snapshot.url or '').strip())
    normalized_path = parsed.path.rstrip('/') or '/'
    return (
        parsed.scheme == route.get('scheme')
        and parsed.hostname == route.get('host')
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and normalized_path == route.get('normalized_path')
        and not parsed.fragment
    )


def _direct_child(node: Any, index: int, role: str, context: str) -> Any:
    try:
        child_count = int(node.get_child_count())
        child = node.get_child_at_index(index) if index < child_count else None
        child_role = str(child.get_role_name() or '') if child is not None else ''
    except Exception as exc:
        raise RuntimeError(f'cannot inspect {context} child') from exc
    if child is None or child_role != role:
        raise RuntimeError(f'{context} child role differs from YAML')
    return child


def _action_names(node: Any) -> list[str]:
    try:
        action_iface = node.get_action_iface()
        action_count = int(action_iface.get_n_actions()) if action_iface is not None else 0
        return [
            str(action_iface.get_action_name(index) or '')
            for index in range(action_count)
        ]
    except Exception as exc:
        raise RuntimeError('cannot inspect mounted job-card Action interface') from exc


def _card_record(element: ElementRef, ordinal: int, contract: Mapping[str, Any]) -> dict[str, Any]:
    node = element.atspi_obj
    if node is None:
        raise RuntimeError('mounted job card has no AT-SPI object')
    title_contract = contract.get('title')
    company_contract = contract.get('company')
    location_contract = contract.get('location')
    if not all(isinstance(item, dict) for item in (title_contract, company_contract, location_contract)):
        raise RuntimeError('mounted job-card field contracts are invalid')
    title_node = _direct_child(
        node,
        int(title_contract['child_index']),
        str(title_contract['role']),
        'job title',
    )
    try:
        title_source = str(title_node.get_name() or '')
    except Exception as exc:
        raise RuntimeError('cannot read mounted job title source') from exc
    prefix = title_contract.get('exact_prefix')
    suffix = title_contract.get('exact_suffix')
    if (
        not isinstance(prefix, str)
        or not isinstance(suffix, str)
        or not title_source.startswith(prefix)
        or not title_source.endswith(suffix)
        or len(title_source) <= len(prefix) + len(suffix)
    ):
        raise RuntimeError('mounted job title source differs from YAML')
    title = title_source[len(prefix):len(title_source) - len(suffix)]
    company_node = _direct_child(
        node,
        int(company_contract['child_index']),
        str(company_contract['role']),
        'job company',
    )
    location_node = _direct_child(
        node,
        int(location_contract['child_index']),
        str(location_contract['role']),
        'job location',
    )
    card = {
        'ordinal': ordinal,
        'target_card_name': element.name,
        'detail_title_name': title,
        'detail_company_name': _text(company_node, 'job company'),
        'location_text': _text(location_node, 'job location'),
        'showing': 'showing' in element.states,
    }
    return {
        **card,
        'card_digest': sha256_hex(canonical_json_bytes(card)),
    }


def observe_mounted_job_search(
    snapshot: Snapshot,
    search_ref: str,
) -> MountedJobSearchObservation:
    if snapshot.platform != 'linkedin':
        raise LinkedInMountedJobSearchUnavailable(
            'snapshot platform is not linkedin',
            {'structural_candidates': 0, 'valid_cards': 0, 'duplicate_cards': 0},
        )
    workflow = _workflow()
    route = workflow.get('route')
    card_contract = workflow.get('card')
    if not isinstance(route, dict) or not isinstance(card_contract, dict):
        raise RuntimeError('LinkedIn mounted job-search contract is invalid')
    if not _route_matches(snapshot, route):
        raise LinkedInMountedJobSearchUnavailable(
            'LinkedIn mounted job-search route is not exact',
            {'structural_candidates': 0, 'valid_cards': 0, 'duplicate_cards': 0},
        )
    role = card_contract.get('role')
    states = card_contract.get('states_include')
    action_names = card_contract.get('action_names_exact')
    child_prefix = card_contract.get('direct_child_roles_prefix')
    minimum_children = card_contract.get('minimum_direct_children')
    if (
        not isinstance(role, str)
        or not isinstance(states, list)
        or not isinstance(action_names, list)
        or not isinstance(child_prefix, list)
        or isinstance(minimum_children, bool)
        or not isinstance(minimum_children, int)
        or minimum_children < len(child_prefix)
    ):
        raise RuntimeError('LinkedIn mounted job-card projection is invalid')
    structural: list[ElementRef] = []
    for element in _all_elements(snapshot):
        if (
            element.role != role
            or not set(states).issubset(element.states)
            or _action_names(element.atspi_obj) != action_names
        ):
            continue
        try:
            child_count = int(element.atspi_obj.get_child_count())
            direct_roles = [
                str(element.atspi_obj.get_child_at_index(index).get_role_name() or '')
                for index in range(min(child_count, len(child_prefix)))
            ]
        except Exception as exc:
            raise RuntimeError('cannot inspect mounted job-card structure') from exc
        if child_count >= minimum_children and direct_roles == child_prefix:
            structural.append(element)
    records = [
        _card_record(element, ordinal, card_contract)
        for ordinal, element in enumerate(structural)
    ]
    card_digests = [str(record['card_digest']) for record in records]
    duplicate_count = len(card_digests) - len(set(card_digests))
    match_counts = {
        'structural_candidates': len(structural),
        'valid_cards': len(records),
        'duplicate_cards': duplicate_count,
    }
    if duplicate_count:
        raise LinkedInMountedJobSearchUnavailable(
            'LinkedIn mounted job-search cards are not unique',
            match_counts,
        )
    source_url = str(snapshot.url or '').strip()
    record = {
        'schema': SEARCH_BATCH_SCHEMA,
        'search_ref': search_ref,
        'source_url': source_url,
        'cards': records,
    }
    return MountedJobSearchObservation(
        record=record,
        content_digest=sha256_hex(canonical_json_bytes(record)),
        card_count=len(records),
        match_counts=match_counts,
    )


def write_mounted_job_search_once(
    observation: MountedJobSearchObservation,
    sink_root: Path,
) -> SearchSinkWriteResult:
    artifact = sink_root / f'linkedin-job-search-{observation.content_digest}.json'
    if artifact.exists():
        raw_bytes = read_owned_private_bytes(artifact, 'mounted job-search artifact')
        if sha256_hex(raw_bytes) != observation.content_digest:
            raise RuntimeError('existing mounted job-search artifact digest mismatch')
        return SearchSinkWriteResult(
            batches_written=0,
            artifact_sha256=observation.content_digest,
        )
    raw_bytes = write_new_private_json(artifact, observation.record)
    artifact_sha256 = sha256_hex(raw_bytes)
    if artifact_sha256 != observation.content_digest:
        raise RuntimeError('mounted job-search sink readback digest mismatch')
    if sha256_hex(
        read_owned_private_bytes(artifact, 'mounted job-search artifact')
    ) != artifact_sha256:
        raise RuntimeError('mounted job-search sink readback changed after write')
    return SearchSinkWriteResult(batches_written=1, artifact_sha256=artifact_sha256)


def mounted_job_search_postcondition(
    before: MountedJobSearchObservation,
    after: MountedJobSearchObservation,
) -> bool:
    return (
        before.content_digest == after.content_digest
        and before.card_count == after.card_count
        and dict(before.match_counts) == dict(after.match_counts)
    )
