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


CONSULT_DISPLAYS = frozenset({':2', ':3', ':4', ':5', ':6'})
DEFAULT_ACT_PATH = Path('/home/mira/treasurer/scripts/loop/act.py')
DEFAULT_SYSTEM_PROMPT_PATH = Path('/home/mira/data/corpus/layer_1/SYSTEM_PROMPT.md')
DEFAULT_EP3_BASE = 'http://10.0.0.197:8000/v1'
DEFAULT_EP3_MODEL = 'ep3'
MAX_TURNS = 12
SOURCE_CONTROL_PATTERN = re.compile(r'^\s*([0-9]+)\s+sources\s*$', re.IGNORECASE)
BODY_CITATION_PATTERN = re.compile(r'(?<!\^)\[([0-9]+)\]')
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


def consult_extract_action_tool() -> dict[str, object]:
    return {
        'type': 'function',
        'function': {
            'name': 'consult_extract_action',
            'description': (
                'Perform one named accessibility action on the completed consult. '
                'Use find before click and finish only after body and sources were captured.'
            ),
            'parameters': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['action', 'name', 'contains'],
                'properties': {
                    'action': {
                        'type': 'string',
                        'enum': ['find', 'click', 'finish'],
                    },
                    'name': {
                        'type': 'string',
                        'description': (
                            'Accessible push-button name. Use an empty string for finish.'
                        ),
                    },
                    'contains': {
                        'type': 'boolean',
                        'description': (
                            'For find only: match name as a substring. Click always requires '
                            'the exact name returned by find. Use false for finish.'
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
    for name in ('find', 'click', 'firefox_app', 'prune_inactive_document'):
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
        self.body = ''
        self.sources: list[dict[str, object]] = []
        self.expected_source_count = 0
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
        if action not in {'find', 'click', 'finish'}:
            raise TaeyConsultExtractionError(
                f'unsupported consult extraction action {action!r}'
            )
        if not isinstance(contains, bool):
            raise TaeyConsultExtractionError('contains must be a boolean')
        if action in {'find', 'click'} and not name:
            raise TaeyConsultExtractionError(f'{action} requires a non-empty name')
        if action == 'finish' and (name or contains):
            raise TaeyConsultExtractionError(
                'finish requires name="" and contains=false'
            )
        if action == 'click' and contains:
            raise TaeyConsultExtractionError(
                'click requires an exact accessible name from a prior find'
            )
        return action, name, contains

    @staticmethod
    def _serializable_found(found: object) -> dict[str, object] | None:
        if not isinstance(found, dict):
            return None
        return {
            'name': str(found.get('name') or ''),
            'role': str(found.get('role') or ''),
            'states': sorted(str(value) for value in (found.get('states') or [])),
        }

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

    def _capture_sources_panel(
        self,
        expected_count: int,
        *,
        timeout: float = 10.0,
    ) -> list[dict[str, object]]:
        deadline = time.monotonic() + timeout
        last_count = 0
        while time.monotonic() < deadline:
            candidates: list[list[dict[str, object]]] = []
            for anchor in self._find_named_nodes('Sources', 'push button'):
                sources = self._source_links(self._following_siblings(anchor))
                if sources:
                    candidates.append(sources)
            exact = [items for items in candidates if len(items) == expected_count]
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1:
                raise TaeyConsultExtractionError(
                    'multiple Sources panels exposed the expected source count'
                )
            last_count = max((len(items) for items in candidates), default=0)
            time.sleep(0.25)
        raise TaeyConsultExtractionError(
            f'Sources panel exposed {last_count}/{expected_count} source links'
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

    def _finish(self) -> dict[str, object]:
        if not self.body:
            raise TaeyConsultExtractionError(
                'Taey attempted finish before the Copy clipboard body was captured'
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
        citation_ids = sorted({
            int(value)
            for value in BODY_CITATION_PATTERN.findall(self.body)
        })
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
                f"{item['index']}. {item['url']}"
                for item in self.sources
            )
        )
        return {
            'ok': True,
            'content': content,
            'body': self.body,
            'body_characters': len(self.body),
            'sources': list(self.sources),
            'source_count': len(self.sources),
            'expected_source_count': self.expected_source_count,
            'citation_ids': citation_ids,
            'missing': missing,
            'missing_source_ids': missing,
            'capture_root': str(self.capture_root),
            'actions': list(self.actions),
        }

    def _execute(self, arguments: dict[str, object]) -> dict[str, object]:
        action, name, contains = self._normalized_action(arguments)
        if action == 'find':
            found = self.act.find(
                name,
                role='push button',
                display=self.display,
                contains=contains,
            )
            result = {
                'ok': bool(found),
                'action': action,
                'query': name,
                'contains': contains,
                'found': self._serializable_found(found),
            }
        elif action == 'click':
            source_match = SOURCE_CONTROL_PATTERN.fullmatch(name)
            if name != 'Copy' and source_match is None:
                raise TaeyConsultExtractionError(
                    'consult extraction click is restricted to exact "Copy" or '
                    'the exact "N sources" name returned by find'
                )
            if name == 'Copy' and not clipboard.write(''):
                raise TaeyConsultExtractionError(
                    'could not clear clipboard before the Copy action'
                )
            clicked = bool(
                self.act.click(
                    name,
                    role='push button',
                    display=self.display,
                    contains=False,
                )
            )
            if not clicked:
                raise TaeyConsultExtractionError(
                    f'act.click({name!r}) returned a non-success value'
                )
            result = {
                'ok': True,
                'action': action,
                'name': name,
            }
            if name == 'Copy':
                body = self._read_clipboard_until_nonempty()
                if not body:
                    raise TaeyConsultExtractionError(
                        'Copy action landed but the clipboard body stayed empty'
                    )
                self.body = body
                result.update(
                    capture='body',
                    body=body,
                    body_characters=len(body),
                    body_sha256=_sha256_text(body),
                )
            else:
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
        action_record = {
            'turn': len(self.actions) + 1,
            'arguments': dict(arguments),
            'ok': bool(result.get('ok')),
            'body_characters': len(self.body),
            'source_count': len(self.sources),
        }
        self.actions.append(action_record)
        self._append_turn_log({'event': 'action', **action_record})
        return result

    def run(self) -> dict[str, object]:
        task = (
            f'Extract the completed Perplexity Deep Research answer on consult display '
            f'{self.display}. Use consult_extract_action only. Execute this observed '
            'sequence one action per turn: find the exact response Copy push button; '
            'click the exact Copy name and read the returned clipboard body; find a '
            'push button whose accessible name contains " sources"; click the exact '
            'N sources name returned by find and read the returned complete source '
            'panel; then finish with name="" and contains=false. Never click '
            'Download, Copy contents, or coordinates. Do not finish until the tool '
            'reports a non-empty body, source_count equals expected_source_count, '
            'and missing=[].'
        )
        overlay = (
            '\n\nCONSULT EXTRACTION SEAT: The sole callable tool is '
            'consult_extract_action. It is the harness binding of canonical act.find '
            'and act.click; do not emit shell commands or prose. One tool call per '
            'turn. Accessible names, never coordinates.'
        )
        messages: list[dict[str, object]] = [
            {'role': 'system', 'content': self.system_prompt + overlay},
            {'role': 'user', 'content': task},
        ]
        for turn in range(1, MAX_TURNS + 1):
            message = self._message(self._call_taey(messages, turn))
            call_id, arguments = self._arguments(message)
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
            f'Taey consult extraction exhausted {MAX_TURNS} turns'
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
