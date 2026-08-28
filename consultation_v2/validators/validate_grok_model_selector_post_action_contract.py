#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.yaml_contract import load_platform_yaml


EXPECTED_ELEMENTS = (
    'model_auto',
    'model_fast',
    'model_expert',
    'model_heavy',
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    cfg = load_platform_yaml('grok')
    workflow = cfg.get('workflow') or {}
    element_map = ((cfg.get('tree') or {}).get('element_map') or {})
    model_menu = ((((workflow.get('selection') or {}).get('menus') or {}).get('model')) or {})
    operate = model_menu.get('operate') or {}
    options = model_menu.get('options') or {}
    policy = workflow.get('model_selector_post_action') or {}

    require(
        operate == {
            'trigger': 'model_selector',
            'scope': 'app_root_snapshot',
            'open_method': 'mapped_pointer_activate',
        },
        'Grok model selector operation drifted',
    )
    require(
        tuple(sorted(str(option.get('element') or '') for option in options.values()))
        == tuple(sorted(EXPECTED_ELEMENTS)),
        'Grok model menu options do not match the exact post-action projection',
    )
    require(
        policy == {
            'trigger': 'model_selector',
            'scope': 'app_root_snapshot',
            'refresh_policy': 'live_reacquire_no_clear',
            'exact_singletons': list(EXPECTED_ELEMENTS),
            'required_states': ['showing', 'focusable', 'enabled'],
            'absent': ['grok_bot_dialog', 'grok_bot_dismiss', 'grok_bot_get'],
            'stable_cycles': 2,
            'interval_ms': 250,
            'timeout_ms': 8000,
        },
        'Grok model-selector post-action policy drifted',
    )
    require(
        policy['trigger'] == operate['trigger'] and policy['scope'] == operate['scope'],
        'Grok post-action policy is detached from its selector operation',
    )
    for element in EXPECTED_ELEMENTS:
        spec = element_map.get(element) or {}
        require(spec.get('role') == 'menu item', f'{element} role is not current AT-SPI menu item')
        require(
            spec.get('scope') == 'app_root_snapshot',
            f'{element} escaped the live app-root scope',
        )
        require(
            isinstance(spec.get('name'), str) and spec['name'],
            f'{element} lost its exact accessible name',
        )

    validations = cfg.get('validation') or {}
    require(
        not ({'auto_active', 'fast_active', 'expert_active', 'heavy_active'} & set(validations)),
        'obsolete checked/radio active-model validation contradicts click_only recognition',
    )
    print('grok model-selector post-action contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
