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
from flask import Flask, request, redirect, url_for
from curl_cffi import requests as cffi_requests
import fiat_parts_tool

app = Flask(__name__)

FIATPECAS_IMPERSONATES = ["chrome124", "safari17_0", "chrome120", "edge101"]
FIATPECAS_CACHE_TTL = 300
_fiatpecas_winning_profile = None
_fiatpecas_cache: dict[str, tuple[float, list]] = {}
_fiatpecas_cache_lock = threading.Lock()

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
            <i class="bi bi-exclamation-triangle-fill me-2"></i> {{ error }}
        </div>
        {% endif %}

        {% if batch_results %}
        <div class="mx-auto" style="max-width: 1200px;">
            <div class="eper-panel mt-2">
                <div class="eper-panel-header d-flex justify-content-between align-items-center">
                    <span>Resultado de Compatibilidade</span>
                    <button type="button" class="btn-copy-results" onclick="copyCompatResults(this)"><i class="bi bi-clipboard"></i> Copiar relatório</button>
                </div>
                <div class="report-title">Resultado de Compatibilidade — {{ report_title }}</div>
                <div class="eper-panel-body">
                    <table class="table compat-table mb-0">
                        <thead>
                            <tr>
                                <th class="col-part">Peça</th>
                                <th class="col-desc">Descrição</th>
                                <th class="col-result">Resultado</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in batch_results %}
                            <tr>
                                <td class="col-part">{{ row.code }}</td>
                                <td class="col-desc">{{ row.description or '—' }}</td>
                                <td class="col-result">{{ row.result }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    <div class="compat-summary">
                        <span class="count-found">{{ found_count }} peça{{ 's' if found_count != 1 else '' }} com aplicação</span>
                        /
                        <span class="count-not-found">{{ not_found_count }} sem resultado no catálogo</span>
                        {% if not_found_codes %}
                        ({{ not_found_codes | join(', ') }}).
                        {% else %}
                        .
                        {% endif %}
                    </div>
                </div>
            </div>
            <pre id="compat-results-text" style="display:none;">Resultado de Compatibilidade — {{ report_title }}

Peça	Descrição	Resultado
{% for row in batch_results %}{{ row.code }}	{{ row.description or '—' }}	{{ row.result }}
{% endfor %}
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
        Versão: 1.2.0 | ÚLTIMA ATUALIZAÇÃO NO SERVIDOR: 15/06/2026 11:30
    </div>

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
    """Background task: tenta login inicial após 10s, depois renova a cada 6 horas."""
    # Primeiro login: espera 10s para o Flask já estar respondendo
    time.sleep(10)
    try:
        print("[BACKGROUND] Tentando login inicial...")
        fiat_parts_tool.get_cookies(headless=True)
        print("[BACKGROUND] Login inicial bem-sucedido!")
    except Exception as e:
        print(f"[BACKGROUND] Login inicial falhou: {e}")
        print("[BACKGROUND] Cookies serao obtidos na primeira busca do usuario.")

    # Renovação periódica a cada 6 horas
    while True:
        time.sleep(6 * 60 * 60)
        try:
            print("[BACKGROUND] Iniciando renovação automática de cookies...")
            fiat_parts_tool.get_cookies(force_login=True, headless=True)
            print("[BACKGROUND] Cookies renovados com sucesso!")
        except Exception as e:
            print(f"[BACKGROUND] Erro ao renovar cookies: {e}")

@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        print("[WEB] Renovação manual de sessão solicitada...")
        fiat_parts_tool.get_cookies(force_login=True, headless=True)
        # We pass a success flag in the URL parameter via redirect
        return redirect(url_for('index', refreshed='success'))
    except Exception as e:
        print(f"[WEB] Falha na renovacao manual: {e}")
        return redirect(url_for('index', refreshed='error', errmsg=str(e)[:100]))

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
            else:
                chassis = vc if vc else None
                print(f"WEB: Consultando {len(entries)} peca(s) em lote" + (f" para chassi {chassis}" if chassis else ""))
                batch_results = fiat_parts_tool.query_batch(entries, chassis, headless=True)

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
        print(f"[INFO] Waitress em http://{host}:{port} ({threads} threads)")
        serve(app, host=host, port=port, threads=threads)
    else:
        print(f"[INFO] Flask dev em http://{host}:{port} (threaded)")
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
