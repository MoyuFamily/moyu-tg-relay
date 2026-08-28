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
  - 基于 Bearer Token 强鉴权与 Constant-Time 签名比较；
  - 彻底关闭 Swagger / OpenAPI / ReDoc 公开调试端点；
  - 生产级沙箱：systemd 单元（14 项内核级加固）、Docker（`read_only: true` + `cap_drop: [ALL]`）。
- ⚡ **轻量且高内聚**：
  - 基于 FastAPI + Telethon 构建，非阻塞异步监听；
  - 纯内存线程安全状态管理，支持 TTL 自动过期与一次性消费（One-Time Consume）。
- 🐳 **双模部署支持**：
  - **Docker Compose**：内置命名卷持久化 session 与健康检查探针；
  - **systemd**：提供开箱即用的 Linux 主机守护服务与权限配置指南。

---

## 🚀 极速部署

### 方式一：Docker Compose（推荐）

1. **配置环境变量**：
   ```bash
   cp deploy/docker/env.example .env
   # 编辑填入真实 TELEGRAM_API_ID, TELEGRAM_API_HASH 等
   nano .env
   ```

2. **交互式初始化 Telegram Session**：
   ```bash
   python3 -m moyu_tg_relay.bootstrap_session --session-path ./.state/telegram.session
   ```

3. **启动容器**：
   ```bash
   docker compose -f deploy/docker/compose.yml up -d
   ```

### 方式二：Linux systemd 原生部署

详细指南请参阅 [deploy/systemd/README.md](deploy/systemd/README.md)。

---

## 🔍 健康检查与探针

```bash
# 检查基础存活 (Liveness)
python3 smoke_check.py --base-url http://127.0.0.1:8787

# 完整就绪性与鉴权校验 (Readiness)
python3 smoke_check.py --base-url http://127.0.0.1:8787 --token <YOUR_BEARER_TOKEN>
```

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。
