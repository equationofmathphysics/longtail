#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: sudo ./deploy/bootstrap.sh <server-ip-or-domain[:port]> [initial-admin-peer]

Example:
  sudo ./deploy/bootstrap.sh vpn.example.com phone

This installs runtime dependencies, creates the Python virtualenv, initializes
/etc/wireguard/wg0.conf when missing, creates the first admin peer, and starts
longtail-web.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 1 ]]; then
    usage
    exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "error: run this script with sudo" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_DIR}"

if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv wireguard-tools qrencode iproute2 iptables
fi

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

install -d -m 755 /etc/longtail
.venv/bin/python -m nettools.bootstrap "$@"

SERVICE_STARTED=0
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    SERVICE_TMP="$(mktemp)"
    SERVICE_PROJECT_DIR="${PROJECT_DIR//\\/\\\\}"
    SERVICE_PROJECT_DIR="${SERVICE_PROJECT_DIR//&/\\&}"
    SERVICE_PROJECT_DIR="${SERVICE_PROJECT_DIR//|/\\|}"
    sed "s|/opt/longtail|${SERVICE_PROJECT_DIR}|g" deploy/longtail-web.service > "${SERVICE_TMP}"
    install -m 644 "${SERVICE_TMP}" /etc/systemd/system/longtail-web.service
    rm -f "${SERVICE_TMP}"
    systemctl daemon-reload
    systemctl enable --now longtail-web
    SERVICE_STARTED=1
else
    echo "warning: systemd is not available; start Longtail manually with:" >&2
    echo "  set -a; . /etc/longtail/longtail.env; set +a; ${PROJECT_DIR}/.venv/bin/gunicorn --workers 2 --bind \${NET_TOOLS_BIND_HOST}:\${NET_TOOLS_BIND_PORT:-51437} nettools.app:app" >&2
fi

echo
if [[ "${SERVICE_STARTED}" -eq 1 ]]; then
    echo "Longtail web service is running."
else
    echo "Longtail bootstrap finished, but the web service was not started automatically."
fi
echo "VPN admin URL: http://10.66.0.1:51437/"
echo "SSH tunnel:    ssh -L 51437:10.66.0.1:51437 user@your-server"
