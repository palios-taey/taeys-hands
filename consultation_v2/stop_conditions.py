"""Machine-readable stop conditions for the clean consultation contract."""
from __future__ import annotations


STOP_CONDITION_IDS = frozenset({
    "unsupported_request_mapping",
    "missing_identity_package",
    "display_substrate_unhealthy",
    "navigation_validation_failed",
    "setup_validation_failed",
    "attachment_validation_failed",
    "prompt_readiness_failed",
    "send_stop_missing",
    "session_url_capture_failed",
    "monitor_registration_failed",
    "answer_thread_lost",
    "generation_stalled",
    "extraction_failed",
    "notification_ack_missing",
    "manual_recovery_required",
    "side_effect_uncertain",
    "duplicate_send_risk",
})

STOP_CONDITION_REFS = {
    "unsupported_request_mapping": "FLOW_CONSULTATION_ENGINE.md:271-304",
    "missing_identity_package": "FLOW_CONSULTATION_ENGINE.md:306-323",
    "display_substrate_unhealthy": "FLOW_CONSULTATION_ENGINE.md:325-371",
    "navigation_validation_failed": "FLOW_CONSULTATION_ENGINE.md:348-355",
    "setup_validation_failed": "FLOW_CONSULTATION_ENGINE.md:373-403",
    "attachment_validation_failed": "FLOW_CONSULTATION_ENGINE.md:373-385",
    "prompt_readiness_failed": "FLOW_CONSULTATION_ENGINE.md:463-468",
    "send_stop_missing": "FLOW_CONSULTATION_ENGINE.md:470-485",
    "session_url_capture_failed": "FLOW_CONSULTATION_ENGINE.md:470-489",
    "monitor_registration_failed": "FLOW_CONSULTATION_ENGINE.md:491-505",
    "answer_thread_lost": "FLOW_CONSULTATION_ENGINE.md:491-518",
    "generation_stalled": "FLOW_CONSULTATION_ENGINE.md:507-518",
    "extraction_failed": "FLOW_CONSULTATION_ENGINE.md:551-605",
    "notification_ack_missing": "FLOW_CONSULTATION_ENGINE.md:520-525",
    "manual_recovery_required": "FLOW_CONSULTATION_ENGINE.md:661-678",
    "side_effect_uncertain": "FLOW_CONSULTATION_ENGINE.md:661-678",
    "duplicate_send_risk": "FLOW_CONSULTATION_ENGINE.md:487-489",
}


def is_stop_condition(value: str) -> bool:
    return value in STOP_CONDITION_IDS
