from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from consultation_v2.types import Choice, ConsultationRequest
from consultation_v2.yaml_contract import load_platform_yaml


PLACEHOLDER_RATIONALES = frozenset({
    'n/a',
    'na',
    'none',
    'default',
    'not needed',
    'not applicable',
    'no',
    'nothing',
    'skip',
})
MIN_RATIONALE_CHARS = 15


@dataclass(frozen=True)
class SelectionPlanError(ValueError):
    findings: tuple[str, ...]

    def __str__(self) -> str:
        return '; '.join(self.findings)


def selection_menus(platform: str) -> dict[str, Any]:
    cfg = load_platform_yaml(platform)
    selection = ((cfg.get('workflow') or {}).get('selection') or {})
    menus = selection.get('menus') or {}
    if not isinstance(menus, dict) or not menus:
        raise SelectionPlanError((f'{platform} workflow.selection.menus is not declared',))
    return menus


def has_selection_menus(platform: str) -> bool:
    cfg = load_platform_yaml(platform)
    selection = ((cfg.get('workflow') or {}).get('selection') or {})
    menus = selection.get('menus')
    return isinstance(menus, dict) and bool(menus)


def normalize_choice(raw: Any) -> Choice:
    if isinstance(raw, Choice):
        return raw
    if isinstance(raw, dict):
        return Choice(value=raw.get('value'), because=str(raw.get('because') or ''))
    return Choice(value=raw, because='')


def build_selection_plan(request: ConsultationRequest) -> list[dict[str, Any]]:
    cfg = load_platform_yaml(request.platform)
    selection = ((cfg.get('workflow') or {}).get('selection') or {})
    menus = selection.get('menus') or {}
    if not isinstance(menus, dict) or not menus:
        raise SelectionPlanError((f'{request.platform} workflow.selection.menus is not declared',))
    defaults = (cfg.get('workflow') or {}).get('defaults') or {}
    selections = {
        str(menu_key): normalize_choice(choice)
        for menu_key, choice in (request.selections or {}).items()
    }
    findings: list[str] = []

    for menu_key in selections:
        if menu_key not in menus:
            findings.append(f'unknown selection menu {menu_key!r}')

    required = _required_menus(menus, followup=bool(request.session_url))
    _seed_default_selections(selections, defaults, required)
    for menu_key in required:
        if menu_key not in selections:
            findings.append(f'required selection menu {menu_key!r} is absent')

    plan: list[dict[str, Any]] = []
    followup = bool(request.session_url)
    for menu_key in _ordered_menu_keys(menus):
        if menu_key not in selections:
            continue
        menu = menus[menu_key]
        choice = selections[menu_key]
        plan.extend(_plan_menu(menu_key, menu, choice, followup, findings))

    if findings:
        raise SelectionPlanError(tuple(findings))
    return plan


def _seed_default_selections(
    selections: dict[str, Choice],
    defaults: dict[str, Any],
    required: tuple[str, ...],
) -> None:
    if not isinstance(defaults, dict):
        return
    for menu_key in required:
        if menu_key in selections or menu_key not in defaults:
            continue
        value = defaults.get(menu_key)
        if value is None:
            continue
        selections[menu_key] = Choice(value=value, because='workflow default')


def selection_plan_record(plan: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for step in plan:
        records.append({
            'menu': step['menu'],
            'option': step.get('option'),
            'value': step.get('value'),
            'because': step.get('because') or '',
            'skip': bool(step.get('skip')),
        })
    return records


def _required_menus(menus: dict[str, Any], *, followup: bool) -> tuple[str, ...]:
    if not followup:
        return tuple(menus.keys())
    return tuple(
        menu_key
        for menu_key, menu in menus.items()
        if isinstance(menu, dict) and menu.get('resettable_on_followup') is True
    )


def _ordered_menu_keys(menus: dict[str, Any]) -> tuple[str, ...]:
    keys = list(menus.keys())
    if 'model' in keys:
        keys.remove('model')
        return tuple(['model'] + keys)
    return tuple(keys)


def _plan_menu(
    menu_key: str,
    menu: dict[str, Any],
    choice: Choice,
    followup: bool,
    findings: list[str],
) -> list[dict[str, Any]]:
    if followup and menu.get('resettable_on_followup') is not True:
        findings.append(f'selection menu {menu_key!r} cannot be changed on follow-up sessions')
        return []

    select_kind = str(menu.get('select') or '')
    options = menu.get('options') or {}
    value = choice.value
    because = str(choice.because or '').strip()

    if isinstance(value, list):
        if select_kind != 'multi':
            findings.append(f'selection menu {menu_key!r} is single-select but received a list')
            return []
        option_keys = _validate_option_list(menu_key, options, value, findings)
        return [
            _step(menu_key, menu, option_key, list(value), because)
            for option_key in option_keys
        ]

    if not isinstance(value, str) or not value.strip():
        findings.append(f'selection menu {menu_key!r} value must be a non-empty option/default/none')
        return []
    value = value.strip()
    if select_kind == 'multi' and value not in {'default', 'none'}:
        findings.append(f'selection menu {menu_key!r} is multi-select and must receive a list, default, or none')
        return []

    if value in {'default', 'none'}:
        _validate_intentionality(menu_key, menu, value, because, followup, findings)
        resolved = menu.get('default_for_fresh') if value == 'default' else 'none'
        if resolved == 'none':
            return [_skip_step(menu_key, value, because)]
        if not isinstance(resolved, str) or resolved not in options:
            findings.append(f'selection menu {menu_key!r} default_for_fresh does not name an option or none')
            return []
        return [_step(menu_key, menu, resolved, value, because)]

    if value not in options:
        findings.append(f'unknown option {value!r} for selection menu {menu_key!r}')
        return []
    return [_step(menu_key, menu, value, value, because)]


def _validate_option_list(
    menu_key: str,
    options: dict[str, Any],
    values: list[Any],
    findings: list[str],
) -> tuple[str, ...]:
    if not values:
        findings.append(f'selection menu {menu_key!r} received an empty option list')
        return ()
    seen: set[str] = set()
    option_keys: list[str] = []
    for raw_value in values:
        if not isinstance(raw_value, str) or not raw_value.strip():
            findings.append(f'selection menu {menu_key!r} list values must be non-empty option keys')
            continue
        option_key = raw_value.strip()
        if option_key in {'default', 'none'}:
            findings.append(f'selection menu {menu_key!r} list cannot include {option_key!r}')
            continue
        if option_key in seen:
            findings.append(f'selection menu {menu_key!r} repeats option {option_key!r}')
            continue
        seen.add(option_key)
        if option_key not in options:
            findings.append(f'unknown option {option_key!r} for selection menu {menu_key!r}')
            continue
        option_keys.append(option_key)
    return tuple(option_keys)


def _validate_intentionality(
    menu_key: str,
    menu: dict[str, Any],
    value: str,
    because: str,
    followup: bool,
    findings: list[str],
) -> None:
    if menu.get('must_choose') is True:
        findings.append(f'selection menu {menu_key!r} must choose a real option; {value!r} is rejected')
        return
    if followup:
        return
    normalized = because.strip().lower()
    banned = set(PLACEHOLDER_RATIONALES)
    banned.add(menu_key.lower())
    example = str(menu.get('example_rationale') or '').strip()
    if example:
        banned.add(example.lower())
    if (
        not because
        or len(because) < MIN_RATIONALE_CHARS
        or normalized in banned
    ):
        findings.append(
            f'selection menu {menu_key!r} {value!r} requires a substantive because rationale'
        )


def _step(
    menu_key: str,
    menu: dict[str, Any],
    option_key: str,
    requested_value: Any,
    because: str,
) -> dict[str, Any]:
    option = (menu.get('options') or {})[option_key]
    return {
        'menu': menu_key,
        'option': option_key,
        'value': requested_value,
        'because': because,
        'select': menu['select'],
        'active_recognition': menu['active_recognition'],
        'operate': dict(menu['operate']),
        'element': option['element'],
        'active_element': option.get('active_element'),
        'active_trigger_names': list(option.get('active_trigger_names') or []),
        'click_strategy': option.get('click_strategy'),
        'path': [dict(item) for item in option.get('path') or []],
        'skip': False,
    }


def _skip_step(menu_key: str, requested_value: str, because: str) -> dict[str, Any]:
    return {
        'menu': menu_key,
        'option': None,
        'value': requested_value,
        'because': because,
        'skip': True,
    }
