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
from consultation_v2.types import ElementRef, Snapshot


class LinkedInSelectedJobUnavailable(RuntimeError):
    def __init__(self, message: str, match_counts: Mapping[str, int]) -> None:
        super().__init__(message)
        self.match_counts = dict(match_counts)


@dataclass(frozen=True, slots=True)
class SelectedJobObservation:
    record: Mapping[str, Any]
    content_digest: str
    match_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SinkWriteResult:
    records_written: int
    artifact_sha256: str


_REQUIRED_KEYS = (
    'active_job_details_jump',
    'about_job_heading',
    'selected_job_article',
)


def _exact_elements(snapshot: Snapshot) -> tuple[dict[str, ElementRef], dict[str, int]]:
    match_counts = {
        key: len(snapshot.mapped.get(key) or [])
        for key in _REQUIRED_KEYS
    }
    if any(count != 1 for count in match_counts.values()):
        raise LinkedInSelectedJobUnavailable(
            'selected-job mapping requires exactly one match per key',
            match_counts,
        )
    return {
        key: snapshot.mapped[key][0]
        for key in _REQUIRED_KEYS
    }, match_counts


def observe_selected_job(snapshot: Snapshot, search_ref: str) -> SelectedJobObservation:
    if snapshot.platform != 'linkedin':
        raise LinkedInSelectedJobUnavailable(
            'snapshot platform is not linkedin',
            {key: 0 for key in _REQUIRED_KEYS},
        )
    elements, match_counts = _exact_elements(snapshot)
    heading = elements['about_job_heading']
    article = elements['selected_job_article']
    source_url = str(snapshot.url or '').strip()
    detail_text = str(article.text or article.name or '').strip()
    if not source_url or not detail_text or heading.name != 'About the job':
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
