#!/usr/bin/env bash
set -euo pipefail

CRON_FILE="$(mktemp)"
CURRENT_CRON="$(mktemp)"

cleanup() {
  rm -f "${CRON_FILE}" "${CURRENT_CRON}"
}
trap cleanup EXIT

if ! crontab -l >"${CURRENT_CRON}" 2>/dev/null; then
  : >"${CURRENT_CRON}"
fi

# Drop previously managed block if present.
awk '
  BEGIN {skip=0}
  /^# BEGIN FAMILY ORCHESTRATION$/ {skip=1; next}
  /^# END FAMILY ORCHESTRATION$/ {skip=0; next}
  skip==0 {print}
' "${CURRENT_CRON}" >"${CRON_FILE}"

cat >>"${CRON_FILE}" <<'CRON'
# BEGIN FAMILY ORCHESTRATION
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Keep remote agents alive with ~12s cadence (script loops 5x per minute).
*/1 * * * * /home/spark/taeys-hands/scripts/remote_heartbeats.sh

# Periodic full-family health summary to The Stream.
*/5 * * * * /home/spark/taeys-hands/scripts/family_health.sh

# Ensure orchestration stack comes up after reboot.
@reboot /home/spark/taeys-hands/scripts/family_boot.sh
# END FAMILY ORCHESTRATION
CRON

crontab "${CRON_FILE}"
printf 'Installed orchestration cron jobs.\n'
