import time
import threading
from flask import Flask, request, render_template_string
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
    </style>
</head>
<body>

    <!-- Header -->
    <div class="eper-navbar">
        <div class="eper-logo" style="background: #f8f9fa; padding: 5px 14px; border-radius: 4px; display: flex; align-items: center; margin-bottom: 8px;">
            <i class="bi bi-gem" style="color: #1a56db; font-size: 1.35rem; margin-right: 7px;"></i>
            <span style="font-family: Arial, sans-serif; font-size: 1.25rem; letter-spacing: -0.5px; text-transform: lowercase; color: #1a1a2e;">marca</span><span style="font-family: Arial, sans-serif; font-size: 1.25rem; font-weight: 900; letter-spacing: -0.5px; text-transform: lowercase; color: #1a1a2e;">seleta</span>
        </div>
    </div>

    <!-- Subheader -->
    <div class="eper-subheader">
        <div class="eper-btn-back">
            <i class="bi bi-chevron-left"></i>
        </div>
        <span><i class="bi bi-car-front"></i> &raquo; BUSCA PARTE POR CÓDIGO</span>
    </div>

    <div class="container-fluid px-4">
        
        <!-- Search Area -->
        <div class="search-container">
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
        </div>

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
        
    </div>

</body>
</html>
"""

def refresh_session_loop():
    """Background task to force login/cookie refresh every 25 mins to keep session valid forever."""
    while True:
        try:
            print("[BACKGROUND] Iniciando renovação da sessão (25 min passados)...")
            fiat_parts_tool.get_cookies(force_login=True, headless=True)
            print("[BACKGROUND] ✅ Sessão renovada com sucesso!")
        except Exception as e:
            print(f"[BACKGROUND] ❌ Erro ao renovar sessão no background: {e}")
        
        # Aguarda 25 minutos para renovar de novo (cookie dura 30m na API)
        time.sleep(25 * 60)

@app.route("/", methods=["GET", "POST"])
def index():
    part = ""
    vc = ""
    result_text = None
    error_text = None
    
    if request.method == "POST":
        part = request.form.get("part", "").strip()
        vc = request.form.get("vc", "").strip()
        
        if not part:
            error_text = "O código da peça é obrigatório."
        else:
            try:
                chassis = vc if vc else None
                print(f"WEB: Consultando peça {part}" + (f" para chassi {chassis}" if chassis else ""))
                
                # A função query_with_retry já lê os cookies, faz request e trata erros/re-login.
                data = fiat_parts_tool.query_with_retry(part, chassis, headless=True)
                
                if data is None:
                    error_text = "A API não retornou dados ou a autenticação final falhou."
                else:
                    result_text = fiat_parts_tool.format_applicability(data, part)
                
            except Exception as e:
                error_text = str(e)

    return render_template_string(HTML_TEMPLATE, part=part, vc=vc, result=result_text, error=error_text)

if __name__ == "__main__":
    print("⚙️ Verificando cookies iniciais de acesso...")
    try:
        fiat_parts_tool.get_cookies(headless=True)
        print("✅ Autenticação pronta.")
    except Exception as e:
        print(f"⚠️ Atenção: Falha no login inicial, tentará ao buscar a primeira peça: {e}")
        
    print("⚙️ Iniciando daemon de background para renovar a sessão automaticamente a cada 25m...")
    bg_thread = threading.Thread(target=refresh_session_loop, daemon=True)
    bg_thread.start()
    
    print("🚀 Servidor Web iniciado na porta 5000!")
    app.run(host="0.0.0.0", port=5000)
