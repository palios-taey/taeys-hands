import os
import time
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


def test_detect_completion_deep_research_waits_for_second_stop_cycle(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    session = {
        "platform": "gemini",
        "monitor_id": "mon-deep",
        "mode": "deep_research",
        "started_ts": 0,
        "timeout": 7200,
    }

    with patch.object(monitor, "_notify") as notify:
        first_generating = monitor._detect_completion(
            session,
            {
                "stop_found": True,
                "send_visible": False,
                "content_hash": "hash-1",
            },
        )
        plan_transition = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "hash-2",
            },
        )
        second_generating = monitor._detect_completion(
            session,
            {
                "stop_found": True,
                "send_visible": False,
                "content_hash": "hash-3",
            },
        )
        completed = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "hash-4",
            },
        )

    assert first_generating is False
    assert plan_transition is False
    assert second_generating is False
    assert completed is True
    assert mock_redis.get("taey:monitor:mon-deep:stop_cycles") == "2"
    notify.assert_called_once_with(session, "response_complete", "stop_button")


def test_detect_completion_deep_think_requires_full_stop_transition(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    session = {
        "platform": "gemini",
        "monitor_id": "mon-think",
        "mode": "deep_think",
        "started_ts": time.time(),
        "timeout": 7200,
    }

    with patch.object(monitor, "_notify") as notify:
        poll_without_transition = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "",
            },
        )

    assert poll_without_transition is False
    assert mock_redis.get("taey:monitor:mon-think:stop_cycles") is None
    notify.assert_not_called()


def test_detect_completion_deep_research_ignores_content_stability_fallback(mock_redis):
    with patch.object(CentralMonitor, "_connect_redis", return_value=mock_redis):
        monitor = CentralMonitor()

    session = {
        "platform": "gemini",
        "monitor_id": "mon-stable",
        "mode": "deep_research",
        "started_ts": time.time(),
        "timeout": 7200,
    }

    with patch.object(monitor, "_notify") as notify:
        first_poll = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "stable-hash",
            },
        )
        second_poll = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "stable-hash",
            },
        )
        third_poll = monitor._detect_completion(
            session,
            {
                "stop_found": False,
                "send_visible": False,
                "content_hash": "stable-hash",
            },
        )

    assert first_poll is False
    assert second_poll is False
    assert third_poll is False
    assert mock_redis.get("taey:monitor:mon-stable:content_stable_ticks") == "2"
    assert mock_redis.get("taey:monitor:mon-stable:stop_cycles") is None
    notify.assert_not_called()


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


def test_cycle_backs_off_platform_after_three_failures(mock_redis):
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
         patch.object(monitor, "_plan_active", return_value=False), \
         patch("core.platforms.get_platform_display", return_value=":2"), \
         patch.object(monitor, "_call_worker", return_value=None) as call_worker, \
         patch.object(monitor, "_detect_completion") as detect_completion, \
         patch.object(monitor, "_remove_session") as remove_session:
        monitor._cycle()
        monitor._cycle()
        monitor._cycle()

        assert monitor._platform_failure_counts.get("chatgpt", 0) == 0
        assert monitor._platform_retry_after["chatgpt"] > time.monotonic()

        call_count_before_backoff = call_worker.call_count
        monitor._cycle()

    assert call_worker.call_count == call_count_before_backoff
    detect_completion.assert_not_called()
    remove_session.assert_not_called()
