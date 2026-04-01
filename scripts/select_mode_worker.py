#!/usr/bin/env python3
"""select_mode_worker.py — Mode selection subprocess for consultation.py.

This script MUST be launched inside the correct dbus-run-session that
owns the Firefox instance. consultation.py runs outside that session,
so Atspi.get_desktop(0) connects to the wrong AT-SPI registry and
cannot see React portal dropdown items after they open.

Launch pattern (from consultation.py):

    dbus-run-session --dbus-daemon=dbus-daemon \
        --config-file=/usr/share/dbus-1/session.conf -- \
        bash -c 'source /tmp/dbus_env_:6 && python3 select_mode_worker.py ...'

OR more simply — re-use the existing session bus from the launch script:

    DBUS_SESSION_BUS_ADDRESS=$(cat /tmp/dbus_addr_:6) \
    AT_SPI_BUS_ADDRESS=$(cat /tmp/a11y_bus_:6) \
    DISPLAY=:6 GTK_USE_PORTAL=0 \
    python3 scripts/select_mode_worker.py --platform perplexity --mode deep_research

The key is that this process must start with the correct
DBUS_SESSION_BUS_ADDRESS *before* any gi/Atspi import, because
Atspi.get_desktop(0) connects at first call and caches the connection.

Outputs JSON to stdout:
    {"success": true, "selected_mode": "deep_research", "selected_item": "Deep research New"}
    {"success": false, "error": "..."}
"""

import argparse
import json
import os
import sys
import time

# --- Environment MUST be set before any AT-SPI/gi import ---
# Caller is responsible for setting DBUS_SESSION_BUS_ADDRESS and
# AT_SPI_BUS_ADDRESS before launching this process.
# We assert they are set so failures are loud, not silent.

def _assert_env():
    bus = os.environ.get('DBUS_SESSION_BUS_ADDRESS', '')
    a11y = os.environ.get('AT_SPI_BUS_ADDRESS', '')
    display = os.environ.get('DISPLAY', '')
    if not bus:
        print(json.dumps({'success': False,
                          'error': 'DBUS_SESSION_BUS_ADDRESS not set — must run inside correct dbus session'}),
              flush=True)
        sys.exit(1)
    if not display:
        print(json.dumps({'success': False,
                          'error': 'DISPLAY not set'}),
              flush=True)
        sys.exit(1)
    return bus, a11y, display


_bus, _a11y, _display = _assert_env()

# Now safe to import AT-SPI modules
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [mode_worker] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stderr,  # stdout is reserved for JSON result
)
logger = logging.getLogger('mode_worker')

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi  # noqa: E402 — must come after env setup

from core import atspi as _atspi
from core.mode_select import select_mode_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', required=True)
    parser.add_argument('--mode', default=None)
    parser.add_argument('--model', default=None)
    parser.add_argument('--pid', type=int, default=None,
                        help='Firefox PID (from /tmp/firefox_pid_:N) for display filtering')
    args = parser.parse_args()

    logger.info(f"mode_worker: platform={args.platform} mode={args.mode} "
                f"model={args.model} DISPLAY={_display}")
    logger.info(f"DBUS_SESSION_BUS_ADDRESS={_bus[:60]}...")

    # Give AT-SPI registry a moment to settle if Firefox was just opened
    time.sleep(0.5)

    firefox = _atspi.find_firefox_for_platform(args.platform, pid=args.pid)
    if not firefox:
        result = {'success': False, 'error': f'Firefox not found in AT-SPI tree for {args.platform}'}
        print(json.dumps(result), flush=True)
        sys.exit(1)

    doc = _atspi.get_platform_document(firefox, args.platform)
    if not doc:
        result = {'success': False, 'error': f'{args.platform} document not found in Firefox AT-SPI tree'}
        print(json.dumps(result), flush=True)
        sys.exit(1)

    result = select_mode_model(
        platform=args.platform,
        mode=args.mode,
        model=args.model,
        doc=doc,
        firefox=firefox,
        our_pid=args.pid,
    )

    # Strip non-serialisable atspi_obj references from result
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items() if k != 'atspi_obj'}
        if isinstance(obj, list):
            return [_clean(i) for i in obj]
        return obj

    print(json.dumps(_clean(result)), flush=True)
    sys.exit(0 if result.get('success') else 2)


if __name__ == '__main__':
    main()
