#!/usr/bin/env bash
set -euo pipefail

URL=${1:-}
if [[ -z "${URL}" ]]; then
  echo "Usage: scripts/smoke.sh <cloud-run-url>" >&2
  exit 1
fi

curl -fsSL "$URL/healthz" -o /dev/null && echo "Smoke OK: $URL/healthz"
