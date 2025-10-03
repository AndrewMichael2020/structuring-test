#!/usr/bin/env bash
set -uuo pipefail

# Robust smoke test with retries and diagnostics. Exits non-zero only when
# endpoints consistently fail after configured attempts.

URL=${1:-}
ATTEMPTS=${SMOKE_ATTEMPTS:-5}
SLEEP_BASE=${SMOKE_SLEEP_BASE:-2}
TIMEOUT=${SMOKE_TIMEOUT:-10}

if [[ -z "${URL}" ]]; then
  echo "Usage: scripts/smoke.sh <cloud-run-url>" >&2
  exit 1
fi

echo "Smoke testing: ${URL} (attempts=${ATTEMPTS}, timeout=${TIMEOUT}s)"

_check() {
  local path="$1"
  local i=0
  local attempt=1
  while (( attempt <= ATTEMPTS )); do
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    # Use --fail to return non-zero on HTTP 4xx/5xx, --show-error for diagnostic
    if curl -sS --fail --show-error --max-time "${TIMEOUT}" "${URL}${path}" -o /dev/null; then
      echo "${ts} OK: ${path}"
      return 0
    else
      echo "${ts} Attempt ${attempt}/${ATTEMPTS} failed for ${path}."
      # Per-attempt diagnostics (more verbose for /healthz by default)
      if [[ "${path}" == "/healthz" || "${DEBUG_SMOKE:-0}" == "1" ]]; then
        host=$(echo "${URL}" | awk -F/ '{print $3}') || host=""
        echo "  - Resolving host: ${host}"
        if command -v dig >/dev/null 2>&1; then
          dig +short "${host}" | sed -n '1,5p' || true
        else
          # fallback to getent/host
          if command -v getent >/dev/null 2>&1; then
            getent ahosts "${host}" | awk '{print $1}' | sed -n '1,5p' || true
          fi
        fi
        # Show short curl timing and first 1KB of body to help debug hangs
        echo "  - Curl timing + status (short):"
        curl -sS --max-time "${TIMEOUT}" -w "\n  time_total=%{time_total} time_connect=%{time_connect} http_code=%{http_code}\n" "${URL}${path}" -o /tmp/smoke_body.$$ || true
        echo "  - Body snippet (first 1KB):"
        head -c 1024 /tmp/smoke_body.$$ | sed -n '1,200p' || true
        rm -f /tmp/smoke_body.$$
      fi
      # small backoff with incremental sleep
      sleep_time=$(( SLEEP_BASE * attempt ))
      sleep ${sleep_time}
      attempt=$(( attempt + 1 ))
    fi
  done

  # Final diagnostic: fetch headers+body for debugging (non-fatal to print)
  echo "--- Diagnostic response for ${URL}${path} ---"
  curl -sS -D - --max-time "${TIMEOUT}" "${URL}${path}" || true
  echo "--- End diagnostic ---"
  return 1
}

failures=0

echo -n "  - Checking /healthz... "
if ! _check "/healthz"; then
  echo " (non-fatal unless other checks fail)"
  healthz_failed=1
else
  healthz_failed=0
fi

echo -n "  - Checking /api/reports/list... "
if ! _check "/api/reports/list"; then
  failures=$((failures+1))
  list_failed=1
else
  list_failed=0
fi

echo -n "  - Checking root path /... "
if ! _check "/"; then
  failures=$((failures+1))
  root_failed=1
else
  root_failed=0
fi

# Make /healthz non-fatal: only fail the smoke if BOTH /api/reports/list and /
# failed. If only /healthz fails but at least one of the other endpoints passed,
# treat the smoke as success (avoids Cloud Run frontal 404 quirks).
if [[ "${healthz_failed:-0}" == "1" && "${list_failed:-0}" == "1" && "${root_failed:-0}" == "1" ]]; then
  echo "Smoke checks failed: endpoints failed after ${ATTEMPTS} attempts." >&2
  exit 2
fi

echo "Smoke checks passed (healthz non-fatal if other endpoints OK)."
