# Env Examples

Longtail reads `/etc/longtail/longtail.env` through the systemd service.

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

For every available setting, see `deploy/longtail.env.example`.
