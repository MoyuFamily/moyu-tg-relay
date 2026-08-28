# 🐟 Moyu Telegram OTP Relay (`moyu-tg-relay`)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Compose_Ready-2496ED.svg)](deploy/docker/compose.yml)
[![systemd Hardened](https://img.shields.io/badge/systemd-Hardened-success.svg)](deploy/systemd/moyu-tg-relay.service)

> **轻量、安全、生产加固的 Telegram 2FA / OTP 验证码中继微服务。**
>
> *自动化登录场景下多账户验证码的高隔离、一次性消费与零特权安全中继。*

---

## 🌟 核心特性

- 🔒 **严格安全边界**：
  - Bearer Token 强鉴权与 constant-time 比较；
  - Swagger / OpenAPI / ReDoc 默认关闭；
  - systemd 沙箱与 Docker `read_only + cap_drop: ALL`；
  - Telethon Session 永远留在 Relay VPS，不进入 GitHub Actions。
- ⚡ **短生命周期 OTP 状态**：
  - 单 Telegram 账号只有一个 active request；
  - TTL、一次性 consume、终态自动回收；
  - sender 与 Telegram Account ID 双重约束。
- 🐳 **双模部署**：
  - Docker Compose：named volume 持久化 Session，`/readyz` 作为容器健康检查；
  - systemd：代码 root-owned，仅 `/var/lib/moyu-tg-relay` 可持久写入。
- 🧭 **引导式部署**：自动生成 Bearer Token、完成 Session bootstrap、提取并回填 `TELEGRAM_ACCOUNT_ID`、启动服务并执行完整 smoke check。

---

## 🚀 推荐：引导式部署

克隆仓库后只需要运行一个入口：

```bash
git clone https://github.com/MoyuFamily/moyu-tg-relay.git
cd moyu-tg-relay
./deploy/install.sh
```

如果 Docker Compose 和 systemd 都可用，向导会让你选择部署方式。也可以直接指定：

```bash
# Docker Compose（推荐）
./deploy/install.sh docker

# Native systemd
sudo ./deploy/install.sh systemd
```

首次部署时用户只需要提供 Telegram `API ID` / `API Hash`，随后按 Telethon 提示输入手机号、Telegram 登录验证码以及账号开启 2FA 时的密码。其余步骤由脚本自动完成：

```text
配置检查
  -> 自动生成 Relay Bearer Token
  -> 构建/安装 runtime
  -> Telegram Session bootstrap
  -> 自动捕获 TELEGRAM_ACCOUNT_ID
  -> 写回受限权限 env 文件
  -> 启动 Relay
  -> /healthz + /readyz
  -> Bearer reject + accept smoke check
```

脚本是幂等入口：已有有效 Session 与 `TELEGRAM_ACCOUNT_ID` 时会直接复用，不会每次重新登录 Telegram。

> Relay 只监听 `127.0.0.1:8787`。远程 `moyu-renew` 应通过 Caddy/Nginx/Traefik 暴露 **HTTPS**，不要把 8787 明文端口直接开放到公网。向导完成后可输入域名获取对应 Caddy snippet。

手工部署与排障文档见 [deploy/README.md](deploy/README.md)。

---

## 🔍 健康检查与上线验收

基础 liveness：

```bash
python3 smoke_check.py --base-url http://127.0.0.1:8787
```

完整 readiness + auth：

```bash
# Docker：脚本会自动在容器内部执行，无需把 Token 放到命令历史。

docker compose --env-file .env -f deploy/docker/compose.yml exec -T moyu-tg-relay \
  python /app/smoke_check.py --base-url http://127.0.0.1:8787

# systemd：从受限权限的 env 文件安全读取 Token。
sudo /opt/moyu-tg-relay/.venv/bin/python /opt/moyu-tg-relay/smoke_check.py \
  --base-url http://127.0.0.1:8787 \
  --env-file /etc/moyu-tg-relay.env
```

完整 smoke check 会验证：HTTP 存活、Telethon 当前 ready、错误 Bearer Token 返回 401，以及正确 Token 能通过鉴权并到达受保护 handler。

---

## 🔗 `moyu-renew` 接入

Relay 通过 HTTPS 暴露后，`moyu-renew` 只需要两个 Secret：

```text
HAX_OTP_RELAY_URL=https://relay.example.com
HAX_OTP_RELAY_TOKEN=<OTP_RELAY_BEARER_TOKEN>
```

Telegram API ID / Hash 和 `.session` 不应进入 `moyu-renew` 或 GitHub Actions。

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。
