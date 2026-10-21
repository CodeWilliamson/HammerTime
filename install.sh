#!/usr/bin/env bash
#
# HammerTime installer / upgrader for Raspberry Pi (Debian / Raspberry Pi OS).
#
# Installs from a published GitHub release (a release tarball), not from a git clone.
# Running it again compares the installed release with the latest published one and only
# downloads when there is something new; everything else is idempotent.
#
# Fresh install:   curl -fsSL https://raw.githubusercontent.com/CodeWilliamson/HammerTime/main/install.sh | bash
# Upgrade:         ./install.sh            (or re-run the curl line above)
# Check only:      ./install.sh --check    (exit 0 = up to date)
#
# What it does, in order:
#   1. checks Python >= 3.11, tar and the venv module (apt-installs what is missing)
#   2. asks GitHub for the latest release and compares it with the installed release
#   3. if it is newer (or nothing is installed): downloads the release tarball and swaps
#      the app tree, keeping data/, .env and .venv
#   4. creates/refreshes .venv and installs requirements.txt
#   5. creates .env with a random JWT_SECRET if it does not exist yet
#   6. backs up data/schedule.db, then applies pending SQL migrations
#   7. installs the systemd unit and (re)starts the service
#   8. waits for http://127.0.0.1:<port>/api/version to answer
#
# The installed release is recorded in <dir>/.release. data/ (the club's schedule
# database) and .env are preserved and never rewritten by an upgrade.
# The kiosk browser unit is NOT touched — see rpi-config-starter/.
#
# Usage: ./install.sh [options]
#   --dir PATH        Install directory                      (default: this install, else ~/HammerTime)
#   --repo OWNER/NAME GitHub repository to install from      (default: CodeWilliamson/HammerTime)
#   --tag TAG         Install this release/tag instead of the latest one
#   --port N          Port for the server                    (default: 3000, or PORT from .env)
#   --service NAME    systemd unit name                      (default: curling-timer.service)
#   --token TOKEN     GitHub token, for private repos / rate limits
#   --check           Report whether an update is available and exit (0 = up to date, 10 = update available)
#   --force           Reinstall even if up to date (also allows a downgrade)
#   --no-restart      Update files and migrations but leave the service running
#   -h, --help        Show this help
#
# Any option can also be set as an environment variable: HAMMERTIME_DIR, HAMMERTIME_REPO,
# HAMMERTIME_TAG, HAMMERTIME_PORT, HAMMERTIME_SERVICE_NAME, HAMMERTIME_GITHUB_TOKEN,
# HAMMERTIME_FORCE.
#
# Requires sudo (or run as root). Run it as the user that should own the files —
# `sudo ./install.sh` is detected and runs the app steps as $SUDO_USER instead.

set -Eeuo pipefail

info()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; trap - ERR; exit 1; }

trap 'printf "\033[1;31m  ✗ install.sh failed at line %s\033[0m\n" "$LINENO" >&2' ERR

# ---------------------------------------------------------------- configuration

PROJECT="${HAMMERTIME_REPO:-CodeWilliamson/HammerTime}"
TAG="${HAMMERTIME_TAG:-}"
API_BASE="${HAMMERTIME_API_BASE:-https://api.github.com}"
TOKEN="${HAMMERTIME_GITHUB_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"
SERVICE_NAME="${HAMMERTIME_SERVICE_NAME:-hammertime.service}"
PORT="${HAMMERTIME_PORT:-3000}"
APP_DIR="${HAMMERTIME_DIR:-}"
FORCE="${HAMMERTIME_FORCE:-0}"
RESTART=1
CHECK_ONLY=0
PYTHON_BIN="${HAMMERTIME_PYTHON:-python3}"
STAGING=""
cleanup() { if [ -n "$STAGING" ]; then rm -rf "$STAGING"; fi; }
trap cleanup EXIT

# ---------------------------------------------------------------- argument parsing

SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)        APP_DIR="${2:?--dir needs a path}"; shift 2 ;;
    --repo)       PROJECT="${2:?--repo needs OWNER/NAME}"; shift 2 ;;
    --tag)        TAG="${2:?--tag needs a release tag}"; shift 2 ;;
    --port)       PORT="${2:?--port needs a number}"; shift 2 ;;
    --service)    SERVICE_NAME="${2:?--service needs a name}"; shift 2 ;;
    --token)      TOKEN="${2:?--token needs a value}"; shift 2 ;;
    --check)      CHECK_ONLY=1; shift ;;
    --force)      FORCE=1; shift ;;
    --no-restart) RESTART=0; shift ;;
    -h|--help)
      if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/install.sh" ]; then
        # Print the leading comment block (everything after the shebang).
        awk 'NR > 1 { if (/^#/) { sub(/^# ?/, ""); print } else exit }' "$SCRIPT_DIR/install.sh"
      else
        echo "HammerTime installer. Options: --dir PATH --repo OWNER/NAME --tag TAG --port N --service NAME --token TOKEN --check --force --no-restart"
      fi
      exit 0 ;;
    *)            die "Unknown option: $1 (try --help)" ;;
  esac
done

case "$PROJECT" in
  */*/*|/*|*/|"") die "--repo must look like OWNER/NAME (got '$PROJECT')" ;;
  */*) : ;;
  *)   die "--repo must look like OWNER/NAME (got '$PROJECT')" ;;
esac

# ---------------------------------------------------------------- privilege helpers

if [ "$(id -u)" -eq 0 ]; then
  APP_USER="${HAMMERTIME_USER:-${SUDO_USER:-}}"
  if [ -z "$APP_USER" ] || [ "$APP_USER" = "root" ]; then
    die "Run this as the normal login user (e.g. 'sudo ./install.sh' from the pi account), not as root directly."
  fi
  as_root() { "$@"; }
else
  APP_USER="$(id -un)"
  command -v sudo >/dev/null 2>&1 || die "sudo is required to install the systemd unit."
  as_root() { sudo "$@"; }
fi
APP_GROUP="$(id -gn "$APP_USER" 2>/dev/null || echo "$APP_USER")"

# Run application-level commands (pip, migrations) as the owning user.
as_user() {
  if [ "$(id -u)" -eq 0 ]; then sudo -u "$APP_USER" -H "$@"; else "$@"; fi
}

# Files we touched may belong to root when this script is run under sudo.
fix_ownership() {
  if [ "$(id -u)" -eq 0 ]; then chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"; fi
}

# Default location: the install this script lives in, otherwise <app user's home>/HammerTime.
if [ -z "$APP_DIR" ]; then
  if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/hammertime/__init__.py" ]; then
    APP_DIR="$SCRIPT_DIR"
  else
    app_home="$(getent passwd "$APP_USER" 2>/dev/null | cut -d: -f6)"
    APP_DIR="${app_home:-$HOME}/HammerTime"
  fi
fi

# ---------------------------------------------------------------- 1. preflight

info "Checking prerequisites"

if [ "$(uname -s)" != "Linux" ]; then
  warn "Not Linux — this script targets Raspberry Pi OS; continuing anyway."
fi

missing_pkgs=()
command -v tar >/dev/null 2>&1 || missing_pkgs+=("tar")
command -v "$PYTHON_BIN" >/dev/null 2>&1 || missing_pkgs+=("python3")

if [ "${#missing_pkgs[@]}" -gt 0 ]; then
  if command -v apt-get >/dev/null 2>&1; then
    ok "Installing: ${missing_pkgs[*]}"
    as_root apt-get update -qq
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing_pkgs[@]}"
  else
    die "Missing required commands: ${missing_pkgs[*]}"
  fi
fi

"$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ is required, found $("$PYTHON_BIN" -V 2>&1). Try 'sudo apt-get install python3' (Raspberry Pi OS Bookworm or newer)."
ok "$("$PYTHON_BIN" -V 2>&1)"

# The venv module ships in python3-venv on Debian; add it if the import fails.
if ! "$PYTHON_BIN" -c 'import venv, ensurepip' >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    ok "Installing python3-venv"
    as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-venv
  else
    die "The Python venv module is missing (install python3-venv)."
  fi
fi
ok "venv module available"

# ---------------------------------------------------------------- 2. which release

# Query GitHub for a release and cache its metadata as plain files in $1:
# tag, name, published, url, body, tarball, source (release|tag). Prints the tag.
github_release() {  # github_release resolve|download <workdir>
  "$PYTHON_BIN" - "$1" "$2" "$PROJECT" "$TAG" "$API_BASE" "$TOKEN" <<'PY'
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

mode, workdir, project, tag, api_base, token = sys.argv[1:7]
token = token.strip()

HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "hammertime-install"}


def request(url, accept=None):
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept
    if token:
        headers["Authorization"] = "Bearer " + token
    return urllib.request.Request(url, headers=headers)


def fail(message):
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(1)


def version_key(version):
    """Semver-ish ordering that matches hammertime.migrate.compare_semver."""
    core, _, pre = version.strip().lstrip("vV").partition("-")
    numbers = [int(part) for part in re.findall(r"\d+", core)][:3]
    if not numbers:
        return None
    numbers += [0] * (3 - len(numbers))
    return numbers, 0 if pre else 1, pre


def api_get(url):
    try:
        with urllib.request.urlopen(request(url), timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (401, 403):
            fail(f"GitHub refused the request ({error.code}). Set HAMMERTIME_GITHUB_TOKEN for private repos or to avoid rate limits.")
        fail(f"GitHub API error {error.code}: {error.reason}")
    except urllib.error.URLError as error:
        fail(f"Cannot reach the GitHub API ({error.reason}).")
    return None


def write(fields):
    os.makedirs(workdir, exist_ok=True)
    for name, value in fields.items():
        with open(os.path.join(workdir, name), "w", encoding="utf-8") as handle:
            handle.write(value or "")


def resolve():
    if tag:
        release = api_get(f"{api_base}/repos/{project}/releases/tags/{urllib.parse.quote(tag)}")
        if release:
            write({
                "tag": release["tag_name"],
                "name": release.get("name") or release["tag_name"],
                "published": release.get("published_at") or "",
                "url": release.get("html_url") or "",
                "body": release.get("body") or "",
                "tarball": release.get("tarball_url") or f"{api_base}/repos/{project}/tarball/{release['tag_name']}",
                "source": "release",
            })
            return
        # Allow --tag to name a plain git tag that has no published release.
        if not api_get(f"{api_base}/repos/{project}/git/refs/tags/{urllib.parse.quote(tag)}"):
            fail(f"No release or tag '{tag}' found in {project}.")
        write({
            "tag": tag,
            "name": tag,
            "published": "",
            "url": f"https://github.com/{project}/releases/tag/{tag}",
            "body": "",
            "tarball": f"{api_base}/repos/{project}/tarball/{tag}",
            "source": "tag",
        })
        return

    release = api_get(f"{api_base}/repos/{project}/releases/latest")
    if release:
        write({
            "tag": release["tag_name"],
            "name": release.get("name") or release["tag_name"],
            "published": release.get("published_at") or "",
            "url": release.get("html_url") or "",
            "body": release.get("body") or "",
            "tarball": release.get("tarball_url") or f"{api_base}/repos/{project}/tarball/{release['tag_name']}",
            "source": "release",
        })
        return

    # No published releases yet: fall back to the highest tag on the repository.
    tags = api_get(f"{api_base}/repos/{project}/tags?per_page=100") or []
    best, best_key = None, None
    for candidate in tags:
        key = version_key(candidate.get("name", ""))
        if key is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = candidate["name"], key
    if not best:
        fail(f"{project} has no published releases and no semver tags to install from.\nPublish a release on GitHub, then run this again.")
    write({
        "tag": best,
        "name": best,
        "published": "",
        "url": f"https://github.com/{project}/releases/tag/{best}",
        "body": "",
        "tarball": f"{api_base}/repos/{project}/tarball/{best}",
        "source": "tag",
    })


def download():
    with open(os.path.join(workdir, "tarball"), encoding="utf-8") as handle:
        url = handle.read().strip()
    destination = os.path.join(workdir, "release.tar.gz")
    try:
        with urllib.request.urlopen(request(url, accept="application/octet-stream"), timeout=180) as response:
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
    except urllib.error.HTTPError as error:
        fail(f"Download failed ({error.code} {error.reason}).")
    except urllib.error.URLError as error:
        fail(f"Download failed ({error.reason}).")
    if os.path.getsize(destination) == 0:
        fail("Downloaded archive is empty.")
    print(destination)


try:
    {"resolve": resolve, "download": download}[mode]()
except SystemExit:
    raise
except Exception as error:  # flaky wifi, TLS errors, truncated reads, ...
    fail(f"Unexpected error talking to GitHub: {error}")
PY
}

# version_compare A B -> prints -1, 0 or 1 (semver-ish, falls back to string equality)
version_compare() {
  "$PYTHON_BIN" -c '
import re, sys

def key(version):
    core, _, pre = version.strip().lstrip("vV").partition("-")
    numbers = [int(part) for part in re.findall(r"\d+", core)][:3]
    if not numbers:
        return None
    numbers += [0] * (3 - len(numbers))
    return numbers, 0 if pre else 1, pre

left, right = key(sys.argv[1]), key(sys.argv[2])
if left is None or right is None:
    print(0 if sys.argv[1].strip() == sys.argv[2].strip() else 1)
else:
    print(0 if left == right else (-1 if left < right else 1))' "$1" "$2"
}

# The release recorded by a previous run (.release), else __version__ from a git checkout.
installed_tag() {
  local recorded=""
  if [ -f "$APP_DIR/.release" ]; then
    recorded="$(sed -n 's/^TAG=//p' "$APP_DIR/.release" | tail -n 1)"
  fi
  if [ -z "$recorded" ] && [ -f "$APP_DIR/hammertime/__init__.py" ]; then
    recorded="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP_DIR/hammertime/__init__.py" | tail -n 1)"
  fi
  printf '%s' "$recorded"
}

info "Checking $PROJECT for releases"

META="$(mktemp -d)"
STAGING="$META"
if ! github_release resolve "$META"; then
  rm -rf "$META"; STAGING=""
  die "Could not determine the latest release of $PROJECT (see the message above)."
fi
latest_tag="$(cat "$META/tag")"
latest_name="$(cat "$META/name")"
latest_published="$(cat "$META/published")"
release_source="$(cat "$META/source")"

if [ "$release_source" = "tag" ]; then
  warn "No published GitHub release — using the newest tag $latest_tag"
fi
ok "Latest: $latest_tag${latest_published:+  (published ${latest_published%%T*})}"

current_tag="$(installed_tag)"
if [ -n "$current_tag" ]; then
  ok "Installed: $current_tag"
else
  ok "Installed: nothing"
fi

needs_install=1
comparison=1
if [ -n "$current_tag" ]; then
  comparison="$(version_compare "$current_tag" "$latest_tag")"
  case "$comparison" in
    0) needs_install=0; ok "Already on the latest release" ;;
    -1) needs_install=1 ;;
    1)
      if [ "$FORCE" = "1" ]; then
        needs_install=1
        warn "$current_tag is newer than $latest_tag — downgrading because of --force"
      else
        needs_install=0
        warn "$current_tag is newer than the latest release ($latest_tag) — nothing to do. Use --force to downgrade."
      fi ;;
  esac
fi
if [ "$FORCE" = "1" ]; then needs_install=1; fi

if [ "$CHECK_ONLY" = "1" ]; then
  rm -rf "$META"; STAGING=""
  if [ "$needs_install" = "1" ]; then
    printf '\nUpdate available: %s → %s\n' "${current_tag:-none}" "$latest_tag"
    exit 10
  fi
  printf '\nUp to date (%s).\n' "$latest_tag"
  exit 0
fi

# ---------------------------------------------------------------- 3. install the release

if [ "$needs_install" = "1" ]; then
  if [ -n "$current_tag" ] && [ "$comparison" = "0" ]; then
    info "Reinstalling $latest_tag"
  elif [ -n "$current_tag" ]; then
    info "Updating $current_tag → $latest_tag"
  else
    info "Installing $latest_tag"
  fi

  # Never replace a directory that is not a HammerTime install (a half-finished swap
  # - only data/, .env, .venv - is fine and gets repaired).
  if [ -d "$APP_DIR" ]; then
    foreign="$(find "$APP_DIR" -mindepth 1 -maxdepth 1 \
      ! -name data ! -name .venv ! -name .env ! -name .release -print -quit)"
    if [ -n "$foreign" ] && [ ! -f "$APP_DIR/hammertime/__init__.py" ]; then
      die "$APP_DIR is not empty and does not look like a HammerTime install (found $foreign). Move it aside or pass --dir."
    fi
  fi
  if [ -d "$APP_DIR/.git" ]; then
    warn "Replacing the old git checkout with release files (data/, .env and .venv are kept)"
  fi

  ok "Downloading release archive"
  github_release download "$META" > /dev/null || die "Could not download the release archive."

  mkdir -p "$META/tree"
  tar -xzf "$META/release.tar.gz" -C "$META/tree" --strip-components=1 \
    || die "Could not unpack the release archive."
  if [ ! -f "$META/tree/hammertime/__init__.py" ] || [ ! -f "$META/tree/requirements.txt" ]; then
    die "The release archive does not look like HammerTime (missing hammertime/ or requirements.txt)."
  fi

  mkdir -p "$APP_DIR"
  # Swap the application tree, keeping the club's data, secrets and the virtualenv.
  find "$APP_DIR" -mindepth 1 -maxdepth 1 \
    ! -name data ! -name .venv ! -name .env -exec rm -rf {} +
  cp -a "$META/tree/." "$APP_DIR/"

  {
    echo "# Written by install.sh — the release this directory was installed from."
    echo "TAG=$latest_tag"
    echo "PROJECT=$PROJECT"
    echo "INSTALLED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  } > "$APP_DIR/.release"

  fix_ownership
  ok "Installed $latest_tag"

  release_body="$(cat "$META/body" 2>/dev/null || true)"
  if [ -n "$release_body" ] && [ -n "$current_tag" ]; then
    info "What changed in $latest_name"
    printf '%s\n' "$release_body" | head -n 20 | sed 's/^/    /'
  fi
elif [ "$comparison" = "0" ] && [ ! -f "$APP_DIR/.release" ]; then
  # Adopted release matches this install (e.g. an older git-based install): record it.
  {
    echo "# Written by install.sh — the release this directory was installed from."
    echo "TAG=$latest_tag"
    echo "PROJECT=$PROJECT"
    echo "INSTALLED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  } > "$APP_DIR/.release"
fi

cd "$APP_DIR"
rm -rf "$META"; STAGING=""

new_version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' hammertime/__init__.py || true)"
if [ -z "$new_version" ]; then
  die "Could not read __version__ from $APP_DIR/hammertime/__init__.py — is $APP_DIR the right directory?"
fi
ok "Version $new_version"

# ---------------------------------------------------------------- 4. virtualenv

info "Installing Python dependencies into .venv"

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  as_user "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
  ok "Created .venv"
fi

VENV_PY="$APP_DIR/.venv/bin/python"
as_user "$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade pip

if ! as_user "$VENV_PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt; then
  die "pip install failed. On 32-bit Raspberry Pi OS, 'bcrypt' has no prebuilt wheel — install the build tools (sudo apt-get install -y build-essential python3-dev libffi-dev && curl https://sh.rustup.rs -sSf | sh) or switch to 64-bit Raspberry Pi OS."
fi
ok "Dependencies installed"

# ---------------------------------------------------------------- 5. configuration

info "Configuration (.env)"

env_value() {  # env_value KEY DEFAULT -> value of KEY in .env, else DEFAULT
  local key="$1" default="$2" value=""
  if [ -f .env ]; then
    value="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" .env | tail -n 1 | cut -d= -f2- | tr -d '[:space:]' | tr -d '"' | tr -d "'")"
  fi
  printf '%s' "${value:-$default}"
}

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    "$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(32))'
  fi
}

if [ ! -f .env ]; then
  warn "No .env found — creating one with a new random JWT_SECRET (existing logins will need to log in again)"
  {
    echo "# Created by install.sh on $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "PORT=$PORT"
    echo "JWT_SECRET=$(generate_secret)"
    echo "# DEBUG=1"
  } > .env
  chmod 600 .env
elif ! grep -qE '^[[:space:]]*JWT_SECRET[[:space:]]*=' .env; then
  warn "Adding a random JWT_SECRET to .env"
  printf '\nJWT_SECRET=%s\n' "$(generate_secret)" >> .env
fi

requested_port="$PORT"
PORT="$(env_value PORT "$PORT")"
if [ "$PORT" != "$requested_port" ]; then
  warn "Using PORT=$PORT from .env (requested $requested_port). Edit $APP_DIR/.env to change it."
fi
ok "Port $PORT"

fix_ownership

# ---------------------------------------------------------------- 6. database

info "Database"

mkdir -p data
if [ -f data/schedule.db ]; then
  mkdir -p data/backups
  backup="data/backups/schedule-$(date +%Y%m%d-%H%M%S).db"
  # A read-only sqlite3 backup is consistent even while the service is running.
  as_user "$VENV_PY" -c 'import sqlite3, sys
s = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
d = sqlite3.connect(sys.argv[2])
with d:
    s.backup(d)
d.close(); s.close()' data/schedule.db "$backup"
  ok "Backed up to $backup"

  # Keep the last 10 backups; they are tiny.
  as_user bash -c 'ls -1t data/backups/schedule-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f'
else
  ok "No database yet — a fresh one will be created"
fi

if [ "$(id -u)" -eq 0 ]; then chown -R "$APP_USER:$APP_GROUP" data; fi

ok "Applying migrations"
as_user "$VENV_PY" -m hammertime.migrate

# ---------------------------------------------------------------- 7. systemd

info "systemd unit $SERVICE_NAME"

UNIT_FILE="/etc/systemd/system/$SERVICE_NAME"
unit_contents="[Unit]
Description=HammerTime curling rink draw timer
Documentation=file://$APP_DIR/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m hammertime
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target"

if ! as_root test -f "$UNIT_FILE" || [ "$(as_root cat "$UNIT_FILE" 2>/dev/null || true)" != "$unit_contents" ]; then
  tmp_unit="$(mktemp)"
  printf '%s\n' "$unit_contents" > "$tmp_unit"
  as_root install -m 0644 "$tmp_unit" "$UNIT_FILE"
  rm -f "$tmp_unit"
  as_root systemctl daemon-reload
  ok "Installed $UNIT_FILE"
else
  ok "Unit unchanged"
fi

as_root systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true

if [ "$RESTART" = "1" ]; then
  ok "Restarting $SERVICE_NAME"
  as_root systemctl restart "$SERVICE_NAME"
else
  warn "Not restarting (--no-restart); run: sudo systemctl restart $SERVICE_NAME"
fi

# ---------------------------------------------------------------- 8. health check

if [ "$RESTART" = "1" ]; then
  info "Waiting for the server on port $PORT"
  healthy=0
  for _ in $(seq 1 30); do
    if "$VENV_PY" -c 'import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)' "http://127.0.0.1:$PORT/api/version"; then
      healthy=1
      break
    fi
    sleep 1
  done

  if [ "$healthy" = "1" ]; then
    ok "Server is up"
  else
    warn "No response from http://127.0.0.1:$PORT — inspect the logs:"
    echo "      sudo journalctl -u $SERVICE_NAME -n 50 --no-pager"
  fi
fi

# ---------------------------------------------------------------- done

host_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
printf '\n\033[1;32mHammerTime %s is installed.\033[0m\n' "$new_version"
printf '  Release : %s (%s)\n' "$latest_tag" "$PROJECT"
printf '  Display : http://%s:%s/\n' "${host_ip:-localhost}" "$PORT"
printf '  Admin   : http://%s:%s/admin   (default login: timer / timer — change it)\n' "${host_ip:-localhost}" "$PORT"
printf '  Service : %s  (logs: sudo journalctl -u %s -f)\n' "$SERVICE_NAME" "$SERVICE_NAME"
printf '  Code    : %s\n' "$APP_DIR"
printf '  Data    : %s/data/schedule.db  (backups in data/backups/)\n\n' "$APP_DIR"
