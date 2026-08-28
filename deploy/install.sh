#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
MODE=""
SERVICE_NAME="moyu-tg-relay"
INSTALL_DIR="/opt/moyu-tg-relay"
STATE_DIR="/var/lib/moyu-tg-relay"
SYSTEMD_ENV="/etc/moyu-tg-relay.env"
LOCAL_URL="http://127.0.0.1:8787"

log() {
  printf '[moyu-tg-relay] %s\n' "$*"
}

warn() {
  printf '[moyu-tg-relay] WARN: %s\n' "$*" >&2
}

die() {
  printf '[moyu-tg-relay] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Moyu Telegram Relay guided deployment

Usage:
  ./deploy/install.sh [docker|systemd]

Modes:
  docker    Docker Compose deployment (recommended when Docker is available)
  systemd   Native Linux systemd deployment

The wizard will:
  1. collect/validate Telegram API credentials
  2. generate a strong Relay Bearer token when missing
  3. bootstrap the Telegram session interactively
  4. capture and persist TELEGRAM_ACCOUNT_ID automatically
  5. start the service and run the full readiness/auth smoke check

It never uploads the Telethon session or Telegram API credentials anywhere.
EOF
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

env_get() {
  local file="$1"
  local key="$2"
  [[ -f "$file" ]] || return 0
  awk -v key="$key" '
    index($0, key "=") == 1 {
      print substr($0, length(key) + 2)
      exit
    }
  ' "$file"
}

env_set() {
  local file="$1"
  local key="$2"
  local value="$3"
  local temp_file="${file}.tmp.$$"

  [[ "$value" != *$'\n'* ]] || die "${key} must not contain a newline"
  touch "$file"
  grep -v "^${key}=" "$file" >"$temp_file" || true
  printf '%s=%s\n' "$key" "$value" >>"$temp_file"
  mv "$temp_file" "$file"
  chmod 0600 "$file" 2>/dev/null || true
}

is_placeholder() {
  local key="$1"
  local value="$2"
  case "${key}:${value}" in
    OTP_RELAY_BEARER_TOKEN:generate-a-secure-random-token-here) return 0 ;;
    TELEGRAM_API_ID:12345678) return 0 ;;
    TELEGRAM_API_HASH:0123456789abcdef0123456789abcdef) return 0 ;;
    TELEGRAM_ACCOUNT_ID:123456789) return 0 ;;
  esac
  return 1
}

generate_token() {
  if command_exists openssl; then
    openssl rand -hex 32
    return
  fi
  if command_exists od && [[ -r /dev/urandom ]]; then
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
    return
  fi
  die "cannot generate Bearer token: install openssl or provide /dev/urandom + od"
}

ensure_config_file() {
  local target="$1"
  local template="$2"
  if [[ ! -f "$target" ]]; then
    install -m 0600 "$template" "$target"
    log "created configuration: ${target}"
  fi
}

configure_common_env() {
  local env_file="$1"
  local value=""

  value="$(env_get "$env_file" OTP_RELAY_BEARER_TOKEN)"
  if [[ -z "$value" ]] || is_placeholder OTP_RELAY_BEARER_TOKEN "$value"; then
    value="$(generate_token)"
    env_set "$env_file" OTP_RELAY_BEARER_TOKEN "$value"
    log "generated a 256-bit Relay Bearer token"
  fi

  value="$(env_get "$env_file" TELEGRAM_API_ID)"
  if [[ -z "$value" ]] || is_placeholder TELEGRAM_API_ID "$value"; then
    while true; do
      read -r -p 'Telegram API ID: ' value
      [[ "$value" =~ ^[0-9]+$ ]] && break
      warn "TELEGRAM_API_ID must contain digits only"
    done
    env_set "$env_file" TELEGRAM_API_ID "$value"
  elif [[ ! "$value" =~ ^[0-9]+$ ]]; then
    die "invalid TELEGRAM_API_ID in ${env_file}"
  fi

  value="$(env_get "$env_file" TELEGRAM_API_HASH)"
  if [[ -z "$value" ]] || is_placeholder TELEGRAM_API_HASH "$value"; then
    while true; do
      read -r -s -p 'Telegram API Hash: ' value
      printf '\n'
      [[ "$value" =~ ^[0-9A-Fa-f]{32}$ ]] && break
      warn "TELEGRAM_API_HASH must be the 32-character hash from my.telegram.org"
    done
    env_set "$env_file" TELEGRAM_API_HASH "$value"
  elif [[ ! "$value" =~ ^[0-9A-Fa-f]{32}$ ]]; then
    die "invalid TELEGRAM_API_HASH in ${env_file}"
  fi

  value="$(env_get "$env_file" HAX_TELEGRAM_BOT)"
  if [[ -z "$value" ]]; then
    env_set "$env_file" HAX_TELEGRAM_BOT HaxTG_bot
  elif [[ ! "$value" =~ ^[A-Za-z0-9_]+$ ]]; then
    die "invalid HAX_TELEGRAM_BOT in ${env_file}"
  fi
}

capture_account_id() {
  local log_file="$1"
  sed -n 's/.*TELEGRAM_ACCOUNT_ID=\([0-9][0-9]*\).*/\1/p' "$log_file" | tail -n 1
}

prompt_public_domain() {
  local domain=""
  [[ -t 0 ]] || return 0
  printf '\n'
  read -r -p 'Public HTTPS domain (optional, Enter to skip): ' domain
  [[ -n "$domain" ]] || return 0
  if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]]; then
    warn "domain contains unsupported characters; skipping reverse-proxy hint"
    return 0
  fi
  cat <<EOF

Caddy example:

${domain} {
    reverse_proxy 127.0.0.1:8787
}

After DNS and TLS are ready, configure moyu-renew GitHub Secrets:
  HAX_OTP_RELAY_URL=https://${domain}
  HAX_OTP_RELAY_TOKEN=<value stored in the Relay env file>
EOF
}

print_finish() {
  local env_file="$1"
  local mode="$2"
  printf '\n'
  log "deployment is ready (${mode})"
  log "local readiness endpoint: ${LOCAL_URL}/readyz"
  if [[ "$env_file" == /etc/* ]]; then
    log "Bearer token: sudo grep '^OTP_RELAY_BEARER_TOKEN=' ${env_file}"
  else
    log "Bearer token: grep '^OTP_RELAY_BEARER_TOKEN=' ${env_file}"
  fi
  prompt_public_domain
}

select_mode() {
  local docker_ok=0
  local systemd_ok=0
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    docker_ok=1
  fi
  if [[ "$(uname -s 2>/dev/null || true)" == "Linux" ]] && command_exists systemctl; then
    systemd_ok=1
  fi

  if [[ "$docker_ok" -eq 1 && "$systemd_ok" -eq 1 && -t 0 ]]; then
    printf 'Deployment mode:\n  1) Docker Compose (recommended)\n  2) Native systemd\n'
    local choice=""
    read -r -p 'Choose [1]: ' choice
    case "${choice:-1}" in
      1) MODE="docker" ;;
      2) MODE="systemd" ;;
      *) die "invalid deployment mode" ;;
    esac
  elif [[ "$docker_ok" -eq 1 ]]; then
    MODE="docker"
  elif [[ "$systemd_ok" -eq 1 ]]; then
    MODE="systemd"
  else
    die "neither Docker Compose nor a supported systemd environment was detected"
  fi
}

run_docker() {
  command_exists docker || die "docker is not installed"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

  local env_file="${ROOT_DIR}/.env"
  local compose_file="${ROOT_DIR}/deploy/docker/compose.yml"
  ensure_config_file "$env_file" "${ROOT_DIR}/.env.example"
  configure_common_env "$env_file"

  local -a compose=(docker compose --env-file "$env_file" -f "$compose_file")
  log "validating Compose configuration"
  "${compose[@]}" config >/dev/null

  log "building Relay image"
  "${compose[@]}" build

  local account_id=""
  local session_exists=0
  account_id="$(env_get "$env_file" TELEGRAM_ACCOUNT_ID)"
  if is_placeholder TELEGRAM_ACCOUNT_ID "$account_id"; then
    account_id=""
  fi
  if "${compose[@]}" run --rm --no-deps -T "$SERVICE_NAME" \
    sh -c 'test -f /data/telegram.session' >/dev/null 2>&1; then
    session_exists=1
  fi

  if [[ -z "$account_id" || "$session_exists" -ne 1 ]]; then
    local bootstrap_log=""
    bootstrap_log="$(mktemp)"
    log "starting interactive Telegram session bootstrap"
    log "Telethon will ask for your phone number, login code, and 2FA password when required"
    set +e
    "${compose[@]}" run --rm --no-deps "$SERVICE_NAME" \
      python -m moyu_tg_relay.bootstrap_session \
      --session-path /data/telegram.session 2>&1 | tee "$bootstrap_log"
    local bootstrap_status=${PIPESTATUS[0]}
    set -e
    if [[ "$bootstrap_status" -ne 0 ]]; then
      rm -f "$bootstrap_log"
      die "Telegram session bootstrap failed"
    fi
    account_id="$(capture_account_id "$bootstrap_log")"
    rm -f "$bootstrap_log"
    [[ "$account_id" =~ ^[0-9]+$ ]] || die "bootstrap succeeded but TELEGRAM_ACCOUNT_ID was not captured"
    env_set "$env_file" TELEGRAM_ACCOUNT_ID "$account_id"
    log "saved TELEGRAM_ACCOUNT_ID=${account_id} to ${env_file}"
  else
    log "existing Telegram session and account id found; reusing them"
  fi

  log "starting Relay container"
  "${compose[@]}" up -d

  local attempt=0
  for attempt in $(seq 1 12); do
    if "${compose[@]}" exec -T "$SERVICE_NAME" \
      python /app/smoke_check.py --base-url "$LOCAL_URL" >/dev/null 2>&1; then
      "${compose[@]}" exec -T "$SERVICE_NAME" \
        python /app/smoke_check.py --base-url "$LOCAL_URL"
      print_finish "$env_file" docker
      return 0
    fi
    sleep 5
  done

  "${compose[@]}" logs --tail=80 "$SERVICE_NAME" >&2 || true
  die "Relay did not become ready within 60 seconds"
}

ensure_system_user() {
  if id -u "$SERVICE_NAME" >/dev/null 2>&1; then
    return
  fi
  local nologin_shell="/usr/sbin/nologin"
  [[ -x "$nologin_shell" ]] || nologin_shell="/sbin/nologin"
  useradd --system --home-dir "$STATE_DIR" --shell "$nologin_shell" "$SERVICE_NAME"
}

copy_systemd_release() {
  install -d -m 0755 "$INSTALL_DIR"
  local install_real=""
  install_real="$(cd "$INSTALL_DIR" && pwd -P)"
  if [[ "$ROOT_DIR" != "$install_real" ]]; then
    rm -rf "${INSTALL_DIR}/src" "${INSTALL_DIR}/deploy"
    cp -a "${ROOT_DIR}/src" "${INSTALL_DIR}/src"
    cp -a "${ROOT_DIR}/deploy" "${INSTALL_DIR}/deploy"
    install -m 0644 "${ROOT_DIR}/pyproject.toml" "${INSTALL_DIR}/pyproject.toml"
    install -m 0644 "${ROOT_DIR}/README.md" "${INSTALL_DIR}/README.md"
    install -m 0644 "${ROOT_DIR}/.env.example" "${INSTALL_DIR}/.env.example"
    install -m 0755 "${ROOT_DIR}/smoke_check.py" "${INSTALL_DIR}/smoke_check.py"
  fi
  chown -R root:root "$INSTALL_DIR"
  chmod -R go-w "$INSTALL_DIR"
}

run_systemd() {
  [[ "$(uname -s)" == "Linux" ]] || die "systemd mode requires Linux"
  [[ "${EUID}" -eq 0 ]] || die "systemd mode must run as root: sudo ./deploy/install.sh systemd"
  command_exists systemctl || die "systemctl is required"
  command_exists python3 || die "python3 is required"
  command_exists useradd || die "useradd is required"
  command_exists runuser || die "runuser is required"

  ensure_system_user
  install -d -o "$SERVICE_NAME" -g "$SERVICE_NAME" -m 0700 "$STATE_DIR"
  copy_systemd_release

  if [[ ! -x "${INSTALL_DIR}/.venv/bin/python" ]]; then
    log "creating Python virtual environment"
    if ! python3 -m venv "${INSTALL_DIR}/.venv"; then
      die "failed to create venv; on Debian/Ubuntu install python3-venv and rerun"
    fi
  fi
  "${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip
  "${INSTALL_DIR}/.venv/bin/pip" install --upgrade "$INSTALL_DIR"

  ensure_config_file "$SYSTEMD_ENV" "${INSTALL_DIR}/deploy/systemd/moyu-tg-relay.env.example"
  env_set "$SYSTEMD_ENV" TELEGRAM_SESSION_PATH "${STATE_DIR}/telegram.session"
  configure_common_env "$SYSTEMD_ENV"
  chown root:"$SERVICE_NAME" "$SYSTEMD_ENV"
  chmod 0640 "$SYSTEMD_ENV"

  local account_id=""
  account_id="$(env_get "$SYSTEMD_ENV" TELEGRAM_ACCOUNT_ID)"
  if is_placeholder TELEGRAM_ACCOUNT_ID "$account_id"; then
    account_id=""
  fi
  if [[ -z "$account_id" || ! -f "${STATE_DIR}/telegram.session" ]]; then
    local bootstrap_log=""
    bootstrap_log="$(mktemp)"
    log "starting interactive Telegram session bootstrap as ${SERVICE_NAME}"
    set +e
    runuser -u "$SERVICE_NAME" -- \
      "${INSTALL_DIR}/.venv/bin/python" -m moyu_tg_relay.bootstrap_session \
      --env-file "$SYSTEMD_ENV" \
      --session-path "${STATE_DIR}/telegram.session" 2>&1 | tee "$bootstrap_log"
    local bootstrap_status=${PIPESTATUS[0]}
    set -e
    if [[ "$bootstrap_status" -ne 0 ]]; then
      rm -f "$bootstrap_log"
      die "Telegram session bootstrap failed"
    fi
    account_id="$(capture_account_id "$bootstrap_log")"
    rm -f "$bootstrap_log"
    [[ "$account_id" =~ ^[0-9]+$ ]] || die "bootstrap succeeded but TELEGRAM_ACCOUNT_ID was not captured"
    env_set "$SYSTEMD_ENV" TELEGRAM_ACCOUNT_ID "$account_id"
    chown root:"$SERVICE_NAME" "$SYSTEMD_ENV"
    chmod 0640 "$SYSTEMD_ENV"
    log "saved TELEGRAM_ACCOUNT_ID=${account_id} to ${SYSTEMD_ENV}"
  else
    log "existing Telegram session and account id found; reusing them"
  fi

  install -o root -g root -m 0644 \
    "${INSTALL_DIR}/deploy/systemd/moyu-tg-relay.service" \
    "/etc/systemd/system/moyu-tg-relay.service"
  systemctl daemon-reload
  systemctl enable moyu-tg-relay.service >/dev/null
  systemctl restart moyu-tg-relay.service

  local attempt=0
  for attempt in $(seq 1 12); do
    if "${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/smoke_check.py" \
      --base-url "$LOCAL_URL" --env-file "$SYSTEMD_ENV" >/dev/null 2>&1; then
      "${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/smoke_check.py" \
        --base-url "$LOCAL_URL" --env-file "$SYSTEMD_ENV"
      print_finish "$SYSTEMD_ENV" systemd
      return 0
    fi
    sleep 5
  done

  systemctl status moyu-tg-relay.service --no-pager >&2 || true
  journalctl -u moyu-tg-relay.service -n 80 --no-pager >&2 || true
  die "Relay did not become ready within 60 seconds"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    docker|systemd)
      [[ -z "$MODE" ]] || die "deployment mode was specified more than once"
      MODE="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1 (use --help)"
      ;;
  esac
done

[[ -n "$MODE" ]] || select_mode

case "$MODE" in
  docker) run_docker ;;
  systemd) run_systemd ;;
  *) die "unsupported deployment mode: ${MODE}" ;;
esac
