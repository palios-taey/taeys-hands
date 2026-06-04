#!/usr/bin/env bash
set -eu

N="${1:?display number required}"

exec xprop -display ":${N}" -spy -root AT_SPI_BUS 2>/dev/null | while IFS= read -r LINE; do
    ADDR="$(printf '%s\n' "$LINE" | sed 's/.*= "//;s/"$//')"
    case "$ADDR" in
        unix:path=*|unix:abstract=*)
            printf '%s\n' "$ADDR" > "/tmp/a11y_bus_:${N}.tmp"
            mv "/tmp/a11y_bus_:${N}.tmp" "/tmp/a11y_bus_:${N}"
            ;;
    esac
done
