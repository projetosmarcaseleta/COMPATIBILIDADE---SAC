"""
Fiat ePER Parts Applicability Tool
===================================
Automates login to reparador.fiat.com.br via Playwright,
extracts session cookies, and queries the ePER parts API.

Usage:
    python fiat_parts_tool.py --part 14144190
    python fiat_parts_tool.py --part 14144190 --vc 9BWAA01J754038498
    python fiat_parts_tool.py --part 14144190 --raw
"""

import argparse
import json
import sys
import time
import pickle
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


# ── Configuration ──────────────────────────────────────────────────────────────

LOGIN_URL = "https://reparador.fiat.com.br/"
EPER_URL = "https://eper-ltm.parts.fiat.com/eConnect/parts/search?vc=9BD358A7HLYK38481&p=7091970"
API_BASE = "https://eper-ltm.parts.fiat.com/eConnect/api/eper"
COOKIES_FILE = Path(__file__).parent / ".fiat_cookies.pkl"
DEBUG_DIR = Path(__file__).parent / "debug_screenshots"

EMAIL = "marcaseleta.db1@gmail.com"
PASSWORD = "Seleta2025@"

HEADERS = {
    "accept": "application/json",
    "accept-language": "pt-BR,pt;q=0.9",
    "cache-control": "no-cache",
    "x-requested-with": "XMLHttpRequest",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
}


# ── Browser Login (Playwright) ─────────────────────────────────────────────────

def login_and_get_cookies(headless: bool = True) -> dict:
    """
    Perform browser login using Playwright and return session cookies.
    Playwright uses native browser input events that work with modern JS frameworks.
    """
    print("🔑 Iniciando login no Fiat Reparador...")
    DEBUG_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        # No VPS, deixamos o Playwright usar o Chromium nativo (sem force channel="chrome")
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=HEADERS["user-agent"],
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            # Step 1: Navigate to site
            page.goto(LOGIN_URL, timeout=60000, wait_until="networkidle")
            page.wait_for_timeout(5000)  # Wait for JS to load
            page.screenshot(path=str(DEBUG_DIR / "01_landing.png"))

            # Close cookie banner or generic modals if present
            print("  → Verificando banners de cookies/popups...")
            try:
                # Tenta o ID específico da Fiat ou seletores genéricos
                cookie_selectors = ["#onetrust-accept-btn-handler", "button:has-text('Aceitar')", "button:has-text('Prosseguir')"]
                for selector in cookie_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            print(f"  ✓ Elemento {selector} fechado.")
                            page.wait_for_timeout(1000)
                    except Exception:
                        continue
            except Exception:
                pass

            # Step 2: Click "Entre ou Cadastre-se"
            print("  → Abrindo modal de login...")
            login_selectors = [
                "a.login-link",
                "a:has-text('Entre ou Cadastre-se')",
                "button:has-text('Entre ou Cadastre-se')",
                "[class*='login']",
            ]
            clicked_login = False
            for sel in login_selectors:
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    page.click(sel)
                    clicked_login = True
                    print(f"  ✓ Botão de login clicado via seletor: {sel}")
                    break
                except Exception:
                    continue
            if not clicked_login:
                page.screenshot(path=str(DEBUG_DIR / "02_login_not_found.png"))
                raise Exception("Não foi possível encontrar o botão de login na página.")
            page.wait_for_timeout(3000)
            page.screenshot(path=str(DEBUG_DIR / "02_modal_open.png"))

            # Step 3: Click "ENTRAR COM E-MAIL"
            print("  → Selecionando login por e-mail...")
            page.click("a.btn-email", timeout=10000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(DEBUG_DIR / "03_email_form.png"))

            # Step 4: Enter email
            print(f"  → Digitando e-mail: {EMAIL}")
            email_input = page.wait_for_selector("input.hub-input-field", timeout=10000)
            email_input.click()
            page.wait_for_timeout(300)
            # Type slowly to trigger input events properly
            email_input.fill(EMAIL)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(DEBUG_DIR / "04_email_typed.png"))

            # Click CONTINUAR (email step)
            # There are 3 a.hub-button elements — target the visible one with text
            print("  → Clicando CONTINUAR...")
            page.locator("a.hub-button", has_text="CONTINUAR").first.click(timeout=10000)
            print("  ✓ CONTINUAR clicado")

            # Wait for password screen
            print("  → Aguardando tela de senha...")
            page.wait_for_timeout(5000)
            page.screenshot(path=str(DEBUG_DIR / "05_after_continuar.png"))

            # Step 5: Enter password
            try:
                password_input = page.wait_for_selector("input#password", timeout=20000)
            except Exception:
                # If password field didn't appear, try clicking CONTINUAR again
                print("  ⚠ Tela de senha não apareceu. Tentando novamente...")
                page.screenshot(path=str(DEBUG_DIR / "05b_retry.png"))
                
                # Try closing any survey popups
                try:
                    page.click("button:text('Cancelar')", timeout=2000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
                
                # Clear and re-type email, then click CONTINUAR again
                try:
                    email_field = page.query_selector("input.hub-input-field")
                    if email_field:
                        email_field.click()
                        email_field.fill("")
                        page.wait_for_timeout(500)
                        email_field.type(EMAIL, delay=50)  # Type character by character
                        page.wait_for_timeout(2000)
                        page.locator("a.hub-button", has_text="CONTINUAR").first.click(timeout=5000)
                        print("  ✓ CONTINUAR clicado (2a tentativa)")
                        page.wait_for_timeout(8000)
                        page.screenshot(path=str(DEBUG_DIR / "05c_after_retry.png"))
                except Exception as e:
                    print(f"  ⚠ Retry falhou: {e}")
                
                password_input = page.wait_for_selector("input#password", timeout=20000)
            
            print("  → Digitando senha...")
            password_input.click()
            page.wait_for_timeout(300)
            password_input.fill(PASSWORD)
            page.wait_for_timeout(1000)
            page.screenshot(path=str(DEBUG_DIR / "06_password_typed.png"))

            # Click CONTINUAR (password step)
            print("  → Clicando CONTINUAR...")
            page.locator("a.hub-button", has_text="CONTINUAR").first.click(timeout=10000)
            print("  → Aguardando autenticação...")
            page.wait_for_timeout(10000)
            page.screenshot(path=str(DEBUG_DIR / "07_after_login.png"))

            # Verify login success
            try:
                page.wait_for_selector("a.badge-logout-button", timeout=10000)
                print("  ✅ Login confirmado!")
            except Exception:
                print("  ⚠ Não foi possível confirmar o login, tentando continuar...")
                page.screenshot(path=str(DEBUG_DIR / "08_login_not_confirmed.png"))

            # Step 6: Navigate to ePER to get the right domain cookies
            print("  → Acessando o Catálogo de Peças...")
            try:
                # Close the new bottom cookie banner
                try:
                    page.locator("text='FECHAR'").first.click(timeout=3000)
                except Exception:
                    pass
                
                # Scroll down so the catalog card elements become visible
                page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                page.wait_for_timeout(1000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                
                # Use robust JS to click the catalog link
                clicked = page.evaluate("""() => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
                    let node;
                    while (node = walker.nextNode()) {
                        if (node.nodeValue.includes('agilizar o tempo')) {
                            let el = node.parentElement;
                            
                            // Highlight the element for debugging
                            el.style.border = '5px solid red';
                            el.style.backgroundColor = 'yellow';
                            
                            while (el && el !== document.body) {
                                if (el.tagName === 'A' || el.tagName === 'BUTTON') {
                                    el.style.border = '5px solid blue';
                                    window.elementToClick = el;
                                    return true;
                                }
                                el = el.parentElement;
                            }
                            window.elementToClick = node.parentElement;
                            return true;
                        }
                    }
                    return false;
                }""")
                
                if clicked:
                    page.screenshot(path=str(DEBUG_DIR / "08b_found_card.png"))
                    
                    # Now click it
                    page.evaluate("if(window.elementToClick) window.elementToClick.click();")
                    print("  ✓ CATÁLOGO DE PEÇAS clicado via JS")
                    # Wait for the new tab to open
                    try:
                        new_page = context.wait_for_event('page', timeout=10000)
                        eper_page = new_page
                        print("  ✓ Nova aba do catálogo aberta")
                    except Exception:
                        print("  ⚠ Nenhuma nova aba detectada. Prosseguindo com a aba atual.")
                        eper_page = page
                else:
                    raise Exception("Texto 'agilizar o tempo' não encontrado na página via JS!")
                    
            except Exception as e:
                print(f"  ⚠ Falha ao abrir catálogo por clique: {e}")
                eper_page = page
            
            print("  → Aguardando redirecionamentos e cookies do ePER...")
            
            # Tenta esperar especificamente pelo domínio do ePER nos cookies
            start_time = time.time()
            found_cookie = False
            while time.time() - start_time < 45:  # Espera até 45 segundos no VPS
                all_cookies = context.cookies()
                cookies_dict = {c["name"]: c["value"] for c in all_cookies}
                if ".AspNetCore.Cookies" in cookies_dict:
                    found_cookie = True
                    break
                
                # Se ainda não achou, e estivermos parado na home, tenta navegar direto
                if time.time() - start_time > 20 and (eper_page.url == LOGIN_URL or eper_page.url == "about:blank"):
                    print("  ⚠ URL não mudou adequadamente. Tentando navegação direta para o ePER...")
                    try:
                        eper_page.goto(EPER_URL, timeout=30000)
                    except Exception:
                        pass
                
                eper_page.wait_for_timeout(3000)

            all_cookies = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in all_cookies}
            domains = set(c["domain"] for c in all_cookies)
            
            print(f"  → Domínios nos cookies: {list(domains)}")

            if not found_cookie:
                print("  ❌ Falha no login - cookie de sessão .AspNetCore.Cookies não encontrado.")
                print(f"     URL da aba ePER: {eper_page.url}")
                print(f"     Páginas abertas no contexto: {[p.url for p in context.pages]}")
                print(f"     Cookies obtidos (nomes): {list(cookies_dict.keys())}")
                
                if eper_page.url == LOGIN_URL:
                     print("  ⚠ O navegador não saiu da página inicial. Provavelmente o clique no catálogo foi bloqueado.")
                
                raise Exception("Falha no login - cookie de sessão não encontrado")

            print(f"  ✅ Login bem-sucedido! ({len(cookies_dict)} cookies de {len(domains)} domínios)")
            return cookies_dict

        finally:
            browser.close()


# ── Cookie Cache ───────────────────────────────────────────────────────────────

def save_cookies(cookies: dict):
    """Save cookies to disk for reuse."""
    with open(COOKIES_FILE, "wb") as f:
        pickle.dump({"cookies": cookies, "time": time.time()}, f)


def load_cookies() -> dict | None:
    """Load cached cookies if they exist and are less than 30 min old."""
    if not COOKIES_FILE.exists():
        return None
    try:
        with open(COOKIES_FILE, "rb") as f:
            data = pickle.load(f)
        age_minutes = (time.time() - data["time"]) / 60
        if age_minutes > 30:
            print(f"⏰ Cookies em cache expiraram ({age_minutes:.0f} min). Novo login necessário.")
            return None
        print(f"♻️  Reutilizando cookies em cache ({age_minutes:.0f} min de idade)")
        return data["cookies"]
    except Exception:
        return None


def get_cookies(force_login: bool = False, headless: bool = True) -> dict:
    """Get cookies from cache or perform new login."""
    if not force_login:
        cached = load_cookies()
        if cached:
            return cached

    cookies = login_and_get_cookies(headless=headless)
    save_cookies(cookies)
    return cookies


# ── API Client ─────────────────────────────────────────────────────────────────

def query_part_applicability(part_number: str, vc: str = None, cookies: dict = None) -> dict:
    """Query the ePER part applicability API."""
    url = f"{API_BASE}/partApplicability/{part_number}"
    params = {}
    if vc:
        params["vc"] = vc

    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update(cookies)

    response = session.get(url, params=params)

    if response.status_code == 401 or "Unauthorized" in response.text:
        return None

    if not response.text.strip():
        # Empty response means part is not applicable for this chassis
        return {"catalog": []}

    try:
        response.raise_for_status()
        return response.json()
    except requests.exceptions.JSONDecodeError:
        print(f"\n❌ Erro: API não retornou JSON. Status: {response.status_code}")
        print(f"URL de resposta: {response.url}")
        print(f"Conteúdo:\n{response.text[:500]}...")
        raise Exception(f"API respondeu com formato inválido (HTML). Status {response.status_code}")


def query_with_retry(part_number: str, vc: str = None, headless: bool = True) -> dict:
    """Query API with automatic re-login on auth failure."""
    cookies = get_cookies(headless=headless)
    result = query_part_applicability(part_number, vc, cookies)

    if result is None:
        print("🔄 Sessão expirada. Realizando novo login...")
        cookies = get_cookies(force_login=True, headless=headless)
        result = query_part_applicability(part_number, vc, cookies)

        if result is None:
            print("❌ Falha na autenticação mesmo após novo login.")
            raise Exception("Falha na autenticação mesmo após tentar re-login na API.")

    return result


# ── Output Formatting ──────────────────────────────────────────────────────────

def format_applicability(data: dict, part_number: str = "") -> str:
    """Format the API response into a readable table."""
    lines = []
    lines.append("=" * 90)
    
    # Define o código da peça usando o retorno da API ou o parâmetro providenciado
    part_code = data.get("partCode")
    if not part_code:
         part_code = part_number
         
    lines.append(f"  Código da Peça: {part_code}")
    lines.append("=" * 90)

    applications = data.get("catalog", [])
    if not applications:
        lines.append("  Nenhuma aplicação encontrada no catálogo.")
        return "\n".join(lines)

    for i, cat in enumerate(applications, 1):
        lines.append("")
        lines.append(f"  [{i}] Modelo: {cat.get('description', 'N/A')} ({cat.get('brand', 'N/A')})")
        
        tables = cat.get("table", [])
        for t in tables:
            lines.append(f"      Tabela: {t.get('table_code', '')} - {t.get('table_description', '')}")
            if t.get("part_dsc"):
                lines.append(f"      Descrição: {t.get('part_dsc')}")
            if t.get("part_pattern"):
                lines.append(f"      Padrão: {t.get('part_pattern')}")

    lines.append("")
    lines.append(f"  Total: {len(applications)} catálogos com aplicação")
    lines.append("=" * 90)
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fiat ePER Parts Applicability Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python fiat_parts_tool.py --part 14144190
  python fiat_parts_tool.py --part 14144190 --vc 9BWAA01J754038498
  python fiat_parts_tool.py --part 14144190 --raw
  python fiat_parts_tool.py --part 14144190 --no-headless
        """,
    )
    parser.add_argument("--part", required=True, help="Número da peça (ex: 14144190)")
    parser.add_argument("--vc", default=None, help="Número do chassi/VIN (opcional)")
    parser.add_argument("--raw", action="store_true", help="Exibir JSON bruto da resposta")
    parser.add_argument("--no-headless", action="store_true", help="Mostrar o navegador durante o login")
    parser.add_argument("--force-login", action="store_true", help="Forçar novo login (ignorar cache)")

    args = parser.parse_args()
    headless = not args.no_headless

    if args.force_login:
        get_cookies(force_login=True, headless=headless)

    print(f"\n🔍 Consultando peça: {args.part}" + (f" | Chassi: {args.vc}" if args.vc else ""))
    print()

    result = query_with_retry(args.part, args.vc, headless=headless)

    if args.raw:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_applicability(result))
        print()
        output_file = Path(__file__).parent / f"result_{args.part}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"📄 JSON salvo em: {output_file}")


if __name__ == "__main__":
    main()
