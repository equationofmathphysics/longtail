# Longtail

Longtail 是一个基于 WireGuard 的轻量级自托管组网工具，可作为有公网服务器场景下的 Tailscale 简化替代。它支持局域网式互联、设备二维码接入、后台权限管理和 WireGuard 侧端口控制，适合多机器人调试、远程运维和小型私有网络。

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
- 默认安装命令面向 Ubuntu/Debian 这类使用 `apt` 和 systemd 的服务器。
- 在云厂商安全组或外层防火墙里放行 WireGuard 入口端口，默认是 `udp/51820`。

## 让 AI 帮你配置

代操作版，把这段发给 AI：

```text
请帮我安装并配置 Longtail；当前服务器 IP/域名是：____，SSH 登录方式是：____，服务器已具备 sudo 权限。
不要在对话里记录 sudo 密码；需要提权时让我在终端交互输入。配置完成后，请给我手机 WireGuard 扫码二维码和后台地址，并告诉我验证方法、手机扫码方法、进入后台方法和后续管理方法。
```

安全版，把这段发给 AI：

```text
请给我生成安装并配置 Longtail 的命令；服务器 IP/域名是：____。
不要连接我的服务器，也不要让我提供 sudo 密码；只输出需要我复制到服务器上执行的命令，并提醒我在云厂商安全组放行 `udp/51820`，再附上验证方法、手机扫码方法、进入后台方法和后续管理方法。
```

## 安装

```bash
sudo apt update
sudo apt install -y git

sudo git clone https://github.com/equationofmathphysics/longtail.git /opt/longtail
cd /opt/longtail

sudo ./deploy/bootstrap.sh YOUR_SERVER_IP_OR_DOMAIN:51820 phone
```

`bootstrap.sh` 会安装运行依赖、创建 Python 虚拟环境、写入 `/etc/longtail/longtail.env`、在缺失时生成 `/etc/wireguard/wg0.conf`、开启 IPv4 转发、启动 `wg-quick@wg0` 和 `longtail-web`，并创建第一个管理员设备 `phone`。命令结束时会在终端输出 WireGuard 二维码。

如果服务器在云厂商安全组后面，确认已放行：

```text
udp/51820
```

如果只输入域名或 IP，没有写端口，会默认使用 `51820`：

```bash
sudo ./deploy/bootstrap.sh YOUR_SERVER_IP_OR_DOMAIN
```

查看状态：

```bash
sudo systemctl status longtail-web --no-pager
```

## 验证和使用

验证服务：

```bash
sudo systemctl status wg-quick@wg0 --no-pager
sudo systemctl status longtail-web --no-pager
```

手机扫码：

1. 用 WireGuard App 扫 `bootstrap.sh` 输出的二维码。
2. 打开手机上的 WireGuard 隧道。
3. 访问 `http://10.66.0.1:51437/`。

进入后台：

手机连上 WireGuard 后打开：

```text
http://10.66.0.1:51437/
```

如果你在自己电脑上管理远程服务器，先开 SSH 隧道：

```bash
ssh -L 51437:10.66.0.1:51437 user@your-server
```

然后浏览器打开：

```text
http://127.0.0.1:51437/
```

后续管理：

1. 在后台新增设备，复制配置或扫码导入 WireGuard。
2. 在设备列表里暂停、恢复、删除 peer。
3. 给需要管理后台的设备开启管理员权限。

端口控制：

- 默认只放行 SSH `tcp/22`、RDP `tcp/3389`/`udp/3389` 和后台 `tcp/51437`。
- 在“可信端口”里添加额外端口，例如 `tcp/80, tcp/443, udp/53`。
- 入站表示 WireGuard 设备访问服务器或经服务器转发；出站表示服务器或转发流量访问 WireGuard 设备。
- 没写进保底端口或可信端口的 WireGuard 侧流量会被丢弃。

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
NET_TOOLS_ADMIN_IPS=127.0.0.1,::1,10.66.0.1
NET_TOOLS_BIND_HOST=10.66.0.1
NET_TOOLS_FIREWALL_ENABLED=1
NET_TOOLS_FIREWALL_REQUIRED_INBOUND_PORTS=tcp/22,tcp/3389,udp/3389,tcp/51437
NET_TOOLS_FIREWALL_REQUIRED_OUTBOUND_PORTS=tcp/22,tcp/3389,udp/3389,tcp/51437
```

更完整的模板在 `deploy/longtail.env.example`，更小的场景模板在 `deploy/examples/`。通常不需要手写这些文件，先用 `deploy/bootstrap.sh` 初始化即可。

## 安全

- 不要提交 `clients/`、`.conf`、二维码图片或 `/var/lib/longtail`，里面可能有客户端私钥。
- 后台默认按来源 IP 控制权限。不要随便把公网 IP 加进 `NET_TOOLS_ADMIN_IPS`。
- 后台默认监听 `10.66.0.1:51437`，不要把后台端口直接暴露到公网。
- 公网只需要放行 WireGuard 入口端口，默认是 `udp/51820`。
- 服务端端口白名单默认开启，保底端口不要随便改小，否则可能断开 SSH 或后台访问。
- 只有在可信反向代理后面运行时，才设置 `NET_TOOLS_TRUST_PROXY_HEADERS=1`。
- 建议后台只给本机和 WireGuard 内的管理员设备访问。

<sub><sup>This project is released under the WH Covenant Public License. Use, copying, modification, distribution, and other dealings are subject to [LICENSE](LICENSE).</sup></sub>
