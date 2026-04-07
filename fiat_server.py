import time
import threading
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, redirect, url_for
from curl_cffi import requests as cffi_requests
import fiat_parts_tool

app = Flask(__name__)

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
        <span style="padding-left: 20px;"><i class="bi bi-car-front"></i> &raquo; BUSCA PARTE POR CÓDIGO</span>
    </div>

    <div class="container-fluid px-4">
        
        <!-- Search Area -->
        <div class="search-container" style="flex-direction: column; gap: 10px;">
            <form method="POST" class="w-100 d-flex flex-column align-items-center">
                <div class="d-flex w-100" style="max-width: 700px; margin-bottom: 5px;">
                    <div style="width: 40%; padding-left: 5px;"><label for="part" class="form-label text-muted small fw-bold mb-0" style="font-size: 0.75rem;">CÓDIGO DA PEÇA</label></div>
                    <div style="width: 60%; padding-left: 15px;"><label for="vc" class="form-label text-muted small fw-bold mb-0" style="font-size: 0.75rem;">CHASSI (Opcional)</label></div>
                </div>
                <div class="search-box">
                    <input type="text" class="form-control" style="width: 40%; border-right: 1px solid #eee;" id="part" name="part" value="{{ part }}" required placeholder="Ex: 14144190">
                    <input type="text" class="form-control" style="width: 60%;" id="vc" name="vc" value="{{ vc }}" placeholder="Ex: 9BWAA01J754038498">
                    <button type="submit" class="btn btn-search"><i class="bi bi-search"></i></button>
                </div>
            </form>
            <form method="POST" class="w-100 d-flex flex-column align-items-center">
                <div class="d-flex w-100" style="max-width: 700px; margin-bottom: 5px;">
                    <div style="padding-left: 5px;"><label for="name_query" class="form-label text-muted small fw-bold mb-0" style="font-size: 0.75rem;">BUSCAR POR NOME (FiatPecas.com.br)</label></div>
                </div>
                <div class="search-box">
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

        {% if result %}
        <div class="mx-auto" style="max-width: 1200px;">
            
            <!-- Details Panel -->
            <div class="eper-panel">
                <div class="eper-panel-header">Detalhes</div>
                <div class="eper-panel-title">
                    <i class="bi bi-cart-plus"></i> Código da Peça: {{ part }}
                </div>
                <div class="eper-panel-body">
                    {% if "Nenhuma aplicação" in result %}
                    <div class="p-4 text-center text-muted">
                        Nenhuma aplicação encontrada para a peça selecionada no catálogo.
                    </div>
                    {% else %}
                    <div class="data-grid bg-light-blue">
                        <div class="data-row">
                            <div class="data-label">CHASSI FORNECIDO:</div>
                            <div class="data-value">{{ vc if vc else 'NENHUM (Busca Global)' }}</div>
                        </div>
                        <div class="data-row">
                            <div class="data-label">DISPONIBILIDADE:</div>
                            <div class="data-value">PRODUTO LISTADO NO CATÁLOGO</div>
                        </div>
                    </div>
                    {% endif %}
                </div>
            </div>

            <!-- Applicability Panel -->
            <div class="eper-panel mt-4">
                <div class="eper-panel-header">Lista de Aplicabilidade</div>
                <div class="eper-panel-body">
                    <pre class="raw-output"><code>{{ result }}</code></pre>
                </div>
            </div>

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

        {% if not products and (part or name_query) and not error %}
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
        Versão: 1.0.4 | ÚLTIMA ATUALIZAÇÃO NO SERVIDOR: 30/03/2026 10:15
    </div>

</body>
</html>
"""

def search_fiatpecas(part_code):
    """Fetch and parse product listings from fiatpecas.com.br for a given part code."""
    url = f"https://fiatpecas.com.br/search/?q={part_code}"
    
    resp = None
    # Perfis para rotacionar caso a VPS seja bloqueada em algum deles
    impersonates = ["chrome124", "safari17_0", "chrome120", "edge101"]
    
    for imp in impersonates:
        try:
            # curl_cffi imitates Browser TLS perfectly to bypass Cloudflare 403
            resp = cffi_requests.get(url, impersonate=imp, timeout=15)
            if resp.status_code == 200:
                print(f"[FIATPECAS] Sucesso ao usar a técnica impersonate='{imp}'")
                break
            else:
                print(f"[FIATPECAS] Resposta não-200 com '{imp}': {resp.status_code}")
        except Exception as e:
            print(f"[FIATPECAS] Erro na requisição (curl_cffi, {imp}): {e}")

    # Adiciona fallback para cloudscraper se o curl_cffi falhar em todos
    if not resp or resp.status_code != 200:
        print("[FIATPECAS] Tentando fallback com Cloudscraper...")
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            resp = scraper.get(url, timeout=15)
            if resp.status_code == 200:
                print("[FIATPECAS] Sucesso com Cloudscraper!")
            else:
                print(f"[FIATPECAS] Resposta não-200 no Cloudscraper: {resp.status_code}")
        except Exception as e:
            print(f"[FIATPECAS] Erro com Cloudscraper: {e}")

    if not resp or resp.status_code != 200:
        print(f"[FIATPECAS] Falha definitiva. Status code: {resp.status_code if resp else 'N/A'}")
        return []


    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select(".js-item-product")
    products = []

    for item in items:
        try:
            # URL
            link_tag = item.select_one("a[href]")
            product_url = link_tag["href"] if link_tag else "#"

            # Name
            name_tag = item.select_one(".js-item-name")
            name = name_tag.get_text(strip=True) if name_tag else ""

            # Image (lazy-loaded via data-srcset)
            img_tag = item.select_one("img.js-item-image")
            image = ""
            if img_tag:
                srcset = img_tag.get("data-srcset", "") or img_tag.get("srcset", "") or img_tag.get("src", "")
                if srcset:
                    # Take first URL from srcset (format: "url 1x, url 2x" or just "url")
                    image = srcset.split(",")[0].strip().split(" ")[0]

            # Prices and installments from data-variants JSON
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

    print(f"[FIATPECAS] {len(products)} produto(s) encontrado(s) para '{part_code}'")
    return products


def refresh_session_loop():
    """Background task: tenta login inicial após 10s, depois renova a cada 6 horas."""
    # Primeiro login: espera 10s para o Flask já estar respondendo
    time.sleep(10)
    try:
        print("[BACKGROUND] Tentando login inicial...")
        fiat_parts_tool.get_cookies(headless=True)
        print("[BACKGROUND] ✅ Login inicial bem-sucedido!")
    except Exception as e:
        print(f"[BACKGROUND] ⚠️ Login inicial falhou: {e}")
        print("[BACKGROUND] ⚠️ Cookies serão obtidos na primeira busca do usuário.")

    # Renovação periódica a cada 6 horas
    while True:
        time.sleep(6 * 60 * 60)
        try:
            print("[BACKGROUND] Iniciando renovação automática de cookies...")
            fiat_parts_tool.get_cookies(force_login=True, headless=True)
            print("[BACKGROUND] ✅ Cookies renovados com sucesso!")
        except Exception as e:
            print(f"[BACKGROUND] ❌ Erro ao renovar cookies: {e}")

@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        print("[WEB] Renovação manual de sessão solicitada...")
        fiat_parts_tool.get_cookies(force_login=True, headless=True)
        # We pass a success flag in the URL parameter via redirect
        return redirect(url_for('index', refreshed='success'))
    except Exception as e:
        print(f"[WEB] ❌ Falha na renovação manual: {e}")
        return redirect(url_for('index', refreshed='error', errmsg=str(e)[:100]))

@app.route("/", methods=["GET", "POST"])
def index():
    part = ""
    vc = ""
    name_query = ""
    result_text = None
    error_text = None
    products = []

    if request.method == "POST":
        part = request.form.get("part", "").strip()
        vc = request.form.get("vc", "").strip()
        name_query = request.form.get("name_query", "").strip()

        if name_query and not part:
            # Name-only search: only hits FiatPecas
            print(f"WEB: Buscando por nome '{name_query}' no FiatPecas")
            products = search_fiatpecas(name_query)
        elif part:
            try:
                chassis = vc if vc else None
                print(f"WEB: Consultando peça {part}" + (f" para chassi {chassis}" if chassis else ""))

                # Usa cookies em cache ou faz login automático se necessário
                data = fiat_parts_tool.query_with_retry(part, chassis, headless=True)

                if data is None:
                    error_text = "A API não retornou dados ou a autenticação falhou."
                else:
                    result_text = fiat_parts_tool.format_applicability(data, part)

            except Exception as e:
                error_text = str(e)

            # Always search FiatPecas by part code alongside ePER
            products = search_fiatpecas(part)
        else:
            error_text = "Informe um código de peça ou um nome para buscar."

    return render_template_string(HTML_TEMPLATE, part=part, vc=vc, name_query=name_query, result=result_text, error=error_text, products=products)

if __name__ == "__main__":
    # Login acontece no background para não bloquear o Flask
    print("⚙️ Iniciando daemon de background para login e renovação automática...")
    bg_thread = threading.Thread(target=refresh_session_loop, daemon=True)
    bg_thread.start()
    
    print("🚀 Servidor Web iniciado na porta 5002!")
    app.run(host="0.0.0.0", port=5002)
