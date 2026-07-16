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
import re
import sys
import os
import time
import pickle
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

import requests
from requests.adapters import HTTPAdapter
try:
    from seleniumbase import Driver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
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

API_CONNECT_TIMEOUT = int(os.environ.get("EPER_CONNECT_TIMEOUT", "10"))
API_READ_TIMEOUT = int(os.environ.get("EPER_READ_TIMEOUT", "60"))
API_TIMEOUT = (API_CONNECT_TIMEOUT, API_READ_TIMEOUT)
RESULT_CACHE_TTL_SECONDS = int(os.environ.get("EPER_CACHE_TTL", "3600"))
BATCH_MAX_WORKERS = int(os.environ.get("EPER_BATCH_WORKERS", "3"))

_login_lock = threading.RLock()
_cookie_memory: dict | None = None
_cookie_memory_time: float = 0
_thread_local = threading.local()
_result_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_result_cache_lock = threading.Lock()


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
        for char in EMAIL:
            email_input.send_keys(char)
            time.sleep(0.01)
        time.sleep(1)
        driver.save_screenshot(str(DEBUG_DIR / "04_email_typed.png"))

        # Hide overlays that block clicks
        try:
            driver.execute_script("""
                const overlays = document.querySelectorAll('.hub-info-bar');
                overlays.forEach(el => el.style.display = 'none');
            """)
        except:
            pass

        # Use native clicks or JS clicks on ALL CONTINUAR buttons to guarantee the right one is clicked
        print("  → Clicando CONTINUAR...")
        continuar_btns = driver.find_elements(By.XPATH, "//*[contains(@class, 'hub-button') and contains(translate(text(), 'continuar', 'CONTINUAR'), 'CONTINUAR')]")
        for btn in continuar_btns:
            try:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click()", btn)
            except:
                pass
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
            # Re-type email and submit again
            try:
                email_field = driver.find_element(By.CSS_SELECTOR, "input.hub-input-field")
                email_field.click()
                email_field.clear()
                for char in EMAIL:
                    email_field.send_keys(char)
                    time.sleep(0.01)
                time.sleep(1)
                retry_btns = driver.find_elements(By.XPATH, "//*[contains(@class, 'hub-button') and contains(translate(text(), 'continuar', 'CONTINUAR'), 'CONTINUAR')]")
                for btn in retry_btns:
                    try:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click()", btn)
                    except:
                        pass
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

        # Submit password via multiple clicks
        print("  → Clicando CONTINUAR (Senha)...")
        continuar_btns = driver.find_elements(By.XPATH, "//*[contains(@class, 'hub-button') and contains(translate(text(), 'continuar', 'CONTINUAR'), 'CONTINUAR')]")
        for btn in continuar_btns:
            try:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click()", btn)
            except:
                pass
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
    """Save cookies to disk and update in-memory cache."""
    global _cookie_memory, _cookie_memory_time
    with open(COOKIES_FILE, "wb") as f:
        pickle.dump({"cookies": cookies, "time": time.time()}, f)
    _cookie_memory = cookies
    _cookie_memory_time = time.time()


COOKIE_TTL_MINUTES = 480  # 8 horas — servidor usa cookies sincronizados da máquina local


def load_cookies() -> dict | None:
    """Load cached cookies from disk if they exist and are fresh."""
    if not COOKIES_FILE.exists():
        return None
    try:
        with open(COOKIES_FILE, "rb") as f:
            data = pickle.load(f)
        age_minutes = (time.time() - data["time"]) / 60
        if age_minutes > COOKIE_TTL_MINUTES:
            print(f"Cookies em cache expiraram ({age_minutes:.0f} min). Novo login necessario.")
            return None
        print(f"Reutilizando cookies em cache ({age_minutes:.0f} min de idade)")
        return data["cookies"]
    except Exception:
        return None


def has_valid_cookies() -> bool:
    """Return True if unexpired cookies exist in memory or disk cache (no login triggered)."""
    global _cookie_memory, _cookie_memory_time
    if _cookie_memory is not None:
        if (time.time() - _cookie_memory_time) / 60 <= COOKIE_TTL_MINUTES:
            return True
    if COOKIES_FILE.exists():
        try:
            with open(COOKIES_FILE, "rb") as f:
                data = pickle.load(f)
            return (time.time() - data["time"]) / 60 <= COOKIE_TTL_MINUTES
        except Exception:
            pass
    return False


def get_cookies(force_login: bool = False, headless: bool = True) -> dict:
    """Get cookies from memory/disk cache or perform new login (thread-safe)."""
    global _cookie_memory, _cookie_memory_time

    with _login_lock:
        if not force_login and _cookie_memory is not None:
            age_minutes = (time.time() - _cookie_memory_time) / 60
            if age_minutes <= COOKIE_TTL_MINUTES:
                return _cookie_memory.copy()

        if not force_login:
            cached = load_cookies()
            if cached:
                _cookie_memory = cached
                _cookie_memory_time = time.time()
                return cached.copy()

        cookies = login_and_get_cookies(headless=headless)
        save_cookies(cookies)
        return cookies.copy()


# ── API Client ─────────────────────────────────────────────────────────────────

def _get_api_session() -> requests.Session:
    """Return a thread-local requests.Session (safe for parallel batch queries)."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        adapter = HTTPAdapter(pool_connections=5, pool_maxsize=5, max_retries=0)
        session.mount("https://", adapter)
        _thread_local.session = session
    return session


def _refresh_cookies(headless: bool = True) -> dict:
    """Force a new login and return fresh cookies (thread-safe)."""
    with _login_lock:
        cookies = login_and_get_cookies(headless=headless)
        save_cookies(cookies)
        return cookies.copy()


def _result_cache_key(part_number: str, vc: str | None) -> tuple[str, str]:
    return (part_number.upper(), vc or "")


def _get_cached_result(part_number: str, vc: str | None) -> dict | None:
    key = _result_cache_key(part_number, vc)
    with _result_cache_lock:
        entry = _result_cache.get(key)
        if entry and time.time() - entry[0] < RESULT_CACHE_TTL_SECONDS:
            return entry[1]
    return None


def _set_cached_result(part_number: str, vc: str | None, data: dict):
    key = _result_cache_key(part_number, vc)
    with _result_cache_lock:
        _result_cache[key] = (time.time(), data)


def query_part_applicability(
    part_number: str,
    vc: str = None,
    cookies: dict = None,
    session: requests.Session = None,
) -> dict | None:
    """Query the ePER part applicability API."""
    url = f"{API_BASE}/partApplicability/{part_number}"
    params = {}
    if vc:
        params["vc"] = vc

    session = session or _get_api_session()

    try:
        response = session.get(url, params=params, timeout=API_TIMEOUT, cookies=cookies or {})
    except requests.Timeout:
        raise TimeoutError(f"Timeout ao consultar peça {part_number} (limite {API_READ_TIMEOUT}s)")
    except requests.RequestException as e:
        raise ConnectionError(f"Erro de rede ao consultar peça {part_number}: {e}") from e

    if response.status_code == 401 or "Unauthorized" in response.text:
        return None

    if not response.text.strip():
        return {"catalog": []}

    try:
        response.raise_for_status()
        return response.json()
    except requests.exceptions.JSONDecodeError:
        print(f"Erro: API nao retornou JSON. Status: {response.status_code}")
        print(f"URL de resposta: {response.url}")
        print(f"Conteudo:\n{response.text[:500]}...")
        raise Exception(f"API respondeu com formato invalido (HTML). Status {response.status_code}")


def query_with_retry(
    part_number: str,
    vc: str = None,
    headless: bool = True,
    cookies: dict = None,
    session: requests.Session = None,
) -> dict:
    """Query API with automatic re-login on auth failure."""
    cached = _get_cached_result(part_number, vc)
    if cached is not None:
        return cached

    if cookies is None:
        cookies = get_cookies(headless=headless)
    session = session or _get_api_session()

    result = query_part_applicability(part_number, vc, cookies, session)

    if result is None:
        print("Sessao expirada. Realizando novo login...")
        cookies = _refresh_cookies(headless=headless)
        result = query_part_applicability(part_number, vc, cookies, session)

        if result is None:
            print("Falha na autenticacao mesmo apos novo login.")
            raise Exception("Falha na autenticacao mesmo apos tentar re-login na API.")

    _set_cached_result(part_number, vc, result)
    return result


def _extract_model(data: dict) -> str:
    for cat in data.get("catalog", []):
        if cat.get("description"):
            return cat.get("description")
    return ""


def format_structured_applicability(data: dict) -> tuple[bool, list[dict], str]:
    """Return (found, list_of_detail_dicts, api_part_description).

    Each detail dict contains:
        brand, model, tables, table_desc, part_dsc
    """
    applications = data.get("catalog", [])
    if not applications:
        return False, [], ""

    details = []
    api_desc = ""

    for cat in applications:
        model = cat.get("description", "N/A")
        brand = cat.get("brand", "")
        tables = cat.get("table", [])
        if not tables:
            continue

        table_codes = [t.get("table_code", "") for t in tables if t.get("table_code")]
        table_descs = list(dict.fromkeys(
            t.get("table_description", "") for t in tables if t.get("table_description")
        ))
        table_desc_str = table_descs[0] if len(table_descs) == 1 else " / ".join(table_descs)

        part_dscs = [t.get("part_dsc", "") for t in tables if t.get("part_dsc")]
        part_dsc = part_dscs[0] if part_dscs else ""
        if part_dsc and not api_desc:
            api_desc = part_dsc

        details.append({
            "brand": brand,
            "model": model,
            "tables": ", ".join(table_codes) if table_codes else "",
            "table_desc": table_desc_str,
            "part_dsc": part_dsc,
        })

    if not details:
        return False, [], ""

    return True, details, api_desc


def _build_batch_row(entry: dict, data: dict | None, error: str | None) -> dict:
    code = entry["code"]
    user_desc = entry["description"]

    if error:
        return {
            "code": code,
            "description": user_desc or "",
            "result": f"❌ Erro: {error}",
            "found": False,
            "model": "",
            "compatibility_details": [],
        }

    if data is None:
        return {
            "code": code,
            "description": user_desc or "",
            "result": "❌ Erro na consulta",
            "found": False,
            "model": "",
            "compatibility_details": [],
        }

    found, result_line, api_desc = format_compact_applicability(data)
    found_s, details, _ = format_structured_applicability(data)
    model = _extract_model(data)
    return {
        "code": code,
        "description": user_desc or api_desc or "",
        "result": result_line,
        "found": found,
        "model": model,
        "compatibility_details": details,
    }


def query_batch(
    entries: list[dict],
    vc: str = None,
    headless: bool = True,
    max_workers: int | None = None,
) -> list[dict]:
    """Query multiple parts in parallel, preserving input order."""
    if not entries:
        return []

    workers = max_workers if max_workers is not None else BATCH_MAX_WORKERS
    batch_start = time.time()
    cookies = get_cookies(headless=headless)

    unique_codes = list(dict.fromkeys(e["code"] for e in entries))
    results_by_code: dict[str, dict | None] = {}
    auth_failed: list[str] = []
    errors_by_code: dict[str, str] = {}
    cache_hits = 0
    timings: dict[str, float] = {}

    def _fetch(code: str):
        t0 = time.time()
        cached = _get_cached_result(code, vc)
        if cached is not None:
            timings[code] = time.time() - t0
            return code, cached, None, False, True

        try:
            session = _get_api_session()
            data = query_part_applicability(code, vc, cookies, session)
            if data is None:
                timings[code] = time.time() - t0
                return code, None, None, True, False
            _set_cached_result(code, vc, data)
            timings[code] = time.time() - t0
            return code, data, None, False, False
        except TimeoutError as e:
            timings[code] = time.time() - t0
            return code, None, str(e), False, False
        except Exception as e:
            timings[code] = time.time() - t0
            return code, None, str(e), False, False

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_fetch, code) for code in unique_codes]
        for future in as_completed(futures):
            code, data, err, need_auth, from_cache = future.result()
            if from_cache:
                cache_hits += 1
            if need_auth:
                auth_failed.append(code)
            elif err:
                errors_by_code[code] = err
            results_by_code[code] = data

    if auth_failed:
        print(f"[BATCH] Re-autenticando para {len(auth_failed)} peca(s)...")
        fresh_cookies = _refresh_cookies(headless=headless)
        for code in auth_failed:
            t0 = time.time()
            try:
                session = _get_api_session()
                data = query_part_applicability(code, vc, fresh_cookies, session)
                if data is None:
                    errors_by_code[code] = "Falha na autenticacao"
                    results_by_code[code] = None
                else:
                    _set_cached_result(code, vc, data)
                    results_by_code[code] = data
            except Exception as e:
                errors_by_code[code] = str(e)
                results_by_code[code] = None
            timings[code] = time.time() - t0

    elapsed = time.time() - batch_start
    avg = sum(timings.values()) / len(timings) if timings else 0
    slowest = max(timings.items(), key=lambda x: x[1]) if timings else ("", 0)
    print(
        f"[BATCH] {len(entries)} peca(s) em {elapsed:.1f}s | "
        f"workers={workers} | cache={cache_hits} | "
        f"media={avg:.1f}s | mais lenta={slowest[0]} ({slowest[1]:.1f}s)"
    )

    return [
        _build_batch_row(entry, results_by_code.get(entry["code"]), errors_by_code.get(entry["code"]))
        for entry in entries
    ]


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


def parse_bulk_parts(text: str) -> list[dict]:
    """Parse pasted text into part entries with optional descriptions."""
    entries = []
    seen = set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        code = ""
        description = ""

        if "\t" in line:
            parts = line.split("\t", 1)
            code, description = parts[0].strip(), parts[1].strip()
        elif ";" in line:
            parts = line.split(";", 1)
            code, description = parts[0].strip(), parts[1].strip()
        elif "," in line and not re.match(r"^[A-Z0-9]+,\s*[A-Z0-9]+$", line, re.I):
            parts = line.split(",", 1)
            code, description = parts[0].strip(), parts[1].strip()
        else:
            match = re.match(r"^([A-Za-z0-9\-]+)(?:\s{2,}|\s-\s|\s\|\s)(.+)$", line)
            if match:
                code, description = match.group(1).strip(), match.group(2).strip()
            else:
                tokens = line.split()
                code = tokens[0]
                if len(tokens) > 1:
                    description = " ".join(tokens[1:])

        code = re.sub(r"[^\w\-]", "", code).upper()
        if not code or code in seen:
            continue
        seen.add(code)
        entries.append({"code": code, "description": description})

    return entries


def format_compact_applicability(data: dict) -> tuple[bool, str, str]:
    """Return (found, one-line result, api part description)."""
    applications = data.get("catalog", [])
    if not applications:
        return False, "❌ Nenhuma aplicação encontrada", ""

    lines = []
    api_desc = ""

    for cat in applications:
        model = cat.get("description", "N/A")
        tables = cat.get("table", [])
        if not tables:
            continue

        table_codes = [t.get("table_code", "") for t in tables if t.get("table_code")]
        table_descs = list(dict.fromkeys(
            t.get("table_description", "") for t in tables if t.get("table_description")
        ))
        table_desc_str = table_descs[0] if len(table_descs) == 1 else " / ".join(table_descs)

        part_dscs = [t.get("part_dsc", "") for t in tables if t.get("part_dsc")]
        part_dsc = part_dscs[0] if part_dscs else ""
        if part_dsc and not api_desc:
            api_desc = part_dsc

        if len(table_codes) == 1:
            table_part = f"Tabela {table_codes[0]}"
        elif len(table_codes) == 2:
            table_part = f"Tabelas {table_codes[0]} e {table_codes[1]}"
        elif table_codes:
            table_part = f"Tabelas {', '.join(table_codes[:-1])} e {table_codes[-1]}"
        else:
            table_part = "Tabela"

        desc_paren = f" ({table_desc_str})" if table_desc_str else ""
        dsc_suffix = f" — {part_dsc}" if part_dsc else ""
        lines.append(f"✅ {model} — {table_part}{desc_paren}{dsc_suffix}")

    if not lines:
        return False, "❌ Nenhuma aplicação encontrada", ""

    result = lines[0] if len(lines) == 1 else " | ".join(lines)
    return True, result, api_desc


def infer_vehicle_label(vehicle_label: str, vc: str, batch_results: list) -> str:
    """Build the compatibility report header."""
    if vehicle_label:
        return vehicle_label
    for item in batch_results:
        if item.get("found") and item.get("model"):
            return item["model"]
    if vc:
        return f"Chassi {vc}"
    return "Busca Global"


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
