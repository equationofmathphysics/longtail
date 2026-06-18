from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_ENDPOINT_PORT = 51820
DEFAULT_WG_IFACE = "wg0"
DEFAULT_WG_CONF = Path("/etc/wireguard/wg0.conf")
DEFAULT_WG_SUBNET = "10.66.0"
DEFAULT_WG_CIDR = "10.66.0.0/24"
DEFAULT_SERVER_VPN_IP = "10.66.0.1"
DEFAULT_ADMIN_NAME = "phone"
ENV_PATH = Path("/etc/longtail/longtail.env")
SYSCTL_PATH = Path("/etc/sysctl.d/99-longtail.conf")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class BootstrapError(RuntimeError):
    pass


def run(args: list[str], input_text: str | None = None, check: bool = True) -> str:
    result = subprocess.run(args, input=input_text, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise BootstrapError(f"{' '.join(args)}: {detail}")
    return result.stdout


def normalize_endpoint(value: str) -> tuple[str, int]:
    raw = value.strip()
    if "://" in raw:
        raw = raw.split("://", 1)[1].strip("/")
    if not raw:
        raise BootstrapError("server endpoint is required")

    host: str
    port_text: str
    if raw.startswith("["):
        match = re.fullmatch(r"\[([^\]]+)\](?::(\d+))?", raw)
        if not match:
            raise BootstrapError(f"endpoint is not valid: {value}")
        host = match.group(1)
        port_text = match.group(2) or str(DEFAULT_ENDPOINT_PORT)
        endpoint = f"[{host}]:{port_text}"
    elif raw.count(":") == 0:
        host = raw
        port_text = str(DEFAULT_ENDPOINT_PORT)
        endpoint = f"{host}:{port_text}"
    elif raw.count(":") == 1:
        host, port_text = raw.rsplit(":", 1)
        endpoint = raw
    else:
        host = raw
        port_text = str(DEFAULT_ENDPOINT_PORT)
        endpoint = f"[{host}]:{port_text}"

    if not host:
        raise BootstrapError(f"endpoint host is empty: {value}")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise BootstrapError(f"endpoint port is not valid: {value}") from exc
    if not 1 <= port <= 65535:
        raise BootstrapError(f"endpoint port is out of range: {port}")
    return endpoint, port


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def update_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    lines: list[str] = []
    key_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

    for line in existing:
        match = key_re.match(line)
        if match and match.group(1) in values:
            key = match.group(1)
            lines.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            lines.append(line)

    missing = [key for key in values if key not in seen]
    if missing and lines and lines[-1].strip():
        lines.append("")
    for key in missing:
        lines.append(f"{key}={values[key]}")

    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_wireguard_config(path: Path, listen_port: int) -> bool:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*PrivateKey\s*=", text, re.MULTILINE):
            os.chmod(path, 0o600)
            return False
        raise BootstrapError(f"{path} exists but does not contain an Interface PrivateKey")

    private_key = run(["wg", "genkey"]).strip()
    prefix = DEFAULT_WG_CIDR.split("/", 1)[1]
    text = (
        "[Interface]\n"
        f"Address = {DEFAULT_SERVER_VPN_IP}/{prefix}\n"
        f"ListenPort = {listen_port}\n"
        f"PrivateKey = {private_key}\n"
    )
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def systemd_available() -> bool:
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").exists()


def interface_exists(iface: str) -> bool:
    return subprocess.run(["ip", "link", "show", "dev", iface], capture_output=True, text=True, check=False).returncode == 0


def ensure_wireguard_running(iface: str) -> None:
    if systemd_available():
        run(["systemctl", "enable", "--now", f"wg-quick@{iface}"])
        return
    if not interface_exists(iface):
        run(["wg-quick", "up", iface])


def ensure_ip_forwarding() -> None:
    SYSCTL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYSCTL_PATH.write_text("net.ipv4.ip_forward=1\n", encoding="utf-8")
    os.chmod(SYSCTL_PATH, 0o644)
    if shutil.which("sysctl"):
        run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    else:
        Path("/proc/sys/net/ipv4/ip_forward").write_text("1\n", encoding="utf-8")


def ensure_admin_peer(admin_name: str) -> tuple[str, str, bool]:
    from .config import Settings
    from .wg_manager import WireGuardManager

    manager = WireGuardManager(Settings())
    peers = {peer.name for peer in manager.list_peers()}
    created = admin_name not in peers
    if created:
        result = manager.add_peer(admin_name)
        config = result["config"]
        ip = result["ip"]
    else:
        config = manager.client_config(admin_name)
        peer = next(peer for peer in manager.list_peers() if peer.name == admin_name)
        ip = peer.ip
    manager.set_peer_admin(admin_name, True)
    return config, ip, created


def print_qr(config: str) -> None:
    if shutil.which("qrencode") is None:
        return
    qr = run(["qrencode", "-t", "ANSIUTF8"], input_text=config, check=False)
    if qr.strip():
        print(qr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize Longtail WireGuard server and first admin peer.")
    parser.add_argument("endpoint", help="public server endpoint, for example vpn.example.com or vpn.example.com:51820")
    parser.add_argument("admin_name", nargs="?", default=DEFAULT_ADMIN_NAME, help="initial admin peer name")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("bootstrap must run as root; use sudo")

    try:
        endpoint, port = normalize_endpoint(args.endpoint)
        if not NAME_RE.fullmatch(args.admin_name):
            raise BootstrapError("initial admin peer name must be 1-32 letters, numbers, underscores, dots, or dashes")
        env_values = {
            "NET_TOOLS_SERVER_ENDPOINT": endpoint,
            "NET_TOOLS_WG_CONF": str(DEFAULT_WG_CONF),
            "NET_TOOLS_WG_IFACE": DEFAULT_WG_IFACE,
            "NET_TOOLS_WG_SUBNET": DEFAULT_WG_SUBNET,
            "NET_TOOLS_WG_CIDR": DEFAULT_WG_CIDR,
            "NET_TOOLS_SERVER_VPN_IP": DEFAULT_SERVER_VPN_IP,
            "NET_TOOLS_WG_PORT": str(port),
            "NET_TOOLS_CLIENT_ALLOWED_IPS": DEFAULT_WG_CIDR,
            "NET_TOOLS_ADMIN_IPS": f"127.0.0.1,::1,{DEFAULT_SERVER_VPN_IP}",
            "NET_TOOLS_INITIAL_ADMIN_PEERS": args.admin_name,
            "NET_TOOLS_FIREWALL_ENABLED": "1",
            "NET_TOOLS_BIND_HOST": DEFAULT_SERVER_VPN_IP,
        }

        update_env(ENV_PATH, env_values)
        os.environ.update(read_env(ENV_PATH))
        created_config = ensure_wireguard_config(DEFAULT_WG_CONF, port)
        ensure_ip_forwarding()
        ensure_wireguard_running(DEFAULT_WG_IFACE)
        config, admin_ip, created_peer = ensure_admin_peer(args.admin_name)

        print(f"Longtail env: {ENV_PATH}")
        print(f"WireGuard config: {DEFAULT_WG_CONF} ({'created' if created_config else 'reused'})")
        print(f"Initial admin peer: {args.admin_name} {admin_ip} ({'created' if created_peer else 'reused'})")
        print(f"Server endpoint: {endpoint}")
        print(f"Web console after VPN connects: http://{DEFAULT_SERVER_VPN_IP}:51437/")
        print("Scan this WireGuard config QR with the first admin device:")
        print_qr(config)
        return 0
    except BootstrapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
