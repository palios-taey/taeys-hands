"""Mode selection helpers for local and worker-routed execution."""

import logging
from typing import Callable, Optional

from core import atspi
from core.mode_select import select_mode_model
from core.platforms import is_multi_display
from workers.manager import send_to_worker

logger = logging.getLogger(__name__)


def handle_select_mode(platform: str, mode: str = None, model: str = None,
                       our_pid: int = None) -> dict:
    """Run mode selection locally in the current process."""
    firefox = atspi.find_firefox_for_platform(platform, pid=our_pid)
    if not firefox:
        return {'success': False, 'error': f'Firefox not found for {platform}'}

    doc = atspi.get_platform_document(firefox, platform)
    if not doc:
        return {'success': False, 'error': f'{platform} document not found'}

    return select_mode_model(
        platform=platform,
        mode=mode,
        model=model,
        doc=doc,
        firefox=firefox,
        our_pid=our_pid,
    )


def select_mode_with_worker_fallback(
    platform: str,
    mode: str = None,
    model: str = None,
    fallback: Optional[Callable[..., dict]] = None,
    timeout: float = 120.0,
) -> dict:
    """Use worker IPC for multi-display mode selection, then fall back locally."""
    if not is_multi_display():
        if fallback:
            return fallback(platform, mode=mode, model=model)
        return handle_select_mode(platform, mode=mode, model=model)

    cmd = {'cmd': 'select_mode'}
    if mode is not None:
        cmd['mode'] = mode
    if model is not None:
        cmd['model'] = model

    try:
        result = send_to_worker(platform, cmd, timeout=timeout)
        if isinstance(result, dict):
            result.setdefault('route', 'worker_ipc')
        return result
    except Exception as e:
        logger.warning("[%s] Worker mode selection unavailable: %s", platform, e)
        if not fallback:
            return {'success': False, 'error': f'worker mode selection failed: {e}'}

        result = fallback(platform, mode=mode, model=model)
        if isinstance(result, dict):
            result.setdefault('route', 'in_process_fallback')
            result.setdefault('worker_error', str(e))
        return result
