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

    def validation_passes(self, snapshot: Snapshot, validation_key: str, filename: str | None = None, item_key: str | None = None) -> bool:
        validation = dict(self.cfg.get('validation', {}).get(validation_key, {}))
        if not validation and not filename:
            # If the validation key is missing, we assume it's NOT active
            return False

        indicators = validation.get('indicators') or []
        all_elements: List[ElementRef] = []
        for items in snapshot.mapped.values():
            all_elements.extend(items)
        all_elements.extend(snapshot.unknown)
        all_elements.extend(snapshot.sidebar)

        if indicators:
            found = False
            for indicator in indicators:
                if any(matches_spec(element, indicator) for element in all_elements):
                    found = True
                    break
            if not found:
                return False

        # State-based menu item check
        if validation.get('check_menu_item_state') and item_key:
            item = snapshot.first(item_key)
            if not item:
                # If item not in mapped, check menu_items directly
                for mi in snapshot.menu_items:
                    if mi.key == item_key:
                        item = mi
                        break
            if not item:
                return False
            states = {s.lower() for s in item.states}
            if not any(s in states for s in {'checked', 'selected', 'pressed'}):
                return False

        # Name-based model check
        if item_key and (validation.get('name_is_model') or validation.get('name_contains_model')):
            target_key = self.cfg.get('workflow', {}).get('selection', {}).get('model_targets', {}).get(item_key) or item_key
            target_spec = self.cfg.get('tree', {}).get('element_map', {}).get(target_key, {})
            
            target_text = ""
            if 'name' in target_spec:
                target_text = str(target_spec['name'])
            elif 'name_contains' in target_spec:
                from consultation_v2.snapshot import _listify
                target_text = str(_listify(target_spec['name_contains'])[0])
            elif 'name_pattern' in target_spec:
                from consultation_v2.snapshot import _listify
                target_text = str(_listify(target_spec['name_pattern'])[0]).replace('*', '')
            else:
                target_text = target_key

            # Find the element to read name from
            read_from = validation.get('read_from', 'model_selector')
            el = snapshot.first(read_from)
            if not el:
                return False
            
            name_lower = el.name.lower()
            target_lower = target_text.lower()
            if validation.get('name_is_model'):
                if target_lower not in name_lower:
                    return False
            else: # name_contains_model
                if target_lower not in name_lower:
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
