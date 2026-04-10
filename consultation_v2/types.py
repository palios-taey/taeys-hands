from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class ConsultationRequest:
    platform: str
    message: str
    attachments: List[str] = field(default_factory=list)
    model: Optional[str] = None
    mode: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    connectors: List[str] = field(default_factory=list)
    session_url: Optional[str] = None
    timeout: int = 3600
    output_path: Optional[str] = None
    no_neo4j: bool = False
    session_type: Optional[str] = None
    purpose: Optional[str] = None
    requester: Optional[str] = None


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
        return items[0] if items else None

    def last(self, key: str) -> Optional[ElementRef]:
        items = self.mapped.get(key) or []
        if not items:
            return None
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
                'model': self.request.model,
                'mode': self.request.mode,
                'tools': list(self.request.tools),
                'connectors': list(self.request.connectors),
                'session_url': self.request.session_url,
                'timeout': self.request.timeout,
                'no_neo4j': self.request.no_neo4j,
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
