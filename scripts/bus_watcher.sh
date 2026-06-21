#!/usr/bin/env bash
set -Eeuo pipefail

N="${1:?display number required}"
[[ "${N}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: display number must be a positive integer" >&2; exit 1; }

exec xprop -display ":${N}" -spy -root AT_SPI_BUS | while IFS= read -r LINE; do
    ADDR="$(printf '%s\n' "$LINE" | sed 's/.*= "//;s/"$//')"
    case "$ADDR" in
        unix:path=*|unix:abstract=*)
            printf '%s\n' "$ADDR" > "/tmp/a11y_bus_:${N}.tmp"
            mv "/tmp/a11y_bus_:${N}.tmp" "/tmp/a11y_bus_:${N}"
            ;;
    esac
done
