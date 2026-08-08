#!/usr/bin/env bash
set -Eeuo pipefail

# Production-safe dashboard/API verification.
#
# Rules:
# - systemd is the source of truth for the production API lifecycle.
# - If crypto-quant-bot-api is active, use the existing service.
# - If the service is not active, start a temporary API process and clean up only that PID.
# - Never kill systemd-managed processes.
# - Never start a duplicate API server when systemd is already active.
# - Protected endpoints must return 401 without auth and 2xx with BOT_API_KEY.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SERVICE_NAME="${SERVICE_NAME:-crypto-quant-bot-api}"
ENV_FILE="${ENV_FILE:-.env}"
COMMAND_TIMEOUT_SECONDS="${COMMAND_TIMEOUT_SECONDS:-10}"
CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-3}"

BOT_API_KEY="${BOT_API_KEY:-}"
BOT_API_HOST="${BOT_API_HOST:-}"
BOT_API_PORT="${BOT_API_PORT:-}"
BASE_URL="${BOT_API_BASE_URL:-${BASE_URL:-}}"

STARTED_TEMP_SERVER=0
API_PID=""
FAILURES=0
REPORT=""

load_dotenv() {
  local line key value

  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"

    value="${value%$'\r'}"

    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    case "$key" in
      BOT_API_KEY)
        [[ -z "$BOT_API_KEY" ]] && BOT_API_KEY="$value"
        ;;
      BOT_API_HOST)
        [[ -z "$BOT_API_HOST" ]] && BOT_API_HOST="$value"
        ;;
      BOT_API_PORT)
        [[ -z "$BOT_API_PORT" ]] && BOT_API_PORT="$value"
        ;;
      BOT_API_BASE_URL|BASE_URL)
        [[ -z "$BASE_URL" ]] && BASE_URL="$value"
        ;;
    esac
  done < "$ENV_FILE"
}

cleanup() {
  if [[ "$STARTED_TEMP_SERVER" == "1" && -n "$API_PID" ]]; then
    echo "INFO: stopping temporary API process PID=${API_PID}"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}

record_result() {
  local verdict="$1"
  local name="$2"
  local detail="$3"

  REPORT+="- ${verdict} ${name}: ${detail}"$'\n'

  if [[ "$verdict" == "FAIL" ]]; then
    FAILURES=$((FAILURES + 1))
  fi
}

curl_status() {
  local url="$1"
  shift || true

  curl \
    --silent \
    --show-error \
    --output /dev/null \
    --write-out "%{http_code}" \
    --connect-timeout "$CONNECT_TIMEOUT_SECONDS" \
    --max-time "$COMMAND_TIMEOUT_SECONDS" \
    "$@" \
    "$url"
}

wait_for_api() {
  local status=""

  for _ in {1..30}; do
    status="$(curl_status "${BASE_URL}/" || true)"

    if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then
      return 0
    fi

    sleep 1
  done

  echo "FAIL: API did not become ready at ${BASE_URL}/"
  return 1
}

ensure_api_available() {
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "INFO: ${SERVICE_NAME} is active; using existing systemd service."
    STARTED_TEMP_SERVER=0
    wait_for_api
    return 0
  fi

  echo "INFO: ${SERVICE_NAME} is not active; starting temporary API process."
  python3 run_api.py &
  API_PID="$!"
  STARTED_TEMP_SERVER=1

  wait_for_api
}

check_public_endpoint() {
  local path="$1"
  local status

  status="$(curl_status "${BASE_URL}${path}" || true)"

  if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then
    record_result "PASS" "public ${path}" "returned HTTP ${status} without authentication"
  else
    record_result "FAIL" "public ${path}" "expected 2xx without authentication, got ${status}"
  fi
}

check_protected_endpoint() {
  local path="$1"
  local unauth_status auth_status

  unauth_status="$(curl_status "${BASE_URL}${path}" || true)"

  if [[ "$unauth_status" == "401" ]]; then
    record_result "PASS" "unauthenticated ${path}" "returned expected HTTP 401"
  else
    record_result "FAIL" "unauthenticated ${path}" "expected HTTP 401 without auth, got ${unauth_status}"
  fi

  auth_status="$(
    curl_status "${BASE_URL}${path}" \
      --header "Authorization: Bearer ${BOT_API_KEY}" || true
  )"

  if [[ "$auth_status" =~ ^2[0-9][0-9]$ ]]; then
    record_result "PASS" "authenticated ${path}" "returned HTTP ${auth_status} with BOT_API_KEY"
  else
    record_result "FAIL" "authenticated ${path}" "expected 2xx with BOT_API_KEY, got ${auth_status}"
  fi
}

main() {
  local public_endpoints protected_endpoints endpoint

  trap cleanup EXIT

  load_dotenv

  BOT_API_HOST="${BOT_API_HOST:-127.0.0.1}"
  BOT_API_PORT="${BOT_API_PORT:-8899}"

  if [[ -z "$BASE_URL" ]]; then
    if [[ "$BOT_API_HOST" == "0.0.0.0" || "$BOT_API_HOST" == "::" ]]; then
      BASE_URL="http://127.0.0.1:${BOT_API_PORT}"
    else
      BASE_URL="http://${BOT_API_HOST}:${BOT_API_PORT}"
    fi
  fi

  if [[ -z "$BOT_API_KEY" ]]; then
    echo "FAIL: BOT_API_KEY is missing. Set it in environment or ${ENV_FILE}."
    return 1
  fi

  public_endpoints=(
    "/"
    "/health"
  )

  protected_endpoints=(
    "/api/health"
    "/api/market"
    "/api/portfolio"
    "/api/paper"
    "/api/analytics"
    "/status"
    "/signals/latest"
    "/paper/state"
  )

  echo "Dashboard API verification report"
  echo "Base URL: ${BASE_URL}"
  echo "Service: ${SERVICE_NAME}"
  echo "BOT_API_KEY: loaded"
  echo "Connect timeout: ${CONNECT_TIMEOUT_SECONDS}s"
  echo "Command timeout: ${COMMAND_TIMEOUT_SECONDS}s"
  echo

  ensure_api_available

  for endpoint in "${public_endpoints[@]}"; do
    check_public_endpoint "$endpoint"
  done

  for endpoint in "${protected_endpoints[@]}"; do
    check_protected_endpoint "$endpoint"
  done

  printf '%s' "$REPORT"
  echo

  if [[ "$FAILURES" -eq 0 ]]; then
    echo "Summary: PASS - dashboard/API verification completed."
    return 0
  fi

  echo "Summary: FAIL - ${FAILURES} check(s) failed."
  return 1
}

main "$@"
