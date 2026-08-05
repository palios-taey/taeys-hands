from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
from typing import Any, Mapping
import uuid

from .interact import atspi_activate, atspi_focus
from .snapshot import build_snapshot
from .supervised_ui_contract import (
    CONTRACT_VERSION,
    ProjectedSnapshot,
    SupervisedUiContractError,
    build_live_ui_action_schema,
    canonical_json_bytes,
    load_supervised_policy,
    project_snapshot,
    snapshot_revision,
    validate_approved_call,
)
from .supervised_ui_receipts import HandsReceiptStore, ReceiptStoreError


_TERMINAL_STATES = frozenset({
    'cancelled',
    'failed',
    'indeterminate',
    'rejected',
    'replayed',
    'stale',
})


class SupervisedUiSeatError(RuntimeError):
    def __init__(self, refusal_class: str) -> None:
        super().__init__(refusal_class)
        self.refusal_class = refusal_class


def _parse_expiry(value: Any, context: str) -> datetime:
    if not isinstance(value, str):
        raise SupervisedUiSeatError(f'{context}_invalid')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise SupervisedUiSeatError(f'{context}_invalid') from exc
    if parsed.tzinfo is None:
        raise SupervisedUiSeatError(f'{context}_invalid')
    return parsed.astimezone(timezone.utc)


class SupervisedUiSeat:
    def __init__(
        self,
        *,
        platform: str,
        lease_secret: bytes,
        lease_expires_at: str,
        presence_incarnation_id: str,
        hands_incarnation_id: str,
        hands_commit: str,
        receipt_store: HandsReceiptStore,
    ) -> None:
        if not isinstance(lease_secret, bytes) or len(lease_secret) < 32:
            raise SupervisedUiSeatError('lease_secret_invalid')
        load_supervised_policy(platform)
        self.platform = platform
        self._lease_secret = lease_secret
        self._lease_expires_at = _parse_expiry(lease_expires_at, 'lease_expiry')
        self.presence_incarnation_id = presence_incarnation_id
        self.hands_incarnation_id = hands_incarnation_id
        self.hands_commit = hands_commit
        self.receipts = receipt_store
        if self.receipts.hands_incarnation_id != hands_incarnation_id:
            raise SupervisedUiSeatError('receipt_incarnation_mismatch')
        if self.receipts.presence_incarnation_id != presence_incarnation_id:
            raise SupervisedUiSeatError('receipt_presence_incarnation_mismatch')
        self.receipts.recover_incarnation()
        self.state = 'needs_observe'
        self._projection: ProjectedSnapshot | None = None
        self._revision: str | None = None
        self._observation_id: str | None = None
        self._pending_verification: dict[str, Any] | None = None
        self._last_approval: Mapping[str, Any] | None = None
        self._closed = False
        self._handshake_recorded = False
        self._record(
            'worker_started',
            {
                'contract_version': CONTRACT_VERSION,
                'hands_commit': hands_commit,
                'hands_incarnation_id': hands_incarnation_id,
                'presence_incarnation_id': presence_incarnation_id,
            },
        )

    def _record(
        self,
        kind: str,
        payload: Mapping[str, Any],
        *,
        approval: Mapping[str, Any] | None = None,
        observation_id: str | None = None,
    ) -> Mapping[str, Any]:
        approval = dict(approval or {})
        return self.receipts.write_once({
            'approval_id': approval.get('approval_id'),
            'event_id': str(uuid.uuid4()),
            'execution_id': approval.get('execution_id'),
            'kind': kind,
            'observation_id': (
                observation_id
                if observation_id is not None
                else approval.get('observation_id')
            ),
            'proposal_id': approval.get('proposal_id'),
            'turn_id': approval.get('turn_id'),
        }, canonical_json_bytes(payload))

    def _assert_open(self) -> None:
        if self._closed:
            raise SupervisedUiSeatError('worker_closed')
        if self.state in _TERMINAL_STATES:
            raise SupervisedUiSeatError(f'session_terminal_{self.state}')

    def _assert_lease_live(self) -> None:
        if datetime.now(timezone.utc) >= self._lease_expires_at:
            self.state = 'failed'
            raise SupervisedUiSeatError('lease_expired')

    def _schema(self) -> Mapping[str, Any] | None:
        if self.state in _TERMINAL_STATES:
            return None
        try:
            return build_live_ui_action_schema(
                self.state,
                self._projection,
                self._revision,
            )
        except SupervisedUiContractError:
            return None

    def handshake(self) -> Mapping[str, Any]:
        if self._handshake_recorded:
            raise SupervisedUiSeatError('handshake_already_recorded')
        result = {
            'contract_version': CONTRACT_VERSION,
            'hands_commit': self.hands_commit,
            'hands_incarnation_id': self.hands_incarnation_id,
            'state': self.state,
            'tool': self._schema(),
        }
        self._record('worker_handshake', result)
        self._handshake_recorded = True
        return result

    def _capture_projection(self) -> tuple[ProjectedSnapshot, str]:
        _firefox, _document, snapshot = build_snapshot(self.platform)
        projected = project_snapshot(snapshot, self._lease_secret)
        revision = snapshot_revision(projected, self._lease_secret)
        return projected, revision

    def _validate_authority(
        self,
        proposal_bytes: bytes,
        approval: Mapping[str, Any],
        capability_secret: bytes,
    ) -> dict[str, Any]:
        self._assert_open()
        self._assert_lease_live()
        if not isinstance(capability_secret, bytes) or len(capability_secret) < 32:
            raise SupervisedUiSeatError('capability_invalid')
        try:
            proposal = validate_approved_call(
                proposal_bytes,
                approval,
                self._projection,
            )
        except SupervisedUiContractError as exc:
            raise SupervisedUiSeatError('proposal_approval_mismatch') from exc
        if approval['hands_incarnation_id'] != self.hands_incarnation_id:
            raise SupervisedUiSeatError('hands_incarnation_mismatch')
        if approval['presence_incarnation_id'] != self.presence_incarnation_id:
            raise SupervisedUiSeatError('presence_incarnation_mismatch')
        approval_expiry = _parse_expiry(approval['expires_at'], 'approval_expiry')
        if approval_expiry > self._lease_expires_at:
            raise SupervisedUiSeatError('approval_exceeds_lease')
        if approval_expiry <= datetime.now(timezone.utc):
            raise SupervisedUiSeatError('approval_expired')
        capability_digest = hashlib.sha256(capability_secret).hexdigest()
        if not hmac.compare_digest(capability_digest, approval['capability_sha256']):
            raise SupervisedUiSeatError('capability_digest_mismatch')
        if self.receipts.has_approval_spend(approval['approval_id']):
            self.state = 'replayed'
            raise SupervisedUiSeatError('approval_replayed')
        if self.receipts.has_execution(approval['execution_id']):
            self.state = 'replayed'
            raise SupervisedUiSeatError('execution_replayed')
        operation = proposal['op']
        allowed_by_state = {
            'needs_observe': frozenset({'observe'}),
            'needs_verify': frozenset({'verify'}),
            'action_ready': frozenset({'activate', 'focus'}),
        }.get(self.state, frozenset())
        if operation not in allowed_by_state:
            raise SupervisedUiSeatError('operation_invalid_for_state')
        if operation in {'activate', 'focus'}:
            if approval['revision'] != self._revision:
                raise SupervisedUiSeatError('approval_revision_mismatch')
            if approval['observation_id'] != self._observation_id:
                raise SupervisedUiSeatError('approval_observation_mismatch')
        return proposal

    def _record_projection_omissions(
        self,
        projected: ProjectedSnapshot,
        approval: Mapping[str, Any],
        observation_id: str,
    ) -> None:
        for omission in projected.omissions:
            self._record(
                'projection_omission',
                omission,
                approval=approval,
                observation_id=observation_id,
            )

    def _spend_and_start(
        self,
        proposal_bytes: bytes,
        approval: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        spend_payload = {
            'actor_id': approval['actor_id'],
            'approval_id': approval['approval_id'],
            'capability_sha256': approval['capability_sha256'],
            'effect_class': approval['effect_class'],
            'operation': approval['operation'],
            'presence_incarnation_id': approval['presence_incarnation_id'],
            'proposal_sha256': hashlib.sha256(proposal_bytes).hexdigest(),
            'ref': approval['ref'],
            'revision': approval['revision'],
        }
        spent = self._record('approval_spent', spend_payload, approval=approval)
        started = self._record(
            'execution_started',
            {
                'approval_event_hash': spent['event_hash'],
                'execution_id': approval['execution_id'],
                'operation': approval['operation'],
            },
            approval=approval,
        )
        return spent, started

    def _fail_after_start(
        self,
        approval: Mapping[str, Any],
        refusal_class: str,
    ) -> None:
        self.state = 'indeterminate'
        try:
            self._record(
                'indeterminate',
                {'reason': refusal_class},
                approval=approval,
            )
        except Exception:
            pass

    def _observe_after_start(
        self,
        operation: str,
        approval: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        observation_id = str(uuid.uuid4())
        projected, revision = self._capture_projection()
        self._record_projection_omissions(projected, approval, observation_id)
        outcome = self._record(
            'execution_outcome',
            {
                'operation': operation,
                'success': True,
            },
            approval=approval,
            observation_id=observation_id,
        )
        observation_payload = {
            **projected.public,
            'observation_id': observation_id,
            'revision': revision,
        }
        observation_kind = (
            'post_action_observation_exact'
            if operation == 'verify'
            else 'observation_exact'
        )
        observation_event = self._record(
            observation_kind,
            observation_payload,
            approval=approval,
            observation_id=observation_id,
        )
        verification: Mapping[str, Any] | None = None
        if operation == 'verify':
            verification = self._verify_postcondition(projected, revision, approval)
            self._record(
                'verification_verdict',
                verification,
                approval=approval,
                observation_id=observation_id,
            )
        self._projection = projected
        self._revision = revision
        self._observation_id = observation_id
        if verification is not None and not verification['passed']:
            self.state = 'failed'
        elif projected.public['elements']:
            self.state = 'action_ready'
        else:
            self.state = 'failed'
        result: dict[str, Any] = {
            'execution_event_hash': outcome['event_hash'],
            'next_required': self.state,
            'observation': observation_payload,
            'observation_event_hash': observation_event['event_hash'],
            'state': self.state,
            'tool': self._schema(),
        }
        if verification is not None:
            result['verification'] = verification
        self._record(
            'tool_result_exact',
            result,
            approval=approval,
            observation_id=observation_id,
        )
        return result

    def _verify_postcondition(
        self,
        projected: ProjectedSnapshot,
        after_revision: str,
        approval: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        pending = self._pending_verification
        if pending is None:
            raise SupervisedUiSeatError('verification_without_action')
        ref = pending['ref']
        element = next(
            (item for item in projected.public['elements'] if item['ref'] == ref),
            None,
        )
        policy = load_supervised_policy(self.platform)
        control = next(
            (
                item for item in policy.controls.values()
                if item.control_id == pending['control_id']
            ),
            None,
        )
        if control is None:
            raise SupervisedUiSeatError('verification_policy_missing')
        postcondition = control.postconditions[pending['operation']]
        observed_states = set(element['states']) if element is not None else set()
        required_states = set(postcondition['states_include'])
        forbidden_states = set(postcondition['states_exclude'])
        passed = (
            element is not None
            and required_states.issubset(observed_states)
            and forbidden_states.isdisjoint(observed_states)
        )
        result = {
            'action_execution_event_hash': pending['execution_event_hash'],
            'after_revision': after_revision,
            'before_revision': pending['before_revision'],
            'forbidden_states': sorted(forbidden_states),
            'observed_states': sorted(observed_states),
            'operation': pending['operation'],
            'passed': passed,
            'ref': ref,
            'required_states': sorted(required_states),
            'verification_execution_id': approval['execution_id'],
        }
        self._pending_verification = None
        return result

    def _execute_action_after_start(
        self,
        proposal: Mapping[str, Any],
        approval: Mapping[str, Any],
        projected: ProjectedSnapshot,
    ) -> Mapping[str, Any]:
        ref = proposal['ref']
        element = projected.bindings[ref]
        if proposal['op'] == 'focus':
            success = atspi_focus(element.raw)
        elif proposal['op'] == 'activate':
            success = atspi_activate(element.raw)
        else:
            raise SupervisedUiSeatError('action_operation_invalid')
        outcome = self._record(
            'execution_outcome',
            {
                'operation': proposal['op'],
                'success': bool(success),
            },
            approval=approval,
        )
        if not success:
            self.state = 'failed'
            result = {
                'execution_event_hash': outcome['event_hash'],
                'next_required': 'failed',
                'operation': proposal['op'],
                'primitive_success': False,
                'ref': ref,
                'revision': proposal['revision'],
                'state': self.state,
            }
            self._record('action_result_exact', result, approval=approval)
            return result
        public_element = next(item for item in projected.public['elements'] if item['ref'] == ref)
        self._pending_verification = {
            'before_revision': proposal['revision'],
            'control_id': public_element['control_id'],
            'execution_event_hash': outcome['event_hash'],
            'operation': proposal['op'],
            'ref': ref,
        }
        self.state = 'needs_verify'
        result = {
            'execution_event_hash': outcome['event_hash'],
            'next_required': 'needs_verify',
            'operation': proposal['op'],
            'primitive_success': True,
            'ref': ref,
            'revision': proposal['revision'],
            'state': self.state,
            'tool': self._schema(),
        }
        self._record('action_result_exact', result, approval=approval)
        self._record(
            'state_needs_verify',
            {
                'action_execution_event_hash': outcome['event_hash'],
                'input_revision': proposal['revision'],
            },
            approval=approval,
        )
        return result

    def execute_approved(
        self,
        proposal_bytes: bytes,
        approval: Mapping[str, Any],
        capability_secret: bytes,
    ) -> Mapping[str, Any]:
        try:
            proposal = self._validate_authority(proposal_bytes, approval, capability_secret)
        except SupervisedUiSeatError:
            if self.state not in _TERMINAL_STATES:
                self.state = 'rejected'
            raise
        self._last_approval = dict(approval)
        operation = proposal['op']
        fresh_projection: ProjectedSnapshot | None = None
        if operation in {'activate', 'focus'}:
            try:
                fresh_projection, fresh_revision = self._capture_projection()
            except Exception as exc:
                self.state = 'failed'
                raise SupervisedUiSeatError('stale_check_failed') from exc
            stale_observation_id = str(uuid.uuid4())
            self._record(
                'stale_check_observation_exact',
                {
                    **fresh_projection.public,
                    'observation_id': stale_observation_id,
                    'revision': fresh_revision,
                },
                approval=approval,
                observation_id=stale_observation_id,
            )
            if fresh_revision != proposal['revision'] or proposal['ref'] not in fresh_projection.bindings:
                self.state = 'stale'
                self._record(
                    'stale',
                    {
                        'actual_revision': fresh_revision,
                        'expected_revision': proposal['revision'],
                        'ref_present': proposal['ref'] in fresh_projection.bindings,
                    },
                    approval=approval,
                    observation_id=stale_observation_id,
                )
                raise SupervisedUiSeatError('stale_projection')
        try:
            self._spend_and_start(proposal_bytes, approval)
        except Exception:
            if self.receipts.has_approval_spend(approval['approval_id']):
                self._fail_after_start(approval, 'execution_start_not_durable')
            else:
                self.state = 'failed'
            raise
        try:
            if operation in {'observe', 'verify'}:
                return self._observe_after_start(operation, approval)
            assert fresh_projection is not None
            return self._execute_action_after_start(proposal, approval, fresh_projection)
        except (SupervisedUiSeatError, ReceiptStoreError):
            self._fail_after_start(approval, 'execution_incomplete')
            raise
        except BaseException:
            self._fail_after_start(approval, 'worker_interrupted_after_start')
            raise

    def cancel(self) -> Mapping[str, Any]:
        self._assert_open()
        self.state = 'cancelled'
        receipt = self._record('cancelled', {'reason': 'supervisor_cancelled'})
        return {'event_hash': receipt['event_hash'], 'state': self.state}

    def reject_protocol(self, refusal_class: str) -> Mapping[str, Any]:
        self._assert_open()
        self.state = 'rejected'
        receipt = self._record(
            'proposal_rejected',
            {'refusal_class': refusal_class},
        )
        return {'event_hash': receipt['event_hash'], 'state': self.state}

    def mark_response_loss(self) -> None:
        if self._closed:
            return
        self.state = 'indeterminate'
        try:
            self._record(
                'indeterminate',
                {'reason': 'response_delivery_lost'},
                approval=self._last_approval,
            )
        except Exception:
            pass

    def close(self) -> Mapping[str, Any]:
        if self._closed:
            raise SupervisedUiSeatError('worker_closed')
        receipt = self._record('worker_closed', {'final_state': self.state})
        self._closed = True
        self.receipts.close()
        return {'event_hash': receipt['event_hash'], 'state': self.state}

    @property
    def closed(self) -> bool:
        return self._closed
