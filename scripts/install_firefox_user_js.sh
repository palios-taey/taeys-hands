#!/usr/bin/env bash
# Install the repo-owned Firefox profile policy into one profile directory.

set -Eeuo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 <profile-dir> [firefox-user.js]" >&2
    exit 2
fi

PROFILE_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_JS="${2:-${REPO_ROOT}/systemd/user/firefox-user.js}"
USER_JS="${PROFILE_DIR}/user.js"

if [[ ! -f "${SOURCE_JS}" ]]; then
    echo "ERROR: Firefox user.js template not found: ${SOURCE_JS}" >&2
    exit 1
fi

mkdir -p "${PROFILE_DIR}"

if [[ -e "${USER_JS}" ]] && command -v chattr >/dev/null 2>&1; then
    chattr -i "${USER_JS}" 2>/dev/null || true
fi

shopt -s nullglob
rm -f "${PROFILE_DIR}"/sessionstore*.jsonlz4
rm -f "${PROFILE_DIR}"/sessionstore-backups/*.jsonlz4
shopt -u nullglob

TMP="${USER_JS}.tmp.$$"
trap 'rm -f "${TMP}"' EXIT
install -m 0644 "${SOURCE_JS}" "${TMP}"
mv -f "${TMP}" "${USER_JS}"
chmod 0644 "${USER_JS}"
