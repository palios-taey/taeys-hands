from unittest.mock import MagicMock, patch

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


def test_notify_extracts_and_stores_after_response_complete(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    session = {
        "platform": "chatgpt",
        "monitor_id": "mon-123",
        "session_id": "sess-123",
        "started_ts": 0,
    }

    extractor = MagicMock()
    extractor.extract.return_value = {
        "success": True,
        "content": "hello world",
    }
    storage = MagicMock()
    storage.store.return_value = "hash-123"

    with patch("monitor.central.ExtractorRegistry", return_value=extractor), \
         patch("monitor.central.StoragePipeline", return_value=storage), \
         patch("workers.manager.send_to_worker") as send_to_worker:
        monitor._notify(session, "response_complete", "stop_button")

    extractor.extract.assert_called_once()
    worker_fn = extractor.extract.call_args.args[1]
    worker_fn({"cmd": "extract", "strategy": "response_last_copy"})
    send_to_worker.assert_called_once_with(
        "chatgpt",
        {"cmd": "extract", "strategy": "response_last_copy"},
        timeout=120.0,
    )
    storage.store.assert_called_once_with(
        "chatgpt",
        "hello world",
        "sess-123",
        "mon-123",
        mock_redis,
    )


def test_notify_keeps_notification_when_extraction_fails(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    session = {
        "platform": "chatgpt",
        "monitor_id": "mon-123",
        "session_id": "sess-123",
        "started_ts": 0,
    }

    rpush = MagicMock()
    mock_redis.rpush = rpush

    extractor = MagicMock()
    extractor.extract.side_effect = RuntimeError("worker failed")

    with patch("monitor.central.ExtractorRegistry", return_value=extractor), \
         patch("monitor.central.StoragePipeline") as storage:
        monitor._notify(session, "response_complete", "stop_button")

    rpush.assert_called_once()
    storage.assert_not_called()
