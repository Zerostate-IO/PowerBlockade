#!/usr/bin/env bash
# PowerBlockade Easy Start (Single Host)
#
# Paste-and-run:
#   curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash
#
# Optional:
#   curl -fsSL https://raw.githubusercontent.com/Zerostate-IO/PowerBlockade/main/deploy/deploy-primary-one-liner.sh | bash -s -- v0.7.0

set -euo pipefail

DEFAULT_REPO_URL="https://github.com/Zerostate-IO/PowerBlockade.git"
DEFAULT_REPO_REF="main"
DEFAULT_IMAGE_REPO="zerostate-io"
DEFAULT_IMAGE_VERSION="latest"

REPO_URL="${POWERBLOCKADE_GIT_URL:-$DEFAULT_REPO_URL}"
REPO_REF="${POWERBLOCKADE_GIT_REF:-$DEFAULT_REPO_REF}"
IMAGE_REPO="${POWERBLOCKADE_REPO:-$DEFAULT_IMAGE_REPO}"
IMAGE_VERSION="${1:-${POWERBLOCKADE_VERSION:-$DEFAULT_IMAGE_VERSION}}"

OS_ID="unknown"
OS_PRETTY="Linux"
PKG_MANAGER=""
INSTALL_DIR=""
PROJECT_DIR=""
COMPOSE_IMPL=""
RUNNING_DOCKER_WITH_SUDO=false

PRIV_CMD=()
DOCKER_CMD_PREFIX=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${BLUE}→${NC} $*"; }
ok() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
die() { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

banner() {
  echo ""
  echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║         PowerBlockade Easy Start (Single Host)             ║${NC}"
  echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
  echo ""
}

confirm() {
  local prompt="$1"
  local default_answer="${2:-y}"
  local suffix="[Y/n]"
  local answer=""

  if [[ "$default_answer" == "n" ]]; then
    suffix="[y/N]"
  fi

  read -r -p "$prompt $suffix: " answer
  answer="${answer:-$default_answer}"

  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    n|N|no|NO) return 1 ;;
    *) return 1 ;;
  esac
}

ask_with_default() {
  local prompt="$1"
  local default_value="$2"
  local answer=""
  read -r -p "$prompt (default: $default_value): " answer
  echo "${answer:-$default_value}"
}

setup_priv_cmd() {
  if [[ "$EUID" -eq 0 ]]; then
    PRIV_CMD=()
  elif command -v sudo >/dev/null 2>&1; then
    PRIV_CMD=(sudo)
  else
    PRIV_CMD=()
  fi
}

run_privileged() {
  if [[ ${#PRIV_CMD[@]} -gt 0 ]]; then
    "${PRIV_CMD[@]}" "$@"
  else
    "$@"
  fi
}

detect_os() {
  local uname_s
  uname_s="$(uname -s)"

  if [[ "$uname_s" != "Linux" ]]; then
    die "This installer supports Linux hosts only. For macOS/Windows dev usage, use docs/GETTING_STARTED.md."
  fi

  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_PRETTY="${PRETTY_NAME:-Linux}"
  fi
}

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt-get"
  elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
  elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
  elif command -v zypper >/dev/null 2>&1; then
    PKG_MANAGER="zypper"
  elif command -v pacman >/dev/null 2>&1; then
    PKG_MANAGER="pacman"
  elif command -v apk >/dev/null 2>&1; then
    PKG_MANAGER="apk"
  else
    PKG_MANAGER=""
  fi
}

install_packages() {
  local packages=("$@")

  if [[ "${#packages[@]}" -eq 0 ]]; then
    return 0
  fi

  case "$PKG_MANAGER" in
    apt-get)
      run_privileged apt-get update
      run_privileged apt-get install -y "${packages[@]}"
      ;;
    dnf)
      run_privileged dnf install -y "${packages[@]}"
      ;;
    yum)
      run_privileged yum install -y "${packages[@]}"
      ;;
    zypper)
      run_privileged zypper --non-interactive install "${packages[@]}"
      ;;
    pacman)
      run_privileged pacman -Sy --noconfirm --needed "${packages[@]}"
      ;;
    apk)
      run_privileged apk add --no-cache "${packages[@]}"
      ;;
    *)
      return 1
      ;;
  esac
}

ensure_base_tools() {
  local missing=()
  local cmd

  for cmd in curl git openssl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "Base tools found (curl, git, openssl)"
    return 0
  fi

  warn "Missing required tools: ${missing[*]}"
  [[ -n "$PKG_MANAGER" ]] || die "No supported package manager detected. Install missing tools manually and re-run."

  if [[ "$EUID" -ne 0 && ${#PRIV_CMD[@]} -eq 0 ]]; then
    die "Need root or sudo privileges to install packages."
  fi

  if ! confirm "Install missing tools now?"; then
    die "Cannot continue without required tools."
  fi

  install_packages "${missing[@]}" || die "Failed to install required tools: ${missing[*]}"

  for cmd in "${missing[@]}"; do
    command -v "$cmd" >/dev/null 2>&1 || die "Tool still missing after install: $cmd"
  done

  ok "Installed required tools: ${missing[*]}"
}

install_docker_engine() {
  local tmp_script

  if command -v docker >/dev/null 2>&1; then
    ok "Docker CLI found"
    return 0
  fi

  warn "Docker is not installed."
  if ! confirm "Install Docker Engine now via get.docker.com?"; then
    die "Docker is required to continue."
  fi

  if [[ "$EUID" -ne 0 && ${#PRIV_CMD[@]} -eq 0 ]]; then
    die "Need root or sudo privileges to install Docker."
  fi

  tmp_script="$(mktemp /tmp/powerblockade-get-docker.XXXXXX.sh)"
  curl -fsSL https://get.docker.com -o "$tmp_script"
  run_privileged sh "$tmp_script"
  rm -f "$tmp_script"

  if command -v systemctl >/dev/null 2>&1; then
    run_privileged systemctl enable --now docker >/dev/null 2>&1 || true
  fi

  command -v docker >/dev/null 2>&1 || die "Docker installation completed but docker command is still unavailable."
  ok "Docker installed"
}

configure_docker_access() {
  if docker info >/dev/null 2>&1; then
    DOCKER_CMD_PREFIX=()
    ok "Docker daemon is accessible for current user"
    return 0
  fi

  if [[ ${#PRIV_CMD[@]} -gt 0 ]] && "${PRIV_CMD[@]}" docker info >/dev/null 2>&1; then
    DOCKER_CMD_PREFIX=("${PRIV_CMD[@]}")
    RUNNING_DOCKER_WITH_SUDO=true
    warn "Using sudo for Docker commands in this run (current user lacks direct Docker access)."
    return 0
  fi

  if command -v systemctl >/dev/null 2>&1 && [[ ${#PRIV_CMD[@]} -gt 0 ]]; then
    info "Attempting to start Docker daemon..."
    run_privileged systemctl enable --now docker >/dev/null 2>&1 || true
    if docker info >/dev/null 2>&1; then
      DOCKER_CMD_PREFIX=()
      ok "Docker daemon started"
      return 0
    fi
    if "${PRIV_CMD[@]}" docker info >/dev/null 2>&1; then
      DOCKER_CMD_PREFIX=("${PRIV_CMD[@]}")
      RUNNING_DOCKER_WITH_SUDO=true
      warn "Docker daemon started; continuing with sudo docker."
      return 0
    fi
  fi

  die "Docker daemon is not accessible. Start Docker and re-run this installer."
}

install_compose_support() {
  local pkg=""

  case "$PKG_MANAGER" in
    apt-get|dnf|yum)
      pkg="docker-compose-plugin"
      ;;
    zypper|pacman)
      pkg="docker-compose"
      ;;
    apk)
      pkg="docker-cli-compose"
      ;;
    *)
      pkg=""
      ;;
  esac

  [[ -n "$pkg" ]] || die "Docker Compose is missing and no supported auto-install path was found."
  install_packages "$pkg" || die "Failed to install Docker Compose support package: $pkg"
}

detect_compose_impl() {
  if "${DOCKER_CMD_PREFIX[@]}" docker compose version >/dev/null 2>&1; then
    COMPOSE_IMPL="plugin"
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1 && "${DOCKER_CMD_PREFIX[@]}" docker-compose version >/dev/null 2>&1; then
    COMPOSE_IMPL="standalone"
    return 0
  fi

  COMPOSE_IMPL=""
  return 1
}

ensure_compose() {
  if detect_compose_impl; then
    ok "Docker Compose available ($COMPOSE_IMPL)"
    return 0
  fi

  warn "Docker Compose is not available."
  [[ -n "$PKG_MANAGER" ]] || die "No supported package manager detected. Install Docker Compose and re-run."

  if ! confirm "Install Docker Compose support now?"; then
    die "Docker Compose is required to continue."
  fi

  install_compose_support
  detect_compose_impl || die "Docker Compose is still unavailable after installation."
  ok "Docker Compose installed ($COMPOSE_IMPL)"
}

compose_cmd() {
  if [[ "$COMPOSE_IMPL" == "plugin" ]]; then
    "${DOCKER_CMD_PREFIX[@]}" docker compose "$@"
  else
    "${DOCKER_CMD_PREFIX[@]}" docker-compose "$@"
  fi
}

suggest_docker_group() {
  if [[ "$RUNNING_DOCKER_WITH_SUDO" != "true" || "$EUID" -eq 0 ]]; then
    return 0
  fi

  if [[ -n "${USER:-}" ]] && command -v getent >/dev/null 2>&1 && getent group docker >/dev/null 2>&1; then
    if confirm "Add '$USER' to the docker group for future runs?"; then
      run_privileged usermod -aG docker "$USER" || warn "Could not add user to docker group."
      warn "Docker group change will apply after you log out and back in."
    fi
  fi
}

prepare_install_dir() {
  if [[ ! -d "$INSTALL_DIR" ]]; then
    if [[ "$INSTALL_DIR" == /opt/* || "$INSTALL_DIR" == /srv/* ]]; then
      run_privileged mkdir -p "$INSTALL_DIR"
      if [[ "$EUID" -ne 0 ]]; then
        run_privileged chown "$(id -un):$(id -gn)" "$INSTALL_DIR"
      fi
    else
      mkdir -p "$INSTALL_DIR"
    fi
  fi

  [[ -d "$INSTALL_DIR" ]] || die "Install directory does not exist: $INSTALL_DIR"
  [[ -w "$INSTALL_DIR" ]] || die "Install directory is not writable: $INSTALL_DIR"
}

clone_or_update_repo() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Existing PowerBlockade checkout detected at $INSTALL_DIR"
    if confirm "Update repository to '$REPO_REF' before setup?"; then
      git -C "$INSTALL_DIR" fetch --tags origin
      git -C "$INSTALL_DIR" checkout "$REPO_REF"
      git -C "$INSTALL_DIR" pull --ff-only origin "$REPO_REF"
      ok "Repository updated"
    else
      warn "Keeping existing repository state as-is"
    fi
    PROJECT_DIR="$INSTALL_DIR"
    return 0
  fi

  if [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    die "Install directory is not empty and is not a git checkout: $INSTALL_DIR"
  fi

  info "Cloning PowerBlockade repository..."
  git clone --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
  PROJECT_DIR="$INSTALL_DIR"
  ok "Repository cloned"
}

prompt_release_version() {
  IMAGE_VERSION="$(ask_with_default "PowerBlockade image tag" "$IMAGE_VERSION")"
}

check_ghcr_access() {
  local image="ghcr.io/${IMAGE_REPO}/powerblockade-admin-ui:${IMAGE_VERSION}"
  local pull_output
  local status
  local gh_user
  local gh_token

  info "Checking registry access for $image ..."

  set +e
  pull_output=$("${DOCKER_CMD_PREFIX[@]}" docker pull "$image" 2>&1)
  status=$?
  set -e

  if [[ "$status" -eq 0 ]]; then
    ok "Registry access confirmed"
    return 0
  fi

  if echo "$pull_output" | grep -Eqi '403|unauthorized|denied|authentication required'; then
    warn "Container registry requires authentication."
    if ! confirm "Log in to GHCR now?"; then
      die "Cannot pull required images without GHCR access."
    fi

    read -r -p "GitHub username: " gh_user
    read -r -s -p "GitHub token (read:packages): " gh_token
    echo ""
    printf '%s' "$gh_token" | "${DOCKER_CMD_PREFIX[@]}" docker login ghcr.io -u "$gh_user" --password-stdin

    set +e
    pull_output=$("${DOCKER_CMD_PREFIX[@]}" docker pull "$image" 2>&1)
    status=$?
    set -e

    if [[ "$status" -ne 0 ]]; then
      echo "$pull_output" >&2
      die "GHCR login succeeded, but image pull still failed."
    fi

    ok "GHCR login verified"
    return 0
  fi

  echo "$pull_output" >&2
  die "Failed to pull image. Check network connectivity and registry settings."
}

run_init_env() {
  cd "$PROJECT_DIR"
  [[ -f ./scripts/init-env.sh ]] || die "Missing setup script: $PROJECT_DIR/scripts/init-env.sh"
  chmod +x ./scripts/init-env.sh
  info "Launching interactive PowerBlockade configuration..."
  ./scripts/init-env.sh
}

start_stack() {
  cd "$PROJECT_DIR"
  export POWERBLOCKADE_VERSION="$IMAGE_VERSION"
  export POWERBLOCKADE_REPO="$IMAGE_REPO"

  info "Pulling images (tag: $POWERBLOCKADE_VERSION)..."
  compose_cmd -f docker-compose.ghcr.yml pull

  info "Starting PowerBlockade services..."
  compose_cmd -f docker-compose.ghcr.yml up -d
  ok "Services started"
}

env_value() {
  local key="$1"
  local fallback="$2"
  local env_file="$PROJECT_DIR/.env"

  if [[ -f "$env_file" ]]; then
    local line
    line="$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#*=}"
      return 0
    fi
  fi

  echo "$fallback"
}

get_host_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')"
  fi
  if [[ -z "$ip" ]] && command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  echo "${ip:-localhost}"
}

wait_for_admin_health() {
  local admin_port
  local health_url
  local waited=0
  local timeout_seconds=120

  admin_port="$(env_value "ADMIN_PORT" "8080")"
  health_url="http://127.0.0.1:${admin_port}/health"

  info "Waiting for Admin UI health endpoint: $health_url"
  while [[ "$waited" -lt "$timeout_seconds" ]]; do
    if curl -fsS "$health_url" >/dev/null 2>&1; then
      ok "Admin UI is healthy"
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done

  warn "Admin UI health check timed out after ${timeout_seconds}s."
  return 1
}

show_summary() {
  local node_name
  local admin_username
  local admin_password
  local dns_bind
  local admin_port
  local host_ip
  local compose_bin
  local compose_prefix=""

  node_name="$(env_value "NODE_NAME" "primary")"
  admin_username="$(env_value "ADMIN_USERNAME" "admin")"
  admin_password="$(env_value "ADMIN_PASSWORD" "(not found)")"
  dns_bind="$(env_value "DNSDIST_LISTEN_ADDRESS" "0.0.0.0")"
  admin_port="$(env_value "ADMIN_PORT" "8080")"
  host_ip="$(get_host_ip)"

  if [[ "$COMPOSE_IMPL" == "plugin" ]]; then
    compose_bin="docker compose"
  else
    compose_bin="docker-compose"
  fi

  if [[ "$RUNNING_DOCKER_WITH_SUDO" == "true" ]]; then
    compose_prefix="sudo "
  fi

  echo ""
  echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║                PowerBlockade Is Up                         ║${NC}"
  echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  ${BOLD}Project Dir:${NC}     $PROJECT_DIR"
  echo -e "  ${BOLD}Node Name:${NC}       $node_name"
  echo -e "  ${BOLD}Admin URL:${NC}       http://$host_ip:$admin_port"
  echo -e "  ${BOLD}Admin Username:${NC}  $admin_username"
  echo -e "  ${BOLD}Admin Password:${NC}  $admin_password"
  echo -e "  ${BOLD}DNS Listen:${NC}      $dns_bind:53"
  echo ""
  echo -e "${BOLD}Useful Commands:${NC}"
  echo "  cd $PROJECT_DIR"
  echo "  ${compose_prefix}${compose_bin} -f docker-compose.ghcr.yml ps"
  echo "  ${compose_prefix}${compose_bin} -f docker-compose.ghcr.yml logs -f admin-ui"
  echo "  dig @127.0.0.1 google.com +short"
  echo ""
  echo -e "${GREEN}Save the admin password above.${NC}"

  if [[ "$RUNNING_DOCKER_WITH_SUDO" == "true" ]]; then
    echo ""
    warn "Docker commands used sudo in this run. After docker-group membership is applied, re-login to use Docker without sudo."
  fi
}

main() {
  banner
  detect_os
  detect_package_manager
  setup_priv_cmd

  info "Detected OS: $OS_PRETTY"
  if [[ -n "$PKG_MANAGER" ]]; then
    info "Detected package manager: $PKG_MANAGER"
  else
    warn "No supported package manager auto-detected."
  fi

  ensure_base_tools
  install_docker_engine
  configure_docker_access
  ensure_compose
  suggest_docker_group

  echo ""
  INSTALL_DIR="$(ask_with_default "Install directory" "$(if [[ -w /opt || "$EUID" -eq 0 || ${#PRIV_CMD[@]} -gt 0 ]]; then echo "/opt/powerblockade"; else echo "$HOME/powerblockade"; fi)")"
  prepare_install_dir
  clone_or_update_repo

  prompt_release_version
  check_ghcr_access
  run_init_env
  start_stack

  echo ""
  info "Current service status:"
  compose_cmd -f docker-compose.ghcr.yml ps || true
  wait_for_admin_health || true
  show_summary
}

main "$@"
