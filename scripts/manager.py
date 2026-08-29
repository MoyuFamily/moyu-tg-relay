#!/usr/bin/env python3
"""
Moyu Telegram Relay 统一交互式管理与运维控制台。

支持：
1. 本地 Relay 服务调试运行 (Uvicorn / FastAPI)；
2. 生产部署冒烟连通性验收 (smoke_check.py)；
3. 本地单元与集成测试套件执行 (pytest)；
4. .env 环境变量与 Telegram Session 状态检查；
5. Docker / systemd 自动化部署与引导向导 (deploy/install.sh)。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


class ConsoleStyle:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def print_banner() -> None:
    print(f"\n{ConsoleStyle.BOLD}{ConsoleStyle.CYAN}{'=' * 58}{ConsoleStyle.RESET}")
    print(f"{ConsoleStyle.BOLD}{ConsoleStyle.CYAN}    🤖 Moyu Telegram Relay 统一运维与管理控制台{ConsoleStyle.RESET}")
    print(f"{ConsoleStyle.BOLD}{ConsoleStyle.CYAN}{'=' * 58}{ConsoleStyle.RESET}")


def load_env_map() -> dict[str, str]:
    if not ENV_FILE.is_file():
        return {}
    content = ENV_FILE.read_text(encoding="utf-8")
    env_map = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" in line:
            k, v = line.split("=", 1)
            env_map[k.strip()] = v.strip().strip("'").strip('"')
    return env_map


def handle_env_check() -> None:
    print(f"\n{ConsoleStyle.BOLD}📋 本地环境与配置状态检查:{ConsoleStyle.RESET}")
    env_map = load_env_map()
    if not env_map:
        print(f"  {ConsoleStyle.YELLOW}⚠️ 未检测到 .env 文件 (路径: {ENV_FILE}){ConsoleStyle.RESET}")
        print(f"  💡 可参考 .env.example 进行配置。")
        return

    keys = [
        ("OTP_RELAY_BEARER_TOKEN", "Bearer 鉴权 Token"),
        ("TELEGRAM_API_ID", "Telegram API ID"),
        ("TELEGRAM_API_HASH", "Telegram API Hash"),
        ("TELEGRAM_ACCOUNT_ID", "Telegram 账号 ID"),
        ("HAX_TELEGRAM_BOT", "Hax 机器人代号"),
        ("HAX_AUTO_CONFIRM", "自动确认开关"),
    ]

    for key, desc in keys:
        val = env_map.get(key)
        if val:
            masked = (val[:3] + "***" + val[-3:]) if len(val) > 8 else "***"
            status = f"{ConsoleStyle.GREEN}已配置{ConsoleStyle.RESET}"
            print(f"  ✅ {ConsoleStyle.BOLD}{key:<26}{ConsoleStyle.RESET} [{status}] {desc} ({masked})")
        else:
            status = f"{ConsoleStyle.RED}未配置{ConsoleStyle.RESET}"
            print(f"  ❌ {ConsoleStyle.BOLD}{key:<26}{ConsoleStyle.RESET} [{status}] {desc}")

    # Check session file if present
    session_files = list(ROOT.glob("*.session")) + list((ROOT / "deploy").glob("*.session"))
    if session_files:
        print(f"\n  📂 检测到 Telegram Session 文件: {', '.join(f.name for f in session_files)}")
    else:
        print(f"\n  ⚠️ 当前未在工作区检测到 .session 文件（通常在首次 bootstrap 后生成）")


def get_python_exe() -> str:
    venv_py = ROOT / ".venv" / "bin" / "python"
    if venv_py.is_file() and os.access(venv_py, os.X_OK):
        return str(venv_py)
    return sys.executable


def handle_run_service(host: str = "0.0.0.0", port: int = 8080, reload: bool = True) -> None:
    print(f"\n{ConsoleStyle.BOLD}🚀 正在启动 Moyu Telegram Relay 服务 ({host}:{port})...{ConsoleStyle.RESET}\n")
    py_exe = get_python_exe()
    cmd = [
        py_exe,
        "-m",
        "uvicorn",
        "moyu_tg_relay.app:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")
    env = os.environ.copy()
    src_dir = str(ROOT / "src")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{src_dir}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_dir
    subprocess.run(cmd, cwd=str(ROOT), env=env)


def handle_smoke_check(url: str | None = None, token: str | None = None) -> None:
    print(f"\n{ConsoleStyle.BOLD}🧪 正在执行生产/本地 Smoke Check 连通性冒烟验收...{ConsoleStyle.RESET}\n")
    py_exe = get_python_exe()
    cmd = [py_exe, str(ROOT / "smoke_check.py")]
    if url:
        cmd.extend(["--base-url", url])
    if token:
        cmd.extend(["--token", token])
    subprocess.run(cmd, cwd=str(ROOT))


def handle_unit_tests() -> None:
    print(f"\n{ConsoleStyle.BOLD}🧪 正在运行单元与集成测试 (unittest / pytest)...{ConsoleStyle.RESET}\n")
    py_exe = get_python_exe()
    env = os.environ.copy()
    src_dir = str(ROOT / "src")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{src_dir}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_dir

    # Try pytest first, fallback to unittest
    res = subprocess.run([py_exe, "-m", "pytest", "tests", "-v"], cwd=str(ROOT), env=env)
    if res.returncode != 0:
        # Fallback to unittest discover
        subprocess.run([py_exe, "-m", "unittest", "discover", "tests", "-v"], cwd=str(ROOT), env=env)



def handle_deployment_guide() -> None:
    print(f"\n{ConsoleStyle.BOLD}🐳 生产部署与向导 (deploy/install.sh):{ConsoleStyle.RESET}")
    install_script = ROOT / "deploy" / "install.sh"
    if not install_script.is_file():
        print(f"{ConsoleStyle.RED}❌ 未找到 {install_script}{ConsoleStyle.RESET}")
        return
    print(f"  安装脚本路径: {install_script}")
    print("  支持模式：Docker Compose / systemd 自动化引导")
    confirm_run = input(f"\n{ConsoleStyle.CYAN}是否执行 install.sh 部署向导？ [y/N]: {ConsoleStyle.RESET}").strip().lower()
    if confirm_run in ("y", "yes"):
        subprocess.run(["bash", str(install_script)], cwd=str(ROOT))


def interactive_loop() -> None:
    while True:
        print_banner()
        print(f"当前服务目录: {ConsoleStyle.BOLD}{ConsoleStyle.GREEN}{ROOT.name}{ConsoleStyle.RESET}\n")
        print(f"  {ConsoleStyle.BOLD}[1]{ConsoleStyle.RESET} 🚀 启动本地 Relay 服务 (Run Uvicorn Server)")
        print(f"  {ConsoleStyle.BOLD}[2]{ConsoleStyle.RESET} 🧪 运行 Smoke Check 冒烟验收 (Run Smoke Check)")
        print(f"  {ConsoleStyle.BOLD}[3]{ConsoleStyle.RESET} 🧪 运行测试套件 (Run Pytest Tests)")
        print(f"  {ConsoleStyle.BOLD}[4]{ConsoleStyle.RESET} 📋 检查本地 .env 与配置 (Check Environment)")
        print(f"  {ConsoleStyle.BOLD}[5]{ConsoleStyle.RESET} 🐳 生产部署与引导 (Run install.sh)")
        print(f"  {ConsoleStyle.BOLD}[0]{ConsoleStyle.RESET} 🚪 退出控制台")
        print(f"\n{ConsoleStyle.CYAN}{'=' * 58}{ConsoleStyle.RESET}")

        choice = input(f"{ConsoleStyle.BOLD}请选择操作 [0-5]: {ConsoleStyle.RESET}").strip()
        if choice in ("0", "q", "exit"):
            print(f"\n{ConsoleStyle.GREEN}👋 再见！{ConsoleStyle.RESET}\n")
            break
        elif choice == "1":
            handle_run_service()
        elif choice == "2":
            handle_smoke_check()
        elif choice == "3":
            handle_unit_tests()
        elif choice == "4":
            handle_env_check()
        elif choice == "5":
            handle_deployment_guide()
        else:
            print(f"{ConsoleStyle.RED}❌ 无效选项，请重新选择{ConsoleStyle.RESET}")

        input(f"\n{ConsoleStyle.DIM}按 Enter 键继续...{ConsoleStyle.RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Moyu Telegram Relay 统一运维与管理控制台"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令 (留空进入交互模式)")

    # run
    run_p = subparsers.add_parser("run", help="启动本地 Relay 服务")
    run_p.add_argument("--host", default="0.0.0.0", help="监听地址")
    run_p.add_argument("--port", type=int, default=8080, help="监听端口")
    run_p.add_argument("--no-reload", action="store_true", help="禁用代码热重载")

    # smoke
    smoke_p = subparsers.add_parser("smoke", help="执行 Smoke Check 连通性冒烟验收")
    smoke_p.add_argument("--url", help="目标 Relay 基础 URL")
    smoke_p.add_argument("--token", help="Bearer Token")

    # test
    subparsers.add_parser("test", help="运行本地测试套件")

    # check
    subparsers.add_parser("check", help="检查本地环境变量与配置")

    # install
    subparsers.add_parser("install", help="执行部署向导")

    args = parser.parse_args()

    if not args.command:
        interactive_loop()
        return 0

    if args.command == "run":
        handle_run_service(host=args.host, port=args.port, reload=not args.no_reload)
    elif args.command == "smoke":
        handle_smoke_check(url=args.url, token=args.token)
    elif args.command == "test":
        handle_unit_tests()
    elif args.command == "check":
        handle_env_check()
    elif args.command == "install":
        handle_deployment_guide()

    return 0


if __name__ == "__main__":
    sys.exit(main())
