import secrets
import socket
import subprocess
from ipaddress import IPv4Address, ip_address
from typing import Iterable, Optional

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghijkmnpqrstuvwxyz"

VIRTUAL_ADAPTER_KEYWORDS = (
    "anyconnect",
    "bluetooth",
    "hyper-v",
    "loopback",
    "openconnect",
    "tap",
    "teamviewer",
    "tunnel",
    "virtual",
    "virtualbox",
    "vmware",
    "vpn",
    "wintun",
    "xbox",
)

PREFERRED_ADAPTER_KEYWORDS = (
    "ethernet",
    "realtek",
    "wi-fi",
    "wifi",
    "wireless",
    "wlan",
    "以太网",
    "无线",
)


def parse_ipv4(value: str) -> Optional[IPv4Address]:
    try:
        parsed = ip_address(value.strip())
    except ValueError:
        return None

    if not isinstance(parsed, IPv4Address):
        return None
    return parsed


def is_usable_ipv4(address: IPv4Address) -> bool:
    return not (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def adapter_text(candidate: dict) -> str:
    return f"{candidate.get('alias', '')} {candidate.get('description', '')}".lower()


def score_candidate(candidate: dict) -> int:
    address = parse_ipv4(candidate.get("ip", ""))
    if not address or not is_usable_ipv4(address):
        return -1000

    text = adapter_text(candidate)
    gateway = candidate.get("gateway", "").strip()
    score = 0

    if address.is_private:
        score += 100
    if gateway and gateway != "0.0.0.0":
        score += 50
    if any(keyword in text for keyword in PREFERRED_ADAPTER_KEYWORDS):
        score += 20
    if any(keyword in text for keyword in VIRTUAL_ADAPTER_KEYWORDS):
        score -= 200

    return score


def windows_ip_candidates() -> list[dict]:
    command = r"""
$items = Get-NetIPConfiguration | Where-Object {
    $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up'
}
foreach ($item in $items) {
    $ip = $item.IPv4Address.IPAddress
    $gateway = ""
    if ($item.IPv4DefaultGateway) {
        $gateway = $item.IPv4DefaultGateway.NextHop
    }
    Write-Output ($ip + "|" + $item.InterfaceAlias + "|" + $item.InterfaceDescription + "|" + $gateway)
}
"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    candidates: list[dict] = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) != 4:
            continue
        ip, alias, description, gateway = parts
        candidates.append(
            {
                "ip": ip.strip(),
                "alias": alias.strip(),
                "description": description.strip(),
                "gateway": gateway.strip(),
            }
        )

    return candidates


def socket_ip_candidates() -> list[dict]:
    candidates: list[dict] = []

    try:
        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family == socket.AF_INET:
                candidates.append({"ip": sockaddr[0], "alias": "hostname", "description": "", "gateway": ""})
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            candidates.append({"ip": sock.getsockname()[0], "alias": "route", "description": "", "gateway": ""})
    except OSError:
        pass

    return candidates


def choose_best_ip(candidates: Iterable[dict]) -> Optional[str]:
    ranked = sorted(candidates, key=score_candidate, reverse=True)
    if not ranked:
        return None

    best = ranked[0]
    if score_candidate(best) < 0:
        return None
    return best["ip"]


def get_host_ip() -> str:
    selected = choose_best_ip(windows_ip_candidates())
    if selected:
        return selected

    selected = choose_best_ip(socket_ip_candidates())
    if selected:
        return selected

    return "localhost"


def random_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


if __name__ == "__main__":
    print(f"{get_host_ip()}|{random_code(8)}|{random_code(12)}")
