#!/usr/bin/env python3
"""
================================================================================
Script: scripts/validate.py
Project: Campus EVPN-VXLAN Network Validation Suite
Purpose: Automated verification of Underlay OSPF, Overlay iBGP EVPN, Anycast
         Multihoming (ESI / LACP), Route Scale Filtering Policies (/24 vs /32),
         End-to-End Data Plane Matrix, and Resiliency / Failure Recovery.
================================================================================
"""

import sys
import os
import re
import json
import time
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any, Optional

# ANSI Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_WHITE = "\033[37m"
C_BG_GREEN = "\033[42m\033[30m"
C_BG_RED = "\033[41m\033[37m"

PREFIX = "clab-campus-evpn-anycast-mh"

ROUTERS = {
    "core-1": {"role": "core", "system_ip": "10.0.0.1", "pair": None},
    "core-2": {"role": "core", "system_ip": "10.0.0.2", "pair": None},
    "agg-1":  {"role": "agg",  "system_ip": "10.0.0.11", "anycast_ip": "10.0.0.101", "pair": 1, "partner": "agg-2", "partner_ip": "10.0.0.12", "core": "core-1"},
    "agg-2":  {"role": "agg",  "system_ip": "10.0.0.12", "anycast_ip": "10.0.0.101", "pair": 1, "partner": "agg-1", "partner_ip": "10.0.0.11", "core": "core-2"},
    "agg-3":  {"role": "agg",  "system_ip": "10.0.0.13", "anycast_ip": "10.0.0.102", "pair": 2, "partner": "agg-4", "partner_ip": "10.0.0.14", "core": "core-1"},
    "agg-4":  {"role": "agg",  "system_ip": "10.0.0.14", "anycast_ip": "10.0.0.102", "pair": 2, "partner": "agg-3", "partner_ip": "10.0.0.13", "core": "core-2"},
    "agg-5":  {"role": "agg",  "system_ip": "10.0.0.15", "anycast_ip": "10.0.0.103", "pair": 3, "partner": "agg-6", "partner_ip": "10.0.0.16", "core": "core-1"},
    "agg-6":  {"role": "agg",  "system_ip": "10.0.0.16", "anycast_ip": "10.0.0.103", "pair": 3, "partner": "agg-5", "partner_ip": "10.0.0.15", "core": "core-2"},
    "agg-7":  {"role": "agg",  "system_ip": "10.0.0.17", "anycast_ip": "10.0.0.104", "pair": 4, "partner": "agg-8", "partner_ip": "10.0.0.18", "core": "core-1"},
    "agg-8":  {"role": "agg",  "system_ip": "10.0.0.18", "anycast_ip": "10.0.0.104", "pair": 4, "partner": "agg-7", "partner_ip": "10.0.0.17", "core": "core-2"},
}

HOSTS = {
    # Pair 1
    "h1-v101": {"ip": "10.1.1.11", "gw": "10.1.1.1", "vlan": 101, "pair": 1, "type": "single", "agg": "agg-1"},
    "h2-v101": {"ip": "10.1.1.12", "gw": "10.1.1.1", "vlan": 101, "pair": 1, "type": "single", "agg": "agg-2"},
    "hm-v101": {"ip": "10.1.1.10", "gw": "10.1.1.1", "vlan": 101, "pair": 1, "type": "multi",  "sys_mac": "00:00:00:01:01:01", "key": 101},
    "h1-v102": {"ip": "10.1.2.11", "gw": "10.1.2.1", "vlan": 102, "pair": 1, "type": "single", "agg": "agg-1"},
    "h2-v102": {"ip": "10.1.2.12", "gw": "10.1.2.1", "vlan": 102, "pair": 1, "type": "single", "agg": "agg-2"},
    "hm-v102": {"ip": "10.1.2.10", "gw": "10.1.2.1", "vlan": 102, "pair": 1, "type": "multi",  "sys_mac": "00:00:00:01:01:02", "key": 102},

    # Pair 2
    "h1-v201": {"ip": "10.2.1.11", "gw": "10.2.1.1", "vlan": 201, "pair": 2, "type": "single", "agg": "agg-3"},
    "h2-v201": {"ip": "10.2.1.12", "gw": "10.2.1.1", "vlan": 201, "pair": 2, "type": "single", "agg": "agg-4"},
    "hm-v201": {"ip": "10.2.1.10", "gw": "10.2.1.1", "vlan": 201, "pair": 2, "type": "multi",  "sys_mac": "00:00:00:02:01:01", "key": 201},
    "h1-v202": {"ip": "10.2.2.11", "gw": "10.2.2.1", "vlan": 202, "pair": 2, "type": "single", "agg": "agg-3"},
    "h2-v202": {"ip": "10.2.2.12", "gw": "10.2.2.1", "vlan": 202, "pair": 2, "type": "single", "agg": "agg-4"},
    "hm-v202": {"ip": "10.2.2.10", "gw": "10.2.2.1", "vlan": 202, "pair": 2, "type": "multi",  "sys_mac": "00:00:00:02:01:02", "key": 202},

    # Pair 3
    "h1-v301": {"ip": "10.3.1.11", "gw": "10.3.1.1", "vlan": 301, "pair": 3, "type": "single", "agg": "agg-5"},
    "h2-v301": {"ip": "10.3.1.12", "gw": "10.3.1.1", "vlan": 301, "pair": 3, "type": "single", "agg": "agg-6"},
    "hm-v301": {"ip": "10.3.1.10", "gw": "10.3.1.1", "vlan": 301, "pair": 3, "type": "multi",  "sys_mac": "00:00:00:03:01:01", "key": 301},
    "h1-v302": {"ip": "10.3.2.11", "gw": "10.3.2.1", "vlan": 302, "pair": 3, "type": "single", "agg": "agg-5"},
    "h2-v302": {"ip": "10.3.2.12", "gw": "10.3.2.1", "vlan": 302, "pair": 3, "type": "single", "agg": "agg-6"},
    "hm-v302": {"ip": "10.3.2.10", "gw": "10.3.2.1", "vlan": 302, "pair": 3, "type": "multi",  "sys_mac": "00:00:00:03:01:02", "key": 302},

    # Pair 4
    "h1-v401": {"ip": "10.4.1.11", "gw": "10.4.1.1", "vlan": 401, "pair": 4, "type": "single", "agg": "agg-7"},
    "h2-v401": {"ip": "10.4.1.12", "gw": "10.4.1.1", "vlan": 401, "pair": 4, "type": "single", "agg": "agg-8"},
    "hm-v401": {"ip": "10.4.1.10", "gw": "10.4.1.1", "vlan": 401, "pair": 4, "type": "multi",  "sys_mac": "00:00:00:04:01:01", "key": 401},
    "h1-v402": {"ip": "10.4.2.11", "gw": "10.4.2.1", "vlan": 402, "pair": 4, "type": "single", "agg": "agg-7"},
    "h2-v402": {"ip": "10.4.2.12", "gw": "10.4.2.1", "vlan": 402, "pair": 4, "type": "single", "agg": "agg-8"},
    "hm-v402": {"ip": "10.4.2.10", "gw": "10.4.2.1", "vlan": 402, "pair": 4, "type": "multi",  "sys_mac": "00:00:00:04:01:02", "key": 402},
}

SUBNETS_24 = [
    "10.1.1.0/24", "10.1.2.0/24",
    "10.2.1.0/24", "10.2.2.0/24",
    "10.3.1.0/24", "10.3.2.0/24",
    "10.4.1.0/24", "10.4.2.0/24"
]

ALL_SYSTEM_IPS = [r["system_ip"] for r in ROUTERS.values()]
ALL_ANYCAST_IPS = ["10.0.0.101", "10.0.0.102", "10.0.0.103", "10.0.0.104"]


# ------------------------------------------------------------------------------
# Helper Utilities
# ------------------------------------------------------------------------------
def run_docker(cname: str, cmd_list: List[str], timeout: int = 15) -> Tuple[int, str, str]:
    full_cmd = ["docker", "exec", cname] + cmd_list
    try:
        p = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s: {' '.join(full_cmd)}"
    except Exception as e:
        return -1, "", str(e)


def run_sr_cli(node: str, cli_cmd: str, json_format: bool = True, timeout: int = 15) -> Tuple[int, Any, str]:
    cname = f"{PREFIX}-{node}"
    args = ["sr_cli"]
    if json_format:
        args += ["--output-format", "json"]
    args.append(cli_cmd)

    rc, stdout, stderr = run_docker(cname, args, timeout=timeout)
    if rc != 0:
        return rc, None, stderr or stdout

    if json_format:
        try:
            parsed = json.loads(stdout)
            return 0, parsed, ""
        except json.JSONDecodeError as err:
            return -2, None, f"Failed to parse JSON: {err} | Output: {stdout[:200]}"
    return 0, stdout, ""


def host_ping(src_host: str, dst_ip: str, count: int = 2, timeout: int = 3) -> Tuple[bool, float, float, str]:
    """Execute ping from a host container to a target IP.
    Returns: (passed, loss_pct, avg_rtt, raw_output)
    """
    cname = f"{PREFIX}-{src_host}"
    cmd = ["ping", "-c", str(count), "-W", str(timeout), dst_ip]
    rc, stdout, stderr = run_docker(cname, cmd, timeout=timeout + 3)
    out = (stdout or "") + (stderr or "")
    avg_rtt = -1.0
    loss_pct = 100.0

    loss_match = re.search(r"(\d+(?:\.\d+)?)%\s+packet\s+loss", out)
    if loss_match:
        loss_pct = float(loss_match.group(1))
    elif rc == 0:
        loss_pct = 0.0

    rtt_match = re.search(r"(?:rtt|round-trip)\s+min/avg/max.*?=\s*[\d.]+/([\d.]+)/", out)
    if rtt_match:
        avg_rtt = float(rtt_match.group(1))

    passed = (rc == 0 and loss_pct == 0.0)
    return passed, loss_pct, avg_rtt, out


def print_banner(title: str):
    width = 90
    print(f"\n{C_BLUE}{'=' * width}{C_RESET}")
    print(f"{C_BOLD}{C_WHITE}{title.center(width)}{C_RESET}")
    print(f"{C_BLUE}{'=' * width}{C_RESET}\n")


def print_result_badge(passed: bool, message: str, detail: str = ""):
    badge = f"{C_BG_GREEN} PASS {C_RESET}" if passed else f"{C_BG_RED} FAIL {C_RESET}"
    out = f"  [{badge}] {C_BOLD}{message}{C_RESET}"
    if detail:
        out += f"\n         {C_WHITE}{detail}{C_RESET}"
    print(out)


# ------------------------------------------------------------------------------
# Test 1: OSPF Underlay Verification
# ------------------------------------------------------------------------------
def test_1_ospf_underlay() -> Dict[str, Any]:
    print_banner("TEST 1: OSPF Underlay Convergence & Neighbor State Verification")
    result = {"test": "OSPF Underlay", "passed": True, "details": []}

    print(f"{C_CYAN}1.1 Verifying OSPF Neighbors across all 10 nodes...{C_RESET}")
    table_header = f"{'Router':<10} | {'Expected Nbrs':<14} | {'Actual Nbrs':<12} | {'Full Nbrs':<10} | {'Status':<8}"
    print(f"  {table_header}")
    print(f"  {'-' * len(table_header)}")

    def check_ospf_node(node):
        info = ROUTERS[node]
        expected_count = 6 if info["role"] == "core" else 3
        rc, data, err = run_sr_cli(node, "show network-instance default protocols ospf neighbor")
        return node, expected_count, rc, data, err

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(check_ospf_node, n) for n in ROUTERS.keys()]
        for f in sorted(futures, key=lambda fut: fut.result()[0]):
            node, expected_count, rc, data, err = f.result()
            if rc != 0 or not data or "instances" not in data:
                result["passed"] = False
                result["details"].append({"node": node, "status": "ERROR", "error": err})
                print(f"  {node:<10} | {expected_count:<14} | {'ERROR':<12} | {'0':<10} | {C_RED}FAIL{C_RESET}")
                continue

            nbrs = data["instances"][0].get("neighbors_brief", [])
            actual_count = len(nbrs)
            full_nbrs = [n for n in nbrs if n.get("State", "").lower() == "full"]
            full_count = len(full_nbrs)

            node_ok = (actual_count == expected_count and full_count == expected_count)
            if not node_ok:
                result["passed"] = False

            status_str = f"{C_GREEN}PASS{C_RESET}" if node_ok else f"{C_RED}FAIL{C_RESET}"
            print(f"  {node:<10} | {expected_count:<14} | {actual_count:<12} | {full_count:<10} | {status_str}")
            result["details"].append({
                "node": node,
                "expected": expected_count,
                "actual": actual_count,
                "full": full_count,
                "passed": node_ok
            })

    print(f"\n{C_CYAN}1.2 Verifying Loopback Reachability (10 System + 4 Anycast) in Routing Tables...{C_RESET}")
    all_loopbacks = set(ALL_SYSTEM_IPS + ALL_ANYCAST_IPS)
    nodes_missing_loopbacks = {}

    def check_routes_node(node):
        rc, data, err = run_sr_cli(node, "show network-instance default ipv4 route")
        return node, rc, data, err

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(check_routes_node, n) for n in ROUTERS.keys()]
        for f in futures:
            node, rc, data, err = f.result()
            if rc != 0 or not data:
                nodes_missing_loopbacks[node] = list(all_loopbacks)
                continue

            routes = data.get("instance", [{}])[0].get("ip route", [])
            installed_prefixes = set(r.get("Prefix", "").split("/")[0] for r in routes)

            local_ips = {ROUTERS[node]["system_ip"]}
            if "anycast_ip" in ROUTERS[node]:
                local_ips.add(ROUTERS[node]["anycast_ip"])

            missing = all_loopbacks - (installed_prefixes | local_ips)
            if missing:
                nodes_missing_loopbacks[node] = list(missing)

    if not nodes_missing_loopbacks:
        print_result_badge(True, "All 10 routers have full visibility and reachability to all 14 Underlay Loopbacks (/32)")
    else:
        result["passed"] = False
        print_result_badge(False, f"Loopbacks missing on {len(nodes_missing_loopbacks)} nodes: {nodes_missing_loopbacks}")

    return result


# ------------------------------------------------------------------------------
# Test 2: BGP Overlay Verification
# ------------------------------------------------------------------------------
def test_2_bgp_overlay() -> Dict[str, Any]:
    print_banner("TEST 2: iBGP EVPN Overlay Session Verification (AS 65000)")
    result = {"test": "BGP Overlay", "passed": True, "details": []}

    table_header = f"{'Router':<10} | {'Role':<12} | {'Expected Peers':<15} | {'Established':<12} | {'Status':<8}"
    print(f"  {table_header}")
    print(f"  {'-' * len(table_header)}")

    def check_bgp_node(node):
        info = ROUTERS[node]
        role = "Core RR" if info["role"] == "core" else f"Agg Pair {info['pair']}"
        expected_peers = 9 if info["role"] == "core" else 3
        rc, data, err = run_sr_cli(node, "show network-instance default protocols bgp neighbor")
        return node, role, expected_peers, rc, data, err

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(check_bgp_node, n) for n in ROUTERS.keys()]
        for f in sorted(futures, key=lambda fut: fut.result()[0]):
            node, role, expected_peers, rc, data, err = f.result()
            if rc != 0 or not data or "neighbor summary" not in data:
                result["passed"] = False
                print(f"  {node:<10} | {role:<12} | {expected_peers:<15} | {'ERROR':<12} | {C_RED}FAIL{C_RESET}")
                result["details"].append({"node": node, "status": "ERROR", "error": err})
                continue

            peers = data["neighbor summary"][0].get("state", [])
            actual_peers = len(peers)
            estab_peers = [p for p in peers if p.get("State", "").lower() == "established"]
            estab_count = len(estab_peers)

            info = ROUTERS[node]
            if info["role"] == "core":
                other_core = "core-2" if node == "core-1" else "core-1"
                expected_peer_ips = {ROUTERS[other_core]["system_ip"]} | {
                    ROUTERS[a]["system_ip"] for a in ROUTERS if ROUTERS[a]["role"] == "agg"
                }
            else:
                expected_peer_ips = {"10.0.0.1", "10.0.0.2", info["partner_ip"]}

            actual_estab_ips = set(p.get("Peer") for p in estab_peers)
            peers_match = (actual_estab_ips == expected_peer_ips)

            node_ok = (actual_peers == expected_peers and estab_count == expected_peers and peers_match)
            if not node_ok:
                result["passed"] = False

            status_str = f"{C_GREEN}PASS{C_RESET}" if node_ok else f"{C_RED}FAIL{C_RESET}"
            print(f"  {node:<10} | {role:<12} | {expected_peers:<15} | {estab_count:<12} | {status_str}")

            result["details"].append({
                "node": node,
                "role": role,
                "expected_peers": expected_peers,
                "actual_peers": actual_peers,
                "established_peers": estab_count,
                "passed": node_ok
            })

    return result


# ------------------------------------------------------------------------------
# Test 3: EVPN Anycast Multihoming & LAG Verification
# ------------------------------------------------------------------------------
def test_3_evpn_multihoming_and_lacp() -> Dict[str, Any]:
    print_banner("TEST 3: EVPN Anycast Multihoming & LACP Bonding Verification")
    result = {"test": "EVPN Multihoming & LACP", "passed": True, "details": []}

    print(f"{C_CYAN}3.1 Verifying Ethernet Segments on Aggregation Routers...{C_RESET}")
    def check_es(node):
        info = ROUTERS[node]
        rc, data, err = run_sr_cli(node, "show system network-instance ethernet-segments")
        return node, info, rc, data, err

    aggs = [n for n, d in ROUTERS.items() if d["role"] == "agg"]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(check_es, n) for n in aggs]
        for f in sorted(futures, key=lambda fut: fut.result()[0]):
            node, info, rc, data, err = f.result()
            if rc != 0 or not data:
                result["passed"] = False
                print_result_badge(False, f"{node}: Failed to query ethernet-segments: {err}")
                continue

            es_list = data.get("Ethernet-Segment", [])
            up_es = [
                es for es in es_list
                if es.get("Oper State") == "up"
                and es.get("Oper multi homing") == "all-active"
                and info["partner_ip"] in es.get("Info", {}).get("Peers", "")
            ]

            if len(up_es) == 2:
                print_result_badge(True, f"{node}: 2/2 Ethernet Segments Oper UP (all-active mode, peer {info['partner_ip']})")
            else:
                result["passed"] = False
                print_result_badge(False, f"{node}: {len(up_es)}/2 Ethernet Segments Oper UP matching peer {info['partner_ip']}")

    print(f"\n{C_CYAN}3.2 Verifying LACP LAG State on Multihomed Linux Hosts...{C_RESET}")
    mh_hosts = [h for h, d in HOSTS.items() if d["type"] == "multi"]

    def check_host_lacp(host):
        h_info = HOSTS[host]
        cname = f"{PREFIX}-{host}"
        rc, stdout, stderr = run_docker(cname, ["cat", "/proc/net/bonding/bond0"])
        return host, h_info, rc, stdout, stderr

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(check_host_lacp, h) for h in mh_hosts]
        for f in sorted(futures, key=lambda fut: fut.result()[0]):
            host, h_info, rc, stdout, stderr = f.result()
            if rc != 0:
                result["passed"] = False
                print_result_badge(False, f"{host}: Unable to read /proc/net/bonding/bond0")
                continue

            has_2_ports = "Number of ports: 2" in stdout
            has_lacp = "Bonding Mode: IEEE 802.3ad Dynamic link aggregation" in stdout
            has_partner_mac = h_info["sys_mac"].lower() in stdout.lower()
            has_slaves_up = stdout.count("MII Status: up") >= 3
            has_fast_rate = "LACP rate: fast" in stdout

            host_ok = has_2_ports and has_lacp and has_partner_mac and has_slaves_up and has_fast_rate
            if not host_ok:
                result["passed"] = False

            detail = f"Active Aggregator: 2 ports, Partner SysMAC: {h_info['sys_mac']}, LACP rate: fast"
            print_result_badge(host_ok, f"{host} (bond0): 802.3ad Dual-Homed LACP Operational", detail)
            result["details"].append({"host": host, "passed": host_ok, "detail": detail})

    return result


# ------------------------------------------------------------------------------
# Test 4: Route Scale and Filtering Verification (CRITICAL)
# ------------------------------------------------------------------------------
def test_4_route_scale_and_filtering() -> Dict[str, Any]:
    print_banner("TEST 4: Route Scale & Filtering Policy Verification (CRITICAL)")
    result = {"test": "Route Scale and Filtering", "passed": True, "details": []}

    print(f"{C_CYAN}4.1 Priming ARP Across All 24 Campus Hosts...{C_RESET}")
    def prime_host(h_name):
        h = HOSTS[h_name]
        return host_ping(h_name, h["gw"], count=1, timeout=2)

    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(prime_host, h): h for h in HOSTS.keys()}
        for f in as_completed(futures):
            f.result()

    print(f"  {C_GREEN}ARP entries primed on all first-hop routers. Allowing 2s for ISL BGP sync...{C_RESET}")
    time.sleep(2)

    # 4.2 Core Verification: Confirm /24 subnets present; Confirm /32 host routes NOT present
    print(f"\n{C_CYAN}4.2 Verifying Core Route Reflectors (core-1 & core-2)...{C_RESET}")
    for core in ["core-1", "core-2"]:
        rc, data, err = run_sr_cli(core, "show network-instance default protocols bgp routes evpn route-type 5 summary")
        if rc != 0 or not data:
            result["passed"] = False
            print_result_badge(False, f"{core}: Failed to fetch EVPN Type 5 routes: {err}")
            continue

        entries = data.get("summary", [{}])[0].get("ip_prefix", [])
        installed_prefixes = set()
        for e in entries:
            p = e.get("IP-address", "")
            if p:
                installed_prefixes.add(p)

        # Check /24 subnets
        p24_present = [p for p in installed_prefixes if p.endswith("/24")]
        missing_24 = set(SUBNETS_24) - set(p24_present)
        subnets_ok = (len(missing_24) == 0)

        # Check /32 single-homed host routes
        leaked_32 = [p for p in installed_prefixes if p.endswith("/32")]
        scale_ok = (len(leaked_32) == 0)

        core_ok = subnets_ok and scale_ok
        if not core_ok:
            result["passed"] = False

        detail = f"Subnet Prefixes (/24): {len(set(p24_present))}/8 present | Leaked Host Prefixes (/32): {len(leaked_32)}"
        print_result_badge(core_ok, f"{core}: EVPN Type 5 Scale Requirements Satisfied", detail)
        if leaked_32:
            print(f"         {C_RED}CRITICAL VIOLATION: Cores received /32 host routes: {leaked_32}{C_RESET}")

        result["details"].append({
            "core": core,
            "subnets_ok": subnets_ok,
            "scale_ok": scale_ok,
            "missing_24": list(missing_24),
            "leaked_32": leaked_32
        })

    # 4.3 Aggregation Pair Verification: Confirm /32 host routes exchanged across ISL
    print(f"\n{C_CYAN}4.3 Verifying Single-Homed Host Routes (/32) Synchronized Across ISLs...{C_RESET}")
    
    # Pre-fetch EVPN route-type 5 tables for all 8 aggs concurrently
    aggs = [f"agg-{i}" for i in range(1, 9)]
    agg_evpn_tables = {}

    def fetch_agg_evpn(node):
        rc, data, err = run_sr_cli(node, "show network-instance default protocols bgp routes evpn route-type 5 summary")
        if rc == 0 and data:
            return node, data.get("summary", [{}])[0].get("ip_prefix", [])
        return node, []

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_agg_evpn, a) for a in aggs]
        for f in futures:
            node, table = f.result()
            agg_evpn_tables[node] = table

    sh_hosts = [h for h, d in HOSTS.items() if d["type"] == "single"]

    table_header = f"{'Host':<10} | {'IP Address':<15} | {'Attached Agg':<12} | {'Partner Agg':<12} | {'Learned via ISL':<18} | {'Status':<8}"
    print(f"  {table_header}")
    print(f"  {'-' * len(table_header)}")

    for host in sorted(sh_hosts):
        h_info = HOSTS[host]
        attached_agg = h_info["agg"]
        partner_agg = ROUTERS[attached_agg]["partner"]
        target_ip = f"{h_info['ip']}/32"
        partner_table = agg_evpn_tables.get(partner_agg, [])

        learned = any(
            e.get("IP-address") == target_ip and e.get("neighbor") == ROUTERS[attached_agg]["system_ip"]
            for e in partner_table
        )

        if not learned:
            result["passed"] = False

        status_str = f"{C_GREEN}PASS{C_RESET}" if learned else f"{C_RED}FAIL{C_RESET}"
        print(f"  {host:<10} | {target_ip:<15} | {attached_agg:<12} | {partner_agg:<12} | {str(learned):<18} | {status_str}")

        result["details"].append({
            "host": host,
            "ip": target_ip,
            "attached_agg": attached_agg,
            "partner_agg": partner_agg,
            "learned_via_isl": learned
        })

    return result


# ------------------------------------------------------------------------------
# Test 5: End-to-End Data Plane Traffic Matrix
# ------------------------------------------------------------------------------
def test_5_dataplane_traffic_matrix() -> Dict[str, Any]:
    print_banner("TEST 5: End-to-End Campus Data Plane Traffic Matrix")
    result = {"test": "Data Plane Traffic Matrix", "passed": True, "categories": {}}

    matrix_tests = [
        # Category 1: Intra-VLAN Single-Homed <-> Single-Homed
        {"cat": "1. Intra-VLAN Single-to-Single", "src": "h1-v101", "dst": "h2-v101", "ip": "10.1.1.12", "desc": "Pair 1 VLAN 101 (agg-1 <-> agg-2)"},
        {"cat": "1. Intra-VLAN Single-to-Single", "src": "h2-v101", "dst": "h1-v101", "ip": "10.1.1.11", "desc": "Pair 1 VLAN 101 (agg-2 <-> agg-1)"},
        {"cat": "1. Intra-VLAN Single-to-Single", "src": "h1-v102", "dst": "h2-v102", "ip": "10.1.2.12", "desc": "Pair 1 VLAN 102 (agg-1 <-> agg-2)"},
        {"cat": "1. Intra-VLAN Single-to-Single", "src": "h1-v201", "dst": "h2-v201", "ip": "10.2.1.12", "desc": "Pair 2 VLAN 201 (agg-3 <-> agg-4)"},
        {"cat": "1. Intra-VLAN Single-to-Single", "src": "h1-v301", "dst": "h2-v301", "ip": "10.3.1.12", "desc": "Pair 3 VLAN 301 (agg-5 <-> agg-6)"},
        {"cat": "1. Intra-VLAN Single-to-Single", "src": "h1-v401", "dst": "h2-v401", "ip": "10.4.1.12", "desc": "Pair 4 VLAN 401 (agg-7 <-> agg-8)"},

        # Category 2: Intra-VLAN Multihomed <-> Single-Homed
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v101", "dst": "h1-v101", "ip": "10.1.1.11", "desc": "Pair 1 VLAN 101 (LAG-1 <-> agg-1)"},
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v101", "dst": "h2-v101", "ip": "10.1.1.12", "desc": "Pair 1 VLAN 101 (LAG-1 <-> agg-2)"},
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v102", "dst": "h1-v102", "ip": "10.1.2.11", "desc": "Pair 1 VLAN 102 (LAG-2 <-> agg-1)"},
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v201", "dst": "h1-v201", "ip": "10.2.1.11", "desc": "Pair 2 VLAN 201 (LAG-1 <-> agg-3)"},
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v201", "dst": "h2-v201", "ip": "10.2.1.12", "desc": "Pair 2 VLAN 201 (LAG-1 <-> agg-4)"},
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v301", "dst": "h1-v301", "ip": "10.3.1.11", "desc": "Pair 3 VLAN 301 (LAG-1 <-> agg-5)"},
        {"cat": "2. Intra-VLAN Multi-to-Single", "src": "hm-v401", "dst": "h1-v401", "ip": "10.4.1.11", "desc": "Pair 4 VLAN 401 (LAG-1 <-> agg-7)"},

        # Category 3: Inter-VLAN Local within Same Pair
        {"cat": "3. Inter-VLAN Local Routing", "src": "h1-v101", "dst": "h1-v102", "ip": "10.1.2.11", "desc": "Pair 1 (VLAN 101 -> VLAN 102)"},
        {"cat": "3. Inter-VLAN Local Routing", "src": "h1-v101", "dst": "h2-v102", "ip": "10.1.2.12", "desc": "Pair 1 (VLAN 101 -> VLAN 102 cross-agg)"},
        {"cat": "3. Inter-VLAN Local Routing", "src": "hm-v101", "dst": "hm-v102", "ip": "10.1.2.10", "desc": "Pair 1 (hm-v101 -> hm-v102)"},
        {"cat": "3. Inter-VLAN Local Routing", "src": "h1-v201", "dst": "h1-v202", "ip": "10.2.2.11", "desc": "Pair 2 (VLAN 201 -> VLAN 202)"},
        {"cat": "3. Inter-VLAN Local Routing", "src": "h1-v301", "dst": "h1-v302", "ip": "10.3.2.11", "desc": "Pair 3 (VLAN 301 -> VLAN 302)"},
        {"cat": "3. Inter-VLAN Local Routing", "src": "h1-v401", "dst": "h1-v402", "ip": "10.4.2.11", "desc": "Pair 4 (VLAN 401 -> VLAN 402)"},

        # Category 4: Cross-Pair Inter-Subnet Fabric Routing
        {"cat": "4. Cross-Pair Fabric Routing", "src": "h1-v101", "dst": "h1-v201", "ip": "10.2.1.11", "desc": "Pair 1 (Bldg 1) -> Pair 2 (Bldg 2)"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "h1-v101", "dst": "h2-v201", "ip": "10.2.1.12", "desc": "Pair 1 (Bldg 1) -> Pair 2 (Bldg 2 agg-4)"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "hm-v101", "dst": "hm-v201", "ip": "10.2.1.10", "desc": "Pair 1 Multi -> Pair 2 Multi"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "h1-v101", "dst": "h1-v301", "ip": "10.3.1.11", "desc": "Pair 1 (Bldg 1) -> Pair 3 (Bldg 3)"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "h1-v101", "dst": "h1-v401", "ip": "10.4.1.11", "desc": "Pair 1 (Bldg 1) -> Pair 4 (Bldg 4)"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "h1-v201", "dst": "h1-v301", "ip": "10.3.1.11", "desc": "Pair 2 (Bldg 2) -> Pair 3 (Bldg 3)"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "h1-v301", "dst": "h1-v401", "ip": "10.4.1.11", "desc": "Pair 3 (Bldg 3) -> Pair 4 (Bldg 4)"},
        {"cat": "4. Cross-Pair Fabric Routing", "src": "hm-v401", "dst": "hm-v101", "ip": "10.1.1.10", "desc": "Pair 4 Multi -> Pair 1 Multi"},

        # Category 5: Asymmetric ISL Transit Testing
        {"cat": "5. Asymmetric ISL Transit", "src": "h2-v201", "dst": "h1-v101", "ip": "10.1.1.11", "desc": "Pair 2 agg-4 -> Pair 1 agg-1 (ISL transit)"},
        {"cat": "5. Asymmetric ISL Transit", "src": "h1-v201", "dst": "h2-v101", "ip": "10.1.1.12", "desc": "Pair 2 agg-3 -> Pair 1 agg-2 (ISL transit)"},
    ]

    current_cat = ""
    for test in matrix_tests:
        if test["cat"] != current_cat:
            current_cat = test["cat"]
            print(f"\n{C_CYAN}--- {current_cat} ---{C_RESET}")
            table_header = f"{'Source':<10} | {'Destination':<10} | {'Target IP':<15} | {'RTT (ms)':<10} | {'Description':<42} | {'Status':<8}"
            print(f"  {table_header}")
            print(f"  {'-' * len(table_header)}")

        ok, loss, rtt, raw = host_ping(test["src"], test["ip"], count=2, timeout=2)
        if not ok:
            # Retry once
            ok, loss, rtt, raw = host_ping(test["src"], test["ip"], count=2, timeout=2)

        if not ok:
            result["passed"] = False

        status_str = f"{C_GREEN}PASS{C_RESET}" if ok else f"{C_RED}FAIL{C_RESET}"
        rtt_str = f"{rtt:.2f}" if ok else (f"LOSS {loss:.0f}%" if loss > 0 else "TIMEOUT")
        print(f"  {test['src']:<10} | {test['dst']:<10} | {test['ip']:<15} | {rtt_str:<10} | {test['desc']:<42} | {status_str}")

        if current_cat not in result["categories"]:
            result["categories"][current_cat] = []
        result["categories"][current_cat].append({
            "src": test["src"],
            "dst": test["dst"],
            "target_ip": test["ip"],
            "loss_pct": loss,
            "rtt_ms": rtt,
            "passed": ok
        })

    return result


# ------------------------------------------------------------------------------
# Test 6: Resiliency and Failure Recovery
# ------------------------------------------------------------------------------
def test_6_resiliency_failure_recovery() -> Dict[str, Any]:
    print_banner("TEST 6: Resiliency, Link Failure Simulation & Auto-Recovery")
    result = {"test": "Resiliency and Failure Recovery", "passed": True, "steps": []}

    target_node = "agg-1"
    target_intf = "ethernet-1/3"  # Uplink to core-1
    test_src = "h1-v101"          # Single-homed on agg-1
    test_dst = "h1-v201"          # On Pair 2 (10.2.1.11)
    target_ip = HOSTS[test_dst]["ip"]

    print(f"{C_CYAN}6.1 Baseline Verification: Active direct uplink agg-1 -> core-1...{C_RESET}")
    ok_base, loss_base, rtt_base, _ = host_ping(test_src, target_ip, count=2, timeout=2)
    print_result_badge(ok_base, f"Baseline ping from {test_src} to {test_dst} ({target_ip})", f"{loss_base:.0f}% Packet Loss, RTT: {rtt_base:.2f} ms")

    # Step 1: Simulate Uplink Failure by disabling ethernet-1/3 on agg-1
    print(f"\n{C_CYAN}6.2 Simulating Uplink Failure: Disabling {target_intf} on {target_node}...{C_RESET}")
    disable_cmd = f"enter candidate\nset / interface {target_intf} admin-state disable\ncommit now"
    rc, stdout, stderr = run_docker(f"{PREFIX}-{target_node}", ["bash", "-c", f"echo -e '{disable_cmd}' | sr_cli"])

    if rc != 0 or "committed" not in stdout:
        result["passed"] = False
        print_result_badge(False, f"Failed to disable interface {target_intf} on {target_node}: {stderr or stdout}")
        return result

    print_result_badge(True, f"Interface {target_intf} on {target_node} administratively disabled")

    # Step 2: Verify OSPF neighbor on uplink is removed
    rc, data, err = run_sr_cli(target_node, "show network-instance default protocols ospf neighbor")
    uplink_nbr_present = False
    if rc == 0 and data and "instances" in data:
        for n in data["instances"][0].get("neighbors_brief", []):
            if n.get("Interface-Name") == f"{target_intf}.0":
                uplink_nbr_present = True

    step2_ok = not uplink_nbr_present
    print_result_badge(step2_ok, f"OSPF Underlay Neighbor to Core-1 removed on {target_node}:{target_intf}")
    if not step2_ok:
        result["passed"] = False

    # Step 3: Verify BGP Overlay session to Core-1 remains ESTABLISHED via ISL redirect
    rc, data, err = run_sr_cli(target_node, "show network-instance default protocols bgp neighbor")
    core1_peer_estab = False
    if rc == 0 and data and "neighbor summary" in data:
        for p in data["neighbor summary"][0].get("state", []):
            if p.get("Peer") == "10.0.0.1" and p.get("State", "").lower() == "established":
                core1_peer_estab = True

    print_result_badge(core1_peer_estab, f"iBGP EVPN session to Core-1 remains ESTABLISHED (routed across ISL via agg-2)")
    if not core1_peer_estab:
        result["passed"] = False

    # Step 4: Verify traffic forwarding during uplink failure across ISL to agg-2 -> core-2
    print(f"\n{C_CYAN}6.3 Testing Data Plane Transit Across ISL during Uplink Outage...{C_RESET}")
    ok_failover, loss_failover, rtt_failover, out_failover = host_ping(test_src, target_ip, count=3, timeout=3)
    print_result_badge(ok_failover, f"Traffic successfully redirected across ISL ({test_src} -> agg-1 -> agg-2 -> core-2 -> {test_dst})", f"{loss_failover:.0f}% Packet Loss, RTT: {rtt_failover:.2f} ms")
    if not ok_failover:
        result["passed"] = False

    # Step 5: Restore interface ethernet-1/3 on agg-1
    print(f"\n{C_CYAN}6.4 Restoring Uplink: Re-enabling {target_intf} on {target_node}...{C_RESET}")
    enable_cmd = f"enter candidate\nset / interface {target_intf} admin-state enable\ncommit now"
    rc, stdout, stderr = run_docker(f"{PREFIX}-{target_node}", ["bash", "-c", f"echo -e '{enable_cmd}' | sr_cli"])
    print_result_badge(rc == 0 and "committed" in stdout, f"Interface {target_intf} on {target_node} administratively re-enabled")

    # Step 6: Wait for OSPF re-convergence
    print(f"  Waiting up to 15 seconds for OSPF adjacency re-convergence...")
    reconverged = False
    for _ in range(15):
        time.sleep(1)
        rc, data, err = run_sr_cli(target_node, "show network-instance default protocols ospf neighbor")
        if rc == 0 and data and "instances" in data:
            for n in data["instances"][0].get("neighbors_brief", []):
                if n.get("Interface-Name") == f"{target_intf}.0" and n.get("State", "").lower() == "full":
                    reconverged = True
                    break
        if reconverged:
            break

    print_result_badge(reconverged, f"OSPF Adjacency to Core-1 re-established to FULL state")
    if not reconverged:
        result["passed"] = False

    # Step 7: Verify normal ping after recovery
    ok_recov, loss_recov, rtt_recov, _ = host_ping(test_src, target_ip, count=2, timeout=2)
    print_result_badge(ok_recov, f"Normal path restored ({test_src} -> {test_dst})", f"{loss_recov:.0f}% Packet Loss, RTT: {rtt_recov:.2f} ms")
    if not ok_recov:
        result["passed"] = False

    result["steps"] = [
        {"step": "baseline", "passed": ok_base, "rtt_ms": rtt_base},
        {"step": "link_down_ospf_drop", "passed": step2_ok},
        {"step": "bgp_session_preserved_via_isl", "passed": core1_peer_estab},
        {"step": "failover_traffic_forwarded", "passed": ok_failover, "rtt_ms": rtt_failover},
        {"step": "reconvergence_full", "passed": reconverged},
        {"step": "post_recovery_traffic", "passed": ok_recov, "rtt_ms": rtt_recov}
    ]

    return result


# ------------------------------------------------------------------------------
# Executive Summary and Main Driver
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Campus EVPN-VXLAN Verification Test Suite")
    parser.add_argument("--test", help="Comma-separated test numbers to run (1-6)", default="all")
    parser.add_argument("--json-report", help="Save test results to specified JSON file", default=None)
    args = parser.parse_args()

    tests_to_run = [1, 2, 3, 4, 5, 6] if args.test == "all" else [int(t.strip()) for t in args.test.split(",")]

    start_time = time.time()
    results = {}

    print(f"\n{C_BOLD}{C_MAGENTA}{'#' * 90}{C_RESET}")
    print(f"{C_BOLD}{C_MAGENTA}#  Campus EVPN-VXLAN Automated Verification & Acceptance Suite  #{C_RESET}".center(98))
    print(f"{C_BOLD}{C_MAGENTA}{'#' * 90}{C_RESET}\n")

    if 1 in tests_to_run:
        results["test_1"] = test_1_ospf_underlay()
    if 2 in tests_to_run:
        results["test_2"] = test_2_bgp_overlay()
    if 3 in tests_to_run:
        results["test_3"] = test_3_evpn_multihoming_and_lacp()
    if 4 in tests_to_run:
        results["test_4"] = test_4_route_scale_and_filtering()
    if 5 in tests_to_run:
        results["test_5"] = test_5_dataplane_traffic_matrix()
    if 6 in tests_to_run:
        results["test_6"] = test_6_resiliency_failure_recovery()

    duration = time.time() - start_time

    # Executive Summary
    print_banner("EXECUTIVE VERIFICATION SUMMARY")
    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r["passed"])
    all_passed = (passed_tests == total_tests)

    table_header = f"{'Test Suite':<45} | {'Scope':<20} | {'Status':<10}"
    print(f"  {table_header}")
    print(f"  {'-' * len(table_header)}")

    test_titles = {
        "test_1": ("Test 1: OSPF Underlay Convergence", "10 Routers, 14 LBs"),
        "test_2": ("Test 2: iBGP EVPN Overlay Sessions", "36 BGP Sessions"),
        "test_3": ("Test 3: EVPN Multihoming & LACP", "16 ES, 8 LAGs"),
        "test_4": ("Test 4: Route Scale & Filtering", "8 Subnets, 16 Host Rts"),
        "test_5": ("Test 5: Campus Data Plane Matrix", "29 End-to-End Pings"),
        "test_6": ("Test 6: Uplink Resiliency & Recovery", "Link Outage Simulation"),
    }

    for key, r in results.items():
        title, scope = test_titles.get(key, (r["test"], "All Nodes"))
        st = f"{C_GREEN}PASS{C_RESET}" if r["passed"] else f"{C_RED}FAIL{C_RESET}"
        print(f"  {title:<45} | {scope:<20} | {st:<10}")

    print(f"  {'-' * len(table_header)}")
    print(f"  Total Duration: {duration:.2f} seconds")
    print(f"  Overall Score : {passed_tests}/{total_tests} Test Suites Passed ({passed_tests/total_tests*100:.1f}%)\n")

    if all_passed:
        print(f"  {C_BG_GREEN} FINAL VERDICT: ALL TEST SUITES PASSED - CAMPUS FABRIC FULLY COMPLIANT {C_RESET}\n")
    else:
        print(f"  {C_BG_RED} FINAL VERDICT: TEST SUITE FAILURES DETECTED - REVIEW LOGS ABOVE {C_RESET}\n")

    if args.json_report:
        report_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": duration,
            "overall_passed": all_passed,
            "passed_suites": passed_tests,
            "total_suites": total_tests,
            "results": results
        }
        with open(args.json_report, "w") as f:
            json.dump(report_data, f, indent=2)
        print(f"  Test results successfully exported to JSON: {args.json_report}\n")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
