from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
import time
from typing import Any, Iterable, Mapping

from consultation_v2.supervised_ui_contract import (
    build_live_ui_action_schema,
    canonical_json_bytes,
)

from .provider_contract import ProviderSpec, load_provider_spec
from .route_contract import RouteContractError, RouteMatch, match_provider_route


PROJECTION_SCHEMA = 'ats_read_only_projection_v1'
RESULT_SCHEMA = 'ats_read_only_qualification_result_v1'
TRANSITION_SCHEMA = 'ats_compiled_transition_v1'

_PUBLIC_STATES = frozenset({
    'editable',
    'enabled',
    'focusable',
    'required',
    'showing',
    'visible',
})


class AtsReadOnlyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def valid(self) -> bool:
        return self.x >= 0 and self.y >= 0 and self.width > 0 and self.height > 0

    def contains(self, other: 'Rect') -> bool:
        return (
            self.valid
            and other.valid
            and other.x >= self.x
            and other.y >= self.y
            and other.x + other.width <= self.x + self.width
            and other.y + other.height <= self.y + self.height
        )


def compile_read_only_transition(spec: ProviderSpec) -> dict[str, Any]:
    transition = dict(spec.document['transitions']['read_only_form_projection'])
    tool = build_live_ui_action_schema('needs_observe')
    function = tool.get('function') if isinstance(tool, dict) else None
    if not isinstance(function, dict) or function.get('name') != transition['grammar']:
        raise AtsReadOnlyError('ATS transition is not bound to the existing ui_action grammar')
    parameters = function.get('parameters')
    expected_parameters = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {'op': {'type': 'string', 'const': 'observe'}},
        'required': ['op'],
    }
    if parameters != expected_parameters or transition['call'] != {'op': 'observe'}:
        raise AtsReadOnlyError('existing ui_action observe contract changed')
    return {
        'schema': TRANSITION_SCHEMA,
        'grammar': 'ui_action',
        'operation': 'observe',
        'call': {'op': 'observe'},
        'effect_class': 'read_only',
        'traversal_primitive': transition['traversal_primitive'],
        'match_primitive': transition['match_primitive'],
        'next': 'terminal',
    }


def _live_states(element: Mapping[str, Any]) -> set[str]:
    states = {
        str(state).strip().lower().replace('_', ' ')
        for state in element.get('states', [])
        if isinstance(state, str)
    }
    obj = element.get('atspi_obj')
    if obj is None:
        return states
    from consultation_v2.tree import Atspi

    live_state_types = {
        'editable': Atspi.StateType.EDITABLE,
        'enabled': Atspi.StateType.ENABLED,
        'focusable': Atspi.StateType.FOCUSABLE,
        'required': Atspi.StateType.REQUIRED,
        'showing': Atspi.StateType.SHOWING,
        'visible': Atspi.StateType.VISIBLE,
    }
    try:
        state_set = obj.get_state_set()
    except Exception as exc:
        raise AtsReadOnlyError('cannot read ATS control state set') from exc
    for name, state_type in live_state_types.items():
        try:
            if state_set.contains(state_type):
                states.add(name)
        except Exception as exc:
            raise AtsReadOnlyError(f'cannot read ATS control state {name!r}') from exc
    return states


def _rect_from_mapping(value: Any) -> Rect | None:
    if not isinstance(value, Mapping):
        return None
    if set(value) != {'x', 'y', 'width', 'height'}:
        return None
    if any(isinstance(value[key], bool) or not isinstance(value[key], int) for key in value):
        return None
    return Rect(value['x'], value['y'], value['width'], value['height'])


def _element_rect(element: Mapping[str, Any]) -> Rect | None:
    declared = _rect_from_mapping(element.get('extent'))
    if declared is not None:
        return declared
    obj = element.get('atspi_obj')
    if obj is None:
        return None
    from consultation_v2.tree import Atspi

    try:
        component = obj.get_component_iface()
        if component is None:
            return None
        rect = component.get_extents(Atspi.CoordType.SCREEN)
    except Exception as exc:
        raise AtsReadOnlyError('cannot read ATS control extent') from exc
    if rect is None:
        return None
    return Rect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))


def _document_rect(document: Any) -> Rect:
    from consultation_v2.tree import Atspi

    try:
        component = document.get_component_iface()
        if component is None:
            raise AtsReadOnlyError('active ATS document has no component interface')
        rect = component.get_extents(Atspi.CoordType.SCREEN)
    except AtsReadOnlyError:
        raise
    except Exception as exc:
        raise AtsReadOnlyError('cannot read active ATS document extent') from exc
    result = Rect(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    if not result.valid:
        raise AtsReadOnlyError('active ATS document extent is invalid')
    return result


def _selector_matches(element: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    from consultation_v2.snapshot import matches_spec

    states = sorted(_live_states(element))
    candidate = dict(element)
    candidate['states'] = states
    for role in selector['roles_any_of']:
        if matches_spec(candidate, {
            'names_any_of': selector['names_any_of'],
            'role': role,
            'states_include': selector['states_all'],
        }):
            return True
    return False


def _opaque_ref(
    secret: bytes,
    spec: ProviderSpec,
    route: RouteMatch,
    element: Mapping[str, Any],
    ordinal: int,
) -> str:
    identity = canonical_json_bytes({
        'provider': spec.provider,
        'application_identity_sha256': route.application_identity_sha256,
        'name': str(element.get('name') or ''),
        'role': str(element.get('role') or ''),
        'ordinal': ordinal,
    })
    digest = hmac.new(secret, b'ats-read-only-ref-v1\x00' + identity, hashlib.sha256).hexdigest()
    return f'r_{digest[:32]}'


def _combo_projection(element: Mapping[str, Any], document_rect: Rect) -> dict[str, Any]:
    rect = _element_rect(element)
    if rect is None or not rect.valid:
        return {
            'geometry': 'refused',
            'refusal': 'combo_rect_invalid',
            'scroll_frontier': True,
            'activation_authority': 'none',
        }
    if not document_rect.contains(rect):
        return {
            'geometry': 'refused',
            'refusal': 'combo_rect_outside_document_rect',
            'scroll_frontier': True,
            'activation_authority': 'none',
        }
    return {
        'geometry': 'contained_by_active_document',
        'refusal': None,
        'scroll_frontier': False,
        'activation_authority': 'none',
    }


def project_required_fields(
    spec: ProviderSpec,
    route: RouteMatch,
    required_elements: Iterable[Mapping[str, Any]],
    document_rect: Rect,
    lease_secret: bytes,
) -> list[dict[str, Any]]:
    elements = [dict(element) for element in required_elements]
    elements.sort(key=lambda element: (
        int(element.get('y') or 0),
        int(element.get('x') or 0),
        str(element.get('role') or ''),
        str(element.get('name') or ''),
    ))
    public_fields: list[dict[str, Any]] = []
    for ordinal, element in enumerate(elements):
        role = str(element.get('role') or '').strip().lower()
        field: dict[str, Any] = {
            'ref': _opaque_ref(lease_secret, spec, route, element, ordinal),
            'role': role,
            'states': sorted(_live_states(element) & _PUBLIC_STATES),
            'operations': [],
        }
        if role == 'combo box':
            field['combo_safety'] = _combo_projection(element, document_rect)
        public_fields.append(field)
    return public_fields


def project_read_only_form(
    spec: ProviderSpec,
    *,
    url: str,
    elements: Iterable[Mapping[str, Any]],
    document_rect: Rect,
    lease_secret: bytes,
) -> dict[str, Any]:
    if not spec.executable or spec.provider != 'greenhouse':
        raise AtsReadOnlyError('provider is not enabled for read-only qualification')
    if not isinstance(lease_secret, bytes) or len(lease_secret) < 32:
        raise AtsReadOnlyError('ATS read-only lease secret must be at least 32 bytes')
    route = match_provider_route(spec, url)
    element_list = [dict(element) for element in elements]
    form = spec.document['form_projection']
    anchor_ids: list[str] = []
    for selector in form['anchors_all']:
        matches = [element for element in element_list if _selector_matches(element, selector)]
        if len(matches) != 1:
            raise AtsReadOnlyError(
                f'ATS form anchor {selector["id"]!r} matched {len(matches)} elements'
            )
        anchor_ids.append(selector['id'])
    required = form['required_controls']
    required_roles = set(required['roles_any_of'])
    required_states = set(required['states_all'])
    required_elements = [
        element
        for element in element_list
        if str(element.get('role') or '').strip().lower() in required_roles
        and required_states.issubset(_live_states(element))
    ]
    if not required_elements:
        raise AtsReadOnlyError('ATS form exposes no exact required-field projection')
    public_fields = project_required_fields(
        spec,
        route,
        required_elements,
        document_rect,
        lease_secret,
    )
    transition = compile_read_only_transition(spec)
    projection = {
        'schema': PROJECTION_SCHEMA,
        'provider': spec.provider,
        'provider_sha256': spec.sha256,
        'route': {
            'grammar_id': route.grammar_id,
            'application_identity_sha256': route.application_identity_sha256,
        },
        'form': {
            'anchor_ids': sorted(anchor_ids),
            'required_field_count': len(public_fields),
            'required_fields': public_fields,
        },
        'authorities': {'fill': False, 'upload': False, 'submit': False},
        'transition': transition,
    }
    projection['projection_sha256'] = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    return projection


def _pid_from_environment() -> int | None:
    raw = str(os.environ.get('ATS_FIREFOX_PID') or '').strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise AtsReadOnlyError('ATS_FIREFOX_PID must be a positive integer when set')
    return int(raw)


def _find_exact_document(spec: ProviderSpec) -> tuple[Any, Any, str]:
    from consultation_v2 import atspi

    firefox_candidates = atspi.find_all_firefox(pid=_pid_from_environment())
    matches: list[tuple[Any, Any, str]] = []
    for firefox in firefox_candidates:
        for document in atspi.document_web_elements(firefox):
            url = atspi.get_document_url(document)
            if not url:
                continue
            try:
                match_provider_route(spec, url)
            except RouteContractError:
                continue
            matches.append((firefox, document, url))
    if len(matches) != 1:
        raise AtsReadOnlyError(f'exact ATS route matched {len(matches)} active documents')
    return matches[0]


def _invalidate_and_reacquire(spec: ProviderSpec) -> tuple[Any, Any, str, dict[str, str]]:
    from consultation_v2.tree import Atspi

    try:
        desktop = Atspi.get_desktop(0)
        desktop.clear_cache_single()
    except Exception as exc:
        raise AtsReadOnlyError('ATS desktop cache invalidation failed') from exc
    firefox, document, _url = _find_exact_document(spec)
    try:
        firefox.clear_cache_single()
    except Exception as exc:
        raise AtsReadOnlyError('ATS Firefox cache invalidation failed') from exc
    try:
        document.clear_cache_single()
    except Exception as exc:
        raise AtsReadOnlyError('ATS document cache invalidation failed') from exc
    firefox, document, url = _find_exact_document(spec)
    return firefox, document, url, {
        'desktop': 'success',
        'firefox': 'success',
        'document': 'success',
        'reacquire': 'success',
    }


def observe_read_only_form(provider: str, lease_secret: bytes) -> dict[str, Any]:
    from consultation_v2.tree import find_elements

    spec = load_provider_spec(provider)
    if not spec.executable:
        raise AtsReadOnlyError(f'{provider} is mapping-only and cannot execute')
    if not os.environ.get('DISPLAY') or not os.environ.get('AT_SPI_BUS_ADDRESS'):
        raise AtsReadOnlyError('DISPLAY and AT_SPI_BUS_ADDRESS must be explicitly bound')
    barrier = spec.document['form_projection']['observation_barrier']
    started = time.monotonic()
    samples: list[dict[str, Any]] = []
    last_digest: str | None = None
    stable_cycles = 0
    while (time.monotonic() - started) * 1000 <= barrier['timeout_ms']:
        _firefox, document, url, refresh = _invalidate_and_reacquire(spec)
        elements = find_elements(document, max_depth=spec.document['form_projection']['max_depth'])
        projection = project_read_only_form(
            spec,
            url=url,
            elements=elements,
            document_rect=_document_rect(document),
            lease_secret=lease_secret,
        )
        digest = projection['projection_sha256']
        samples.append({
            'sample': len(samples) + 1,
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'projection_sha256': digest,
            'refresh': refresh,
        })
        stable_cycles = stable_cycles + 1 if digest == last_digest else 1
        last_digest = digest
        if stable_cycles >= barrier['stable_cycles']:
            result = {
                'schema': RESULT_SCHEMA,
                'ok': True,
                'provider': provider,
                'state': 'terminal_read_only_pass',
                'samples': samples,
                'projection': projection,
                'next_mutation_authorized': False,
            }
            result['receipt_sha256'] = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
            return result
        time.sleep(barrier['interval_ms'] / 1000)
    raise AtsReadOnlyError('ATS read-only observation barrier timed out without a stable projection')
