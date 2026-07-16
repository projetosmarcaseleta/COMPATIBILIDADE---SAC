import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

import time
import threading
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, redirect, url_for, jsonify
from curl_cffi import requests as cffi_requests
import fiat_parts_tool

app = Flask(__name__)

FIATPECAS_IMPERSONATES = ["chrome124", "safari17_0", "chrome120", "edge101"]
FIATPECAS_CACHE_TTL = 300
_fiatpecas_winning_profile = None
_fiatpecas_cache: dict[str, tuple[float, list]] = {}
_fiatpecas_cache_lock = threading.Lock()

# ── Auth Status Tracking ────────────────────────────────────────────────────────
# Tracks background Selenium authentication so the UI can poll progress
# without blocking the request thread.
_auth_bg_status: dict = {
    "state": "idle",       # idle | loading | success | error
    "started_at": 0.0,
    "completed_at": 0.0,
    "error_msg": None,
}
_auth_bg_lock = threading.Lock()


def _run_auth(force: bool = False):
    """Execute Selenium authentication and update _auth_bg_status. Run in a daemon thread."""
    global _auth_bg_status
    # If cookies are already valid and we're not forcing, just mark success
    if not force and fiat_parts_tool.has_valid_cookies():
        with _auth_bg_lock:
            _auth_bg_status["state"] = "success"
            _auth_bg_status["completed_at"] = time.time()
        return
    # Prevent concurrent logins
    with _auth_bg_lock:
        if _auth_bg_status["state"] == "loading":
            return
        _auth_bg_status["state"] = "loading"
        _auth_bg_status["started_at"] = time.time()
        _auth_bg_status["error_msg"] = None
    try:
        fiat_parts_tool.get_cookies(force_login=force, headless=True)
        with _auth_bg_lock:
            _auth_bg_status["state"] = "success"
            _auth_bg_status["completed_at"] = time.time()
        print("[AUTH] Autenticação concluída com sucesso.")
    except Exception as e:
        with _auth_bg_lock:
            _auth_bg_status["state"] = "error"
            _auth_bg_status["completed_at"] = time.time()
            _auth_bg_status["error_msg"] = str(e)[:250]
        print(f"[AUTH] Falha na autenticação em background: {e}")

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login — Consulta ePER</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
    <style>
        /* ── Theme Variables (Dark - default) ──────────────── */
        :root {
            --bg-body: #0f1117;
            --bg-surface: rgba(255,255,255,0.04);
            --bg-surface-hover: rgba(255,255,255,0.06);
            --border-subtle: rgba(255,255,255,0.08);
            --text-primary: #e2e8f0;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent: #3b82f6;
            --accent-secondary: #6366f1;
            --success-bg: rgba(16,185,129,0.12);
            --success-text: #34d399;
            --danger-bg: rgba(239,68,68,0.12);
            --danger-text: #f87171;
            --status-idle-bg: rgba(100,116,139,0.12);
            --status-idle-text: #94a3b8;
        }

        /* ── Light Theme ──────────────────────────────────── */
        [data-theme="light"] {
            --bg-body: #f5f7fa;
            --bg-surface: rgba(255,255,255,0.85);
            --bg-surface-hover: rgba(255,255,255,0.95);
            --border-subtle: rgba(0,0,0,0.1);
            --text-primary: #1e293b;
            --text-secondary: #475569;
            --text-muted: #64748b;
            --accent: #2563eb;
            --accent-secondary: #4f46e5;
            --success-bg: rgba(5,150,105,0.1);
            --success-text: #059669;
            --danger-bg: rgba(220,38,38,0.08);
            --danger-text: #dc2626;
            --status-idle-bg: rgba(100,116,139,0.1);
            --status-idle-text: #475569;
        }

        *, *::before, *::after { box-sizing: border-box; }
        body {
            margin: 0; padding: 0;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background: var(--bg-body);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            color: var(--text-primary);
            transition: background 0.3s, color 0.3s;
        }

        /* Animated background shapes */
        body::before {
            content: '';
            position: fixed; top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: radial-gradient(ellipse at 20% 50%, rgba(59,130,246,0.06) 0%, transparent 50%),
                        radial-gradient(ellipse at 80% 20%, rgba(99,102,241,0.05) 0%, transparent 50%),
                        radial-gradient(ellipse at 50% 80%, rgba(16,185,129,0.04) 0%, transparent 50%);
            animation: bgShift 20s ease-in-out infinite alternate;
            z-index: 0;
            pointer-events: none;
        }
        [data-theme="light"] body::before {
            background: radial-gradient(ellipse at 20% 50%, rgba(37,99,235,0.04) 0%, transparent 50%),
                        radial-gradient(ellipse at 80% 20%, rgba(79,70,229,0.03) 0%, transparent 50%);
        }
        @keyframes bgShift {
            0% { transform: translate(0, 0) rotate(0deg); }
            100% { transform: translate(2%, -2%) rotate(3deg); }
        }

        /* ── Theme Toggle ─────────────────────────────────── */
        .theme-toggle {
            position: fixed;
            top: 16px;
            right: 20px;
            z-index: 200;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: 1px solid var(--border-subtle);
            background: var(--bg-surface);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            color: var(--text-secondary);
            font-size: 1.1rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.25s;
            box-shadow: 0 2px 12px rgba(0,0,0,0.15);
        }
        .theme-toggle:hover {
            background: var(--bg-surface-hover);
            transform: scale(1.1);
            color: var(--text-primary);
        }

        /* Main content */
        .login-wrapper {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 40px 20px;
            position: relative;
            z-index: 1;
        }

        /* Glass card */
        .login-card {
            background: var(--bg-surface);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid var(--border-subtle);
            border-radius: 16px;
            padding: 44px 40px 36px;
            max-width: 460px;
            width: 100%;
            box-shadow: 0 8px 32px rgba(0,0,0,0.15);
            animation: cardIn 0.5s ease-out;
            transition: background 0.3s, border-color 0.3s;
        }
        @keyframes cardIn {
            from { opacity: 0; transform: translateY(20px) scale(0.97); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        .login-card h4 {
            font-size: 1.35rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 4px;
        }
        .login-card .subtitle {
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 28px;
        }

        /* Status area */
        #status-area { min-height: 52px; margin-bottom: 20px; }
        .status-badge {
            display: flex; align-items: center; gap: 10px;
            padding: 12px 16px;
            border-radius: 10px;
            font-size: 0.84rem;
            font-weight: 500;
            animation: statusIn 0.3s ease-out;
        }
        @keyframes statusIn {
            from { opacity: 0; transform: translateY(-6px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .status-badge i { font-size: 1.1rem; flex-shrink: 0; }
        .status-badge.status-idle    { background: var(--status-idle-bg); color: var(--status-idle-text); border: 1px solid var(--border-subtle); }
        .status-badge.status-loading { background: var(--success-bg); color: var(--accent); border: 1px solid var(--border-subtle); }
        .status-badge.status-success { background: var(--success-bg); color: var(--success-text); border: 1px solid var(--border-subtle); }
        .status-badge.status-error   { background: var(--danger-bg); color: var(--danger-text); border: 1px solid var(--border-subtle); }

        .status-badge.status-loading i { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

        /* Button */
        .btn-iniciar {
            width: 100%;
            padding: 14px 24px;
            font-size: 0.95rem;
            font-weight: 700;
            font-family: 'Inter', sans-serif;
            color: white;
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            border: none;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.25s ease;
            box-shadow: 0 4px 16px rgba(59,130,246,0.15);
            position: relative;
            overflow: hidden;
        }
        .btn-iniciar::before {
            content: '';
            position: absolute; inset: 0;
            background: linear-gradient(135deg, rgba(255,255,255,0.12), transparent);
            opacity: 0;
            transition: opacity 0.25s;
        }
        .btn-iniciar:hover:not(:disabled)::before { opacity: 1; }
        .btn-iniciar:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(59,130,246,0.25);
        }
        .btn-iniciar:active:not(:disabled) {
            transform: translateY(0);
            box-shadow: 0 2px 8px rgba(59,130,246,0.1);
        }
        .btn-iniciar:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            box-shadow: none;
        }
        .btn-iniciar .spinner-border {
            width: 16px; height: 16px;
            border-width: 2px;
        }

        /* Direct link */
        .direct-link {
            display: block;
            text-align: center;
            margin-top: 20px;
            font-size: 0.84rem;
            color: var(--text-muted);
            text-decoration: none;
            transition: color 0.2s;
        }
        .direct-link:hover { color: var(--accent); }
        .direct-link i { transition: transform 0.2s; }
        .direct-link:hover i { transform: translateX(3px); }

        @media (max-width: 520px) {
            .login-card { padding: 32px 24px 28px; }
            .theme-toggle { top: 10px; right: 12px; width: 36px; height: 36px; font-size: 1rem; }
        }
    </style>
</head>
<body>
    <!-- Theme Toggle -->
    <button id="theme-toggle-btn" class="theme-toggle" onclick="toggleTheme()" title="Alternar tema claro/escuro">
        <i class="bi bi-sun-fill"></i>
    </button>

    <div class="login-wrapper">
        <div class="login-card">
            <h4>Consulta de Compatibilidade</h4>
            <p class="subtitle">Sistema de Consulta ePER — Peças Fiat</p>

            <div id="status-area">
                <div class="status-badge status-idle">
                    <i class="bi bi-hourglass-split"></i>
                    <span>Verificando status da sessão...</span>
                </div>
            </div>

            <button id="btn-start" class="btn-iniciar" disabled>
                <span class="spinner-border spinner-border-sm"></span> Verificando...
            </button>

            <a href="/compatibilidade/" class="direct-link">
                Ir direto para a busca <i class="bi bi-arrow-right"></i>
            </a>
        </div>
    </div>

    <script>
    var _polling = false;

    function setStatus(state, msg) {
        var cfg = {
            success: {cls:'status-success', icon:'bi-check-circle-fill'},
            loading: {cls:'status-loading', icon:'bi-arrow-repeat'},
            error:   {cls:'status-error',   icon:'bi-exclamation-triangle-fill'},
            idle:    {cls:'status-idle',     icon:'bi-info-circle'}
        }[state] || {cls:'status-idle', icon:'bi-info-circle'};
        document.getElementById('status-area').innerHTML =
            '<div class="status-badge ' + cfg.cls + '">' +
            '<i class="bi ' + cfg.icon + '"></i><span>' + msg + '</span></div>';
    }

    function setBtnReady(label, action) {
        var btn = document.getElementById('btn-start');
        btn.disabled = false;
        btn.innerHTML = label;
        btn.onclick = action;
    }

    function startAuth() {
        var btn = document.getElementById('btn-start');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Conectando ao portal Fiat...';
        setStatus('loading', 'Iniciando autenticação com o portal Fiat. Redirecionando para a busca...');
        fetch('/compatibilidade/api/auth/start', {method:'POST'})
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.state === 'success') {
                    setStatus('success', 'Sessão ativa! Redirecionando...');
                } else {
                    setStatus('loading', 'Autenticação iniciada em segundo plano. Você já pode usar a busca.');
                }
                setTimeout(function() { window.location.href = '/compatibilidade/'; }, 900);
            })
            .catch(function() {
                setTimeout(function() { window.location.href = '/compatibilidade/'; }, 1200);
            });
    }

    function pollUntilReady() {
        if (_polling) return;
        _polling = true;
        (function tick() {
            setTimeout(function() {
                fetch('/compatibilidade/api/auth/status')
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.state === 'success') {
                            _polling = false;
                            setStatus('success', 'Autenticação concluída! Redirecionando...');
                            setTimeout(function() { window.location.href = '/compatibilidade/'; }, 800);
                        } else if (data.state === 'error') {
                            _polling = false;
                            setStatus('error', 'Falha: ' + (data.error_msg || 'Erro desconhecido'));
                            setBtnReady('<i class="bi bi-arrow-clockwise me-2"></i> Tentar Novamente', startAuth);
                        } else {
                            tick();
                        }
                    })
                    .catch(tick);
            }, 3000);
        })();
    }

    fetch('/compatibilidade/api/auth/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.state === 'success') {
                setStatus('success', 'Sessão ativa. Você já pode usar a busca.');
                setBtnReady('<i class="bi bi-arrow-right me-2"></i> Ir para a Busca', function() { window.location.href = '/compatibilidade/'; });
            } else if (data.state === 'loading') {
                setStatus('loading', 'Autenticação em andamento em segundo plano...');
                var btn = document.getElementById('btn-start');
                btn.disabled = true;
                btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Aguardando autenticação...';
                pollUntilReady();
            } else {
                setStatus('idle', 'Clique no botão abaixo para autenticar e acessar o sistema.');
                setBtnReady('<i class="bi bi-box-arrow-in-right me-2"></i> Iniciar Sessão', startAuth);
            }
        })
        .catch(function() {
            setStatus('idle', 'Clique em "Iniciar Sessão" para começar.');
            setBtnReady('<i class="bi bi-box-arrow-in-right me-2"></i> Iniciar Sessão', startAuth);
        });

    function toggleTheme() {
        var html = document.documentElement;
        var current = html.getAttribute('data-theme') || 'dark';
        var next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('eper-theme', next);
        updateThemeIcon(next);
    }
    function updateThemeIcon(theme) {
        var btn = document.getElementById('theme-toggle-btn');
        if (btn) btn.innerHTML = theme === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
    }
    (function() {
        var saved = localStorage.getItem('eper-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        document.addEventListener('DOMContentLoaded', function() { updateThemeIcon(saved); });
    })();
    </script>
</body>
</html>
"""

LOGIN_TEMPLATE_COMPILED = app.jinja_env.from_string(LOGIN_TEMPLATE)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Consulta Catálogo ePER</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
    <style>
        /* ── Theme Variables (Dark - default) ──────────────── */
        :root {
            --bg-body: #0f1117;
            --bg-surface: rgba(255,255,255,0.04);
            --bg-surface-hover: rgba(255,255,255,0.06);
            --bg-elevated: rgba(255,255,255,0.03);
            --bg-input: rgba(255,255,255,0.04);
            --border-subtle: rgba(255,255,255,0.08);
            --border-muted: rgba(255,255,255,0.05);
            --text-primary: #e2e8f0;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --text-dimmed: #475569;
            --text-faint: #334155;
            --accent: #3b82f6;
            --accent-secondary: #6366f1;
            --success: #10b981;
            --success-text: #34d399;
            --success-bg: rgba(16,185,129,0.12);
            --danger: #ef4444;
            --danger-text: #f87171;
            --danger-bg: rgba(239,68,68,0.12);
            --table-header-bg: rgba(30,33,48,0.95);
            --table-header-text: #93c5fd;
            --table-row-alt: rgba(255,255,255,0.015);
            --table-row-hover: rgba(59,130,246,0.06);
            --table-border: rgba(255,255,255,0.04);
            --card-hover-shadow: 0 12px 32px rgba(0,0,0,0.3);
            --panel-header-bg: linear-gradient(135deg, rgba(59,130,246,0.15), rgba(99,102,241,0.1));
            --stat-total-bg: rgba(148,163,184,0.12);
            --stat-total-text: #94a3b8;
            --banner-bg: rgba(30,58,138,0.9);
            --banner-border: rgba(59,130,246,0.2);
            --banner-text: #93c5fd;
            --toast-bg: rgba(16,185,129,0.15);
            --toast-border: rgba(16,185,129,0.3);
            --footer-border: rgba(255,255,255,0.04);
        }

        /* ── Light Theme ──────────────────────────────────── */
        [data-theme="light"] {
            --bg-body: #f5f7fa;
            --bg-surface: rgba(255,255,255,0.85);
            --bg-surface-hover: rgba(255,255,255,0.95);
            --bg-elevated: rgba(255,255,255,0.7);
            --bg-input: rgba(255,255,255,0.9);
            --border-subtle: rgba(0,0,0,0.1);
            --border-muted: rgba(0,0,0,0.06);
            --text-primary: #1e293b;
            --text-secondary: #475569;
            --text-muted: #64748b;
            --text-dimmed: #94a3b8;
            --text-faint: #cbd5e1;
            --accent: #2563eb;
            --accent-secondary: #4f46e5;
            --success: #059669;
            --success-text: #059669;
            --success-bg: rgba(5,150,105,0.1);
            --danger: #dc2626;
            --danger-text: #dc2626;
            --danger-bg: rgba(220,38,38,0.08);
            --table-header-bg: #f1f5f9;
            --table-header-text: #2563eb;
            --table-row-alt: rgba(0,0,0,0.02);
            --table-row-hover: rgba(37,99,235,0.04);
            --table-border: rgba(0,0,0,0.06);
            --card-hover-shadow: 0 12px 32px rgba(0,0,0,0.08);
            --panel-header-bg: linear-gradient(135deg, rgba(37,99,235,0.08), rgba(79,70,229,0.05));
            --stat-total-bg: rgba(100,116,139,0.1);
            --stat-total-text: #475569;
            --banner-bg: rgba(239,246,255,0.95);
            --banner-border: rgba(37,99,235,0.15);
            --banner-text: #1e40af;
            --toast-bg: rgba(5,150,105,0.1);
            --toast-border: rgba(5,150,105,0.2);
            --footer-border: rgba(0,0,0,0.06);
        }
        [data-theme="light"] .compat-brand { background: linear-gradient(135deg, #2563eb, #4f46e5); }
        [data-theme="light"] .summary-title { background: linear-gradient(135deg, #2563eb, #4f46e5); -webkit-background-clip: text; background-clip: text; }
        [data-theme="light"] .product-card-price-pix { background: linear-gradient(135deg, #059669, #10b981); -webkit-background-clip: text; background-clip: text; }
        [data-theme="light"] .status-dot.found { background: #059669; box-shadow: 0 0 6px rgba(5,150,105,0.3); }
        [data-theme="light"] .status-dot.not-found { background: #dc2626; box-shadow: 0 0 6px rgba(220,38,38,0.3); }
        [data-theme="light"] .found-row { border-left-color: #059669; }
        [data-theme="light"] .not-found-row { border-left-color: #dc2626; }
        [data-theme="light"] .compat-card { border-left-color: #059669; }
        [data-theme="light"] .progress-fill { background: linear-gradient(90deg, #059669, #10b981); }
        [data-theme="light"] .btn-search-main,
        [data-theme="light"] .btn-link-product,
        [data-theme="light"] .btn-search-icon,
        [data-theme="light"] .banner-link { background: linear-gradient(135deg, #2563eb, #4f46e5); }
        [data-theme="light"] .search-tab.active { color: #2563eb; }
        [data-theme="light"] .toggle-btn.active { background: rgba(5,150,105,0.1); color: #059669; border-color: rgba(5,150,105,0.2); }

        /* ── Reset & Base ─────────────────────────────────── */
        *, *::before, *::after { box-sizing: border-box; margin: 0; }
        html { scroll-behavior: smooth; }
        body {
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            background: var(--bg-body);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.5;
            transition: background 0.3s, color 0.3s;
        }

        /* ── Theme Toggle ─────────────────────────────────── */
        .theme-toggle {
            position: fixed;
            top: 16px;
            right: 20px;
            z-index: 200;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: 1px solid var(--border-subtle);
            background: var(--bg-surface);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            color: var(--text-secondary);
            font-size: 1.1rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.25s;
            box-shadow: 0 2px 12px rgba(0,0,0,0.15);
        }
        .theme-toggle:hover {
            background: var(--bg-surface-hover);
            transform: scale(1.1);
            color: var(--text-primary);
        }

        /* ── Search Container ─────────────────────────────── */
        .search-section {
            max-width: 960px;
            margin: 24px auto;
            padding: 0 20px;
        }

        /* Tabs */
        .search-tabs {
            display: flex;
            gap: 4px;
            margin-bottom: 0;
        }
        .search-tab {
            padding: 10px 20px;
            font-size: 0.82rem;
            font-weight: 600;
            font-family: 'Inter', sans-serif;
            color: var(--text-muted);
            background: var(--bg-elevated);
            border: 1px solid var(--border-subtle);
            border-bottom: none;
            border-radius: 10px 10px 0 0;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .search-tab:hover { color: var(--text-primary); background: var(--bg-surface-hover); }
        .search-tab.active {
            color: var(--accent);
            background: var(--bg-surface);
            border-color: var(--border-subtle);
        }

        /* Search panels */
        .search-panel-wrap {
            background: var(--bg-surface);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border-subtle);
            border-radius: 0 12px 12px 12px;
            padding: 28px;
            animation: panelIn 0.3s ease-out;
            transition: background 0.3s, border-color 0.3s;
        }
        @keyframes panelIn {
            from { opacity: 0; transform: translateY(8px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .search-panel { display: none; }
        .search-panel.active { display: block; }

        /* Form elements */
        .form-label-custom {
            font-size: 0.72rem;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 6px;
            display: block;
        }
        .form-input, .form-textarea {
            width: 100%;
            background: var(--bg-input);
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            color: var(--text-primary);
            padding: 10px 14px;
            font-size: 0.9rem;
            font-family: 'Inter', sans-serif;
            transition: border-color 0.2s, box-shadow 0.2s;
            outline: none;
        }
        .form-textarea {
            font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
            resize: vertical;
            min-height: 160px;
            line-height: 1.6;
        }
        .form-input:focus, .form-textarea:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(59,130,246,0.12);
        }
        .form-input::placeholder, .form-textarea::placeholder {
            color: var(--text-dimmed);
        }
        .form-hint {
            font-size: 0.72rem;
            color: var(--text-muted);
            margin-top: 6px;
        }

        /* Grid layout for search form */
        .search-grid {
            display: grid;
            grid-template-columns: 1.8fr 1fr;
            gap: 20px;
        }
        @media (max-width: 700px) {
            .search-grid { grid-template-columns: 1fr; }
        }

        /* Search button */
        .btn-search-main {
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            color: white;
            border: none;
            border-radius: 10px;
            padding: 12px 28px;
            font-size: 0.88rem;
            font-weight: 700;
            font-family: 'Inter', sans-serif;
            cursor: pointer;
            transition: all 0.25s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 16px rgba(59,130,246,0.2);
        }
        .btn-search-main:hover {
            transform: translateY(-2px);
            filter: brightness(1.1);
        }
        .btn-search-main:active {
            transform: translateY(0);
        }

        /* Name search bar */
        .name-search-bar {
            display: flex;
            gap: 0;
        }
        .name-search-bar .form-input {
            border-radius: 8px 0 0 8px;
            flex: 1;
        }
        .name-search-bar .btn-search-icon {
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            color: white;
            border: none;
            border-radius: 0 8px 8px 0;
            padding: 10px 20px;
            cursor: pointer;
            font-size: 1rem;
            transition: all 0.2s;
        }
        .name-search-bar .btn-search-icon:hover {
            filter: brightness(1.1);
        }

        /* ── Alerts ───────────────────────────────────────── */
        .alert-modern {
            padding: 14px 18px;
            border-radius: 10px;
            font-size: 0.85rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 10px;
            animation: alertIn 0.3s ease-out;
            max-width: 960px;
            margin: 0 auto 16px;
        }
        @keyframes alertIn {
            from { opacity: 0; transform: translateY(-8px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .alert-success-modern {
            background: var(--success-bg);
            border: 1px solid var(--border-subtle);
            color: var(--success-text);
        }
        .alert-danger-modern {
            background: var(--danger-bg);
            border: 1px solid var(--border-subtle);
            color: var(--danger-text);
        }

        /* ── Results Panel ────────────────────────────────── */
        .results-section {
            max-width: 1320px;
            margin: 0 auto 32px;
            padding: 0 20px;
        }
        .results-panel {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 14px;
            transition: background 0.3s, border-color 0.3s;
            overflow: hidden;
            animation: panelIn 0.4s ease-out;
        }

        /* Panel header */
        .panel-header {
            background: var(--panel-header-bg);
            padding: 14px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-muted);
        }
        .panel-header-title {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--table-header-text);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .btn-copy-report {
            background: var(--bg-surface-hover);
            color: var(--text-secondary);
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 6px 14px;
            font-size: 0.78rem;
            font-weight: 600;
            font-family: 'Inter', sans-serif;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .btn-copy-report:hover {
            background: var(--bg-surface-hover);
            color: var(--text-primary);
        }
        .btn-copy-report.copied {
            background: var(--success-bg);
            color: var(--success-text);
            border-color: var(--border-subtle);
        }

        /* Summary strip */
        .summary-strip {
            padding: 14px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
            border-bottom: 1px solid var(--border-muted);
        }
        .summary-title {
            font-weight: 800;
            font-size: 0.95rem;
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .stat-pill {
            font-size: 0.76rem;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 20px;
            white-space: nowrap;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }
        .stat-pill.total     { background: var(--stat-total-bg); color: var(--stat-total-text); }
        .stat-pill.found     { background: var(--success-bg); color: var(--success-text); }
        .stat-pill.not-found { background: var(--danger-bg); color: var(--danger-text); }
        .summary-stats {
            display: flex;
            gap: 8px;
            margin-left: auto;
            flex-wrap: wrap;
        }

        /* Progress bar */
        .progress-wrap {
            height: 3px;
            background: var(--border-muted);
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--success), var(--success-text));
            transition: width 1s ease-out;
        }

        /* Filter bar */
        .filter-bar {
            padding: 12px 20px;
            background: var(--bg-elevated);
            border-bottom: 1px solid var(--border-muted);
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .filter-input {
            background: var(--bg-input);
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            color: var(--text-primary);
            padding: 7px 12px 7px 32px;
            font-size: 0.82rem;
            font-family: 'Inter', sans-serif;
            flex: 1;
            min-width: 200px;
            max-width: 360px;
            outline: none;
            transition: border-color 0.2s;
        }
        .filter-input:focus { border-color: var(--accent); }
        .filter-input::placeholder { color: var(--text-dimmed); }
        .filter-icon-wrap {
            position: relative;
        }
        .filter-icon-wrap i {
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 0.82rem;
            pointer-events: none;
        }
        .toggle-btn {
            font-size: 0.78rem;
            font-weight: 600;
            font-family: 'Inter', sans-serif;
            padding: 6px 14px;
            border: 1px solid var(--border-subtle);
            background: var(--bg-surface);
            color: var(--text-secondary);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .toggle-btn:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
        .toggle-btn.active {
            background: var(--success-bg);
            color: var(--success-text);
            border-color: var(--border-subtle);
        }
        .filter-count {
            font-size: 0.72rem;
            color: var(--text-dimmed);
            margin-left: auto;
        }

        /* ── Table ────────────────────────────────────────── */
        .table-scroll-wrap {
            overflow-x: auto;
            max-height: 600px;
            overflow-y: auto;
        }
        .compat-table {
            width: 100%;
            font-size: 0.84rem;
            border-collapse: collapse;
        }
        .compat-table thead th {
            background: var(--table-header-bg);
            color: var(--table-header-text);
            font-weight: 700;
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.5px;
            padding: 12px 14px;
            border: none;
            position: sticky;
            top: 0;
            z-index: 5;
        }
        .compat-table tbody td {
            padding: 12px 14px;
            vertical-align: top;
            border-bottom: 1px solid var(--table-border);
        }
        .compat-table tbody tr { transition: background 0.15s; }
        .compat-table tbody tr:nth-child(even) { background: var(--table-row-alt); }
        .compat-table tbody tr:hover { background: var(--table-row-hover) !important; }

        .col-status { width: 34px; text-align: center; padding: 12px 8px !important; }
        .status-dot {
            width: 10px; height: 10px;
            border-radius: 50%;
            display: inline-block;
        }
        .status-dot.found     { background: var(--success); box-shadow: 0 0 6px var(--success); }
        .status-dot.not-found { background: var(--danger); box-shadow: 0 0 6px var(--danger); }
        .found-row     { border-left: 3px solid var(--success); }
        .not-found-row { border-left: 3px solid var(--danger); }

        .col-part {
            font-family: 'JetBrains Mono', 'Consolas', monospace;
            font-weight: 600;
            white-space: nowrap;
            width: 140px;
            color: var(--text-primary);
        }
        .col-desc { width: 180px; color: var(--text-secondary); }
        .col-model { width: 160px; font-size: 0.82rem; color: var(--text-secondary); }
        .col-result { color: var(--text-primary); line-height: 1.45; }

        /* ── Compatibility Detail Cards ───────────────────── */
        .compat-details { display: flex; flex-direction: column; gap: 6px; }
        .compat-card {
            background: var(--bg-elevated);
            border: 1px solid var(--border-muted);
            border-left: 3px solid var(--success);
            padding: 10px 12px;
            font-size: 0.82rem;
            line-height: 1.4;
            border-radius: 0 8px 8px 0;
            transition: background 0.2s, transform 0.15s;
        }
        .compat-card:hover {
            background: var(--bg-surface-hover);
            transform: translateX(2px);
        }
        .compat-card-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }
        .compat-brand {
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            color: white;
            font-size: 0.65rem;
            font-weight: 800;
            padding: 2px 8px;
            border-radius: 4px;
            text-transform: uppercase;
            white-space: nowrap;
            letter-spacing: 0.5px;
        }
        .compat-model-name {
            font-weight: 700;
            color: var(--text-primary);
            font-size: 0.84rem;
        }
        .compat-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 4px 14px;
            font-size: 0.76rem;
            color: var(--text-secondary);
        }
        .compat-meta-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .compat-meta-label {
            color: var(--text-muted);
            font-weight: 700;
            text-transform: uppercase;
            font-size: 0.66rem;
            letter-spacing: 0.3px;
        }
        .compat-error-msg {
            color: var(--danger-text);
            font-weight: 600;
            font-size: 0.82rem;
        }

        /* Summary footer */
        .results-footer {
            padding: 14px 20px;
            background: var(--bg-elevated);
            border-top: 1px solid var(--border-muted);
            font-size: 0.84rem;
            color: var(--text-secondary);
        }
        .count-found { color: var(--success-text); font-weight: 700; }
        .count-not-found { color: var(--danger-text); font-weight: 700; }

        /* ── Product Cards ────────────────────────────────── */
        .products-section {
            max-width: 1280px;
            margin: 0 auto 32px;
            padding: 0 20px;
        }
        .products-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 16px;
            padding: 20px;
        }
        .product-card {
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 100%;
            transition: transform 0.25s, box-shadow 0.25s, border-color 0.25s;
        }
        .product-card:hover {
            transform: translateY(-4px);
            box-shadow: var(--card-hover-shadow);
            border-color: rgba(59,130,246,0.2);
        }
        .product-card-img-wrap {
            background: var(--bg-elevated);
            display: flex;
            align-items: center;
            justify-content: center;
            height: 160px;
            overflow: hidden;
            border-bottom: 1px solid var(--border-muted);
        }
        .product-card-img-wrap img {
            max-height: 140px;
            max-width: 90%;
            object-fit: contain;
            transition: transform 0.3s;
        }
        .product-card:hover .product-card-img-wrap img {
            transform: scale(1.08);
        }
        .product-card-body {
            padding: 14px;
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .product-card-name {
            font-size: 0.8rem;
            color: var(--text-primary);
            font-weight: 500;
            line-height: 1.4;
            flex: 1;
            margin-bottom: 10px;
        }
        .product-card-price-original {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-decoration: line-through;
            margin-bottom: 2px;
        }
        .product-card-price-pix {
            font-size: 1rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--success), var(--success-text));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 2px;
        }
        .product-card-price-pix-label {
            font-size: 0.68rem;
            color: var(--success-text);
            font-weight: 600;
            margin-bottom: 4px;
        }
        .product-card-installments {
            font-size: 0.72rem;
            color: var(--text-muted);
            margin-bottom: 12px;
        }
        .product-unavailable {
            font-size: 0.72rem;
            color: var(--danger-text);
            font-weight: 700;
            margin-bottom: 8px;
        }
        .btn-product-actions {
            display: flex;
            width: 100%;
            border-top: 1px solid var(--border-muted);
        }
        .btn-link-product {
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            color: white;
            border: none;
            padding: 10px 8px;
            font-size: 0.78rem;
            font-weight: 700;
            flex: 1;
            text-align: center;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            transition: all 0.2s;
        }
        .btn-link-product:hover {
            filter: brightness(1.15);
            color: white;
        }
        .btn-copy-product {
            background: var(--bg-surface-hover);
            color: var(--text-secondary);
            border: none;
            border-left: 1px solid var(--border-muted);
            padding: 10px 12px;
            font-size: 0.82rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            min-width: 40px;
            transition: all 0.2s;
        }
        .btn-copy-product:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
        .btn-copy-product.copied { background: var(--success-bg); color: var(--success-text); }

        /* No results */
        .no-results-msg {
            text-align: center;
            padding: 40px 20px;
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        .no-results-msg i {
            font-size: 2.5rem;
            color: var(--text-faint);
            display: block;
            margin-bottom: 12px;
        }

        /* ── Footer ───────────────────────────────────────── */
        .app-footer {
            text-align: center;
            padding: 24px 20px;
            color: var(--text-faint);
            font-size: 0.7rem;
            margin-top: 40px;
            border-top: 1px solid var(--footer-border);
        }

        /* ── Auth Banner ──────────────────────────────────── */
        #auth-status-banner {
            display: none;
            position: fixed;
            bottom: 0; left: 0; right: 0;
            z-index: 1050;
            padding: 14px 24px;
            animation: bannerSlide 0.3s ease-out;
        }
        @keyframes bannerSlide {
            from { transform: translateY(100%); }
            to   { transform: translateY(0); }
        }
        .banner-inner {
            max-width: 960px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            gap: 12px;
            background: var(--banner-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--banner-border);
            border-radius: 12px;
            padding: 12px 20px;
        }
        .banner-inner .spinner-border {
            width: 16px; height: 16px;
            border-width: 2px;
            color: var(--accent);
            flex-shrink: 0;
        }
        #auth-banner-msg {
            font-size: 0.84rem;
            color: var(--banner-text);
            flex: 1;
        }
        .banner-link {
            background: linear-gradient(135deg, var(--accent), var(--accent-secondary));
            color: white;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 600;
            padding: 6px 14px;
            text-decoration: none;
            white-space: nowrap;
            flex-shrink: 0;
            transition: all 0.2s;
        }
        .banner-link:hover { filter: brightness(1.1); color: white; }

        /* ── Toast Notification ───────────────────────────── */
        .toast-notification {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--toast-bg);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--toast-border);
            color: var(--success-text);
            padding: 12px 20px;
            border-radius: 10px;
            font-size: 0.84rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
            z-index: 2000;
            animation: toastIn 0.3s ease-out, toastOut 0.3s ease-in 1.5s forwards;
            pointer-events: none;
        }
        @keyframes toastIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes toastOut { to { opacity: 0; transform: translateY(10px); } }

        /* ── Responsive ───────────────────────────────────── */
        @media (max-width: 768px) {
            .search-section { padding: 0 12px; margin: 16px auto; }
            .search-panel-wrap { padding: 20px 16px; border-radius: 0 0 12px 12px; }
            .search-grid { grid-template-columns: 1fr; }
            .results-section, .products-section { padding: 0 12px; }
            .products-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; padding: 12px; }
            .summary-strip { flex-direction: column; align-items: flex-start; }
            .summary-stats { margin-left: 0; }
            .theme-toggle { top: 10px; right: 12px; width: 36px; height: 36px; font-size: 1rem; }
        }
    </style>

    <script>
    function showToast(msg) {
        var t = document.createElement('div');
        t.className = 'toast-notification';
        t.innerHTML = '<i class="bi bi-check-circle-fill"></i> ' + msg;
        document.body.appendChild(t);
        setTimeout(function() { t.remove(); }, 2000);
    }
    function copyProductLink(btn, url) {
        navigator.clipboard.writeText(url).then(function() {
            btn.innerHTML = '<i class="bi bi-check-lg"></i>';
            btn.classList.add('copied');
            showToast('Link copiado!');
            setTimeout(function() {
                btn.innerHTML = '<i class="bi bi-clipboard"></i>';
                btn.classList.remove('copied');
            }, 1500);
        });
    }
    function copyCompatResults(btn) {
        var el = document.getElementById('compat-results-text');
        if (!el) return;
        navigator.clipboard.writeText(el.textContent).then(function() {
            var original = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-check-lg"></i> Copiado!';
            btn.classList.add('copied');
            showToast('Relatório copiado para a área de transferência!');
            setTimeout(function() {
                btn.innerHTML = original;
                btn.classList.remove('copied');
            }, 1500);
        });
    }
    function filterCompatTable() {
        var q = (document.getElementById('compat-filter') || {}).value || '';
        q = q.toLowerCase();
        var errorsOnly = (document.getElementById('toggle-errors-btn') || {}).classList &&
                         document.getElementById('toggle-errors-btn').classList.contains('active');
        var rows = document.querySelectorAll('#compat-table tbody tr');
        var visible = 0;
        rows.forEach(function(row) {
            var matchText  = !q || row.textContent.toLowerCase().includes(q);
            var matchErr   = !errorsOnly || row.getAttribute('data-found') === 'true';
            if (matchText && matchErr) { row.style.display = ''; visible++; }
            else { row.style.display = 'none'; }
        });
        var el = document.getElementById('filter-row-count');
        if (el) el.textContent = (q || errorsOnly) ? (visible + ' de ' + rows.length + ' linhas') : '';
    }
    function toggleErrorsOnly() {
        var btn = document.getElementById('toggle-errors-btn');
        if (btn) btn.classList.toggle('active');
        filterCompatTable();
    }
    function switchTab(tabId) {
        document.querySelectorAll('.search-tab').forEach(function(t) { t.classList.remove('active'); });
        document.querySelectorAll('.search-panel').forEach(function(p) { p.classList.remove('active'); });
        document.querySelector('[data-tab="' + tabId + '"]').classList.add('active');
        document.getElementById(tabId).classList.add('active');
    }
    function toggleTheme() {
        var html = document.documentElement;
        var current = html.getAttribute('data-theme') || 'dark';
        var next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        localStorage.setItem('eper-theme', next);
        updateThemeIcon(next);
    }
    function updateThemeIcon(theme) {
        var btn = document.getElementById('theme-toggle-btn');
        if (btn) btn.innerHTML = theme === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
    }
    (function() {
        var saved = localStorage.getItem('eper-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        document.addEventListener('DOMContentLoaded', function() { updateThemeIcon(saved); });
    })();
    </script>
</head>
<body>

    <!-- Theme Toggle -->
    <button id="theme-toggle-btn" class="theme-toggle" onclick="toggleTheme()" title="Alternar tema claro/escuro">
        <i class="bi bi-sun-fill"></i>
    </button>

    <!-- Search Section -->
    <div class="search-section">
        <div class="search-tabs">
            <button class="search-tab active" data-tab="tab-code" onclick="switchTab('tab-code')">
                <i class="bi bi-upc-scan"></i> Por Código
            </button>
            <button class="search-tab" data-tab="tab-name" onclick="switchTab('tab-name')">
                <i class="bi bi-search"></i> Por Nome
            </button>
        </div>

        <div class="search-panel-wrap">
            <!-- Tab: By Code -->
            <div id="tab-code" class="search-panel active">
                <form method="POST">
                    <div class="search-grid">
                        <div>
                            <label for="parts_bulk" class="form-label-custom">Códigos das Peças (uma por linha)</label>
                            <textarea class="form-textarea" id="parts_bulk" name="parts_bulk" rows="8" placeholder="K55111314AC&#9;Reservatório&#10;K55111354AA&#9;Tampa&#10;K05168128AB&#9;Barra estabilizadora&#10;K68073033AC&#9;Haste da barra">{{ parts_bulk }}</textarea>
                            <div class="form-hint">Cole vários códigos de uma vez. Use tab, ponto-e-vírgula ou espaço para incluir a descrição opcional.</div>
                        </div>
                        <div>
                            <label for="vc" class="form-label-custom">Chassi (Opcional)</label>
                            <input type="text" class="form-input" id="vc" name="vc" value="{{ vc }}" placeholder="Ex: 9BWAA01J754038498" style="margin-bottom:16px;">

                            <label for="vehicle_label" class="form-label-custom">Veículo (Opcional)</label>
                            <input type="text" class="form-input" id="vehicle_label" name="vehicle_label" value="{{ vehicle_label }}" placeholder="Ex: FIAT 500 (2010–2018)">
                            <div class="form-hint">Título do relatório. Se vazio, será inferido dos resultados.</div>
                        </div>
                    </div>
                    <div style="display:flex;justify-content:flex-end;margin-top:20px;">
                        <button type="submit" class="btn-search-main">
                            <i class="bi bi-search"></i> Consultar Compatibilidade
                        </button>
                    </div>
                </form>
            </div>

            <!-- Tab: By Name -->
            <div id="tab-name" class="search-panel">
                <form method="POST">
                    <label for="name_query" class="form-label-custom">Buscar por Nome (FiatPecas.com.br)</label>
                    <div class="name-search-bar">
                        <input type="text" class="form-input" id="name_query" name="name_query" value="{{ name_query }}" placeholder="Ex: Lâmpada pingo d'água w5w">
                        <button type="submit" class="btn-search-icon"><i class="bi bi-search"></i></button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    {% if request.args.get('refreshed') == 'success' %}
    <div class="alert-modern alert-success-modern" style="padding-left:20px;padding-right:20px;">
        <i class="bi bi-check-circle-fill"></i> Sessão renovada com sucesso!
    </div>
    {% elif request.args.get('refreshed') == 'error' %}
    <div class="alert-modern alert-danger-modern" style="padding-left:20px;padding-right:20px;">
        <i class="bi bi-exclamation-triangle-fill"></i> Falha ao renovar: {{ request.args.get('errmsg') }}
    </div>
    {% endif %}

    {% if error %}
    <div class="alert-modern alert-danger-modern" style="max-width:960px;margin:0 auto 16px;padding-left:20px;padding-right:20px;">
        <i class="bi bi-exclamation-triangle-fill"></i> {{ error | safe }}
    </div>
    {% endif %}

    {% if batch_results %}
    <div class="results-section">
        <div class="results-panel">

            <!-- Panel Header -->
            <div class="panel-header">
                <span class="panel-header-title">
                    <i class="bi bi-clipboard-data"></i> Resultado de Compatibilidade
                </span>
                <button type="button" class="btn-copy-report" onclick="copyCompatResults(this)">
                    <i class="bi bi-clipboard"></i> Copiar relatório
                </button>
            </div>

            <!-- Summary Strip -->
            <div class="summary-strip">
                <span class="summary-title">{{ report_title }}</span>
                <div class="summary-stats">
                    <span class="stat-pill total"><i class="bi bi-list-ul"></i> {{ batch_results|length }} peças</span>
                    <span class="stat-pill found"><i class="bi bi-check-circle"></i> {{ found_count }} encontradas</span>
                    {% if not_found_count > 0 %}
                    <span class="stat-pill not-found"><i class="bi bi-x-circle"></i> {{ not_found_count }} sem resultado</span>
                    {% endif %}
                </div>
            </div>
            <div class="progress-wrap">
                <div class="progress-fill" style="width:{{ (found_count / batch_results|length * 100)|round|int }}%"></div>
            </div>

            <!-- Filter Bar -->
            <div class="filter-bar">
                <div class="filter-icon-wrap" style="flex:1;min-width:200px;max-width:360px;">
                    <i class="bi bi-search"></i>
                    <input type="text" id="compat-filter" class="filter-input" style="width:100%;"
                           placeholder="Filtrar por código, descrição ou modelo..."
                           oninput="filterCompatTable()">
                </div>
                <button id="toggle-errors-btn" class="toggle-btn" onclick="toggleErrorsOnly()">
                    <i class="bi bi-check-circle"></i> Apenas sem erro
                </button>
                <span id="filter-row-count" class="filter-count"></span>
            </div>

            <!-- Table -->
            <div class="table-scroll-wrap">
                <table class="compat-table" id="compat-table">
                    <thead>
                        <tr>
                            <th class="col-status" title="Status"></th>
                            <th class="col-part">Peça</th>
                            <th class="col-desc">Descrição</th>
                            <th class="col-model">Modelo</th>
                            <th class="col-result">Compatibilidade</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for row in batch_results %}
                        <tr class="{{ 'found-row' if row.found else 'not-found-row' }}"
                            data-found="{{ 'true' if row.found else 'false' }}">
                            <td class="col-status">
                                <span class="status-dot {{ 'found' if row.found else 'not-found' }}"
                                      title="{{ 'Compatível' if row.found else 'Sem resultado' }}"></span>
                            </td>
                            <td class="col-part">{{ row.code }}</td>
                            <td class="col-desc">{{ row.description or '—' }}</td>
                            <td class="col-model">{{ row.model or '—' }}</td>
                            <td class="col-result">
                                {% if row.compatibility_details %}
                                <div class="compat-details">
                                    {% for d in row.compatibility_details %}
                                    <div class="compat-card">
                                        <div class="compat-card-header">
                                            {% if d.brand %}<span class="compat-brand">{{ d.brand }}</span>{% endif %}
                                            <span class="compat-model-name">{{ d.model }}</span>
                                        </div>
                                        <div class="compat-meta">
                                            {% if d.tables %}
                                            <span class="compat-meta-item">
                                                <span class="compat-meta-label">Tabelas:</span> {{ d.tables }}
                                            </span>
                                            {% endif %}
                                            {% if d.table_desc %}
                                            <span class="compat-meta-item">
                                                <span class="compat-meta-label">Grupo:</span> {{ d.table_desc }}
                                            </span>
                                            {% endif %}
                                            {% if d.part_dsc %}
                                            <span class="compat-meta-item">
                                                <span class="compat-meta-label">Peça:</span> {{ d.part_dsc }}
                                            </span>
                                            {% endif %}
                                        </div>
                                    </div>
                                    {% endfor %}
                                </div>
                                {% else %}
                                <span class="compat-error-msg">{{ row.result }}</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <!-- Footer summary -->
            <div class="results-footer">
                <span class="count-found">{{ found_count }} peça{{ 's' if found_count != 1 else '' }} com aplicação</span>
                /
                <span class="count-not-found">{{ not_found_count }} sem resultado no catálogo</span>
                {% if not_found_codes %}
                — sem resultado: {{ not_found_codes | join(', ') }}.
                {% else %}
                .
                {% endif %}
            </div>
        </div>

        <!-- Hidden text for copy -->
        <pre id="compat-results-text" style="display:none;">Resultado de Compatibilidade — {{ report_title }}

Peça	Descrição	Marca	Modelo	Tabelas	Grupo	Peça Catálogo
{% for row in batch_results %}{% if row.compatibility_details %}{% for d in row.compatibility_details %}{{ row.code }}	{{ row.description or '—' }}	{{ d.brand or '—' }}	{{ d.model }}	{{ d.tables or '—' }}	{{ d.table_desc or '—' }}	{{ d.part_dsc or '—' }}
{% endfor %}{% else %}{{ row.code }}	{{ row.description or '—' }}	—	{{ row.model or '—' }}	—	—	{{ row.result }}
{% endif %}{% endfor %}
{{ found_count }} peça{{ 's' if found_count != 1 else '' }} com aplicação / {{ not_found_count }} sem resultado no catálogo{% if not_found_codes %} ({{ not_found_codes | join(', ') }}){% endif %}.</pre>
    </div>
    {% endif %}

    {% if products %}
    <!-- Products Panel -->
    <div class="products-section">
        <div class="results-panel">
            <div class="panel-header">
                <span class="panel-header-title">
                    <i class="bi bi-shop"></i> Produtos Encontrados no FiatPecas.com.br
                </span>
            </div>
            <div class="products-grid">
                {% for p in products %}
                <div class="product-card">
                    <div class="product-card-img-wrap">
                        {% if p.image %}
                        <img src="{{ p.image }}" alt="{{ p.name }}" loading="lazy">
                        {% else %}
                        <i class="bi bi-image" style="font-size:2rem;color:#334155;"></i>
                        {% endif %}
                    </div>
                    <div class="product-card-body">
                        <div class="product-card-name">{{ p.name }}</div>
                        {% if p.price_original and p.price_pix and p.price_original != p.price_pix %}
                        <div class="product-card-price-original">{{ p.price_original }}</div>
                        {% endif %}
                        {% if p.price_pix %}
                        <div class="product-card-price-pix">{{ p.price_pix }}</div>
                        <div class="product-card-price-pix-label">no PIX</div>
                        {% elif p.price_original %}
                        <div class="product-card-price-pix">{{ p.price_original }}</div>
                        {% endif %}
                        {% if p.installments %}
                        <div class="product-card-installments">{{ p.installments }}</div>
                        {% endif %}
                        {% if not p.available %}
                        <div class="product-unavailable">Indisponível</div>
                        {% endif %}
                    </div>
                    <div class="btn-product-actions">
                        <a href="{{ p.url }}" target="_blank" class="btn-link-product"><i class="bi bi-box-arrow-up-right"></i> LINK</a>
                        <button type="button" class="btn-copy-product" title="Copiar link" data-url="{{ p.url }}" onclick="copyProductLink(this, this.dataset.url)"><i class="bi bi-clipboard"></i></button>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}

    {% if not products and name_query and not error %}
    <div class="products-section">
        <div class="results-panel">
            <div class="panel-header">
                <span class="panel-header-title">
                    <i class="bi bi-shop"></i> Produtos Encontrados no FiatPecas.com.br
                </span>
            </div>
            <div class="no-results-msg">
                <i class="bi bi-search"></i>
                Desculpe, sua busca por <strong>"{{ name_query if name_query else part }}"</strong> não retornou nenhum resultado.
            </div>
        </div>
    </div>
    {% endif %}

    <!-- Footer -->
    <div class="app-footer">
        Versão: 2.0.0 | ÚLTIMA ATUALIZAÇÃO NO SERVIDOR: 16/07/2026 16:00
    </div>

    <!-- Auth Status Banner -->
    <div id="auth-status-banner">
        <div class="banner-inner">
            <span class="spinner-border spinner-border-sm" id="auth-banner-spinner"></span>
            <span id="auth-banner-msg">Autenticação em andamento. A busca estará disponível em breve...</span>
            <a href="/compatibilidade/login" class="banner-link">Ver status</a>
        </div>
    </div>

    <script>
    (function() {
        var banner = document.getElementById('auth-status-banner');
        var msg    = document.getElementById('auth-banner-msg');
        var spin   = document.getElementById('auth-banner-spinner');

        function showError(text) {
            if (!banner) return;
            var inner = banner.querySelector('.banner-inner');
            if (inner) {
                inner.style.background = 'rgba(127,29,29,0.9)';
                inner.style.borderColor = 'rgba(239,68,68,0.3)';
            }
            if (spin) spin.style.display = 'none';
            if (msg) msg.innerHTML = text;
            banner.style.display = 'block';
        }

        function pollUntilDone() {
            setTimeout(function() {
                fetch('/compatibilidade/api/auth/status')
                    .then(function(r) { return r.json(); })
                    .then(function(d) {
                        if (d.state === 'success') {
                            if (banner) {
                                var inner = banner.querySelector('.banner-inner');
                                if (inner) {
                                    inner.style.background = 'rgba(6,78,59,0.9)';
                                    inner.style.borderColor = 'rgba(16,185,129,0.3)';
                                }
                                if (spin) spin.style.display = 'none';
                                if (msg) msg.textContent = 'Sessão autenticada! Você já pode realizar buscas.';
                                setTimeout(function() { banner.style.display = 'none'; }, 4000);
                            }
                        } else if (d.state === 'error') {
                            showError('Falha na autenticação. <a href="/compatibilidade/login" style="color:#fca5a5;font-weight:600;">Clique aqui para renovar a sessão.</a>');
                        } else {
                            pollUntilDone();
                        }
                    })
                    .catch(pollUntilDone);
            }, 4000);
        }

        fetch('/compatibilidade/api/auth/status')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.state === 'loading') {
                    if (banner) banner.style.display = 'block';
                    pollUntilDone();
                } else if (d.state === 'error') {
                    showError('Sessão não autenticada. <a href="/compatibilidade/login" style="color:#fca5a5;font-weight:600;">Clique aqui para iniciar sessão.</a>');
                }
            })
            .catch(function() {});

        // Auto-switch to name tab if name_query has value
        var nameInput = document.getElementById('name_query');
        if (nameInput && nameInput.value && !document.getElementById('parts_bulk').value) {
            switchTab('tab-name');
        }
    })();
    </script>

</body>
</html>
"""


HTML_TEMPLATE_COMPILED = app.jinja_env.from_string(HTML_TEMPLATE)



def _parse_fiatpecas_html(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".js-item-product")
    products = []

    for item in items:
        try:
            link_tag = item.select_one("a[href]")
            product_url = link_tag["href"] if link_tag else "#"

            name_tag = item.select_one(".js-item-name")
            name = name_tag.get_text(strip=True) if name_tag else ""

            img_tag = item.select_one("img.js-item-image")
            image = ""
            if img_tag:
                srcset = img_tag.get("data-srcset", "") or img_tag.get("srcset", "") or img_tag.get("src", "")
                if srcset:
                    image = srcset.split(",")[0].strip().split(" ")[0]

            container = item.select_one(".js-product-container")
            price_original = ""
            price_pix = ""
            installments = ""
            available = True

            if container:
                variants_raw = container.get("data-variants", "[]")
                try:
                    variants = json.loads(variants_raw)
                    if variants:
                        v = variants[0]
                        price_original = v.get("price_short", "")
                        price_pix = v.get("price_with_payment_discount_short", "") or price_original
                        available = bool(v.get("available", True))
                        inst_raw = v.get("installments_data", "")
                        if inst_raw:
                            try:
                                inst_data = json.loads(inst_raw)
                                qty = inst_data.get("installments_count", "")
                                val = inst_data.get("installment_value_short", "")
                                if qty and val:
                                    installments = f"{qty}x de {val}"
                            except Exception:
                                pass
                except Exception:
                    pass

            products.append({
                "name": name,
                "url": product_url,
                "image": image,
                "price_original": price_original,
                "price_pix": price_pix,
                "installments": installments,
                "available": available,
            })
        except Exception as e:
            print(f"[FIATPECAS] Erro ao parsear produto: {e}")
            continue

    return products


def search_fiatpecas(part_code):
    """Fetch and parse product listings from fiatpecas.com.br for a given part code."""
    global _fiatpecas_winning_profile

    with _fiatpecas_cache_lock:
        cached = _fiatpecas_cache.get(part_code)
        if cached and time.time() - cached[0] < FIATPECAS_CACHE_TTL:
            return cached[1]

    url = f"https://fiatpecas.com.br/search/?q={part_code}"
    profiles = []
    if _fiatpecas_winning_profile:
        profiles.append(_fiatpecas_winning_profile)
    profiles.extend(p for p in FIATPECAS_IMPERSONATES if p != _fiatpecas_winning_profile)

    resp = None
    used_profile = None

    for imp in profiles:
        try:
            resp = cffi_requests.get(url, impersonate=imp, timeout=15)
            if resp.status_code == 200:
                used_profile = imp
                print(f"[FIATPECAS] Sucesso com impersonate='{imp}'")
                break
            print(f"[FIATPECAS] Resposta nao-200 com '{imp}': {resp.status_code}")
        except Exception as e:
            print(f"[FIATPECAS] Erro (curl_cffi, {imp}): {e}")

    if not resp or resp.status_code != 200:
        print("[FIATPECAS] Tentando fallback com Cloudscraper...")
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            resp = scraper.get(url, timeout=15)
            if resp.status_code == 200:
                print("[FIATPECAS] Sucesso com Cloudscraper!")
            else:
                print(f"[FIATPECAS] Resposta nao-200 no Cloudscraper: {resp.status_code}")
        except Exception as e:
            print(f"[FIATPECAS] Erro com Cloudscraper: {e}")

    if not resp or resp.status_code != 200:
        print(f"[FIATPECAS] Falha definitiva. Status: {resp.status_code if resp else 'N/A'}")
        return []

    if used_profile:
        _fiatpecas_winning_profile = used_profile

    products = _parse_fiatpecas_html(resp.text)
    print(f"[FIATPECAS] {len(products)} produto(s) encontrado(s) para '{part_code}'")

    with _fiatpecas_cache_lock:
        _fiatpecas_cache[part_code] = (time.time(), products)

    return products


def refresh_session_loop():
    """Background task: initial login after 10s, then refresh every 6 hours."""
    time.sleep(10)
    print("[BACKGROUND] Iniciando autenticação inicial...")
    _run_auth(force=False)
    while True:
        time.sleep(6 * 60 * 60)
        print("[BACKGROUND] Renovando cookies automaticamente...")
        _run_auth(force=True)

@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        print("[WEB] Renovação manual de sessão solicitada...")
        fiat_parts_tool.get_cookies(force_login=True, headless=True)
        return redirect(url_for('index', refreshed='success'))
    except Exception as e:
        print(f"[WEB] Falha na renovacao manual: {e}")
        return redirect(url_for('index', refreshed='error', errmsg=str(e)[:100]))


@app.route("/api/auth/status", methods=["GET"])
def api_auth_status():
    """Return current authentication status as JSON (non-blocking)."""
    if fiat_parts_tool.has_valid_cookies():
        return jsonify({"state": "success", "has_cookies": True})
    with _auth_bg_lock:
        status = dict(_auth_bg_status)
    status["has_cookies"] = False
    return jsonify(status)


@app.route("/api/auth/start", methods=["POST"])
def api_auth_start():
    """Start background Selenium authentication without blocking. Returns immediately."""
    if fiat_parts_tool.has_valid_cookies():
        return jsonify({"state": "success", "message": "Sessão já ativa."})
    with _auth_bg_lock:
        already_running = _auth_bg_status["state"] == "loading"
    if not already_running:
        t = threading.Thread(target=lambda: _run_auth(force=False), daemon=True)
        t.start()
        message = "Autenticação iniciada em segundo plano."
    else:
        message = "Autenticação já em andamento."
    return jsonify({"state": "loading", "message": message})


@app.route("/login", methods=["GET"])
def login_page():
    """Login splash page — triggers async Selenium auth and lets user navigate immediately."""
    return LOGIN_TEMPLATE_COMPILED.render()

@app.route("/", methods=["GET", "POST"])
def index():
    part = ""
    vc = ""
    name_query = ""
    parts_bulk = ""
    vehicle_label = ""
    error_text = None
    products = []
    batch_results = None
    report_title = ""
    found_count = 0
    not_found_count = 0
    not_found_codes = []

    if request.method == "POST":
        parts_bulk = request.form.get("parts_bulk", "").strip()
        vc = request.form.get("vc", "").strip()
        vehicle_label = request.form.get("vehicle_label", "").strip()
        name_query = request.form.get("name_query", "").strip()

        if name_query and not parts_bulk:
            print(f"WEB: Buscando por nome '{name_query}' no FiatPecas")
            products = search_fiatpecas(name_query)
        elif parts_bulk:
            entries = fiat_parts_tool.parse_bulk_parts(parts_bulk)
            if not entries:
                error_text = "Nenhum código de peça válido encontrado no texto informado."
            elif not fiat_parts_tool.has_valid_cookies():
                with _auth_bg_lock:
                    auth_state = _auth_bg_status["state"]
                if auth_state == "loading":
                    error_text = "⏳ Autenticação em andamento. Aguarde alguns segundos e tente novamente."
                else:
                    error_text = '⚠️ Sessão não iniciada. <a href="/compatibilidade/login" class="alert-link">Clique aqui</a> para autenticar antes de pesquisar.'
            else:
                chassis = vc if vc else None
                batch_start = time.time()
                print(f"WEB: Consultando {len(entries)} peca(s) em lote" + (f" para chassi {chassis}" if chassis else ""))
                batch_results = fiat_parts_tool.query_batch(entries, chassis, headless=True)
                print(f"WEB: Lote concluido em {time.time() - batch_start:.1f}s")

                found_count = sum(1 for r in batch_results if r["found"])
                not_found_count = len(batch_results) - found_count
                not_found_codes = [r["code"] for r in batch_results if not r["found"]]
                report_title = fiat_parts_tool.infer_vehicle_label(vehicle_label, vc, batch_results)

                if len(entries) == 1:
                    part = entries[0]["code"]
                    products = search_fiatpecas(part)
        else:
            error_text = "Informe um ou mais códigos de peça ou um nome para buscar."

    return HTML_TEMPLATE_COMPILED.render(
        request=request,
        part=part,
        vc=vc,
        name_query=name_query,
        parts_bulk=parts_bulk,
        vehicle_label=vehicle_label,
        error=error_text,
        products=products,
        batch_results=batch_results,
        report_title=report_title,
        found_count=found_count,
        not_found_count=not_found_count,
        not_found_codes=not_found_codes,
    )

if __name__ == "__main__":
    print("[INFO] Iniciando daemon de background para login e renovacao automatica...")
    bg_thread = threading.Thread(target=refresh_session_loop, daemon=True)
    bg_thread.start()

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5002"))
    use_waitress = os.environ.get("USE_WAITRESS", "auto")

    if use_waitress == "auto":
        use_waitress = sys.platform != "win32"
    else:
        use_waitress = use_waitress.lower() in ("1", "true", "yes")

    if use_waitress:
        from waitress import serve
        threads = int(os.environ.get("WAITRESS_THREADS", "8"))
        channel_timeout = int(os.environ.get("WAITRESS_CHANNEL_TIMEOUT", "300"))
        print(f"[INFO] Waitress em http://{host}:{port} ({threads} threads, timeout={channel_timeout}s)")
        serve(app, host=host, port=port, threads=threads, channel_timeout=channel_timeout)
    else:
        print(f"[INFO] Flask dev em http://{host}:{port} (threaded)")
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
