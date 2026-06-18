from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DATA_DIR = Path(os.getenv("NET_TOOLS_DATA_DIR", "/var/lib/longtail"))
DEFAULT_BIND_PORT = os.getenv("NET_TOOLS_BIND_PORT", "51437")
DEFAULT_REQUIRED_PORTS = f"tcp/22,tcp/3389,udp/3389,tcp/{DEFAULT_BIND_PORT}"


@dataclass(frozen=True)
class Settings:
    wg_conf: Path = Path(os.getenv("NET_TOOLS_WG_CONF", "/etc/wireguard/wg0.conf"))
    wg_iface: str = os.getenv("NET_TOOLS_WG_IFACE", "wg0")
    wg_subnet: str = os.getenv("NET_TOOLS_WG_SUBNET", "10.66.0")
    wg_cidr: str = os.getenv("NET_TOOLS_WG_CIDR", "10.66.0.0/24")
    server_vpn_ip: str = os.getenv("NET_TOOLS_SERVER_VPN_IP", "10.66.0.1")
    server_endpoint: str = os.getenv("NET_TOOLS_SERVER_ENDPOINT", "")
    server_public_ip: str = os.getenv("NET_TOOLS_SERVER_PUBLIC_IP", "")
    wg_port: int = int(os.getenv("NET_TOOLS_WG_PORT", "51820"))
    dns: str = os.getenv("NET_TOOLS_DNS", "1.1.1.1, 1.0.0.1")
    clients_dir: Path = Path(os.getenv("NET_TOOLS_CLIENTS_DIR", str(DATA_DIR / "clients")))
    client_allowed_ips: str = os.getenv("NET_TOOLS_CLIENT_ALLOWED_IPS", "10.66.0.0/24")
    state_file: Path = Path(os.getenv("NET_TOOLS_STATE_FILE", str(DATA_DIR / "state.json")))
    hidden_peers: tuple[str, ...] = _csv_env("NET_TOOLS_HIDDEN_PEERS", "")
    admin_ips: tuple[str, ...] = _csv_env("NET_TOOLS_ADMIN_IPS", "127.0.0.1,::1")
    initial_admin_peers: tuple[str, ...] = _csv_env("NET_TOOLS_INITIAL_ADMIN_PEERS", "")
    admin_token: str = os.getenv("NET_TOOLS_ADMIN_TOKEN", "")
    trust_proxy_headers: bool = _bool_env("NET_TOOLS_TRUST_PROXY_HEADERS")
    firewall_enabled: bool = _bool_env("NET_TOOLS_FIREWALL_ENABLED", True)
    firewall_chain_prefix: str = os.getenv("NET_TOOLS_FIREWALL_CHAIN_PREFIX", "LONGTAIL")
    firewall_required_inbound_ports: str = os.getenv("NET_TOOLS_FIREWALL_REQUIRED_INBOUND_PORTS", DEFAULT_REQUIRED_PORTS)
    firewall_required_outbound_ports: str = os.getenv("NET_TOOLS_FIREWALL_REQUIRED_OUTBOUND_PORTS", DEFAULT_REQUIRED_PORTS)
    bind_host: str = os.getenv("NET_TOOLS_BIND_HOST", "0.0.0.0")
    bind_port: int = int(DEFAULT_BIND_PORT)
    lock_file: Path = Path(os.getenv("NET_TOOLS_LOCK_FILE", "/tmp/net-tools-wg.lock"))


settings = Settings()
