from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from .config import settings
from .wg_manager import WireGuardError, WireGuardManager


BASE_DIR = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
manager = WireGuardManager(settings)


try:
    with manager.locked():
        manager.apply_firewall()
except WireGuardError as error:
    app.logger.warning("Firewall policy was not applied on startup: %s", error)


def client_ip() -> str:
    remote = request.remote_addr or ""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return remote


def require_admin(handler):
    @wraps(handler)
    def wrapper(*args, **kwargs):
        remote = client_ip()
        token = request.headers.get("X-Admin-Token") or ""
        ip_allowed = remote in settings.admin_ips or remote in manager.admin_ips()
        token_allowed = bool(settings.admin_token and token == settings.admin_token)
        if not (ip_allowed or token_allowed):
            return jsonify({"ok": False, "error": "forbidden", "remote": remote}), 403
        return handler(*args, **kwargs)

    return wrapper


def payload() -> dict:
    return request.get_json(silent=True) or {}


def ok(**data):
    return jsonify({"ok": True, **data})


@app.errorhandler(WireGuardError)
def handle_wg_error(error: WireGuardError):
    return jsonify({"ok": False, "error": str(error)}), 400


@app.errorhandler(Exception)
def handle_error(error: Exception):
    app.logger.exception("Unhandled error")
    return jsonify({"ok": False, "error": str(error)}), 500


@app.get("/")
@require_admin
def index():
    return render_template(
        "index.html",
        admin_ips=", ".join(sorted(set(settings.admin_ips) | manager.admin_ips())),
        server_vpn_ip=settings.server_vpn_ip,
        bind_port=settings.bind_port,
        client_allowed_ips=settings.client_allowed_ips,
    )


@app.get("/api/status")
@require_admin
def status():
    admin_peer_names = manager.admin_peer_names()
    visible_peers = [peer for peer in manager.list_peers() if peer.name not in settings.hidden_peers]
    return ok(
        iface=settings.wg_iface,
        server_vpn_ip=settings.server_vpn_ip,
        bind_port=settings.bind_port,
        admin_ips=tuple(sorted(set(settings.admin_ips) | manager.admin_ips())),
        client_allowed_ips=settings.client_allowed_ips,
        next_ip=manager.next_ip(),
        diagnostics=manager.diagnostics(),
        firewall=manager.firewall_policy(),
        peers=[
            peer.__dict__ | {
                "status": peer.status,
                "is_admin": peer.name in admin_peer_names,
                "has_config": manager.has_client_config(peer.name),
            }
            for peer in visible_peers
        ],
    )


@app.get("/api/firewall")
@require_admin
def get_firewall():
    return ok(policy=manager.firewall_policy())


@app.post("/api/firewall")
@require_admin
def update_firewall():
    data = payload()
    policy = manager.set_firewall_policy(
        data.get("trusted_inbound_ports", ""),
        data.get("trusted_outbound_ports", ""),
    )
    return ok(policy=policy)


@app.post("/api/peers")
@require_admin
def add_peer():
    data = payload()
    result = manager.add_peer(data.get("name", ""), data.get("allowed_ips") or None)
    return ok(**result)


@app.post("/api/peers/<name>/pause")
@require_admin
def pause_peer(name: str):
    manager.pause_peer(name)
    return ok()


@app.post("/api/peers/<name>/resume")
@require_admin
def resume_peer(name: str):
    manager.resume_peer(name)
    return ok()


@app.delete("/api/peers/<name>")
@require_admin
def remove_peer(name: str):
    manager.remove_peer(name)
    return ok()


@app.get("/api/peers/<name>/config")
@require_admin
def get_config(name: str):
    return Response(manager.client_config(name), mimetype="text/plain; charset=utf-8")


@app.get("/api/peers/<name>/download")
@require_admin
def download_config(name: str):
    path = manager.client_path(name)
    if not path.exists():
        raise WireGuardError(f"Client config not found: {name}")
    return send_file(path, as_attachment=True, download_name=f"{name}.conf", mimetype="text/plain")


@app.get("/api/peers/<name>/qr.svg")
@require_admin
def qr(name: str):
    svg = manager.qr_svg(manager.client_config(name))
    return Response(svg, mimetype="image/svg+xml")


@app.get("/api/peers/<name>/qr.png")
@require_admin
def qr_png(name: str):
    png = manager.qr_png(manager.client_config(name))
    return Response(png, mimetype="image/png")


@app.get("/api/peers/<name>/qr")
@require_admin
def qr_image(name: str):
    png = manager.qr_png(manager.client_config(name))
    return Response(png, mimetype="image/png")


@app.post("/api/peers/<name>/allowed-ips")
@require_admin
def update_allowed_ips(name: str):
    data = payload()
    config = manager.update_client_allowed_ips(name, data.get("allowed_ips", ""))
    return ok(config=config)


@app.post("/api/peers/<name>/admin")
@require_admin
def update_peer_admin(name: str):
    data = payload()
    manager.set_peer_admin(name, bool(data.get("is_admin")))
    return ok()


def main():
    app.run(host=settings.bind_host, port=settings.bind_port)


if __name__ == "__main__":
    main()
