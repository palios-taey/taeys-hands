#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.ats.provider_contract import PROVIDERS, load_provider_spec  # noqa: E402
from consultation_v2.ats.read_only import (  # noqa: E402
    Rect,
    compile_read_only_transition,
    project_required_fields,
)
from consultation_v2.ats.route_contract import RouteContractError, match_provider_route  # noqa: E402


BASELINE_SHA256 = {
    'consultation_v2/snapshot.py': 'd3780f73e5528576df4941fbc6268a754ba8abd6b6d08299f35ccee54cba5f9a',
    'consultation_v2/yaml_contract.py': '580c07a2dd016596f63c34d96caaed92b799b4acfe369380ae80d755b79e3721',
    'consultation_v2/platforms/routing.py': '9fcfbcf70c50c41cd8ca17e826f80fcdb38df8277a09afdfba170ed8d8988b68',
    'consultation_v2/primitives.py': 'e0a0bcc21456f3a3d6d94b4bccbbe485020485c43bd187b3f36682443fed0d71',
    'consultation_v2/interact.py': '1f4c1e871248e98c8d5a4d6234d7ebcef4847aa49c19c3e27691cb2edca43abd',
    'consultation_v2/supervised_ui_contract.py': 'f3be0eeb6c4535529a5e0acf6778335cde9f446b368dadd998b0e75ede7dfcc3',
    'consultation_v2/supervised_ui_seat.py': '5b8517541a4d6ead65b411e8bd18b9d153d873c95dacea10dd1162d46d032efd',
    'consultation_v2/supervised_ui_receipts.py': '30a8afe01ce76e40483ed7de32cc73bb1c0da0192576f94e69528858e9394880',
    'scripts/run_supervised_ui_seat.py': 'a454355f4c5dab4f1ce3b7d960522c58b6f106d8f1baf2eb7590d1699e9cd362',
    'consultation_v2/platforms/chatgpt/supervised_ui.yaml': '50d307f0cd265de420aef6ece6985baa2943a213508fba40dbed0a9e4513e2ba',
    'consultation_v2/platforms/claude/supervised_ui.yaml': '02ce600e094f0565102fb5ecb97cc7638e50eef14ee963a9592c54a2247d9668',
    'consultation_v2/platforms/gemini/supervised_ui.yaml': '02ce600e094f0565102fb5ecb97cc7638e50eef14ee963a9592c54a2247d9668',
    'consultation_v2/platforms/grok/supervised_ui.yaml': '02ce600e094f0565102fb5ecb97cc7638e50eef14ee963a9592c54a2247d9668',
    'consultation_v2/platforms/perplexity/supervised_ui.yaml': 'fd8c76a22eb3a9f5e59dc5dd3b40c85eeda682f0ecd91cbe3db347bbdcfb8400',
}

NEW_PYTHON = (
    'consultation_v2/ats/provider_contract.py',
    'consultation_v2/ats/route_contract.py',
    'consultation_v2/ats/read_only.py',
    'scripts/run_ats_read_only_qualification.py',
)
FORBIDDEN_CALLS = frozenset({
    'activate',
    'atspi_activate',
    'atspi_click',
    'atspi_focus',
    'atspi_mapped_pointer_activate',
    'click',
    'focus',
    'key',
    'navigate',
    'paste',
    'press',
    'scroll_element_into_view',
    'type_text',
    'write',
})
PRIVATE_TEXT = re.compile(
    r'(?:/home/|/tmp/|\b(?:10|127|169\.254|172\.(?:1[6-9]|2[0-9]|3[01])|192\.168)\.'
    r'|apply-machine|careers_(?:db|kb)|\bJesse\b|@)',
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_baseline_unchanged() -> None:
    errors = []
    for relative, expected in BASELINE_SHA256.items():
        path = REPO_ROOT / relative
        if not path.is_file() or path.is_symlink():
            errors.append(f'baseline path missing or unsafe: {relative}')
        elif _sha256(path) != expected:
            errors.append(f'baseline path changed: {relative}')
    if errors:
        raise RuntimeError('; '.join(errors))


def _assert_specs_public_and_read_only() -> None:
    executable = []
    for provider in PROVIDERS:
        spec = load_provider_spec(provider)
        source = spec.path.read_text(encoding='utf-8')
        if PRIVATE_TEXT.search(source):
            raise RuntimeError(f'{provider} provider spec contains private/operator-local text')
        if spec.executable:
            executable.append(provider)
        if spec.document['authorities'] != {'fill': False, 'upload': False, 'submit': False}:
            raise RuntimeError(f'{provider} provider grants mutation authority')
        transition = compile_read_only_transition(spec)
        if transition != {
            'schema': 'ats_compiled_transition_v1',
            'grammar': 'ui_action',
            'operation': 'observe',
            'call': {'op': 'observe'},
            'effect_class': 'read_only',
            'traversal_primitive': 'consultation_v2.tree.find_elements',
            'match_primitive': 'consultation_v2.snapshot.matches_spec',
            'next': 'terminal',
        }:
            raise RuntimeError(f'{provider} provider transition escaped the read-only lifecycle')
    if executable != ['greenhouse']:
        raise RuntimeError(f'executable ATS provider set must be greenhouse only, got {executable}')


def _assert_no_action_calls() -> None:
    def dotted_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            if parent:
                return f'{parent}.{node.attr}'
        return None

    for relative in NEW_PYTHON:
        path = REPO_ROOT / relative
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_path = dotted_name(node.func)
            if call_path is None or call_path == 'sys.stdout.buffer.write':
                continue
            call_name = call_path.rsplit('.', 1)[-1]
            if call_name in FORBIDDEN_CALLS:
                raise RuntimeError(f'{relative}:{node.lineno} calls forbidden UI mutation {call_path}')


def _reject(spec_name: str, url: str) -> None:
    spec = load_provider_spec(spec_name)
    try:
        match_provider_route(spec, url)
    except RouteContractError:
        return
    raise RuntimeError(f'{spec_name} route accepted invalid URL {url!r}')


def _assert_route_contract() -> None:
    cases = {
        'greenhouse': (
            'https://boards.greenhouse.io/example/jobs/123456',
            'hosted_job',
        ),
        'lever': (
            'https://jobs.lever.co/example/position-123',
            'hosted_job',
        ),
        'ashby': (
            'https://jobs.ashbyhq.com/example/123e4567-e89b-42d3-a456-426614174000',
            'hosted_job',
        ),
        'workday': (
            'https://example.myworkdayjobs.com/board/job/location/REQ-123',
            'hosted_job',
        ),
    }
    for provider, (url, grammar_id) in cases.items():
        match = match_provider_route(load_provider_spec(provider), url)
        if match.grammar_id != grammar_id or len(match.application_identity_sha256) != 64:
            raise RuntimeError(f'{provider} exact route binding is invalid')
    greenhouse = load_provider_spec('greenhouse')
    repeated = match_provider_route(
        greenhouse,
        'https://job-boards.greenhouse.io/example/jobs/123456?gh_jid=123456',
    )
    if repeated.grammar_id != 'hosted_job_with_identity_query':
        raise RuntimeError('Greenhouse repeated identity query did not bind exactly')
    padded_embed = match_provider_route(
        greenhouse,
        'https://job-boards.greenhouse.io/embed/job_app?for=example&validityToken=abc_123%3D%3D&token=123456',
    )
    if padded_embed.grammar_id != 'embedded_application_with_validity':
        raise RuntimeError('Greenhouse padded validity token did not bind exactly')
    _reject('greenhouse', 'http://boards.greenhouse.io/example/jobs/123456')
    _reject('greenhouse', 'https://boards.greenhouse.io/example/jobs/123456?gh_jid=999999')
    _reject(
        'greenhouse',
        'https://boards.greenhouse.io/example/jobs/123456?gh_jid=123456&gh_jid=123456',
    )
    _reject('greenhouse', 'https://boards.greenhouse.io.evil.invalid/example/jobs/123456')
    _reject('greenhouse', 'https://boards.greenhouse.io:bad/example/jobs/123456')
    _reject('greenhouse', 'https://[broken/example/jobs/123456')
    _reject(
        'greenhouse',
        'https://job-boards.greenhouse.io/embed/job_app?for=example&validityToken=abc%3Ddef&token=123456',
    )
    _reject('workday', 'https://myworkdayjobs.com/board/job/location/REQ-123')


def _assert_projection_contract() -> None:
    common = ['showing', 'visible', 'enabled']
    required = [*common, 'required', 'editable', 'focusable']
    elements = [
        {
            'name': 'First Name',
            'role': 'entry',
            'states': required,
            'x': 120,
            'y': 200,
            'extent': {'x': 100, 'y': 180, 'width': 300, 'height': 40},
        },
        {
            'name': 'Last Name',
            'role': 'entry',
            'states': required,
            'x': 120,
            'y': 260,
            'extent': {'x': 100, 'y': 240, 'width': 300, 'height': 40},
        },
        {
            'name': 'Submit application',
            'role': 'push button',
            'states': common,
            'x': 120,
            'y': 700,
            'extent': {'x': 100, 'y': 680, 'width': 180, 'height': 40},
        },
        {
            'name': 'Country',
            'role': 'combo box',
            'states': required,
            'x': 120,
            'y': 80,
            'extent': {'x': 100, 'y': 60, 'width': 300, 'height': 3},
        },
    ]
    spec = load_provider_spec('greenhouse')
    route = match_provider_route(spec, 'https://boards.greenhouse.io/example/jobs/123456')
    fields = project_required_fields(
        spec,
        route,
        [elements[0], elements[1], elements[3]],
        Rect(0, 100, 1000, 800),
        b'v' * 32,
    )
    if len(fields) != 3:
        raise RuntimeError('required-field projection cardinality changed')
    if any(field['operations'] for field in fields):
        raise RuntimeError('read-only projection exposed a field operation')
    combo = next(field for field in fields if field['role'] == 'combo box')['combo_safety']
    if combo != {
        'geometry': 'refused',
        'refusal': 'combo_rect_outside_document_rect',
        'scroll_frontier': True,
        'activation_authority': 'none',
    }:
        raise RuntimeError('off-document combo refusal/frontier invariant changed')
    if any('name' in field or 'value' in field for field in fields):
        raise RuntimeError('required-field projection leaked dynamic names or values')
    scrolled_document = Rect(390, -2813, 840, 7137)
    if not scrolled_document.valid or not scrolled_document.contains(Rect(500, 60, 300, 40)):
        raise RuntimeError('scrolled active-document geometry was rejected')
    if Rect(-1, -1, -1, -1).valid:
        raise RuntimeError('invalid AT-SPI extent sentinel was accepted')
    if spec.document['authorities'] != {'fill': False, 'upload': False, 'submit': False}:
        raise RuntimeError('read-only projection granted mutation authority')


def main() -> int:
    _assert_baseline_unchanged()
    _assert_specs_public_and_read_only()
    _assert_no_action_calls()
    _assert_route_contract()
    _assert_projection_contract()
    print(
        'ATS PROVIDER READ-ONLY GATE PASS — 4 strict public specs; Greenhouse observe-only; '
        '0 mutation calls; shared/P0 baselines byte-identical.'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
