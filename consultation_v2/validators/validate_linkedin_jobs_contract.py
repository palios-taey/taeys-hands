#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
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
    'private_input': PLATFORM_ROOT / 'private-input.schema.json',
    'receipt': PLATFORM_ROOT / 'receipt.schema.json',
}
FORBIDDEN_RUNTIME_TOKENS = (
    'find_elements',
    'get_child_at_index',
    'get_extents',
    'Atspi',
    'xdotool',
    'pyautogui',
    'clipboard',
    'click(',
    '.x',
    '.y',
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return value


def _validate_schema(path: Path, required: set[str]) -> list[str]:
    errors: list[str] = []
    schema = _load_json(path)
    if schema.get('$schema') != 'https://json-schema.org/draft/2020-12/schema':
        errors.append(f'{path}: schema draft is not pinned')
    if schema.get('type') != 'object' or schema.get('additionalProperties') is not False:
        errors.append(f'{path}: root must be an exact object')
    properties = schema.get('properties')
    if not isinstance(properties, dict) or set(properties) != required:
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
        'active_job_details_jump',
        'about_job_heading',
        'selected_job_article',
    }:
        errors.append(f'{YAML_PATH}: selected-job map keys drifted')
    exact_expected = {
        'active_job_details_jump': ('Jump to active job details', 'push button'),
        'about_job_heading': ('About the job', 'heading'),
    }
    for key, (name, role) in exact_expected.items():
        spec = element_map.get(key) or {}
        if spec.get('name') != name or spec.get('role') != role:
            errors.append(f'{YAML_PATH}: {key} is not exact name+role')
    article = element_map.get('selected_job_article') or {}
    if article.get('role') != 'article' or article.get('states_include') != ['showing']:
        errors.append(f'{YAML_PATH}: selected article is not exact role+state')
    about = element_map.get('about_job_heading') or {}
    if about.get('structural') != {'parent': 'selected_job_article', 'ordinal': 'first'}:
        errors.append(f'{YAML_PATH}: About heading lost its direct-parent structural anchor')
    forbidden = {'contains', 'regex', 'fuzzy', 'name_contains', 'name_pattern'}
    if any(key in forbidden for spec in element_map.values() for key in spec):
        errors.append(f'{YAML_PATH}: fuzzy matcher grammar is forbidden')
    workflow = document.get('workflow') or {}
    expected_workflow = {
        'operation': 'capture_selected_job',
        'observation': 'canonical_snapshot',
        'required_elements': [
            'active_job_details_jump',
            'about_job_heading',
            'selected_job_article',
        ],
        'action': 'private_sink_write_once',
        'postcondition': 'selected_job_content_digest_unchanged',
    }
    if workflow.get('selected_job_read') != expected_workflow:
        errors.append(f'{YAML_PATH}: frozen transaction workflow drifted')
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
    return errors


def _validate_runtime_source() -> list[str]:
    errors: list[str] = []
    for path in (DRIVER, RUNNER):
        source = path.read_text(encoding='utf-8')
        ast.parse(source, filename=str(path))
        for token in FORBIDDEN_RUNTIME_TOKENS:
            if token in source:
                errors.append(f'{path}: forbidden runtime token {token!r}')
    driver_source = DRIVER.read_text(encoding='utf-8')
    runner_source = RUNNER.read_text(encoding='utf-8')
    display_lock_source = DISPLAY_LOCK.read_text(encoding='utf-8')
    ast.parse(display_lock_source, filename=str(DISPLAY_LOCK))
    if 'from consultation_v2.snapshot import build_snapshot' not in runner_source:
        errors.append(f'{RUNNER}: canonical snapshot builder is not wired')
    if runner_source.count("build_snapshot('linkedin')") != 2:
        errors.append(f'{RUNNER}: transaction must make exactly pre/post canonical observations')
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
    if runner_source.count('with _internal_deadline(deadline_at):') != 3:
        errors.append(f'{RUNNER}: pre/action/post stages must share three bounded deadline scopes')
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
    if 'Snapshot' not in driver_source or "count != 1" not in driver_source:
        errors.append(f'{DRIVER}: driver must consume mapped canonical Snapshot refs')
    if 'match_counts' not in driver_source:
        errors.append(f'{DRIVER}: exact selector counts are not bound to observations')

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
        if calls.count('_execute_locked_transaction') != 1:
            errors.append(f'{RUNNER}: the frozen transaction must execute once inside the lock')
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
    if execute_calls.count('build_snapshot') != 2:
        errors.append(f'{RUNNER}: both canonical observations must occur inside the locked transaction')
    if execute_calls.count('write_selected_job_once') != 1:
        errors.append(f'{RUNNER}: the single sink action must occur inside the locked transaction')
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
            and return_node.value.func.id == '_finalize'
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
    errors.extend(_validate_schema(SCHEMAS['private_input'], {
        'schema', 'operation', 'search_ref', 'sink_ref'
    }))
    errors.extend(_validate_schema(SCHEMAS['result'], {
        'ok', 'platform', 'display', 'state', 'failure_code', 'records_observed',
        'records_written', 'content_digest', 'receipt_sha256', 'turn_lineage_sha256'
    }))
    errors.extend(_validate_schema(SCHEMAS['receipt'], {
        'schema', 'platform', 'operation', 'display', 'requester',
        'turn_lineage_sha256', 'correlation_id_sha256', 'deadline_seconds',
        'hands_commit', 'terminal_state', 'ok', 'failure_code',
        'transaction_sha256', 'expected_transaction_sha256',
        'search_ref_sha256', 'sink_ref_sha256',
        'pre_observation_sha256', 'pre_match_counts', 'lock', 'action', 'postcondition'
    }))
    errors.extend(_validate_yaml())
    errors.extend(_validate_interface_patterns())
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
