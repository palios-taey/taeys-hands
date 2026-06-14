from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import yaml

from consultation_v2.drivers.perplexity import PerplexityConsultationDriver
from consultation_v2.types import ConsultationRequest


ROOT = Path(__file__).resolve().parents[1]


def _request(message: str = 'hello world') -> ConsultationRequest:
    return ConsultationRequest(platform='perplexity', message=message)


def _snapshot() -> MagicMock:
    snap = MagicMock()
    snap.serializable.return_value = {'ok': True}
    return snap


def test_perplexity_send_prompt_uses_last_submit_button() -> None:
    driver = PerplexityConsultationDriver()
    driver.runtime = MagicMock()
    first_snap = _snapshot()
    confirm_snap = _snapshot()
    driver.runtime.snapshot.side_effect = [first_snap, confirm_snap]
    driver.runtime.wait_until.return_value = True
    driver.runtime.current_url.return_value = 'https://example.test/thread'
    driver.runtime.click.return_value = True

    send_button = MagicMock()
    driver.find_last = MagicMock(return_value=send_button)

    result = driver.result(_request())
    result.session_url_before = 'https://example.test/new'

    assert driver.send_prompt(result.request, result) is True
    driver.find_last.assert_called_once_with(first_snap, 'submit_button')
    driver.runtime.click.assert_called_once_with(send_button)


def test_perplexity_yaml_submit_button_uses_last_by_y_pick() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'perplexity.yaml').read_text())
    submit = data['tree']['element_map']['submit_button']
    assert submit['pick'] == 'last_by_y'


def test_consultation_v2_perplexity_exact_map() -> None:
    data = yaml.safe_load((ROOT / 'consultation_v2' / 'platforms' / 'perplexity.yaml').read_text())
    element_map = data['tree']['element_map']
    workflow = data['workflow']['selection']
    validation = data['validation']

    assert element_map['input']['name'] == ''
    assert element_map['attach_trigger']['name'] == 'Add files or tools'
    assert element_map['upload_files_item']['name'] == 'Upload files or images'
    assert element_map['git_connector_item']['name'] == 'Connectors'
    assert element_map['spaces_item']['name'] == 'Spaces'
    assert element_map['submit_button']['name'] == 'Submit'
    assert element_map['copy_button']['name'] == 'Copy'
    assert workflow['mode_targets']['deep_research'] == 'deep_research_toggle'
    assert validation['deep_research_active']['indicators'] == [
        {'name': 'Deep research', 'role': 'toggle button', 'states_include': ['pressed']},
    ]
