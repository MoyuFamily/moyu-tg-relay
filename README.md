# 🐟 Moyu Telegram Interaction Relay (`moyu-tg-relay`)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Compose_Ready-2496ED.svg)](deploy/docker/compose.yml)
[![systemd](https://img.shields.io/badge/systemd-Hardened-success.svg)](deploy/systemd/moyu-tg-relay.service)

> **轻量、安全、生产加固的 Telegram verification / confirmation 中继服务。**
>
> Relay 长期持有 Telethon Session，为 `moyu-renew` 提供一次性 OTP、受限自动确认，以及自动失败后的可恢复人工 fallback 信号。

---

## 🌟 核心特性

- 🔒 **严格安全边界**：
  - Bearer Token 强鉴权与 constant-time 比较；
  - Swagger / OpenAPI / ReDoc 默认关闭；
  - systemd 沙箱与 Docker `read_only + cap_drop: ALL`；
  - Telegram Session credential 永不进入源码、Git history 或发布 Artifact。独立 Docker/systemd 部署默认使用 Host 上的文件 Session；Secret-managed 部署可使用 `TELEGRAM_SESSION_STRING` 注入 Telethon `StringSession`。
- ⚡ **短生命周期交互状态**：
  - 单 Telegram 账号只有一个 active request；
  - TTL、一次性 consume、终态自动回收；
  - sender、Telegram Account ID 与 Hax message marker 多重约束。
- 🤖 **安全自动确认**：
  - 仅当前存在唯一 active Hax request 时工作；
  - sender、Hax marker 与 button text 必须同时命中白名单；
  - 只允许单一、无歧义的 allow-listed confirmation button；
  - 任何未知按钮、歧义或点击异常都 fail-closed 到 `human_required`。
- 🧩 **Human fallback**：
  - Relay 不负责通知用户；只向 caller 暴露 `human_required`；
  - `moyu-renew` 根据已配置渠道实时通知飞书 / Telegram Bot / 其他渠道，并保持原浏览器会话等待用户手机操作。
- 🐳 **双模部署**：
  - Docker Compose：named volume 持久化 Session，`/readyz` 作为容器健康检查；
  - systemd：代码 root-owned，仅 `/var/lib/moyu-tg-relay` 可持久写入。
- 🧭 **引导式部署**：自动生成 Bearer Token、完成 Session bootstrap、提取并回填 `TELEGRAM_ACCOUNT_ID`、启动服务并执行完整 smoke check。

---

## 🔄 Interaction State Machine

```text
moyu-renew 创建 active request
            ↓
Telegram incoming message
            ↓
┌───────────────────────────────┐
│ OTP code                      │
│   → ready → consume once      │
├───────────────────────────────┤
│ allow-listed confirmation     │
│   → click                     │
│   → auto_attempted            │
├───────────────────────────────┤
│ unknown / unsafe / click fail │
│   → human_required            │
└───────────────────────────────┘
```

完整状态：

```text
pending
  尚未收到可处理 Telegram 交互

auto_attempted
  Relay 已尝试自动确认，caller 应给目标网页一个短 grace period

human_required
  无法安全自动完成，caller 应通知用户并保持原任务上下文等待

ready
  OTP 已就绪，可以一次性 consume

consumed / expired / cancelled
  terminal
```

OTP 在 `auto_attempted` / `human_required` 之后仍可到达并把 request 转成 `ready`，因此用户手机完成 fallback 后不需要创建第二个 request。

---

## 🛡️ Auto-confirm Safety Policy

默认配置：

```text
HAX_AUTO_CONFIRM=true
HAX_CONFIRMATION_SENDER_IDS=777000
HAX_CONFIRMATION_MARKERS=hax.co.id,hax
HAX_AUTO_CONFIRM_BUTTONS=confirm,approve,authorize,accept,yes,continue
```

自动点击必须同时满足：

1. 当前 `TELEGRAM_ACCOUNT_ID` 恰好只有一个 active Hax request；
2. sender 为配置的 Hax Bot username，或 sender ID 命中 `HAX_CONFIRMATION_SENDER_IDS`；
3. message text 命中 `HAX_CONFIRMATION_MARKERS`；
4. message 中恰好有一个按钮的 normalized text 命中 `HAX_AUTO_CONFIRM_BUTTONS`。

**Relay 不会实现“看到 Telegram 里的 Confirm 就点击”的通用逻辑。**

如果 Hax/Telegram 的真实确认消息格式发生变化，优先更新 sender / marker / button allow-list；不要放宽成全局自动点击。

如果不希望 Relay 自动点击，可以：

```text
HAX_AUTO_CONFIRM=false
```

此时匹配到 confirmation card 会直接进入 `human_required`。

---

## 🔐 Session 与 Secret 模型

以下内容都属于敏感凭据，不得提交到仓库、Issue、PR、日志或 Artifact：

```text
OTP_RELAY_BEARER_TOKEN
TELEGRAM_API_HASH
TELEGRAM_SESSION_STRING
*.session
```

`TELEGRAM_SESSION_STRING` 与文件 `.session` 包含等价的长期 Telegram 登录能力，应按高敏 Secret 处理。

### 独立 Docker / systemd 部署

推荐继续使用文件 Session。部署向导会在目标 Host 上交互式完成 Telegram 登录，并将 `.session` 保存在受限权限的持久目录中。

### Secret-managed / Workload 部署

可在可信本机一次性执行：

```bash
python -m moyu_tg_relay.bootstrap_session
```

完成 Telegram 登录后会输出：

```text
TELEGRAM_ACCOUNT_ID=<account-id>
TELEGRAM_SESSION_STRING=<secret-session-string>
```

将 `TELEGRAM_SESSION_STRING` 保存到部署系统的 Secret store 后，运行时通过环境变量注入即可。服务在 `TELEGRAM_SESSION_STRING` 存在时优先使用 `StringSession`；未配置时继续兼容 `TELEGRAM_SESSION_PATH` 文件 Session。

---

## 🚀 推荐：引导式部署

克隆仓库后只需要运行一个入口：

```bash
git clone https://github.com/MoyuFamily/moyu-tg-relay.git
cd moyu-tg-relay

# 启动统一交互式管理控制台
python3 -m scripts.manager

# 或直接执行自动化部署向导
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

> Relay 只监听 `127.0.0.1:8787`。远程 `moyu-renew` 应通过 Caddy/Nginx/Traefik 暴露 **HTTPS**，不要把 8787 明文端口直接开放到公网。

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

Telegram API credential 与 Relay Session credential 不应进入 `moyu-renew` 或其 GitHub Actions。它们只属于 Relay 的部署边界。

`moyu-renew` 负责：

```text
auto_attempted
  → 给网页 grace period
  → 页面继续则无感运行

human_required
  → 通过所有已配置通知渠道即时提醒
  → 保持 Selenium session
  → 用户手机确认后继续同一 Action
  → 超时才 action_required
```

Relay **不决定使用飞书还是 Telegram Bot 通知**，通知渠道属于 `moyu-renew` 的职责。

---

## HTTP Contract

```text
GET    /healthz
GET    /readyz
POST   /v1/otp/requests
GET    /v1/otp/requests/{request_id}
POST   /v1/otp/requests/{request_id}/consume
DELETE /v1/otp/requests/{request_id}
```

`GET /v1/otp/requests/{request_id}` 返回：

```json
{
  "request_id": "...",
  "status": "pending | auto_attempted | human_required | ready | consumed | expired | cancelled",
  "detail": ""
}
```

`detail` 只提供可安全暴露的状态说明，不返回 OTP。OTP 只允许在 `ready` 后通过 `consume` 返回一次。

---

## 🔒 安全报告

如果发现安全问题，请不要在公开 Issue 中附带真实 Token、API Hash、StringSession、`.session` 内容或其他凭据。请先阅读 [SECURITY.md](SECURITY.md)。

---

## 📄 开源协议

基于 [MIT License](LICENSE)。
