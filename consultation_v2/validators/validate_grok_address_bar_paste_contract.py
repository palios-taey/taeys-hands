#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
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


def function_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


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
    names = function_names(source)
    assert '_address_bar_exact_paste_values' in names
    assert '_address_bar_exact_paste_proof' in names
    assert 'address_bar_observed_text' in source
    assert 'address_bar_matched_value' in source
    assert '_navigation_tree_ready(settled_snapshot)' in source
    assert '_navigation_target_loaded(current, url)' in source

    sys.path.insert(0, str(REPO_ROOT))
    from consultation_v2.runtime import ConsultationRuntime

    runtime = object.__new__(ConsultationRuntime)
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
