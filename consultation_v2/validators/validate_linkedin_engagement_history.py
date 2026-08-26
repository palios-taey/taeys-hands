#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

PROD2_RECEIPT_SHA256 = (
    'aa98208e4adc6d2e2be48f65fd0ac8ccb5fe2ffba9bc036d49052cfc6f59213f'
)
V1_SCHEMA = (
    REPO_ROOT
    / 'consultation_v2/platforms/linkedin/engagement-receipt.schema.json'
)


def _strict_object(raw_bytes: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f'duplicate receipt field: {key}')
            value[key] = item
        return value

    value = json.loads(
        raw_bytes.decode('utf-8'),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f'non-JSON receipt constant: {token}')
        ),
    )
    if not isinstance(value, dict):
        raise ValueError('historical receipt must be an object')
    return value


def validate_prod2(path: Path) -> None:
    from consultation_v2.linkedin_jobs_contract import read_owned_private_bytes

    raw_bytes = read_owned_private_bytes(path, 'historical prod2 receipt')
    if hashlib.sha256(raw_bytes).hexdigest() != PROD2_RECEIPT_SHA256:
        raise ValueError('historical prod2 receipt digest is not exact')
    receipt = _strict_object(raw_bytes)
    schema = json.loads(V1_SCHEMA.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(receipt),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise ValueError(f'historical prod2 receipt fails v1 schema: {errors[0].message}')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Validate the exact private LinkedIn prod2 receipt against v1.',
    )
    parser.add_argument('--prod2-receipt', required=True, type=Path)
    args = parser.parse_args()
    try:
        validate_prod2(args.prod2_receipt)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f'LinkedIn prod2 historical receipt: FAIL: {exc}', file=sys.stderr)
        return 1
    print(f'LinkedIn prod2 historical receipt: PASS {PROD2_RECEIPT_SHA256}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
