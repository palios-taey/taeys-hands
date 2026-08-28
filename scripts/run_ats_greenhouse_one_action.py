#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.ats.greenhouse_one_action import (  # noqa: E402
    GreenhouseOneActionError,
    execute_frozen_action_fd,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Execute exactly one frozen Greenhouse ATS action.',
    )
    parser.add_argument('--transaction-fd', required=True, type=int)
    parser.add_argument('--expected-transaction-sha256', required=True)
    args = parser.parse_args()
    try:
        result = execute_frozen_action_fd(
            args.transaction_fd,
            args.expected_transaction_sha256,
        )
    except GreenhouseOneActionError as exc:
        result = {
            'schema': 'ats_greenhouse_one_action_refusal_v1',
            'ok': False,
            'state': 'refused_before_receipt_binding',
            'stop_code': exc.code,
            'stop_reason': exc.reason,
            'next_mutation_authorized': False,
        }
    except Exception as exc:
        result = {
            'schema': 'ats_greenhouse_one_action_refusal_v1',
            'ok': False,
            'state': 'refused_before_receipt_binding',
            'stop_code': 'policy_or_authority_boundary',
            'stop_reason': f'runner boundary failure: {type(exc).__name__}',
            'next_mutation_authorized': False,
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + '\n')
    return 0 if result.get('ok') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
