#!/usr/bin/env bash
set -euo pipefail

URL=${1:-}
if [[ -z "${URL}" ]]; then
  echo "Usage: scripts/smoke.sh <cloud-run-url>" >&2
  exit 1
fi

curl -fsSL "$URL/healthz" -o /dev/null && echo "Smoke OK: $URL/healthz"
#!/usr/bin/env bash
set -euo pipefail
URL="$1"
if [[ -z "${URL}" ]]; then
  echo "Usage: $0 <cloud-run-url>" >&2
  exit 2
fi
curl -fsS "${URL}/healthz" >/dev/null
echo "Smoke OK: ${URL}"
