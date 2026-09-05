# 🐟 Moyu Telegram Interaction Relay (`moyu-tg-relay`)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Compose_Ready-2496ED.svg)](deploy/docker/compose.yml)
[![systemd](https://img.shields.io/badge/systemd-Hardened-success.svg)](deploy/systemd/moyu-tg-relay.service)

> **轻量、安全、生产加固的通用 Telegram 交互与验证码中继微服务。**
>
> Relay 长期持有 Telethon Session，为下游各类无状态自动化任务（CI/CD、自动化脚本、后台爬虫/保活任务等）提供持久化 Telegram 交互桥接能力：支持一次性提取 2FA/OTP 验证码、受限规则的安全自动确认交互，以及自动失败后的可恢复人工 Fallback 信号。下游调用端无需感知任何 Telegram 登录凭据。

---

## 🌟 核心特性

- 🔒 **严格安全边界**：
  - Bearer Token 强鉴权与 constant-time 比较；
  - Swagger / OpenAPI / ReDoc 默认彻底关闭；
  - 生产级沙箱：systemd 单元（14 项内核级加固）与 Docker（`read_only: true` + `cap_drop: ALL`）；
  - Telegram Session 凭据永不进入源码、Git history 或发布 Artifact。独立 Docker/systemd 部署默认使用 Host 上的受保护文件 Session；Secret-managed 部署可使用 `TELEGRAM_SESSION_STRING` 注入 Telethon `StringSession`。
- ⚡ **短生命周期交互状态**：
  - 单 Telegram 账号在任意时刻仅允许一个 active request，从根源消除多任务并发时消息归属的歧义；
  - TTL 自动过期、单次安全消费（One-Time Consume）、终态延迟回收机制。
- 🔌 **插件化 Provider 架构**：
  - 核心传输网络、状态存储与业务规则彻底解耦；
  - 通过 Provider 机制独立定义不同 Bot/服务商的识别逻辑、验证码提取与确认规则；
  - 内置开箱即用的 Hax Provider，支持[轻松扩展自定义 Provider](docs/provider-development.md)。
- 🤖 **安全自动确认（Fail-Closed）**：
  - 仅在当前存在唯一活跃且匹配的交互请求时触发；
  - 发送方（Sender ID / Username）、消息特征词（Markers）与按钮文本必须同时命中严格白名单；
  - 只允许单一、无歧义的 allow-listed confirmation button；
  - 遇到未知按钮、多选歧义、不可编程点击或执行异常时，一律安全退避至 `human_required`。
- 🧩 **Human Fallback（人工干预可恢复）**：
  - Relay 专注于 Telegram 交互中继，不强绑定特定通知通道；当无法自动安全完成时向 caller 暴露 `human_required` 状态；
  - 调用端可根据自身业务通过飞书、钉钉、Telegram Bot、邮件等渠道即时告警，并保持原任务上下文等待用户在真实手机端确认。
- 🐳 **双模加固部署**：
  - Docker Compose：named volume 持久化 Session，`/readyz` 作为容器健康检查；
  - systemd：代码 root-owned，仅 `/var/lib/moyu-tg-relay` 可持久写入。
- 🧭 **引导式自动化向导**：自动生成 Bearer Token、完成 Session bootstrap、提取并回填 `TELEGRAM_ACCOUNT_ID`、启动服务并执行完整 smoke check。

---

## 🔄 Interaction State Machine

```text
调用方客户端 (Automation Client) 创建 active request
                    ↓
        Telegram incoming message
                    ↓
        (Provider 消息识别与规则评估)
                    ↓
┌───────────────────────────────────────┐
│ OTP code (收到验证码)                  │
│   → ready → consume once (一次性安全提取)│
├───────────────────────────────────────┤
│ allow-listed confirmation (命中白名单) │
│   → click (受限安全自动点击)            │
│   → auto_attempted                    │
├───────────────────────────────────────┤
│ unknown / unsafe / click fail (不可控) │
│   → human_required (通知人工介入)      │
└───────────────────────────────────────┘
```

状态说明：

```text
pending
  尚未收到可处理的目标 Telegram 交互消息

auto_attempted
  Relay 已尝试安全自动确认，caller 应给予目标服务一个短暂 grace period 观察状态

human_required
  无法安全自动完成（如未知按钮、异常），caller 应通知人工介入并在原任务上下文中等待

ready
  OTP 验证码已就绪，等待调用方一次性提取

consumed / expired / cancelled
  终态（已消费 / 超时失效 / 主动取消）
```

> **设计保障**：OTP 在 `auto_attempted` 或 `human_required` 之后仍可到达并把 request 转为 `ready`。当用户在手机端手动确认后，服务后续发送的验证码仍会被正常捕获，无需创建第二个 request。

---

## 🔌 Provider 插件架构

`moyu-tg-relay` 采用解耦设计，将 Telegram 底层传输与具体业务识别规则分离：

```text
Telegram MTProto / Telethon
            ↓
       Relay Core (会话生命周期 / 请求路由 / 鉴权 / TTL 存储)
            ↓
    Provider Registry (注册表)
            ↓
  ┌───────────────────┬─────────────────────┐
  │ Hax Provider      │ Custom Provider ... │
  │ (内置提供者)       │ (用户自定义提供者)   │
  └───────────────────┴─────────────────────┘
```

- **内置 Provider**：当前默认包含 `hax` Provider（实现 Hax 验证码提取与安全确认交互）；
- **自定义扩展**：只需实现标准 `evaluate(message, request)` 接口即可接入任何 Telegram Bot 或群组交互。详见 [Provider 开发指南](docs/provider-development.md)。

---

## 🛡️ 自动交互安全策略（Fail-Closed 原则）

Relay 坚持 **Fail-Closed（故障安全断开）** 原则。**绝不提供“只要看到 Telegram 里有 Confirm 按钮就全局乱点”的危险逻辑。**

每个 Provider（无论是内置 Provider 还是自定义扩展）在评估自动确认时，都必须遵循严格的白名单与状态边界：

1. **唯一活跃请求**：当前 `TELEGRAM_ACCOUNT_ID` 必须恰好存在一个匹配的 active request；
2. **发送方严格白名单**：发送方必须为 Provider 显式声明的 Bot username，或 sender ID 命中受信任的系统白名单（如官方系统号 `777000`）；
3. **消息特征白名单**：消息正文必须匹配 Provider 声明的特征标记（Markers）；
4. **单一受限按钮白名单**：消息中必须有且仅有一个按钮命中允许的自动确认白名单；任何未知按钮、多选歧义或执行异常一律安全退避至 `human_required`。

### 内置 Hax Provider 配置示例

内置 `hax` Provider 严格遵循上述准则，默认安全配置如下：

```text
HAX_TELEGRAM_BOT=HaxTG_bot
HAX_AUTO_CONFIRM=true
HAX_CONFIRMATION_SENDER_IDS=777000
HAX_CONFIRMATION_MARKERS=hax.co.id,hax
HAX_AUTO_CONFIRM_BUTTONS=confirm,approve,authorize,accept,yes,continue
```

如果不希望 Hax 执行任何自动点击，可设置：

```text
HAX_AUTO_CONFIRM=false
```

此时一旦匹配到确认卡片将直接安全进入 `human_required` 状态，提示人工在手机端确认。

---

## 🔐 Session 与 Secret 模型

以下内容均属于高敏感凭据，严禁提交到仓库、Issue、PR、日志或 Artifact 中：

```text
OTP_RELAY_BEARER_TOKEN
TELEGRAM_API_HASH
TELEGRAM_SESSION_STRING
*.session
```

`TELEGRAM_SESSION_STRING` 与文件 `.session` 拥有完全等价的 Telegram 长期登录权限，应按最高安全级别 Secret 保管。

### 独立 Docker / systemd 部署

推荐使用文件 Session。部署向导会在目标主机上交互式完成 Telegram 登录，并将 `.session` 保存在受限权限的持久化隔离目录中。

### Secret-managed / Workload 部署

可在可信本地机器一次性执行：

```bash
python -m moyu_tg_relay.bootstrap_session
```

完成 Telegram 登录后会输出：

```text
TELEGRAM_ACCOUNT_ID=<account-id>
TELEGRAM_SESSION_STRING=<secret-session-string>
```

将 `TELEGRAM_SESSION_STRING` 存入部署平台的 Secret store 后，运行时通过环境变量注入即可。服务在检测到 `TELEGRAM_SESSION_STRING` 时优先使用 `StringSession`；未配置时回退兼容 `TELEGRAM_SESSION_PATH` 文件 Session。

---

## 🚀 推荐：引导式部署

克隆仓库后只需运行一个命令：

```bash
git clone https://github.com/MoyuFamily/moyu-tg-relay.git
cd moyu-tg-relay

# 启动统一交互式管理控制台
python3 -m scripts.manager

# 或直接执行自动化部署向导
./deploy/install.sh
```

如果 Docker Compose 和 systemd 均可用，向导会提供交互式选择。也可显式指定模式：

```bash
# Docker Compose（推荐）
./deploy/install.sh docker

# Native systemd
sudo ./deploy/install.sh systemd
```

首次部署时只需提供 Telegram `API ID` / `API Hash`，随后按 Telethon 提示输入手机号、登录验证码以及账号 2FA 密码（若开启）。向导会自动完成其余全部工作：

```text
配置检查
  -> 自动生成 256 位 Relay Bearer Token
  -> 构建/安装 runtime
  -> Telegram Session bootstrap
  -> 自动捕获 TELEGRAM_ACCOUNT_ID
  -> 写回受限权限 env 文件 (0600)
  -> 启动 Relay 服务
  -> /healthz + /readyz 存活探针
  -> Bearer reject (401) + accept (404) 冒烟验收
```

向导具备幂等性：检测到有效 Session 与 `TELEGRAM_ACCOUNT_ID` 时会自动复用，避免重复登录。

> Relay 本地仅监听 `127.0.0.1:8787`。公网通信必须经由 Caddy / Nginx / Traefik 配置 **HTTPS 反向代理**，切勿将明文 8787 端口直接暴露至公网。

完整手工部署与排障文档请参阅 [deploy/README.md](deploy/README.md)。

---

## 🔍 健康检查与上线验收

基础存活检查（Liveness）：

```bash
python3 smoke_check.py --base-url http://127.0.0.1:8787
```

完整就绪性与鉴权校验（Readiness + Auth）：

```bash
# Docker：在容器内部执行，无泄漏命令历史风险
docker compose --env-file .env -f deploy/docker/compose.yml exec -T moyu-tg-relay \
  python /app/smoke_check.py --base-url http://127.0.0.1:8787

# systemd：从受限权限的 env 文件安全读取 Token
sudo /opt/moyu-tg-relay/.venv/bin/python /opt/moyu-tg-relay/smoke_check.py \
  --base-url http://127.0.0.1:8787 \
  --env-file /etc/moyu-tg-relay.env
```

完整 smoke check 会严格验证：HTTP 进程存活、Telethon MTProto 已连接就绪、错误 Bearer Token 返回 401，以及有效 Token 成功通过鉴权。

---

## 🔗 调用方客户端接入 (Client Integration)

Relay 配置好 HTTPS 反向代理后，任何外部调用方（如自动化脚本、CI/CD Runner、定时保活服务等）只需配置两个环境变量：

```text
OTP_RELAY_URL=https://relay.example.com
OTP_RELAY_TOKEN=<OTP_RELAY_BEARER_TOKEN>
```

> **客户端适配说明**：通用调用端建议统一配置 `OTP_RELAY_URL` 与 `OTP_RELAY_TOKEN`。在部分下游生态（如 `moyu-renew` 云实例自动续期）中，亦兼容对应的 `HAX_OTP_RELAY_URL` 与 `HAX_OTP_RELAY_TOKEN`。

### 核心调用流程

1. **申请待提取请求**：
   ```bash
   POST /v1/otp/requests
   Authorization: Bearer <OTP_RELAY_TOKEN>
   Content-Type: application/json

   {
     "provider": "hax",
     "account": "<TELEGRAM_ACCOUNT_ID>",
     "ttl_seconds": 300,
     "context": {"stage": "login"}
   }
   ```
   > 💡 `"provider"` 字段指定目标业务提供者（如内置的 `"hax"`，或自行扩展注册的 provider）。
2. **轮询状态**：
   ```bash
   GET /v1/otp/requests/{request_id}
   Authorization: Bearer <OTP_RELAY_TOKEN>
   ```
   - 若状态为 `auto_attempted`：给予目标网页短暂等待（如 5~10 秒），观察是否通过；
   - 若状态为 `human_required`：调用端通过自身渠道（飞书、钉钉、Telegram Bot 等）即时告警，并保持任务上下文等待人工处理；
   - 若状态为 `ready`：即可提取验证码。
3. **单次提取验证码**：
   ```bash
   POST /v1/otp/requests/{request_id}/consume
   Authorization: Bearer <OTP_RELAY_TOKEN>
   ```
   接口返回 `{"code": "..."}`。提取后请求状态立即变为 `consumed`，验证码从内存中彻底擦除。
4. **清理释放**：
   ```bash
   DELETE /v1/otp/requests/{request_id}
   ```

---

## 📡 HTTP API 契约

| 方法 | 路径 | 鉴权 | 描述 |
| :--- | :--- | :---: | :--- |
| `GET` | `/healthz` | 否 | 进程存活检查（Liveness） |
| `GET` | `/readyz` | 否 | Telegram 连通性检查（Readiness，200=可用，503=未就绪） |
| `POST` | `/v1/otp/requests` | 是 | 创建等待交互请求（绑定 `provider` 与 `account`） |
| `GET` | `/v1/otp/requests/{id}` | 是 | 查询交互状态与安全详情（不返回验证码） |
| `POST` | `/v1/otp/requests/{id}/consume` | 是 | **一次性提取** 验证码（提取后立即失效） |
| `DELETE` | `/v1/otp/requests/{id}` | 是 | 取消交互请求 |

`GET /v1/otp/requests/{request_id}` 响应格式：

```json
{
  "request_id": "...",
  "status": "pending | auto_attempted | human_required | ready | consumed | expired | cancelled",
  "detail": "安全状态描述"
}
```

---

## 🔒 安全报告

如果您在代码或部署流程中发现任何安全缺陷，请勿在公开 Issue 或 PR 中附带真实 Token、API Hash、StringSession 或 `.session` 内容。请先查阅 [SECURITY.md](SECURITY.md)。

---

## 📄 开源协议

基于 [MIT License](LICENSE) 开源。
