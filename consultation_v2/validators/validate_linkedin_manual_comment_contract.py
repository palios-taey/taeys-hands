#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from consultation_v2.platforms.linkedin.manual import (  # noqa: E402
    SELECTED_POST_EDITOR_PREFIX,
    element_operation,
)
from consultation_v2.yaml_contract import load_platform_yaml  # noqa: E402


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    contract = (
        (((load_platform_yaml('linkedin').get('workflow') or {})
          .get('engagement_signal_capture') or {})
         .get('manual_comment_composition') or {})
    )
    editor = contract.get('editor') or {}
    activity = '1234567890'
    body_sha256 = hashlib.sha256(b'public post body').hexdigest()
    element_key = (
        f'{SELECTED_POST_EDITOR_PREFIX}{activity}_body_{body_sha256}'
    )
    empty_context = {
        'selected_activity': activity,
        'selected_post_body_sha256': body_sha256,
        'comment_editor_ready': True,
        'comment_editor_empty': True,
        'comment_editor_text_sha256': hashlib.sha256(b'').hexdigest(),
        'comment_editor_text_chars': 0,
    }
    empty_operation = element_operation(element_key, [], empty_context)
    _require(
        empty_operation == {
            'method': 'paste_frozen_text',
            'effect_class': 'draft',
            'primitives': ['paste_frozen_text'],
            'allowed_now': ['paste_frozen_text'],
            'max_text_chars': editor.get('max_text_chars'),
            'forbidden': [
                'click',
                'activate',
                'hover',
                'mapped_pointer_activate',
                'submit_frozen_comment',
            ],
            'postcondition': {
                'kind': editor.get('postcondition'),
                'activity': activity,
                'body_sha256': body_sha256,
            },
        },
        'empty LinkedIn editor did not declare one YAML-bounded paste',
    )

    draft = 'Frozen public comment'
    draft_sha256 = hashlib.sha256(draft.encode('utf-8')).hexdigest()
    nonempty_context = {
        **empty_context,
        'comment_editor_empty': False,
        'comment_editor_text_sha256': draft_sha256,
        'comment_editor_text_chars': len(draft),
    }
    nonempty_operation = element_operation(element_key, [], nonempty_context)
    _require(
        nonempty_operation == {
            'method': 'observe',
            'effect_class': 'observation',
            'primitives': [],
            'allowed_now': [],
            'forbidden': [
                'activate',
                'activate_optional_like',
                'paste_frozen_text',
                'submit_frozen_comment',
            ],
            'postcondition': {
                'kind': editor.get('postcondition'),
                'activity': activity,
                'body_sha256': body_sha256,
                'editor_text_sha256': draft_sha256,
                'editor_text_chars': len(draft),
            },
        },
        'non-empty LinkedIn editor was not observation-only',
    )

    invalid_context = {
        **nonempty_context,
        'comment_editor_text_chars': 0,
    }
    try:
        element_operation(element_key, [], invalid_context)
    except ValueError:
        pass
    else:
        raise AssertionError('inconsistent LinkedIn editor identity did not fail')

    print('linkedin manual comment contract: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
