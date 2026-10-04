#!/usr/bin/env bash
# ==============================================================================
# Script: scripts/setup-hosts.sh
# Purpose: Configure IP addressing, default gateways, and LACP bonds on all 24
#          Linux multitool hosts in the Campus EVPN-VXLAN topology.
# ==============================================================================

set -euo pipefail

# ANSI color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PREFIX="clab-campus-evpn-anycast-mh"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

get_container_name() {
    local host_name="$1"
    if docker ps --format '{{.Names}}' | grep -q "^${PREFIX}-${host_name}$"; then
        echo "${PREFIX}-${host_name}"
    elif docker ps --format '{{.Names}}' | grep -q "^${host_name}$"; then
        echo "${host_name}"
    else
        echo ""
    fi
}

configure_single_homed() {
    local host_name="$1"
    local ip_addr="$2"
    local gw_addr="$3"

    local cname
    cname=$(get_container_name "$host_name")

    if [[ -z "$cname" ]]; then
        log_warn "Host container '${host_name}' is not running. Skipping."
        return
    fi

    log_info "Configuring Single-Homed host: ${host_name} (${cname}) -> IP: ${ip_addr}, GW: ${gw_addr}"

    docker exec "$cname" bash -c "
        ip link set eth1 up
        ip addr flush dev eth1
        ip addr add ${ip_addr} dev eth1
        ip route replace default via ${gw_addr} dev eth1
    "
    log_success "Host ${host_name} configured successfully."
}

configure_multihomed() {
    local host_name="$1"
    local ip_addr="$2"
    local gw_addr="$3"

    local cname
    cname=$(get_container_name "$host_name")

    if [[ -z "$cname" ]]; then
        log_warn "Host container '${host_name}' is not running. Skipping."
        return
    fi

    log_info "Configuring Multihomed host (802.3ad LACP): ${host_name} (${cname}) -> IP: ${ip_addr}, GW: ${gw_addr}"

    docker exec "$cname" bash -c "
        # Delete existing bond if present
        ip link del bond0 2>/dev/null || true

        # Create 802.3ad bond with fast LACP rate and L3+L4 hash policy
        ip link add bond0 type bond mode 802.3ad lacp_rate fast xmit_hash_policy layer3+4

        # Bring down physical interfaces to enslave into bond
        ip link set eth1 down
        ip link set eth2 down
        ip link set eth1 master bond0
        ip link set eth2 master bond0

        # Bring up interfaces and bond
        ip link set eth1 up
        ip link set eth2 up
        ip link set bond0 up

        # Flush and set IP and default route
        ip addr flush dev bond0
        ip addr add ${ip_addr} dev bond0
        ip route replace default via ${gw_addr} dev bond0
    "
    log_success "Host ${host_name} multihomed bond0 configured successfully."
}

verify_host() {
    local host_name="$1"
    local intf="$2"
    local gw_addr="$3"

    local cname
    cname=$(get_container_name "$host_name")

    if [[ -z "$cname" ]]; then
        printf "%-12s | %-10s | %-16s | %-16s | %-10s\n" "$host_name" "$intf" "N/A" "$gw_addr" "OFFLINE"
        return
    fi

    local operstate
    operstate=$(docker exec "$cname" cat "/sys/class/net/${intf}/operstate" 2>/dev/null || echo "unknown")
    local current_ip
    current_ip=$(docker exec "$cname" ip -4 -o addr show "$intf" 2>/dev/null | awk '{print $4}' || echo "none")

    # Prime gateway ARP resolution
    docker exec "$cname" ping -c 1 -W 1 "$gw_addr" >/dev/null 2>&1 || true

    printf "%-12s | %-10s | %-16s | %-16s | %-10s\n" "$host_name" "$intf" "$current_ip" "$gw_addr" "$operstate"
}

echo "=============================================================================="
echo " Campus EVPN-VXLAN: Host Network Configuration Script"
echo "=============================================================================="

# ------------------------------------------------------------------------------
# Pair 1 Hosts (VLAN 101: 10.1.1.0/24, VLAN 102: 10.1.2.0/24)
# ------------------------------------------------------------------------------
echo -e "\n--- Configuring Pair 1 Hosts ---"
configure_single_homed "h1-v101" "10.1.1.11/24" "10.1.1.1"
configure_single_homed "h2-v101" "10.1.1.12/24" "10.1.1.1"
configure_multihomed   "hm-v101" "10.1.1.10/24" "10.1.1.1"

configure_single_homed "h1-v102" "10.1.2.11/24" "10.1.2.1"
configure_single_homed "h2-v102" "10.1.2.12/24" "10.1.2.1"
configure_multihomed   "hm-v102" "10.1.2.10/24" "10.1.2.1"

# ------------------------------------------------------------------------------
# Pair 2 Hosts (VLAN 201: 10.2.1.0/24, VLAN 202: 10.2.2.0/24)
# ------------------------------------------------------------------------------
echo -e "\n--- Configuring Pair 2 Hosts ---"
configure_single_homed "h1-v201" "10.2.1.11/24" "10.2.1.1"
configure_single_homed "h2-v201" "10.2.1.12/24" "10.2.1.1"
configure_multihomed   "hm-v201" "10.2.1.10/24" "10.2.1.1"

configure_single_homed "h1-v202" "10.2.2.11/24" "10.2.2.1"
configure_single_homed "h2-v202" "10.2.2.12/24" "10.2.2.1"
configure_multihomed   "hm-v202" "10.2.2.10/24" "10.2.2.1"

# ------------------------------------------------------------------------------
# Pair 3 Hosts (VLAN 301: 10.3.1.0/24, VLAN 302: 10.3.2.0/24)
# ------------------------------------------------------------------------------
echo -e "\n--- Configuring Pair 3 Hosts ---"
configure_single_homed "h1-v301" "10.3.1.11/24" "10.3.1.1"
configure_single_homed "h2-v301" "10.3.1.12/24" "10.3.1.1"
configure_multihomed   "hm-v301" "10.3.1.10/24" "10.3.1.1"

configure_single_homed "h1-v302" "10.3.2.11/24" "10.3.2.1"
configure_single_homed "h2-v302" "10.3.2.12/24" "10.3.2.1"
configure_multihomed   "hm-v302" "10.3.2.10/24" "10.3.2.1"

# ------------------------------------------------------------------------------
# Pair 4 Hosts (VLAN 401: 10.4.1.0/24, VLAN 402: 10.4.2.0/24)
# ------------------------------------------------------------------------------
echo -e "\n--- Configuring Pair 4 Hosts ---"
configure_single_homed "h1-v401" "10.4.1.11/24" "10.4.1.1"
configure_single_homed "h2-v401" "10.4.1.12/24" "10.4.1.1"
configure_multihomed   "hm-v401" "10.4.1.10/24" "10.4.1.1"

configure_single_homed "h1-v402" "10.4.2.11/24" "10.4.2.1"
configure_single_homed "h2-v402" "10.4.2.12/24" "10.4.2.1"
configure_multihomed   "hm-v402" "10.4.2.10/24" "10.4.2.1"

# ------------------------------------------------------------------------------
# Verification Summary Table
# ------------------------------------------------------------------------------
echo -e "\n=============================================================================="
echo " Host Status and Verification Summary"
echo "=============================================================================="
printf "%-12s | %-10s | %-16s | %-16s | %-10s\n" "Host" "Interface" "IPv4 Address" "Gateway" "Status"
echo "------------------------------------------------------------------------------"
verify_host "h1-v101" "eth1" "10.1.1.1"
verify_host "h2-v101" "eth1" "10.1.1.1"
verify_host "hm-v101" "bond0" "10.1.1.1"
verify_host "h1-v102" "eth1" "10.1.2.1"
verify_host "h2-v102" "eth1" "10.1.2.1"
verify_host "hm-v102" "bond0" "10.1.2.1"

verify_host "h1-v201" "eth1" "10.2.1.1"
verify_host "h2-v201" "eth1" "10.2.1.1"
verify_host "hm-v201" "bond0" "10.2.1.1"
verify_host "h1-v202" "eth1" "10.2.2.1"
verify_host "h2-v202" "eth1" "10.2.2.1"
verify_host "hm-v202" "bond0" "10.2.2.1"

verify_host "h1-v301" "eth1" "10.3.1.1"
verify_host "h2-v301" "eth1" "10.3.1.1"
verify_host "hm-v301" "bond0" "10.3.1.1"
verify_host "h1-v302" "eth1" "10.3.2.1"
verify_host "h2-v302" "eth1" "10.3.2.1"
verify_host "hm-v302" "bond0" "10.3.2.1"

verify_host "h1-v401" "eth1" "10.4.1.1"
verify_host "h2-v401" "eth1" "10.4.1.1"
verify_host "hm-v401" "bond0" "10.4.1.1"
verify_host "h1-v402" "eth1" "10.4.2.1"
verify_host "h2-v402" "eth1" "10.4.2.1"
verify_host "hm-v402" "bond0" "10.4.2.1"
echo "=============================================================================="
