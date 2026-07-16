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
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
    <style>
        body { background-color: #f1f1f1; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; }
        .eper-navbar { background-color: #005fa9; color: white; display: flex; align-items: flex-end; padding: 0 20px; height: 60px; }
        .login-card { background: white; border: 1px solid #ddd; padding: 40px; max-width: 480px; width: 100%; }
        .btn-iniciar { background-color: #005fa9; color: white; border: none; border-radius: 0; padding: 14px 40px; font-size: 1rem; font-weight: 600; width: 100%; }
        .btn-iniciar:hover:not(:disabled) { background-color: #004d8a; color: white; }
        .btn-iniciar:disabled { background-color: #6c9dc5; color: white; cursor: not-allowed; }
    </style>
</head>
<body>
    <div class="eper-navbar">
        <div style="background:#ffffff;padding:5px 10px;border-radius:4px;display:flex;align-items:center;margin-bottom:8px;">
            <img src="https://s3-sa-east-1.amazonaws.com/images.anymarket.com.br/22449504./6ECFF29E478B05B93B2973D56786FCFE/standard_resolution.jpg" alt="Marca Seleta" style="height:48px;width:auto;">
        </div>
    </div>

    <div class="d-flex justify-content-center align-items-center" style="min-height:calc(100vh - 60px);padding:40px 20px;">
        <div class="login-card">
            <h4 class="mb-1" style="color:#005fa9;font-weight:700;">Consulta de Compatibilidade</h4>
            <p class="text-muted mb-4" style="font-size:0.9rem;">Sistema de Consulta ePER — Peças Fiat</p>

            <div id="status-area" class="mb-4" style="min-height:52px;">
                <div class="alert alert-secondary mb-0" style="font-size:0.85rem;">
                    <i class="bi bi-info-circle me-2"></i> Verificando status da sessão...
                </div>
            </div>

            <button id="btn-start" class="btn btn-iniciar" disabled>
                <span class="spinner-border spinner-border-sm me-2"></span> Verificando...
            </button>

            <div class="mt-3 text-center">
                <a href="/compatibilidade/" style="font-size:0.85rem;color:#888;">Ir direto para a busca &rarr;</a>
            </div>
        </div>
    </div>

    <script>
    var _polling = false;

    function setStatus(state, msg) {
        var cfg = {
            success: {color:'success', icon:'bi-check-circle-fill'},
            loading: {color:'info',    icon:'bi-arrow-repeat'},
            error:   {color:'danger',  icon:'bi-exclamation-triangle-fill'},
            idle:    {color:'secondary',icon:'bi-info-circle'}
        }[state] || {color:'secondary', icon:'bi-info-circle'};
        document.getElementById('status-area').innerHTML =
            '<div class="alert alert-' + cfg.color + ' mb-0" style="font-size:0.85rem;">' +
            '<i class="bi ' + cfg.icon + ' me-2"></i>' + msg + '</div>';
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
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Conectando ao portal Fiat...';
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
                btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Aguardando autenticação...';
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
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
    <style>
        body { 
            background-color: #f1f1f1; 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0; 
            padding: 0; 
        }
        
        /* Navbar / Header */
        .eper-navbar {
            background-color: #005fa9;
            color: white;
            display: flex;
            align-items: flex-end;
            padding: 0 20px;
            height: 60px;
        }
        .eper-logo {
            font-size: 1.5rem;
            font-weight: 800;
            margin-right: 15px;
            letter-spacing: 1px;
            padding-bottom: 10px;
        }
        .eper-header-right {
            margin-left: auto;
            padding-bottom: 15px;
        }

        /* Subheader */
        .eper-subheader {
            background-color: #f8f9fa;
            border-bottom: 1px solid #ddd;
            display: flex;
            align-items: center;
            height: 40px;
            font-size: 0.8rem;
            font-weight: 600;
            color: #555;
        }
        .eper-btn-back {
            background-color: #bf1018;
            color: white;
            height: 100%;
            width: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 15px;
        }

        /* Search Area */
        .search-container {
            padding: 30px 0;
            background-color: #f1f1f1;
            display: flex;
            justify-content: center;
        }
        .search-box {
            display: flex;
            width: 100%;
            max-width: 700px;
            background: white;
            border: 1px solid #005fa9;
        }
        .search-box input {
            border: none;
            padding: 10px 15px;
            outline: none;
            box-shadow: none;
            border-radius: 0;
            font-size: 0.95rem;
        }
        .search-box input:focus {
            box-shadow: none;
        }
        .search-box .btn-search {
            background-color: #005fa9;
            color: white;
            border: none;
            border-radius: 0;
            padding: 10px 20px;
        }
        .search-box .btn-search:hover {
            background-color: #004d8a;
        }

        /* Results / Panel */
        .eper-panel {
            background: white;
            margin-bottom: 25px;
            border: 1px solid #ddd;
        }
        .eper-panel-header {
            background-color: #005fa9;
            color: white;
            padding: 8px 15px;
            font-size: 0.85rem;
            font-weight: 600;
            text-transform: uppercase;
        }
        .eper-panel-title {
            padding: 15px;
            font-size: 1.1rem;
            color: #005fa9;
            font-weight: 600;
            display: flex;
            align-items: center;
            border-bottom: 1px solid #ddd;
        }
        .eper-panel-title i {
            font-size: 1.4rem;
            margin-right: 10px;
        }
        .eper-panel-body {
            padding: 0;
        }

        /* Grid data */
        .data-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            font-size: 0.85rem;
        }
        .data-row {
            display: flex;
            padding: 8px 15px;
            border-bottom: 1px solid #f1f1f1;
        }
        .data-label {
            width: 40%;
            text-align: right;
            color: #666;
            text-transform: uppercase;
            margin-right: 15px;
        }
        .data-value {
            width: 60%;
            font-weight: 500;
            color: #333;
        }
        .bg-light-blue { background-color: #f7fbff; }

        /* Output Pre */
        .raw-output {
            background: #f8f9fa;
            border: none;
            padding: 15px;
            font-size: 0.85rem;
            color: #333;
            margin: 0;
            max-height: 400px;
            overflow-y: auto;
        }

        /* Product Cards */
        .product-card {
            background: white;
            border: 1px solid #ddd;
            display: flex;
            flex-direction: column;
            height: 100%;
        }
        .product-card-img-wrap {
            background: #f8f9fa;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 160px;
            overflow: hidden;
            border-bottom: 1px solid #eee;
        }
        .product-card-img-wrap img {
            max-height: 150px;
            max-width: 100%;
            object-fit: contain;
        }
        .product-card-body {
            padding: 12px;
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        .product-card-name {
            font-size: 0.8rem;
            color: #333;
            font-weight: 500;
            line-height: 1.35;
            flex: 1;
            margin-bottom: 10px;
        }
        .product-card-price-original {
            font-size: 0.75rem;
            color: #999;
            text-decoration: line-through;
            margin-bottom: 2px;
        }
        .product-card-price-pix {
            font-size: 0.95rem;
            font-weight: 700;
            color: #1a7a2e;
            margin-bottom: 2px;
        }
        .product-card-price-pix-label {
            font-size: 0.7rem;
            color: #1a7a2e;
            margin-bottom: 4px;
        }
        .product-card-installments {
            font-size: 0.72rem;
            color: #555;
            margin-bottom: 12px;
        }
        .btn-product-actions {
            display: flex;
            width: 100%;
        }
        .btn-link-product {
            background-color: #005fa9;
            color: white;
            border: none;
            border-radius: 0;
            padding: 8px 6px;
            font-size: 0.78rem;
            font-weight: 600;
            flex: 1;
            text-align: center;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
        }
        .btn-link-product:hover {
            background-color: #004d8a;
            color: white;
        }
        .btn-copy-product {
            background-color: #4a4a6a;
            color: white;
            border: none;
            border-left: 1px solid rgba(255,255,255,0.2);
            border-radius: 0;
            padding: 8px 10px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            min-width: 36px;
        }
        .btn-copy-product:hover {
            background-color: #36365a;
        }
        .btn-copy-product.copied {
            background-color: #1a7a2e;
        }
        .product-unavailable {
            font-size: 0.72rem;
            color: #bf1018;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .no-results-msg {
            text-align: center;
            padding: 30px 20px;
            color: #555;
            font-size: 0.9rem;
        }

        /* Bulk search */
        .bulk-search-box {
            width: 100%;
            max-width: 900px;
            background: white;
            border: 1px solid #005fa9;
            padding: 15px;
        }
        .bulk-search-box textarea {
            border: 1px solid #ddd;
            border-radius: 0;
            font-size: 0.9rem;
            font-family: 'Consolas', 'Courier New', monospace;
            resize: vertical;
            min-height: 160px;
        }
        .bulk-search-box textarea:focus {
            border-color: #005fa9;
            box-shadow: none;
        }
        .bulk-hint {
            font-size: 0.75rem;
            color: #777;
            margin-top: 6px;
        }
        .compat-table {
            width: 100%;
            font-size: 0.85rem;
            margin: 0;
        }
        .compat-table thead th {
            background-color: #005fa9;
            color: white;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            padding: 10px 12px;
            border: none;
        }
        .compat-table tbody td {
            padding: 10px 12px;
            vertical-align: top;
            border-bottom: 1px solid #eee;
        }
        .compat-table tbody tr:nth-child(even) {
            background-color: #f7fbff;
        }
        .compat-table .col-part {
            font-family: 'Consolas', 'Courier New', monospace;
            font-weight: 600;
            white-space: nowrap;
            width: 140px;
        }
        .compat-table .col-desc {
            width: 180px;
            color: #555;
        }
        .compat-table .col-result {
            color: #333;
            line-height: 1.45;
        }
        .compat-summary {
            padding: 12px 15px;
            background: #f8f9fa;
            border-top: 1px solid #ddd;
            font-size: 0.85rem;
            color: #444;
        }
        .compat-summary .count-found {
            color: #1a7a2e;
            font-weight: 600;
        }
        .compat-summary .count-not-found {
            color: #bf1018;
            font-weight: 600;
        }
        .btn-copy-results {
            background-color: #4a4a6a;
            color: white;
            border: none;
            border-radius: 0;
            padding: 6px 14px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-copy-results:hover {
            background-color: #36365a;
        }
        .btn-copy-results.copied {
            background-color: #1a7a2e;
        }
        .report-title {
            padding: 15px;
            font-size: 1.05rem;
            color: #005fa9;
            font-weight: 700;
            border-bottom: 1px solid #ddd;
        }

        /* ── Redesign: Result Table ─────────────────────────── */
        .col-status { width: 34px; text-align: center; padding: 10px 6px !important; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .status-dot.found     { background: #1a7a2e; box-shadow: 0 0 0 2px #d1e7dd; }
        .status-dot.not-found { background: #bf1018; box-shadow: 0 0 0 2px #f8d7da; }
        .found-row     { border-left: 3px solid #1a7a2e; }
        .not-found-row { border-left: 3px solid #bf1018; }
        .found-row:hover, .not-found-row:hover { background-color: #f0f6ff !important; }
        .compat-table .col-model { width: 160px; font-size: 0.82rem; color: #444; }

        /* Summary strip */
        .result-summary-strip { padding: 10px 15px; background: #f8f9fa; border-bottom: 1px solid #ddd; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .stat-badge { font-size: 0.78rem; font-weight: 600; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }
        .stat-badge.total     { background: #e2e3e5; color: #41464b; }
        .stat-badge.found     { background: #d1e7dd; color: #0f5132; }
        .stat-badge.not-found { background: #f8d7da; color: #842029; }

        /* Progress bar */
        .found-progress-wrap { height: 4px; background: #e9ecef; }
        .found-progress-bar  { height: 100%; background: linear-gradient(90deg, #1a7a2e, #2da84e); }

        /* Filter bar */
        .compat-filter-bar { padding: 10px 15px; background: #f0f6ff; border-bottom: 1px solid #d0d9e8; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .compat-filter-input { border: 1px solid #b0c4de; padding: 5px 10px; font-size: 0.82rem; flex: 1; min-width: 180px; max-width: 340px; border-radius: 0; outline: none; }
        .compat-filter-input:focus { border-color: #005fa9; }
        .toggle-errors-btn { font-size: 0.78rem; padding: 5px 12px; border: 1px solid #ddd; background: white; cursor: pointer; border-radius: 0; color: #555; white-space: nowrap; }
        .toggle-errors-btn.active { background: #bf1018; color: white; border-color: #bf1018; }

        /* Scrollable table body */
        .table-scroll-wrap { overflow-x: auto; max-height: 560px; overflow-y: auto; }
        .table-scroll-wrap thead th { position: sticky; top: 0; z-index: 5; }

        /* ── Compatibility Detail Cards ───────────────────── */
        .compat-details { display: flex; flex-direction: column; gap: 6px; }
        .compat-card {
            background: #f8fafe;
            border: 1px solid #e0e7ef;
            border-left: 3px solid #1a7a2e;
            padding: 8px 10px;
            font-size: 0.82rem;
            line-height: 1.4;
            border-radius: 0 3px 3px 0;
            transition: background 0.15s;
        }
        .compat-card:hover { background: #eef4fb; }
        .compat-card-header {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-bottom: 4px;
        }
        .compat-brand {
            background: #005fa9;
            color: white;
            font-size: 0.68rem;
            font-weight: 700;
            padding: 1px 6px;
            border-radius: 2px;
            text-transform: uppercase;
            white-space: nowrap;
            letter-spacing: 0.5px;
        }
        .compat-model-name {
            font-weight: 700;
            color: #222;
            font-size: 0.84rem;
        }
        .compat-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 4px 12px;
            font-size: 0.76rem;
            color: #555;
        }
        .compat-meta-item {
            display: flex;
            align-items: center;
            gap: 3px;
        }
        .compat-meta-label {
            color: #888;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.68rem;
            letter-spacing: 0.3px;
        }
        .compat-error-msg {
            color: #bf1018;
            font-weight: 600;
            font-size: 0.82rem;
        }
    </style>
    <script>
    function copyProductLink(btn, url) {
        navigator.clipboard.writeText(url).then(function() {
            btn.innerHTML = '<i class="bi bi-check-lg"></i>';
            btn.classList.add('copied');
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
    </script>
</head>
<body>

    <!-- Header -->
    <div class="eper-navbar">
        <div class="eper-logo" style="background: #ffffff; padding: 5px 10px; border-radius: 4px; display: flex; align-items: center; margin-bottom: 8px;">
            <img src="https://s3-sa-east-1.amazonaws.com/images.anymarket.com.br/22449504./6ECFF29E478B05B93B2973D56786FCFE/standard_resolution.jpg" alt="Marca Seleta Logo" style="height: 48px; width: auto;">
        </div>
    </div>

    <!-- Subheader -->
    <div class="eper-subheader">
        <span style="padding-left: 20px;"><i class="bi bi-car-front"></i> &raquo; BUSCA DE COMPATIBILIDADE</span>
    </div>

    <div class="container-fluid px-4">
        
        <!-- Search Area -->
        <div class="search-container" style="flex-direction: column; gap: 10px;">
            <form method="POST" class="w-100 d-flex flex-column align-items-center">
                <div class="bulk-search-box">
                    <div class="row g-3 mb-3">
                        <div class="col-md-8">
                            <label for="parts_bulk" class="form-label text-muted small fw-bold mb-1" style="font-size: 0.75rem;">CÓDIGOS DAS PEÇAS (uma por linha)</label>
                            <textarea class="form-control" id="parts_bulk" name="parts_bulk" rows="8" placeholder="K55111314AC	Reservatório&#10;K55111354AA	Tampa&#10;K05168128AB	Barra estabilizadora&#10;K68073033AC	Haste da barra">{{ parts_bulk }}</textarea>
                            <div class="bulk-hint">Cole vários códigos de uma vez. Use tab, ponto-e-vírgula ou espaço para incluir a descrição opcional.</div>
                        </div>
                        <div class="col-md-4">
                            <label for="vc" class="form-label text-muted small fw-bold mb-1" style="font-size: 0.75rem;">CHASSI (Opcional)</label>
                            <input type="text" class="form-control mb-3" id="vc" name="vc" value="{{ vc }}" placeholder="Ex: 9BWAA01J754038498">
                            <label for="vehicle_label" class="form-label text-muted small fw-bold mb-1" style="font-size: 0.75rem;">VEÍCULO (Opcional)</label>
                            <input type="text" class="form-control" id="vehicle_label" name="vehicle_label" value="{{ vehicle_label }}" placeholder="Ex: FIAT 500 (2010–2018)">
                            <div class="bulk-hint">Título do relatório. Se vazio, será inferido dos resultados.</div>
                        </div>
                    </div>
                    <div class="d-flex justify-content-end">
                        <button type="submit" class="btn btn-search"><i class="bi bi-search me-1"></i> Consultar Compatibilidade</button>
                    </div>
                </div>
            </form>
            <form method="POST" class="w-100 d-flex flex-column align-items-center">
                <div class="d-flex w-100" style="max-width: 900px; margin-bottom: 5px;">
                    <div style="padding-left: 5px;"><label for="name_query" class="form-label text-muted small fw-bold mb-0" style="font-size: 0.75rem;">BUSCAR POR NOME (FiatPecas.com.br)</label></div>
                </div>
                <div class="search-box" style="max-width: 900px;">
                    <input type="text" class="form-control" id="name_query" name="name_query" value="{{ name_query }}" placeholder="Ex: Lâmpada pingo d'água w5w">
                    <button type="submit" class="btn btn-search"><i class="bi bi-search"></i></button>
                </div>
            </form>
        </div>

        {% if request.args.get('refreshed') == 'success' %}
        <div class="alert alert-success mx-auto mt-3" style="max-width: 900px;" role="alert">
            <i class="bi bi-check-circle-fill me-2"></i> Sessão renovada com sucesso!
        </div>
        {% elif request.args.get('refreshed') == 'error' %}
        <div class="alert alert-danger mx-auto mt-3" style="max-width: 900px;" role="alert">
            <i class="bi bi-exclamation-triangle-fill me-2"></i> Falha ao renovar: {{ request.args.get('errmsg') }}
        </div>
        {% endif %}

        {% if error %}
        <div class="alert alert-danger mx-auto" style="max-width: 900px;" role="alert">
            <i class="bi bi-exclamation-triangle-fill me-2"></i> {{ error | safe }}
        </div>
        {% endif %}

        {% if batch_results %}
        <div class="mx-auto" style="max-width: 1280px;">
            <div class="eper-panel mt-2">

                <!-- Cabeçalho do painel -->
                <div class="eper-panel-header d-flex justify-content-between align-items-center">
                    <span><i class="bi bi-clipboard-data me-1"></i> Resultado de Compatibilidade</span>
                    <button type="button" class="btn-copy-results" onclick="copyCompatResults(this)"><i class="bi bi-clipboard"></i> Copiar relatório</button>
                </div>

                <!-- Faixa de resumo com badges e barra de progresso -->
                <div class="result-summary-strip">
                    <span style="font-weight:700;color:#005fa9;font-size:0.92rem;">{{ report_title }}</span>
                    <div class="d-flex gap-2 ms-auto flex-wrap">
                        <span class="stat-badge total"><i class="bi bi-list-ul me-1"></i>{{ batch_results|length }} peças</span>
                        <span class="stat-badge found"><i class="bi bi-check-circle me-1"></i>{{ found_count }} encontradas</span>
                        {% if not_found_count > 0 %}
                        <span class="stat-badge not-found"><i class="bi bi-x-circle me-1"></i>{{ not_found_count }} sem resultado</span>
                        {% endif %}
                    </div>
                </div>
                <div class="found-progress-wrap">
                    <div class="found-progress-bar" style="width:{{ (found_count / batch_results|length * 100)|round|int }}%"></div>
                </div>

                <!-- Barra de filtros -->
                <div class="compat-filter-bar">
                    <i class="bi bi-search text-muted" style="font-size:0.82rem;"></i>
                    <input type="text" id="compat-filter" class="compat-filter-input"
                           placeholder="Filtrar por código, descrição ou modelo..."
                           oninput="filterCompatTable()">
                    <button id="toggle-errors-btn" class="toggle-errors-btn" onclick="toggleErrorsOnly()">
                        <i class="bi bi-check-circle me-1"></i> Apenas sem erro
                    </button>
                    <span id="filter-row-count" style="font-size:0.75rem;color:#888;margin-left:auto;"></span>
                </div>

                <!-- Tabela com cabeçalho fixo e scroll vertical -->
                <div class="table-scroll-wrap">
                    <table class="table compat-table mb-0" id="compat-table">
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

                <!-- Rodapé de resumo -->
                <div class="compat-summary">
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

            <!-- Texto oculto para cópia (formato tabular estruturado) -->
            <pre id="compat-results-text" style="display:none;">Resultado de Compatibilidade — {{ report_title }}

Peça	Descrição	Marca	Modelo	Tabelas	Grupo	Peça Catálogo
{% for row in batch_results %}{% if row.compatibility_details %}{% for d in row.compatibility_details %}{{ row.code }}	{{ row.description or '—' }}	{{ d.brand or '—' }}	{{ d.model }}	{{ d.tables or '—' }}	{{ d.table_desc or '—' }}	{{ d.part_dsc or '—' }}
{% endfor %}{% else %}{{ row.code }}	{{ row.description or '—' }}	—	{{ row.model or '—' }}	—	—	{{ row.result }}
{% endif %}{% endfor %}
{{ found_count }} peça{{ 's' if found_count != 1 else '' }} com aplicação / {{ not_found_count }} sem resultado no catálogo{% if not_found_codes %} ({{ not_found_codes | join(', ') }}){% endif %}.</pre>
        </div>
        {% endif %}

        {% if products %}
        <!-- FiatPecas Products Panel -->
        <div class="mx-auto" style="max-width: 1200px;">
            <div class="eper-panel mt-4">
                <div class="eper-panel-header"><i class="bi bi-shop me-1"></i> Produtos Encontrados no FiatPecas.com.br</div>
                <div class="p-3">
                    <div class="row g-3">
                        {% for p in products %}
                        <div class="col-6 col-sm-4 col-md-3 col-lg-2">
                            <div class="product-card">
                                <div class="product-card-img-wrap">
                                    {% if p.image %}
                                    <img src="{{ p.image }}" alt="{{ p.name }}" loading="lazy">
                                    {% else %}
                                    <i class="bi bi-image text-muted" style="font-size:2rem;"></i>
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
                        </div>
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        {% if not products and name_query and not error %}
        <div class="mx-auto" style="max-width: 1200px;">
            <div class="eper-panel mt-4">
                <div class="eper-panel-header"><i class="bi bi-shop me-1"></i> Produtos Encontrados no FiatPecas.com.br</div>
                <div class="no-results-msg">
                    <i class="bi bi-search" style="font-size:1.5rem; color:#aaa; display:block; margin-bottom:8px;"></i>
                    Desculpe, sua busca por <strong>"{{ name_query if name_query else part }}"</strong> não retornou nenhum resultado.
                </div>
            </div>
        </div>
        {% endif %}

    </div>

    <!-- Footer com Versão -->
    <div style="text-align: center; padding: 20px; color: #888; font-size: 0.7rem; margin-top: 40px; border-top: 1px solid #ddd;">
        Versão: 1.3.0 | ÚLTIMA ATUALIZAÇÃO NO SERVIDOR: 23/06/2026 15:00
    </div>

    <!-- Auth Status Banner (fixed bottom, shown by JS while Selenium login runs in background) -->
    <div id="auth-status-banner" style="display:none;position:fixed;bottom:0;left:0;right:0;z-index:1050;background:#cfe2ff;border-top:2px solid #9ec5fe;padding:10px 20px;">
        <div class="d-flex align-items-center" style="max-width:960px;margin:0 auto;gap:12px;">
            <span class="spinner-border spinner-border-sm flex-shrink-0" id="auth-banner-spinner" style="color:#0a58ca;"></span>
            <span id="auth-banner-msg" style="font-size:0.85rem;color:#084298;flex:1;">Autenticação em andamento. A busca estará disponível em breve...</span>
            <a href="/compatibilidade/login" style="background:#005fa9;color:white;border-radius:0;font-size:0.78rem;padding:4px 12px;text-decoration:none;white-space:nowrap;flex-shrink:0;">Ver status</a>
        </div>
    </div>

    <script>
    (function() {
        var banner = document.getElementById('auth-status-banner');
        var msg    = document.getElementById('auth-banner-msg');
        var spin   = document.getElementById('auth-banner-spinner');

        function showError(text) {
            if (!banner) return;
            banner.style.background = '#f8d7da';
            banner.style.borderTopColor = '#f5c2c7';
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
                                banner.style.background = '#d1e7dd';
                                banner.style.borderTopColor = '#a3cfbb';
                                if (spin) spin.style.display = 'none';
                                if (msg) msg.textContent = 'Sessão autenticada! Você já pode realizar buscas.';
                                setTimeout(function() { banner.style.display = 'none'; }, 4000);
                            }
                        } else if (d.state === 'error') {
                            showError('Falha na autenticação. <a href="/compatibilidade/login" style="color:#842029;font-weight:600;">Clique aqui para renovar a sessão.</a>');
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
                    showError('Sessão não autenticada. <a href="/compatibilidade/login" style="color:#842029;font-weight:600;">Clique aqui para iniciar sessão.</a>');
                }
            })
            .catch(function() {});
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
