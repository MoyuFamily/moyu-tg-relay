# Systemd Deployment Guide

本指南说明如何在 Linux 生产主机上使用 systemd 原生服务运行 `moyu-tg-relay`。

---

## 1. 系统用户与目录准备

```bash
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/moyu-tg-relay moyu-tg-relay
sudo mkdir -p /var/lib/moyu-tg-relay /opt/moyu-tg-relay
sudo chown -R moyu-tg-relay:moyu-tg-relay /var/lib/moyu-tg-relay /opt/moyu-tg-relay
```

## 2. 部署代码与虚拟环境

将仓库代码放到 `/opt/moyu-tg-relay` 后执行：

```bash
cd /opt/moyu-tg-relay
sudo -u moyu-tg-relay python3 -m venv .venv
sudo -u moyu-tg-relay .venv/bin/pip install --upgrade pip
sudo -u moyu-tg-relay .venv/bin/pip install .
```

仓库提供 `pyproject.toml`，因此 `pip install .` 会安装 `src/` layout 下的 `moyu_tg_relay` 包及运行依赖，不需要额外设置 `PYTHONPATH`。

## 3. 配置环境变量

复制模板文件到 `/etc/moyu-tg-relay.env` 并设置仅 root 与服务组可读：

```bash
sudo cp deploy/systemd/moyu-tg-relay.env.example /etc/moyu-tg-relay.env
sudo chown root:moyu-tg-relay /etc/moyu-tg-relay.env
sudo chmod 0640 /etc/moyu-tg-relay.env
# 编辑填入真实 API_ID / API_HASH / Token；TELEGRAM_ACCOUNT_ID 在 bootstrap 后回写
sudo nano /etc/moyu-tg-relay.env
```

## 4. 初始化 Telegram Session

bootstrap 必须显式加载与 systemd 服务相同的环境文件：

```bash
sudo -u moyu-tg-relay sh -c '
  set -a
  . /etc/moyu-tg-relay.env
  set +a
  exec /opt/moyu-tg-relay/.venv/bin/python -m moyu_tg_relay.bootstrap_session \
    --session-path /var/lib/moyu-tg-relay/telegram.session
'
```

成功后会输出：

```text
Telegram session authorised. TELEGRAM_ACCOUNT_ID=<your-id>
```

把输出的真实 `TELEGRAM_ACCOUNT_ID` 写回 `/etc/moyu-tg-relay.env`。正式服务启动时会校验该 ID 与已授权 Telegram Session 是否一致。

## 5. 安装并启动服务

```bash
sudo cp deploy/systemd/moyu-tg-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now moyu-tg-relay
sudo systemctl status moyu-tg-relay
```

上线验收：

```bash
curl --fail http://127.0.0.1:8787/readyz
/opt/moyu-tg-relay/.venv/bin/python /opt/moyu-tg-relay/smoke_check.py \
  --base-url http://127.0.0.1:8787 \
  --token '<OTP_RELAY_BEARER_TOKEN>'
```
