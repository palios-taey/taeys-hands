from __future__ import annotations

import argparse
import json
from pathlib import Path

from consultation_v2.orchestrator import run_consultation
from consultation_v2.planner import SelectionPlanError, has_selection_menus, selection_menus
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
    parser.add_argument('--no-neo4j', action='store_true')
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        selections = parse_select_args(args.platform, list(args.select or []))
    except ValueError as exc:
        parser.error(str(exc))
    request = ConsultationRequest(
        platform=args.platform,
        message=args.message,
        attachments=list(args.attach or []),
        selections=selections,
        session_url=args.session_url,
        timeout=args.timeout,
        output_path=args.output,
        no_neo4j=args.no_neo4j,
        session_type=args.session_type,
        purpose=args.purpose,
        requester=args.requester,
    )
    result = run_consultation(request)
    payload = result.serializable()
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
