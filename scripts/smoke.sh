#!/usr/bin/env bash
set -euo pipefail

URL=${1:-}
if [[ -z "${URL}" ]]; then
  echo "Usage: scripts/smoke.sh <cloud-run-url>" >&2
  exit 1
fi

echo "Smoke testing: ${URL}"

echo -n "  - Checking /healthz... "
curl -fsSL "${URL}/healthz" -o /dev/null
echo "OK"

echo -n "  - Checking /api/reports/list... "
curl -fsSL "${URL}/api/reports/list" -o /dev/null
echo "OK"

echo -n "  - Checking root path /... "
curl -fsSL "${URL}/" -o /dev/null
echo "OK"
