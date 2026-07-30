from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import ModuleType
import urllib.parse
import urllib.request

from consultation_v2 import clipboard
from consultation_v2.snapshot import (
    build_app_root_snapshot,
    build_menu_snapshot,
    build_snapshot,
)
from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.yaml_contract import CHAT_PLATFORMS, load_platform_yaml


CONSULT_DISPLAYS = frozenset({
    ':2', ':3', ':4', ':5', ':6',
    ':20', ':21', ':22', ':23', ':24',
})
DEFAULT_ACT_PATH = Path('/home/mira/treasurer/scripts/loop/act.py')
DEFAULT_SYSTEM_PROMPT_PATH = Path('/home/mira/data/corpus/layer_1/SYSTEM_PROMPT.md')
DEFAULT_EP3_BASE = 'http://10.0.0.197:8000/v1'
DEFAULT_EP3_MODEL = 'ep3'
MAX_TURNS = 12
MAX_FULL_CONSULT_TURNS = 40
MAX_FRAMING_PROMPT_CHARACTERS = 600
DEFAULT_COMPLETION_TIMEOUT_SECONDS = 3600.0
PRE_EXECUTION_REJECTION = (
    'PRE_EXECUTION_CONTRACT_REJECTED; nothing executed; re-emit one '
    'consult_extract_action call that follows the exact-name requirements'
)
SOURCE_CONTROL_PATTERN = re.compile(r'^\s*([0-9]+)\s+sources?\s*$', re.IGNORECASE)
BODY_CITATION_PATTERN = re.compile(r'(?<!\^)\[([0-9]+)\]')
MARKDOWN_CITATION_PATTERN = re.compile(r'\[\^([0-9]+(?:_[0-9]+)*)\]')
MARKDOWN_SOURCE_DEFINITION_PATTERN = re.compile(
    r'^\[\^([0-9]+(?:_[0-9]+)*)\]:\s+(.+?)\s*$'
)
FILE_SOURCE_CONTROL_PATTERN = re.compile(r'^\s*Files\s+([0-9]+)\s*$', re.IGNORECASE)
MARKDOWN_EXPORT_NAME = 'Export as Markdown'
OVERFLOW_CONTROL_NAMES = ('Session actions', '...')
FULL_CONSULT_REQUIRED_STEPS = frozenset({
    'new_thread',
    'attach_trigger',
    'upload_item',
    'composer_input',
    'submit',
    'completion',
    'copy_response',
})
FULL_CONSULT_OPTIONAL_STEPS = frozenset({'post_submit'})
INTERACTIVE_ROLES = frozenset({
    'check box',
    'combo box',
    'entry',
    'link',
    'list item',
    'menu item',
    'push button',
    'radio button',
    'spin button',
    'toggle button',
})


class TaeyConsultExtractionError(RuntimeError):
    pass


class TaeyConsultControlError(TaeyConsultExtractionError):
    pass


class TaeyConsultStateError(TaeyConsultExtractionError):
    def __init__(self, required_action: dict[str, object]) -> None:
        self.required_action = dict(required_action)
        super().__init__(
            'action is out of phase; nothing executed; required_action='
            + json.dumps(
                self.required_action,
                ensure_ascii=True,
                sort_keys=True,
                separators=(',', ':'),
            )
        )


def consult_extract_action_tool() -> dict[str, object]:
    return {
        'type': 'function',
        'function': {
            'name': 'consult_extract_action',
            'description': (
                'Perform one state-bound action in the closed consultation seat. '
                'The harness owns the file path and short prompt; never emit their '
                'contents. Use find before control activation and finish only after '
                'the harness has captured the configured response surface.'
            ),
            'parameters': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['action', 'name', 'contains'],
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': [
                            'find',
                            'click',
                            'activate',
                            'focus',
                            'key',
                            'typeahead',
                            'paste_path',
                            'paste_prompt',
                            'select_mode',
                            'wait_complete',
                            'finish',
                        ],
                    },
                    'name': {
                        'type': 'string',
                        'description': (
                            'The required semantic step supplied by the harness, a '
                            'legacy exact accessible name for extraction-only mode, '
                            'or an empty string for paste_path, wait_complete, and '
                            'finish. paste_path ignores this field; select_mode uses '
                            'the exact select_mode semantic name.'
                        ),
                    },
                    'contains': {
                        'type': 'boolean',
                        'description': (
                            'Legacy extraction-only substring matching for find. '
                            'Full consultations and all activation actions use false.'
                        ),
                    },
                },
            },
        },
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _citation_ids(value: str) -> list[int]:
    identifiers = {
        int(item)
        for item in BODY_CITATION_PATTERN.findall(value or '')
    }
    for token in MARKDOWN_CITATION_PATTERN.findall(value or ''):
        source_id = token.rsplit('_', 1)[-1]
        if source_id.isdigit():
            identifiers.add(int(source_id))
    return sorted(identifiers)


def _without_markdown_source_definitions(value: str) -> str:
    kept: list[str] = []
    previous_blank = False
    for line in (value or '').splitlines():
        if MARKDOWN_SOURCE_DEFINITION_PATTERN.fullmatch(line.strip()):
            continue
        blank = not line.strip()
        if blank and previous_blank:
            continue
        kept.append(line)
        previous_blank = blank
    return '\n'.join(kept).strip()


def _markdown_sources(
    value: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    definitions: dict[int, str] = {}
    conflicts: list[dict[str, object]] = []
    conflict_keys: set[tuple[int, str]] = set()
    definition_count = 0
    for line in (value or '').splitlines():
        match = MARKDOWN_SOURCE_DEFINITION_PATTERN.fullmatch(line.strip())
        if match is None:
            continue
        definition_count += 1
        source_id = int(match.group(1).rsplit('_', 1)[-1])
        target = match.group(2).strip()
        previous = definitions.get(source_id)
        if previous is None:
            definitions[source_id] = target
            continue
        if previous == target:
            continue
        conflict_key = (source_id, target)
        if conflict_key in conflict_keys:
            continue
        conflict_keys.add(conflict_key)
        conflicts.append({
            'source_id': source_id,
            'kept_definition': previous,
            'ignored_definition': target,
            'resolution': 'first_definition_kept',
        })
    sources: list[dict[str, object]] = []
    for source_id, target in sorted(definitions.items()):
        parsed = urllib.parse.urlsplit(target)
        is_url = parsed.scheme in {'http', 'https'} and bool(parsed.netloc)
        sources.append({
            'index': source_id,
            'url': target if is_url else '',
            'title': target[:240],
            'kind': 'url' if is_url else 'file',
        })
    return sources, conflicts, definition_count


def _required_text(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding='utf-8')
    except OSError as exc:
        raise TaeyConsultExtractionError(
            f'{label} unavailable at {path}: {exc}'
        ) from exc
    if not value.strip():
        raise TaeyConsultExtractionError(f'{label} is empty at {path}')
    return value


def _endpoint(base: str) -> str:
    value = str(base or '').strip().rstrip('/')
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise TaeyConsultExtractionError(
            'TAEY_CONSULT_EP3_BASE must be an absolute HTTP(S) URL'
        )
    if value.endswith('/chat/completions'):
        return value
    if value.endswith('/v1'):
        return value + '/chat/completions'
    return value + '/v1/chat/completions'


def _load_act(path: Path) -> ModuleType:
    if not path.is_file():
        raise TaeyConsultExtractionError(f'canonical act.py is unavailable at {path}')
    spec = importlib.util.spec_from_file_location('_taey_consult_act', path)
    if spec is None or spec.loader is None:
        raise TaeyConsultExtractionError(f'could not load canonical act.py from {path}')
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise TaeyConsultExtractionError(
            f'canonical act.py import failed: {type(exc).__name__}: {exc}'
        ) from exc
    for name in (
        'find',
        'click',
        'do',
        'key',
        'paste_into',
        'current_url_atspi',
        'firefox_app',
        'node_label',
        'prune_inactive_document',
    ):
        if not callable(getattr(module, name, None)):
            raise TaeyConsultExtractionError(
                f'canonical act.py does not expose required callable {name!r}'
            )
    return module


def _full_consult_contract(
    platform: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    cfg = load_platform_yaml(platform)
    workflow = cfg.get('workflow') or {}
    full_consult = workflow.get('full_consult') if isinstance(workflow, dict) else None
    if not isinstance(full_consult, dict):
        raise TaeyConsultExtractionError(
            f'{platform} workflow.full_consult must be a mapping'
        )
    raw_steps = full_consult.get('steps')
    if not isinstance(raw_steps, dict):
        raise TaeyConsultExtractionError(
            f'{platform} workflow.full_consult.steps must be a mapping'
        )
    missing = sorted(FULL_CONSULT_REQUIRED_STEPS - set(raw_steps))
    unknown = sorted(
        set(raw_steps)
        - FULL_CONSULT_REQUIRED_STEPS
        - FULL_CONSULT_OPTIONAL_STEPS
    )
    if missing or unknown:
        raise TaeyConsultExtractionError(
            f'{platform} full-consult step vocabulary mismatch; '
            f'missing={missing}, unknown={unknown}'
        )
    element_map = ((cfg.get('tree') or {}).get('element_map') or {})
    if not isinstance(element_map, dict):
        raise TaeyConsultExtractionError(
            f'{platform} tree.element_map must be a mapping'
        )
    steps: dict[str, dict[str, object]] = {}
    for step_name, raw_step in raw_steps.items():
        if not isinstance(raw_step, dict):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} must be a mapping'
            )
        unknown_step_keys = sorted(
            set(raw_step)
            - {
                'elements',
                'sequence',
                'pick',
                'paste_strategy',
                'action',
                'settle_seconds',
            }
        )
        if unknown_step_keys:
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} has unsupported '
                f'keys {unknown_step_keys}'
            )
        element_keys = raw_step.get('elements')
        if (
            not isinstance(element_keys, list)
            or not element_keys
            or not all(isinstance(key, str) and key for key in element_keys)
        ):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} must declare '
                'a non-empty elements list'
            )
        for element_key in element_keys:
            spec = element_map.get(element_key)
            if not isinstance(spec, dict):
                raise TaeyConsultExtractionError(
                    f'{platform} full-consult step {step_name!r} references '
                    f'unknown element_map key {element_key!r}'
                )
            if not isinstance(spec.get('role'), str) or not spec.get('role'):
                raise TaeyConsultExtractionError(
                    f'{platform} full-consult element {element_key!r} has no exact role'
                )
            if not any(
                key in spec for key in ('name', 'names_any_of', 'structural')
            ):
                raise TaeyConsultExtractionError(
                    f'{platform} full-consult element {element_key!r} has no '
                    'exact or structural identity'
                )
        sequence = raw_step.get('sequence', False)
        if not isinstance(sequence, bool):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} sequence must be boolean'
            )
        pick = raw_step.get('pick')
        if pick not in {None, 'last_by_y'}:
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} has unsupported '
                f'pick strategy {pick!r}'
            )
        paste_strategy = raw_step.get('paste_strategy', 'act_paste')
        if paste_strategy not in {'act_paste', 'focus_and_paste'}:
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} has unsupported '
                f'paste strategy {paste_strategy!r}'
            )
        action = raw_step.get('action', 'click')
        if action not in {'click', 'activate'}:
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} has unsupported '
                f'action {action!r}'
            )
        settle_seconds = raw_step.get('settle_seconds', 0.3)
        if (
            not isinstance(settle_seconds, (int, float))
            or not 0.0 <= float(settle_seconds) <= 2.0
        ):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult step {step_name!r} has invalid '
                f'settle_seconds {settle_seconds!r}'
            )
        steps[str(step_name)] = {
            'elements': tuple(element_keys),
            'sequence': sequence,
            'pick': pick,
            'paste_strategy': paste_strategy,
            'action': action,
            'settle_seconds': float(settle_seconds),
        }
    attachment_present = full_consult.get('attachment_present') or {}
    if not isinstance(attachment_present, dict):
        raise TaeyConsultExtractionError(
            f'{platform} workflow.full_consult.attachment_present must be a mapping'
        )
    attachment_elements = attachment_present.get('elements') or []
    filename_roles = attachment_present.get('filename_roles') or []
    filename_value = attachment_present.get('filename_value', 'name')
    if (
        not isinstance(attachment_elements, list)
        or not all(isinstance(key, str) and key in element_map for key in attachment_elements)
        or not isinstance(filename_roles, list)
        or not all(isinstance(role, str) and role for role in filename_roles)
        or filename_value not in {'name', 'stem'}
        or not attachment_elements and not filename_roles
    ):
        raise TaeyConsultExtractionError(
            f'{platform} full-consult attachment_present must declare exact '
            'element keys or exact filename roles'
        )
    mode = full_consult.get('mode') or {}
    if not isinstance(mode, dict):
        raise TaeyConsultExtractionError(
            f'{platform} workflow.full_consult.mode must be a mapping'
        )
    if mode:
        if set(mode) != {'active', 'trigger', 'option'}:
            raise TaeyConsultExtractionError(
                f'{platform} full-consult mode must declare active/trigger/option'
            )
        for value in mode.values():
            if not isinstance(value, str) or value not in element_map:
                raise TaeyConsultExtractionError(
                    f'{platform} full-consult mode references unknown element {value!r}'
                )
    raw_select_mode = full_consult.get('select_mode')
    if not isinstance(raw_select_mode, list) or not raw_select_mode:
        raise TaeyConsultExtractionError(
            f'{platform} workflow.full_consult.select_mode must be a non-empty list'
        )
    selection = workflow.get('selection') or {}
    menus = selection.get('menus') if isinstance(selection, dict) else None
    if not isinstance(menus, dict):
        raise TaeyConsultExtractionError(
            f'{platform} workflow.selection.menus must be a mapping'
        )
    select_mode: list[dict[str, object]] = []
    for index, raw_selection in enumerate(raw_select_mode):
        if (
            not isinstance(raw_selection, dict)
            or set(raw_selection) != {'menu', 'option'}
        ):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult select_mode[{index}] must declare '
                'exactly menu/option'
            )
        menu_key = raw_selection.get('menu')
        option_key = raw_selection.get('option')
        menu = menus.get(menu_key) if isinstance(menu_key, str) else None
        options = menu.get('options') if isinstance(menu, dict) else None
        option = (
            options.get(option_key)
            if isinstance(options, dict) and isinstance(option_key, str)
            else None
        )
        operate = menu.get('operate') if isinstance(menu, dict) else None
        if not isinstance(option, dict) or not isinstance(operate, dict):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult select_mode[{index}] references '
                f'unknown selection {menu_key!r}={option_key!r}'
            )
        trigger = operate.get('trigger')
        target = option.get('element')
        active_element = option.get('active_element')
        path = option.get('path') or []
        referenced_elements = [trigger, target, active_element]
        referenced_elements.extend(
            step.get('element')
            for step in path
            if isinstance(step, dict)
        )
        if not all(
            value is None
            or isinstance(value, str) and value in element_map
            for value in referenced_elements
        ):
            raise TaeyConsultExtractionError(
                f'{platform} full-consult select_mode[{index}] references '
                'an unknown element_map key'
            )
        select_mode.append({
            'menu': str(menu_key),
            'option': str(option_key),
            'trigger': str(trigger),
            'target': str(target),
            'scope': str(operate.get('scope') or 'snapshot'),
            'active_recognition': str(
                menu.get('active_recognition') or ''
            ),
            'active_element': (
                str(active_element)
                if isinstance(active_element, str)
                else ''
            ),
            'active_trigger_names': tuple(
                str(value)
                for value in (option.get('active_trigger_names') or ())
            ),
            'click_strategy': str(
                option.get('click_strategy') or 'atspi_only'
            ),
            'path': tuple(
                {
                    'element': str(step.get('element') or ''),
                    'action': str(step.get('action') or ''),
                }
                for step in path
                if isinstance(step, dict)
            ),
        })
    failures = full_consult.get('failures') or []
    if (
        not isinstance(failures, list)
        or not all(
            isinstance(value, str) and value in element_map
            for value in failures
        )
    ):
        raise TaeyConsultExtractionError(
            f'{platform} full-consult failures must reference exact element keys'
        )
    return {
        'cfg': cfg,
        'steps': steps,
        'attachment_present': {
            'elements': tuple(attachment_elements),
            'filename_roles': tuple(filename_roles),
            'filename_value': filename_value,
        },
        'mode': dict(mode),
        'select_mode': tuple(select_mode),
        'failures': tuple(str(value) for value in failures),
    }, {
        str(key): dict(value)
        for key, value in element_map.items()
        if isinstance(value, dict)
    }


class TaeyConsultExtractionSeat:
    def __init__(
        self,
        *,
        platform: str,
        display: str,
        endpoint: str | None = None,
        model: str | None = None,
        act_path: str | Path | None = None,
        system_prompt_path: str | Path | None = None,
        capture_root: str | Path | None = None,
        attachment_path: str | Path | None = None,
        framing_prompt: str | None = None,
        completion_timeout: float = DEFAULT_COMPLETION_TIMEOUT_SECONDS,
    ) -> None:
        self.platform = str(platform or '').strip().lower()
        if self.platform not in CHAT_PLATFORMS:
            raise TaeyConsultExtractionError(
                f'consult extraction seat does not support {self.platform!r}'
            )
        self.full_consult_contract, self.element_map = _full_consult_contract(
            self.platform
        )
        self.cfg = dict(self.full_consult_contract['cfg'])
        self.display = str(display or '').strip()
        if self.display not in CONSULT_DISPLAYS:
            raise TaeyConsultExtractionError(
                f'consult extraction display must be one of {sorted(CONSULT_DISPLAYS)}'
            )
        self.endpoint = _endpoint(
            endpoint
            or os.environ.get('TAEY_CONSULT_EP3_BASE')
            or os.environ.get('APPLYMACHINE_EP3_BASE')
            or DEFAULT_EP3_BASE
        )
        self.model = str(
            model
            or os.environ.get('TAEY_CONSULT_EP3_MODEL')
            or os.environ.get('APPLYMACHINE_EP3_MODEL')
            or DEFAULT_EP3_MODEL
        ).strip()
        if not self.model:
            raise TaeyConsultExtractionError('Taey consult extraction model is empty')
        self.act_path = Path(
            act_path
            or os.environ.get('TAEY_CONSULT_ACT_PATH')
            or DEFAULT_ACT_PATH
        ).expanduser().resolve()
        self.system_prompt_path = Path(
            system_prompt_path
            or os.environ.get('TAEY_CONSULT_SYSTEM_PROMPT')
            or DEFAULT_SYSTEM_PROMPT_PATH
        ).expanduser().resolve()
        self.capture_root = (
            Path(capture_root).expanduser().resolve()
            if capture_root
            else Path(tempfile.mkdtemp(prefix='taey_consult_extract_'))
        )
        self._prepare_display_environment()
        self.act = _load_act(self.act_path)
        self.runtime = ConsultationRuntime(self.platform)
        self.system_prompt = _required_text(
            self.system_prompt_path,
            'Taey system prompt',
        )
        supplied_attachment = attachment_path is not None
        supplied_prompt = framing_prompt is not None
        if supplied_attachment != supplied_prompt:
            raise TaeyConsultExtractionError(
                'full consult requires both attachment_path and framing_prompt'
            )
        self.full_consult = supplied_attachment and supplied_prompt
        self.attachment_path: Path | None = None
        self.attachment_sha256 = ''
        self.framing_prompt = ''
        self.framing_prompt_sha256 = ''
        if self.full_consult:
            raw_attachment = Path(str(attachment_path)).expanduser()
            if not raw_attachment.is_absolute():
                raise TaeyConsultExtractionError(
                    'full consult attachment_path must be absolute'
                )
            self.attachment_path = raw_attachment.resolve()
            if not self.attachment_path.is_file():
                raise TaeyConsultExtractionError(
                    f'full consult attachment is unavailable: {self.attachment_path}'
                )
            try:
                attachment_bytes = self.attachment_path.read_bytes()
            except OSError as exc:
                raise TaeyConsultExtractionError(
                    f'full consult attachment could not be read: {exc}'
                ) from exc
            if not attachment_bytes:
                raise TaeyConsultExtractionError('full consult attachment is empty')
            self.attachment_sha256 = hashlib.sha256(attachment_bytes).hexdigest()
            self.framing_prompt = str(framing_prompt or '').strip()
            if not self.framing_prompt:
                raise TaeyConsultExtractionError(
                    'full consult framing prompt is empty'
                )
            if len(self.framing_prompt) > MAX_FRAMING_PROMPT_CHARACTERS:
                raise TaeyConsultExtractionError(
                    'full consult framing prompt exceeds '
                    f'{MAX_FRAMING_PROMPT_CHARACTERS} characters'
                )
            prompt_bytes = self.framing_prompt.encode('utf-8')
            if attachment_bytes.strip() == prompt_bytes.strip():
                raise TaeyConsultExtractionError(
                    'full consult framing prompt must not inline the attachment'
                )
            attachment_text = attachment_bytes.decode('utf-8', errors='ignore').strip()
            if (
                len(attachment_text) >= 80
                and attachment_text[:200] in self.framing_prompt
            ):
                raise TaeyConsultExtractionError(
                    'full consult framing prompt contains attachment content'
                )
            self.framing_prompt_sha256 = _sha256_text(self.framing_prompt)
        try:
            self.completion_timeout = float(completion_timeout)
        except (TypeError, ValueError) as exc:
            raise TaeyConsultExtractionError(
                'full consult completion_timeout must be numeric'
            ) from exc
        if not 30.0 <= self.completion_timeout <= 7200.0:
            raise TaeyConsultExtractionError(
                'full consult completion_timeout must be between 30 and 7200 seconds'
            )
        self.body = ''
        self.body_control = ''
        self.sources: list[dict[str, object]] = []
        self.expected_source_count = 0
        self.body_citation_ids: list[int] = []
        self.found_controls: set[tuple[str, str]] = set()
        self.full_consult_found: dict[str, dict[str, object]] = {}
        self.copy_contents_checked = False
        self.markdown_export_checked = False
        self.overflow_checked: set[str] = set()
        self.markdown_sources: list[dict[str, object]] = []
        self.markdown_source_conflicts: list[dict[str, object]] = []
        self.markdown_source_definition_count = 0
        self.download_path = ''
        self.download_sha256 = ''
        self.initial_session_url = ''
        self.fresh_thread_url = ''
        self.fresh_thread_opened = False
        self.attach_trigger_focused = False
        self.attach_trigger_activated = False
        self.upload_typeahead_entered = False
        self.upload_submit_key_index = 0
        self.upload_control_clicked = False
        self.dialog_location_opened = False
        self.dialog_path_selected = False
        self.attachment_path_pasted = False
        self.attachment_submitted = False
        self.attachment_verified = False
        self.prompt_entered = False
        self.mode_selected = False
        self.mode_evidence: list[dict[str, object]] = []
        self.submitted = False
        self.post_submitted = False
        self.consult_completed = False
        self.copy_response_index = 0
        self.browser_url_before_dialog = ''
        self.session_url_before = ''
        self.session_url_after = ''
        self.completion_evidence: dict[str, object] = {}
        self.actions: list[dict[str, object]] = []
        self.capture_root.mkdir(parents=True, exist_ok=True)
        self.turn_log_path = self.capture_root / 'turns.jsonl'
        if self.turn_log_path.exists():
            raise TaeyConsultExtractionError(
                f'capture log is not pristine: {self.turn_log_path}'
            )

    def _prepare_display_environment(self) -> None:
        bus_path = Path(f'/tmp/a11y_bus_{self.display}')
        bus = _required_text(bus_path, 'consult display AT-SPI bus').strip()
        current_display = str(os.environ.get('DISPLAY') or '').strip()
        if current_display and current_display != self.display:
            raise TaeyConsultExtractionError(
                f'process DISPLAY={current_display!r} does not match leased {self.display!r}'
            )
        current_bus = str(os.environ.get('AT_SPI_BUS_ADDRESS') or '').strip()
        if current_bus and current_bus != bus:
            raise TaeyConsultExtractionError(
                f'process AT_SPI_BUS_ADDRESS does not match {bus_path}'
            )
        os.environ['DISPLAY'] = self.display
        os.environ['AT_SPI_BUS_ADDRESS'] = bus

    def _append_turn_log(self, record: dict[str, object]) -> None:
        payload = {
            'at': dt.datetime.now(dt.UTC).isoformat(timespec='milliseconds'),
            **record,
        }
        with self.turn_log_path.open('a', encoding='utf-8') as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=True, sort_keys=True) + '\n'
            )
            handle.flush()
            os.fsync(handle.fileno())

    def _call_taey(
        self,
        messages: list[dict[str, object]],
        turn: int,
    ) -> dict[str, object]:
        tool = consult_extract_action_tool()
        payload = {
            'model': self.model,
            'messages': messages,
            'tools': [tool],
            'tool_choice': {
                'type': 'function',
                'function': {'name': 'consult_extract_action'},
            },
            'parallel_tool_calls': False,
            'chat_template_kwargs': {'enable_thinking': False},
            'stream': False,
            'max_tokens': 900,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
        )
        raw_path = self.capture_root / f'generation_{turn:04d}.json'
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                raw = response.read()
        except Exception as exc:
            raise TaeyConsultExtractionError(
                f'Taey inference failed: {type(exc).__name__}: {exc}'
            ) from exc
        try:
            with raw_path.open('xb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise TaeyConsultExtractionError(
                f'Taey raw generation could not be made durable: {exc}'
            ) from exc
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TaeyConsultExtractionError(
                f'Taey returned non-JSON inference bytes: {exc}'
            ) from exc
        self._append_turn_log({
            'event': 'generation',
            'turn': turn,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'request_sha256': hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
            'response_sha256': hashlib.sha256(raw).hexdigest(),
        })
        return result

    @staticmethod
    def _message(result: dict[str, object]) -> dict[str, object]:
        choices = result.get('choices')
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
            or not isinstance(choices[0].get('message'), dict)
        ):
            raise TaeyConsultExtractionError('Taey returned a malformed response')
        return dict(choices[0]['message'])

    @staticmethod
    def _arguments(message: dict[str, object]) -> tuple[str, dict[str, object]]:
        calls = message.get('tool_calls')
        if not isinstance(calls, list) or len(calls) != 1:
            raise TaeyConsultExtractionError(
                'Taey must emit exactly one consult_extract_action call per turn'
            )
        if str(message.get('content') or '').strip():
            raise TaeyConsultExtractionError(
                'Taey emitted assistant prose alongside an extraction action'
            )
        call = calls[0]
        if not isinstance(call, dict):
            raise TaeyConsultExtractionError('Taey emitted a malformed tool call')
        function = call.get('function')
        if (
            not isinstance(function, dict)
            or function.get('name') != 'consult_extract_action'
        ):
            raise TaeyConsultExtractionError(
                'Taey emitted a tool outside the consult extraction seat'
            )
        raw_arguments = function.get('arguments')
        if not isinstance(raw_arguments, str):
            raise TaeyConsultExtractionError('Taey tool arguments were not JSON text')
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise TaeyConsultExtractionError(
                f'Taey tool arguments were invalid JSON: {exc}'
            ) from exc
        if not isinstance(arguments, dict):
            raise TaeyConsultExtractionError('Taey tool arguments must be an object')
        return str(call.get('id') or ''), arguments

    def _semantic_element_keys(self, step: str) -> tuple[str, ...]:
        steps = self.full_consult_contract['steps']
        if isinstance(steps, dict) and step in steps:
            step_cfg = steps[step]
            if not isinstance(step_cfg, dict):
                return ()
            elements = tuple(step_cfg.get('elements') or ())
            if step_cfg.get('sequence'):
                if self.copy_response_index >= len(elements):
                    return ()
                return (str(elements[self.copy_response_index]),)
            return tuple(str(value) for value in elements)
        if step == 'attachment_present':
            attachment_present = self.full_consult_contract['attachment_present']
            if isinstance(attachment_present, dict):
                return tuple(
                    str(value)
                    for value in (attachment_present.get('elements') or ())
                )
        return ()

    def _semantic_slot(self, step: str) -> str:
        steps = self.full_consult_contract['steps']
        step_cfg = steps.get(step) if isinstance(steps, dict) else None
        if isinstance(step_cfg, dict) and step_cfg.get('sequence'):
            return f'{step}:{self.copy_response_index}'
        return step

    def _semantic_action(self, step: str) -> str:
        steps = self.full_consult_contract['steps']
        step_cfg = steps.get(step) if isinstance(steps, dict) else None
        return (
            str(step_cfg.get('action') or 'click')
            if isinstance(step_cfg, dict)
            else 'click'
        )

    def _stored_semantic_control(
        self,
        step: str,
    ) -> dict[str, object] | None:
        return self.full_consult_found.get(self._semantic_slot(step))

    def _forget_semantic_control(self, step: str) -> None:
        self.full_consult_found.pop(self._semantic_slot(step), None)

    @staticmethod
    def _spec_exact_names(spec: dict[str, object]) -> tuple[str, ...]:
        if isinstance(spec.get('name'), str):
            return (str(spec['name']),)
        names = spec.get('names_any_of')
        if isinstance(names, list):
            return tuple(str(value) for value in names if isinstance(value, str))
        return ()

    @staticmethod
    def _states_satisfy(
        found: dict[str, object],
        spec: dict[str, object],
    ) -> bool:
        required = {
            str(value).lower()
            for value in (spec.get('states_include') or [])
        }
        actual = {
            str(value).lower()
            for value in (found.get('states') or [])
        }
        return required.issubset(actual)

    def _mapped_structural_control(
        self,
        element_key: str,
        spec: dict[str, object],
    ) -> dict[str, object] | None:
        scope = str(spec.get('scope') or 'snapshot')
        if scope == 'menu_snapshot' or scope.endswith('_menu'):
            _, _, snapshot = build_menu_snapshot(self.platform)
        elif scope == 'app_root_snapshot':
            _, _, snapshot = build_app_root_snapshot(self.platform)
        else:
            _, _, snapshot = build_snapshot(self.platform)
        refs = list(snapshot.mapped.get(element_key) or [])
        if not refs:
            return None
        ref = refs[-1] if spec.get('pick') == 'last_by_y' else refs[0]
        node = ref.atspi_obj
        action_name = str(self.act.node_label(node) or '').strip()
        if not action_name:
            raise TaeyConsultExtractionError(
                f'{self.platform} structural control {element_key!r} resolved '
                'without a canonical act.py action label'
            )
        return {
            'node': node,
            'name': action_name,
            'role': ref.role,
            'states': set(ref.states or []),
            'element_ref': ref,
        }

    def _find_element_control(
        self,
        element_key: str,
        *,
        must_show: bool = True,
        scroll: bool = True,
        pick: str | None = None,
    ) -> dict[str, object] | None:
        spec = self.element_map.get(element_key)
        if not isinstance(spec, dict):
            raise TaeyConsultExtractionError(
                f'{self.platform} element_map key {element_key!r} is unavailable'
            )
        if isinstance(spec.get('structural'), dict):
            found = self._mapped_structural_control(element_key, spec)
            if found is None or not self._states_satisfy(found, spec):
                return None
            return {
                **found,
                'element_key': element_key,
                'scope': str(spec.get('scope') or 'snapshot'),
            }
        if pick == 'last_by_y':
            scope = str(spec.get('scope') or 'snapshot')
            if scope == 'menu_snapshot' or scope.endswith('_menu'):
                _, _, snapshot = build_menu_snapshot(self.platform)
            elif scope == 'app_root_snapshot':
                _, _, snapshot = build_app_root_snapshot(self.platform)
            else:
                _, _, snapshot = build_snapshot(self.platform)
            refs = list(snapshot.mapped.get(element_key) or [])
            if not refs:
                return None
            ref = max(refs, key=lambda item: item.y if item.y is not None else -1)
            found = {
                'node': ref.atspi_obj,
                'name': ref.name,
                'role': ref.role,
                'states': set(ref.states or []),
                'element_ref': ref,
            }
            if not self._states_satisfy(found, spec):
                return None
            return {
                **found,
                'element_key': element_key,
                'scope': scope,
            }
        role = str(spec.get('role') or '')
        for exact_name in self._spec_exact_names(spec):
            found = self.act.find(
                exact_name,
                role=role,
                display=self.display,
                contains=False,
                must_show=must_show,
                scroll=scroll,
            )
            if found and self._states_satisfy(found, spec):
                return {
                    **found,
                    'name': exact_name,
                    'element_key': element_key,
                    'scope': str(spec.get('scope') or 'snapshot'),
                }
        return None

    def _find_semantic_control(
        self,
        step: str,
        *,
        must_show: bool = True,
        scroll: bool = True,
    ) -> dict[str, object] | None:
        steps = self.full_consult_contract['steps']
        step_cfg = steps.get(step) if isinstance(steps, dict) else None
        pick = (
            str(step_cfg.get('pick'))
            if isinstance(step_cfg, dict) and step_cfg.get('pick')
            else None
        )
        for element_key in self._semantic_element_keys(step):
            found = self._find_element_control(
                element_key,
                must_show=must_show,
                scroll=scroll,
                pick=pick,
            )
            if found is not None:
                return {
                    **found,
                    'semantic_step': step,
                }
        if step != 'attachment_present' or self.attachment_path is None:
            return None
        attachment_present = self.full_consult_contract['attachment_present']
        roles = (
            tuple(attachment_present.get('filename_roles') or ())
            if isinstance(attachment_present, dict)
            else ()
        )
        filename_value = (
            str(attachment_present.get('filename_value') or 'name')
            if isinstance(attachment_present, dict)
            else 'name'
        )
        attachment_label = (
            self.attachment_path.stem
            if filename_value == 'stem'
            else self.attachment_path.name
        )
        for role in roles:
            found = self.act.find(
                attachment_label,
                role=str(role),
                display=self.display,
                contains=False,
                must_show=must_show,
                scroll=scroll,
            )
            if found:
                return {
                    **found,
                    'name': attachment_label,
                    'element_key': 'dynamic_attachment_filename',
                    'scope': 'snapshot',
                    'semantic_step': step,
                }
        return None

    def _find_full_consult_failure(self) -> dict[str, object] | None:
        for element_key in self.full_consult_contract['failures']:
            found = self._find_element_control(
                str(element_key),
                must_show=False,
                scroll=False,
            )
            if found is not None:
                return found
        return None

    def _normalized_action(
        self,
        arguments: dict[str, object],
    ) -> tuple[str, str, bool]:
        expected_keys = {'action', 'name', 'contains'}
        if set(arguments) != expected_keys:
            raise TaeyConsultExtractionError(
                f'consult extraction action keys must be {sorted(expected_keys)}'
            )
        action = str(arguments.get('action') or '').strip()
        name = str(arguments.get('name') or '').strip()
        contains = arguments.get('contains')
        supported_actions = {
            'find',
            'click',
            'activate',
            'focus',
            'key',
            'typeahead',
            'paste_path',
            'paste_prompt',
            'select_mode',
            'wait_complete',
            'finish',
        }
        if action not in supported_actions:
            raise TaeyConsultExtractionError(
                f'unsupported consultation action {action!r}'
            )
        if not isinstance(contains, bool):
            raise TaeyConsultExtractionError('contains must be a boolean')
        if action in {
            'find',
            'click',
            'activate',
            'focus',
            'key',
            'typeahead',
            'paste_prompt',
            'select_mode',
        } and not name:
            raise TaeyConsultExtractionError(f'{action} requires a non-empty name')
        if action in {'wait_complete', 'finish'} and (name or contains):
            raise TaeyConsultExtractionError(
                f'{action} requires name="" and contains=false'
            )
        if action == 'find' and name in {'Copy', 'Copy contents'} and contains:
            raise TaeyConsultExtractionError(
                f'find for {name!r} must use contains=false so Copy query and '
                'other controls cannot satisfy it'
            )
        if action != 'find' and contains:
            raise TaeyConsultExtractionError(
                f'{action} requires contains=false'
            )
        attachment = (self.cfg.get('workflow') or {}).get('attachment') or {}
        allowed_keys = {'ctrl+l', 'ctrl+a', 'Return'}
        if isinstance(attachment, dict):
            open_key = attachment.get('open_key')
            if isinstance(open_key, str) and open_key:
                allowed_keys.add(open_key)
            for submit_key in attachment.get('typeahead_submit_keys') or ():
                if isinstance(submit_key, str) and submit_key:
                    allowed_keys.add(submit_key)
        if action == 'key' and name not in allowed_keys:
            raise TaeyConsultExtractionError(
                f'consultation key action is restricted, got {name!r}'
            )
        if action == 'typeahead' and name != 'upload_item':
            raise TaeyConsultExtractionError(
                'typeahead is restricted to semantic step upload_item'
            )
        if action == 'select_mode' and name != 'select_mode':
            raise TaeyConsultExtractionError(
                'select_mode is restricted to semantic step select_mode'
            )
        if action == 'paste_path':
            name = ''
        return action, name, contains

    def _control_role(self, action: str, name: str) -> str:
        if self.full_consult:
            stored = self._stored_semantic_control(name)
            if stored is not None:
                return str(stored.get('role') or '')
            roles = {
                str((self.element_map.get(key) or {}).get('role') or '')
                for key in self._semantic_element_keys(name)
            }
            roles.discard('')
            if name == 'attachment_present':
                attachment_present = self.full_consult_contract[
                    'attachment_present'
                ]
                if isinstance(attachment_present, dict):
                    roles.update(
                        str(value)
                        for value in (
                            attachment_present.get('filename_roles') or ()
                        )
                    )
            if len(roles) == 1:
                return next(iter(roles))
            if roles:
                if action == 'find':
                    return ''
                raise TaeyConsultControlError(
                    f'{self.platform} semantic step {name!r} resolves to '
                    f'multiple roles {sorted(roles)}'
                )
            raise TaeyConsultControlError(
                f'{self.platform} semantic step {name!r} has no resolved role'
            )
        return 'menu item' if name == MARKDOWN_EXPORT_NAME else 'push button'

    def _validated_action(
        self,
        arguments: dict[str, object],
    ) -> tuple[str, str, bool, str]:
        action, name, contains = self._normalized_action(arguments)
        required = self._required_action()
        normalized_arguments = {
            'action': action,
            'name': name,
            'contains': contains,
        }
        if normalized_arguments != required:
            raise TaeyConsultStateError(required)
        role = (
            self._control_role(action, name)
            if action in {'find', 'click', 'activate', 'focus', 'paste_prompt'}
            else ''
        )
        if (
            action in {'click', 'activate', 'focus', 'paste_prompt'}
            and (name, role) not in self.found_controls
        ):
            raise TaeyConsultExtractionError(
                f'{action} requires a live successful find for exact {name!r} '
                f'with role {role!r}; nothing executed'
            )
        return action, name, contains, role

    def _required_action(self) -> dict[str, object]:
        if self.full_consult and not self.consult_completed:
            return self._required_full_consult_action()
        if self.full_consult:
            return self._required_full_consult_extraction_action()
        return self._required_extraction_action()

    def _required_full_consult_action(self) -> dict[str, object]:
        if not self.fresh_thread_opened:
            if self._stored_semantic_control('new_thread') is not None:
                return {
                    'action': 'click',
                    'name': 'new_thread',
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': 'new_thread',
                'contains': False,
            }
        attachment = (self.cfg.get('workflow') or {}).get('attachment') or {}
        open_method = (
            str(attachment.get('open_method') or 'click')
            if isinstance(attachment, dict)
            else 'click'
        )
        if not self.attach_trigger_activated:
            if self._stored_semantic_control('attach_trigger') is None:
                return {
                    'action': 'find',
                    'name': 'attach_trigger',
                    'contains': False,
                }
            if open_method == 'focus_and_key_open':
                if not self.attach_trigger_focused:
                    return {
                        'action': 'focus',
                        'name': 'attach_trigger',
                        'contains': False,
                    }
                open_key = str(attachment.get('open_key') or '')
                if not open_key:
                    raise TaeyConsultControlError(
                        f'{self.platform} focus_and_key_open has no open_key'
                    )
                return {
                    'action': 'key',
                    'name': open_key,
                    'contains': False,
                }
            return {
                'action': 'click',
                'name': 'attach_trigger',
                'contains': False,
            }
        if not self.upload_control_clicked:
            typeahead_label = (
                str(attachment.get('typeahead_label') or '').strip()
                if isinstance(attachment, dict)
                else ''
            )
            if typeahead_label:
                if not self.upload_typeahead_entered:
                    return {
                        'action': 'typeahead',
                        'name': 'upload_item',
                        'contains': False,
                    }
                submit_keys = tuple(
                    str(value)
                    for value in (
                        attachment.get('typeahead_submit_keys') or ()
                    )
                )
                if self.upload_submit_key_index >= len(submit_keys):
                    raise TaeyConsultControlError(
                        f'{self.platform} attachment typeahead exhausted its '
                        'submit keys without opening the file chooser'
                    )
                return {
                    'action': 'key',
                    'name': submit_keys[self.upload_submit_key_index],
                    'contains': False,
                }
            if self._stored_semantic_control('upload_item') is not None:
                return {
                    'action': 'click',
                    'name': 'upload_item',
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': 'upload_item',
                'contains': False,
            }
        if not self.dialog_location_opened:
            return {'action': 'key', 'name': 'ctrl+l', 'contains': False}
        if not self.dialog_path_selected:
            return {'action': 'key', 'name': 'ctrl+a', 'contains': False}
        if not self.attachment_path_pasted:
            return {
                'action': 'paste_path',
                'name': '',
                'contains': False,
            }
        if not self.attachment_submitted:
            return {'action': 'key', 'name': 'Return', 'contains': False}
        if not self.attachment_verified:
            return {
                'action': 'find',
                'name': 'attachment_present',
                'contains': False,
            }
        if not self.prompt_entered:
            if self._stored_semantic_control('composer_input') is not None:
                return {
                    'action': 'paste_prompt',
                    'name': 'composer_input',
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': 'composer_input',
                'contains': False,
            }
        if not self.mode_selected:
            return {
                'action': 'select_mode',
                'name': 'select_mode',
                'contains': False,
            }
        if not self.submitted:
            if self._stored_semantic_control('submit') is not None:
                return {
                    'action': self._semantic_action('submit'),
                    'name': 'submit',
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': 'submit',
                'contains': False,
            }
        if (
            self._semantic_element_keys('post_submit')
            and not self.post_submitted
        ):
            if self._stored_semantic_control('post_submit') is not None:
                return {
                    'action': 'click',
                    'name': 'post_submit',
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': 'post_submit',
                'contains': False,
            }
        return {'action': 'wait_complete', 'name': '', 'contains': False}

    def _required_full_consult_extraction_action(self) -> dict[str, object]:
        copy_steps = self.full_consult_contract['steps']['copy_response']
        elements = tuple(copy_steps.get('elements') or ())
        if not self.body:
            if self.copy_response_index >= len(elements):
                raise TaeyConsultControlError(
                    f'{self.platform} copy_response sequence exhausted without a body'
                )
            if self._stored_semantic_control('copy_response') is not None:
                return {
                    'action': self._semantic_action('copy_response'),
                    'name': 'copy_response',
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': 'copy_response',
                'contains': False,
            }
        return {'action': 'finish', 'name': '', 'contains': False}

    def _required_extraction_action(self) -> dict[str, object]:
        if not self.body:
            copy_contents = ('Copy contents', 'push button')
            if not self.copy_contents_checked:
                return {
                    'action': 'find',
                    'name': 'Copy contents',
                    'contains': False,
                }
            if copy_contents in self.found_controls:
                return {
                    'action': 'click',
                    'name': 'Copy contents',
                    'contains': False,
                }
            markdown_export = (MARKDOWN_EXPORT_NAME, 'menu item')
            if not self.markdown_export_checked:
                return {
                    'action': 'find',
                    'name': MARKDOWN_EXPORT_NAME,
                    'contains': False,
                }
            if markdown_export in self.found_controls:
                return {
                    'action': 'click',
                    'name': MARKDOWN_EXPORT_NAME,
                    'contains': False,
                }
            found_overflow = [
                name
                for name in OVERFLOW_CONTROL_NAMES
                if (name, 'push button') in self.found_controls
            ]
            if len(found_overflow) > 1:
                raise TaeyConsultControlError(
                    f'multiple answer overflow controls were found: {found_overflow}'
                )
            if found_overflow:
                return {
                    'action': 'click',
                    'name': found_overflow[0],
                    'contains': False,
                }
            for overflow_name in OVERFLOW_CONTROL_NAMES:
                if overflow_name not in self.overflow_checked:
                    return {
                        'action': 'find',
                        'name': overflow_name,
                        'contains': False,
                    }
            raise TaeyConsultControlError(
                'Copy contents and Export as Markdown are absent, and no supported '
                f'answer overflow control was found: {list(OVERFLOW_CONTROL_NAMES)}'
            )
        if self.sources:
            return {'action': 'finish', 'name': '', 'contains': False}
        found_sources = sorted(
            name
            for name, role in self.found_controls
            if role == 'push button'
            and SOURCE_CONTROL_PATTERN.fullmatch(name) is not None
        )
        if len(found_sources) > 1:
            raise TaeyConsultExtractionError(
                f'multiple source controls were found: {found_sources}'
            )
        if found_sources:
            return {
                'action': 'click',
                'name': found_sources[0],
                'contains': False,
            }
        return {'action': 'find', 'name': ' source', 'contains': True}

    @staticmethod
    def _serializable_found(found: object) -> dict[str, object] | None:
        if not isinstance(found, dict):
            return None
        return {
            'name': str(found.get('name') or ''),
            'role': str(found.get('role') or ''),
            'states': sorted(str(value) for value in (found.get('states') or [])),
        }

    def _find_full_consult_control(
        self,
        step: str,
        *,
        timeout: float = 15.0,
        must_show: bool = True,
        scroll: bool = True,
    ) -> dict[str, object] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self._find_semantic_control(
                step,
                must_show=must_show,
                scroll=scroll,
            )
            if found is not None:
                return found
            time.sleep(0.3)
        return None

    @staticmethod
    def _normalized_session_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(str(url or '').strip())
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            return ''
        path = parsed.path.rstrip('/') or '/'
        return urllib.parse.urlunsplit((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            '',
        ))

    def _actuate_semantic_control(
        self,
        step: str,
        action: str,
    ) -> dict[str, object]:
        found = self._stored_semantic_control(step)
        if found is None:
            raise TaeyConsultExtractionError(
                f'{action} requires a live successful find for semantic '
                f'step {step!r}; nothing executed'
            )
        control_name = str(found.get('name') or '')
        role = str(found.get('role') or '')
        if not control_name or not role:
            raise TaeyConsultExtractionError(
                f'{self.platform} semantic step {step!r} resolved without '
                'an actionable exact name and role'
            )
        element_ref = found.get('element_ref')
        if element_ref is not None:
            self.runtime.scroll_element_into_view(element_ref)
            steps = self.full_consult_contract['steps']
            step_cfg = steps.get(step) if isinstance(steps, dict) else None
            settle_seconds = (
                float(step_cfg.get('settle_seconds', 0.3))
                if isinstance(step_cfg, dict)
                else 0.3
            )
            time.sleep(settle_seconds)
            refreshed = self._find_semantic_control(
                step,
                must_show=True,
                scroll=False,
            )
            refreshed_ref = (
                refreshed.get('element_ref')
                if isinstance(refreshed, dict)
                else None
            )
            if refreshed_ref is None:
                raise TaeyConsultExtractionError(
                    f'{self.platform} semantic step {step!r} disappeared '
                    'after scroll; nothing activated'
                )
            acted = bool(
                self.runtime.click(refreshed_ref, strategy='atspi_only')
            )
            actuator_name = 'runtime.click'
        else:
            actuator = self.act.do if action == 'activate' else self.act.click
            acted = bool(
                actuator(
                    control_name,
                    role=role,
                    display=self.display,
                    contains=False,
                )
            )
            actuator_name = f'act.{actuator.__name__}'
        self._forget_semantic_control(step)
        self.found_controls.discard((step, role))
        if not acted:
            raise TaeyConsultExtractionError(
                f'{actuator_name}({control_name!r}, role={role!r}) '
                f'failed for semantic step {step!r}'
            )
        return {
            'semantic_step': step,
            'element_key': str(found.get('element_key') or ''),
            'control_name': control_name,
            'role': role,
            'scope': str(found.get('scope') or ''),
        }

    def _mode_element_control(
        self,
        element_key: str,
    ) -> dict[str, object] | None:
        spec = self.element_map.get(element_key)
        if not isinstance(spec, dict):
            raise TaeyConsultExtractionError(
                f'{self.platform} mode element {element_key!r} is unavailable'
            )
        scope = str(spec.get('scope') or 'snapshot')
        if scope == 'app_root_snapshot':
            _, _, snapshot = build_app_root_snapshot(self.platform)
        elif scope == 'menu_snapshot' or scope.endswith('_menu'):
            _, _, snapshot = build_menu_snapshot(self.platform)
        else:
            _, _, snapshot = build_snapshot(self.platform)
        refs = list(snapshot.mapped.get(element_key) or ())
        if not refs:
            return None
        ref = refs[0]
        name = str(ref.name or self.act.node_label(ref.atspi_obj) or '').strip()
        if not name:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode element {element_key!r} resolved '
                'without an actionable exact label'
            )
        return {
            'element_key': element_key,
            'element_ref': ref,
            'name': name,
            'role': str(ref.role or ''),
            'scope': scope,
            'states': set(ref.states or ()),
        }

    def _wait_for_mode_element(
        self,
        element_key: str,
        *,
        timeout: float = 6.0,
    ) -> dict[str, object] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self._mode_element_control(element_key)
            if found is not None:
                return found
            time.sleep(0.2)
        return None

    def _actuate_mode_element(
        self,
        found: dict[str, object],
        *,
        action: str = 'click',
        strategy: str = 'atspi_only',
    ) -> dict[str, object]:
        element_ref = found.get('element_ref')
        if element_ref is None:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode element '
                f'{found.get("element_key")!r} has no live element reference'
            )
        if action == 'hover':
            acted = bool(self.runtime.hover(element_ref))
        elif action in {'click', 'press'}:
            acted = bool(self.runtime.click(element_ref, strategy=strategy))
        else:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode path action {action!r} is unsupported'
            )
        if not acted:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode element '
                f'{found.get("element_key")!r} {action} failed'
            )
        return {
            'element': str(found.get('element_key') or ''),
            'control_name': str(found.get('name') or ''),
            'role': str(found.get('role') or ''),
            'scope': str(found.get('scope') or ''),
            'action': action,
            'strategy': strategy if action != 'hover' else 'atspi_hover',
        }

    @staticmethod
    def _mode_target_is_active(
        found: dict[str, object],
        recognition: str,
    ) -> bool:
        normalized = recognition.strip().lower()
        if normalized in {'click_only', 'selected_name_prefix'}:
            return False
        states = {
            str(value).strip().lower()
            for value in (found.get('states') or ())
        }
        return normalized in states

    def _mode_active_evidence(
        self,
        step: dict[str, object],
        *,
        timeout: float,
    ) -> dict[str, object] | None:
        trigger_names = {
            str(value)
            for value in (step.get('active_trigger_names') or ())
        }
        if trigger_names:
            trigger = self._wait_for_mode_element(
                str(step['trigger']),
                timeout=timeout,
            )
            trigger_name = str((trigger or {}).get('name') or '')
            if trigger_name in trigger_names:
                return {
                    'confirmation': 'active_trigger_name',
                    'element': str(step['trigger']),
                    'control_name': trigger_name,
                    'states': sorted(
                        str(value)
                        for value in ((trigger or {}).get('states') or ())
                    ),
                }
        active_element = str(step.get('active_element') or '')
        if active_element:
            active = self._wait_for_mode_element(
                active_element,
                timeout=timeout,
            )
            if active is not None:
                return {
                    'confirmation': 'active_element_present',
                    'element': active_element,
                    'control_name': str(active.get('name') or ''),
                    'states': sorted(
                        str(value)
                        for value in (active.get('states') or ())
                    ),
                }
        return None

    def _close_mode_menu(self, *, timeout: float = 5.0) -> None:
        self.runtime.press('Escape')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, _, snapshot = build_menu_snapshot(self.platform)
            if int(snapshot.raw_count or 0) == 0:
                return
            time.sleep(0.2)
        raise TaeyConsultExtractionError(
            f'{self.platform} mode menu did not close after selection'
        )

    def _open_mode_selection(
        self,
        step: dict[str, object],
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        trigger_key = str(step['trigger'])
        trigger = self._wait_for_mode_element(trigger_key)
        if trigger is None:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode trigger {trigger_key!r} was not found'
            )
        path_evidence = [
            self._actuate_mode_element(
                trigger,
                strategy=self.runtime.click_strategy,
            )
        ]
        path = tuple(step.get('path') or ())
        for path_step in path:
            if not isinstance(path_step, dict):
                raise TaeyConsultExtractionError(
                    f'{self.platform} mode path entry is not a mapping'
                )
            element_key = str(path_step.get('element') or '')
            path_control = self._wait_for_mode_element(element_key)
            if path_control is None:
                raise TaeyConsultExtractionError(
                    f'{self.platform} mode path element {element_key!r} '
                    'was not found'
                )
            path_evidence.append(
                self._actuate_mode_element(
                    path_control,
                    action=str(path_step.get('action') or ''),
                    strategy='atspi_only',
                )
            )
            time.sleep(0.2)
        target_key = str(step['target'])
        target = self._wait_for_mode_element(target_key)
        if target is None:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode target {target_key!r} was not found'
            )
        return target, path_evidence

    def _select_mode_step(
        self,
        step: dict[str, object],
    ) -> dict[str, object]:
        menu = str(step['menu'])
        option = str(step['option'])
        active = self._mode_active_evidence(step, timeout=0.8)
        if active is not None:
            return {
                'menu': menu,
                'option': option,
                'selected': True,
                'already_active': True,
                **active,
            }
        target, path_evidence = self._open_mode_selection(step)
        recognition = str(step.get('active_recognition') or '')
        if self._mode_target_is_active(target, recognition):
            self._close_mode_menu()
            return {
                'menu': menu,
                'option': option,
                'selected': True,
                'already_active': True,
                'confirmation': 'menu_active_state',
                'active_state': recognition,
                'target': str(step['target']),
                'states': sorted(
                    str(value)
                    for value in (target.get('states') or ())
                ),
                'path': path_evidence,
            }
        click_strategy = str(step.get('click_strategy') or 'atspi_only')
        click_evidence = self._actuate_mode_element(
            target,
            strategy=click_strategy,
        )
        time.sleep(0.3)
        active = self._mode_active_evidence(step, timeout=8.0)
        if active is not None:
            self.runtime.press('Escape')
            return {
                'menu': menu,
                'option': option,
                'selected': True,
                'already_active': False,
                **active,
                'path': path_evidence,
                'selection': click_evidence,
            }
        if recognition == 'click_only':
            self._close_mode_menu()
            return {
                'menu': menu,
                'option': option,
                'selected': True,
                'already_active': False,
                'confirmation': 'click_only_menu_closed',
                'path': path_evidence,
                'selection': click_evidence,
            }
        verified_target, verification_path = self._open_mode_selection(step)
        verified = self._mode_target_is_active(
            verified_target,
            recognition,
        )
        self._close_mode_menu()
        if not verified:
            raise TaeyConsultExtractionError(
                f'{self.platform} mode selection {menu}={option} did not '
                f'expose required active state {recognition!r}'
            )
        return {
            'menu': menu,
            'option': option,
            'selected': True,
            'already_active': False,
            'confirmation': 'menu_active_state',
            'active_state': recognition,
            'target': str(step['target']),
            'states': sorted(
                str(value)
                for value in (verified_target.get('states') or ())
            ),
            'path': path_evidence,
            'selection': click_evidence,
            'verification_path': verification_path,
        }

    def _execute_select_mode(self) -> dict[str, object]:
        self.mode_evidence = []
        for step in self.full_consult_contract['select_mode']:
            if not isinstance(step, dict):
                raise TaeyConsultExtractionError(
                    f'{self.platform} normalized select_mode step is invalid'
                )
            self.mode_evidence.append(self._select_mode_step(step))
        self.mode_selected = True
        return {
            'ok': True,
            'action': 'select_mode',
            'semantic_step': 'select_mode',
            'mode_selections': [
                {
                    'menu': str(item.get('menu') or ''),
                    'option': str(item.get('option') or ''),
                }
                for item in self.mode_evidence
            ],
            'mode_evidence': list(self.mode_evidence),
        }

    def _current_url(self) -> str:
        return str(self.runtime.current_url() or '').strip()

    def _answer_thread_identity(self, url: str) -> str:
        normalized = self._normalized_session_url(url)
        if not normalized:
            return ''
        fresh_url = self._normalized_session_url(
            str((self.cfg.get('urls') or {}).get('fresh') or '')
        )
        if normalized == fresh_url:
            return ''
        return normalized

    def _wait_for_fresh_thread(
        self,
        previous_url: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        last_url = ''
        composer_seen = False
        answer_surface_seen = False
        completion_control_seen = False
        attachment_seen = False
        failure_seen: dict[str, object] | None = None
        fresh_url = self._normalized_session_url(
            str((self.cfg.get('urls') or {}).get('fresh') or '')
        )
        if not fresh_url:
            raise TaeyConsultExtractionError(
                f'{self.platform} urls.fresh is not an absolute HTTP(S) URL'
            )
        while time.monotonic() < deadline:
            last_url = self._current_url()
            composer = self._find_semantic_control(
                'composer_input',
                must_show=True,
                scroll=False,
            )
            answer_surface = self._find_semantic_control(
                'copy_response',
                must_show=False,
                scroll=False,
            )
            completion_control = self._find_semantic_control(
                'completion',
                must_show=False,
                scroll=False,
            )
            attachment = self._find_semantic_control(
                'attachment_present',
                must_show=False,
                scroll=False,
            )
            failure = self._find_full_consult_failure()
            if failure is not None:
                failure_seen = failure
            composer_seen = composer_seen or bool(composer)
            answer_surface_seen = answer_surface_seen or bool(answer_surface)
            completion_control_seen = (
                completion_control_seen or bool(completion_control)
            )
            attachment_seen = attachment_seen or bool(attachment)
            clean_url = self._normalized_session_url(last_url) == fresh_url
            left_previous_thread = (
                not self._answer_thread_identity(previous_url)
                or self._answer_thread_identity(previous_url)
                != self._answer_thread_identity(last_url)
            )
            if (
                clean_url
                and left_previous_thread
                and composer
                and not answer_surface
                and not completion_control
                and not attachment
                and not failure
            ):
                return {
                    'opened': True,
                    'previous_url': previous_url,
                    'fresh_thread_url': last_url,
                    'composer_seen': True,
                    'answer_surface_absent': True,
                    'completion_control_absent': True,
                    'attachment_absent': True,
                }
            time.sleep(0.3)
        raise TaeyConsultExtractionError(
            f'{self.platform} new_thread did not expose its configured fresh '
            'composer; '
            f'previous_url={previous_url!r}, url={last_url!r}, '
            f'composer_seen={composer_seen}, '
            f'answer_surface_seen={answer_surface_seen}, '
            f'completion_control_seen={completion_control_seen}, '
            f'attachment_seen={attachment_seen}, '
            f'failure_seen={self._serializable_found(failure_seen)!r}'
        )

    def _reset_to_neutral(self) -> dict[str, object]:
        previous_url = self._current_url()
        if not self._answer_thread_identity(previous_url):
            raise TaeyConsultExtractionError(
                f'refusing {self.platform} post-consult reset outside the '
                'completed answer thread; '
                f'current_url={previous_url!r}'
            )
        new_thread = self._find_full_consult_control(
            'new_thread',
            must_show=True,
            scroll=False,
        )
        if not new_thread:
            raise TaeyConsultExtractionError(
                f'{self.platform} configured new_thread control is unavailable '
                'for post-consult reset'
            )
        self.full_consult_found['new_thread'] = new_thread
        control = self._actuate_semantic_control('new_thread', 'click')
        fresh = self._wait_for_fresh_thread(previous_url)
        return {
            **fresh,
            **control,
            'clicked': True,
        }

    def _assert_bound_answer_thread(self) -> None:
        if not self.full_consult:
            return
        expected = self._normalized_session_url(self.session_url_after)
        current_url = self._current_url()
        current = self._normalized_session_url(current_url)
        if (
            not self.fresh_thread_opened
            or not expected
            or current != expected
        ):
            raise TaeyConsultExtractionError(
                'refusing extraction outside the answer thread created by this '
                f'fresh consult; expected={self.session_url_after!r}, '
                f'current={current_url!r}, '
                f'fresh_thread_opened={self.fresh_thread_opened}'
            )

    def _wait_for_full_consult_completion(self) -> dict[str, object]:
        started = time.monotonic()
        deadline = started + self.completion_timeout
        stop_seen_before_wait = bool(
            self.completion_evidence.get('stop_seen_after_action')
        )
        stop_seen = stop_seen_before_wait
        last_url = ''
        last_response_control: dict[str, object] | None = None
        ready_cycles = 0
        while time.monotonic() < deadline:
            last_url = self._current_url()
            failure = self._find_full_consult_failure()
            if failure is not None:
                raise TaeyConsultExtractionError(
                    f'{self.platform} full consult exposed configured failure '
                    f'{self._serializable_found(failure)!r}'
                )
            stop = self._find_semantic_control(
                'completion',
                must_show=False,
                scroll=False,
            )
            stop_seen = stop_seen or bool(stop)
            response_control = self._find_semantic_control(
                'copy_response',
                must_show=False,
                scroll=False,
            )
            if response_control is not None:
                last_response_control = response_control
            landed = (
                bool(self._normalized_session_url(last_url))
                and not stop
                and response_control is not None
                and (
                    stop_seen
                    or (
                        bool(self.session_url_before)
                        and self._normalized_session_url(last_url)
                        != self._normalized_session_url(self.session_url_before)
                    )
                )
            )
            if landed:
                ready_cycles += 1
            else:
                ready_cycles = 0
            if ready_cycles >= 2:
                return {
                    'completed': True,
                    'elapsed_seconds': round(time.monotonic() - started, 3),
                    'stop_seen': stop_seen,
                    'stop_seen_before_wait': stop_seen_before_wait,
                    'session_url_before': self.session_url_before,
                    'session_url_after': last_url,
                    'response_control': self._serializable_found(
                        last_response_control
                    ),
                    'response_element': str(
                        (last_response_control or {}).get('element_key') or ''
                    ),
                }
            time.sleep(1.0)
        raise TaeyConsultExtractionError(
            f'{self.platform} full consult did not expose its configured '
            f'completed response surface within {self.completion_timeout:.1f}s; '
            f'stop_seen={stop_seen}, url={last_url!r}, '
            f'response_control={self._serializable_found(last_response_control)!r}'
        )

    def _find_named_nodes(self, name: str, role: str) -> list[object]:
        app = self.act.firefox_app()
        if app is None:
            raise TaeyConsultExtractionError(
                f'no Firefox accessibility application on {self.display}'
            )
        matches: list[object] = []

        def walk(node: object, depth: int) -> None:
            if depth > 45:
                return
            try:
                node_role = node.get_role_name() or ''
                if self.act.prune_inactive_document(node_role, node):
                    return
                node_name = (node.get_name() or '').strip()
                if node_name == name and node_role == role:
                    matches.append(node)
                for index in range(node.get_child_count()):
                    child = node.get_child_at_index(index)
                    if child is not None:
                        walk(child, depth + 1)
            except Exception:
                return

        walk(app, 0)
        return matches

    @staticmethod
    def _following_siblings(node: object) -> list[object]:
        try:
            parent = node.get_parent()
            if parent is None:
                return []
            children = [
                parent.get_child_at_index(index)
                for index in range(parent.get_child_count())
            ]
        except Exception:
            return []
        for index, child in enumerate(children):
            if child is node:
                return [item for item in children[index + 1:] if item is not None]
        return []

    @staticmethod
    def _source_links(roots: list[object]) -> list[dict[str, object]]:
        sources: list[dict[str, object]] = []
        seen_urls: set[str] = set()

        def walk(node: object, depth: int) -> None:
            if depth > 20:
                return
            try:
                role = node.get_role_name() or ''
                if role == 'link':
                    hyperlink = node.get_hyperlink()
                    uri = str(hyperlink.get_uri(0) if hyperlink else '').strip()
                    if uri and uri not in seen_urls:
                        seen_urls.add(uri)
                        sources.append({
                            'index': len(sources) + 1,
                            'url': uri,
                            'title': (node.get_name() or '').strip()[:240],
                        })
                for index in range(node.get_child_count()):
                    child = node.get_child_at_index(index)
                    if child is not None:
                        walk(child, depth + 1)
            except Exception:
                return

        for root in roots:
            walk(root, 0)
        return sources

    @staticmethod
    def _source_file_counts(roots: list[object]) -> set[int]:
        counts: set[int] = set()

        def walk(node: object, depth: int) -> None:
            if depth > 20:
                return
            try:
                role = node.get_role_name() or ''
                name = (node.get_name() or '').strip()
                match = (
                    FILE_SOURCE_CONTROL_PATTERN.fullmatch(name)
                    if role == 'push button'
                    else None
                )
                if match is not None:
                    counts.add(int(match.group(1)))
                for index in range(node.get_child_count()):
                    child = node.get_child_at_index(index)
                    if child is not None:
                        walk(child, depth + 1)
            except Exception:
                return

        for root in roots:
            walk(root, 0)
        return counts

    def _capture_sources_panel(
        self,
        expected_count: int,
        *,
        timeout: float = 10.0,
    ) -> list[dict[str, object]]:
        deadline = time.monotonic() + timeout
        last_count = 0
        last_file_count = 0
        accepted_panel_counts = {expected_count}
        if self.markdown_source_definition_count > 0:
            accepted_panel_counts.add(self.markdown_source_definition_count)

        def retained_markdown_sources() -> list[dict[str, object]]:
            source_ids = [
                int(item['index'])
                for item in self.markdown_sources
            ]
            expected_ids = list(range(1, expected_count + 1))
            if source_ids != expected_ids:
                raise TaeyConsultExtractionError(
                    'Sources panel does not match the retained Markdown export '
                    f'definitions: expected={expected_ids}, definitions={source_ids}'
                )
            return list(self.markdown_sources)

        while time.monotonic() < deadline:
            candidates: list[list[dict[str, object]]] = []
            file_panels = 0
            for anchor in self._find_named_nodes('Sources', 'push button'):
                roots = self._following_siblings(anchor)
                sources = self._source_links(roots)
                if sources:
                    candidates.append(sources)
                file_counts = self._source_file_counts(roots)
                last_file_count = max(
                    [last_file_count, *file_counts],
                )
                for file_count in file_counts:
                    panel_count = len(sources) + file_count
                    if (
                        panel_count == expected_count
                        and file_count == 1
                        and self.attachment_path is not None
                    ):
                        candidates.append([
                            *sources,
                            {
                                'index': len(sources) + 1,
                                'url': '',
                                'title': self.attachment_path.name,
                            },
                        ])
                    elif file_count in accepted_panel_counts:
                        file_panels += 1
            exact = [
                items
                for items in candidates
                if len(items) in accepted_panel_counts
            ]
            if len(exact) == 1:
                if len(exact[0]) == expected_count:
                    return exact[0]
                return retained_markdown_sources()
            if len(exact) > 1:
                raise TaeyConsultExtractionError(
                    'multiple Sources panels exposed the expected source count'
                )
            if file_panels > 1:
                raise TaeyConsultExtractionError(
                    'multiple Sources panels exposed the expected file count'
                )
            if file_panels == 1:
                return retained_markdown_sources()
            last_count = max((len(items) for items in candidates), default=0)
            time.sleep(0.25)
        raise TaeyConsultExtractionError(
            f'Sources panel exposed {last_count}/{expected_count} source links '
            f'and Files {last_file_count}'
        )

    @staticmethod
    def _read_clipboard_until_nonempty(timeout: float = 5.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = (clipboard.read() or '').strip()
            if value:
                return value
            time.sleep(0.2)
        return ''

    @staticmethod
    def _markdown_download_state() -> dict[str, tuple[int, int]]:
        directory = Path.home() / 'Downloads'
        if not directory.is_dir():
            raise TaeyConsultExtractionError(
                f'Perplexity Markdown download directory is unavailable: {directory}'
            )
        state: dict[str, tuple[int, int]] = {}
        for path in directory.glob('*.md'):
            try:
                stat = path.stat()
            except OSError as exc:
                raise TaeyConsultExtractionError(
                    f'could not stat Markdown download candidate {path}: {exc}'
                ) from exc
            state[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
        return state

    @staticmethod
    def _read_new_markdown_download(
        before: dict[str, tuple[int, int]],
        *,
        timeout: float = 15.0,
    ) -> tuple[str, dict[str, object]]:
        directory = Path.home() / 'Downloads'
        deadline = time.monotonic() + timeout
        stable: dict[str, tuple[int, int]] = {}
        changed_paths: set[str] = set()
        while time.monotonic() < deadline:
            ready: list[tuple[Path, str, bytes, tuple[int, int]]] = []
            for path in directory.glob('*.md'):
                try:
                    stat = path.stat()
                    current = (int(stat.st_mtime_ns), int(stat.st_size))
                except OSError as exc:
                    raise TaeyConsultExtractionError(
                        f'could not inspect Markdown download candidate {path}: {exc}'
                    ) from exc
                if before.get(str(path)) == current or current[1] <= 0:
                    continue
                changed_paths.add(str(path))
                try:
                    raw_bytes = path.read_bytes()
                except OSError as exc:
                    raise TaeyConsultExtractionError(
                        f'could not read Markdown download candidate {path}: {exc}'
                    ) from exc
                raw = raw_bytes.decode('utf-8', errors='replace')
                if (
                    'r2cdn.perplexity.ai/pplx-full-logo' not in raw[:500]
                    or not _citation_ids(raw)
                    or not any(
                        MARKDOWN_SOURCE_DEFINITION_PATTERN.fullmatch(line.strip())
                        for line in raw.splitlines()
                    )
                ):
                    stable[str(path)] = current
                    continue
                if stable.get(str(path)) == current:
                    ready.append((path, raw, raw_bytes, current))
                stable[str(path)] = current
            if len(ready) > 1:
                raise TaeyConsultExtractionError(
                    'multiple new Perplexity Markdown exports appeared: '
                    + ', '.join(str(item[0]) for item in ready)
                )
            if len(ready) == 1:
                path, raw, raw_bytes, _ = ready[0]
                body = _without_markdown_source_definitions(raw)
                (
                    markdown_sources,
                    markdown_source_conflicts,
                    markdown_source_definition_count,
                ) = _markdown_sources(raw)
                return body, {
                    'download_path': str(path),
                    'download_characters': len(raw),
                    'download_body_characters': len(body),
                    'download_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                    'citation_ids': _citation_ids(raw),
                    'markdown_sources': markdown_sources,
                    'markdown_source_conflicts': markdown_source_conflicts,
                    'markdown_source_definition_count': (
                        markdown_source_definition_count
                    ),
                }
            time.sleep(0.25)
        raise TaeyConsultExtractionError(
            'Perplexity Export as Markdown produced no unique complete download; '
            f'changed candidates={sorted(changed_paths)}'
        )

    def _finish(self) -> dict[str, object]:
        if not self.body:
            raise TaeyConsultExtractionError(
                'Taey attempted finish before a full report body was captured'
            )
        if self.full_consult:
            return {
                'ok': True,
                'content': self.body,
                'body': self.body,
                'body_control': self.body_control,
                'body_characters': len(self.body),
                'body_sha256': _sha256_text(self.body),
                'sources': [],
                'source_count': 0,
                'expected_source_count': 0,
                'citation_ids': _citation_ids(self.body),
                'missing': [],
                'missing_source_ids': [],
                'capture_root': str(self.capture_root),
                'actions': list(self.actions),
                'download_path': None,
                'download_sha256': None,
                'markdown_source_conflicts': [],
                'markdown_source_definition_count': 0,
                'consultation': {
                    'platform': self.platform,
                    'attachment_path': str(self.attachment_path),
                    'attachment_sha256': self.attachment_sha256,
                    'attachment_verified': self.attachment_verified,
                    'framing_prompt_characters': len(self.framing_prompt),
                    'framing_prompt_sha256': self.framing_prompt_sha256,
                    'mode': (
                        ((self.cfg.get('workflow') or {}).get('defaults') or {})
                        .get('mode')
                    ),
                    'mode_active': self.mode_selected,
                    'mode_selections': [
                        {
                            'menu': str(step.get('menu') or ''),
                            'option': str(step.get('option') or ''),
                        }
                        for step in self.full_consult_contract['select_mode']
                    ],
                    'mode_evidence': list(self.mode_evidence),
                    'submitted': self.submitted,
                    'completed': self.consult_completed,
                    'browser_url_before_dialog': self.browser_url_before_dialog,
                    'initial_session_url': self.initial_session_url,
                    'fresh_thread_url': self.fresh_thread_url,
                    'fresh_thread_opened': self.fresh_thread_opened,
                    'session_url_before': self.session_url_before,
                    'session_url_after': self.session_url_after,
                    'answer_thread_identity': self._answer_thread_identity(
                        self.session_url_after
                    ),
                    'completion': dict(self.completion_evidence),
                },
            }
        if self.expected_source_count <= 0:
            raise TaeyConsultExtractionError(
                'Taey attempted finish before clicking the N sources control'
            )
        if len(self.sources) != self.expected_source_count:
            raise TaeyConsultExtractionError(
                f'Taey attempted finish with {len(self.sources)}/'
                f'{self.expected_source_count} sources'
            )
        citation_ids = sorted(set(self.body_citation_ids) | set(_citation_ids(self.body)))
        if not citation_ids:
            raise TaeyConsultExtractionError(
                f'{self.body_control or "body"} has no source citation '
                'markers; it is not the complete Deep Research report'
            )
        source_ids = set(range(1, len(self.sources) + 1))
        missing = sorted(set(citation_ids) - source_ids)
        if missing:
            raise TaeyConsultExtractionError(
                f'Taey extraction is missing cited sources {missing}'
            )
        content = (
            self.body.rstrip()
            + '\n\n## Sources\n\n'
            + '\n'.join(
                f"{item['index']}. {item['url'] or item['title']}"
                for item in self.sources
            )
        )
        result: dict[str, object] = {
            'ok': True,
            'content': content,
            'body': self.body,
            'body_control': self.body_control,
            'body_characters': len(self.body),
            'body_sha256': _sha256_text(self.body),
            'sources': list(self.sources),
            'source_count': len(self.sources),
            'expected_source_count': self.expected_source_count,
            'citation_ids': citation_ids,
            'missing': missing,
            'missing_source_ids': missing,
            'capture_root': str(self.capture_root),
            'actions': list(self.actions),
            'download_path': self.download_path or None,
            'download_sha256': self.download_sha256 or None,
            'markdown_source_conflicts': list(self.markdown_source_conflicts),
            'markdown_source_definition_count': (
                self.markdown_source_definition_count
            ),
        }
        return result

    def _execute_extraction_action(
        self,
        action: str,
        name: str,
        contains: bool,
        role: str,
    ) -> dict[str, object]:
        self._assert_bound_answer_thread()
        if action == 'find':
            found = self.act.find(
                name,
                role=role,
                display=self.display,
                contains=contains,
            )
            serialized = self._serializable_found(found)
            if serialized is not None:
                self.found_controls.add((
                    str(serialized['name']),
                    str(serialized['role']),
                ))
            elif not contains:
                self.found_controls.discard((name, role))
            if name == 'Copy contents' and not contains:
                self.copy_contents_checked = True
            if name == MARKDOWN_EXPORT_NAME and not contains:
                self.markdown_export_checked = True
            if name in OVERFLOW_CONTROL_NAMES and not contains:
                self.overflow_checked.add(name)
            result = {
                'ok': bool(found),
                'action': action,
                'query': name,
                'role': role,
                'contains': contains,
                'found': serialized,
            }
        elif action == 'click':
            source_match = SOURCE_CONTROL_PATTERN.fullmatch(name)
            download_before = (
                self._markdown_download_state()
                if name == MARKDOWN_EXPORT_NAME
                else None
            )
            if name in {'Copy', 'Copy contents'}:
                try:
                    clipboard.clear()
                except Exception as exc:
                    raise TaeyConsultExtractionError(
                        f'could not clear clipboard before the Copy action: {exc}'
                    ) from exc
            clicked = bool(
                self.act.click(
                    name,
                    role=role,
                    display=self.display,
                    contains=False,
                )
            )
            self.found_controls.discard((name, role))
            if not clicked:
                raise TaeyConsultExtractionError(
                    f'act.click({name!r}, role={role!r}) returned a non-success value'
                )
            result = {
                'ok': True,
                'action': action,
                'name': name,
                'role': role,
            }
            if name in OVERFLOW_CONTROL_NAMES:
                self.markdown_export_checked = False
                self.found_controls.discard((MARKDOWN_EXPORT_NAME, 'menu item'))
            if name in {'Copy', 'Copy contents'}:
                body = self._read_clipboard_until_nonempty()
                if not body:
                    raise TaeyConsultExtractionError(
                        f'{name} action landed but the clipboard body stayed empty'
                    )
                self.body = body
                self.body_control = name
                self.body_citation_ids = _citation_ids(body)
                result.update(
                    capture='body',
                    body_control=name,
                    body=body,
                    body_characters=len(body),
                    body_sha256=_sha256_text(body),
                    citation_ids=list(self.body_citation_ids),
                )
            elif name == MARKDOWN_EXPORT_NAME:
                body, download_evidence = self._read_new_markdown_download(
                    download_before or {},
                )
                self.body = body
                self.body_control = name
                self.body_citation_ids = list(download_evidence['citation_ids'])
                self.markdown_sources = list(download_evidence['markdown_sources'])
                self.markdown_source_conflicts = list(
                    download_evidence['markdown_source_conflicts']
                )
                self.markdown_source_definition_count = int(
                    download_evidence['markdown_source_definition_count']
                )
                self.download_path = str(download_evidence['download_path'])
                self.download_sha256 = str(download_evidence['download_sha256'])
                result.update(
                    capture='body',
                    body_control=name,
                    body=body,
                    body_characters=len(body),
                    body_sha256=_sha256_text(body),
                    **download_evidence,
                )
            elif source_match is not None:
                expected_count = int(source_match.group(1))
                sources = self._capture_sources_panel(expected_count)
                self.expected_source_count = expected_count
                self.sources = sources
                result.update(
                    capture='sources',
                    expected_source_count=expected_count,
                    source_count=len(sources),
                    sources=sources,
                    missing=[],
                )
        else:
            result = self._finish()
        return result

    def _execute_full_consult_action(
        self,
        action: str,
        name: str,
        contains: bool,
        role: str,
    ) -> dict[str, object]:
        if action == 'find':
            found = self._find_full_consult_control(name)
            serialized = self._serializable_found(found)
            if serialized is not None:
                self.full_consult_found[self._semantic_slot(name)] = found
                self.found_controls.add((name, str(serialized['role'])))
            else:
                self._forget_semantic_control(name)
                self.found_controls.discard((name, role))
            if name == 'attachment_present' and serialized is not None:
                self.attachment_verified = True
            return {
                'ok': serialized is not None,
                'action': action,
                'semantic_step': name,
                'role': (
                    str(serialized['role'])
                    if serialized is not None
                    else role
                ),
                'contains': contains,
                'found': serialized,
            }
        if action == 'select_mode':
            return self._execute_select_mode()
        if action == 'focus':
            found = self._stored_semantic_control(name)
            node = found.get('node') if isinstance(found, dict) else None
            component = node.get_component_iface() if node is not None else None
            focused = bool(component and component.grab_focus())
            if not focused:
                raise TaeyConsultExtractionError(
                    f'could not focus semantic step {name!r}; nothing else executed'
                )
            self.attach_trigger_focused = True
            return {
                'ok': True,
                'action': action,
                'semantic_step': name,
                'control_name': str(found.get('name') or ''),
                'role': str(found.get('role') or ''),
            }
        if action in {'click', 'activate'}:
            before_url = ''
            if name in {'new_thread', 'attach_trigger', 'upload_item', 'submit'}:
                before_url = self._current_url()
                if not self._normalized_session_url(before_url):
                    raise TaeyConsultExtractionError(
                        f'could not read the browser URL before semantic step '
                        f'{name!r}; nothing executed'
                    )
            control = self._actuate_semantic_control(name, action)
            action_evidence: dict[str, object] = {}
            if name == 'new_thread':
                fresh_evidence = self._wait_for_fresh_thread(before_url)
                self.initial_session_url = before_url
                self.fresh_thread_url = str(
                    fresh_evidence['fresh_thread_url']
                )
                self.fresh_thread_opened = True
                self.found_controls.clear()
                self.full_consult_found.clear()
                action_evidence['fresh_thread'] = fresh_evidence
            elif name == 'attach_trigger':
                self.attach_trigger_activated = True
                if self.runtime.focus_file_dialog():
                    self.browser_url_before_dialog = before_url
                    self.upload_control_clicked = True
                    action_evidence['direct_file_dialog'] = True
            elif name == 'upload_item':
                self.browser_url_before_dialog = before_url
                time.sleep(1.0)
                if not self.runtime.focus_file_dialog():
                    raise TaeyConsultExtractionError(
                        f'{self.platform} upload_item did not expose a focusable '
                        'file dialog'
                    )
                self.upload_control_clicked = True
            elif name == 'submit':
                self.session_url_before = before_url
                self.submitted = True
            elif name == 'post_submit':
                self.post_submitted = True
            if name in {'submit', 'post_submit'}:
                completion_probe_started = time.monotonic()
                completion_control = None
                while (
                    completion_control is None
                    and time.monotonic() - completion_probe_started < 10.0
                ):
                    completion_control = self._find_semantic_control(
                        'completion',
                        must_show=False,
                        scroll=False,
                    )
                    if completion_control is None:
                        time.sleep(0.25)
                serialized_completion = self._serializable_found(
                    completion_control
                )
                self.completion_evidence = {
                    'semantic_step': name,
                    'stop_seen_after_action': completion_control is not None,
                    'completion_control_after_action': serialized_completion,
                    'completion_probe_elapsed_seconds': round(
                        time.monotonic() - completion_probe_started,
                        3,
                    ),
                }
                action_evidence.update(self.completion_evidence)
            return {
                'ok': True,
                'action': action,
                **control,
                **action_evidence,
            }
        if action == 'typeahead':
            attachment = (self.cfg.get('workflow') or {}).get('attachment') or {}
            typeahead_label = (
                str(attachment.get('typeahead_label') or '').strip()
                if isinstance(attachment, dict)
                else ''
            )
            if not typeahead_label:
                raise TaeyConsultExtractionError(
                    f'{self.platform} upload_item has no configured typeahead label'
                )
            before_url = self._current_url()
            if not self._normalized_session_url(before_url):
                raise TaeyConsultExtractionError(
                    'could not read the browser URL before upload typeahead'
                )
            if not clipboard.write(typeahead_label):
                raise TaeyConsultExtractionError(
                    'upload typeahead label could not be staged on the clipboard'
                )
            if clipboard.read() != typeahead_label:
                raise TaeyConsultExtractionError(
                    'upload typeahead clipboard verification failed'
                )
            if not self.act.key('ctrl+v', display=self.display):
                raise TaeyConsultExtractionError(
                    'upload typeahead paste key returned a non-success value'
                )
            self.browser_url_before_dialog = before_url
            self.upload_typeahead_entered = True
            return {
                'ok': True,
                'action': action,
                'semantic_step': name,
                'typeahead_characters': len(typeahead_label),
                'typeahead_sha256': _sha256_text(typeahead_label),
            }
        if action == 'key':
            pressed = bool(self.act.key(name, display=self.display))
            if not pressed:
                raise TaeyConsultExtractionError(
                    f'act.key({name!r}) returned a non-success value'
                )
            attachment = (self.cfg.get('workflow') or {}).get('attachment') or {}
            submit_keys = (
                tuple(
                    str(value)
                    for value in (
                        attachment.get('typeahead_submit_keys') or ()
                    )
                )
                if isinstance(attachment, dict)
                else ()
            )
            if self.upload_typeahead_entered and not self.upload_control_clicked:
                expected_key = submit_keys[self.upload_submit_key_index]
                if name != expected_key:
                    raise TaeyConsultExtractionError(
                        f'upload typeahead expected key {expected_key!r}, '
                        f'got {name!r}'
                    )
                self.upload_submit_key_index += 1
                if self.upload_submit_key_index == len(submit_keys):
                    time.sleep(1.0)
                    if not self.runtime.focus_file_dialog():
                        raise TaeyConsultExtractionError(
                            f'{self.platform} upload typeahead did not expose a '
                            'focusable file dialog'
                        )
                    self.upload_control_clicked = True
            elif name == 'ctrl+l':
                self.dialog_location_opened = True
            elif name == 'ctrl+a':
                self.dialog_path_selected = True
            elif name == 'Return':
                self.attachment_submitted = True
                time.sleep(1.0)
            else:
                if (
                    isinstance(attachment, dict)
                    and name == attachment.get('open_key')
                ):
                    self.attach_trigger_activated = True
            return {'ok': True, 'action': action, 'name': name}
        if action == 'paste_path':
            if self.attachment_path is None:
                raise TaeyConsultExtractionError(
                    'paste_path is unavailable without an attachment'
                )
            path_text = str(self.attachment_path)
            if not clipboard.write(path_text):
                raise TaeyConsultExtractionError(
                    'attachment path could not be staged on the clipboard'
                )
            staged = clipboard.read()
            if staged != path_text:
                raise TaeyConsultExtractionError(
                    'attachment path clipboard verification failed'
                )
            if not self.act.key('ctrl+v', display=self.display):
                raise TaeyConsultExtractionError(
                    'attachment path paste key returned a non-success value'
                )
            browser_url_after_paste = self._current_url()
            if browser_url_after_paste != self.browser_url_before_dialog:
                raise TaeyConsultExtractionError(
                    'file chooser focus proof failed after path paste; refusing to '
                    f'press Return; browser_url_before={self.browser_url_before_dialog!r}, '
                    f'browser_url_after={browser_url_after_paste!r}'
                )
            self.attachment_path_pasted = True
            return {
                'ok': True,
                'action': action,
                'name': name,
                'attachment_characters': len(path_text),
                'attachment_sha256': self.attachment_sha256,
            }
        if action == 'paste_prompt':
            found = self._stored_semantic_control(name)
            if found is None:
                raise TaeyConsultExtractionError(
                    'paste_prompt requires the live composer_input control'
                )
            control_name = str(found.get('name') or '')
            control_role = str(found.get('role') or '')
            composer_step = self.full_consult_contract['steps'].get(name) or {}
            paste_strategy = str(
                composer_step.get('paste_strategy') or 'act_paste'
            )
            if paste_strategy == 'focus_and_paste':
                node = found.get('node')
                component = (
                    node.get_component_iface()
                    if node is not None
                    else None
                )
                focused = bool(component and component.grab_focus())
                pasted = bool(focused and self.runtime.paste(self.framing_prompt))
                verification_sentinel = (
                    f'taey-prompt-proof-{self.framing_prompt_sha256[:16]}'
                )
                if (
                    pasted
                    and clipboard.write(verification_sentinel)
                    and self.act.key('ctrl+a', display=self.display)
                    and self.act.key('ctrl+c', display=self.display)
                ):
                    pasted = (
                        clipboard.read().strip()
                        == self.framing_prompt.strip()
                    )
                else:
                    pasted = False
            else:
                pasted = bool(
                    self.act.paste_into(
                        control_name,
                        self.framing_prompt,
                        role=control_role,
                        display=self.display,
                        contains=False,
                        clear=True,
                        verify=True,
                    )
                )
            if not pasted:
                raise TaeyConsultExtractionError(
                    'short framing prompt paste verification failed'
                )
            self._forget_semantic_control(name)
            self.found_controls.discard((name, role))
            self.prompt_entered = True
            return {
                'ok': True,
                'action': action,
                'semantic_step': name,
                'control_name': control_name,
                'role': control_role,
                'paste_strategy': paste_strategy,
                'framing_prompt_characters': len(self.framing_prompt),
                'framing_prompt_sha256': self.framing_prompt_sha256,
            }
        if action == 'wait_complete':
            evidence = self._wait_for_full_consult_completion()
            self.consult_completed = True
            self.session_url_after = str(evidence['session_url_after'])
            self.completion_evidence = evidence
            self.found_controls.clear()
            return {'ok': True, 'action': action, **evidence}
        raise TaeyConsultExtractionError(
            f'action {action!r} is unavailable before consult completion'
        )

    def _execute_full_consult_extraction_action(
        self,
        action: str,
        name: str,
        contains: bool,
        role: str,
    ) -> dict[str, object]:
        self._assert_bound_answer_thread()
        if action == 'find':
            found = self._find_full_consult_control(name)
            serialized = self._serializable_found(found)
            if serialized is not None:
                self.full_consult_found[self._semantic_slot(name)] = found
                self.found_controls.add((name, str(serialized['role'])))
            else:
                self._forget_semantic_control(name)
                self.found_controls.discard((name, role))
            return {
                'ok': serialized is not None,
                'action': action,
                'semantic_step': name,
                'role': (
                    str(serialized['role'])
                    if serialized is not None
                    else role
                ),
                'contains': contains,
                'found': serialized,
            }
        if action in {'click', 'activate'}:
            copy_step = self.full_consult_contract['steps']['copy_response']
            elements = tuple(copy_step.get('elements') or ())
            final_control = self.copy_response_index == len(elements) - 1
            if final_control:
                try:
                    clipboard.clear()
                except Exception as exc:
                    raise TaeyConsultExtractionError(
                        f'could not clear clipboard before copy_response: {exc}'
                    ) from exc
            control = self._actuate_semantic_control(name, action)
            if not final_control:
                self.copy_response_index += 1
                return {
                    'ok': True,
                    'action': action,
                    **control,
                    'copy_response_index': self.copy_response_index,
                }
            body = self._read_clipboard_until_nonempty()
            if not body:
                raise TaeyConsultExtractionError(
                    f'{self.platform} copy_response action landed but the '
                    'clipboard body stayed empty'
                )
            self.body = body
            self.body_control = str(control['control_name'])
            self.body_citation_ids = _citation_ids(body)
            return {
                'ok': True,
                'action': action,
                **control,
                'capture': 'body',
                'body': body,
                'body_characters': len(body),
                'body_sha256': _sha256_text(body),
            }
        return self._finish()

    def _execute(self, arguments: dict[str, object]) -> dict[str, object]:
        action, name, contains, role = self._validated_action(arguments)
        if self.full_consult and not self.consult_completed:
            result = self._execute_full_consult_action(
                action,
                name,
                contains,
                role,
            )
        elif self.full_consult:
            result = self._execute_full_consult_extraction_action(
                action,
                name,
                contains,
                role,
            )
        else:
            result = self._execute_extraction_action(
                action,
                name,
                contains,
                role,
            )
        if action != 'finish':
            result['required_next_action'] = self._required_action()
        action_record = {
            'turn': len(self.actions) + 1,
            'arguments': dict(arguments),
            'ok': bool(result.get('ok')),
            'body_characters': len(self.body),
            'source_count': len(self.sources),
        }
        if action == 'find':
            action_record['found'] = result.get('found')
        if result.get('capture'):
            action_record['capture'] = result.get('capture')
        self.actions.append(action_record)
        self._append_turn_log({'event': 'action', **action_record})
        return result

    def run(self) -> dict[str, object]:
        extraction_task = (
            'First find the exact Copy contents push button. If found, click it. If '
            'absent, find the exact Export as Markdown menu item to detect an already '
            'open menu. If absent, find the exact Session actions push button (the '
            'accessible name of the top visual ellipsis); only if absent, find the '
            'exact "..." push button. Click the exact overflow name returned, then '
            'find and click the exact Export as Markdown menu item; the harness '
            'returns the complete exported body and citations. Do not use plain Copy '
            'or Download. Next find a push button whose accessible name contains '
            '" source"; click the exact N sources name returned by find and read the '
            'complete source panel; the harness then validates and finalizes.'
        )
        if self.full_consult:
            task = (
                f'Run one complete {self.platform} consultation on display '
                f'{self.display} with consult_extract_action only, one action per '
                'turn. Use only the platform-agnostic semantic names supplied by '
                'required_next_action: new_thread, attach_trigger, upload_item, '
                'attachment_present, composer_input, select_mode, submit, '
                'post_submit, completion, and copy_response. '
                'The harness resolves those names through the platform YAML and '
                'executes the exact live AT-SPI control. It owns one validated '
                'attachment named '
                f'{self.attachment_path.name!r} at SHA256 '
                f'{self.attachment_sha256}; never request, reproduce, or paste its '
                'contents into the composer. The harness also owns a short framing '
                f'prompt of {len(self.framing_prompt)} characters at SHA256 '
                f'{self.framing_prompt_sha256}; use paste_prompt without emitting its '
                'text. Begin by finding new_thread. The harness must prove a clean '
                'fresh composer before attachment. Follow each returned '
                'required_next_action exactly through file selection, verified '
                'attachment presence, prompt entry, configured mode, submission, '
                'completion, and response copy. '
                'The harness binds extraction to the answer-thread URL created by '
                'that submission and refuses any other thread. Finish only after '
                'the configured copy_response action returns a non-empty body.'
            )
        else:
            task = (
                f'Extract the completed Perplexity Deep Research answer on consult '
                f'display {self.display}. Use consult_extract_action only, one action '
                'per turn. '
                + extraction_task
            )
        task += (
            ' Never activate a control after its find returned ok=false. Never click '
            'coordinates. Follow required_next_action exactly whenever the harness '
            'returns it.'
        )
        if not self.full_consult:
            task += (
                ' Do not finish until citation_ids is non-empty, source_count equals '
                'expected_source_count, and missing=[].'
            )
        overlay = (
            '\n\nCLOSED CONSULTATION SEAT: The sole callable tool is '
            'consult_extract_action. It is the harness binding of canonical act.py '
            'operations; do not emit shell commands, file contents, prompt text, or '
            'prose. One tool call per turn. Accessible names, never coordinates. The '
            'harness state machine is authoritative: emit required_next_action exactly.'
        )
        messages: list[dict[str, object]] = [
            {'role': 'system', 'content': self.system_prompt + overlay},
            {'role': 'user', 'content': task},
        ]
        pre_execution_retry_used = False
        max_turns = MAX_FULL_CONSULT_TURNS if self.full_consult else MAX_TURNS
        for turn in range(1, max_turns + 1):
            message = self._message(self._call_taey(messages, turn))
            call_id, arguments = self._arguments(message)
            try:
                self._validated_action(arguments)
            except TaeyConsultControlError:
                raise
            except TaeyConsultStateError as exc:
                rejection = {
                    'ok': False,
                    'executed': False,
                    'error': str(exc),
                    'instruction': (
                        'Emit exactly required_next_action on the next turn; do not '
                        'repeat the rejected action'
                    ),
                    'required_next_action': exc.required_action,
                }
                self._append_turn_log({
                    'event': 'state_rejection',
                    'turn': turn,
                    'arguments': dict(arguments),
                    'error': str(exc),
                    'required_action': exc.required_action,
                })
                messages.extend([
                    message,
                    {
                        'role': 'tool',
                        'tool_call_id': call_id or f'consult_extract_action_{turn}',
                        'content': json.dumps(
                            rejection,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(',', ':'),
                        ),
                    },
                ])
                continue
            except TaeyConsultExtractionError as exc:
                if pre_execution_retry_used:
                    raise TaeyConsultExtractionError(
                        f'Taey repeated an invalid pre-execution action: {exc}'
                    ) from exc
                pre_execution_retry_used = True
                required_action = self._required_action()
                rejection = {
                    'ok': False,
                    'executed': False,
                    'error': str(exc),
                    'instruction': (
                        f'{PRE_EXECUTION_REJECTION}; emit required_next_action '
                        'exactly'
                    ),
                    'required_next_action': required_action,
                }
                self._append_turn_log({
                    'event': 'pre_execution_rejection',
                    'turn': turn,
                    'arguments': dict(arguments),
                    'error': str(exc),
                    'required_action': required_action,
                })
                messages.extend([
                    message,
                    {
                        'role': 'tool',
                        'tool_call_id': call_id or f'consult_extract_action_{turn}',
                        'content': json.dumps(
                            rejection,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(',', ':'),
                        ),
                    },
                ])
                continue
            result = self._execute(arguments)
            deterministic_finish = (
                arguments.get('action') != 'finish'
                and result.get('required_next_action')
                == {'action': 'finish', 'name': '', 'contains': False}
            )
            if arguments.get('action') == 'finish' or deterministic_finish:
                if deterministic_finish:
                    result = self._finish()
                    result['finish_reason'] = (
                        'deterministic_after_complete_source_capture'
                    )
                result['neutral_reset'] = self._reset_to_neutral()
                result.update(
                    turns=turn,
                    model=self.model,
                    endpoint=self.endpoint,
                    tool_schema_sha256=hashlib.sha256(
                        _canonical_bytes(consult_extract_action_tool())
                    ).hexdigest(),
                    system_prompt_path=str(self.system_prompt_path),
                    system_prompt_sha256=_sha256_text(self.system_prompt),
                    act_path=str(self.act_path),
                )
                return result
            messages.extend([
                message,
                {
                    'role': 'tool',
                    'tool_call_id': call_id or f'consult_extract_action_{turn}',
                    'content': json.dumps(
                        result,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(',', ':'),
                    ),
                },
            ])
        raise TaeyConsultExtractionError(
            f'Taey consultation seat exhausted {max_turns} turns'
        )


def extract_with_taey(
    *,
    platform: str,
    display: str,
    endpoint: str | None = None,
    model: str | None = None,
    capture_root: str | Path | None = None,
) -> dict[str, object]:
    return TaeyConsultExtractionSeat(
        platform=platform,
        display=display,
        endpoint=endpoint,
        model=model,
        capture_root=capture_root,
    ).run()


def consult_with_taey(
    *,
    platform: str,
    display: str,
    attachment_path: str | Path,
    framing_prompt: str,
    endpoint: str | None = None,
    model: str | None = None,
    capture_root: str | Path | None = None,
    completion_timeout: float = DEFAULT_COMPLETION_TIMEOUT_SECONDS,
) -> dict[str, object]:
    return TaeyConsultExtractionSeat(
        platform=platform,
        display=display,
        endpoint=endpoint,
        model=model,
        capture_root=capture_root,
        attachment_path=attachment_path,
        framing_prompt=framing_prompt,
        completion_timeout=completion_timeout,
    ).run()
