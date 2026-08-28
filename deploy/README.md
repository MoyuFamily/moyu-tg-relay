# moyu-tg-relay 部署指南

## 首选入口：部署向导

在仓库根目录运行：

```bash
./deploy/install.sh
```

或显式选择：

```bash
./deploy/install.sh docker
sudo ./deploy/install.sh systemd
```

向导负责环境配置、Bearer Token 生成、Telegram Session bootstrap、`TELEGRAM_ACCOUNT_ID` 自动回填、服务启动和完整 smoke check。

## 手工部署

- **Docker Compose**：使用根目录 `.env.example` 作为唯一 Docker env 模板，Compose 文件位于 `deploy/docker/compose.yml`。
- **Native systemd**：完整手工步骤见 [systemd/README.md](systemd/README.md)。

## 公网访问

Relay runtime 始终只在 `127.0.0.1:8787` 提供本地 HTTP。公网访问必须通过 HTTPS reverse proxy；参考 [Caddyfile.example](Caddyfile.example)。

不要直接把 8787 暴露到公网，也不要把 Telegram API Hash 或 Telethon `.session` 放入 GitHub Actions。
