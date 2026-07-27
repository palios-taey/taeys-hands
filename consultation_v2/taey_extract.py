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
from typing import Any
import urllib.parse
import urllib.request

from consultation_v2 import clipboard


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
ATTACH_TRIGGER_NAME = 'Add files or tools'
UPLOAD_FILE_NAME = 'Upload files or images'
COMPOSER_CONTROL_NAME = '\ufffc'
DEEP_RESEARCH_NAME = 'Deep research'
SEARCH_MODE_NAME = 'Search'
SUBMIT_CONTROL_NAME = 'Submit'
STOP_CONTROL_NAME = 'Stop response (Esc)'
ATTACHMENT_PATH_SENTINEL = 'attachment path'
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
                'a citation-bearing body and all sources were captured.'
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
                            'paste_path',
                            'paste_prompt',
                            'wait_complete',
                            'finish',
                        ],
                    },
                    'name': {
                        'type': 'string',
                        'description': (
                            'Exact accessible control name, or a substring for find. '
                            'Use an empty string for finish.'
                        ),
                    },
                    'contains': {
                        'type': 'boolean',
                        'description': (
                            'For find only: match name as a substring. Click always requires '
                            'the exact name returned by a successful find. Use false for finish.'
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


def _markdown_sources(value: str) -> list[dict[str, object]]:
    definitions: dict[int, str] = {}
    for line in (value or '').splitlines():
        match = MARKDOWN_SOURCE_DEFINITION_PATTERN.fullmatch(line.strip())
        if match is None:
            continue
        source_id = int(match.group(1).rsplit('_', 1)[-1])
        target = match.group(2).strip()
        previous = definitions.get(source_id)
        if previous is not None and previous != target:
            raise TaeyConsultExtractionError(
                f'Markdown export has conflicting definitions for source {source_id}'
            )
        definitions[source_id] = target
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
    return sources


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
        'prune_inactive_document',
    ):
        if not callable(getattr(module, name, None)):
            raise TaeyConsultExtractionError(
                f'canonical act.py does not expose required callable {name!r}'
            )
    return module


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
        if self.platform != 'perplexity':
            raise TaeyConsultExtractionError(
                f'consult extraction seat does not yet support {self.platform!r}'
            )
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
        self.copy_contents_checked = False
        self.markdown_export_checked = False
        self.overflow_checked: set[str] = set()
        self.markdown_sources: list[dict[str, object]] = []
        self.download_path = ''
        self.download_sha256 = ''
        self.attach_trigger_focused = False
        self.attach_trigger_activated = False
        self.upload_control_clicked = False
        self.dialog_location_opened = False
        self.dialog_path_selected = False
        self.attachment_path_pasted = False
        self.attachment_submitted = False
        self.attachment_verified = False
        self.prompt_entered = False
        self.mode_checked = False
        self.mode_menu_opened = False
        self.mode_selected = False
        self.mode_active = False
        self.submitted = False
        self.consult_completed = False
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

    @staticmethod
    def _normalized_action(arguments: dict[str, object]) -> tuple[str, str, bool]:
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
            'paste_path',
            'paste_prompt',
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
            'paste_path',
            'paste_prompt',
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
        if action == 'key' and name not in {'ctrl+l', 'ctrl+a', 'Return'}:
            raise TaeyConsultExtractionError(
                f'consultation key action is restricted, got {name!r}'
            )
        if action == 'paste_path' and name != ATTACHMENT_PATH_SENTINEL:
            raise TaeyConsultExtractionError(
                f'paste_path requires name={ATTACHMENT_PATH_SENTINEL!r}'
            )
        return action, name, contains

    def _control_role(self, action: str, name: str) -> str:
        if name == COMPOSER_CONTROL_NAME:
            return 'entry'
        if name == DEEP_RESEARCH_NAME:
            if self.mode_menu_opened and not self.mode_selected:
                return 'radio menu item'
            return 'toggle button'
        if name == SEARCH_MODE_NAME:
            return 'toggle button'
        if name == UPLOAD_FILE_NAME:
            return 'menu item'
        return 'menu item' if name == MARKDOWN_EXPORT_NAME else 'push button'

    def _validated_action(
        self,
        arguments: dict[str, object],
    ) -> tuple[str, str, bool, str]:
        action, name, contains = self._normalized_action(arguments)
        required = self._required_action()
        if arguments != required:
            raise TaeyConsultStateError(required)
        role = self._control_role(action, name)
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
        return self._required_extraction_action()

    def _required_full_consult_action(self) -> dict[str, object]:
        attach_trigger = (ATTACH_TRIGGER_NAME, 'push button')
        if not self.attach_trigger_focused:
            if attach_trigger in self.found_controls:
                return {
                    'action': 'focus',
                    'name': ATTACH_TRIGGER_NAME,
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': ATTACH_TRIGGER_NAME,
                'contains': False,
            }
        if not self.attach_trigger_activated:
            return {'action': 'key', 'name': 'Return', 'contains': False}
        upload_control = (UPLOAD_FILE_NAME, 'menu item')
        if not self.upload_control_clicked:
            if upload_control in self.found_controls:
                return {
                    'action': 'click',
                    'name': UPLOAD_FILE_NAME,
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': UPLOAD_FILE_NAME,
                'contains': False,
            }
        if not self.dialog_location_opened:
            return {'action': 'key', 'name': 'ctrl+l', 'contains': False}
        if not self.dialog_path_selected:
            return {'action': 'key', 'name': 'ctrl+a', 'contains': False}
        if not self.attachment_path_pasted:
            return {
                'action': 'paste_path',
                'name': ATTACHMENT_PATH_SENTINEL,
                'contains': False,
            }
        if not self.attachment_submitted:
            return {'action': 'key', 'name': 'Return', 'contains': False}
        if not self.attachment_verified:
            return {
                'action': 'find',
                'name': self.attachment_path.name if self.attachment_path else '',
                'contains': True,
            }
        composer = (COMPOSER_CONTROL_NAME, 'entry')
        if not self.prompt_entered:
            if composer in self.found_controls:
                return {
                    'action': 'paste_prompt',
                    'name': COMPOSER_CONTROL_NAME,
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': COMPOSER_CONTROL_NAME,
                'contains': False,
            }
        if not self.mode_active:
            deep_toggle = (DEEP_RESEARCH_NAME, 'toggle button')
            if not self.mode_checked:
                return {
                    'action': 'find',
                    'name': DEEP_RESEARCH_NAME,
                    'contains': False,
                }
            if deep_toggle in self.found_controls:
                raise TaeyConsultControlError(
                    'Deep research toggle was found but not recognized as active'
                )
            search_toggle = (SEARCH_MODE_NAME, 'toggle button')
            if not self.mode_menu_opened:
                if search_toggle in self.found_controls:
                    return {
                        'action': 'click',
                        'name': SEARCH_MODE_NAME,
                        'contains': False,
                    }
                return {
                    'action': 'find',
                    'name': SEARCH_MODE_NAME,
                    'contains': False,
                }
            deep_option = (DEEP_RESEARCH_NAME, 'radio menu item')
            if deep_option in self.found_controls:
                return {
                    'action': 'click',
                    'name': DEEP_RESEARCH_NAME,
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': DEEP_RESEARCH_NAME,
                'contains': False,
            }
        submit = (SUBMIT_CONTROL_NAME, 'push button')
        if not self.submitted:
            if submit in self.found_controls:
                return {
                    'action': 'activate',
                    'name': SUBMIT_CONTROL_NAME,
                    'contains': False,
                }
            return {
                'action': 'find',
                'name': SUBMIT_CONTROL_NAME,
                'contains': False,
            }
        return {'action': 'wait_complete', 'name': '', 'contains': False}

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
        name: str,
        role: str,
        contains: bool,
        *,
        timeout: float = 15.0,
    ) -> object:
        deadline = time.monotonic() + timeout
        roles = (role,)
        if (
            self.attachment_path is not None
            and name == self.attachment_path.name
            and contains
        ):
            roles = ('push button', 'section', 'link', 'heading')
        while time.monotonic() < deadline:
            for candidate_role in roles:
                found = self.act.find(
                    name,
                    role=candidate_role,
                    display=self.display,
                    contains=contains,
                )
                if found:
                    return found
            time.sleep(0.3)
        return None

    def _current_url(self) -> str:
        value = self.act.current_url_atspi(self.display)
        if not isinstance(value, dict) or not value.get('ok'):
            return ''
        return str(value.get('url') or '').strip()

    def _wait_for_full_consult_completion(self) -> dict[str, object]:
        started = time.monotonic()
        deadline = started + self.completion_timeout
        stop_seen = False
        last_url = ''
        last_source_name = ''
        last_body_control = ''
        while time.monotonic() < deadline:
            last_url = self._current_url()
            stop = self.act.find(
                STOP_CONTROL_NAME,
                role='push button',
                display=self.display,
                contains=False,
                must_show=False,
                scroll=False,
            )
            stop_seen = stop_seen or bool(stop)
            source = self.act.find(
                ' source',
                role='push button',
                display=self.display,
                contains=True,
                must_show=False,
                scroll=False,
            )
            source_name = (
                str(source.get('name') or '').strip()
                if isinstance(source, dict)
                else ''
            )
            if SOURCE_CONTROL_PATTERN.fullmatch(source_name):
                last_source_name = source_name
            copy_contents = self.act.find(
                'Copy contents',
                role='push button',
                display=self.display,
                contains=False,
                must_show=False,
                scroll=False,
            )
            session_actions = self.act.find(
                'Session actions',
                role='push button',
                display=self.display,
                contains=False,
                must_show=False,
                scroll=False,
            )
            last_body_control = (
                'Copy contents'
                if copy_contents
                else 'Session actions' if session_actions else ''
            )
            landed = (
                '/search/' in last_url
                and not stop
                and bool(last_source_name)
                and bool(last_body_control)
                and (
                    stop_seen
                    or (
                        bool(self.session_url_before)
                        and last_url != self.session_url_before
                    )
                )
            )
            if landed:
                time.sleep(1.0)
                return {
                    'completed': True,
                    'elapsed_seconds': round(time.monotonic() - started, 3),
                    'stop_seen': stop_seen,
                    'session_url_before': self.session_url_before,
                    'session_url_after': last_url,
                    'source_control': last_source_name,
                    'body_control': last_body_control,
                }
            time.sleep(1.0)
        raise TaeyConsultExtractionError(
            'Perplexity full consult did not expose a completed citation/source '
            f'surface within {self.completion_timeout:.1f}s; stop_seen={stop_seen}, '
            f'url={last_url!r}, source={last_source_name!r}, '
            f'body_control={last_body_control!r}'
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
                if expected_count in file_counts:
                    file_panels += 1
            exact = [items for items in candidates if len(items) == expected_count]
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1:
                raise TaeyConsultExtractionError(
                    'multiple Sources panels exposed the expected source count'
                )
            if file_panels > 1:
                raise TaeyConsultExtractionError(
                    'multiple Sources panels exposed the expected file count'
                )
            if file_panels == 1:
                source_ids = [
                    int(item['index'])
                    for item in self.markdown_sources
                ]
                expected_ids = list(range(1, expected_count + 1))
                if source_ids != expected_ids:
                    raise TaeyConsultExtractionError(
                        'Sources panel file count does not match the Markdown export '
                        f'definitions: panel={expected_count}, definitions={source_ids}'
                    )
                return list(self.markdown_sources)
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
                return body, {
                    'download_path': str(path),
                    'download_characters': len(raw),
                    'download_body_characters': len(body),
                    'download_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                    'citation_ids': _citation_ids(raw),
                    'markdown_sources': _markdown_sources(raw),
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
        }
        if self.full_consult:
            result['consultation'] = {
                'attachment_path': str(self.attachment_path),
                'attachment_sha256': self.attachment_sha256,
                'attachment_verified': self.attachment_verified,
                'framing_prompt_characters': len(self.framing_prompt),
                'framing_prompt_sha256': self.framing_prompt_sha256,
                'mode': DEEP_RESEARCH_NAME,
                'mode_active': self.mode_active,
                'submitted': self.submitted,
                'completed': self.consult_completed,
                'browser_url_before_dialog': self.browser_url_before_dialog,
                'session_url_before': self.session_url_before,
                'session_url_after': self.session_url_after,
                'completion': dict(self.completion_evidence),
            }
        return result

    def _execute_extraction_action(
        self,
        action: str,
        name: str,
        contains: bool,
        role: str,
    ) -> dict[str, object]:
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
            found = self._find_full_consult_control(name, role, contains)
            serialized = self._serializable_found(found)
            if serialized is not None:
                control_name = (
                    str(serialized['name'])
                    if contains
                    else name
                )
                self.found_controls.add((control_name, role))
            elif not contains:
                self.found_controls.discard((name, role))
            if (
                self.attachment_path is not None
                and name == self.attachment_path.name
                and contains
                and serialized is not None
            ):
                self.attachment_verified = True
            if name == DEEP_RESEARCH_NAME and role == 'toggle button':
                self.mode_checked = True
                self.mode_active = serialized is not None
            return {
                'ok': serialized is not None,
                'action': action,
                'query': name,
                'role': role,
                'contains': contains,
                'found': serialized,
            }
        if action == 'focus':
            found = self.act.find(
                name,
                role=role,
                display=self.display,
                contains=False,
                must_show=True,
                scroll=True,
            )
            node = found.get('node') if isinstance(found, dict) else None
            component = node.get_component_iface() if node is not None else None
            focused = bool(component and component.grab_focus())
            if not focused:
                raise TaeyConsultExtractionError(
                    f'could not focus exact {name!r} control; nothing else executed'
                )
            self.attach_trigger_focused = True
            return {
                'ok': True,
                'action': action,
                'name': name,
                'role': role,
            }
        if action in {'click', 'activate'}:
            actuator = self.act.do if action == 'activate' else self.act.click
            before_url = ''
            if name in {UPLOAD_FILE_NAME, SUBMIT_CONTROL_NAME}:
                before_url = self._current_url()
                if not before_url.startswith(('http://', 'https://')):
                    raise TaeyConsultExtractionError(
                        f'could not read the browser URL before activating {name!r}; '
                        'nothing executed'
                    )
            acted = bool(
                actuator(
                    name,
                    role=role,
                    display=self.display,
                    contains=False,
                )
            )
            self.found_controls.discard((name, role))
            if not acted:
                raise TaeyConsultExtractionError(
                    f'act.{actuator.__name__}({name!r}, role={role!r}) '
                    'returned a non-success value'
                )
            if name == UPLOAD_FILE_NAME:
                self.browser_url_before_dialog = before_url
                self.upload_control_clicked = True
                time.sleep(1.0)
            elif name == SEARCH_MODE_NAME:
                self.mode_menu_opened = True
                self.found_controls.discard((
                    DEEP_RESEARCH_NAME,
                    'radio menu item',
                ))
            elif name == DEEP_RESEARCH_NAME and role == 'radio menu item':
                self.mode_selected = True
                self.mode_menu_opened = False
                self.mode_checked = False
                self.found_controls.discard((
                    DEEP_RESEARCH_NAME,
                    'toggle button',
                ))
            elif name == SUBMIT_CONTROL_NAME:
                self.session_url_before = before_url
                self.submitted = True
            return {
                'ok': True,
                'action': action,
                'name': name,
                'role': role,
            }
        if action == 'key':
            pressed = bool(self.act.key(name, display=self.display))
            if not pressed:
                raise TaeyConsultExtractionError(
                    f'act.key({name!r}) returned a non-success value'
                )
            if name == 'ctrl+l':
                self.dialog_location_opened = True
            elif name == 'ctrl+a':
                self.dialog_path_selected = True
            elif name == 'Return':
                if (
                    self.attach_trigger_focused
                    and not self.attach_trigger_activated
                ):
                    self.attach_trigger_activated = True
                    self.found_controls.discard((UPLOAD_FILE_NAME, 'menu item'))
                else:
                    self.attachment_submitted = True
                    time.sleep(1.0)
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
            pasted = bool(
                self.act.paste_into(
                    name,
                    self.framing_prompt,
                    role=role,
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
            self.prompt_entered = True
            return {
                'ok': True,
                'action': action,
                'name': name,
                'role': role,
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

    def _execute(self, arguments: dict[str, object]) -> dict[str, object]:
        action, name, contains, role = self._validated_action(arguments)
        if self.full_consult and not self.consult_completed:
            result = self._execute_full_consult_action(
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
            'complete source panel; then finish with name="" and contains=false.'
        )
        if self.full_consult:
            task = (
                f'Run one complete Perplexity Deep Research consultation on display '
                f'{self.display} with consult_extract_action only, one action per '
                'turn. The harness owns one validated attachment named '
                f'{self.attachment_path.name!r} at SHA256 '
                f'{self.attachment_sha256}; never request, reproduce, or paste its '
                'contents into the composer. The harness also owns a short framing '
                f'prompt of {len(self.framing_prompt)} characters at SHA256 '
                f'{self.framing_prompt_sha256}; use paste_prompt without emitting its '
                'text. Find and focus Add files or tools, activate it with Return, '
                'then use Upload files or images and the file '
                'chooser ctrl+l, ctrl+a, paste_path, Return, and verify the filename '
                'chip. '
                'Then find the composer and paste_prompt. Verify Deep research is '
                'active; if its active toggle is absent, open Search and activate the '
                'Deep research radio menu item, then verify the active toggle. Find '
                'and activate Submit, wait_complete, and only then extract. '
                + extraction_task
            )
        else:
            task = (
                f'Extract the completed Perplexity Deep Research answer on consult '
                f'display {self.display}. Use consult_extract_action only, one action '
                'per turn. '
                + extraction_task
            )
        task += (
            ' Never click a control after its find returned ok=false. Never click '
            'coordinates. Follow required_next_action exactly whenever the harness '
            'returns it. Do not finish until citation_ids is non-empty, source_count '
            'equals expected_source_count, and missing=[].'
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
                        'Emit exactly required_action on the next turn; do not repeat '
                        'the rejected action'
                    ),
                    'required_action': exc.required_action,
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
                rejection = {
                    'ok': False,
                    'executed': False,
                    'error': str(exc),
                    'instruction': PRE_EXECUTION_REJECTION,
                }
                self._append_turn_log({
                    'event': 'pre_execution_rejection',
                    'turn': turn,
                    'arguments': dict(arguments),
                    'error': str(exc),
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
            if arguments.get('action') == 'finish':
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
