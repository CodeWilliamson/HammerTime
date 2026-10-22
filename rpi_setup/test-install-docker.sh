#!/usr/bin/env bash
#
# Try install.sh end-to-end in a throwaway Debian container (with systemd).
#
# Builds a small image (systemd + python3 + sudo + an unprivileged "pi" user),
# starts it with systemd as PID 1, copies *this working tree's* install.sh into
# it, runs a fresh install, and checks the result: systemd unit, app port,
# nginx on port 80, the /events SSE stream, and idempotency.
#
# Nothing in the container touches this repository, and the container is
# removed afterwards unless --keep is given. While it runs, nginx is published
# on http://localhost:8080/ so you can use the app in a browser.
#
# Usage: ./test-install-docker.sh [options] [-- install.sh options...]
#   --keep            Leave the container running for poking around
#   --tag TAG         Install that release (default: latest)
#   --dir PATH        App directory inside the container (default: /home/pi/HammerTime)
#   -h, --help        Show this help
#
# Requires Docker. Takes a few minutes the first time (image + pip download).
# HAMMERTIME_TEST_HTTP_PORT changes the published port (default 8080).

set -Eeuo pipefail

IMAGE="${HAMMERTIME_TEST_IMAGE:-hammertime-test:debian}"
NAME="${HAMMERTIME_TEST_NAME:-hammertime-test}"
HTTP_PORT="${HAMMERTIME_TEST_HTTP_PORT:-8080}"
APP_DIR="/home/pi/HammerTime"
TAG=""
KEEP=0
PASSTHRU=()

info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
bad()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --keep)  KEEP=1; shift ;;
    --tag)   TAG="${2:?--tag needs a release tag}"; shift 2 ;;
    --dir)   APP_DIR="${2:?--dir needs a path}"; shift 2 ;;
    -h|--help)
      awk 'NR > 1 { if (/^#/) { sub(/^# ?/, ""); print } else exit }' "${BASH_SOURCE[0]}"
      exit 0 ;;
    --)      shift; PASSTHRU=("$@"); break ;;
    *)       die "Unknown option: $1 (try --help)" ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$ROOT/install.sh" ] || die "No install.sh next to this script ($ROOT)."
command -v docker >/dev/null 2>&1 || die "Docker is required."

# Verify* functions count results so the script can fail at the end.
PASS=0
FAIL=0
check() {  # check "description" <command...>
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$label"; PASS=$((PASS + 1));
  else bad "$label"; FAIL=$((FAIL + 1)); fi
}

cleanup() {
  if [ "$KEEP" = "0" ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- container

info "Building the test image ($IMAGE)"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker build -q -t "$IMAGE" - <<'DOCKERFILE' >/dev/null
FROM debian:bookworm
ENV DEBIAN_FRONTEND=noninteractive container=docker
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
      systemd systemd-sysv sudo python3 python3-venv ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
# The unprivileged user install.sh expects to be run as (its systemd unit User=).
RUN useradd -m -s /bin/bash pi \
 && echo 'pi ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/pi \
 && chmod 440 /etc/sudoers.d/pi
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
DOCKERFILE
ok "Image ready"

info "Starting the container"
docker run -d --name "$NAME" --hostname hammertime \
  --privileged --tmpfs /run --tmpfs /run/lock \
  -p "$HTTP_PORT:80" \
  "$IMAGE" >/dev/null
ok "Started $NAME (nginx on http://localhost:$HTTP_PORT/)"

# systemd is PID 1 now; give it a moment to finish bringing itself up.
for _ in $(seq 1 30); do
  state="$(docker exec "$NAME" systemctl is-system-running 2>/dev/null || true)"
  case "$state" in
    running|degraded) break ;;
  esac
  sleep 1
done
[ "${state:-}" = "running" ] || [ "${state:-}" = "degraded" ] \
  || die "systemd did not come up in the container (state: ${state:-unknown}). Try a Docker engine that allows --privileged."
ok "systemd is ${state}"

docker cp "$ROOT/install.sh" "$NAME:/home/pi/install.sh"
docker exec "$NAME" chown pi:pi /home/pi/install.sh
docker exec "$NAME" chmod +x /home/pi/install.sh

# Everything below runs as the normal user, exactly like on the Pi.
as_pi() { docker exec -u pi -w /home/pi -e HOME=/home/pi "$NAME" "$@"; }

# ---------------------------------------------------------------- install

info "Fresh install (as pi, unprivileged)"
install_args=(--dir "$APP_DIR")
[ -n "$TAG" ] && install_args+=(--tag "$TAG")
if as_pi ./install.sh "${install_args[@]}" ${PASSTHRU[@]+"${PASSTHRU[@]}"}; then
  ok "install.sh completed"
else
  bad "install.sh failed"; FAIL=$((FAIL + 1))
fi

# ---------------------------------------------------------------- checks

info "Checks"

check "systemd unit is active"  docker exec "$NAME" systemctl is-active --quiet hammertime.service
check "app answers on :3000"    docker exec "$NAME" curl -fsS --max-time 5 http://127.0.0.1:3000/api/version
check "nginx answers on :80"    docker exec "$NAME" curl -fsS --max-time 5 http://127.0.0.1/api/version
check "kiosk page loads"        docker exec "$NAME" curl -fsS --max-time 5 http://127.0.0.1/
check "nginx config is valid"   docker exec "$NAME" nginx -t
check "default site disabled"   docker exec -u pi "$NAME" test ! -e /etc/nginx/sites-enabled/default
check "second run reports up to date" \
  docker exec -u pi -w /home/pi "$NAME" ./install.sh --dir "$APP_DIR" --check

# The checks above only prove file contents / exit codes; assert the specific
# directive that keeps the kiosk alive.
if docker exec "$NAME" nginx -T 2>/dev/null | grep -q 'proxy_buffering off'; then
  ok "proxy_buffering is off for /events"; PASS=$((PASS + 1))
else
  bad "proxy_buffering is off for /events"; FAIL=$((FAIL + 1))
fi

info "SSE through nginx"
sse="$(docker exec "$NAME" curl -sN --max-time 8 -w '\nTTFB=%{time_starttransfer}\n' \
        http://127.0.0.1/events 2>/dev/null || true)"
if printf '%s' "$sse" | grep -q '^event: hello'; then
  ok "hello snapshot: $(printf '%s' "$sse" | grep -m1 '^TTFB=')"
  PASS=$((PASS + 1))
else
  bad "no 'event: hello' from http://127.0.0.1/events"; FAIL=$((FAIL + 1))
fi
if printf '%s' "$sse" | grep -q '"timer_state"'; then
  ok "snapshot carries timer_state"; PASS=$((PASS + 1))
else
  bad "snapshot is missing timer_state"; FAIL=$((FAIL + 1))
fi

# ---------------------------------------------------------------- summary

info "Summary"
docker exec -u pi -w /home/pi "$NAME" cat "$APP_DIR/.release" 2>/dev/null || true
docker exec "$NAME" /usr/sbin/nginx -v 2>&1 || true
printf '\n  App: http://localhost:%s/   (admin: http://localhost:%s/admin)\n' "$HTTP_PORT" "$HTTP_PORT"
printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  warn "Container left behind for inspection: docker exec -it -u pi $NAME bash"
  KEEP=1
  exit 1
fi
printf '\033[1;32mInstall script works.\033[0m\n'
