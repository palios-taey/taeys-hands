import os
from unittest.mock import MagicMock, patch

from monitor.central import CentralMonitor, ExtractTimeout


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
         patch.object(monitor, "_call_worker", return_value={"success": True}) as call_worker:
        monitor._notify(session, "response_complete", "stop_button")
        extractor.extract.assert_called_once()
        worker_fn = extractor.extract.call_args.args[1]
        worker_fn({"cmd": "extract"})
        call_worker.assert_called_once_with(
            "chatgpt",
            {"cmd": "extract"},
            operation="extract",
        )

    storage.store.assert_called_once()
    assert storage.store.call_args.args == (
        "chatgpt",
        "hello world",
        "sess-123",
        "mon-123",
        mock_redis,
    )
    assert storage.store.call_args.kwargs == {"source": "monitor"}


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


def test_notify_keeps_notification_when_extraction_times_out(mock_redis):
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
    extractor.extract.side_effect = ExtractTimeout()

    with patch("monitor.central.ExtractorRegistry", return_value=extractor), \
         patch("monitor.central.StoragePipeline") as storage:
        monitor._notify(session, "response_complete", "stop_button")

    rpush.assert_called_once()
    storage.assert_not_called()


def test_notify_keeps_notification_when_signal_setup_fails(mock_redis):
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

    with patch("monitor.central.signal.signal", side_effect=ValueError("no signals")), \
         patch("monitor.central.ExtractorRegistry") as extractor, \
         patch("monitor.central.StoragePipeline") as storage:
        monitor._notify(session, "response_complete", "stop_button")

    rpush.assert_called_once()
    extractor.assert_not_called()
    storage.assert_not_called()


def test_call_worker_uses_platform_override_timeout(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    with patch.dict(
        os.environ,
        {
            "MONITOR_WORKER_TIMEOUT_SEC": "5",
            "MONITOR_POLL_TIMEOUT_CHATGPT_SEC": "7.5",
        },
        clear=False,
    ), patch("workers.manager.send_to_worker", return_value={"ok": True}) as send_to_worker:
        result = monitor._call_worker("chatgpt", {"cmd": "check_stop"}, operation="poll")

    assert result == {"ok": True}
    send_to_worker.assert_called_once_with(
        "chatgpt",
        {"cmd": "check_stop"},
        timeout=7.5,
    )


def test_cycle_skips_platform_when_worker_call_times_out(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    sessions = [
        {
            "platform": "chatgpt",
            "monitor_id": "mon-123",
            "session_id": "sess-123",
            "started_ts": 0,
        }
    ]

    with patch.object(monitor, "_get_sessions", return_value=sessions), \
         patch("core.platforms.get_platform_display", return_value=":2"), \
         patch.object(monitor, "_call_worker", side_effect=[None, {"send_visible": True}, {"content_hash": "hash"}]), \
         patch.object(monitor, "_detect_completion") as detect_completion, \
         patch.object(monitor, "_remove_session") as remove_session:
        monitor._cycle()

    detect_completion.assert_not_called()
    remove_session.assert_not_called()
