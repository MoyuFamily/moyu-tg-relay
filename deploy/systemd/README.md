# Systemd Deployment Guide

本指南说明如何在 Linux 生产主机上使用 systemd 原生服务运行 `moyu-tg-relay`。

优先推荐在仓库根目录直接运行引导式安装：

```bash
sudo ./deploy/install.sh systemd
```

向导会完成配置、Session bootstrap、`TELEGRAM_ACCOUNT_ID` 回填、服务安装和 smoke check。下面保留手工部署流程，便于排障或定制。

---

## 1. 系统用户与目录准备

```bash
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/moyu-tg-relay moyu-tg-relay
sudo install -d -o moyu-tg-relay -g moyu-tg-relay -m 0700 /var/lib/moyu-tg-relay
sudo install -d -o root -g root -m 0755 /opt/moyu-tg-relay
```

`/opt/moyu-tg-relay` 中的代码和虚拟环境应由 `root` 持有，**不要**授予服务用户写权限。服务进程唯一需要持久写入的目录是 `/var/lib/moyu-tg-relay`。

## 2. 部署代码与虚拟环境

将仓库代码放到 `/opt/moyu-tg-relay` 后执行：

```bash
cd /opt/moyu-tg-relay
sudo chown -R root:root /opt/moyu-tg-relay
sudo chmod -R go-w /opt/moyu-tg-relay
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install --upgrade pip
sudo .venv/bin/pip install .
```

`pyproject.toml` 是 Python package / standalone 安装的运行依赖来源；根目录 `requirements.txt` 同步维护相同的 pinned 依赖，供外部 Artifact 构建流程使用。CI 会校验两者保持一致。`src/` package layout 不需要额外 `PYTHONPATH`。

## 3. 配置环境变量

复制模板到 `/etc/moyu-tg-relay.env`：

```bash
sudo cp deploy/systemd/moyu-tg-relay.env.example /etc/moyu-tg-relay.env
sudo chown root:moyu-tg-relay /etc/moyu-tg-relay.env
sudo chmod 0640 /etc/moyu-tg-relay.env
sudo nano /etc/moyu-tg-relay.env
```

先填入真实的：

```text
OTP_RELAY_BEARER_TOKEN
TELEGRAM_API_ID
TELEGRAM_API_HASH
```

`TELEGRAM_ACCOUNT_ID` 在 bootstrap 后回填。

## 4. 初始化 Telegram Session

bootstrap 直接通过 `--env-file` 读取 literal `KEY=VALUE`，**不会用 shell source/eval 解析 Secret**。

systemd standalone 部署使用文件 Session。显式传入 `--session-path` 会保持历史兼容并自动选择 file-session 模式；也可以同时写出 `--file-session` 以强调意图：

```bash
sudo -u moyu-tg-relay \
  /opt/moyu-tg-relay/.venv/bin/python -m moyu_tg_relay.bootstrap_session \
  --env-file /etc/moyu-tg-relay.env \
  --file-session \
  --session-path /var/lib/moyu-tg-relay/telegram.session
```

成功后会输出：

```text
Telegram session authorised. TELEGRAM_ACCOUNT_ID=<your-id>
```

把真实 `TELEGRAM_ACCOUNT_ID` 写回 `/etc/moyu-tg-relay.env`。正式服务启动时会校验该 ID 与已授权 Session 是否一致。

如果需要 Secret-managed / portable 部署，则不要传 `--session-path` / `--file-session`；裸调用 bootstrap 会输出 `TELEGRAM_SESSION_STRING`。

## 5. 安装并启动服务

```bash
sudo cp deploy/systemd/moyu-tg-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now moyu-tg-relay
sudo systemctl status moyu-tg-relay
```

## 6. 上线验收

```bash
curl --fail http://127.0.0.1:8787/readyz
sudo /opt/moyu-tg-relay/.venv/bin/python /opt/moyu-tg-relay/smoke_check.py \
  --base-url http://127.0.0.1:8787 \
  --env-file /etc/moyu-tg-relay.env
```

完整 smoke check 同时验证 liveness、Telegram readiness、错误 Bearer Token 被拒绝，以及正确 Token 能通过鉴权进入 handler。
