# Longtail

[English](README.md) | 中文

Longtail 是一个轻量级、全开源的 WireGuard 网页管理后台。你只要用一句话把服务器地址告诉 AI，让 AI 生成或执行安装命令，然后就可以在浏览器里管理 WireGuard 设备。

![Longtail 网页管理后台](docs/longtail-dashboard.png)

## 特性

- AI 一句配置：把服务器地址发给 AI，让 AI 帮你配置 Longtail。
- AI 一键安装：通过 `deploy/bootstrap.sh` 自动完成主要安装流程。
- 全开源、自托管。
- 轻量级 Python/Flask 网页后台。
- 底层使用 WireGuard 协议，兼容标准 WireGuard 客户端。
- 在网页里新增设备、扫码导入、下载 `.conf`、暂停 peer、授权管理员、控制可信端口。

## AI 配置提示词

代操作版：

```text
请帮我安装并配置 Longtail；服务器 IP/域名是：____。
配置完成后，请给我 WireGuard 扫码二维码、网页后台地址和验证方法。
```

安全版：

```text
请给我生成安装 Longtail 的命令；服务器 IP/域名是：____。
不要连接我的服务器，只输出需要我复制执行的命令，提醒我放行 udp/51820，并说明怎么打开网页后台。
```

## 安装

```bash
sudo apt update
sudo apt install -y git

sudo git clone https://github.com/equationofmathphysics/longtail.git /opt/longtail
cd /opt/longtail

sudo ./deploy/bootstrap.sh YOUR_SERVER_IP_OR_DOMAIN:51820 phone
```

`bootstrap.sh` 会安装依赖、创建 `/etc/longtail/longtail.env`、创建或复用
`/etc/wireguard/wg0.conf`、启动 `wg-quick@wg0` 和 `longtail-web`，并输出第一个 WireGuard 二维码。

在云防火墙或安全组里放行：

```text
udp/51820
```

## 网页后台

手机扫码并打开 WireGuard 后，访问：

```text
http://10.66.0.1:51437/
```

如果在 VPN 外的电脑上管理远程服务器，先开 SSH 隧道：

```bash
ssh -L 51437:10.66.0.1:51437 user@your-server
```

然后打开：

```text
http://127.0.0.1:51437/
```

## 验证

```bash
sudo systemctl status wg-quick@wg0 --no-pager
sudo systemctl status longtail-web --no-pager
```

## 配置

主配置文件：

```text
/etc/longtail/longtail.env
```

常用配置：

```env
NET_TOOLS_SERVER_ENDPOINT=YOUR_SERVER_IP_OR_DOMAIN:51820
NET_TOOLS_WG_CONF=/etc/wireguard/wg0.conf
NET_TOOLS_WG_CIDR=10.66.0.0/24
NET_TOOLS_SERVER_VPN_IP=10.66.0.1
NET_TOOLS_CLIENT_ALLOWED_IPS=10.66.0.0/24
NET_TOOLS_ADMIN_IPS=127.0.0.1,::1,10.66.0.1
NET_TOOLS_BIND_HOST=10.66.0.1
NET_TOOLS_FIREWALL_ENABLED=1
```

完整示例在 `deploy/longtail.env.example` 和 `deploy/examples/`。

## 安全

- 不要提交生成的客户端配置、二维码图片或 `/var/lib/longtail`，里面可能有私钥。
- 不要把网页后台直接暴露到公网。
- 默认只需要公网放行 `udp/51820`。
- 管理权限建议只给本机和可信 WireGuard 设备。

## 许可证

本项目基于 WH Covenant Public License 发布。使用、复制、修改、分发及其他处理行为均受 [LICENSE](LICENSE) 约束。
