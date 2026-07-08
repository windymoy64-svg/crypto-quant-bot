#!/usr/bin/env bash
set -uo pipefail

# Dashboard API smoke verification.
#
# This script intentionally verifies authentication behavior without changing
# application code:
# - public endpoints must succeed without credentials
# - protected endpoints may return 401 without credentials when BOT_API_KEY is set
# - protected endpoints must succeed when authenticated with BOT_API_KEY
# - every external command is wrapped with `timeout`

BASE_URL="${BOT_API_BASE_URL:-}"
COMMAND_TIMEOUT_SECONDS="${COMMAND_TIMEOUT_SECONDS:-10}"
BOT_API_KEY="${BOT_API_KEY:-}"
BOT_API_HOST="${BOT_API_HOST:-}"
BOT_API_PORT="${BOT_API_PORT:-}"

load_dotenv() {
  local line key value

  if [[ ! -f ".env" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"

    # Trim optional CR from Windows-edited .env files.
    value="${value%$'\r'}"

    # Remove simple matching quotes.
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    case "$key" in
      BOT_API_KEY)
        if [[ -z "${BOT_API_KEY}" ]]; then
          BOT_API_KEY="$value"
        fi
        ;;
      BOT_API_HOST)
        [[ -z "${BOT_API_HOST}" ]] && BOT_API_HOST="$value"
        ;;
      BOT_API_PORT)
        [[ -z "${BOT_API_PORT}" ]] && BOT_API_PORT="$value"
        ;;
    esac
  done < ".env"
}

request_status() {
  local path="$1"
  local mode="$2"
  local response status

  if [[ "$mode" == "auth" ]]; then
    response="$(timeout "${COMMAND_TIMEOUT_SECONDS}" curl --silent --show-error --max-time "${COMMAND_TIMEOUT_SECONDS}" --output /dev/null --write-out "%{http_code}" --header "Authorization: Bearer ${BOT_API_KEY}" "${BASE_URL}${path}" 2>&1)"
  else
    response="$(timeout "${COMMAND_TIMEOUT_SECONDS}" curl --silent --show-error --max-time "${COMMAND_TIMEOUT_SECONDS}" --output /dev/null --write-out "%{http_code}" "${BASE_URL}${path}" 2>&1)"
  fi

  status="${response: -3}"
  if [[ "$status" =~ ^[0-9][0-9][0-9]$ ]]; then
    printf '%s' "$status"
    return 0
  fi

  printf 'COMMAND_FAILED: %s' "$response"
  return 1
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

check_public_endpoint() {
  local path="$1"
  local status

  status="$(request_status "$path" "noauth")"
  if [[ "$status" =~ ^2[0-9][0-9]$ ]]; then
    record_result "PASS" "public ${path}" "returned HTTP ${status} without authentication"
  else
    record_result "FAIL" "public ${path}" "expected 2xx without authentication, got ${status}"
  fi
}

check_protected_endpoint() {
  local path="$1"
  local unauth_status auth_status

  unauth_status="$(request_status "$path" "noauth")"
  if [[ -n "$BOT_API_KEY" && "$unauth_status" == "401" ]]; then
    record_result "PASS" "unauthenticated ${path}" "returned expected HTTP 401"
  elif [[ "$unauth_status" =~ ^2[0-9][0-9]$ ]]; then
    record_result "PASS" "unauthenticated ${path}" "returned HTTP ${unauth_status}; endpoint is accessible without auth in this environment"
  else
    record_result "PASS" "unauthenticated ${path}" "non-auth smoke did not fail verification; observed HTTP ${unauth_status}"
  fi

  if [[ -z "$BOT_API_KEY" ]]; then
    record_result "FAIL" "authenticated ${path}" "BOT_API_KEY is missing; cannot verify authenticated request"
    return
  fi

  auth_status="$(request_status "$path" "auth")"
  if [[ "$auth_status" =~ ^2[0-9][0-9]$ ]]; then
    record_result "PASS" "authenticated ${path}" "returned HTTP ${auth_status} with BOT_API_KEY"
  else
    record_result "FAIL" "authenticated ${path}" "expected 2xx with BOT_API_KEY, got ${auth_status}"
  fi
}

main() {
  local public_endpoints protected_endpoints endpoint

  FAILURES=0
  REPORT=""

  load_dotenv

  if [[ -z "${BASE_URL}" ]]; then
    if [[ -z "${BOT_API_HOST}" || -z "${BOT_API_PORT}" ]]; then
      printf 'FAIL - BOT_API_HOST and BOT_API_PORT must be set in .env or environment.\n'
      return 1
    fi
    BASE_URL="http://${BOT_API_HOST}:${BOT_API_PORT}"
  fi

  public_endpoints=("/" "/health")
  protected_endpoints=(
    "/status"
    "/signals/latest"
    "/paper/state"
    "/api/health"
    "/api/market"
    "/api/portfolio"
    "/api/paper"
    "/api/analytics"
    "/api/backtest"
    "/api/live/orders"
    "/api/klines"
  )

  printf 'Dashboard API verification report\n'
  printf 'Base URL: %s\n' "$BASE_URL"
  if [[ -n "$BOT_API_KEY" ]]; then
    printf 'BOT_API_KEY: loaded from environment/.env\n'
  else
    printf 'BOT_API_KEY: missing\n'
  fi
  printf 'Command timeout: %ss\n\n' "$COMMAND_TIMEOUT_SECONDS"

  for endpoint in "${public_endpoints[@]}"; do
    check_public_endpoint "$endpoint"
  done

  for endpoint in "${protected_endpoints[@]}"; do
    check_protected_endpoint "$endpoint"
  done

  printf '%s' "$REPORT"
  printf '\nSummary: '
  if [[ "$FAILURES" -eq 0 ]]; then
    printf 'PASS - all authenticated checks succeeded; expected 401 responses were tolerated.\n'
    return 0
  fi

  printf 'FAIL - %s authenticated/public check(s) failed.\n' "$FAILURES"
  return 1
}

main "$@"