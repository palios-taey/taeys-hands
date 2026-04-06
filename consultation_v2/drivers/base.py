from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Iterable, List, Optional

from consultation_v2.runtime import ConsultationRuntime
from consultation_v2.snapshot import matches_spec
from consultation_v2.types import ConsultationRequest, ConsultationResult, ElementRef, ExtractedArtifact, Snapshot
from consultation_v2.yaml_contract import load_platform_yaml


class BaseConsultationDriver(ABC):
    platform: str

    def __init__(self) -> None:
        self.cfg = load_platform_yaml(self.platform)
        self.runtime = ConsultationRuntime(self.platform)

    def result(self, request: ConsultationRequest) -> ConsultationResult:
        return ConsultationResult(platform=self.platform, request=request)

    def find_first(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.first(key)

    def find_last(self, snapshot: Snapshot, key: str) -> Optional[ElementRef]:
        return snapshot.last(key)

    def validation_passes(self, snapshot: Snapshot, validation_key: str, filename: str | None = None) -> bool:
        validation = dict(self.cfg.get('validation', {}).get(validation_key, {}))
        indicators = validation.get('indicators') or []
        if indicators:
            found = False
            all_elements: List[ElementRef] = []
            for items in snapshot.mapped.values():
                all_elements.extend(items)
            all_elements.extend(snapshot.unknown)
            for indicator in indicators:
                if any(matches_spec(element, indicator) for element in all_elements):
                    found = True
                    break
            if not found:
                return False
        file_chip = dict(validation.get('file_chip', {}))
        if filename and file_chip:
            probes = []
            base = filename.split('/')[-1]
            probes.append(base.lower())
            stem = base.rsplit('.', 1)[0].lower() if '.' in base else base.lower()
            probes.append(stem)
            all_elements: List[ElementRef] = []
            for items in snapshot.mapped.values():
                all_elements.extend(items)
            all_elements.extend(snapshot.unknown)
            role_set = {str(role).lower() for role in file_chip.get('roles', [])}
            matched_chip = False
            for element in all_elements:
                if role_set and element.role.lower() not in role_set:
                    continue
                name = element.name.lower()
                if any(probe and probe in name for probe in probes):
                    matched_chip = True
                    break
            if not matched_chip:
                return False
        if validation.get('stop_absent'):
            stop_key = self.cfg.get('workflow', {}).get('monitor', {}).get('stop_key') or 'stop_button'
            if snapshot.has(stop_key):
                return False
        return True

    def serialize_artifacts(self, artifacts: Iterable[ExtractedArtifact]) -> List[str]:
        return [json.dumps(artifact.serializable(), sort_keys=True) for artifact in artifacts]

    @abstractmethod
    def run(self, request: ConsultationRequest) -> ConsultationResult:
        raise NotImplementedError
