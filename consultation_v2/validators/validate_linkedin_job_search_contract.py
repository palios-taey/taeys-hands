#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / 'consultation_v2/platforms/linkedin/search_driver.py'
RUNNER = REPO_ROOT / 'scripts/run_linkedin_job_search.py'
YAML_PATH = REPO_ROOT / 'consultation_v2/platforms/linkedin/linkedin.yaml'
SCHEMAS = (
    REPO_ROOT / 'consultation_v2/platforms/linkedin/search-private-input.schema.json',
    REPO_ROOT / 'consultation_v2/platforms/linkedin/search-result.schema.json',
    REPO_ROOT / 'consultation_v2/platforms/linkedin/search-receipt.schema.json',
)
FORBIDDEN = (
    'find_elements',
    'get_extents',
    'xdotool',
    'pyautogui',
    'read_clipboard',
    'do_action(',
)


def validate() -> list[str]:
    errors: list[str] = []
    for path in (DRIVER, RUNNER):
        try:
            ast.parse(path.read_text(encoding='utf-8'))
        except (OSError, SyntaxError) as exc:
            errors.append(f'{path}: {exc}')
    for path in SCHEMAS:
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f'{path}: {exc}')
            continue
        if value.get('$schema') != 'https://json-schema.org/draft/2020-12/schema':
            errors.append(f'{path}: JSON Schema draft is not pinned')
        if value.get('type') != 'object' or value.get('additionalProperties') is not False:
            errors.append(f'{path}: root must be an exact object')
    try:
        document = yaml.safe_load(YAML_PATH.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f'{YAML_PATH}: {exc}')
        document = {}
    workflow = ((document or {}).get('workflow') or {}).get('mounted_job_search_read')
    expected = {
        'operation': 'capture_mounted_job_search',
        'route': {
            'scheme': 'https',
            'host': 'www.linkedin.com',
            'normalized_path': '/jobs/search-results',
        },
        'card': {
            'role': 'push button',
            'states_include': ['enabled'],
            'action_names_exact': ['click'],
            'direct_child_roles_prefix': [
                'section',
                'paragraph',
                'paragraph',
                'push button',
                'section',
            ],
            'minimum_direct_children': 6,
            'title': {
                'child_index': 3,
                'role': 'push button',
                'exact_prefix': 'Dismiss ',
                'exact_suffix': ' job',
            },
            'company': {
                'child_index': 1,
                'role': 'paragraph',
                'interface': 'atspi_text',
            },
            'location': {
                'child_index': 2,
                'role': 'paragraph',
                'interface': 'atspi_text',
            },
        },
        'observation_barrier': {
            'projection': 'exact_route_and_mounted_job_card_set',
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
        'action': 'private_sink_write_once',
        'postcondition': 'mounted_job_card_set_digest_unchanged',
    }
    if workflow != expected:
        errors.append(f'{YAML_PATH}: mounted job-search contract drifted')
    combined = DRIVER.read_text(encoding='utf-8') + RUNNER.read_text(encoding='utf-8')
    for token in FORBIDDEN:
        if token in combined:
            errors.append(f'mounted job-search path contains forbidden token {token!r}')
    if "build_snapshot('linkedin')" not in combined:
        errors.append('mounted job-search path does not use canonical LinkedIn snapshot')
    if 'private_sink_write_once' not in combined:
        errors.append('mounted job-search path lost its write-once sink receipt')
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f'FAIL {error}')
        return 1
    print('PASS LinkedIn mounted job-search contract')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
