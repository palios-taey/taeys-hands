#!/usr/bin/env python3
"""Consultation V2 CLI entrypoint.

Sets AT_SPI_BUS_ADDRESS + DBUS_SESSION_BUS_ADDRESS BEFORE any imports.
libatspi (gi.repository.Atspi) reads the bus address once at first use
and caches the connection for the process lifetime. The env must be
correct before the import chain reaches `from gi.repository import Atspi`.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Read the AT-SPI bus for the current DISPLAY before any Atspi import.
# Each Xvfb display has its own bus written to /tmp/a11y_bus_:N by
# restart_display.sh during display launch.
_display = os.environ.get('DISPLAY', ':0')
_bus_file = f'/tmp/a11y_bus_{_display}'
try:
    with open(_bus_file) as _f:
        _bus = _f.read().strip()
    if _bus:
        os.environ['AT_SPI_BUS_ADDRESS'] = _bus
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = _bus
except FileNotFoundError:
    pass

from consultation_v2.cli import main


if __name__ == '__main__':
    raise SystemExit(main())
