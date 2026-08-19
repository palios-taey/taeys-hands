#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run Taey in the closed full-consult or extraction-only seat.',
    )
    parser.add_argument(
        '--platform',
        required=True,
        choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'],
    )
    parser.add_argument(
        '--display',
        required=True,
        choices=[':2', ':3', ':4', ':5', ':6', ':20', ':21', ':22', ':23', ':24'],
    )
    parser.add_argument('--output', required=True)
    parser.add_argument('--capture-root', default=None)
    parser.add_argument('--endpoint', default=None)
    parser.add_argument('--model', default=None)
    parser.add_argument(
        '--attach',
        action='append',
        default=None,
        help='Absolute attachment path; repeat once for a second ordered attachment.',
    )
    parser.add_argument('--prompt', default=None)
    parser.add_argument(
        '--completion-timeout',
        type=float,
        default=3600.0,
    )
    parser.add_argument(
        '--lock-policy',
        choices=['careers', 'discretionary'],
        default='discretionary',
    )
    return parser


def _bind_display(display: str) -> None:
    bus_path = Path(f'/tmp/a11y_bus_{display}')
    bus = bus_path.read_text(encoding='utf-8').strip()
    if not bus:
        raise RuntimeError(f'AT-SPI bus file is empty: {bus_path}')
    os.environ['DISPLAY'] = display
    os.environ['AT_SPI_BUS_ADDRESS'] = bus


def _request_id(args: argparse.Namespace, output: Path) -> str:
    record = {
        'entrypoint': 'scripts/run_taey_consult_extract.py',
        'platform': args.platform,
        'display': args.display,
        'output': str(output),
        'attachments': (
            [str(Path(value).expanduser().resolve()) for value in args.attach]
            if args.attach is not None else []
        ),
        'prompt_sha256': (
            hashlib.sha256(args.prompt.encode('utf-8')).hexdigest()
            if args.prompt is not None else None
        ),
    }
    encoded = json.dumps(record, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:32]


def _exit_on_sigterm(signum, _frame) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise SystemExit(128 + int(signum))


def main() -> int:
    args = build_parser().parse_args()
    if (args.attach is None) != (args.prompt is None):
        raise RuntimeError('--attach and --prompt must be supplied together')
    if args.attach is not None and len(args.attach) > 2:
        raise RuntimeError('--attach may be supplied at most twice')
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise RuntimeError(f'refusing to overwrite existing output: {output}')
    _bind_display(args.display)
    from consultation_v2.display_lock import (
        display_lock_ttl,
        entrypoint_display_lock,
    )
    from consultation_v2.taey_extract import consult_with_taey, extract_with_taey

    common = {
        'platform': args.platform,
        'display': args.display,
        'endpoint': args.endpoint,
        'model': args.model,
        'capture_root': args.capture_root,
    }
    request_id = _request_id(args, output)
    with entrypoint_display_lock(
        display=args.display,
        policy=args.lock_policy,
        request_id=request_id,
        entrypoint='scripts/run_taey_consult_extract.py',
        payload={
            'platform': args.platform,
            'output': str(output),
            'seat_mode': 'full_consult' if args.attach is not None else 'extraction',
        },
        ttl=display_lock_ttl(args.completion_timeout),
    ):
        if args.attach is not None:
            result = consult_with_taey(
                **common,
                attachment_paths=args.attach,
                framing_prompt=args.prompt,
                completion_timeout=args.completion_timeout,
            )
        else:
            result = extract_with_taey(**common)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding='utf-8',
    )
    print(json.dumps({
        'ok': result.get('ok'),
        'body_characters': result.get('body_characters'),
        'source_count': result.get('source_count'),
        'expected_source_count': result.get('expected_source_count'),
        'missing_source_ids': result.get('missing_source_ids'),
        'consultation': result.get('consultation'),
        'output': str(output),
        'capture_root': result.get('capture_root'),
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    raise SystemExit(main())
