# 🐟 Moyu Telegram OTP Relay (`moyu-tg-relay`)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg)](deploy/docker/)

> **轻量、安全、解耦的 Telegram 2FA / OTP 验证码中继微服务。**
> 
> *让自动化脚本在无状态环境（如 GitHub Actions）中安全获取 Telegram 验证码，无需将 Telegram Session 凭据暴露给 Runner。*

---

## 🌟 核心特性

- 🔒 **严格安全边界**：Telethon Session 文件与 Telegram API 凭据仅保存在独立部署的 VPS 上，永不进入客户端 Runner 或代码库。
- ⚡ **一次性安全提取**：提供 Bearer Token 鉴权 REST API。状态查询端点绝不泄露验证码；仅有 `/v1/otp/requests/{id}/consume` 允许**单次安全消费**。
- ⏱️ **内存 TTL 队列**：每个 Telegram 账号只允许一个处于活跃 TTL（60~600s）的 pending 请求，过期或被新请求覆盖时自动销毁。
- 📦 **开箱即用部署**：提供标准的 **Docker Compose**（只读根文件系统、非 root 运行）与 **Native systemd** 部署资产。
- 🩺 **双重健康探针**：提供 `/healthz`（HTTP 进程存活）与 `/readyz`（Telegram MTProto 实际连接状态）探针。

---

## 🏗️ 架构概览

```mermaid
flowchart LR
    subgraph Client["自动化客户端 (如 moyu-renew)"]
        Runner["Batch Runner / Script"]
    end

    subgraph Service["moyu-tg-relay 独立微服务 (私有 VPS)"]
        FastAPI["FastAPI 鉴权网关
(Bearer Auth)"]
        Store["内存 TTL 队列
(一次性消费机制)"]
        Telethon["Telethon 守护进程
(持有持久化 Session)"]
    end

    subgraph TG["Telegram 平台"]
        Bot["@HaxTG_bot 等机器人"]
    end

    Runner -->|1. POST /v1/otp/requests
(申请等待验证码)| FastAPI
    FastAPI --> Store
    Bot -->|2. 发送 2FA 验证码| Telethon
    Telethon -->|3. 解析并绑定| Store
    Runner -->|4. POST .../consume
(一次性安全提取)| FastAPI
```

---

## 🚀 极速部署

### 方式一：Docker Compose（推荐）

1. **生成 Telegram Session**：
   ```bash
   pip install -r requirements.txt
   python src/moyu_tg_relay/bootstrap_session.py --session-path ./telegram.session
   ```
2. **配置环境变量**：
   ```bash
   cp deploy/docker/env.example deploy/docker/.env
   # 编辑 .env 填入你的 OTP_RELAY_BEARER_TOKEN、TELEGRAM_API_ID 等
   ```
3. **启动容器**：
   ```bash
   cd deploy/docker
   docker compose up -d
   ```

### 方式二：Native Linux (systemd)

详细操作请查看 [deploy/systemd/README.md](deploy/systemd/README.md)。

---

## 🔌 API 契约

所有业务接口均需携带 Header：`Authorization: Bearer <YOUR_TOKEN>`

| 方法 | 路径 | 描述 |
| :--- | :--- | :--- |
| `GET` | `/healthz` | 进程存活检查（无需鉴权） |
| `GET` | `/readyz` | Telegram 连通性检查（200=可用，503=未就绪） |
| `POST` | `/v1/otp/requests` | 创建待接收验证码请求（指定 `provider` 与 `account`） |
| `GET` | `/v1/otp/requests/{id}` | 查询状态（返回 `pending` / `ready`，不返回验证码） |
| `POST` | `/v1/otp/requests/{id}/consume` | **一次性提取** 验证码（提取后状态变为 `consumed`） |
| `DELETE` | `/v1/otp/requests/{id}` | 取消请求 |

---

## 🧪 连通性与健康检查

```bash
python smoke_check.py --base-url https://relay.yourdomain.com --token your-token
```

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。
