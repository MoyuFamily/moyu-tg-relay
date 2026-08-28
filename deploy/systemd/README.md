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

```bash
cd /opt/moyu-tg-relay
sudo -u moyu-tg-relay python3 -m venv .venv
sudo -u moyu-tg-relay .venv/bin/pip install -r requirements.txt
sudo -u moyu-tg-relay .venv/bin/pip install .
```

## 3. 配置环境变量

复制模板文件到 `/etc/moyu-tg-relay.env` 并设置受控权限：

```bash
sudo cp deploy/systemd/moyu-tg-relay.env.example /etc/moyu-tg-relay.env
sudo chmod 0600 /etc/moyu-tg-relay.env
sudo chown root:moyu-tg-relay /etc/moyu-tg-relay.env
# 编辑填入真实 API_ID / API_HASH / Token
sudo nano /etc/moyu-tg-relay.env
```

## 4. 初始化 Telegram Session

```bash
sudo -u moyu-tg-relay /opt/moyu-tg-relay/.venv/bin/python -m moyu_tg_relay.bootstrap_session --session-path /var/lib/moyu-tg-relay/telegram.session
```

## 5. 安装并启动服务

```bash
sudo cp deploy/systemd/moyu-tg-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now moyu-tg-relay
sudo systemctl status moyu-tg-relay
```
