# Env Examples

Longtail reads `/etc/longtail/longtail.env` through the systemd service.

For a normal first install, use `deploy/bootstrap.sh` instead of copying these files by hand.

Copy one example, edit it, then restart:

```bash
sudo install -m 600 deploy/examples/minimal.env /etc/longtail/longtail.env
sudo nano /etc/longtail/longtail.env
sudo systemctl restart longtail-web
```

Examples:

- `minimal.env`: smallest useful config.
- `vpn-admin.env`: first phone/laptop can manage the web UI through WireGuard.
- `custom-network.env`: use a different WireGuard subnet.
- `custom-ports.env`: change the web port and required firewall ports.

Network examples should be applied before creating clients. If you change the WireGuard subnet after bootstrap, keep `/etc/wireguard/wg0.conf`, `/etc/longtail/longtail.env`, `NET_TOOLS_BIND_HOST`, `NET_TOOLS_ADMIN_IPS`, and generated client configs aligned.

For every available setting, see `deploy/longtail.env.example`.
