"""Self-contained modern responsive Admin Web Dashboard for Moyu TG Relay.

Features:
- Obsidian slate dark theme with glassmorphic accents & responsive layout;
- Web-standard semantic form supporting browser & password manager autofill
  (1Password, Bitwarden, Apple Keychain, Chrome/Edge);
- Live auto-refresh, multi-dimensional filters, keyword search;
- Detailed slide-out drawer / modal for JSON metadata and full Telegram context;
- Zero external CDN dependencies: works completely offline and in private networks.
"""

from __future__ import annotations

import base64

TG_RELAY_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" fill="none">
  <defs>
    <linearGradient id="tgr-bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0b101d"/>
      <stop offset="50%" stop-color="#0d1527"/>
      <stop offset="100%" stop-color="#141a2e"/>
    </linearGradient>
    <linearGradient id="tgr-border" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00aaff" stop-opacity="0.85"/>
      <stop offset="50%" stop-color="#6366f1" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.8"/>
    </linearGradient>
    <linearGradient id="tgr-plane-main" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="100%" stop-color="#0284c7"/>
    </linearGradient>
    <linearGradient id="tgr-plane-fold" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#bae6fd"/>
      <stop offset="100%" stop-color="#38bdf8"/>
    </linearGradient>
    <linearGradient id="tgr-plane-dark" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0369a1"/>
      <stop offset="100%" stop-color="#075985"/>
    </linearGradient>
    <linearGradient id="tgr-pulse" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#06b6d4"/>
    </linearGradient>
    <linearGradient id="tgr-fish" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="50%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#c084fc"/>
    </linearGradient>
    <filter id="tgr-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="1.5" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
  </defs>

  <rect width="64" height="64" rx="15" fill="url(#tgr-bg)"/>
  <rect x="0.75" y="0.75" width="62.5" height="62.5" rx="14.25" fill="none" stroke="url(#tgr-border)" stroke-width="1.5"/>

  <path d="M 44 14 A 12 12 0 0 1 52 22" stroke="url(#tgr-pulse)" stroke-width="2.2" stroke-linecap="round" fill="none" opacity="0.85"/>
  <path d="M 48 10 A 18 18 0 0 1 58 20" stroke="url(#tgr-pulse)" stroke-width="2.2" stroke-linecap="round" fill="none" opacity="0.5"/>

  <path d="M 12 48 C 16 46, 20 49, 23 46 C 26 43, 25 39, 28 36" stroke="url(#tgr-fish)" stroke-width="2.2" stroke-linecap="round" fill="none" opacity="0.75"/>
  <circle cx="12" cy="48" r="1.8" fill="#38bdf8" opacity="0.9"/>
  <circle cx="17" cy="52" r="1.2" fill="#818cf8" opacity="0.6"/>

  <g transform="translate(3, 1)" filter="url(#tgr-glow)">
    <path d="M 46 16 L 18 31 L 28 36 L 46 16 Z" fill="url(#tgr-plane-fold)"/>
    <path d="M 46 16 L 28 36 L 33 46 L 46 16 Z" fill="url(#tgr-plane-main)"/>
    <path d="M 28 36 L 31 43 L 34 37 Z" fill="url(#tgr-plane-dark)"/>
  </g>
</svg>"""

TG_RELAY_FAVICON_DATA_URI = f"data:image/svg+xml;base64,{base64.b64encode(TG_RELAY_LOGO_SVG.encode('utf-8')).decode('ascii')}"


def render_admin_html() -> str:
    """Return the complete single-page application HTML for the admin dashboard."""
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Moyu Telegram Relay 运维后台</title>
  <meta name="description" content="Moyu Telegram Interaction Relay 统一活动日志与运行状态审计控制台">
  <link rel="icon" type="image/svg+xml" href="__FAVICON_DATA_URI__">
  <link rel="alternate icon" href="/favicon.ico">
  <style>
    :root {
      --bg-base: #0a0d14;
      --bg-surface: #111622;
      --bg-surface-elevated: #182030;
      --bg-card: rgba(20, 27, 42, 0.75);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-focus: #6366f1;
      --text-main: #f3f4f6;
      --text-muted: #9ca3af;
      --text-subtle: #6b7280;
      --primary: #6366f1;
      --primary-hover: #4f46e5;
      --primary-glow: rgba(99, 102, 241, 0.25);
      --accent-cyan: #06b6d4;
      --accent-green: #10b981;
      --accent-yellow: #f59e0b;
      --accent-red: #ef4444;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --shadow-card: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
      --backdrop-blur: blur(12px);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      background-image:
        radial-gradient(circle at 15% 15%, rgba(99, 102, 241, 0.07) 0%, transparent 40%),
        radial-gradient(circle at 85% 20%, rgba(6, 182, 212, 0.05) 0%, transparent 40%),
        radial-gradient(circle at 50% 90%, rgba(16, 185, 129, 0.04) 0%, transparent 50%);
      background-attachment: fixed;
    }

    /* Top Navigation Header */
    header.navbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 24px;
      background: rgba(17, 22, 34, 0.85);
      backdrop-filter: var(--backdrop-blur);
      -webkit-backdrop-filter: var(--backdrop-blur);
      border-bottom: 1px solid var(--border-subtle);
      position: sticky;
      top: 0;
      z-index: 100;
    }

    .nav-brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      border-radius: var(--radius-md);
      background: transparent;
      border: 0;
      flex-shrink: 0;
      transition: transform 0.2s ease, filter 0.2s ease;
    }

    .brand-icon:hover {
      transform: scale(1.05);
      filter: drop-shadow(0 0 8px rgba(56, 189, 248, 0.4));
    }

    .brand-icon svg {
      width: 100%;
      height: 100%;
      display: block;
    }

    .brand-text h1 {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: -0.01em;
      color: #fff;
    }

    .brand-text .sub {
      font-size: 11px;
      color: var(--text-subtle);
    }

    .nav-meta {
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 500;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--text-subtle);
    }

    .status-dot.online {
      background: var(--accent-green);
      box-shadow: 0 0 8px var(--accent-green);
    }

    .status-dot.offline {
      background: var(--accent-red);
      box-shadow: 0 0 8px var(--accent-red);
    }

    .nav-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 12px;
      border-radius: var(--radius-sm);
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border-subtle);
      color: var(--text-main);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .nav-btn:hover {
      background: rgba(255, 255, 255, 0.12);
      border-color: rgba(255, 255, 255, 0.2);
    }

    .nav-btn.primary {
      background: var(--primary);
      border-color: var(--primary);
      color: #fff;
    }

    .nav-btn.primary:hover {
      background: var(--primary-hover);
    }

    /* Main Container */
    main.container {
      max-width: 1440px;
      width: 100%;
      margin: 0 auto;
      padding: 20px 24px 40px;
      flex: 1;
    }

    /* Metric Cards */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }

    .metric-card {
      background: var(--bg-card);
      backdrop-filter: var(--backdrop-blur);
      -webkit-backdrop-filter: var(--backdrop-blur);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 16px 20px;
      box-shadow: var(--shadow-card);
      position: relative;
      overflow: hidden;
    }

    .metric-card::before {
      content: "";
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--border-focus), transparent);
      opacity: 0.5;
    }

    .metric-title {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .metric-value {
      font-size: 26px;
      font-weight: 700;
      color: #fff;
      font-family: var(--font-sans);
      display: flex;
      align-items: baseline;
      gap: 8px;
    }

    .metric-desc {
      font-size: 11px;
      color: var(--text-subtle);
      margin-top: 4px;
    }

    /* Controls & Toolbar */
    .toolbar-panel {
      background: var(--bg-card);
      backdrop-filter: var(--backdrop-blur);
      -webkit-backdrop-filter: var(--backdrop-blur);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 16px;
      margin-bottom: 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
    }

    .filter-group {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }

    .input-wrapper {
      position: relative;
      min-width: 240px;
    }

    input.search-input {
      width: 100%;
      background: rgba(10, 13, 20, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 8px 12px 8px 32px;
      color: #fff;
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s ease;
    }

    input.search-input:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 2px var(--primary-glow);
    }

    .search-icon {
      position: absolute;
      left: 10px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-subtle);
      font-size: 14px;
      pointer-events: none;
    }

    select.filter-select {
      background: rgba(10, 13, 20, 0.7);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
      color: var(--text-main);
      font-size: 13px;
      outline: none;
      cursor: pointer;
    }

    select.filter-select:focus {
      border-color: var(--border-focus);
    }

    .action-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    /* Logs Table Panel */
    .table-panel {
      background: var(--bg-card);
      backdrop-filter: var(--backdrop-blur);
      -webkit-backdrop-filter: var(--backdrop-blur);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      overflow: hidden;
      box-shadow: var(--shadow-card);
    }

    .table-container {
      width: 100%;
      overflow-x: auto;
    }

    table.logs-table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 13px;
    }

    table.logs-table th {
      background: rgba(17, 22, 34, 0.95);
      color: var(--text-muted);
      font-weight: 600;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border-subtle);
      white-space: nowrap;
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.05em;
    }

    table.logs-table td {
      padding: 10px 14px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: var(--text-main);
      vertical-align: middle;
    }

    table.logs-table tr.log-row {
      cursor: pointer;
      transition: background-color 0.12s ease;
    }

    table.logs-table tr.log-row:hover {
      background-color: rgba(99, 102, 241, 0.08);
    }

    /* Badges */
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 2px 7px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.02em;
    }

    .badge-info {
      background: rgba(6, 182, 212, 0.15);
      color: #38bdf8;
      border: 1px solid rgba(6, 182, 212, 0.3);
    }

    .badge-warning {
      background: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.3);
    }

    .badge-error {
      background: rgba(239, 68, 68, 0.15);
      color: #f87171;
      border: 1px solid rgba(239, 68, 68, 0.3);
    }

    .badge-debug {
      background: rgba(156, 163, 175, 0.15);
      color: #9ca3af;
      border: 1px solid rgba(156, 163, 175, 0.2);
    }

    .badge-cat {
      background: rgba(99, 102, 241, 0.12);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.25);
    }

    .badge-provider {
      background: rgba(16, 185, 129, 0.12);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.25);
    }

    .mono-cell {
      font-family: var(--font-mono);
      font-size: 12px;
      color: #e5e7eb;
    }

    .time-cell {
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-muted);
      white-space: nowrap;
    }

    .time-cell .rel-time {
      display: block;
      font-size: 11px;
      color: var(--text-subtle);
    }

    .message-cell {
      max-width: 460px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .detail-hint {
      color: var(--text-subtle);
      font-size: 11px;
      margin-left: 6px;
    }

    /* Table Footer & Pagination */
    .table-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-top: 1px solid var(--border-subtle);
      background: rgba(17, 22, 34, 0.8);
      font-size: 12px;
      color: var(--text-muted);
      flex-wrap: wrap;
      gap: 12px;
    }

    .pagination-btns {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* Empty & Loading States */
    .state-container {
      padding: 48px 24px;
      text-align: center;
      color: var(--text-muted);
    }

    .state-container .state-icon {
      font-size: 32px;
      margin-bottom: 8px;
    }

    /* Modal Styles */
    .modal-backdrop {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 999;
      padding: 20px;
      opacity: 0;
    }

    .modal-backdrop.open {
      display: flex !important;
      opacity: 1 !important;
      pointer-events: auto;
      animation: modalFadeIn 0.2s ease-out;
    }

    @keyframes modalFadeIn {
      from {
        opacity: 0;
        transform: scale(0.98);
      }
      to {
        opacity: 1;
        transform: scale(1);
      }
    }

    .modal-dialog {
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      width: 100%;
      max-width: 680px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.8);
      transform: translateY(12px) scale(0.98);
      transition: transform 0.2s ease;
      overflow: hidden;
    }

    .modal-backdrop.open .modal-dialog {
      transform: translateY(0) scale(1);
    }

    .modal-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-surface-elevated);
    }

    .modal-title {
      font-size: 16px;
      font-weight: 700;
      color: #fff;
    }

    .modal-close-btn {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 20px;
      cursor: pointer;
      line-height: 1;
    }

    .modal-close-btn:hover {
      color: #fff;
    }

    .modal-body {
      padding: 20px;
      overflow-y: auto;
      flex: 1;
    }

    /* Detail Grid */
    .detail-grid {
      display: grid;
      grid-template-columns: 120px 1fr;
      gap: 12px;
      font-size: 13px;
      margin-bottom: 16px;
    }

    .detail-label {
      color: var(--text-subtle);
      font-weight: 500;
    }

    .detail-val {
      color: #fff;
      word-break: break-all;
    }

    .code-box {
      background: #090c13;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 12px;
      font-family: var(--font-mono);
      font-size: 12px;
      color: #a5b4fc;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 320px;
      overflow-y: auto;
    }

    /* Semantic Login Form (Autofill-compatible) */
    .login-card {
      width: 100%;
      max-width: 440px;
      background: var(--bg-surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 28px;
      box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.8);
      position: relative;
    }

    .login-card h2 {
      font-size: 20px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 6px;
    }

    .login-card p.sub {
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 24px;
    }

    .form-group {
      margin-bottom: 16px;
    }

    .form-group label {
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 6px;
    }

    .form-group input {
      width: 100%;
      background: #090c13;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      color: #fff;
      font-size: 14px;
      outline: none;
      transition: all 0.15s ease;
    }

    .form-group input:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 2px var(--primary-glow);
    }

    .form-check {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 20px;
      cursor: pointer;
    }

    .form-check input {
      cursor: pointer;
    }

    .btn-submit {
      width: 100%;
      padding: 10px 16px;
      border-radius: var(--radius-sm);
      background: var(--primary);
      border: none;
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
    }

    .btn-submit:hover {
      background: var(--primary-hover);
    }

    .login-error-msg {
      margin-top: 12px;
      padding: 8px 12px;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      border-radius: var(--radius-sm);
      color: #fca5a5;
      font-size: 12px;
      display: none;
    }

    /* Toast Notification */
    #toast-container {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 10000;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .toast {
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 10px 16px;
      color: #fff;
      font-size: 13px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.6);
      display: flex;
      align-items: center;
      gap: 8px;
      animation: slideIn 0.2s ease-out;
    }

    @keyframes slideIn {
      from {
        transform: translateY(12px);
        opacity: 0;
      }
      to {
        transform: translateY(0);
        opacity: 1;
      }
    }
  </style>
</head>
<body>

  <!-- Top Navbar -->
  <header class="navbar">
    <div class="nav-brand">
      <div class="brand-icon">__LOGO_SVG__</div>
      <div class="brand-text">
        <h1>Moyu Telegram Relay</h1>
        <div class="sub">运维监控与 15 天审计日志看板</div>
      </div>
    </div>

    <div class="nav-meta">
      <div class="status-pill" id="telegram-status-pill">
        <span class="status-dot" id="telegram-status-dot"></span>
        <span id="telegram-status-text">检测中...</span>
      </div>

      <div class="status-pill mono-cell" id="account-pill" style="display:none;">
        <span id="account-display">ID: -</span>
      </div>

      <button class="nav-btn" id="btn-refresh" title="立即刷新">
        🔄 刷新
      </button>

      <button class="nav-btn" id="btn-prune" title="手动清理超过 15 天的历史日志">
        🧹 清理过期
      </button>

      <button class="nav-btn" id="btn-logout" title="退出并清除保存的 Token">
        🚪 退出登录
      </button>
    </div>
  </header>

  <!-- Main Content Container -->
  <main class="container">

    <!-- Metrics Cards -->
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-title">
          <span>15 天日志总量</span>
          <span>📅 保留 15 天</span>
        </div>
        <div class="metric-value" id="metric-total-logs">-</div>
        <div class="metric-desc" id="metric-db-size">SQLite WAL 存储库</div>
      </div>

      <div class="metric-card">
        <div class="metric-title">
          <span>今日日志事件 (24h)</span>
          <span>⚡ 实时吞吐</span>
        </div>
        <div class="metric-value" id="metric-logs-24h">-</div>
        <div class="metric-desc" id="metric-level-breakdown">INFO: - · WARN: - · ERR: -</div>
      </div>

      <div class="metric-card">
        <div class="metric-title">
          <span>今日交互请求 (24h)</span>
          <span>🔐 OTP / 确认</span>
        </div>
        <div class="metric-value" id="metric-requests-24h">-</div>
        <div class="metric-desc" id="metric-active-provider">活跃 Provider: hax</div>
      </div>

      <div class="metric-card">
        <div class="metric-title">
          <span>Telegram MTProto</span>
          <span>🌐 网络连接</span>
        </div>
        <div class="metric-value" id="metric-session-mode" style="font-size: 20px;">-</div>
        <div class="metric-desc" id="metric-dc-info">DC 路由与 IP 地址</div>
      </div>
    </div>

    <div class="toolbar-panel" id="telegram-accounts" aria-label="Telegram 账号连接状态" style="display:none; flex-wrap:wrap;"></div>

    <!-- Filter & Toolbar Panel -->
    <div class="toolbar-panel">
      <div class="filter-group">
        <div class="input-wrapper">
          <span class="search-icon">🔍</span>
          <input
            type="search"
            class="search-input"
            id="input-search"
            placeholder="搜索消息正文 / Request ID / Detail..."
          />
        </div>

        <select class="filter-select" id="select-level">
          <option value="ALL">全部级别 (Level: ALL)</option>
          <option value="INFO">INFO (正常日志)</option>
          <option value="WARNING">WARNING (警告/需人工)</option>
          <option value="ERROR">ERROR (异常/错误)</option>
          <option value="DEBUG">DEBUG</option>
        </select>

        <select class="filter-select" id="select-category">
          <option value="all">全部分类 (Category: ALL)</option>
          <option value="telegram">telegram (消息接收/连接)</option>
          <option value="provider">provider (规则评估/点击)</option>
          <option value="otp_request">otp_request (请求生命周期)</option>
          <option value="system">system (系统事件)</option>
          <option value="http">http (接口访问)</option>
        </select>

        <select class="filter-select" id="select-provider">
          <option value="all">全部 Provider</option>
          <option value="hax">Hax Provider</option>
          <option value="generic">Generic Provider</option>
        </select>

        <select class="filter-select" id="select-time-range">
          <option value="all">时间: 15 天全部</option>
          <option value="1h">最近 1 小时</option>
          <option value="6h">最近 6 小时</option>
          <option value="24h">最近 24 小时</option>
          <option value="7d">最近 7 天</option>
        </select>
      </div>

      <div class="action-group">
        <select class="filter-select" id="select-auto-refresh">
          <option value="5000">自动刷新: 5秒</option>
          <option value="10000" selected>自动刷新: 10秒</option>
          <option value="30000">自动刷新: 30秒</option>
          <option value="0">自动刷新: 关闭</option>
        </select>

        <button class="nav-btn" id="btn-export-json" title="导出当前筛选日志为 JSON 文件">
          📥 导出 JSON
        </button>
      </div>
    </div>

    <!-- Logs Table Panel -->
    <div class="table-panel">
      <div class="table-container">
        <table class="logs-table">
          <thead>
            <tr>
              <th style="width: 140px;">时间 (UTC/Local)</th>
              <th style="width: 80px;">级别</th>
              <th style="width: 90px;">分类</th>
              <th style="width: 80px;">Provider</th>
              <th style="width: 130px;">Request ID</th>
              <th>事件消息 / 摘要</th>
            </tr>
          </thead>
          <tbody id="logs-tbody">
            <tr>
              <td colspan="6">
                <div class="state-container">
                  <div class="state-icon">⏳</div>
                  <div>正在加载日志数据...</div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Table Footer & Pagination -->
      <div class="table-footer">
        <div id="pagination-info">显示 0 - 0 / 共 0 条</div>
        <div class="pagination-btns">
          <button class="nav-btn" id="btn-prev-page" disabled>上一页</button>
          <span id="current-page-display" class="mono-cell">第 1 页</span>
          <button class="nav-btn" id="btn-next-page" disabled>下一页</button>
        </div>
      </div>
    </div>
  </main>

  <!-- Login Modal (Full Web-Standard Autofill Support) -->
  <div class="modal-backdrop" id="modal-login" style="display: none;">
    <div class="login-card">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px;">
        <div style="width:44px;height:44px;flex-shrink:0;">__LOGO_SVG__</div>
        <div>
          <h2>Moyu Relay 运维控制台</h2>
          <p class="sub">请输入 Relay Bearer Token 验证访问权限</p>
        </div>
      </div>

      <!-- Standard HTML form structure for password managers (1Password, Bitwarden, Apple Keychain) -->
      <form id="login-form" method="POST" action="javascript:void(0);">
        <div class="form-group">
          <label for="admin-username">账号标识 (Username)</label>
          <input
            type="text"
            id="admin-username"
            name="username"
            autocomplete="username"
            value="relay"
            placeholder="relay"
            required
            disabled
            spellcheck="false"
          />
        </div>

        <div class="form-group">
          <label for="admin-password">Relay Bearer Token (Password)</label>
          <input
            type="password"
            id="admin-password"
            name="password"
            autocomplete="current-password"
            placeholder="输入 OTP_RELAY_BEARER_TOKEN"
            required
            disabled
            spellcheck="false"
          />
        </div>

        <label class="form-check">
          <input type="checkbox" id="remember-token" checked />
          <span>在此浏览器记住凭据 (本地持久存储)</span>
        </label>

        <button type="submit" class="btn-submit" id="btn-login-submit">
          解锁并进入控制台
        </button>

        <div class="login-error-msg" id="login-error-msg"></div>
      </form>
    </div>
  </div>

  <!-- Detail Modal -->
  <div class="modal-backdrop" id="modal-detail" style="display: none;">
    <div class="modal-dialog">
      <div class="modal-header">
        <div class="modal-title">📄 结构化日志详情</div>
        <button class="modal-close-btn" id="btn-close-detail">&times;</button>
      </div>
      <div class="modal-body">
        <div class="detail-grid">
          <div class="detail-label">日志 ID</div>
          <div class="detail-val mono-cell" id="detail-id">-</div>

          <div class="detail-label">记录时间</div>
          <div class="detail-val mono-cell" id="detail-time">-</div>

          <div class="detail-label">级别 / 分类</div>
          <div class="detail-val" id="detail-level-cat">-</div>

          <div class="detail-label">Provider</div>
          <div class="detail-val mono-cell" id="detail-provider">-</div>

          <div class="detail-label">Telegram 账号</div>
          <div class="detail-val mono-cell" id="detail-account">-</div>

          <div class="detail-label">Request ID</div>
          <div class="detail-val mono-cell" id="detail-req-id">-</div>

          <div class="detail-label">事件消息</div>
          <div class="detail-val" id="detail-message" style="font-weight: 600;">-</div>

          <div class="detail-label">补充说明</div>
          <div class="detail-val" id="detail-extra-detail">-</div>
        </div>

        <div style="margin-top: 14px; margin-bottom: 6px; font-weight: 600; color: var(--text-muted); font-size: 12px;">
          上下文扩展数据 (JSON Context / Telegram Raw Text / Buttons):
        </div>
        <pre class="code-box" id="detail-extra-json">{}</pre>

        <div style="margin-top: 14px; display: flex; justify-content: flex-end; gap: 8px;">
          <button class="nav-btn" id="btn-copy-detail">📋 复制完整数据</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Toast Container -->
  <div id="toast-container"></div>

  <!-- Frontend Logic -->
  <script>
    (function () {
      const STORAGE_KEY = "moyu_tg_relay_admin_token";
      let currentToken = "";
      let currentPage = 1;
      let pageSize = 50;
      let totalPages = 1;
      let autoRefreshTimer = null;
      let searchDebounceTimer = null;
      let lastFetchedLogs = [];

      // Elements
      const modalLogin = document.getElementById("modal-login");
      const loginForm = document.getElementById("login-form");
      const inputUsername = document.getElementById("admin-username");
      const inputPassword = document.getElementById("admin-password");
      const checkRemember = document.getElementById("remember-token");
      const loginErrorMsg = document.getElementById("login-error-msg");

      const modalDetail = document.getElementById("modal-detail");
      const btnCloseDetail = document.getElementById("btn-close-detail");
      const btnCopyDetail = document.getElementById("btn-copy-detail");

      const logsTbody = document.getElementById("logs-tbody");
      const inputSearch = document.getElementById("input-search");
      const selectLevel = document.getElementById("select-level");
      const selectCategory = document.getElementById("select-category");
      const selectProvider = document.getElementById("select-provider");
      const selectTimeRange = document.getElementById("select-time-range");
      const selectAutoRefresh = document.getElementById("select-auto-refresh");

      const btnRefresh = document.getElementById("btn-refresh");
      const btnPrune = document.getElementById("btn-prune");
      const btnLogout = document.getElementById("btn-logout");
      const btnExportJson = document.getElementById("btn-export-json");
      const btnPrevPage = document.getElementById("btn-prev-page");
      const btnNextPage = document.getElementById("btn-next-page");
      const paginationInfo = document.getElementById("pagination-info");
      const currentPageDisplay = document.getElementById("current-page-display");

      // Toast helper
      function showToast(message, duration = 2500) {
        const container = document.getElementById("toast-container");
        const toast = document.createElement("div");
        toast.className = "toast";
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => {
          toast.style.opacity = "0";
          toast.style.transition = "opacity 0.3s ease";
          setTimeout(() => toast.remove(), 300);
        }, duration);
      }

      // Time formatting helper
      function formatTime(timestamp) {
        if (!timestamp) return "-";
        const date = new Date(timestamp * 1000);
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, "0");
        const d = String(date.getDate()).padStart(2, "0");
        const hh = String(date.getHours()).padStart(2, "0");
        const mm = String(date.getMinutes()).padStart(2, "0");
        const ss = String(date.getSeconds()).padStart(2, "0");
        return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
      }

      function formatRelativeTime(timestamp) {
        if (!timestamp) return "";
        const diff = Math.floor(Date.now() / 1000 - timestamp);
        if (diff < 5) return "刚刚";
        if (diff < 60) return `${diff} 秒前`;
        if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
        return `${Math.floor(diff / 86400)} 天前`;
      }

      // API call helper
      async function apiFetch(path, options = {}) {
        const headers = options.headers || {};
        if (currentToken) {
          headers["Authorization"] = `Bearer ${currentToken}`;
        }
        options.headers = headers;

        const response = await fetch(path, options);
        if (response.status === 401) {
          showLoginModal("鉴权失效或 Token 错误，请重新登录");
          throw new Error("unauthorized");
        }
        if (!response.ok) {
          const errText = await response.text();
          throw new Error(`HTTP ${response.status}: ${errText}`);
        }
        return response.json();
      }

      // Auth modal control
      function showLoginModal(errorText = "") {
        inputUsername.disabled = false;
        inputPassword.disabled = false;
        modalLogin.style.display = "flex";
        modalLogin.classList.add("open");
        if (errorText) {
          loginErrorMsg.textContent = errorText;
          loginErrorMsg.style.display = "block";
        } else {
          loginErrorMsg.style.display = "none";
        }
        setTimeout(() => inputPassword.focus(), 50);
      }

      function hideLoginModal() {
        modalLogin.classList.remove("open");
        modalLogin.style.display = "none";
        inputUsername.disabled = true;
        inputPassword.disabled = true;
        loginErrorMsg.style.display = "none";
        inputPassword.value = "";
      }

      // Load initial token: URL query parameter > localStorage > prompt
      function initAuth() {
        const urlParams = new URLSearchParams(window.location.search);
        const urlToken = urlParams.get("token");

        if (urlToken) {
          currentToken = urlToken.trim();
          // Clear query parameter from URL to prevent credential leaking in history
          window.history.replaceState(null, "", window.location.pathname);
          verifyAndLoad(currentToken, true);
          return;
        }

        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          currentToken = saved.trim();
          verifyAndLoad(currentToken, false);
          return;
        }

        showLoginModal();
      }

      async function verifyAndLoad(token, remember = true) {
        try {
          const res = await fetch("/api/admin/verify", {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (res.ok) {
            const data = await res.json();
            currentToken = token;
            if (remember) {
              localStorage.setItem(STORAGE_KEY, token);
            }
            hideLoginModal();
            updateTelegramStatus(data);
            showToast("✅ 凭据校验成功");
            fetchStats();
            fetchLogs();
            setupAutoRefresh();
          } else {
            showLoginModal("Token 验证失败，请检查后重新输入");
          }
        } catch (err) {
          showLoginModal("连接验证异常: " + err.message);
        }
      }

      // Handle standard form submit (supports browser autofill)
      loginForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        const token = inputPassword.value.trim();
        if (!token) {
          loginErrorMsg.textContent = "请输入 Relay Bearer Token";
          loginErrorMsg.style.display = "block";
          return;
        }
        await verifyAndLoad(token, checkRemember.checked);
      });

      btnLogout.addEventListener("click", function () {
        localStorage.removeItem(STORAGE_KEY);
        currentToken = "";
        inputPassword.value = "";
        if (autoRefreshTimer) clearInterval(autoRefreshTimer);
        showLoginModal("已退出登录");
      });

      // Update Header Telegram Status
      function updateTelegramStatus(info) {
        const dot = document.getElementById("telegram-status-dot");
        const txt = document.getElementById("telegram-status-text");
        const accPill = document.getElementById("account-pill");
        const accDisplay = document.getElementById("account-display");

        if (info && info.status === "ready") {
          dot.className = "status-dot online";
          txt.textContent = "Telegram 已连接";
        } else {
          dot.className = "status-dot offline";
          txt.textContent = "未就绪 / 离线";
        }

        const entries = (info && info.accounts) || [];
        const panel = document.getElementById("telegram-accounts");
        panel.replaceChildren();
        panel.style.display = entries.length ? "flex" : "none";
        entries.forEach(account => {
          const card = document.createElement("div");
          card.className = "metric-card";
          card.style.flex = "1 1 240px";
          const identity = document.createElement("div");
          identity.className = "mono-cell";
          identity.textContent = `UID: ${account.account_id}${account.username ? " · @" + account.username : ""}`;
          const details = document.createElement("div");
          details.className = "metric-desc";
          details.textContent = `${account.status === "ready" ? "已连接" : "离线"} · ${account.session_mode} · ${account.dc_info || "DC 未知"}`;
          card.append(identity, details);
          panel.appendChild(card);
        });
        if (entries.length > 1) {
          const ready = entries.filter(account => account.status === "ready").length;
          accPill.style.display = "inline-flex";
          accDisplay.textContent = `账号 ${ready}/${entries.length} 在线`;
        } else if (info && info.account_id) {
          accPill.style.display = "inline-flex";
          accDisplay.textContent = `UID: ${info.account_id}`;
        }
      }

      // Fetch Stats
      async function fetchStats() {
        try {
          const stats = await apiFetch("/api/admin/stats");

          document.getElementById("metric-total-logs").textContent = stats.total_logs.toLocaleString();
          document.getElementById("metric-logs-24h").textContent = stats.logs_24h.toLocaleString();
          document.getElementById("metric-requests-24h").textContent = stats.requests_24h.toLocaleString();

          // Size
          const kb = (stats.db_size_bytes / 1024).toFixed(1);
          document.getElementById("metric-db-size").textContent = `数据库占用: ${kb} KB · 保留 ${stats.retention_days} 天`;

          // Level breakdown
          const lvls = stats.level_counts || {};
          document.getElementById("metric-level-breakdown").textContent =
            `INFO: ${lvls.INFO || 0} · WARN: ${lvls.WARNING || 0} · ERR: ${lvls.ERROR || 0}`;

          // Session mode & DC
          const sMode = stats.session_mode || "file";
          const dcIp = stats.dc_info || "-";
          document.getElementById("metric-session-mode").textContent = `Session: ${sMode}`;
          document.getElementById("metric-dc-info").textContent = `DC 路由: ${dcIp}`;

          const entries = stats.accounts || [];
          updateTelegramStatus({...stats.telegram, accounts: entries});
          if (entries.length > 1) {
            document.getElementById("metric-session-mode").textContent = `${stats.ready_count}/${entries.length} 个账号在线`;
            document.getElementById("metric-dc-info").textContent = "各账号 Session 与连接独立管理";
          }
        } catch (err) {
          console.error("fetchStats error:", err);
        }
      }

      // Fetch Logs
      async function fetchLogs() {
        try {
          const params = new URLSearchParams({
            page: currentPage,
            page_size: pageSize,
          });

          const level = selectLevel.value;
          if (level && level !== "ALL") params.append("level", level);

          const category = selectCategory.value;
          if (category && category !== "all") params.append("category", category);

          const provider = selectProvider.value;
          if (provider && provider !== "all") params.append("provider", provider);

          const search = inputSearch.value.trim();
          if (search) params.append("search", search);

          // Time range calculation
          const range = selectTimeRange.value;
          if (range !== "all") {
            const now = Math.floor(Date.now() / 1000);
            let seconds = 3600;
            if (range === "6h") seconds = 6 * 3600;
            else if (range === "24h") seconds = 24 * 3600;
            else if (range === "7d") seconds = 7 * 86400;
            params.append("since", now - seconds);
          }

          const res = await apiFetch(`/api/admin/logs?${params.toString()}`);
          renderLogs(res);
        } catch (err) {
          console.error("fetchLogs error:", err);
        }
      }

      // Render table rows
      function renderLogs(data) {
        lastFetchedLogs = data.logs || [];
        totalPages = data.total_pages || 1;
        currentPage = data.page || 1;

        paginationInfo.textContent = `显示第 ${data.logs.length ? (currentPage - 1) * pageSize + 1 : 0} - ${
          (currentPage - 1) * pageSize + data.logs.length
        } 条 / 共 ${data.total} 条`;
        currentPageDisplay.textContent = `第 ${currentPage} / ${totalPages} 页`;
        btnPrevPage.disabled = currentPage <= 1;
        btnNextPage.disabled = currentPage >= totalPages;

        if (!data.logs || !data.logs.length) {
          logsTbody.innerHTML = `
            <tr>
              <td colspan="6">
                <div class="state-container">
                  <div class="state-icon">📭</div>
                  <div>未查询到匹配的日志记录</div>
                </div>
              </td>
            </tr>
          `;
          return;
        }

        let html = "";
        for (const item of data.logs) {
          const lvlClass =
            item.level === "ERROR"
              ? "badge-error"
              : item.level === "WARNING"
              ? "badge-warning"
              : item.level === "DEBUG"
              ? "badge-debug"
              : "badge-info";

          const providerBadge = item.provider
            ? `<span class="badge badge-provider">${item.provider}</span>`
            : `<span style="color:var(--text-subtle);">-</span>`;

          const reqShort = item.request_id ? item.request_id.substring(0, 10) + "…" : "-";

          html += `
            <tr class="log-row" data-id="${item.id}">
              <td class="time-cell">
                <div>${formatTime(item.timestamp)}</div>
                <div class="rel-time">${formatRelativeTime(item.timestamp)}</div>
              </td>
              <td><span class="badge ${lvlClass}">${item.level}</span></td>
              <td><span class="badge badge-cat">${item.category}</span></td>
              <td>${providerBadge}</td>
              <td class="mono-cell" title="${item.request_id || ""}">${reqShort}</td>
              <td class="message-cell">
                <span>${escapeHtml(item.message)}</span>
                ${item.detail ? `<span class="detail-hint">${escapeHtml(item.detail)}</span>` : ""}
              </td>
            </tr>
          `;
        }
        logsTbody.innerHTML = html;

        // Bind click events on rows to open detail drawer
        const rows = logsTbody.querySelectorAll("tr.log-row");
        rows.forEach((row) => {
          row.addEventListener("click", () => {
            const id = parseInt(row.getAttribute("data-id"), 10);
            const item = lastFetchedLogs.find((l) => l.id === id);
            if (item) openDetailModal(item);
          });
        });
      }

      function escapeHtml(str) {
        if (!str) return "";
        return String(str)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#039;");
      }

      // Open detail modal
      let currentDetailItem = null;
      function openDetailModal(item) {
        currentDetailItem = item;
        document.getElementById("detail-id").textContent = `#${item.id}`;
        document.getElementById("detail-time").textContent = `${formatTime(item.timestamp)} (${item.created_at})`;
        document.getElementById("detail-level-cat").innerHTML = `
          <span class="badge badge-${item.level.toLowerCase()}">${item.level}</span>
          <span class="badge badge-cat" style="margin-left:4px;">${item.category}</span>
        `;
        document.getElementById("detail-provider").textContent = item.provider || "无 (None)";
        document.getElementById("detail-account").textContent = item.account || "无 (None)";
        document.getElementById("detail-req-id").textContent = item.request_id || "无 (None)";
        document.getElementById("detail-message").textContent = item.message;
        document.getElementById("detail-extra-detail").textContent = item.detail || "-";

        const extraJsonElem = document.getElementById("detail-extra-json");
        try {
          extraJsonElem.textContent = JSON.stringify(item.extra || {}, null, 2);
        } catch (e) {
          extraJsonElem.textContent = String(item.extra);
        }

        modalDetail.style.display = "flex";
        modalDetail.classList.add("open");
      }

      function closeDetailModal() {
        modalDetail.classList.remove("open");
        modalDetail.style.display = "none";
      }

      btnCloseDetail.addEventListener("click", closeDetailModal);
      modalDetail.addEventListener("click", (e) => {
        if (e.target === modalDetail) closeDetailModal();
      });

      btnCopyDetail.addEventListener("click", () => {
        if (!currentDetailItem) return;
        navigator.clipboard.writeText(JSON.stringify(currentDetailItem, null, 2)).then(() => {
          showToast("📋 已成功复制结构化日志至剪贴板");
        });
      });

      // Pagination events
      btnPrevPage.addEventListener("click", () => {
        if (currentPage > 1) {
          currentPage--;
          fetchLogs();
        }
      });

      btnNextPage.addEventListener("click", () => {
        if (currentPage < totalPages) {
          currentPage++;
          fetchLogs();
        }
      });

      // Search & Filters
      function triggerFilterChange() {
        currentPage = 1;
        fetchLogs();
      }

      inputSearch.addEventListener("input", () => {
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(triggerFilterChange, 350);
      });

      selectLevel.addEventListener("change", triggerFilterChange);
      selectCategory.addEventListener("change", triggerFilterChange);
      selectProvider.addEventListener("change", triggerFilterChange);
      selectTimeRange.addEventListener("change", triggerFilterChange);

      btnRefresh.addEventListener("click", () => {
        fetchStats();
        fetchLogs();
        showToast("🔄 数据已更新");
      });

      // Prune Action
      btnPrune.addEventListener("click", async () => {
        if (!confirm("确定执行过期日志清理吗？将彻底清除超过 15 天的历史日志。")) return;
        try {
          const res = await apiFetch("/api/admin/logs/prune", { method: "POST" });
          showToast(`🧹 清理完成: 已清除 ${res.deleted} 条过期日志`);
          fetchStats();
          fetchLogs();
        } catch (err) {
          alert("清理失败: " + err.message);
        }
      });

      // Export JSON
      btnExportJson.addEventListener("click", async () => {
        try {
          const params = new URLSearchParams({ page: 1, page_size: 500 });
          const search = inputSearch.value.trim();
          if (search) params.append("search", search);
          if (selectLevel.value !== "ALL") params.append("level", selectLevel.value);
          if (selectCategory.value !== "all") params.append("category", selectCategory.value);

          const res = await apiFetch(`/api/admin/logs?${params.toString()}`);
          const blob = new Blob([JSON.stringify(res.logs || [], null, 2)], {
            type: "application/json",
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `relay_logs_${new Date().toISOString().slice(0, 10)}.json`;
          a.click();
          URL.revokeObjectURL(url);
          showToast("📥 导出完成");
        } catch (err) {
          alert("导出失败: " + err.message);
        }
      });

      // Auto-refresh control
      function setupAutoRefresh() {
        if (autoRefreshTimer) clearInterval(autoRefreshTimer);
        const interval = parseInt(selectAutoRefresh.value, 10);
        if (interval > 0) {
          autoRefreshTimer = setInterval(() => {
            fetchStats();
            fetchLogs();
          }, interval);
        }
      }

      selectAutoRefresh.addEventListener("change", setupAutoRefresh);

      // Start initialization
      initAuth();
    })();
  </script>
</body>
</html>
"""
    return html.replace("__FAVICON_DATA_URI__", TG_RELAY_FAVICON_DATA_URI).replace("__LOGO_SVG__", TG_RELAY_LOGO_SVG)
