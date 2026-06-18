#!/usr/bin/env bash
set -euo pipefail

SERVICE="${NET_TOOLS_SERVICE:-longtail-web}"
BIND_PORT="${NET_TOOLS_BIND_PORT:-51437}"
SERVER_VPN_IP="${NET_TOOLS_SERVER_VPN_IP:-10.66.0.1}"
URL_LOCAL="http://127.0.0.1:${BIND_PORT}/"
URL_PHONE="http://${SERVER_VPN_IP}:${BIND_PORT}/"

usage() {
    cat <<EOF
Longtail Web 后台辅助命令

Usage: $(basename "$0") <command>

Commands:
  url       显示后台访问地址
  status    查看 systemd 服务状态
  restart   重启 Web 后台
  logs      查看最近日志

WireGuard 用户管理已经迁移到 Web 后台：
  本机：${URL_LOCAL}
  手机：${URL_PHONE}
EOF
}

case "${1:-url}" in
    url)
        printf "本机: %s\n手机: %s\n" "$URL_LOCAL" "$URL_PHONE"
        ;;
    status)
        systemctl --no-pager --full status "$SERVICE"
        ;;
    restart)
        sudo systemctl restart "$SERVICE"
        ;;
    logs)
        journalctl -u "$SERVICE" -n 120 --no-pager
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac
