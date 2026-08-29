#!/usr/bin/env bash
# Wait until the lab is genuinely ready to demonstrate.
#
# `docker compose up -d` returns as soon as containers start. The control API is
# ready seconds later, but on a cold build Reflex still has to compile the
# dashboard frontend, which can take minutes. Without this you cannot tell a
# still-building dashboard from a broken one.
#
#   scripts/wait_for_lab.sh              # wait for the control API and the dashboard
#   scripts/wait_for_lab.sh --api-only   # wait only for the control API (CI)
set -uo pipefail

CONTROL_URL="${CONTROL_URL:-http://localhost:8053/health}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
API_TIMEOUT="${API_TIMEOUT:-120}"
DASHBOARD_TIMEOUT="${DASHBOARD_TIMEOUT:-600}"
API_ONLY=0
[ "${1:-}" = "--api-only" ] && API_ONLY=1

bold=$(printf '\033[1m'); dim=$(printf '\033[2m'); green=$(printf '\033[32m')
red=$(printf '\033[31m'); reset=$(printf '\033[0m')

wait_for() {
  local label="$1" url="$2" timeout="$3" hint="$4"
  local started elapsed
  started=$(date +%s)
  printf '%s' "  waiting for ${label}... "
  while true; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      elapsed=$(( $(date +%s) - started ))
      printf '%sready%s %s(%ss)%s\n' "$green" "$reset" "$dim" "$elapsed" "$reset"
      return 0
    fi
    elapsed=$(( $(date +%s) - started ))
    if [ "$elapsed" -ge "$timeout" ]; then
      printf '%snot ready after %ss%s\n' "$red" "$elapsed" "$reset"
      printf '    %s\n' "$hint"
      printf '    inspect with: %smake logs%s\n' "$bold" "$reset"
      return 1
    fi
    if [ $(( elapsed % 15 )) -eq 0 ] && [ "$elapsed" -gt 0 ]; then
      printf '%s%ss%s ' "$dim" "$elapsed" "$reset"
    fi
    sleep 1
  done
}

printf '%sChecking the lab%s\n' "$bold" "$reset"

wait_for "DNS control API" "$CONTROL_URL" "$API_TIMEOUT" \
  "The dns-manager container did not start. Check it built and that port 8053 is free." || exit 1

if [ "$API_ONLY" -eq 1 ]; then
  printf '%sControl API ready.%s\n' "$green" "$reset"
  exit 0
fi

printf '  %sthe dashboard compiles its frontend on a cold build; the first start takes minutes%s\n' \
  "$dim" "$reset"
wait_for "Reflex dashboard" "$DASHBOARD_URL" "$DASHBOARD_TIMEOUT" \
  "Still not serving. The frontend build may have failed." || exit 1

printf '\n%sLab is ready.%s\n' "$green" "$reset"
printf '  Dashboard   %s\n' "$DASHBOARD_URL"
printf '  Control API %s %s(bearer protected)%s\n' "http://localhost:8053" "$dim" "$reset"
