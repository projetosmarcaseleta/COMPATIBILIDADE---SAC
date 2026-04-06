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
import time
import pickle
from pathlib import Path

import requests
try:
    from seleniumbase import Driver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    _HAS_UC = True
except ImportError:
    _HAS_UC = False


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


# ── Browser Login (SeleniumBase UC Mode) ───────────────────────────────────────

def login_and_get_cookies(headless: bool = True) -> dict:
    """
    Perform browser login using SeleniumBase UC mode to bypass Akamai WAF.
    Returns a dict of session cookies.
    """
    if not _HAS_UC:
        raise ImportError("seleniumbase não instalado. Rode: pip install seleniumbase")

    print("🔑 Iniciando login no Fiat Reparador (SeleniumBase UC)...")
    DEBUG_DIR.mkdir(exist_ok=True)

    import platform
    is_linux = platform.system() == "Linux"
    
    # Em servidores Linux (como o VPS da Hostinger), o modo headless costuma
    # ser detectado pelo Akamai ou causar crash (Stacktrace #0...)
    # Para resolver, usamos o Xvfb (Virtual Display) para simular uma tela real
    # e rodamos o Chrome no modo COM interface gráfica (headless=False)
    display = None
    if is_linux:
        try:
            from pyvirtualdisplay import Display
            print("  💻 Iniciando Xvfb Virtual Display...")
            # Usa o Xvfb instalado via apt-get no deploy.yml
            display = Display(visible=0, size=(1280, 900))
            display.start()
            headless = False # Força modo não-headless já que temos a tela virtual
        except ImportError:
            print("  ⚠️ pyvirtualdisplay não instalado. Prosseguindo sem tela virtual.")
    
    # SeleniumBase Driver com uc=True ativa o modo anti-detecção
    driver = Driver(
        uc=True,
        headless=headless,
        chromium_arg="--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--disable-software-rasterizer"
    )
    driver.set_page_load_timeout(60)

    try:
        # Step 1: Navigate to site
        driver.get(LOGIN_URL)
        time.sleep(8)  # Espera JS carregar completamente
        driver.save_screenshot(str(DEBUG_DIR / "01_landing.png"))

        # Close cookie banner if present
        print("  → Verificando banners de cookies/popups...")
        for selector in ["#onetrust-accept-btn-handler", "button[aria-label='Aceitar']"]:
            try:
                btn = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                btn.click()
                print(f"  ✓ Banner fechado ({selector})")
                time.sleep(1)
            except Exception:
                continue

        # Step 2: Click "Entre ou Cadastre-se"
        print("  → Abrindo modal de login...")
        try:
            login_link = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a.login-link"))
            )
            driver.execute_script("arguments[0].click()", login_link)
            print("  ✓ Botão de login clicado.")
        except Exception:
            driver.save_screenshot(str(DEBUG_DIR / "02_login_not_found.png"))
            # Fallback: tenta clicar via JS
            found = driver.execute_script("""
                const els = Array.from(document.querySelectorAll('a, button'));
                const target = els.find(e => e.textContent && (
                    e.textContent.includes('Entre') || e.textContent.includes('Entrar')
                ));
                if (target) { target.click(); return true; }
                return false;
            """)
            if not found:
                print(f"  ❌ URL atual: {driver.current_url}")
                print(f"  ❌ Título: {driver.title}")
                body_text = driver.execute_script("return document.body ? document.body.innerText.slice(0, 500) : 'sem body'")
                print(f"  ❌ Conteúdo: {body_text}")
                raise Exception("Não foi possível encontrar o botão de login na página.")

        time.sleep(3)
        driver.save_screenshot(str(DEBUG_DIR / "02_modal_open.png"))

        # Step 3: Click "ENTRAR COM E-MAIL"
        print("  → Selecionando login por e-mail...")
        email_btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn-email"))
        )
        driver.execute_script("arguments[0].click()", email_btn)
        time.sleep(2)
        driver.save_screenshot(str(DEBUG_DIR / "03_email_form.png"))

        # Step 4: Enter email
        print(f"  → Digitando e-mail: {EMAIL}")
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input.hub-input-field"))
        )
        email_input.click()
        time.sleep(0.3)
        email_input.clear()
        email_input.send_keys(EMAIL)
        time.sleep(2)
        driver.save_screenshot(str(DEBUG_DIR / "04_email_typed.png"))

        # Click CONTINUAR (email step)
        print("  → Clicando CONTINUAR...")
        continuar_btns = driver.find_elements(By.XPATH, "//a[contains(@class, 'hub-button') and contains(text(), 'CONTINUAR')]")
        for btn in continuar_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click()", btn)
                break
        print("  ✓ CONTINUAR clicado")

        # Wait for password screen
        print("  → Aguardando tela de senha...")
        time.sleep(5)
        driver.save_screenshot(str(DEBUG_DIR / "05_after_continuar.png"))

        # Step 5: Enter password
        try:
            password_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "password"))
            )
        except Exception:
            print("  ⚠ Tela de senha não apareceu. Tentando novamente...")
            driver.save_screenshot(str(DEBUG_DIR / "05b_retry.png"))
            # Close any survey popups
            try:
                driver.find_element(By.XPATH, "//button[contains(text(), 'Cancelar')]").click()
                time.sleep(0.5)
            except Exception:
                pass
            # Re-type email and click CONTINUAR again
            try:
                email_field = driver.find_element(By.CSS_SELECTOR, "input.hub-input-field")
                email_field.click()
                email_field.clear()
                for char in EMAIL:
                    email_field.send_keys(char)
                    time.sleep(0.05)
                time.sleep(2)
                retry_btns = driver.find_elements(By.XPATH, "//a[contains(@class, 'hub-button') and contains(text(), 'CONTINUAR')]")
                for btn in retry_btns:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click()", btn)
                        break
                print("  ✓ CONTINUAR clicado (2a tentativa)")
                time.sleep(8)
                driver.save_screenshot(str(DEBUG_DIR / "05c_after_retry.png"))
            except Exception as e:
                print(f"  ⚠ Retry falhou: {e}")

            password_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "password"))
            )

        print("  → Digitando senha...")
        driver.execute_script("arguments[0].click()", password_input)
        time.sleep(0.3)
        password_input.clear()
        password_input.send_keys(PASSWORD)
        time.sleep(1)
        driver.save_screenshot(str(DEBUG_DIR / "06_password_typed.png"))

        # Click CONTINUAR (password step)
        print("  → Clicando CONTINUAR...")
        continuar_btns = driver.find_elements(By.XPATH, "//a[contains(@class, 'hub-button') and contains(text(), 'CONTINUAR')]")
        for btn in continuar_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click()", btn)
                break
        print("  → Aguardando autenticação...")
        time.sleep(10)
        driver.save_screenshot(str(DEBUG_DIR / "07_after_login.png"))

        # Verify login success
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a.badge-logout-button"))
            )
            print("  ✅ Login confirmado!")
        except Exception:
            print("  ⚠ Não foi possível confirmar o login, tentando continuar...")
            driver.save_screenshot(str(DEBUG_DIR / "08_login_not_confirmed.png"))

        # Step 6: Navigate to ePER to get the right domain cookies
        print("  → Acessando o Catálogo de Peças...")
        try:
            # Close any bottom banner
            try:
                driver.find_element(By.XPATH, "//button[contains(text(), 'FECHAR')]").click()
                time.sleep(1)
            except Exception:
                pass

            # Scroll down to make catalog visible
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2)")
            time.sleep(1)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # Click catalog via JS
            clicked = driver.execute_script("""
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
                let node;
                while (node = walker.nextNode()) {
                    if (node.nodeValue.includes('agilizar o tempo')) {
                        let el = node.parentElement;
                        while (el && el !== document.body) {
                            if (el.tagName === 'A' || el.tagName === 'BUTTON') {
                                el.click();
                                return true;
                            }
                            el = el.parentElement;
                        }
                        node.parentElement.click();
                        return true;
                    }
                }
                return false;
            """)

            if clicked:
                print("  ✓ CATÁLOGO DE PEÇAS clicado via JS")
                time.sleep(5)
                # If new tab opened, switch to it
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    print("  ✓ Nova aba do catálogo aberta")
                    time.sleep(5)
            else:
                print("  ⚠ Texto 'agilizar o tempo' não encontrado. Tentando navegar direto ao ePER...")
                driver.get(EPER_URL)
                time.sleep(10)

        except Exception as e:
            print(f"  ⚠ Falha ao abrir catálogo: {e}. Tentando navegar direto ao ePER...")
            driver.get(EPER_URL)
            time.sleep(10)

        # Collect cookies
        print("  → Aguardando cookies do ePER...")
        start_time = time.time()
        found_cookie = False
        while time.time() - start_time < 30:
            selenium_cookies = driver.get_cookies()
            cookies_dict = {c["name"]: c["value"] for c in selenium_cookies}
            if ".AspNetCore.Cookies" in cookies_dict:
                found_cookie = True
                break
            time.sleep(3)

        selenium_cookies = driver.get_cookies()
        cookies_dict = {c["name"]: c["value"] for c in selenium_cookies}
        domains = set(c.get("domain", "") for c in selenium_cookies)
        print(f"  → Domínios nos cookies: {list(domains)}")

        if not found_cookie:
            # Última tentativa: navegar diretamente ao ePER
            print("  ⚠ Cookie não encontrado. Navegação direta ao ePER...")
            driver.get(EPER_URL)
            time.sleep(10)
            selenium_cookies = driver.get_cookies()
            cookies_dict = {c["name"]: c["value"] for c in selenium_cookies}
            if ".AspNetCore.Cookies" not in cookies_dict:
                print(f"  ❌ Falha no login - cookie .AspNetCore.Cookies não encontrado.")
                print(f"     URL atual: {driver.current_url}")
                print(f"     Cookies: {list(cookies_dict.keys())}")
                raise Exception("Falha no login - cookie de sessão não encontrado")

        print(f"  ✅ Login bem-sucedido! ({len(cookies_dict)} cookies obtidos)")
        return cookies_dict

    except Exception as e:
        final_url = "Desconhecida"
        final_title = "Desconhecido"
        try:
            final_url = driver.current_url
            final_title = driver.title
            driver.save_screenshot(str(DEBUG_DIR / "final_error_crash.png"))
        except:
            pass
            
        error_msg = str(e)
        if "Stacktrace:" in error_msg or "TimeoutException" in str(type(e)):
            raise Exception(f"Timeout na interface do login. O site demorou muito para responder ou bloqueou o acesso do servidor. (URL: {final_url} | Título: {final_title})")
        else:
            raise Exception(f"Erro durante o login no navegador: {error_msg} (URL: {final_url})")

    finally:
        try:
            driver.quit()
        except:
            pass
        if 'display' in locals() and display:
            print("  💻 Encerrando Xvfb Virtual Display...")
            try:
                display.stop()
            except:
                pass


# ── Cookie Cache ───────────────────────────────────────────────────────────────

def save_cookies(cookies: dict):
    """Save cookies to disk for reuse."""
    with open(COOKIES_FILE, "wb") as f:
        pickle.dump({"cookies": cookies, "time": time.time()}, f)


COOKIE_TTL_MINUTES = 480  # 8 horas — servidor usa cookies sincronizados da máquina local


def load_cookies() -> dict | None:
    """Load cached cookies if they exist and are less than COOKIE_TTL_MINUTES old."""
    if not COOKIES_FILE.exists():
        return None
    try:
        with open(COOKIES_FILE, "rb") as f:
            data = pickle.load(f)
        age_minutes = (time.time() - data["time"]) / 60
        if age_minutes > COOKIE_TTL_MINUTES:
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
