from unittest.mock import patch

from monitor.central import CentralMonitor


def test_detect_completion_allows_primary_gate_without_send_visible(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    session = {
        "platform": "chatgpt",
        "monitor_id": "mon-123",
        "started_ts": 0,
        "timeout": 7200,
    }

    with patch.object(monitor, "_notify") as notify:
        generating = monitor._detect_completion(
            session,
            {
                "stop_found": True,
                "send_visible": False,
                "content_hash": "hash-1",
            },
        )
        completed = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "hash-2",
            },
        )

    assert generating is False
    assert completed is True
    notify.assert_called_once_with(session, "response_complete", "stop_button")
