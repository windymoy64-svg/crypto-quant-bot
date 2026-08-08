#!/usr/bin/env bash
# Deploy helper for the crypto-quant-bot VPS.
#
# Safe pull-only deployment:
# - Pulls the latest main from GitHub (fast-forward only).
# - Installs Python dependencies only when requirements*.txt change.
# - ALWAYS restarts both systemd services after a successful pull.
# - Never pushes, never force-resets, never touches local data.
#
# Usage:
#   ./deploy_vps.sh            # deploy + verify
#   ./deploy_vps.sh --dry-run  # simulate without pull/restart
#   DEPLOY_DIR=/opt/crypto-quant-bot ./deploy_vps.sh

set -Eeuo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/crypto-quant-bot}"
SERVICE_SCANNER="crypto-quant-bot"
SERVICE_API="crypto-quant-bot-api"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

export_dir() {
  local dir="$1"
  echo "== Directory: ${dir}"
  if [[ ! -d "$dir" ]]; then
    echo "FAIL: directory ${dir} does not exist."
    exit 1
  fi
  cd "$dir"
  if [[ ! -d .git ]]; then
    echo "FAIL: ${dir} is not a git repository."
    exit 1
  fi
}

check_remote() {
  echo "== Remote"
  if ! git remote get-url origin >/dev/null 2>&1; then
    echo "FAIL: no git remote 'origin' configured. Run: git remote add origin <repo-url>"
    exit 1
  fi
  git remote -v | head -2
}

check_clean_tree() {
  echo "== Working tree"
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "FAIL: local changes found. Stash, commit, or move them before deploying."
    echo "      VPS is pull-only; do NOT commit/push from here."
    git status --short
    exit 1
  fi
  echo "OK: working tree is clean."
}

update_dependencies() {
  local old_head="$1"
  local diff_files
  diff_files="$(git diff --name-only "$old_head" HEAD || true)"
  if echo "$diff_files" | grep -q '^requirements.*\.txt$'; then
    echo "== Dependencies: requirements changed -> updating"
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "(dry-run) skip: pip install -r requirements.txt"
      return 0
    fi
    ./.venv/bin/pip install -r requirements.txt
  else
    echo "== Dependencies: unchanged, skipping pip install"
  fi
}

restart_services() {
  echo "== Restart services"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "(dry-run) skip: systemctl restart ${SERVICE_SCANNER} ${SERVICE_API}"
    return 0
  fi
  systemctl restart "$SERVICE_SCANNER" "$SERVICE_API"
  echo "OK: services restarted."
}

verify_services() {
  echo "== Service status"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "(dry-run) skip: systemctl is-active checks"
    return 0
  fi
  local scanner_status api_status
  scanner_status="$(systemctl is-active "$SERVICE_SCANNER" 2>/dev/null || echo inactive)"
  api_status="$(systemctl is-active "$SERVICE_API" 2>/dev/null || echo inactive)"
  echo "${SERVICE_SCANNER}: ${scanner_status}"
  echo "${SERVICE_API}: ${api_status}"
  if [[ "$scanner_status" != "active" || "$api_status" != "active" ]]; then
    echo "FAIL: one or more services are not active."
    exit 1
  fi
  echo "OK: both services active."
}

run_health_check() {
  echo "== Health check"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "(dry-run) skip: ./check_production_health.sh"
    return 0
  fi
  if [[ ! -x ./check_production_health.sh ]]; then
    chmod +x ./check_production_health.sh
  fi
  ./check_production_health.sh
}

need_pull() {
  git rev-list --count HEAD..origin/main 2>/dev/null || echo 0
}

main() {
  export_dir "$DEPLOY_DIR"
  check_remote

  echo "== Fetch"
  git fetch origin

  local pending
  pending="$(need_pull)"
  if [[ "$pending" -eq 0 ]]; then
    echo "Already up to date with origin/main."
    verify_services
    run_health_check
    echo "PASS: deployment complete (no changes)."
    return 0
  fi
  echo "Pending commits: ${pending}"

  check_clean_tree

  local before_head
  before_head="$(git rev-parse HEAD)"

  echo "== Pull"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "(dry-run) skip: git pull --ff-only origin main"
  else
    git pull --ff-only origin main
    echo "OK: fast-forward pull completed."
  fi

  if [[ "$DRY_RUN" != "1" ]]; then
    local after_head
    after_head="$(git rev-parse HEAD)"
    if [[ "$after_head" == "$before_head" ]]; then
      echo "No new commits applied."
      return 0
    fi
  fi

  # Run dependency + restart + verify either way (dry-run prints skip lines).
  update_dependencies "$before_head"
  restart_services
  verify_services
  run_health_check

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "== Dry-run complete: no changes were made."
  else
    echo "== Deployment complete."
  fi
}

main "$@"