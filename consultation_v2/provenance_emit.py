"""Emit successful consultation captures to the provenance ledger ingress."""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from consultation_v2 import storage_policy
from consultation_v2.types import ConsultationRequest, ConsultationResult

logger = logging.getLogger(__name__)

_EMIT_ENABLED_ENV = 'TAEY_CONSULT_EVENT_EMIT_ENABLED'
_ORCHESTRATOR_BASE_URL_ENV = 'TAEY_ORCHESTRATOR_BASE_URL'
_CONSULT_EVENT_PATH = '/api/provenance/consult-event'
_EMIT_TIMEOUT_SECONDS = 5.0
_TRUE_VALUES = {'1', 'true', 'yes', 'on', 'enabled'}
_FALSE_VALUES = {'0', 'false', 'no', 'off', 'disabled'}
_PLATFORM_SEAT_ROLES = {
    'chatgpt': 'horizon',
    'claude': 'gaia',
    'gemini': 'cosmos',
    'grok': 'logos',
    'perplexity': 'clarity',
}
_RECEIPT_FIELDS = ('event_id', 'attestation_id', 'row_hash')


class ProvenanceEmitConfigError(RuntimeError):
    """Provenance emission configuration is missing or malformed."""


class ProvenanceEmitResponseError(RuntimeError):
    """The provenance ingress returned an invalid success response."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _sha256_oid(content: bytes) -> str:
    return f'sha256:{hashlib.sha256(content).hexdigest()}'


def _emit_enabled() -> bool:
    raw = storage_policy.env_or_machine(_EMIT_ENABLED_ENV)
    if not raw:
        return False
    normalized = raw.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ProvenanceEmitConfigError(
        f'{_EMIT_ENABLED_ENV} must be one of '
        f'{sorted(_TRUE_VALUES | _FALSE_VALUES)}; got {raw!r}'
    )


def _consult_event_endpoint() -> str:
    base_url = storage_policy.env_or_machine(_ORCHESTRATOR_BASE_URL_ENV).rstrip('/')
    if not base_url:
        raise ProvenanceEmitConfigError(
            f'{_ORCHESTRATOR_BASE_URL_ENV} is required when '
            f'{_EMIT_ENABLED_ENV}=1'
        )
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProvenanceEmitConfigError(
            f'{_ORCHESTRATOR_BASE_URL_ENV} must be an absolute HTTP(S) base URL '
            'without credentials, query, or fragment'
        )
    return f'{base_url}{_CONSULT_EVENT_PATH}'


def _request_oid(
    caller_request: ConsultationRequest,
    rendered_request: ConsultationRequest,
) -> str:
    attachment_hashes = [
        f'sha256:{item.sha256}'
        for item in rendered_request.caller_attachment_provenance
    ]
    canonical_request = {
        'attachment_content_hashes': attachment_hashes,
        'message': caller_request.message,
        'platform': caller_request.platform,
        'requester': caller_request.requester or 'unknown',
    }
    return _sha256_oid(_canonical_json_bytes(canonical_request))


def _consult_event_payload(
    caller_request: ConsultationRequest,
    rendered_request: ConsultationRequest,
    result: ConsultationResult,
) -> dict[str, object]:
    try:
        seat_role = _PLATFORM_SEAT_ROLES[rendered_request.platform]
    except KeyError as exc:
        raise ProvenanceEmitConfigError(
            f'no provenance seat role for platform {rendered_request.platform!r}'
        ) from exc
    return {
        'source_family_id': caller_request.request_id(),
        'request_oid': _request_oid(caller_request, rendered_request),
        'rendered_prompt_oid': _sha256_oid(
            rendered_request.message.encode('utf-8')
        ),
        'response_oid': _sha256_oid(result.response_text.encode('utf-8')),
        'platform': rendered_request.platform,
        'seat_role': seat_role,
        'requester': caller_request.requester or 'unknown',
        'session_url': result.session_url_after or rendered_request.session_url or '',
        'parents': [],
    }


def _post_consult_event(endpoint: str, payload: dict[str, object]) -> dict[str, str]:
    request = urllib.request.Request(
        endpoint,
        data=_canonical_json_bytes(payload),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=_EMIT_TIMEOUT_SECONDS) as response:
        response_payload: Any = json.loads(response.read().decode('utf-8'))
    if not isinstance(response_payload, dict):
        raise ProvenanceEmitResponseError(
            'provenance ingress success response must be a JSON object'
        )
    receipt: dict[str, str] = {}
    for field in _RECEIPT_FIELDS:
        value = response_payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProvenanceEmitResponseError(
                f'provenance ingress success response is missing {field!r}'
            )
        receipt[field] = value
    return receipt


def emit_consult_completed(
    *,
    caller_request: ConsultationRequest,
    rendered_request: ConsultationRequest,
    result: ConsultationResult,
) -> dict[str, str] | None:
    if not result.ok or not result.response_text:
        return None
    if not _emit_enabled():
        result.add_step(
            'provenance_emit',
            False,
            'Consult provenance emission is disabled by machine configuration',
            enabled=False,
            skipped=True,
        )
        logger.info('Consult provenance emission disabled by %s', _EMIT_ENABLED_ENV)
        return None

    endpoint = _consult_event_endpoint()
    payload = _consult_event_payload(caller_request, rendered_request, result)
    try:
        receipt = _post_consult_event(endpoint, payload)
    except Exception as exc:
        logger.error('Consult provenance emission failed: %s', exc)
        result.add_step(
            'provenance_emit',
            False,
            'Consult response captured but provenance emission failed',
            error=str(exc),
            request_oid=payload['request_oid'],
        )
        return None

    result.storage['provenance_event'] = dict(receipt)
    result.add_step(
        'provenance_emit',
        True,
        'Consult completion appended to the provenance ledger',
        request_oid=payload['request_oid'],
        receipt=dict(receipt),
    )
    return receipt
