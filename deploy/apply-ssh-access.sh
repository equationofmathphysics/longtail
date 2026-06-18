#!/usr/bin/env bash
set -euo pipefail

WG_IFACE="${NET_TOOLS_WG_IFACE:-wg0}"
WG_CIDR="${NET_TOOLS_WG_CIDR:-10.66.0.0/24}"
SSH_PORT="${NET_TOOLS_SSH_PORT:-22}"

while iptables -D INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; do :; done
while iptables -D INPUT -i lo -p tcp --dport "$SSH_PORT" -j ACCEPT 2>/dev/null; do :; done
while iptables -D INPUT -i "$WG_IFACE" -s "$WG_CIDR" -p tcp --dport "$SSH_PORT" -j ACCEPT 2>/dev/null; do :; done
while iptables -D INPUT -p tcp --dport "$SSH_PORT" -j DROP 2>/dev/null; do :; done

iptables -I INPUT 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -I INPUT 2 -i lo -p tcp --dport "$SSH_PORT" -j ACCEPT
iptables -I INPUT 3 -i "$WG_IFACE" -s "$WG_CIDR" -p tcp --dport "$SSH_PORT" -j ACCEPT
iptables -I INPUT 4 -p tcp --dport "$SSH_PORT" -j DROP

while ip6tables -D INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; do :; done
while ip6tables -D INPUT -i lo -p tcp --dport "$SSH_PORT" -j ACCEPT 2>/dev/null; do :; done
while ip6tables -D INPUT -p tcp --dport "$SSH_PORT" -j DROP 2>/dev/null; do :; done

ip6tables -I INPUT 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ip6tables -I INPUT 2 -i lo -p tcp --dport "$SSH_PORT" -j ACCEPT
ip6tables -I INPUT 3 -p tcp --dport "$SSH_PORT" -j DROP

echo "Applied: SSH/${SSH_PORT} accepts localhost and ${WG_CIDR} via ${WG_IFACE}; public SSH is blocked."
