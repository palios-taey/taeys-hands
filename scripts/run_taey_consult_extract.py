#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run Taey in the closed consult-extraction seat.',
    )
    parser.add_argument('--platform', required=True, choices=['perplexity'])
    parser.add_argument(
        '--display',
        required=True,
        choices=[':2', ':3', ':4', ':5', ':6'],
    )
    parser.add_argument('--output', required=True)
    parser.add_argument('--capture-root', default=None)
    parser.add_argument('--endpoint', default=None)
    parser.add_argument('--model', default=None)
    return parser


def _bind_display(display: str) -> None:
    bus_path = Path(f'/tmp/a11y_bus_{display}')
    bus = bus_path.read_text(encoding='utf-8').strip()
    if not bus:
        raise RuntimeError(f'AT-SPI bus file is empty: {bus_path}')
    os.environ['DISPLAY'] = display
    os.environ['AT_SPI_BUS_ADDRESS'] = bus


def main() -> int:
    args = build_parser().parse_args()
    _bind_display(args.display)
    from consultation_v2.taey_extract import extract_with_taey

    result = extract_with_taey(
        platform=args.platform,
        display=args.display,
        endpoint=args.endpoint,
        model=args.model,
        capture_root=args.capture_root,
    )
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise RuntimeError(f'refusing to overwrite existing output: {output}')
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
        'output': str(output),
        'capture_root': result.get('capture_root'),
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
