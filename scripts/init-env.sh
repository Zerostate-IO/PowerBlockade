#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ============================================
# Non-interactive mode defaults
# ============================================
NON_INTERACTIVE=false
CLI_NODE_NAME=""
CLI_ADMIN_USERNAME=""
CLI_ADMIN_PASSWORD=""
CLI_DNS_BIND_ADDRESS=""

# ============================================
# Help and Usage
# ============================================
show_help() {
  cat << 'EOF'
PowerBlockade Environment Setup

USAGE:
    ./scripts/init-env.sh [OPTIONS]

OPTIONS:
    -n, --non-interactive    Run without prompts (required for automation)
    --node-name NAME         Set node name (default: primary)
    --admin-username USER    Set admin username (default: admin)
    --admin-password PASS    Set admin password (auto-generated if not provided)
    --dns-bind-address IP    Set DNS bind address (default: 0.0.0.0)
    -h, --help               Show this help message

ENVIRONMENT VARIABLES (used when --non-interactive and flag not provided):
    PB_NODE_NAME             Node name
    PB_ADMIN_USERNAME        Admin username
    PB_ADMIN_PASSWORD        Admin password
    PB_DNS_BIND_ADDRESS      DNS bind address

PRIORITY ORDER:
    1. CLI flags (highest)
    2. Environment variables
    3. Interactive prompts (only without --non-interactive)
    4. Defaults (lowest)

EXAMPLES:
    # Interactive setup (default)
    ./scripts/init-env.sh

    # Non-interactive with auto-generated password
    ./scripts/init-env.sh --non-interactive --node-name secondary

    # Non-interactive with all values specified
    ./scripts/init-env.sh --non-interactive \
        --node-name secondary \
        --admin-username admin \
        --admin-password "my-secret-password" \
        --dns-bind-address 192.168.1.10

    # Using environment variables
    PB_NODE_NAME=secondary PB_ADMIN_PASSWORD=secret ./scripts/init-env.sh --non-interactive

EOF
}

# ============================================
# Argument Parsing
# ============================================
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--non-interactive)
      NON_INTERACTIVE=true
      shift
      ;;
    --node-name)
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo -e "${RED}Error: --node-name requires a value${NC}" >&2
        exit 1
      fi
      CLI_NODE_NAME="$2"
      shift 2
      ;;
    --admin-username)
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo -e "${RED}Error: --admin-username requires a value${NC}" >&2
        exit 1
      fi
      CLI_ADMIN_USERNAME="$2"
      shift 2
      ;;
    --admin-password)
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo -e "${RED}Error: --admin-password requires a value${NC}" >&2
        exit 1
      fi
      CLI_ADMIN_PASSWORD="$2"
      shift 2
      ;;
    --dns-bind-address)
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo -e "${RED}Error: --dns-bind-address requires a value${NC}" >&2
        exit 1
      fi
      CLI_DNS_BIND_ADDRESS="$2"
      shift 2
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}" >&2
      echo "Run './scripts/init-env.sh --help' for usage." >&2
      exit 1
      ;;
  esac
done

# ============================================
# Helper Functions
# ============================================
require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo -e "${RED}Missing required command: $1${NC}" >&2
    exit 1
  }
}

require openssl

rand_b64() {
  openssl rand -base64 "$1" | tr -d '\n' | tr '+/' '-_' | tr -d '='
}

set_kv() {
  local key="$1"
  local value="$2"
  # Escape special characters in value for safe Perl substitution
  local escaped_value
  escaped_value=$(printf '%s' "$value" | sed 's/[&/\\]/\\&/g')
  # Remove existing key if present
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    perl -0777 -i -pe "s|^${key}=.*\$|${key}=${escaped_value}|m" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

get_kv() {
  local key="$1"
  local default="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    grep -E "^${key}=" "$ENV_FILE" | cut -d'=' -f2-
  else
    echo "$default"
  fi
}

# Get value with priority: CLI > ENV > default
# Usage: get_value cli_var env_var default
get_value() {
  local cli_val="$1"
  local env_var="$2"
  local default="$3"
  
  if [[ -n "$cli_val" ]]; then
    echo "$cli_val"
  elif [[ -n "${!env_var:-}" ]]; then
    echo "${!env_var}"
  else
    echo "$default"
  fi
}

detect_port53_conflict() {
  local conflict=""
  local details=""
  
  # Check for systemd-resolved
  if systemctl is-active systemd-resolved &>/dev/null; then
    conflict="systemd-resolved"
    details="Ubuntu's default DNS stub resolver"
  # Check for Netbird
  elif pgrep -x "netbird" &>/dev/null || systemctl is-active netbird &>/dev/null; then
    conflict="netbird"
    details="Netbird VPN DNS resolver"
  # Check for Tailscale
  elif pgrep -x "tailscaled" &>/dev/null || systemctl is-active tailscaled &>/dev/null; then
    conflict="tailscale"
    details="Tailscale VPN DNS resolver"
  # Check for dnsmasq
  elif systemctl is-active dnsmasq &>/dev/null; then
    conflict="dnsmasq"
    details="DNS forwarder (often used by NetworkManager)"
  # Check for Pi-hole
  elif systemctl is-active pihole-FTL &>/dev/null; then
    conflict="pihole"
    details="Pi-hole DNS server"
  # Generic check - what's listening on port 53
  elif command -v ss &>/dev/null && ss -tulpn 2>/dev/null | grep -q ':53 '; then
    local listener=$(ss -tulpn 2>/dev/null | grep ':53 ' | head -1)
    conflict="unknown"
    details="Another service is listening on port 53"
  fi
  
  echo "$conflict|$details"
}

get_default_ip() {
  # Get the default route interface's IP
  local ip=""
  if command -v ip &>/dev/null; then
    ip=$(ip route get 1 2>/dev/null | grep -oP 'src \K\S+' | head -1)
  elif command -v hostname &>/dev/null; then
    ip=$(hostname -I 2>/dev/null | cut -d' ' -f1)
  fi
  echo "$ip"
}

# ============================================
# Main Setup
# ============================================
echo ""
echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║          PowerBlockade Configuration Setup                 ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [[ "$NON_INTERACTIVE" == "true" ]]; then
  echo -e "${BLUE}→${NC} Running in non-interactive mode"
fi

# Initialize .env file
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo -e "${GREEN}✓${NC} Created .env from .env.example"
  else
    touch "$ENV_FILE"
    echo -e "${GREEN}✓${NC} Created empty .env file"
  fi
else
  echo -e "${BLUE}→${NC} Using existing .env file"
fi

echo ""

# ============================================
# Step 1: Port 53 Conflict Detection
# ============================================
echo -e "${BOLD}Step 1: DNS Port Check${NC}"
echo "─────────────────────────────────────"

# Determine DNS bind address with priority: CLI > ENV > interactive > default
DNSDIST_LISTEN="0.0.0.0"

if [[ -n "$CLI_DNS_BIND_ADDRESS" ]]; then
  DNSDIST_LISTEN="$CLI_DNS_BIND_ADDRESS"
  echo -e "${GREEN}✓${NC} DNS will bind to $DNSDIST_LISTEN (from CLI flag)"
elif [[ -n "${PB_DNS_BIND_ADDRESS:-}" ]]; then
  DNSDIST_LISTEN="$PB_DNS_BIND_ADDRESS"
  echo -e "${GREEN}✓${NC} DNS will bind to $DNSDIST_LISTEN (from env var)"
elif [[ "$NON_INTERACTIVE" == "true" ]]; then
  # In non-interactive mode, check for conflicts but don't prompt
  conflict_info=$(detect_port53_conflict)
  conflict="${conflict_info%%|*}"
  conflict_details="${conflict_info##*|}"
  
  if [[ -n "$conflict" ]]; then
    echo -e "${YELLOW}⚠ Port 53 Conflict Detected${NC}"
    echo -e "  ${BOLD}$conflict${NC}: $conflict_details"
    echo -e "${YELLOW}!${NC} Using default 0.0.0.0 - startup may fail"
    echo "  (Use --dns-bind-address to specify an IP)"
  else
    echo -e "${GREEN}✓${NC} Port 53 is available"
  fi
else
  # Interactive mode - check and prompt
  conflict_info=$(detect_port53_conflict)
  conflict="${conflict_info%%|*}"
  conflict_details="${conflict_info##*|}"

  if [[ -n "$conflict" ]]; then
    echo -e "${YELLOW}⚠ Port 53 Conflict Detected${NC}"
    echo -e "  ${BOLD}$conflict${NC}: $conflict_details"
    echo ""
    echo "Options:"
    echo "  1) Bind DNS to a specific IP (recommended)"
    echo "  2) Keep binding to all interfaces (0.0.0.0) - may fail if port is in use"
    echo "  3) Stop the conflicting service and continue"
    echo ""
    
    default_ip=$(get_default_ip)
    read -p "Choose [1/2/3] (default: 1): " port_choice
    port_choice=${port_choice:-1}
    
    case "$port_choice" in
      1)
        read -p "Enter IP to bind DNS to (default: $default_ip): " bind_ip
        bind_ip=${bind_ip:-$default_ip}
        DNSDIST_LISTEN="$bind_ip"
        echo -e "${GREEN}✓${NC} DNS will bind to $bind_ip"
        ;;
      2)
        echo -e "${YELLOW}!${NC} Keeping 0.0.0.0 - startup may fail"
        ;;
      3)
        echo ""
        echo "Stopping $conflict..."
        case "$conflict" in
          systemd-resolved)
            sudo systemctl stop systemd-resolved
            echo -e "${GREEN}✓${NC} Stopped systemd-resolved"
            ;;
          netbird)
            sudo systemctl stop netbird
            echo -e "${GREEN}✓${NC} Stopped netbird"
            ;;
          tailscale)
            sudo systemctl stop tailscaled
            echo -e "${GREEN}✓${NC} Stopped tailscale"
            ;;
          dnsmasq)
            sudo systemctl stop dnsmasq
            echo -e "${GREEN}✓${NC} Stopped dnsmasq"
            ;;
          pihole)
            sudo systemctl stop pihole-FTL
            echo -e "${GREEN}✓${NC} Stopped Pi-hole"
            ;;
          *)
            echo -e "${YELLOW}!${NC} Could not auto-stop. Please stop $conflict manually and re-run."
            exit 1
            ;;
        esac
        ;;
      *)
        echo -e "${YELLOW}!${NC} Invalid choice, defaulting to bind all interfaces"
        ;;
    esac
  else
    echo -e "${GREEN}✓${NC} Port 53 is available"
  fi
fi

echo ""

# ============================================
# Step 2: Node Configuration
# ============================================
echo -e "${BOLD}Step 2: Node Configuration${NC}"
echo "─────────────────────────────────────"

current_node=$(get_kv "NODE_NAME" "primary")

# Determine node name with priority: CLI > ENV > interactive > default
if [[ -n "$CLI_NODE_NAME" ]]; then
  node_name="$CLI_NODE_NAME"
  echo -e "${GREEN}✓${NC} Node name: $node_name (from CLI flag)"
elif [[ -n "${PB_NODE_NAME:-}" ]]; then
  node_name="$PB_NODE_NAME"
  echo -e "${GREEN}✓${NC} Node name: $node_name (from env var)"
elif [[ "$NON_INTERACTIVE" == "true" ]]; then
  node_name="$current_node"
  echo -e "${GREEN}✓${NC} Node name: $node_name (default)"
else
  read -p "Node name (default: $current_node): " node_name
  node_name=${node_name:-$current_node}
  echo -e "${GREEN}✓${NC} Node name: $node_name"
fi

echo ""

# ============================================
# Step 3: Admin Credentials
# ============================================
echo -e "${BOLD}Step 3: Admin Credentials${NC}"
echo "─────────────────────────────────────"

current_username=$(get_kv "ADMIN_USERNAME" "admin")

# Determine admin username with priority: CLI > ENV > interactive > default
if [[ -n "$CLI_ADMIN_USERNAME" ]]; then
  admin_username="$CLI_ADMIN_USERNAME"
  echo -e "${GREEN}✓${NC} Admin username: $admin_username (from CLI flag)"
elif [[ -n "${PB_ADMIN_USERNAME:-}" ]]; then
  admin_username="$PB_ADMIN_USERNAME"
  echo -e "${GREEN}✓${NC} Admin username: $admin_username (from env var)"
elif [[ "$NON_INTERACTIVE" == "true" ]]; then
  admin_username="$current_username"
  echo -e "${GREEN}✓${NC} Admin username: $admin_username (default)"
else
  read -p "Admin username (default: $current_username): " admin_username
  admin_username=${admin_username:-$current_username}
fi

echo ""

# Determine admin password with priority: CLI > ENV > interactive > auto-generate
if [[ -n "$CLI_ADMIN_PASSWORD" ]]; then
  admin_password="$CLI_ADMIN_PASSWORD"
  echo -e "${GREEN}✓${NC} Admin password: (set via CLI flag)"
elif [[ -n "${PB_ADMIN_PASSWORD:-}" ]]; then
  admin_password="$PB_ADMIN_PASSWORD"
  echo -e "${GREEN}✓${NC} Admin password: (set via env var)"
elif [[ "$NON_INTERACTIVE" == "true" ]]; then
  # Auto-generate password in non-interactive mode
  admin_password=$(rand_b64 18)
  echo -e "${GREEN}✓${NC} Generated secure password"
else
  # Interactive mode - prompt for password choice
  echo "Admin password options:"
  echo "  1) Auto-generate secure password"
  echo "  2) Enter custom password"
  read -p "Choose [1/2] (default: 1): " pwd_choice
  pwd_choice=${pwd_choice:-1}

  case "$pwd_choice" in
    1)
      admin_password=$(rand_b64 18)
      echo -e "${GREEN}✓${NC} Generated secure password"
      ;;
    2)
      while true; do
        read -s -p "Enter admin password (min 8 chars): " admin_password
        echo ""
        if [[ ${#admin_password} -lt 8 ]]; then
          echo -e "${RED}Password too short. Minimum 8 characters.${NC}"
          continue
        fi
        read -s -p "Confirm password: " pwd_confirm
        echo ""
        if [[ "$admin_password" != "$pwd_confirm" ]]; then
          echo -e "${RED}Passwords don't match. Try again.${NC}"
          continue
        fi
        break
      done
      echo -e "${GREEN}✓${NC} Password set"
      ;;
    *)
      admin_password=$(rand_b64 18)
      echo -e "${GREEN}✓${NC} Generated secure password"
      ;;
  esac
fi

echo ""

# ============================================
# Step 4: Generate All Secrets
# ============================================
echo -e "${BOLD}Step 4: Generating Secrets${NC}"
echo "─────────────────────────────────────"

# Set all configuration values
set_kv "POWERBLOCKADE_REPO" "zerostate-io"
set_kv "NODE_NAME" "$node_name"
set_kv "ADMIN_USERNAME" "$admin_username"
set_kv "ADMIN_PASSWORD" "$admin_password"
set_kv "ADMIN_SECRET_KEY" "$(rand_b64 48)"
set_kv "POSTGRES_PASSWORD" "$(rand_b64 24)"
set_kv "RECURSOR_API_KEY" "$(rand_b64 24)"
set_kv "PRIMARY_API_KEY" "$(rand_b64 24)"
set_kv "GRAFANA_ADMIN_PASSWORD" "$(rand_b64 18)"
set_kv "DNSDIST_LISTEN_ADDRESS" "$DNSDIST_LISTEN"
set_kv "DOCKER_SUBNET" "172.30.0.0/24"
set_kv "RECURSOR_IP" "172.30.0.10"
set_kv "DNSTAP_PROCESSOR_IP" "172.30.0.20"
set_kv "DOMAIN" "localhost"
set_kv "ACME_EMAIL" ""

echo -e "${GREEN}✓${NC} All secrets generated"
echo ""

# ============================================
# Summary
# ============================================
echo ""
echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║                    Configuration Summary                   ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Node Name:${NC}      $node_name"
echo -e "  ${BOLD}Admin Username:${NC} $admin_username"
echo -e "  ${BOLD}Admin Password:${NC} $admin_password"
echo -e "  ${BOLD}DNS Bind IP:${NC}    $DNSDIST_LISTEN"
echo -e "  ${BOLD}Config File:${NC}    $ENV_FILE"
echo ""

if [[ "$DNSDIST_LISTEN" != "0.0.0.0" ]]; then
  echo -e "${YELLOW}Note:${NC} DNS is bound to $DNSDIST_LISTEN"
  echo "      Make sure your devices use this IP as their DNS server."
  echo ""
fi

echo -e "${BOLD}Next Steps:${NC}"
echo "  1. Review: cat .env"
echo "  2. Start:  docker compose -f docker-compose.ghcr.yml up -d"
echo "  3. Access: http://${DNSDIST_LISTEN}:8080"
echo ""
echo -e "${GREEN}✓${NC} ${BOLD}Save your admin password!${NC} It won't be shown again."
echo ""
