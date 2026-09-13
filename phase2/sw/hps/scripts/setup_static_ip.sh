#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 HPS Ethernet setup helper.
# File class: [1] hand-written HPS bring-up script.
#
# This script configures the HPS-side Ethernet interface for the direct-link
# demo topology described by sw/hps/config/trecap_hps_config.json. It does not
# touch FPGA CSRs, DDR ring pointers, or telemetry packet state.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HPS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
REPO_ROOT="$(cd "${HPS_DIR}/../.." && pwd -P)"
DEFAULT_CONFIG="${HPS_DIR}/config/trecap_hps_config.json"

CONFIG="${DEFAULT_CONFIG}"
IFACE=""
APPLY=0
NO_FLUSH=0
NO_PING=0
PRINT_PC_HINTS=0
QUIET=0
OVERRIDE_HPS_IP=""
OVERRIDE_PC_IP=""
OVERRIDE_NETMASK=""
GATEWAY=""

log() {
  if [[ "${QUIET}" -eq 0 ]]; then
    printf '[setup_static_ip] %s\n' "$*"
  fi
}

warn() {
  printf '[setup_static_ip] WARNING: %s\n' "$*" >&2
}

die() {
  printf '[setup_static_ip] ERROR: %s\n' "$*" >&2
  exit 2
}

usage() {
  cat <<'USAGE_TEXT'
Usage: setup_static_ip.sh [options]

Configure the DE1-SoC HPS Ethernet interface for the T-RECAP direct-link demo.
The default topology is read from sw/hps/config/trecap_hps_config.json:

  PC  = telemetry_dst_ip      default 192.168.10.1/24
  HPS = hps_static_ip         default 192.168.10.2/24

Safety policy:
  The default mode is dry-run. Pass --apply to change the interface.

Options:
  --config <path>       Runtime config JSON. Default: sw/hps/config/trecap_hps_config.json
  --iface <name>        Network interface to configure, e.g. eth0 or end0.
  --hps-ip <addr>       Override HPS static IPv4 address from config.
  --pc-ip <addr>        Override PC/trusted peer IPv4 address from config.
  --netmask <mask>      Override netmask from config, e.g. 255.255.255.0.
  --gateway <addr>      Optional default gateway to install with ip route replace.
  --apply               Actually run ip commands. Without this, commands are printed only.
  --dry-run             Force dry-run mode.
  --no-flush            Do not flush existing IPv4 addresses on the interface.
  --no-ping             Do not ping the PC after applying configuration.
  --print-pc-hints      Print Linux/Windows PC-side direct-link setup hints.
  --quiet               Print less output.
  --help                Show this help.

Examples:
  # Safe preview on the HPS:
  sw/hps/scripts/setup_static_ip.sh --iface eth0

  # Apply on the HPS:
  sudo sw/hps/scripts/setup_static_ip.sh --iface eth0 --apply

  # Apply and skip connectivity ping while the PC is not connected yet:
  sudo sw/hps/scripts/setup_static_ip.sh --iface eth0 --apply --no-ping
USAGE_TEXT
}

require_file() {
  [[ -f "$1" ]] || die "missing file: $1"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

json_value() {
  local key="$1"
  python3 - "${CONFIG}" "${key}" <<'PY_JSON'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
key = sys.argv[2]
with path.open("r", encoding="utf-8") as f:
    data = json.load(f)
value = data.get(key, "")
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(value)
PY_JSON
}

netmask_to_prefix() {
  local mask="$1"
  python3 - "${mask}" <<'PY_MASK'
import ipaddress
import sys
mask = sys.argv[1]
try:
    net = ipaddress.IPv4Network(f"0.0.0.0/{mask}", strict=False)
except Exception as exc:
    raise SystemExit(f"invalid netmask {mask!r}: {exc}")
print(net.prefixlen)
PY_MASK
}

validate_ipv4() {
  local name="$1"
  local value="$2"
  python3 - "${name}" "${value}" <<'PY_IP'
import ipaddress
import sys
name, value = sys.argv[1], sys.argv[2]
try:
    ipaddress.IPv4Address(value)
except Exception as exc:
    raise SystemExit(f"{name}: invalid IPv4 address {value!r}: {exc}")
PY_IP
}

run_or_print() {
  if [[ "${APPLY}" -eq 1 ]]; then
    log "+ $*"
    "$@"
  else
    printf '[setup_static_ip] DRY-RUN: '
    printf '%q ' "$@"
    printf '\n'
  fi
}

find_iface() {
  local candidate
  for candidate in eth0 end0 enp0s0 enx0 usb0; do
    if [[ -d "/sys/class/net/${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  if command -v ip >/dev/null 2>&1; then
    ip -o link show | awk -F': ' '$2 != "lo" {print $2; exit}' | cut -d@ -f1
  fi
}

print_pc_hints() {
  local pc_ip="$1"
  local prefix="$2"
  local hps_ip="$3"
  cat <<HINTS_TEXT

PC direct-link setup hints
--------------------------
Linux temporary setup example:
  sudo ip addr flush dev <pc_ethernet_iface>
  sudo ip addr add ${pc_ip}/${prefix} dev <pc_ethernet_iface>
  sudo ip link set <pc_ethernet_iface> up
  ping ${hps_ip}

Windows PowerShell example, run as Administrator:
  Get-NetAdapter
  New-NetIPAddress -InterfaceAlias "<adapter name>" -IPAddress ${pc_ip} -PrefixLength ${prefix}
  ping ${hps_ip}

Do not expose the command port to an untrusted network. The Revision G command protocol is
for isolated lab/demo networks and has no authentication or encryption.
HINTS_TEXT
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || die "--config requires a path"
      CONFIG="$2"
      shift 2
      ;;
    --iface)
      [[ $# -ge 2 ]] || die "--iface requires an interface name"
      IFACE="$2"
      shift 2
      ;;
    --hps-ip)
      [[ $# -ge 2 ]] || die "--hps-ip requires an IPv4 address"
      OVERRIDE_HPS_IP="$2"
      shift 2
      ;;
    --pc-ip)
      [[ $# -ge 2 ]] || die "--pc-ip requires an IPv4 address"
      OVERRIDE_PC_IP="$2"
      shift 2
      ;;
    --netmask)
      [[ $# -ge 2 ]] || die "--netmask requires a dotted mask"
      OVERRIDE_NETMASK="$2"
      shift 2
      ;;
    --gateway)
      [[ $# -ge 2 ]] || die "--gateway requires an IPv4 address"
      GATEWAY="$2"
      shift 2
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    --dry-run)
      APPLY=0
      shift
      ;;
    --no-flush)
      NO_FLUSH=1
      shift
      ;;
    --no-ping)
      NO_PING=1
      shift
      ;;
    --print-pc-hints)
      PRINT_PC_HINTS=1
      shift
      ;;
    --quiet)
      QUIET=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

require_cmd python3
require_file "${CONFIG}"

HPS_IP="${OVERRIDE_HPS_IP:-$(json_value hps_static_ip)}"
PC_IP="${OVERRIDE_PC_IP:-$(json_value telemetry_dst_ip)}"
TRUSTED_PEER="$(json_value trusted_command_peer)"
NETMASK="${OVERRIDE_NETMASK:-$(json_value netmask)}"

[[ -n "${HPS_IP}" ]] || die "hps_static_ip is missing from ${CONFIG}; pass --hps-ip"
[[ -n "${PC_IP}" ]] || die "telemetry_dst_ip is missing from ${CONFIG}; pass --pc-ip"
[[ -n "${NETMASK}" ]] || NETMASK="255.255.255.0"

validate_ipv4 hps_static_ip "${HPS_IP}"
validate_ipv4 telemetry_dst_ip "${PC_IP}"
if [[ -n "${TRUSTED_PEER}" ]]; then
  validate_ipv4 trusted_command_peer "${TRUSTED_PEER}"
fi
if [[ -n "${GATEWAY}" ]]; then
  validate_ipv4 gateway "${GATEWAY}"
fi
PREFIX="$(netmask_to_prefix "${NETMASK}")"

if [[ -z "${IFACE}" ]]; then
  IFACE="$(find_iface || true)"
fi
[[ -n "${IFACE}" ]] || die "could not auto-detect Ethernet interface; pass --iface eth0"

log "repo root: ${REPO_ROOT}"
log "config:    ${CONFIG}"
log "iface:     ${IFACE}"
log "HPS IP:    ${HPS_IP}/${PREFIX}"
log "PC IP:     ${PC_IP}"
if [[ -n "${TRUSTED_PEER}" && "${TRUSTED_PEER}" != "${PC_IP}" ]]; then
  warn "trusted_command_peer (${TRUSTED_PEER}) differs from telemetry_dst_ip (${PC_IP})"
fi

if [[ "${APPLY}" -eq 1 ]]; then
  require_cmd ip
  [[ "$(id -u)" -eq 0 ]] || die "--apply requires root; run with sudo on the HPS"
  [[ -d "/sys/class/net/${IFACE}" ]] || die "network interface does not exist: ${IFACE}"
else
  if ! command -v ip >/dev/null 2>&1; then
    warn "ip command not found on this host; dry-run output still generated"
  fi
fi

run_or_print ip link set dev "${IFACE}" up
if [[ "${NO_FLUSH}" -eq 0 ]]; then
  run_or_print ip addr flush dev "${IFACE}" scope global
fi
run_or_print ip addr add "${HPS_IP}/${PREFIX}" dev "${IFACE}"
run_or_print ip route replace "${PC_IP}/32" dev "${IFACE}"
if [[ -n "${GATEWAY}" ]]; then
  run_or_print ip route replace default via "${GATEWAY}" dev "${IFACE}"
fi

if [[ "${APPLY}" -eq 1 ]]; then
  log "current IPv4 state:"
  ip -4 addr show dev "${IFACE}" || true
  ip route get "${PC_IP}" || true
  if [[ "${NO_PING}" -eq 0 ]]; then
    if command -v ping >/dev/null 2>&1; then
      if ping -c 3 -W 1 "${PC_IP}"; then
        log "PC connectivity check passed: ${PC_IP}"
      else
        warn "PC ping failed: ${PC_IP}. Check cable, PC static IP, firewall, and interface selection."
      fi
    else
      warn "ping command not found; skipped connectivity check"
    fi
  fi
else
  log "dry-run only; pass --apply to change HPS network state"
fi

if [[ "${PRINT_PC_HINTS}" -eq 1 ]]; then
  print_pc_hints "${PC_IP}" "${PREFIX}" "${HPS_IP}"
fi
