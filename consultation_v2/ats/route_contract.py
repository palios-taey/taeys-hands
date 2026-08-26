from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

from .provider_contract import ProviderSpec


_TYPE_PATTERNS = {
    'base64url': re.compile(r'[A-Za-z0-9_-]+={0,2}\Z'),
    'integer': re.compile(r'[0-9]+\Z'),
    'locale': re.compile(r'[a-z]{2}-[A-Z]{2}\Z'),
    'slug': re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z'),
    'token': re.compile(r'[A-Za-z0-9][A-Za-z0-9._~-]*\Z'),
    'uuid': re.compile(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-'
        r'[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z'
    ),
    'workday_job': re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z'),
    'workday_text': re.compile(r'[A-Za-z0-9][A-Za-z0-9._~-]*\Z'),
}


class RouteContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RouteMatch:
    provider: str
    grammar_id: str
    application_identity_sha256: str
    host: str


def _typed_value(value: str, capture_type: str) -> str | None:
    pattern = _TYPE_PATTERNS[capture_type]
    if not value or '/' in value or '\x00' in value or not pattern.fullmatch(value):
        return None
    return value.casefold() if capture_type == 'uuid' else value


def _bind(captures: dict[str, str], key: str, value: str) -> bool:
    existing = captures.get(key)
    if existing is not None and existing != value:
        return False
    captures[key] = value
    return True


def _host_allowed(route: Mapping[str, Any], host: str) -> bool:
    exact_hosts = set(route['exact_hosts'])
    if host in exact_hosts:
        return True
    return any(host.endswith(suffix) and host != suffix[1:] for suffix in route['suffix_hosts'])


def _match_grammar(
    grammar: Mapping[str, Any],
    path_segments: list[str],
    query_pairs: list[tuple[str, str]],
) -> dict[str, str] | None:
    path = grammar['path']
    if len(path) != len(path_segments):
        return None
    captures: dict[str, str] = {}
    for part, segment in zip(path, path_segments, strict=True):
        if 'literal' in part:
            if segment != part['literal']:
                return None
            continue
        typed = _typed_value(segment, part['type'])
        if typed is None or not _bind(captures, part['capture'], typed):
            return None
    query = grammar['query']
    if len(query) != len(query_pairs):
        return None
    query_values: dict[str, str] = {}
    for key, value in query_pairs:
        if key in query_values:
            return None
        query_values[key] = value
    if set(query_values) != {item['key'] for item in query}:
        return None
    for item in query:
        typed = _typed_value(query_values[item['key']], item['type'])
        if typed is None or not _bind(captures, item['capture'], typed):
            return None
    return captures


def match_provider_route(spec: ProviderSpec, url: str) -> RouteMatch:
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise RouteContractError('ATS route URL is absent or oversized')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').casefold()
        port = parsed.port
    except ValueError as exc:
        raise RouteContractError('ATS URL authority is malformed') from exc
    route = spec.document['route']
    if (
        parsed.scheme != route['scheme']
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
        or not _host_allowed(route, host)
    ):
        raise RouteContractError('ATS URL is outside the exact provider route')
    encoded_segments = [segment for segment in parsed.path.split('/') if segment]
    path_segments: list[str] = []
    for encoded in encoded_segments:
        decoded = unquote(encoded)
        if not decoded or '/' in decoded or '\x00' in decoded:
            raise RouteContractError('ATS URL contains an invalid path segment')
        path_segments.append(decoded)
    try:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise RouteContractError('ATS URL query is malformed') from exc
    matches: list[tuple[str, dict[str, str]]] = []
    for grammar in route['grammars']:
        captures = _match_grammar(grammar, path_segments, query_pairs)
        if captures is not None:
            matches.append((grammar['id'], captures))
    if len(matches) != 1:
        raise RouteContractError(f'ATS URL matched {len(matches)} provider route grammars')
    grammar_id, captures = matches[0]
    identity: dict[str, str] = {}
    for field in route['identity_fields']:
        if field == 'host':
            identity[field] = host
        elif field in captures:
            identity[field] = captures[field]
        else:
            raise RouteContractError(f'ATS route did not bind identity field {field!r}')
    canonical = json.dumps(
        {'provider': spec.provider, 'identity': identity},
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('ascii')
    return RouteMatch(
        provider=spec.provider,
        grammar_id=grammar_id,
        application_identity_sha256=hashlib.sha256(canonical).hexdigest(),
        host=host,
    )
