from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from consultation_v2.identity import (
    IdentityError,
    consolidate_attachments,
    validate_caller_attachments,
)
from consultation_v2.orchestrator import _prepare_platform_identity_request, run_consultation
from consultation_v2.planner import (
    SelectionPlanError,
    build_selection_plan,
    has_selection_menus,
    selection_menus,
    selection_plan_record,
)
from consultation_v2 import storage_policy
from consultation_v2.types import Choice, ConsultationRequest


LEGACY_MULTI_SELECTIONS = frozenset({'tools', 'connectors'})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run the isolated Consultation V2 workflow.')
    parser.add_argument('--platform', required=True, choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'])
    parser.add_argument('--message', required=True)
    parser.add_argument('--attach', action='append', default=[])
    parser.add_argument(
        '--select',
        action='append',
        default=[],
        metavar='MENU=OPTION',
        help='Repeatable selection, e.g. --select model=pro_extended, --select model=default:"because", or --select tools=none:"because"',
    )
    parser.add_argument('--session-url', default=None)
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default=None)
    parser.add_argument(
        '--store',
        action='store_true',
        help='Opt in to external Neo4j/ISMA storage for this run. Default is local delivery only.',
    )
    parser.add_argument(
        '--no-neo4j',
        action='store_true',
        help='Legacy explicit external-store disable; external storage is disabled by default.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate and print the resolved request/selection plan without browser contact.',
    )
    parser.add_argument(
        '--no-identity',
        action='store_true',
        help='Attach only caller-provided files; do not prepend FAMILY_KERNEL or platform IDENTITY.',
    )
    parser.add_argument('--session-type', default=None)
    parser.add_argument('--purpose', default=None)
    parser.add_argument('--requester', default=None,
                        help='Node ID of the requester (for notifications)')
    return parser


def _strip_cli_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_select_args(platform: str, raw_selections: list[str]) -> dict[str, Choice]:
    if not has_selection_menus(platform):
        return _parse_unplanned_select_args(raw_selections)
    try:
        menus = selection_menus(platform)
    except SelectionPlanError as exc:
        raise ValueError(str(exc)) from exc
    parsed: dict[str, Choice] = {}
    for raw in raw_selections:
        if '=' not in raw:
            raise ValueError(f'--select must use MENU=OPTION syntax: {raw!r}')
        menu_key, raw_value = raw.split('=', 1)
        menu_key = menu_key.strip()
        raw_value = raw_value.strip()
        if not menu_key or not raw_value:
            raise ValueError(f'--select must use non-empty MENU=OPTION syntax: {raw!r}')
        because = ''
        value = raw_value
        for sentinel in ('default', 'none'):
            prefix = f'{sentinel}:'
            if raw_value.startswith(prefix):
                value = sentinel
                because = _strip_cli_quotes(raw_value[len(prefix):])
                break
        menu = menus.get(menu_key)
        if not isinstance(menu, dict):
            parsed[menu_key] = Choice(value=value, because=because)
            continue
        if menu.get('select') == 'multi' and value not in {'default', 'none'}:
            existing = parsed.get(menu_key)
            values = []
            if existing is not None:
                if isinstance(existing.value, list):
                    values.extend(existing.value)
                else:
                    raise ValueError(f'--select {menu_key}=... cannot mix scalar and multi values')
            values.append(value)
            parsed[menu_key] = Choice(value=values, because=because or (existing.because if existing else ''))
        else:
            if menu_key in parsed:
                raise ValueError(f'--select {menu_key}=... was provided more than once for a scalar selection')
            parsed[menu_key] = Choice(value=value, because=because)
    return parsed


def _parse_unplanned_select_args(raw_selections: list[str]) -> dict[str, Choice]:
    parsed: dict[str, Choice] = {}
    for raw in raw_selections:
        if '=' not in raw:
            raise ValueError(f'--select must use MENU=OPTION syntax: {raw!r}')
        menu_key, raw_value = raw.split('=', 1)
        menu_key = menu_key.strip()
        raw_value = raw_value.strip()
        if not menu_key or not raw_value:
            raise ValueError(f'--select must use non-empty MENU=OPTION syntax: {raw!r}')
        if menu_key in LEGACY_MULTI_SELECTIONS:
            existing = parsed.get(menu_key)
            values = list(existing.value) if existing and isinstance(existing.value, list) else []
            values.append(raw_value)
            parsed[menu_key] = Choice(value=values)
            continue
        if menu_key in parsed:
            raise ValueError(f'--select {menu_key}=... was provided more than once for a scalar selection')
        parsed[menu_key] = Choice(value=raw_value)
    return parsed


def _resolve_identity_for_dry_run(
    request: ConsultationRequest,
) -> tuple[ConsultationRequest, dict[str, Any]]:
    caller_attachments = list(request.attachments)
    if request.no_identity:
        if not caller_attachments:
            raise IdentityError(
                '--no-identity requires at least one --attach file; refusing to '
                'send an empty packet without FAMILY_KERNEL/IDENTITY overlay.'
            )
        provenance = validate_caller_attachments(caller_attachments)
        return (
            replace(
                request,
                attachments=caller_attachments,
                caller_attachment_provenance=provenance,
            ),
            {
                'mode': 'caller_only',
                'package_paths': [],
                'caller_attachment_provenance': [
                    item.serializable() for item in provenance
                ],
            },
        )

    prepared_identity = _prepare_platform_identity_request(request, caller_attachments)
    if prepared_identity is not None:
        return prepared_identity

    package = consolidate_attachments(
        platform=request.platform,
        caller_attachments=caller_attachments,
    )
    package_paths = package.attachment_paths()
    provenance = list(package.caller_provenance)
    return (
        replace(
            request,
            attachments=package_paths,
            caller_attachment_provenance=provenance,
        ),
        {
            'mode': 'identity_consolidated',
            'package_paths': package_paths,
            'caller_attachment_provenance': [
                item.serializable() for item in provenance
            ],
        },
    )


def _dry_run_payload(request: ConsultationRequest) -> dict[str, Any]:
    selection_record = []
    if has_selection_menus(request.platform):
        selection_record = selection_plan_record(build_selection_plan(request))
    resolved_request, identity = _resolve_identity_for_dry_run(request)
    return {
        'dry_run': True,
        'platform_contact': False,
        'would_call_run_consultation': False,
        'request': _request_record(resolved_request),
        'selection_plan': selection_record,
        'identity': identity,
    }


def _request_record(request: ConsultationRequest) -> dict[str, Any]:
    return {
        'platform': request.platform,
        'message': request.message,
        'attachments': list(request.attachments),
        'selections': request.serializable_selections(),
        'session_url': request.session_url,
        'timeout': request.timeout,
        'output_path': request.output_path,
        'no_neo4j': request.no_neo4j,
        'store_enabled': request.store_enabled,
        'external_store_enabled': storage_policy.external_store_enabled(request),
        'no_identity': request.no_identity,
        'session_type': request.session_type,
        'purpose': request.purpose,
        'requester': request.requester,
        'request_id': request.request_id(),
        'prompt_hash': request.prompt_hash(),
        'caller_attachment_provenance': [
            item.serializable() for item in request.caller_attachment_provenance
        ],
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        selections = parse_select_args(args.platform, list(args.select or []))
    except ValueError as exc:
        parser.error(str(exc))
    if args.no_identity and not args.attach:
        parser.error('--no-identity requires at least one --attach file')
    request = ConsultationRequest(
        platform=args.platform,
        message=args.message,
        attachments=list(args.attach or []),
        selections=selections,
        session_url=args.session_url,
        timeout=args.timeout,
        output_path=args.output,
        no_neo4j=args.no_neo4j,
        store_enabled=args.store,
        no_identity=args.no_identity,
        session_type=args.session_type,
        purpose=args.purpose,
        requester=args.requester,
    )
    if args.dry_run:
        try:
            payload = _dry_run_payload(request)
        except (IdentityError, SelectionPlanError, ValueError) as exc:
            parser.error(str(exc))
        if args.output:
            Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    result = run_consultation(request)
    payload = result.serializable()
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
