from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
PORT_RE = re.compile(r"^(?:(tcp|udp)/)?(\d{1,5})(?:[-:](\d{1,5}))?(?:/(tcp|udp))?$", re.IGNORECASE)


class WireGuardError(RuntimeError):
    pass


@dataclass
class Peer:
    name: str
    public_key: str
    ip: str
    enabled: bool
    latest_handshake: int | None = None
    rx_bytes: int = 0
    tx_bytes: int = 0

    @property
    def status(self) -> str:
        return "active" if self.enabled else "paused"


@dataclass(frozen=True)
class PortRule:
    protocol: str
    start: int
    end: int

    @property
    def display(self) -> str:
        port = str(self.start) if self.start == self.end else f"{self.start}-{self.end}"
        return f"{self.protocol}/{port}"

    @property
    def iptables_port(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}:{self.end}"

    def allows(self, protocol: str, port: int) -> bool:
        return self.protocol == protocol and self.start <= port <= self.end


class WireGuardManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.clients_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.settings.clients_dir, 0o700)

    @contextmanager
    def locked(self):
        self.settings.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with self.settings.lock_file.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def list_peers(self) -> list[Peer]:
        peers = self._parse_config()
        runtime = self._runtime_dump()
        for peer in peers:
            data = runtime.get(peer.public_key)
            if data:
                peer.latest_handshake = data["latest_handshake"]
                peer.rx_bytes = data["rx_bytes"]
                peer.tx_bytes = data["tx_bytes"]
        return peers

    def next_ip(self) -> str:
        return self._next_ip()

    def admin_peer_names(self) -> set[str]:
        state = self._read_state()
        return set(state.get("admin_peers", []))

    def admin_ips(self) -> set[str]:
        names = self.admin_peer_names()
        return {peer.ip for peer in self._parse_config() if peer.name in names and peer.enabled}

    def set_peer_admin(self, name: str, is_admin: bool) -> None:
        self._validate_name(name)
        if not self._find_peer(name, include_disabled=True):
            raise WireGuardError(f"用户不存在: {name}")
        with self.locked():
            state = self._read_state()
            names = set(state.get("admin_peers", []))
            if is_admin:
                names.add(name)
            else:
                names.discard(name)
            state["admin_peers"] = sorted(names)
            self._write_state(state)

    def firewall_policy(self) -> dict[str, str | bool]:
        policy = self._firewall_policy_state()
        required_inbound = self._normalize_port_spec(self.settings.firewall_required_inbound_ports)
        required_outbound = self._normalize_port_spec(self.settings.firewall_required_outbound_ports)
        trusted_inbound = self._normalize_port_spec(str(policy.get("trusted_inbound_ports", "")))
        trusted_outbound = self._normalize_port_spec(str(policy.get("trusted_outbound_ports", "")))
        effective_inbound = self._merge_port_specs(required_inbound, trusted_inbound)
        effective_outbound = self._merge_port_specs(required_outbound, trusted_outbound)
        return {
            "enabled": self.settings.firewall_enabled,
            "required_inbound_ports": required_inbound,
            "required_outbound_ports": required_outbound,
            "trusted_inbound_ports": trusted_inbound,
            "trusted_outbound_ports": trusted_outbound,
            "effective_inbound_ports": effective_inbound,
            "effective_outbound_ports": effective_outbound,
        }

    def set_firewall_policy(self, trusted_inbound_ports: str, trusted_outbound_ports: str) -> dict[str, str | bool]:
        trusted_inbound_ports = self._normalize_port_spec(trusted_inbound_ports)
        trusted_outbound_ports = self._normalize_port_spec(trusted_outbound_ports)
        with self.locked():
            state = self._read_state()
            state["firewall"] = {
                "trusted_inbound_ports": trusted_inbound_ports,
                "trusted_outbound_ports": trusted_outbound_ports,
            }
            self._write_state(state)
            self.apply_firewall()
        return self.firewall_policy()

    def apply_firewall(self) -> None:
        if not self.settings.firewall_enabled:
            self.clear_firewall()
            return

        inbound_chain = self._firewall_chain("IN")
        outbound_chain = self._firewall_chain("OUT")
        policy = self.firewall_policy()
        inbound_rules = self._parse_port_rules(str(policy["effective_inbound_ports"]))
        outbound_rules = self._parse_port_rules(str(policy["effective_outbound_ports"]))
        wg_network = str(ipaddress.ip_network(self.settings.wg_cidr, strict=False))

        self._ensure_firewall_chain(inbound_chain, [("INPUT", "-i"), ("FORWARD", "-i")])
        self._ensure_firewall_chain(outbound_chain, [("OUTPUT", "-o"), ("FORWARD", "-o")])

        self._append_firewall_rules(inbound_chain, "-s", wg_network, inbound_rules)
        self._append_firewall_rules(outbound_chain, "-d", wg_network, outbound_rules)

    def clear_firewall(self) -> None:
        for chain, hooks in (
            (self._firewall_chain("IN"), [("INPUT", "-i"), ("FORWARD", "-i")]),
            (self._firewall_chain("OUT"), [("OUTPUT", "-o"), ("FORWARD", "-o")]),
        ):
            for base_chain, iface_flag in hooks:
                while self._run_ok(["iptables", "-D", base_chain, iface_flag, self.settings.wg_iface, "-j", chain]):
                    pass
            self._run(["iptables", "-F", chain], check=False)
            self._run(["iptables", "-X", chain], check=False)

    def diagnostics(self) -> list[str]:
        warnings: list[str] = []
        try:
            routes = self._run(["ip", "-4", "route"], check=False).splitlines()
            wg_network = ipaddress.ip_network(self.settings.wg_cidr, strict=False)
            for route in routes:
                parts = route.split()
                if not parts or parts[0] == "default" or "dev" not in parts:
                    continue
                dev = parts[parts.index("dev") + 1]
                if dev == self.settings.wg_iface:
                    continue
                try:
                    network = ipaddress.ip_network(parts[0], strict=False)
                except ValueError:
                    continue
                if network.prefixlen == network.max_prefixlen:
                    continue
                if wg_network.overlaps(network):
                    warnings.append(
                        f"WireGuard 网段 {wg_network} 与 {dev} 路由 {network} 重叠，访问部分 10.x 地址可能冲突。"
                    )
        except Exception as exc:
            warnings.append(f"路由诊断失败: {exc}")
        return warnings

    def add_peer(self, name: str, allowed_ips: str | None = None) -> dict[str, str]:
        self._validate_name(name)
        allowed_ips = allowed_ips or self.settings.client_allowed_ips
        self._validate_allowed_ips(allowed_ips)
        with self.locked():
            if self._find_peer(name):
                raise WireGuardError(f"用户已存在: {name}")
            ip = self._next_ip()
            private_key = self._run(["wg", "genkey"]).strip()
            public_key = self._run(["wg", "pubkey"], input_text=private_key + "\n").strip()
            server_public_key = self.server_public_key()

            self._backup_config()
            with self.settings.wg_conf.open("a", encoding="utf-8") as fh:
                fh.write(f"\n# {name}\n[Peer]\nPublicKey = {public_key}\nAllowedIPs = {ip}/32\n")

            client_config = self._client_config(private_key, ip, server_public_key, allowed_ips)
            client_path = self.client_path(name)
            self._write_secret_file(client_path, client_config)
            self.reload()
            return {"name": name, "ip": ip, "config": client_config}

    def pause_peer(self, name: str) -> None:
        self._validate_name(name)
        with self.locked():
            peer = self._find_peer(name)
            if not peer or not peer.enabled:
                raise WireGuardError(f"用户不存在或已暂停: {name}")
            text = self.settings.wg_conf.read_text(encoding="utf-8")
            block = self._peer_block_pattern(name, disabled=False)
            text = block.sub(lambda m: self._disable_block(name, m.group(0)), text, count=1)
            self._backup_config()
            self._write_config(text)
            self._run(["wg", "set", self.settings.wg_iface, "peer", peer.public_key, "remove"], check=False)

    def resume_peer(self, name: str) -> None:
        self._validate_name(name)
        with self.locked():
            peer = self._find_peer(name, include_disabled=True)
            if not peer or peer.enabled:
                raise WireGuardError(f"用户不存在或未暂停: {name}")
            text = self.settings.wg_conf.read_text(encoding="utf-8")
            block = self._peer_block_pattern(name, disabled=True)
            text = block.sub(lambda m: self._enable_block(m.group(0)), text, count=1)
            self._backup_config()
            self._write_config(text)
            self._run(["wg", "set", self.settings.wg_iface, "peer", peer.public_key, "allowed-ips", f"{peer.ip}/32"], check=False)

    def remove_peer(self, name: str) -> None:
        self._validate_name(name)
        with self.locked():
            peer = self._find_peer(name, include_disabled=True)
            if not peer:
                raise WireGuardError(f"用户不存在: {name}")
            text = self.settings.wg_conf.read_text(encoding="utf-8")
            text = self._peer_block_pattern(name, disabled=not peer.enabled).sub("", text, count=1)
            self._backup_config()
            self._write_config(text)
            self._run(["wg", "set", self.settings.wg_iface, "peer", peer.public_key, "remove"], check=False)
            self.client_path(name).unlink(missing_ok=True)
            state = self._read_state()
            names = set(state.get("admin_peers", []))
            names.discard(name)
            state["admin_peers"] = sorted(names)
            self._write_state(state)

    def client_config(self, name: str) -> str:
        self._validate_name(name)
        path = self.client_path(name)
        if not path.exists():
            raise WireGuardError(f"找不到客户端配置: {name}")
        return path.read_text(encoding="utf-8")

    def has_client_config(self, name: str) -> bool:
        self._validate_name(name)
        return self.client_path(name).exists()

    def update_client_allowed_ips(self, name: str, allowed_ips: str) -> str:
        self._validate_name(name)
        self._validate_allowed_ips(allowed_ips)
        config = self.client_config(name)
        updated = re.sub(r"^AllowedIPs\s*=.*$", f"AllowedIPs = {allowed_ips}", config, flags=re.MULTILINE)
        self._write_secret_file(self.client_path(name), updated)
        return updated

    def qr_svg(self, config_text: str) -> str:
        return self._run(["qrencode", "-t", "SVG"], input_text=config_text)

    def qr_png(self, config_text: str) -> bytes:
        result = subprocess.run(
            ["qrencode", "-t", "PNG", "-s", "6", "-m", "2", "-o", "-"],
            input=config_text.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip() or "QR 生成失败"
            raise WireGuardError(detail)
        return result.stdout

    def server_public_key(self) -> str:
        private_key = ""
        for line in self.settings.wg_conf.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PrivateKey"):
                private_key = line.split("=", 1)[1].strip()
                break
        if not private_key:
            raise WireGuardError("服务端 PrivateKey 不存在")
        return self._run(["wg", "pubkey"], input_text=private_key + "\n").strip()

    def client_path(self, name: str) -> Path:
        return self.settings.clients_dir / f"{name}.conf"

    def _parse_config(self) -> list[Peer]:
        if not self.settings.wg_conf.exists():
            raise WireGuardError(f"WireGuard 配置不存在: {self.settings.wg_conf}")
        peers: list[Peer] = []
        current_name: str | None = None
        enabled = True
        public_key = ""
        ip = ""

        for raw in self.settings.wg_conf.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            disabled_line = line.removeprefix("# DISABLED # ").strip() if line.startswith("# DISABLED # ") else None
            if disabled_line is not None:
                if current_name is None and disabled_line and disabled_line not in {"[Peer]"} and "=" not in disabled_line:
                    current_name = disabled_line
                    enabled = False
                    public_key = ""
                    ip = ""
                elif current_name and disabled_line.startswith("PublicKey"):
                    public_key = disabled_line.split("=", 1)[1].strip()
                elif current_name and disabled_line.startswith("AllowedIPs"):
                    allowed = disabled_line.split("=", 1)[1].strip()
                    ip = allowed.split("/", 1)[0].strip()
                    if public_key and self._is_peer_ip(ip):
                        peers.append(Peer(current_name, public_key, ip, enabled))
                        current_name = None
            elif line.startswith("# "):
                current_name = line.removeprefix("# ").strip()
                enabled = True
                public_key = ""
                ip = ""
            elif current_name and line.startswith("PublicKey"):
                public_key = line.split("=", 1)[1].strip()
            elif current_name and line.startswith("AllowedIPs"):
                allowed = line.split("=", 1)[1].strip()
                ip = allowed.split("/", 1)[0].strip()
                if public_key and self._is_peer_ip(ip):
                    peers.append(Peer(current_name, public_key, ip, enabled))
                    current_name = None
        return peers

    def _runtime_dump(self) -> dict[str, dict[str, int | None]]:
        output = self._run(["wg", "show", self.settings.wg_iface, "dump"], check=False)
        rows = output.splitlines()[1:]
        runtime: dict[str, dict[str, int | None]] = {}
        for row in rows:
            parts = row.split("\t")
            if len(parts) >= 7:
                runtime[parts[0]] = {
                    "latest_handshake": int(parts[4]) or None,
                    "rx_bytes": int(parts[5]),
                    "tx_bytes": int(parts[6]),
                }
        return runtime

    def _find_peer(self, name: str, include_disabled: bool = True) -> Peer | None:
        for peer in self._parse_config():
            if peer.name == name and (include_disabled or peer.enabled):
                return peer
        return None

    def _next_ip(self) -> str:
        used = {int(peer.ip.rsplit(".", 1)[1]) for peer in self._parse_config()}
        for last_octet in range(2, 255):
            if last_octet not in used:
                return f"{self.settings.wg_subnet}.{last_octet}"
        raise WireGuardError("没有可用的 WireGuard IP")

    def _client_config(self, private_key: str, ip: str, server_public_key: str, allowed_ips: str) -> str:
        endpoint = self._server_endpoint()
        return (
            "[Interface]\n"
            f"PrivateKey = {private_key}\n"
            f"Address = {ip}/24\n"
            f"DNS = {self.settings.dns}\n\n"
            "[Peer]\n"
            f"PublicKey = {server_public_key}\n"
            f"Endpoint = {endpoint}\n"
            f"AllowedIPs = {allowed_ips}\n"
            "PersistentKeepalive = 25\n"
        )

    def _server_endpoint(self) -> str:
        if self.settings.server_endpoint:
            return self.settings.server_endpoint
        if self.settings.server_public_ip:
            return f"{self.settings.server_public_ip}:{self.settings.wg_port}"
        raise WireGuardError("请设置 NET_TOOLS_SERVER_ENDPOINT，例如 vpn.example.com:51820")

    def reload(self) -> None:
        command = f"wg syncconf {self.settings.wg_iface} <(wg-quick strip {self.settings.wg_iface})"
        self._run(["bash", "-lc", command])

    def _backup_config(self) -> None:
        backup = self.settings.wg_conf.with_name(f"{self.settings.wg_conf.name}.bak.{int(time.time())}")
        shutil.copy2(self.settings.wg_conf, backup)

    def _write_config(self, text: str) -> None:
        fd, path = tempfile.mkstemp(prefix="wg0.", suffix=".conf", dir=str(self.settings.wg_conf.parent))
        tmp = Path(path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(tmp, 0o600)
            tmp.replace(self.settings.wg_conf)
        finally:
            tmp.unlink(missing_ok=True)

    def _write_secret_file(self, path: Path, text: str) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(tmp, 0o600)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    def _read_state(self) -> dict:
        if not self.settings.state_file.exists():
            return {"admin_peers": list(self.settings.initial_admin_peers)}
        try:
            return json.loads(self.settings.state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WireGuardError(f"状态文件损坏: {self.settings.state_file}") from exc

    def _write_state(self, state: dict) -> None:
        self.settings.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f"{self.settings.state_file.name}.", dir=str(self.settings.state_file.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.chmod(tmp, 0o600)
            tmp.replace(self.settings.state_file)
        finally:
            tmp.unlink(missing_ok=True)

    def _firewall_policy_state(self) -> dict[str, str]:
        state = self._read_state()
        firewall = state.get("firewall", {})
        if not isinstance(firewall, dict):
            return {}
        return {str(key): str(value) for key, value in firewall.items()}

    def _firewall_chain(self, suffix: str) -> str:
        prefix = re.sub(r"[^A-Za-z0-9_]", "_", self.settings.firewall_chain_prefix.upper()).strip("_")
        return f"{prefix or 'LONGTAIL'}_{suffix}"

    def _ensure_firewall_chain(self, chain: str, hooks: list[tuple[str, str]]) -> None:
        self._run(["iptables", "-N", chain], check=False)
        self._run(["iptables", "-F", chain])
        self._run(["iptables", "-A", chain, "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"])
        for base_chain, iface_flag in hooks:
            jump = ["iptables", "-C", base_chain, iface_flag, self.settings.wg_iface, "-j", chain]
            if not self._run_ok(jump):
                self._run(["iptables", "-I", base_chain, "1", iface_flag, self.settings.wg_iface, "-j", chain])

    def _append_firewall_rules(self, chain: str, ip_match: str, ip: str, rules: list[PortRule]) -> None:
        for rule in rules:
            self._run(
                [
                    "iptables",
                    "-A",
                    chain,
                    ip_match,
                    ip,
                    "-p",
                    rule.protocol,
                    "-m",
                    rule.protocol,
                    "--dport",
                    rule.iptables_port,
                    "-j",
                    "ACCEPT",
                ]
            )
        self._run(["iptables", "-A", chain, ip_match, ip, "-j", "DROP"])

    def _merge_port_specs(self, *values: str) -> str:
        rules: list[PortRule] = []
        for value in values:
            for rule in self._parse_port_rules(value):
                if rule not in rules:
                    rules.append(rule)
        return ", ".join(rule.display for rule in rules)

    def _normalize_port_spec(self, value: str) -> str:
        return ", ".join(rule.display for rule in self._parse_port_rules(value))

    def _parse_port_rules(self, value: str) -> list[PortRule]:
        rules: list[PortRule] = []
        if not value.strip():
            return rules
        for raw in re.split(r"[\s,]+", value.strip()):
            if not raw:
                continue
            match = PORT_RE.fullmatch(raw)
            if not match:
                raise WireGuardError(f"端口规则不合法: {raw}")
            prefix_proto, start_text, end_text, suffix_proto = match.groups()
            if prefix_proto and suffix_proto and prefix_proto.lower() != suffix_proto.lower():
                raise WireGuardError(f"端口协议冲突: {raw}")
            protocol = (prefix_proto or suffix_proto or "tcp").lower()
            start = int(start_text)
            end = int(end_text or start_text)
            if not (1 <= start <= 65535 and 1 <= end <= 65535 and start <= end):
                raise WireGuardError(f"端口范围不合法: {raw}")
            rule = PortRule(protocol, start, end)
            if rule not in rules:
                rules.append(rule)
        return rules

    def _peer_block_pattern(self, name: str, disabled: bool) -> re.Pattern[str]:
        if disabled:
            marker = re.escape(f"# DISABLED # {name}")
            return re.compile(rf"^{marker}\n(?:# DISABLED # .*\n)*?(?:\n|\Z)", re.MULTILINE)
        marker = re.escape(f"# {name}")
        return re.compile(rf"^{marker}\n\[Peer\]\n(?:.*\n)*?AllowedIPs\s*=.*(?:\n\n|\Z)", re.MULTILINE)

    @staticmethod
    def _disable_block(name: str, block: str) -> str:
        lines = block.splitlines()
        return "\n".join([f"# DISABLED # {name}", *[f"# DISABLED # {line}" for line in lines[1:]]]) + "\n\n"

    @staticmethod
    def _enable_block(block: str) -> str:
        return "\n".join(line.removeprefix("# DISABLED # ") for line in block.splitlines()) + "\n\n"

    def _validate_name(self, name: str) -> None:
        if not NAME_RE.fullmatch(name):
            raise WireGuardError("用户名只能包含 1-32 位字母、数字、下划线、点和短横线")

    def _validate_allowed_ips(self, allowed_ips: str) -> None:
        try:
            for part in allowed_ips.split(","):
                ipaddress.ip_network(part.strip(), strict=False)
        except ValueError as exc:
            raise WireGuardError(f"AllowedIPs 不合法: {allowed_ips}") from exc

    def _is_peer_ip(self, value: str) -> bool:
        try:
            ip = ipaddress.ip_address(value)
            network = ipaddress.ip_network(self.settings.wg_cidr, strict=False)
            return ip in network and str(ip) != self.settings.server_vpn_ip
        except ValueError:
            return False

    def _run(self, args: list[str], input_text: str | None = None, check: bool = True) -> str:
        result = subprocess.run(args, input=input_text, text=True, capture_output=True, check=False)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "command failed"
            raise WireGuardError(detail)
        return result.stdout

    def _run_ok(self, args: list[str]) -> bool:
        return subprocess.run(args, text=True, capture_output=True, check=False).returncode == 0
