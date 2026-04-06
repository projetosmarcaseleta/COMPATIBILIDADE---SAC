"""
sync_cookies.py — Executa na MÁQUINA LOCAL (não no servidor)
============================================================
Faz login no Fiat Reparador usando o IP local (não bloqueado pela Stellantis)
e envia o arquivo de cookies para o servidor Hostinger via SCP.

Uso:
    python sync_cookies.py

Configure as variáveis SERVER_USER, SERVER_IP e SERVER_PATH abaixo.
Recomendado: agendar via Agendador de Tarefas do Windows a cada 6 horas.
"""

import subprocess
import sys
from pathlib import Path

# ── Configuração do servidor ──────────────────────────────────────────────────
SERVER_USER = "root"
SERVER_IP   = "195.200.0.29"
SERVER_PATH = "/root/projetos/COMPATIBILIDADE---SAC/.fiat_cookies.pkl"
# ─────────────────────────────────────────────────────────────────────────────

COOKIES_FILE = Path(__file__).parent / ".fiat_cookies.pkl"

def main():
    print("🔑 Realizando login local no Fiat Reparador...")
    import fiat_parts_tool
    try:
        cookies = fiat_parts_tool.get_cookies(force_login=True, headless=True)
        print(f"✅ Login OK! {len(cookies)} cookies obtidos.")
    except Exception as e:
        print(f"❌ Falha no login: {e}")
        sys.exit(1)

    if not COOKIES_FILE.exists():
        print("❌ Arquivo de cookies não encontrado após login.")
        sys.exit(1)

    print(f"📤 Enviando cookies para {SERVER_USER}@{SERVER_IP}...")
    scp_cmd = [
        "scp",
        str(COOKIES_FILE),
        f"{SERVER_USER}@{SERVER_IP}:{SERVER_PATH}"
    ]
    result = subprocess.run(scp_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print("✅ Cookies sincronizados com sucesso!")
    else:
        print(f"❌ Falha no SCP: {result.stderr}")
        print("💡 Verifique se o SSH está configurado com chave sem senha para o servidor.")
        sys.exit(1)

if __name__ == "__main__":
    main()
