#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.ats.read_only import AtsReadOnlyError, observe_read_only_form  # noqa: E402
from consultation_v2.supervised_ui_contract import canonical_json_bytes  # noqa: E402


def _lease_secret() -> bytes:
    raw = str(os.environ.get('ATS_READ_ONLY_LEASE_SECRET') or '').strip()
    if len(raw) != 64:
        raise AtsReadOnlyError('ATS_READ_ONLY_LEASE_SECRET must be exactly 64 lowercase hex characters')
    try:
        secret = bytes.fromhex(raw)
    except ValueError as exc:
        raise AtsReadOnlyError('ATS_READ_ONLY_LEASE_SECRET must be lowercase hexadecimal') from exc
    if raw != raw.lower():
        raise AtsReadOnlyError('ATS_READ_ONLY_LEASE_SECRET must be lowercase hexadecimal')
    return secret


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Observe one exact ATS form without fill, upload, submit, or database access.',
    )
    parser.add_argument('--provider', choices=('greenhouse',), required=True)
    args = parser.parse_args()
    try:
        result = observe_read_only_form(args.provider, _lease_secret())
    except AtsReadOnlyError as exc:
        failure = {
            'schema': 'ats_read_only_qualification_result_v1',
            'ok': False,
            'provider': args.provider,
            'state': 'terminal_read_only_halt',
            'error': str(exc),
            'next_mutation_authorized': False,
        }
        sys.stdout.buffer.write(canonical_json_bytes(failure) + b'\n')
        return 1
    sys.stdout.buffer.write(canonical_json_bytes(result) + b'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
