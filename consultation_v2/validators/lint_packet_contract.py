#!/usr/bin/env python3
"""Mechanical PACKET_CONTRACT gate for dry-run / built consultation packets.

Asserts the production builder emitted exactly Bundle A + Bundle B (no
one-package fallback): two non-empty attachments, contract basenames, Bundle A
governance order, Bundle B without governance duplication, and a local receipt
binding both hashes.

USAGE:
    python3 -m consultation_v2.validators.lint_packet_contract <dryrun.json>
    python3 -m consultation_v2.validators.lint_packet_contract \\
        --bundle-a PATH --bundle-b PATH [--receipt PATH] [--platform PLATFORM]

EXIT:
    0 = pass
    1 = fail (violations printed)
    2 = usage / file error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any


BUNDLE_A_RE = re.compile(r'^taey_bundle_a_([a-z]+)_[A-Za-z0-9._-]+\.md$')
BUNDLE_B_RE = re.compile(r'^taey_bundle_b_([a-z]+)_[A-Za-z0-9._-]+\.md$')
ONE_PACKAGE_RE = re.compile(r'taey_package_')

# PACKET_CONTRACT Bundle A order: kernel → destination identity → Spotlight.
GOVERNANCE_ORDER = (
    'FAMILY_KERNEL.md',
    None,  # platform IDENTITY_*.md — checked separately
    'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
)
IDENTITY_BASENAMES = {
    'IDENTITY_HORIZON.md',
    'IDENTITY_GAIA.md',
    'IDENTITY_COSMOS.md',
    'IDENTITY_LOGOS.md',
    'IDENTITY_CLARITY.md',
}
PLATFORM_IDENTITY = {
    'chatgpt': 'IDENTITY_HORIZON.md',
    'claude': 'IDENTITY_GAIA.md',
    'gemini': 'IDENTITY_COSMOS.md',
    'grok': 'IDENTITY_LOGOS.md',
    'perplexity': 'IDENTITY_CLARITY.md',
}


def _sha256_file(path: str) -> tuple[int, str]:
    with open(path, 'rb') as handle:
        data = handle.read()
    return len(data), hashlib.sha256(data).hexdigest()


def _heading_basenames(text: str) -> list[str]:
    """Extract builder section headers, not headings inside fenced source bodies.

    Rendered sections are always:
        ## <logical_name>

        `<logical_name>`
    followed by a fenced body. Naive ``## `` scans falsely match headings inside
    FAMILY_KERNEL / IDENTITY markdown.
    """
    names: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith('## '):
            continue
        name = line[3:].strip()
        # Require the immediate non-empty following line to be the locator.
        for look in range(index + 1, min(index + 4, len(lines))):
            candidate = lines[look].strip()
            if not candidate:
                continue
            if candidate == f'`{name}`':
                names.append(name)
            break
    return names


def _fail(findings: list[str]) -> int:
    for item in findings:
        print(f'FAIL: {item}', file=sys.stderr)
    return 1


def gate_paths(
    bundle_a: str,
    bundle_b: str,
    *,
    receipt: str | None = None,
    platform: str | None = None,
    expect_mode: str | None = None,
) -> list[str]:
    findings: list[str] = []
    for label, path in (('bundle_a', bundle_a), ('bundle_b', bundle_b)):
        if not path or not os.path.isfile(path):
            findings.append(f'{label} missing or not a regular file: {path!r}')
    if findings:
        return findings

    a_base = os.path.basename(bundle_a)
    b_base = os.path.basename(bundle_b)
    if ONE_PACKAGE_RE.search(a_base) or ONE_PACKAGE_RE.search(b_base):
        findings.append(
            f'one-package basename detected ({a_base!r}, {b_base!r}); '
            'PACKET_CONTRACT forbids taey_package_* fallback'
        )
    a_match = BUNDLE_A_RE.match(a_base)
    b_match = BUNDLE_B_RE.match(b_base)
    if not a_match:
        findings.append(f'bundle_a basename not contract-shaped: {a_base!r}')
    if not b_match:
        findings.append(f'bundle_b basename not contract-shaped: {b_base!r}')
    if a_match and b_match and a_match.group(1) != b_match.group(1):
        findings.append(
            f'platform mismatch between basenames: {a_match.group(1)} vs '
            f'{b_match.group(1)}'
        )
    inferred_platform = a_match.group(1) if a_match else platform
    if platform and inferred_platform and platform != inferred_platform:
        findings.append(
            f'--platform {platform!r} disagrees with basename platform '
            f'{inferred_platform!r}'
        )
    platform = platform or inferred_platform

    a_bytes, a_digest = _sha256_file(bundle_a)
    b_bytes, b_digest = _sha256_file(bundle_b)
    if a_bytes == 0:
        findings.append('bundle_a is empty')
    if b_bytes == 0:
        findings.append('bundle_b is empty')

    with open(bundle_a, encoding='utf-8') as handle:
        a_text = handle.read()
    with open(bundle_b, encoding='utf-8') as handle:
        b_text = handle.read()

    a_sections = _heading_basenames(a_text)
    b_sections = _heading_basenames(b_text)

    if len(a_sections) < 3:
        findings.append(
            f'bundle_a has {len(a_sections)} sections; expected >=3 governance '
            f'sources in order, got {a_sections!r}'
        )
    else:
        if a_sections[0] != 'FAMILY_KERNEL.md':
            findings.append(
                f'bundle_a[0] must be FAMILY_KERNEL.md, got {a_sections[0]!r}'
            )
        expected_identity = PLATFORM_IDENTITY.get(platform or '')
        if expected_identity and a_sections[1] != expected_identity:
            findings.append(
                f'bundle_a[1] must be {expected_identity} for platform '
                f'{platform!r}, got {a_sections[1]!r}'
            )
        elif a_sections[1] not in IDENTITY_BASENAMES:
            findings.append(
                f'bundle_a[1] must be a destination IDENTITY_*.md, got '
                f'{a_sections[1]!r}'
            )
        if a_sections[2] != 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md':
            findings.append(
                f'bundle_a[2] must be SPOTLIGHT_STANDARD_FOR_INTEGRITY.md, got '
                f'{a_sections[2]!r}'
            )
        # Bundle A must not contain task/caller artifacts beyond governance.
        extra = [
            name for name in a_sections[3:]
            if name not in (
                'FAMILY_KERNEL.md',
                'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
                *IDENTITY_BASENAMES,
            )
        ]
        if extra:
            findings.append(f'bundle_a contains non-governance sections: {extra!r}')

    # Bundle B must not duplicate governance sources.
    leaked = [
        name for name in b_sections
        if name in IDENTITY_BASENAMES
        or name in {'FAMILY_KERNEL.md', 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md'}
    ]
    if leaked:
        findings.append(f'bundle_b duplicates governance sources: {leaked!r}')
    if 'PROVENANCE_MANIFEST.md' not in b_sections:
        findings.append('bundle_b missing generated PROVENANCE_MANIFEST.md')
    if not any(name not in {'PROVENANCE_MANIFEST.md'} for name in b_sections):
        findings.append('bundle_b has no task source sections')

    if '# Bundle A - Governance' not in a_text and 'Bundle A - Governance' not in a_text:
        findings.append('bundle_a missing Bundle A governance title')
    if '# Bundle B - Task' not in b_text and 'Bundle B - Task' not in b_text:
        findings.append('bundle_b missing Bundle B task title')
    if '# Package for ' in a_text or '# Package for ' in b_text:
        findings.append('legacy one-package "# Package for" title found in a bundle')

    if receipt:
        if not os.path.isfile(receipt):
            findings.append(f'receipt missing: {receipt!r}')
        else:
            with open(receipt, encoding='utf-8') as handle:
                payload: dict[str, Any] = json.load(handle)
            if payload.get('attachment_count') != 2:
                findings.append(
                    f'receipt attachment_count={payload.get("attachment_count")!r} '
                    '!= 2'
                )
            if payload.get('one_package_fallback') is not False:
                findings.append(
                    'receipt one_package_fallback must be false'
                )
            ra = payload.get('bundle_a') or {}
            rb = payload.get('bundle_b') or {}
            if ra.get('sha256') != a_digest:
                findings.append(
                    f'receipt bundle_a.sha256 mismatch: {ra.get("sha256")!r} vs '
                    f'{a_digest!r}'
                )
            if rb.get('sha256') != b_digest:
                findings.append(
                    f'receipt bundle_b.sha256 mismatch: {rb.get("sha256")!r} vs '
                    f'{b_digest!r}'
                )
            if ra.get('bytes') != a_bytes or rb.get('bytes') != b_bytes:
                findings.append('receipt byte counts disagree with re-read bundles')

    if expect_mode and expect_mode != 'packet_contract_two_bundle':
        findings.append(
            f'identity.mode={expect_mode!r}; expected packet_contract_two_bundle'
        )
    return findings


def gate_dryrun(path: str) -> list[str]:
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)
    identity = payload.get('identity') or {}
    request = payload.get('request') or {}
    package_paths = list(identity.get('package_paths') or request.get('attachments') or [])
    findings: list[str] = []
    if len(package_paths) != 2:
        findings.append(
            f'dry-run package_paths count={len(package_paths)} (need exactly 2): '
            f'{package_paths!r}'
        )
        return findings
    if any(ONE_PACKAGE_RE.search(os.path.basename(p) or '') for p in package_paths):
        findings.append(f'one-package path in dry-run attachments: {package_paths!r}')
    mode = identity.get('mode')
    receipt = identity.get('receipt_path')
    platform = request.get('platform')
    findings.extend(
        gate_paths(
            package_paths[0],
            package_paths[1],
            receipt=receipt,
            platform=platform,
            expect_mode=mode,
        )
    )
    message = request.get('message') or ''
    if 'Read both attached files fully before answering' not in message:
        findings.append('brief missing required "Read both attached files..." opener')
    if 'If either attachment is unavailable or incomplete' not in message:
        findings.append('brief missing stop condition for unavailable attachments')
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dryrun', nargs='?', help='Path to consultation dry-run JSON')
    parser.add_argument('--bundle-a', default=None)
    parser.add_argument('--bundle-b', default=None)
    parser.add_argument('--receipt', default=None)
    parser.add_argument('--platform', default=None)
    args = parser.parse_args(argv)

    if args.dryrun:
        if not os.path.isfile(args.dryrun):
            print(f'ERROR: dry-run not found: {args.dryrun}', file=sys.stderr)
            return 2
        findings = gate_dryrun(args.dryrun)
    elif args.bundle_a and args.bundle_b:
        findings = gate_paths(
            args.bundle_a,
            args.bundle_b,
            receipt=args.receipt,
            platform=args.platform,
        )
    else:
        print(
            'ERROR: provide a dry-run JSON path or --bundle-a and --bundle-b',
            file=sys.stderr,
        )
        return 2

    if findings:
        return _fail(findings)
    print('PASS: PACKET_CONTRACT mechanical gate')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
