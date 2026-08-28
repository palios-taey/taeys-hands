#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = REPO_ROOT / 'consultation_v2' / 'runtime.py'
PLATFORM_ROOT = REPO_ROOT / 'consultation_v2' / 'platforms'
GROK_YAML = PLATFORM_ROOT / 'grok' / 'grok.yaml'
FRESH_URL = 'https://grok.com/'
EXACT_VALUES = [FRESH_URL, 'grok.com']


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(value, dict), f'{path}: expected mapping'
    return value


def runtime_under_test(source: str) -> tuple[type, set[str]]:
    tree = ast.parse(source)
    runtime_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'ConsultationRuntime'
    )
    selected_names = {
        '_address_bar_exact_paste_values',
        '_address_bar_exact_paste_proof',
    }
    selected = [
        node
        for node in runtime_class.body
        if isinstance(node, ast.FunctionDef) and node.name in selected_names
    ]
    assert {node.name for node in selected} == selected_names
    isolated = ast.Module(
        body=[
            ast.ClassDef(
                name='RuntimeUnderTest',
                bases=[],
                keywords=[],
                body=selected,
                decorator_list=[],
            )
        ],
        type_ignores=[],
    )
    namespace: dict[str, object] = {}
    exec(compile(ast.fix_missing_locations(isolated), str(RUNTIME_PATH), 'exec'), namespace)
    return namespace['RuntimeUnderTest'], selected_names


def bind_entry(runtime: object, *, text: str, focused: bool = True) -> None:
    entry = SimpleNamespace(
        text=text,
        states=['focused'] if focused else [],
    )
    runtime._address_bar_entry = MethodType(lambda self: entry, runtime)


def main() -> int:
    grok = load_yaml(GROK_YAML)
    urls = grok.get('urls') or {}
    assert urls.get('fresh') == FRESH_URL
    assert urls.get('address_bar_exact_paste_values') == EXACT_VALUES

    source = RUNTIME_PATH.read_text(encoding='utf-8')
    runtime_type, names = runtime_under_test(source)
    assert '_address_bar_exact_paste_values' in names
    assert '_address_bar_exact_paste_proof' in names
    assert 'address_bar_observed_text' in source
    assert 'address_bar_matched_value' in source
    assert '_navigation_tree_ready(settled_snapshot)' in source
    assert '_navigation_target_loaded(current, url)' in source

    runtime = object.__new__(runtime_type)
    runtime.cfg = {'urls': {'fresh': FRESH_URL}}
    assert runtime._address_bar_exact_paste_values(FRESH_URL) == (FRESH_URL,)

    runtime.cfg = {
        'urls': {
            'fresh': FRESH_URL,
            'address_bar_exact_paste_values': EXACT_VALUES,
        }
    }
    allowed = runtime._address_bar_exact_paste_values(FRESH_URL)
    assert allowed == tuple(EXACT_VALUES)
    thread_url = 'https://grok.com/c/exact-thread'
    assert runtime._address_bar_exact_paste_values(thread_url) == (thread_url,)

    bind_entry(runtime, text=FRESH_URL)
    proof = runtime._address_bar_exact_paste_proof(allowed)
    assert proof == {
        'address_bar_observed_text': FRESH_URL,
        'address_bar_matched_value': FRESH_URL,
    }

    bind_entry(runtime, text='grok.com')
    proof = runtime._address_bar_exact_paste_proof(allowed)
    assert proof == {
        'address_bar_observed_text': 'grok.com',
        'address_bar_matched_value': 'grok.com',
    }

    bind_entry(runtime, text='http://grok.com/')
    proof = runtime._address_bar_exact_paste_proof(allowed)
    assert proof['address_bar_observed_text'] == 'http://grok.com/'
    assert proof['address_bar_matched_value'] is None

    bind_entry(runtime, text='grok.com', focused=False)
    assert runtime._address_bar_exact_paste_proof(allowed)[
        'address_bar_matched_value'
    ] is None

    invalid_values = (
        [],
        [FRESH_URL, FRESH_URL],
        ['grok.com'],
        [FRESH_URL, ''],
        [FRESH_URL, 7],
    )
    for values in invalid_values:
        runtime.cfg = {
            'urls': {
                'fresh': FRESH_URL,
                'address_bar_exact_paste_values': values,
            }
        }
        try:
            runtime._address_bar_exact_paste_values(FRESH_URL)
        except ValueError:
            pass
        else:
            raise AssertionError(f'invalid exact values accepted: {values!r}')

    print('PASS: Grok exact address-bar rendering contract')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
