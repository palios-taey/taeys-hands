#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

PLATFORM_ROOT = REPO_ROOT / 'consultation_v2' / 'platforms' / 'linkedin'
DRIVER = PLATFORM_ROOT / 'driver.py'
RUNNER = REPO_ROOT / 'scripts' / 'run_linkedin_jobs.py'
CONTRACT = REPO_ROOT / 'consultation_v2' / 'linkedin_jobs_contract.py'
DISPLAY_LOCK = REPO_ROOT / 'consultation_v2' / 'display_lock.py'
DISPLAY_LOCK_CALLERS = (
    REPO_ROOT / 'consultation_v2' / 'cli.py',
    REPO_ROOT / 'scripts' / 'run_supervised_ui_seat.py',
    REPO_ROOT / 'scripts' / 'run_taey_consult_extract.py',
)
YAML_PATH = PLATFORM_ROOT / 'linkedin.yaml'
SCHEMAS = {
    'request': PLATFORM_ROOT / 'request.schema.json',
    'result': PLATFORM_ROOT / 'result.schema.json',
    'private_input_v1': PLATFORM_ROOT / 'private-input.schema.json',
    'engagement_private_input_v2': (
        PLATFORM_ROOT / 'engagement-private-input-v2.schema.json'
    ),
    'receipt': PLATFORM_ROOT / 'receipt.schema.json',
    'engagement_result': PLATFORM_ROOT / 'engagement-result.schema.json',
    'engagement_receipt_v1': PLATFORM_ROOT / 'engagement-receipt.schema.json',
    'engagement_receipt_v2': PLATFORM_ROOT / 'engagement-receipt-v2.schema.json',
}
FORBIDDEN_RUNTIME_TOKENS = (
    'find_elements',
    'get_extents',
    'xdotool',
    'pyautogui',
    'click(',
    'read_clipboard',
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return value


def _validate_schema(
    path: Path,
    required: set[str],
    optional: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    schema = _load_json(path)
    if schema.get('$schema') != 'https://json-schema.org/draft/2020-12/schema':
        errors.append(f'{path}: schema draft is not pinned')
    if schema.get('type') != 'object' or schema.get('additionalProperties') is not False:
        errors.append(f'{path}: root must be an exact object')
    properties = schema.get('properties')
    if not isinstance(properties, dict) or set(properties) != required | (optional or set()):
        errors.append(f'{path}: properties differ from the frozen contract')
    if set(schema.get('required') or []) != required:
        errors.append(f'{path}: required fields differ from the frozen contract')
    return errors


def _validate_yaml() -> list[str]:
    errors: list[str] = []
    document = yaml.safe_load(YAML_PATH.read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        return [f'{YAML_PATH}: root must be a mapping']
    if document.get('platform') != 'linkedin' or document.get('click_strategy') != 'atspi_only':
        errors.append(f'{YAML_PATH}: platform or click strategy drifted')
    element_map = ((document.get('tree') or {}).get('element_map') or {})
    if set(element_map) != {
        'about_job_heading',
        'my_posts_filter',
        'selected_filter_marker',
    }:
        errors.append(f'{YAML_PATH}: LinkedIn map keys drifted')
    about = element_map.get('about_job_heading') or {}
    if about != {
        'name': 'About the job',
        'role': 'heading',
        'scope': 'jobs.selected_detail',
    }:
        errors.append(f'{YAML_PATH}: About heading is not exact name+role')
    if element_map.get('my_posts_filter') != {
        'name': 'My posts',
        'role': 'radio button',
        'states_include': ['showing'],
        'action': {'name': 'press', 'index': 0},
    }:
        errors.append(f'{YAML_PATH}: My posts exact press contract drifted')
    if element_map.get('selected_filter_marker') != {
        'name': 'My posts’ filters',
        'role': 'push button',
        'states_include': ['showing'],
    }:
        errors.append(f'{YAML_PATH}: My posts marker contract drifted')
    forbidden = {'contains', 'regex', 'fuzzy', 'name_contains', 'name_pattern'}
    if any(key in forbidden for spec in element_map.values() for key in spec):
        errors.append(f'{YAML_PATH}: fuzzy matcher grammar is forbidden')
    workflow = document.get('workflow') or {}
    expected_workflow = {
        'operation': 'capture_selected_job',
        'observation': 'canonical_snapshot_anchor',
        'required_elements': ['about_job_heading'],
        'description_traversal': [
            {'relation': 'parent', 'role': 'section'},
            {'relation': 'child', 'index': 1, 'role': 'paragraph'},
            {'relation': 'child', 'index': 0, 'role': 'section'},
        ],
        'description_interface': 'atspi_text',
        'action': 'private_sink_write_once',
        'postcondition': 'selected_job_content_digest_unchanged',
    }
    if workflow.get('selected_job_read') != expected_workflow:
        errors.append(f'{YAML_PATH}: frozen transaction workflow drifted')
    expected_selection = {
        'operation': 'select_and_capture_job',
        'observation': 'canonical_snapshot_private_exact_name',
        'target_card': {
            'role': 'push button',
            'states_include': ['showing', 'enabled'],
        },
        'action': {
            'interface': 'atspi_action',
            'name': 'click',
        },
        'detail_title': {
            'role': 'link',
            'states_include': ['showing', 'enabled'],
        },
        'detail_company': {
            'role': 'link',
            'states_include': ['showing', 'enabled'],
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
        'postcondition': 'private_exact_detail_identity_and_selected_job',
    }
    if workflow.get('job_selection') != expected_selection:
        errors.append(f'{YAML_PATH}: exact job-selection workflow drifted')
    engagement = workflow.get('engagement_signal_capture') or {}
    required_engagement = {
        'operation': 'capture_visible_new_engagement_signal',
        'sink_action': 'private_sink_write_once',
        'postcondition': 'selected_signal_content_digest_unchanged',
    }
    if any(engagement.get(key) != value for key, value in required_engagement.items()):
        errors.append(f'{YAML_PATH}: engagement operation boundary drifted')
    navigation = engagement.get('navigation') or {}
    if navigation.get('target') != {
        'scope': 'exact_linkedin_navigation_preload_document',
        'ancestor_document': {
            'scheme': 'https',
            'host': 'www.linkedin.com',
            'normalized_path': '/preload',
            'exact_query': {'_bprMode': 'vanilla'},
        },
        'role': 'link',
        'states_exact': ['enabled', 'focusable', 'showing'],
        'uri': {
            'scheme': 'https',
            'host': 'www.linkedin.com',
            'normalized_path': '/notifications',
            'exact_query': {'filter': 'all', 'refresh': 'true'},
        },
        'action_names_exact': ['jump'],
    } or navigation.get('action') != {'name': 'jump', 'index': 0}:
        errors.append(f'{YAML_PATH}: Notifications exact jump contract drifted')
    if navigation.get('manual_post_action') != {
        'element_key': 'notifications_navigation',
        'operation': 'activate',
        'postcondition': {
            'projection': 'exact_route_and_all_category',
            'route_key': 'notifications_all',
        },
        'observation_barrier': {
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
    }:
        errors.append(f'{YAML_PATH}: manual Notifications route barrier drifted')
    expected_barriers = (
        (
            navigation.get('initial_observation_barrier'),
            'exact_notifications_navigation',
        ),
        (
            navigation.get('observation_barrier'),
            'exact_route_and_my_posts_state',
        ),
        (
            engagement.get('observation_barrier'),
            'exact_route_marker_and_candidate_set',
        ),
        (
            (engagement.get('restore') or {}).get('observation_barrier'),
            'exact_return_route_and_current_notifications_state',
        ),
    )
    for barrier, projection in expected_barriers:
        if barrier != {
            'projection': projection,
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        }:
            errors.append(f'{YAML_PATH}: {projection} barrier drifted')
    candidate = engagement.get('candidate_observation') or {}
    if candidate != {
        'observation_name_prefix': 'Unread notification.',
        'role': 'link',
        'states_include': ['showing'],
        'allowed_uri_normalized_path_prefixes': ['/feed/', '/posts/'],
        'authority': 'observation_classification_only',
    }:
        errors.append(f'{YAML_PATH}: engagement classifier drifted')
    restore = engagement.get('restore') or {}
    if restore != {
        'navigation_key': 'ctrl+l',
        'address_bar': {
            'key': 'address_bar',
            'name': 'Search with Google or enter address',
            'role': 'entry',
            'states_include': ['editable', 'focusable'],
        },
        'submit_key': 'Return',
        'observation_barrier': {
            'projection': 'exact_return_route_and_current_notifications_state',
            'refresh_policy': 'invalidate_reacquire',
            'stable_cycles': 2,
            'interval_ms': 200,
            'timeout_ms': 10000,
        },
    }:
        errors.append(f'{YAML_PATH}: exact Jobs return contract drifted')
    indicators = ((document.get('validation') or {}).get('selected_job_ready') or {}).get('indicators')
    if indicators != ['about_job_heading']:
        errors.append(f'{YAML_PATH}: selected-job readiness must use the exact heading')
    return errors


def _state_conditionals(state_field: str) -> list[dict[str, Any]]:
    technical_codes = [
        'deadline_expired',
        'display_lock_unavailable',
        'lock_release_indeterminate',
        'post_observation_indeterminate',
        'pre_observation_failed',
        'private_input_invalid',
    ]
    digest = (
        {'$ref': '#/$defs/digest'}
        if state_field == 'terminal_state'
        else {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
    )

    def facts(
        observed: int,
        written: int | list[int] | None,
        digest_rule: dict[str, Any],
    ) -> dict[str, Any]:
        record_facts = {
            'records_observed': {'const': observed},
            'records_written': (
                {'type': 'null'}
                if written is None
                else (
                    {'const': written}
                    if isinstance(written, int)
                    else {'enum': written}
                )
            ),
            'content_digest': digest_rule,
        }
        if state_field == 'terminal_state':
            return {'action': {'properties': record_facts}}
        return record_facts

    return [
        {
            'if': {
                'properties': {
                    state_field: {'const': 'captured'},
                },
                'required': [state_field],
            },
            'then': {
                'properties': {
                    'ok': {'const': True},
                    'failure_code': {'type': 'null'},
                    **facts(1, 1, digest),
                },
            },
        },
        {
            'if': {
                'properties': {
                    state_field: {'const': 'already_captured'},
                },
                'required': [state_field],
            },
            'then': {
                'properties': {
                    'ok': {'const': True},
                    'failure_code': {'type': 'null'},
                    **facts(1, 0, digest),
                },
            },
        },
        {
            'if': {
                'properties': {state_field: {'const': 'no_selected_job'}},
                'required': [state_field],
            },
            'then': {
                'properties': {
                    'ok': {'const': False},
                    'failure_code': {'const': 'selected_job_not_exact'},
                    **facts(0, 0, {'type': 'null'}),
                },
            },
        },
        {
            'if': {
                'properties': {state_field: {'const': 'postcondition_failed'}},
                'required': [state_field],
            },
            'then': {
                'properties': {
                    'ok': {'const': False},
                    'failure_code': {'const': 'postcondition_failed'},
                    **facts(1, [0, 1], digest),
                },
            },
        },
        {
            'if': {
                'properties': {state_field: {'const': 'technical_failure'}},
                'required': [state_field],
            },
            'then': {
                'properties': {
                    'ok': {'const': False},
                },
                'oneOf': [
                    {
                        'properties': {
                            'failure_code': {'const': 'sink_write_indeterminate'},
                            **facts(1, None, digest),
                        },
                    },
                    {
                        'properties': {
                            'failure_code': {'enum': technical_codes},
                        },
                        'anyOf': [
                            {'properties': facts(0, 0, {'type': 'null'})},
                            {'properties': facts(1, [0, 1], digest)},
                        ],
                    },
                ],
            },
        },
    ]


def _validate_interface_patterns() -> list[str]:
    errors: list[str] = []
    contract_source = CONTRACT.read_text(encoding='utf-8')
    if "_DISPLAY_RE = re.compile(r'^:[0-9]{1,3}$')" not in contract_source:
        errors.append(f'{CONTRACT}: display grammar differs from Presence')
    if "_REQUESTER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')" not in contract_source:
        errors.append(f'{CONTRACT}: requester grammar differs from Presence')
    result_schema = _load_json(SCHEMAS['result'])
    receipt_schema = _load_json(SCHEMAS['receipt'])
    match_counts = ((receipt_schema.get('$defs') or {}).get('match_counts') or {})
    expected_match_keys = {'about_job_heading', 'selected_job_description_path'}
    if (
        match_counts.get('type') != 'object'
        or match_counts.get('additionalProperties') is not False
        or set(match_counts.get('properties') or {}) != expected_match_keys
        or set(match_counts.get('required') or []) != expected_match_keys
    ):
        errors.append(f"{SCHEMAS['receipt']}: exact match-count schema drifted")
    selection = (receipt_schema.get('properties') or {}).get('selection') or {}
    expected_selection_keys = {
        'kind',
        'verdict',
        'target_card_name_sha256',
        'detail_title_name_sha256',
        'detail_company_name_sha256',
        'target_match_count',
        'detail_title_match_count',
        'detail_company_match_count',
        'stable_cycles_observed',
        'action_name',
        'action_index',
        'action_match_count',
    }
    if (
        selection.get('type') != 'object'
        or selection.get('additionalProperties') is not False
        or set(selection.get('properties') or {}) != expected_selection_keys
        or set(selection.get('required') or []) != expected_selection_keys
    ):
        errors.append(f"{SCHEMAS['receipt']}: selection receipt schema drifted")
    if result_schema.get('allOf') != _state_conditionals('state'):
        errors.append(f"{SCHEMAS['result']}: state/ok/failure_code conditionals drifted")
    if receipt_schema.get('allOf') != _state_conditionals('terminal_state'):
        errors.append(f"{SCHEMAS['receipt']}: state/ok/failure_code conditionals drifted")
    if (result_schema.get('properties') or {}).get('display', {}).get('pattern') != '^:[0-9]{1,3}$':
        errors.append(f"{SCHEMAS['result']}: display grammar differs from Presence")
    if (
        (receipt_schema.get('properties') or {}).get('requester', {}).get('pattern')
        != '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'
    ):
        errors.append(f"{SCHEMAS['receipt']}: requester grammar differs from Presence")
    from consultation_v2.linkedin_jobs_contract import (
        FAILURE_CODES,
        FAILURE_CODES_BY_STATE,
        LinkedInJobsContractError,
        validate_public_result,
    )

    states = {
        'captured': frozenset({None}),
        'already_captured': frozenset({None}),
        **FAILURE_CODES_BY_STATE,
    }
    valid_facts = {
        'captured': (1, 1, '2' * 64),
        'already_captured': (1, 0, '2' * 64),
        'no_selected_job': (0, 0, None),
        'postcondition_failed': (1, 0, '2' * 64),
        'technical_failure': (0, 0, None),
    }

    def facts_match(
        state: str,
        failure_code: str | None,
        records_observed: int,
        records_written: int | None,
        content_digest: str | None,
    ) -> bool:
        facts = (records_observed, records_written, content_digest is not None)
        if state == 'captured':
            return facts == (1, 1, True)
        if state == 'already_captured':
            return facts == (1, 0, True)
        if state == 'no_selected_job':
            return facts == (0, 0, False)
        if state == 'postcondition_failed':
            return (
                records_observed == 1
                and records_written in {0, 1}
                and content_digest is not None
            )
        if failure_code == 'sink_write_indeterminate':
            return facts == (1, None, True)
        return facts == (0, 0, False) or (
            records_observed == 1
            and records_written in {0, 1}
            and content_digest is not None
        )

    for state, allowed_codes in states.items():
        for failure_code in {None, *FAILURE_CODES}:
            if state == 'technical_failure' and failure_code == 'sink_write_indeterminate':
                records_observed, records_written, content_digest = (1, None, '2' * 64)
            else:
                records_observed, records_written, content_digest = valid_facts[state]
            candidate = {
                'ok': state in {'captured', 'already_captured'},
                'platform': 'linkedin',
                'display': ':18',
                'state': state,
                'failure_code': failure_code,
                'records_observed': records_observed,
                'records_written': records_written,
                'content_digest': content_digest,
                'receipt_sha256': '0' * 64,
                'turn_lineage_sha256': '1' * 64,
            }
            try:
                validate_public_result(candidate)
                accepted = True
            except LinkedInJobsContractError:
                accepted = False
            if accepted is not (failure_code in allowed_codes):
                errors.append(
                    f'{CONTRACT}: {state}/{failure_code} failure mapping is not exact'
                )
    for state, allowed_codes in states.items():
        for failure_code in allowed_codes:
            for records_observed in (0, 1):
                for records_written in (0, 1, None):
                    for content_digest in (None, '2' * 64):
                        candidate = {
                            'ok': state in {'captured', 'already_captured'},
                            'platform': 'linkedin',
                            'display': ':18',
                            'state': state,
                            'failure_code': failure_code,
                            'records_observed': records_observed,
                            'records_written': records_written,
                            'content_digest': content_digest,
                            'receipt_sha256': '0' * 64,
                            'turn_lineage_sha256': '1' * 64,
                        }
                        expected = facts_match(
                            state,
                            failure_code,
                            records_observed,
                            records_written,
                            content_digest,
                        )
                        try:
                            validate_public_result(candidate)
                            accepted = True
                        except LinkedInJobsContractError:
                            accepted = False
                        if accepted is not expected:
                            errors.append(
                                f'{CONTRACT}: {state} count/digest mapping is not exact'
                            )
    engagement_result = _load_json(SCHEMAS['engagement_result'])
    engagement_receipt_v1 = _load_json(SCHEMAS['engagement_receipt_v1'])
    engagement_receipt_v2 = _load_json(SCHEMAS['engagement_receipt_v2'])
    engagement_result_keys = {
        'ok', 'platform', 'display', 'state', 'failure_code',
        'records_observed', 'records_written', 'content_digest',
        'receipt_sha256', 'turn_lineage_sha256', 'restore_verified',
    }
    if (
        set(engagement_result.get('properties') or {}) != engagement_result_keys
        or set(engagement_result.get('required') or []) != engagement_result_keys
    ):
        errors.append(f"{SCHEMAS['engagement_result']}: exact 11-key result drifted")
    if (
        (engagement_receipt_v1.get('properties') or {}).get('schema', {}).get('const')
        != 'linkedin_engagement_receipt_v1'
    ):
        errors.append(f"{SCHEMAS['engagement_receipt_v1']}: receipt identity drifted")
    if (
        (engagement_receipt_v2.get('properties') or {}).get('schema', {}).get('const')
        != 'linkedin_engagement_receipt_v2'
    ):
        errors.append(f"{SCHEMAS['engagement_receipt_v2']}: receipt identity drifted")
    engagement_cases = (
        ('already_known', True, None, 1, 0, '2' * 64, True),
        ('ambiguous_signal', False, 'ambiguous_signal', 0, 0, None, False),
        ('captured', True, None, 1, 1, '2' * 64, True),
        ('no_new_signal', True, None, 0, 0, None, True),
        ('postcondition_failed', False, 'postcondition_failed', 0, 0, None, False),
        (
            'sink_write_indeterminate',
            False,
            'sink_write_indeterminate',
            1,
            None,
            '2' * 64,
            False,
        ),
        ('technical_failure', False, 'action_failed', 0, 0, None, False),
    )
    for state, ok, code, observed, written, digest, restored in engagement_cases:
        candidate = {
            'ok': ok,
            'platform': 'linkedin',
            'display': ':18',
            'state': state,
            'failure_code': code,
            'records_observed': observed,
            'records_written': written,
            'content_digest': digest,
            'receipt_sha256': '0' * 64,
            'turn_lineage_sha256': '1' * 64,
            'restore_verified': restored,
        }
        try:
            validate_public_result(candidate)
        except LinkedInJobsContractError as exc:
            errors.append(f'{CONTRACT}: engagement {state} rejected: {exc}')
        if ok:
            candidate['restore_verified'] = False
            try:
                validate_public_result(candidate)
            except LinkedInJobsContractError:
                rejected_without_restore = True
            else:
                rejected_without_restore = False
            if not rejected_without_restore:
                errors.append(f'{CONTRACT}: {state} accepted without exact restoration')
    return errors


def _validate_engagement_schema_fixtures() -> list[str]:
    from jsonschema import Draft202012Validator

    errors: list[str] = []
    private_schema_v1 = _load_json(SCHEMAS['private_input_v1'])
    private_schema_v2 = _load_json(SCHEMAS['engagement_private_input_v2'])
    result_schema = _load_json(SCHEMAS['engagement_result'])
    receipt_schema_v1 = _load_json(SCHEMAS['engagement_receipt_v1'])
    receipt_schema_v2 = _load_json(SCHEMAS['engagement_receipt_v2'])
    for path, schema in (
        (SCHEMAS['private_input_v1'], private_schema_v1),
        (SCHEMAS['engagement_private_input_v2'], private_schema_v2),
        (SCHEMAS['engagement_result'], result_schema),
        (SCHEMAS['engagement_receipt_v1'], receipt_schema_v1),
        (SCHEMAS['engagement_receipt_v2'], receipt_schema_v2),
    ):
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            errors.append(f'{path}: invalid Draft 2020-12 schema: {exc}')

    digest = '1' * 64
    result = {
        'ok': True,
        'platform': 'linkedin',
        'display': ':18',
        'state': 'captured',
        'failure_code': None,
        'records_observed': 1,
        'records_written': 1,
        'content_digest': digest,
        'receipt_sha256': '2' * 64,
        'turn_lineage_sha256': '3' * 64,
        'restore_verified': True,
    }
    action = {
        'stage': 'notifications_navigation',
        'target_match_count': 1,
        'action_name': 'jump',
        'action_index': 0,
        'action_match_count': 1,
        'verdict': 'executed',
    }
    receipt = {
        'schema': 'linkedin_engagement_receipt_v2',
        'platform': 'linkedin',
        'operation': 'capture_visible_new_engagement_signal',
        'display': ':18',
        'requester': 'schema-fixture',
        'turn_lineage_sha256': '3' * 64,
        'correlation_id_sha256': '4' * 64,
        'deadline_seconds': 300,
        'hands_commit': '5' * 40,
        'yaml_sha256': '6' * 64,
        'terminal_state': 'captured',
        'ok': True,
        'failure_code': None,
        'records_observed': 1,
        'records_written': 1,
        'content_digest': digest,
        'restore_verified': True,
        'transaction_sha256': '7' * 64,
        'expected_transaction_sha256': '7' * 64,
        'source_ref_sha256': '8' * 64,
        'sink_ref_sha256': '9' * 64,
        'return_url_sha256': 'b' * 64,
        'start': {
            'route_exact': True,
            'route_kind_exact': True,
            'notifications_target_match_count': 1,
            'notifications_target_state_digest': 'c' * 64,
        },
        'notifications_action': action,
        'notifications_postcondition': {
            'route_exact': True,
            'my_posts_match_count': 1,
            'my_posts_state_digest': 'd' * 64,
            'stable_cycles_required': 2,
            'stable_cycles_observed': 2,
        },
        'my_posts_action': {
            **action,
            'stage': 'my_posts_filter',
            'action_name': 'press',
        },
        'my_posts_postcondition': {
            'route_exact': True,
            'selected_filter_marker_match_count': 1,
            'candidate_count': 1,
            'candidate_set_digest': 'e' * 64,
            'stable_cycles_required': 2,
            'stable_cycles_observed': 2,
        },
        'candidate': {'match_count': 1, 'content_digest': digest},
        'sink': {
            'kind': 'private_sink_write_once',
            'verdict': 'written',
            'records_written': 1,
        },
        'signal_postcondition': 'satisfied',
        'restore': {
            'verdict': 'satisfied',
            'failed_substep': None,
            'firefox_pid_sha256': 'f' * 64,
            'stable_cycles_required': 2,
            'stable_cycles_observed': 2,
            'return_url_sha256': 'b' * 64,
        },
        'lock': {
            'policy': 'careers',
            'request_id': '0' * 64,
            'acquired': True,
            'released': True,
            'owner_token_sha256': '1' * 64,
            'wait_ms': 0,
            'turn_lineage_sha256': '3' * 64,
            'correlation_id_sha256': '4' * 64,
            'deadline_seconds': 300,
        },
    }
    validators = {
        'private_v1': Draft202012Validator(private_schema_v1),
        'private_v2': Draft202012Validator(private_schema_v2),
        'result': Draft202012Validator(result_schema),
        'receipt_v1': Draft202012Validator(receipt_schema_v1),
        'receipt_v2': Draft202012Validator(receipt_schema_v2),
        'receipt': Draft202012Validator(receipt_schema_v2),
    }
    legacy_receipt = deepcopy(receipt)
    legacy_receipt.update({
        'schema': 'linkedin_engagement_receipt_v1',
        'notifications_name_sha256': 'a' * 64,
    })
    private_v1 = {
        'schema': 'linkedin_jobs_private_input_v1',
        'operation': 'capture_visible_new_engagement_signal',
        'source_ref': '/private/source',
        'sink_ref': '/private/sink',
        'notifications_name': 'Notifications, 0 new notifications',
        'return_url': 'https://www.linkedin.com/jobs/search-results/?keywords=ai',
    }
    private_v2 = {
        key: value
        for key, value in private_v1.items()
        if key != 'notifications_name'
    }
    private_v2['schema'] = 'linkedin_engagement_private_input_v2'
    for label, validator, candidate in (
        ('valid v1 private input', validators['private_v1'], private_v1),
        ('valid v2 private input', validators['private_v2'], private_v2),
        ('valid captured result', validators['result'], result),
        ('valid captured v1 receipt', validators['receipt_v1'], legacy_receipt),
        ('valid captured v2 receipt', validators['receipt_v2'], receipt),
    ):
        if not validator.is_valid(candidate):
            errors.append(f'{label} rejected by engagement schema')
    for label, validator, candidate in (
        ('v1 private input accepted as v2', validators['private_v2'], private_v1),
        ('v2 private input accepted as v1', validators['private_v1'], private_v2),
        ('v1 receipt accepted as v2', validators['receipt_v2'], legacy_receipt),
        ('v2 receipt accepted as v1', validators['receipt_v1'], receipt),
    ):
        if validator.is_valid(candidate):
            errors.append(label)

    empty_action = {
        'stage': 'notifications_navigation',
        'target_match_count': 0,
        'action_name': None,
        'action_index': None,
        'action_match_count': 0,
        'verdict': 'not_executed',
    }
    empty_restore = {
        'verdict': 'not_executed',
        'failed_substep': None,
        'firefox_pid_sha256': None,
        'stable_cycles_required': 0,
        'stable_cycles_observed': 0,
        'return_url_sha256': None,
    }
    already_known = deepcopy(receipt)
    already_known.update({
        'terminal_state': 'already_known',
        'records_written': 0,
    })
    already_known['sink'].update({'verdict': 'already_present', 'records_written': 0})
    no_new = deepcopy(receipt)
    no_new.update({
        'terminal_state': 'no_new_signal',
        'records_observed': 0,
        'records_written': 0,
        'content_digest': None,
    })
    no_new['candidate'] = {'match_count': 0, 'content_digest': None}
    no_new['my_posts_postcondition']['candidate_count'] = 0
    no_new['sink'] = {
        'kind': 'private_sink_write_once',
        'verdict': 'not_executed',
        'records_written': 0,
    }
    no_new['signal_postcondition'] = 'not_evaluated'
    ambiguous = deepcopy(no_new)
    ambiguous.update({
        'terminal_state': 'ambiguous_signal',
        'ok': False,
        'failure_code': 'ambiguous_signal',
        'restore_verified': False,
    })
    ambiguous['candidate']['match_count'] = 2
    ambiguous['my_posts_postcondition']['candidate_count'] = 2
    ambiguous['restore'] = empty_restore
    postcondition_failed = deepcopy(receipt)
    postcondition_failed.update({
        'terminal_state': 'postcondition_failed',
        'ok': False,
        'failure_code': 'postcondition_failed',
        'restore_verified': False,
    })
    postcondition_failed['signal_postcondition'] = 'failed'
    postcondition_failed['restore'] = empty_restore
    sink_indeterminate = deepcopy(receipt)
    sink_indeterminate.update({
        'terminal_state': 'sink_write_indeterminate',
        'ok': False,
        'failure_code': 'sink_write_indeterminate',
        'records_written': None,
        'restore_verified': False,
    })
    sink_indeterminate['sink'].update({
        'verdict': 'indeterminate',
        'records_written': None,
    })
    sink_indeterminate['signal_postcondition'] = 'not_evaluated'
    sink_indeterminate['restore'] = empty_restore
    technical_failure = deepcopy(receipt)
    technical_failure.update({
        'terminal_state': 'technical_failure',
        'ok': False,
        'failure_code': 'pre_observation_failed',
        'records_observed': 0,
        'records_written': 0,
        'content_digest': None,
        'restore_verified': False,
        'start': {},
        'notifications_action': empty_action,
        'notifications_postcondition': {},
        'my_posts_action': {**empty_action, 'stage': 'my_posts_filter'},
        'my_posts_postcondition': {},
        'candidate': {'match_count': 0, 'content_digest': None},
        'sink': {
            'kind': 'private_sink_write_once',
            'verdict': 'not_executed',
            'records_written': 0,
        },
        'signal_postcondition': 'not_evaluated',
        'restore': empty_restore,
    })
    for state, candidate in (
        ('captured', receipt),
        ('already_known', already_known),
        ('no_new_signal', no_new),
        ('ambiguous_signal', ambiguous),
        ('postcondition_failed', postcondition_failed),
        ('sink_write_indeterminate', sink_indeterminate),
        ('technical_failure', technical_failure),
    ):
        if not validators['receipt'].is_valid(candidate):
            errors.append(f'actual-shape {state} receipt rejected by engagement schema')
    chain_receipts = (
        ('captured', receipt),
        ('already_known', already_known),
        ('no_new_signal', no_new),
        ('ambiguous_signal', ambiguous),
        ('sink_write_indeterminate', sink_indeterminate),
    )
    for state, candidate in chain_receipts:
        missing_start = deepcopy(candidate)
        missing_start['start'] = {}
        if validators['receipt'].is_valid(missing_start):
            errors.append(f'{state} accepted without exact start proof')
        for postcondition_key in (
            'notifications_postcondition',
            'my_posts_postcondition',
        ):
            missing_postcondition = deepcopy(candidate)
            missing_postcondition[postcondition_key] = {}
            if validators['receipt'].is_valid(missing_postcondition):
                errors.append(
                    f'{state} accepted without exact {postcondition_key} proof'
                )
        unowned_lock = deepcopy(candidate)
        unowned_lock['lock'].update({
            'acquired': False,
            'released': False,
            'owner_token_sha256': None,
        })
        if validators['receipt'].is_valid(unowned_lock):
            required_lock = (
                'acquired lock'
                if state == 'sink_write_indeterminate'
                else 'acquired+released lock'
            )
            errors.append(f'{state} accepted without {required_lock} proof')

    sink_unreleased = deepcopy(sink_indeterminate)
    sink_unreleased['lock']['released'] = False
    if not validators['receipt'].is_valid(sink_unreleased):
        errors.append('sink indeterminacy with truthful released=false rejected')
    sink_after_signal_postcondition = deepcopy(sink_indeterminate)
    sink_after_signal_postcondition['signal_postcondition'] = 'satisfied'
    if validators['receipt'].is_valid(sink_after_signal_postcondition):
        errors.append('sink indeterminacy accepted after signal postcondition')

    action_verdicts = {
        'target_not_exact': {
            'stage': 'notifications_navigation',
            'target_match_count': 0,
            'action_name': 'jump',
            'action_index': None,
            'action_match_count': 0,
            'verdict': 'target_not_exact',
        },
        'action_enumeration_failed': {
            'stage': 'notifications_navigation',
            'target_match_count': 1,
            'action_name': 'jump',
            'action_index': None,
            'action_match_count': 0,
            'verdict': 'action_enumeration_failed',
        },
        'action_not_exact': {
            'stage': 'notifications_navigation',
            'target_match_count': 1,
            'action_name': 'jump',
            'action_index': None,
            'action_match_count': 0,
            'verdict': 'action_not_exact',
        },
        'action_raised': {
            'stage': 'notifications_navigation',
            'target_match_count': 1,
            'action_name': 'jump',
            'action_index': 0,
            'action_match_count': 1,
            'verdict': 'action_raised',
        },
        'action_returned_false': {
            'stage': 'notifications_navigation',
            'target_match_count': 1,
            'action_name': 'jump',
            'action_index': 0,
            'action_match_count': 1,
            'verdict': 'action_returned_false',
        },
    }
    action_failure_receipts: dict[str, dict[str, Any]] = {}
    for verdict, action_facts in action_verdicts.items():
        candidate = deepcopy(technical_failure)
        candidate.update({
            'failure_code': 'action_failed',
            'start': deepcopy(receipt['start']),
            'notifications_action': action_facts,
        })
        action_failure_receipts[verdict] = candidate
        if not validators['receipt'].is_valid(candidate):
            errors.append(f'valid {verdict} action facts rejected')

    invalid_action_facts = {
        'target_not_exact': {'target_match_count': 1},
        'action_enumeration_failed': {'target_match_count': 0},
        'action_not_exact': {'action_match_count': 1},
        'action_raised': {'action_match_count': 0},
        'action_returned_false': {'target_match_count': 0},
    }
    for verdict, impossible_facts in invalid_action_facts.items():
        candidate = deepcopy(action_failure_receipts[verdict])
        candidate['notifications_action'].update(impossible_facts)
        if validators['receipt'].is_valid(candidate):
            errors.append(f'impossible {verdict} action facts accepted')
    result_cases = (
        result,
        {**result, 'state': 'already_known', 'records_written': 0},
        {
            **result,
            'state': 'no_new_signal',
            'records_observed': 0,
            'records_written': 0,
            'content_digest': None,
        },
        {
            **result,
            'state': 'ambiguous_signal',
            'ok': False,
            'failure_code': 'ambiguous_signal',
            'records_observed': 0,
            'records_written': 0,
            'content_digest': None,
            'restore_verified': False,
        },
        {
            **result,
            'state': 'postcondition_failed',
            'ok': False,
            'failure_code': 'postcondition_failed',
            'restore_verified': False,
        },
        {
            **result,
            'state': 'sink_write_indeterminate',
            'ok': False,
            'failure_code': 'sink_write_indeterminate',
            'records_written': None,
            'restore_verified': False,
        },
        {
            **result,
            'state': 'technical_failure',
            'ok': False,
            'failure_code': 'pre_observation_failed',
            'records_observed': 0,
            'records_written': 0,
            'content_digest': None,
            'restore_verified': False,
        },
    )
    for candidate in result_cases:
        if not validators['result'].is_valid(candidate):
            errors.append(
                f"actual-shape {candidate['state']} result rejected by engagement schema"
            )

    impossible_captured = deepcopy(result)
    impossible_captured['records_written'] = 0
    impossible_failure = deepcopy(result)
    impossible_failure.update({
        'ok': False,
        'state': 'technical_failure',
        'failure_code': None,
        'records_observed': 0,
        'records_written': 0,
        'content_digest': None,
        'restore_verified': False,
    })
    impossible_action = deepcopy(receipt)
    impossible_action['notifications_action']['coordinate'] = [1, 2]
    impossible_lock = deepcopy(receipt)
    del impossible_lock['lock']['released']
    impossible_no_action_chain = deepcopy(receipt)
    impossible_no_action_chain.update({
        'notifications_action': empty_action,
        'notifications_postcondition': {},
        'my_posts_action': {**empty_action, 'stage': 'my_posts_filter'},
        'my_posts_postcondition': {},
    })
    for label, validator, candidate in (
        ('impossible captured facts', validators['result'], impossible_captured),
        ('impossible failure identity', validators['result'], impossible_failure),
        ('impossible action object', validators['receipt'], impossible_action),
        ('impossible lock object', validators['receipt'], impossible_lock),
        (
            'captured without exact action/postcondition chain',
            validators['receipt'],
            impossible_no_action_chain,
        ),
    ):
        if validator.is_valid(candidate):
            errors.append(f'{label} accepted by engagement schema')
    return errors


def _validate_restore_projection() -> list[str]:
    from consultation_v2.platforms.linkedin.driver import (
        _notifications_target,
        observe_engagement_start,
        observe_engagement_restore,
    )
    from consultation_v2.types import ElementRef, Snapshot

    class Hyperlink:
        def __init__(self, uri: str) -> None:
            self._uri = uri

        def get_uri(self, index: int) -> str:
            if index != 0:
                raise IndexError(index)
            return self._uri

    class Action:
        def __init__(self, names: tuple[str, ...]) -> None:
            self._names = names

        def get_n_actions(self) -> int:
            return len(self._names)

        def get_action_name(self, index: int) -> str:
            return self._names[index]

    class Document:
        def __init__(self, url: str) -> None:
            self._url = url

        def get_parent(self) -> None:
            return None

        def get_role_name(self) -> str:
            return 'document web'

        def get_document_iface(self) -> Document:
            return self

        def get_document_attribute_value(self, key: str) -> str | None:
            return self._url if key == 'DocURL' else None

    class Accessible:
        def __init__(
            self,
            uri: str,
            document_url: str,
            action_names: tuple[str, ...],
        ) -> None:
            self._hyperlink = Hyperlink(uri)
            self._document = Document(document_url)
            self._action = Action(action_names)

        def get_hyperlink(self) -> Hyperlink:
            return self._hyperlink

        def get_parent(self) -> Document:
            return self._document

        def get_action_iface(self) -> Action:
            return self._action

    def notifications(
        name: str,
        uri: str,
        document_url: str,
        action_names: tuple[str, ...] = ('jump',),
        role: str = 'link',
        states: tuple[str, ...] = ('enabled', 'focusable', 'showing'),
    ) -> ElementRef:
        return ElementRef(
            key=None,
            name=name,
            role=role,
            x=None,
            y=None,
            states=list(states),
            atspi_obj=Accessible(uri, document_url, action_names),
        )

    def snapshot(*elements: ElementRef) -> Snapshot:
        return Snapshot(
            platform='linkedin',
            url=return_url,
            unknown=list(elements),
        )

    errors: list[str] = []
    current_name = 'Notifications, 15 new notifications'
    notifications_uri = (
        'https://www.linkedin.com/notifications?filter=all&refresh=true'
    )
    return_url = 'https://www.linkedin.com/jobs/search-results?keywords=engineering'
    preload_url = 'https://www.linkedin.com/preload/?_bprMode=vanilla'
    samples = [
        snapshot(
            notifications('15 new notifications Notifications', notifications_uri, preload_url),
            notifications(current_name, notifications_uri, return_url),
        )
        for _sample in range(3)
    ]
    digests: list[str] = []
    for sample in samples:
        target, count = _notifications_target(sample)
        start = observe_engagement_start(sample, return_url)
        restored = observe_engagement_restore(sample, return_url)
        digest = start['notifications_target_state_digest']
        if not (
            target is not None
            and count == 1
            and start['route_exact'] is True
            and start['route_kind_exact'] is True
            and start['notifications_target_match_count'] == 1
            and restored == start
            and isinstance(digest, str)
        ):
            errors.append('preload-document Notifications authority was not exact')
            break
        digests.append(digest)
    if len(digests) != 3 or len(set(digests)) != 1:
        errors.append('three read-only Notifications samples did not stabilize')

    changed_name = snapshot(
        notifications('933 new notifications Notifications', notifications_uri, preload_url),
        notifications('Notifications, 933 new notifications', notifications_uri, return_url),
    )
    changed_target, changed_count = _notifications_target(changed_name)
    changed_start = observe_engagement_start(changed_name, return_url)
    changed_restore = observe_engagement_restore(changed_name, return_url)
    if (
        changed_target is None
        or changed_count != 1
        or changed_start['notifications_target_state_digest'] != digests[0]
        or changed_restore['notifications_target_state_digest'] != digests[0]
    ):
        errors.append('mutable unread count remained part of Notifications authority')

    failures = {
        'zero': snapshot(),
        'duplicate_preload_document': snapshot(
            notifications(current_name, notifications_uri, preload_url),
            notifications('Notifications, 1 new notification', notifications_uri, preload_url),
        ),
        'current_document_only': snapshot(
            notifications(current_name, notifications_uri, return_url),
        ),
        'preload_extra_query': snapshot(
            notifications(
                current_name,
                notifications_uri,
                preload_url + '&extra=true',
            ),
        ),
        'preload_wrong_host': snapshot(
            notifications(
                current_name,
                notifications_uri,
                'https://example.com/preload/?_bprMode=vanilla',
            ),
        ),
        'target_extra_query': snapshot(
            notifications(
                current_name,
                notifications_uri + '&extra=true',
                preload_url,
            ),
        ),
        'target_wrong_path': snapshot(
            notifications(
                current_name,
                'https://www.linkedin.com/feed/?filter=all&refresh=true',
                preload_url,
            ),
        ),
        'missing_state': snapshot(
            notifications(
                current_name,
                notifications_uri,
                preload_url,
                states=('enabled', 'showing'),
            ),
        ),
        'extra_state': snapshot(
            notifications(
                current_name,
                notifications_uri,
                preload_url,
                states=('enabled', 'focusable', 'showing', 'selected'),
            ),
        ),
        'wrong_action': snapshot(
            notifications(current_name, notifications_uri, preload_url, ('click',)),
        ),
        'extra_action': snapshot(
            notifications(
                current_name,
                notifications_uri,
                preload_url,
                ('jump', 'click'),
            ),
        ),
        'wrong_role': snapshot(
            notifications(
                current_name,
                notifications_uri,
                preload_url,
                role='push button',
            ),
        ),
    }
    for label, candidate in failures.items():
        observed = observe_engagement_restore(candidate, return_url)
        if (
            observed['notifications_target_match_count'] == 1
            or observed['notifications_target_state_digest'] is not None
        ):
            errors.append(f'{label} Notifications target satisfied restore projection')
    return errors


def _validate_runtime_source() -> list[str]:
    errors: list[str] = []
    for path in (DRIVER, RUNNER):
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(path))
        for token in FORBIDDEN_RUNTIME_TOKENS:
            if token in source:
                errors.append(f'{path}: forbidden runtime token {token!r}')
        if any(
            isinstance(node, ast.Attribute) and node.attr in {'x', 'y'}
            for node in ast.walk(tree)
        ):
            errors.append(f'{path}: coordinate attribute access is forbidden')
    driver_source = DRIVER.read_text(encoding='utf-8')
    runner_source = RUNNER.read_text(encoding='utf-8')
    display_lock_source = DISPLAY_LOCK.read_text(encoding='utf-8')
    ast.parse(display_lock_source, filename=str(DISPLAY_LOCK))
    if 'from consultation_v2.snapshot import build_snapshot' not in runner_source:
        errors.append(f'{RUNNER}: canonical snapshot builder is not wired')
    if 'write_selected_job_once(before, sink_root)' not in runner_source:
        errors.append(f'{RUNNER}: frozen one-action sink write is not wired')
    if 'selected_job_postcondition(before, after)' not in runner_source:
        errors.append(f'{RUNNER}: exact fresh postcondition is not wired')
    if "'status'," not in runner_source or "'--untracked-files=all'," not in runner_source:
        errors.append(f'{RUNNER}: clean tracked-and-untracked source provenance gate is missing')
    if runner_source.index('hands_commit = _current_commit()') > runner_source.rindex('with entrypoint_display_lock('):
        errors.append(f'{RUNNER}: clean source provenance must be established before display binding')
    required_runtime_args = {
        '--private-root',
        '--expected-transaction-sha256',
        '--requester',
        '--turn-id',
        '--correlation-id',
        '--process-generation',
        '--deadline-seconds',
    }
    if any(repr(arg) not in runner_source for arg in required_runtime_args):
        errors.append(f'{RUNNER}: Presence-injected runtime lineage arguments are incomplete')
    required_private_boundary = {
        'validate_external_private_root(args.private_root, REPO_ROOT)',
        'validate_new_private_output_beneath_root(',
        'read_private_input(',
        'validate_path_beneath_private_root(',
    }
    if any(token not in runner_source for token in required_private_boundary):
        errors.append(f'{RUNNER}: private-root containment boundary is incomplete')
    if "re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$')" not in runner_source:
        errors.append(f'{RUNNER}: turn/correlation grammar differs from Presence')
    if "re.compile(r'^[0-9a-f]{32}$')" not in runner_source:
        errors.append(f'{RUNNER}: process-generation grammar differs from Presence')
    if "_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')" not in runner_source:
        errors.append(f'{RUNNER}: permanent-claim digest grammar is not exact')
    if '_MAXIMUM_DEADLINE_SECONDS = 1700' not in runner_source:
        errors.append(f'{RUNNER}: internal deadline no longer preserves the Presence margin')
    if 'signal.setitimer(signal.ITIMER_REAL, 0.0)' not in runner_source:
        errors.append(f'{RUNNER}: internal deadline is not canceled before finalization')
    for token in (
        "'correlation_id': correlation_id",
        "'turn_lineage_sha256': turn_lineage_sha256",
        "'correlation_id_sha256': correlation_id_sha256",
        "'failure_code': failure_code",
    ):
        if token not in runner_source:
            errors.append(f'{RUNNER}: compact lineage/failure contract is missing {token}')
    claim_compare = 'transaction_sha256 != args.expected_transaction_sha256'
    if claim_compare not in runner_source:
        errors.append(f'{RUNNER}: permanent transaction claim is not compared')
    elif runner_source.index(claim_compare) > runner_source.rindex('with entrypoint_display_lock('):
        errors.append(f'{RUNNER}: permanent transaction claim must be checked before the lock')
    required_description_read = {
        "snapshot.mapped.get('about_job_heading')",
        "load_platform_yaml('linkedin')",
        'node.get_parent()',
        'node.get_child_at_index(index)',
        'node.get_text_iface()',
        "gi.require_version('Atspi', '2.0')",
        'Atspi.Text.get_character_count(text_iface)',
        'Atspi.Text.get_text(text_iface, 0, character_count)',
    }
    if any(token not in driver_source for token in required_description_read):
        errors.append(f'{DRIVER}: exact YAML-owned AT-SPI description read is incomplete')
    if (
        driver_source.count('node.get_parent()') != 1
        or driver_source.count('node.get_child_at_index(index)') != 1
    ):
        errors.append(f'{DRIVER}: description resolver must not become a tree walker')
    if 'match_counts' not in driver_source:
        errors.append(f'{DRIVER}: exact selector counts are not bound to observations')
    required_selection = {
        'activate_private_job_card',
        'observe_private_selected_job',
        'job_selection_barrier_policy',
        "action_contract.get('interface') != 'atspi_action'",
        "str(action_iface.get_action_name(index) or '') == action_name",
        'action_iface.do_action(action_index)',
        'element.name == exact_name',
        'element.role == role',
        'set(states).issubset(element.states)',
    }
    if any(token not in driver_source for token in required_selection):
        errors.append(f'{DRIVER}: private exact job-selection contract is incomplete')
    if 'from consultation_v2.interact import atspi_activate' in driver_source:
        errors.append(f'{DRIVER}: shared fallback action primitive is forbidden')

    runner_tree = ast.parse(runner_source, filename=str(RUNNER))
    lock_nodes = [
        node
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Name)
            and item.context_expr.func.id == 'entrypoint_display_lock'
            for item in node.items
        )
    ]
    if len(lock_nodes) != 1:
        errors.append(f'{RUNNER}: exactly one canonical entrypoint display lock is required')
    else:
        lock_node = lock_nodes[0]
        calls = [
            node.func.id
            for node in ast.walk(lock_node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        if (
            calls.count('_execute_locked_transaction') != 1
            or calls.count('_execute_engagement_transaction') != 1
        ):
            errors.append(f'{RUNNER}: each operation dispatcher must occur once inside the lock')
        if '_finalize' in calls:
            errors.append(f'{RUNNER}: receipt finalization must occur after display-lock cleanup')
    execute_node = next(
        node for node in runner_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == '_execute_locked_transaction'
    )
    execute_calls = [
        node.func.id
        for node in ast.walk(execute_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    if execute_calls.count('_bind_display') != 1:
        errors.append(f'{RUNNER}: display binding must occur once inside the locked transaction')
    if execute_calls.count('build_snapshot') != 3:
        errors.append(f'{RUNNER}: pre/barrier/post observations must use the canonical snapshot')
    if execute_calls.count('activate_private_job_card') != 1:
        errors.append(f'{RUNNER}: exact job-card action must occur once inside the lock')
    if execute_calls.count('write_selected_job_once') != 1:
        errors.append(f'{RUNNER}: the single sink action must occur inside the locked transaction')
    engagement_node = next(
        node for node in runner_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_execute_engagement_transaction'
    )
    engagement_calls = [
        node.func.id
        for node in ast.walk(engagement_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    if engagement_calls.count('_bind_display') != 1:
        errors.append(f'{RUNNER}: engagement display binding must occur once')
    for exact_call in (
        'activate_notifications',
        'stable_notifications_observation',
        'activate_my_posts',
        'stable_my_posts_observation',
        'exact_engagement_return',
    ):
        if engagement_calls.count(exact_call) != 1:
            errors.append(f'{RUNNER}: engagement must call {exact_call} exactly once')
    required_engagement_source = {
        "indexes != [0]",
        "action_iface.do_action(0)",
        "focus_firefox_pid(pid)",
        "press_key_cleared('ctrl+l')",
        "clipboard_paste(return_url)",
        "press_key_cleared('Return')",
        "build_snapshot('linkedin')",
        "'source_ref_sha256': _digest_text(source_ref)",
    }
    if any(token not in driver_source + runner_source for token in required_engagement_source):
        errors.append(f'{RUNNER}: exact engagement sequence or provenance is incomplete')
    if "'source_ref':" in driver_source:
        errors.append(f'{DRIVER}: source_ref must not enter stable signal identity')
    if (
        "readback = read_owned_private_bytes(artifact, 'engagement artifact')"
        not in driver_source
        or 'sha256_hex(readback) != observation.content_digest' not in driver_source
    ):
        errors.append(f'{DRIVER}: engagement sink lacks persisted-byte digest proof')
    routing_source = (PLATFORM_ROOT / 'routing.py').read_text(encoding='utf-8')
    if 'linkedin.com/feed/' in routing_source or 'linkedin.com/posts/' in routing_source:
        errors.append(f'{PLATFORM_ROOT / "routing.py"}: candidate URIs entered routing authority')
    if (
        'operation: str | None = None' not in runner_source
        or 'if operation is None:\n            raise' not in runner_source
    ):
        errors.append(f'{RUNNER}: unknown private operation does not fail before receipt fabrication')
    if 'def _restore_contract()' not in driver_source:
        errors.append(f'{DRIVER}: exact restore contract preflight is missing')
    if 'Back' in driver_source or 'go_back' in driver_source:
        errors.append(f'{DRIVER}: browser Back is forbidden for exact restoration')
    if "if lock.get('acquired') is not True" not in runner_source:
        errors.append(f'{RUNNER}: CAREERS fail-open must be rejected before UI access')
    if (
        "and not lineage['released']" not in runner_source
        or "and terminal['failure_code'] != 'sink_write_indeterminate'" not in runner_source
        or "terminal['failure_code'] = 'lock_release_indeterminate'" not in runner_source
    ):
        errors.append(f'{RUNNER}: lock-release demotion/preservation contract drifted')
    expected_failures = {
        'no_selected_job': {'selected_job_not_exact'},
        'postcondition_failed': {'postcondition_failed'},
        'technical_failure': {
            'deadline_expired',
            'display_lock_unavailable',
            'post_observation_indeterminate',
            'pre_observation_failed',
            'private_input_invalid',
            'sink_write_indeterminate',
        },
    }
    sink_indeterminate_terminals = 0
    for call in (
        node for node in ast.walk(runner_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {'_terminal_facts', '_finalize'}
    ):
        keywords = {item.arg: item.value for item in call.keywords if item.arg is not None}
        state_node = keywords.get('terminal_state')
        failure_node = keywords.get('failure_code')
        ok_node = keywords.get('ok')
        if not isinstance(failure_node, ast.Constant) or not isinstance(ok_node, ast.Constant):
            continue
        failure_code = failure_node.value
        ok = ok_node.value
        if failure_code == 'sink_write_indeterminate':
            sink_indeterminate_terminals += 1
            records_written_node = keywords.get('records_written')
            if (
                not isinstance(records_written_node, ast.Constant)
                or records_written_node.value is not None
            ):
                errors.append(
                    f'{RUNNER}:{call.lineno}: sink indeterminacy must report unknown writes'
                )
        if isinstance(state_node, ast.Constant) and isinstance(state_node.value, str):
            state = state_node.value
            if ok is False and failure_code not in expected_failures.get(state, set()):
                errors.append(
                    f'{RUNNER}:{call.lineno}: {state}/{failure_code} failure mapping drifted'
                )
        elif ok is True and failure_code is not None:
            errors.append(f'{RUNNER}:{call.lineno}: success must use a null failure code')
    if sink_indeterminate_terminals != 2:
        errors.append(f'{RUNNER}: sink timeout and exception terminals must both be indeterminate')
    run_node = next(
        node for node in runner_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == 'run'
    )
    for return_node in (
        node for node in ast.walk(run_node) if isinstance(node, ast.Return)
    ):
        if not (
            isinstance(return_node.value, ast.Call)
            and isinstance(return_node.value.func, ast.Name)
            and return_node.value.func.id in {'_finalize', '_finalize_engagement'}
        ):
            errors.append(f'{RUNNER}: every run terminal must pass through immutable receipt finalization')
            break
    if 'lock_record["released"] = released is True' not in display_lock_source:
        errors.append(f'{DISPLAY_LOCK}: yielded lock record does not expose the release verdict')
    for caller in DISPLAY_LOCK_CALLERS:
        source = caller.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(caller))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'entrypoint_display_lock'
        ]
        if len(calls) != 1:
            errors.append(f'{caller}: expected one canonical display-lock call')
    return errors


def validate() -> list[str]:
    errors: list[str] = []
    errors.extend(_validate_schema(SCHEMAS['request'], {'operation'}))
    errors.extend(_validate_schema(
        SCHEMAS['private_input_v1'],
        {'schema', 'operation', 'sink_ref'},
        {
            'search_ref', 'target_card_name', 'detail_title_name',
            'detail_company_name', 'source_ref', 'notifications_name',
            'return_url',
        },
    ))
    errors.extend(_validate_schema(
        SCHEMAS['engagement_private_input_v2'],
        {'schema', 'operation', 'source_ref', 'sink_ref', 'return_url'},
    ))
    errors.extend(_validate_schema(SCHEMAS['result'], {
        'ok', 'platform', 'display', 'state', 'failure_code', 'records_observed',
        'records_written', 'content_digest', 'receipt_sha256', 'turn_lineage_sha256'
    }))
    errors.extend(_validate_schema(
        SCHEMAS['receipt'],
        {
            'schema', 'platform', 'operation', 'display', 'requester',
            'turn_lineage_sha256', 'correlation_id_sha256', 'deadline_seconds',
            'hands_commit', 'terminal_state', 'ok', 'failure_code',
            'transaction_sha256', 'expected_transaction_sha256',
            'search_ref_sha256', 'sink_ref_sha256',
            'pre_observation_sha256', 'pre_match_counts', 'lock', 'action',
            'postcondition',
        },
        {'selection'},
    ))
    errors.extend(_validate_schema(SCHEMAS['engagement_result'], {
        'ok', 'platform', 'display', 'state', 'failure_code', 'records_observed',
        'records_written', 'content_digest', 'receipt_sha256',
        'turn_lineage_sha256', 'restore_verified',
    }))
    errors.extend(_validate_schema(SCHEMAS['engagement_receipt_v1'], {
        'schema', 'platform', 'operation', 'display', 'requester',
        'turn_lineage_sha256', 'correlation_id_sha256', 'deadline_seconds',
        'hands_commit', 'yaml_sha256', 'terminal_state', 'ok', 'failure_code',
        'records_observed', 'records_written', 'content_digest',
        'restore_verified', 'transaction_sha256', 'expected_transaction_sha256',
        'source_ref_sha256', 'sink_ref_sha256', 'notifications_name_sha256',
        'return_url_sha256', 'start', 'notifications_action',
        'notifications_postcondition', 'my_posts_action',
        'my_posts_postcondition', 'candidate', 'sink',
        'signal_postcondition', 'restore', 'lock',
    }))
    errors.extend(_validate_schema(SCHEMAS['engagement_receipt_v2'], {
        'schema', 'platform', 'operation', 'display', 'requester',
        'turn_lineage_sha256', 'correlation_id_sha256', 'deadline_seconds',
        'hands_commit', 'yaml_sha256', 'terminal_state', 'ok', 'failure_code',
        'records_observed', 'records_written', 'content_digest',
        'restore_verified', 'transaction_sha256', 'expected_transaction_sha256',
        'source_ref_sha256', 'sink_ref_sha256',
        'return_url_sha256', 'start', 'notifications_action',
        'notifications_postcondition', 'my_posts_action',
        'my_posts_postcondition', 'candidate', 'sink',
        'signal_postcondition', 'restore', 'lock',
    }))
    errors.extend(_validate_yaml())
    errors.extend(_validate_interface_patterns())
    errors.extend(_validate_engagement_schema_fixtures())
    errors.extend(_validate_restore_projection())
    errors.extend(_validate_runtime_source())
    from consultation_v2.yaml_contract import clear_yaml_cache, load_platform_yaml

    clear_yaml_cache()
    try:
        load_platform_yaml('linkedin')
    except Exception as exc:
        errors.append(f'linkedin YAML does not load through canonical loader: {exc}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate the LinkedIn Jobs read-only contract.')
    parser.parse_args()
    errors = validate()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print('linkedin jobs contract: valid')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
