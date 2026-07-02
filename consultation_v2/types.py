from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class AttachmentProvenance:
    """Provenance of one caller-supplied attachment, captured BEFORE the file is
    merged into the consolidated identity package (FLOW §3 / §8).

    ``path`` is the original caller source path; ``sha256`` is the hex digest of
    that file's bytes at consolidation time. This survives consolidation so the
    durable run-state / storage layer can record what the caller actually sent
    even though the browser only ever receives the single merged package."""
    path: str
    sha256: str

    def serializable(self) -> Dict[str, Any]:
        return {'path': self.path, 'sha256': self.sha256}


@dataclass(slots=True)
class ConsolidatedPackage:
    """Result of identity+attachment consolidation (FLOW §3, §4).

    ``path`` is the primary package path (the only path for ordinary packages,
    or the first chunk for a split package). ``paths`` is the ordered list the
    browser is sent.
    ``caller_provenance`` is the per-caller-attachment path+hash list captured
    before the merge. consolidate_attachments either returns a complete one of
    these or raises loudly — it never returns a partial/None packet."""
    path: str
    paths: List[str] = field(default_factory=list)
    caller_provenance: List[AttachmentProvenance] = field(default_factory=list)

    def attachment_paths(self) -> List[str]:
        return list(self.paths or [self.path])


@dataclass(slots=True)
class Choice:
    value: Any
    because: str = ''

    def serializable(self) -> Dict[str, Any]:
        return {
            'value': self.value,
            'because': self.because,
        }


@dataclass(slots=True)
class ConsultationRequest:
    platform: str
    message: str
    attachments: List[str] = field(default_factory=list)
    selections: Dict[str, Choice] = field(default_factory=dict)
    session_url: Optional[str] = None
    timeout: int = 3600
    output_path: Optional[str] = None
    no_neo4j: bool = False
    store_enabled: bool = False
    no_identity: bool = False
    session_type: Optional[str] = None
    purpose: Optional[str] = None
    requester: Optional[str] = None
    # Provenance of caller attachments, captured before consolidation (FLOW §3).
    # The browser receives only the merged package, but this records the
    # original caller files + their content hashes so provenance survives.
    caller_attachment_provenance: List[AttachmentProvenance] = field(default_factory=list)

    def serializable_selections(self) -> Dict[str, Dict[str, Any]]:
        payload: Dict[str, Dict[str, Any]] = {}
        for menu_key, choice in self.selections.items():
            if isinstance(choice, Choice):
                payload[str(menu_key)] = choice.serializable()
            elif isinstance(choice, dict):
                payload[str(menu_key)] = {
                    'value': choice.get('value'),
                    'because': str(choice.get('because') or ''),
                }
            else:
                payload[str(menu_key)] = {
                    'value': choice,
                    'because': '',
                }
        return payload

    def selection_value(self, menu_key: str, default: Any = None) -> Any:
        choice = self.selections.get(menu_key)
        if isinstance(choice, Choice):
            return choice.value
        if isinstance(choice, dict):
            return choice.get('value', default)
        if choice is None:
            return default
        return choice

    def selection_list(self, menu_key: str) -> List[str]:
        value = self.selection_value(menu_key, [])
        if value in (None, 'none', 'default'):
            return []
        if isinstance(value, list):
            return [str(item) for item in value if isinstance(item, str) and item]
        if isinstance(value, str) and value:
            return [value]
        return []

    def prompt_hash(self) -> str:
        """Stable hex digest of the prompt text actually sent to the platform.

        This is the prompt-hash checkpoint field (FLOW §8): it lets a re-run
        confirm the run-state it found corresponds to THIS prompt, and a monitor
        confirm what was generated. It hashes ``message`` only (the prompt/lens),
        not the consolidated package path (which is a per-run timestamped temp
        file and is therefore unstable across re-runs)."""
        return hashlib.sha256(self.message.encode('utf-8')).hexdigest()

    def request_id(self) -> str:
        """Stable identity of THIS consultation for durable run-state keying
        (FLOW §8 / CONSULTATION_CONTRACT §10).

        The id MUST be identical across re-runs of the same consultation so a
        re-run maps to the same ``taey:{node}:run_state:{request_id}`` record and
        can detect a landed send instead of replaying it. It is derived from the
        invariant identity of the request: the platform, the session target
        (``session_url`` for a follow-up, or the literal ``'new'`` for a fresh
        chat), and the prompt hash. It deliberately does NOT include the
        consolidated-package path (unstable per run) or volatile metadata
        (timeout, purpose, requester) — those vary run-to-run without changing
        which irreversible turn this is."""
        session_target = self.session_url or 'new'
        seed = f'{self.platform}\x1f{session_target}\x1f{self.prompt_hash()}'
        if self.no_identity:
            provenance = self.caller_attachment_provenance or []
            if provenance:
                attachment_seed = '\x1e'.join(
                    f'{prov.path}\x1d{prov.sha256}' for prov in provenance
                )
            else:
                attachment_seed = '\x1e'.join(self.attachments)
            seed = f'{seed}\x1fno_identity\x1f{attachment_seed}'
        return hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]


@dataclass(slots=True)
class ElementRef:
    key: Optional[str]
    name: str
    role: str
    x: Optional[int]
    y: Optional[int]
    states: List[str] = field(default_factory=list)
    text: Optional[str] = None
    description: Optional[str] = None
    atspi_obj: Any = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def serializable(self) -> Dict[str, Any]:
        payload = {
            'key': self.key,
            'name': self.name,
            'role': self.role,
            'x': self.x,
            'y': self.y,
            'states': list(self.states),
        }
        if self.text:
            payload['text'] = self.text
        if self.description:
            payload['description'] = self.description
        return payload


class SnapshotDriftError(ValueError):
    def __init__(self, key: str, items: List[ElementRef], selector: str) -> None:
        count = len(items)
        examples = '; '.join(self._describe(item) for item in items[:3])
        if count > 3:
            examples = f'{examples}; ...'
        super().__init__(
            f"snapshot key {key!r} matched {count} elements; Snapshot.{selector}() "
            f"refuses silent selection. Disambiguate the YAML with a structural "
            f"index/ordinal or split the element_map key. Matches: {examples}"
        )
        self.key = key
        self.count = count
        self.selector = selector
        self.matches = list(items)

    @staticmethod
    def _describe(item: ElementRef) -> str:
        return (
            f"name={item.name!r} role={item.role!r} "
            f"x={item.x!r} y={item.y!r} states={list(item.states)!r}"
        )


@dataclass(slots=True)
class Snapshot:
    platform: str
    url: Optional[str]
    mapped: Dict[str, List[ElementRef]] = field(default_factory=dict)
    unknown: List[ElementRef] = field(default_factory=list)
    sidebar: List[ElementRef] = field(default_factory=list)
    raw_count: int = 0
    menu_items: List[ElementRef] = field(default_factory=list)

    def first(self, key: str) -> Optional[ElementRef]:
        items = self.mapped.get(key) or []
        if len(items) > 1:
            raise SnapshotDriftError(key, items, 'first')
        return items[0] if items else None

    def last(self, key: str) -> Optional[ElementRef]:
        items = self.mapped.get(key) or []
        if not items:
            return None
        if len(items) > 1:
            raise SnapshotDriftError(key, items, 'last')
        return sorted(items, key=lambda item: (item.y or 0, item.x or 0))[-1]

    def has(self, key: str) -> bool:
        return bool(self.mapped.get(key))

    def serializable(self) -> Dict[str, Any]:
        return {
            'platform': self.platform,
            'url': self.url,
            'mapped': {k: [item.serializable() for item in v] for k, v in self.mapped.items() if v},
            'unknown': [item.serializable() for item in self.unknown],
            'sidebar': [item.serializable() for item in self.sidebar],
            'raw_count': self.raw_count,
            'menu_items': [item.serializable() for item in self.menu_items],
        }


@dataclass(slots=True)
class ExtractedArtifact:
    name: str
    content: str
    kind: str = 'attachment_output'
    metadata: Dict[str, Any] = field(default_factory=dict)

    def serializable(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'kind': self.kind,
            'content': self.content,
            'metadata': dict(self.metadata),
        }


@dataclass(slots=True)
class StepRecord:
    step: str
    success: bool
    message: str = ''
    evidence: Dict[str, Any] = field(default_factory=dict)

    def serializable(self) -> Dict[str, Any]:
        return {
            'step': self.step,
            'success': self.success,
            'message': self.message,
            'evidence': self.evidence,
        }


@dataclass(slots=True)
class ConsultationResult:
    platform: str
    request: ConsultationRequest
    steps: List[StepRecord] = field(default_factory=list)
    session_url_before: Optional[str] = None
    session_url_after: Optional[str] = None
    response_text: str = ''
    extractions: List[ExtractedArtifact] = field(default_factory=list)
    storage: Dict[str, Any] = field(default_factory=dict)
    ok: bool = False

    def add_step(self, step: str, success: bool, message: str = '', **evidence: Any) -> StepRecord:
        record = StepRecord(step=step, success=success, message=message, evidence=evidence)
        self.steps.append(record)
        return record

    def serializable(self) -> Dict[str, Any]:
        return {
            'platform': self.platform,
            'request': {
                'platform': self.request.platform,
                'message': self.request.message,
                'attachments': list(self.request.attachments),
                'selections': self.request.serializable_selections(),
                'session_url': self.request.session_url,
                'timeout': self.request.timeout,
                'no_neo4j': self.request.no_neo4j,
                'store_enabled': self.request.store_enabled,
                'no_identity': self.request.no_identity,
                'session_type': self.request.session_type,
                'purpose': self.request.purpose,
            },
            'steps': [step.serializable() for step in self.steps],
            'session_url_before': self.session_url_before,
            'session_url_after': self.session_url_after,
            'response_text': self.response_text,
            'extractions': [artifact.serializable() for artifact in self.extractions],
            'storage': dict(self.storage),
            'ok': self.ok,
        }
