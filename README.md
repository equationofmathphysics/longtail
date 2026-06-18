# Longtail

Longtail 是一个很小的 WireGuard Web 管理后台。

它可以：

- 查看 WireGuard peer、最近连接时间和流量
- 新增 peer，自动分配 VPN IP
- 生成手机可扫码的二维码
- 复制或下载客户端 `.conf`
- 暂停、恢复、删除 peer
- 指定哪些 peer 可以访问后台
- 在服务端限制 WireGuard 可信端口

## 前提

- 准备服务器 IP 或域名。服务器可以是云服务器、VPS、带公网 IP 的电脑，也可以是当前本机。
- 远程服务器需要 SSH 登录方式和 root/sudo 权限；本机服务器直接在本机执行命令。
- 已有可用的 `/etc/wireguard/wg0.conf`，里面有服务端 `PrivateKey`。

## 让 AI 帮你配置

可以把这段发给 AI：

```text
请帮我安装并配置 Longtail：
1. 先确认服务器 IP/域名、SSH 登录方式和 root/sudo 权限；如果服务器是本机，就直接本机执行。
2. 配置完成后，给我手机 WireGuard 二维码，并告诉我后台地址。
3. 说明 WireGuard 子网、服务器公网入口和开机常态运行方式。
4. 说明如何使用后台，特别是 WireGuard 可信端口控制。
```

## 安装

```bash
sudo apt update
sudo apt install -y git python3-venv wireguard-tools qrencode

sudo git clone https://github.com/equationofmathphysics/longtail.git /opt/longtail
cd /opt/longtail

sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt

sudo install -d -m 755 /etc/longtail
sudo install -m 600 deploy/longtail.env.example /etc/longtail/longtail.env
sudo nano /etc/longtail/longtail.env
```

更简单的模板在 `deploy/examples/`，例如：

```bash
sudo install -m 600 deploy/examples/minimal.env /etc/longtail/longtail.env
```

至少修改这一行：

```env
NET_TOOLS_SERVER_ENDPOINT=YOUR_SERVER_IP_OR_DOMAIN:51820
```

最短流程：

1. 复制一个 env 模板到 `/etc/longtail/longtail.env`。
2. 修改 `NET_TOOLS_SERVER_ENDPOINT`。
3. 启动 `longtail-web`。
4. 用 SSH 隧道打开后台。
5. 在后台新增设备、扫码导入 WireGuard。

启动后台：

```bash
sudo cp deploy/longtail-web.service /etc/systemd/system/longtail-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now longtail-web
```

如果 `wg0` 还没有设置开机启动：

```bash
sudo systemctl enable --now wg-quick@wg0
```

查看状态：

```bash
sudo systemctl status longtail-web --no-pager
```

## 使用

本机打开：

```text
http://127.0.0.1:51437/
```

如果你在自己电脑上管理远程服务器，先开 SSH 隧道：

```bash
ssh -L 51437:127.0.0.1:51437 user@your-server
```

然后浏览器打开：

```text
http://127.0.0.1:51437/
```

第一次添加手机：

1. 点击“新增设备”，输入 `phone`。
2. 如果希望手机也能管理后台，在设备列表里给 `phone` 点“提权”。
3. 用 WireGuard App 扫二维码。
4. 手机连上 VPN 后，打开 `http://10.66.0.1:51437/`。
5. 如果走 SSH 隧道管理，继续打开 `http://127.0.0.1:51437/`。

端口控制：

- 默认只放行 SSH `tcp/22`、RDP `tcp/3389`/`udp/3389` 和后台 `tcp/51437`。
- 在“可信端口”里添加额外端口，例如 `tcp/80, tcp/443, udp/53`。
- 入站表示 WireGuard 设备访问服务器或经服务器转发；出站表示服务器或转发流量访问 WireGuard 设备。
- 没写进保底端口或可信端口的 WireGuard 侧流量会被丢弃。

## 可选：限制 SSH

如果想让 SSH 只允许 WireGuard 网段访问：

```bash
sudo cp deploy/longtail-ssh-firewall.service /etc/systemd/system/longtail-ssh-firewall.service
sudo systemctl daemon-reload
sudo systemctl enable --now longtail-ssh-firewall
```

默认允许 `10.66.0.0/24` 访问 SSH，公网 SSH 会被丢弃。

## 常用配置

配置文件在：

```text
/etc/longtail/longtail.env
```

最常用的几项：

```env
NET_TOOLS_SERVER_ENDPOINT=YOUR_SERVER_IP_OR_DOMAIN:51820
NET_TOOLS_WG_CONF=/etc/wireguard/wg0.conf
NET_TOOLS_WG_CIDR=10.66.0.0/24
NET_TOOLS_SERVER_VPN_IP=10.66.0.1
NET_TOOLS_CLIENT_ALLOWED_IPS=10.66.0.0/24
NET_TOOLS_ADMIN_IPS=127.0.0.1,::1
NET_TOOLS_FIREWALL_ENABLED=1
NET_TOOLS_FIREWALL_REQUIRED_INBOUND_PORTS=tcp/22,tcp/3389,udp/3389,tcp/51437
NET_TOOLS_FIREWALL_REQUIRED_OUTBOUND_PORTS=tcp/22,tcp/3389,udp/3389,tcp/51437
```

## 安全

- 不要提交 `clients/`、`.conf`、二维码图片或 `/var/lib/longtail`，里面可能有客户端私钥。
- 后台默认按来源 IP 控制权限。不要随便把公网 IP 加进 `NET_TOOLS_ADMIN_IPS`。
- 服务端端口白名单默认开启，保底端口不要随便改小，否则可能断开 SSH 或后台访问。
- 只有在可信反向代理后面运行时，才设置 `NET_TOOLS_TRUST_PROXY_HEADERS=1`。
- 建议后台只给本机和 WireGuard 内的管理员设备访问。

<sub><sup>This project is released under the WH Covenant Public License. Use, copying, modification, distribution, and other dealings are subject to [LICENSE](LICENSE).</sup></sub>
