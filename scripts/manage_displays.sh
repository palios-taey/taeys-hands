#!/usr/bin/env bash

set -euo pipefail

ACTION="${1:-}"
SERVICES=(
    taey-display-2.service
    taey-display-3.service
    taey-display-4.service
    taey-display-5.service
    taey-display-6.service
)

usage() {
    echo "Usage: $0 {start|stop|status|restart}"
}

case "${ACTION}" in
    start|stop|status|restart)
        exec systemctl --user "${ACTION}" "${SERVICES[@]}"
        ;;
    *)
        usage
        exit 1
        ;;
esac
