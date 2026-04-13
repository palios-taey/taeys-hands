#!/usr/bin/env python3
"""consultation_v2 CLI — production consultation runner.

Runs V2 YAML-driven consultation on a single platform.
Handles multi-display DBUS/AT-SPI setup before any imports.

Usage:
    python3 -m consultation_v2.cli --platform chatgpt \
        --message "Analyze this" --attach file.md

    # Uses YAML consultation_defaults for model/mode if not specified
    python3 -m consultation_v2.cli --platform gemini \
        --message "Research this topic" --attach package.md

    # Follow-up on existing session
    python3 -m consultation_v2.cli --platform gemini \
        --session-url "https://gemini.google.com/app/abc123" \
        --message "Elaborate on point 3"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


# ---- Display + bus setup BEFORE any AT-SPI imports ----

def _read_platform_displays() -> dict:
    """Read PLATFORM_DISPLAYS from env or .env file."""
    raw = os.environ.get('PLATFORM_DISPLAYS', '')
    if not raw:
        env_file = Path(__file__).resolve().parents[1] / '.env'
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith('PLATFORM_DISPLAYS='):
                    raw = line.split('=', 1)[1].strip()
                    break
        except FileNotFoundError:
            pass
    result = {}
    if raw:
        for pair in raw.split(','):
            pair = pair.strip()
            if ':' in pair:
                plat, dnum = pair.rsplit(':', 1)
                result[plat.strip()] = f':{dnum.strip()}'
    return result


def setup_display(platform: str, display: str | None = None) -> None:
    """Set DISPLAY, AT_SPI_BUS_ADDRESS, DBUS_SESSION_BUS_ADDRESS for a platform.

    Must be called BEFORE importing gi/Atspi.
    """
    if not display:
        displays = _read_platform_displays()
        display = displays.get(platform)
    if display:
        os.environ['DISPLAY'] = display

    disp = os.environ.get('DISPLAY', '')
    if not disp:
        return

    # AT-SPI bus (for Atspi library) — obtained via org.a11y.Bus.GetAddress
    a11y_file = f'/tmp/a11y_bus_{disp}'
    try:
        bus = Path(a11y_file).read_text().strip()
        if bus:
            os.environ['AT_SPI_BUS_ADDRESS'] = bus
    except FileNotFoundError:
        pass

    # D-Bus session bus (for xdotool) — the Firefox process's session bus
    session_file = f'/tmp/dbus_session_bus_{disp}'
    try:
        session_bus = Path(session_file).read_text().strip()
        if session_bus:
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = session_bus
    except FileNotFoundError:
        # Fall back to AT-SPI bus if no separate session bus file
        if os.environ.get('AT_SPI_BUS_ADDRESS'):
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = os.environ['AT_SPI_BUS_ADDRESS']

    # This process IS the display worker — no subprocess routing
    os.environ.pop('PLATFORM_DISPLAYS', None)
    os.environ['GTK_USE_PORTAL'] = '0'


# ---- Load .env before anything else ----
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _PROJECT_ROOT / '.env'
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault('TAEY_NODE_ID', 'taeys-hands')
sys.path.insert(0, str(_PROJECT_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='V2 YAML-driven consultation runner.')
    parser.add_argument('--platform', required=True,
                        choices=['chatgpt', 'claude', 'gemini', 'grok', 'perplexity'])
    parser.add_argument('--message', required=True)
    parser.add_argument('--attach', action='append', default=[])
    parser.add_argument('--model', default=None)
    parser.add_argument('--mode', default=None)
    parser.add_argument('--tool', action='append', default=[])
    parser.add_argument('--connector', action='append', default=[],
                        help='Connector name to enable (repeatable)')
    parser.add_argument('--session-url', default=None,
                        help='Existing session URL for follow-up')
    parser.add_argument('--display', default=None,
                        help='X11 display (auto-detected from PLATFORM_DISPLAYS)')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default=None)
    parser.add_argument('--no-neo4j', action='store_true')
    parser.add_argument('--requester', default=None,
                        help='Node ID of requester (for Redis notifications)')
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Set up display + bus BEFORE importing AT-SPI
    setup_display(args.platform, args.display)

    # NOW import V2 modules (which import AT-SPI)
    from consultation_v2.orchestrator import run_consultation
    from consultation_v2.types import ConsultationRequest

    request = ConsultationRequest(
        platform=args.platform,
        message=args.message,
        attachments=list(args.attach or []),
        model=args.model,
        mode=args.mode,
        tools=list(args.tool or []),
        connectors=list(args.connector or []),
        session_url=args.session_url,
        timeout=args.timeout,
        output_path=args.output,
        no_neo4j=args.no_neo4j,
        requester=args.requester,
    )
    result = run_consultation(request)

    # Output
    payload = result.serializable()
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))

    # Summary to stderr
    for step in result.steps:
        status = "OK" if step.success else "FAIL"
        print(f"  [{status}] {step.step}: {step.message}", file=sys.stderr)
    if result.ok:
        print(f"  Response: {len(result.response_text)} chars", file=sys.stderr)
    else:
        failed = next((s for s in result.steps if not s.success), None)
        if failed:
            print(f"  STOPPED at: {failed.step} — {failed.message}", file=sys.stderr)

    return 0 if result.ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
