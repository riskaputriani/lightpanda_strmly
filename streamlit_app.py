import asyncio
import json
import os
import platform
import random
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, sync_playwright

# --- Solver Integration ---
# Add src directory to path to allow import of cf_solver
sys.path.insert(0, str(Path(__file__).parent / "src"))
from cf_solver.solver_zendriver import CloudflareSolver, get_chrome_user_agent
# --- End Solver Integration ---

if sys.platform == "win32":
    try:
        # Fix for asyncio on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except (RuntimeError, AttributeError):
        pass

CHROME_DIR = Path.home() / ".local" / "chrome"
CHROME_BIN = CHROME_DIR / "chrome"
INSTALL_SCRIPT = Path(__file__).parent / "install_chrome.sh"


def ensure_chrome_installed() -> str:
    """
    Ensure Chrome binary is available under ~/.local/chrome using the provided install script.
    Returns the path to the Chrome binary.
    """
    if CHROME_BIN.exists():
        return str(CHROME_BIN)

    subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        check=True,
        env=os.environ.copy(),
    )

    if not CHROME_BIN.exists():
        raise PlaywrightError("Chrome installation failed; chrome binary not found.")

    return str(CHROME_BIN)


def _ensure_scheme(value: str) -> str:
    """Add a default scheme when the provided URL is missing one."""
    trimmed = value.strip()
    if trimmed and not trimmed.startswith(("http://", "https://")):
        return f"https://{trimmed}"
    return trimmed


@st.cache_data(ttl=600)
def get_free_proxies():
    """Scrape free-proxy-list.net for HTTPS proxies and their countries."""
    try:
        url = "https://free-proxy-list.net/"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table")
        
        proxies = []
        for row in table.tbody.find_all("tr"):
            cols = row.find_all("td")
            if cols and len(cols) > 6:
                ip = cols[0].text.strip()
                port = cols[1].text.strip()
                country = cols[3].text.strip()
                is_https = cols[6].text.strip()
                if is_https == 'yes':
                    proxies.append({
                        "proxy": f"http://{ip}:{port}",
                        "country": country
                    })
        return proxies
    except requests.exceptions.RequestException:
        return []

def find_best_proxy():
    """Find a working proxy by testing them sequentially."""
    proxies_list = get_free_proxies()
    random.shuffle(proxies_list)

    for proxy_info in proxies_list:
        proxy = proxy_info["proxy"]
        try:
            requests.get(
                "https://httpbin.org/ip", 
                proxies={"http": proxy, "https": proxy}, 
                timeout=3
            )
            return proxy_info
        except requests.exceptions.RequestException:
            continue
    return None

@st.cache_resource
def get_chrome_path() -> str:
    """
    Ensure Chrome is installed via the bundled shell script and return its path.
    """
    if st.session_state.get("browser_path"):
        return st.session_state.browser_path

    chrome_path = ensure_chrome_installed()
    st.session_state.browser_path = chrome_path
    return chrome_path

def run_solver(url: str, proxy: str | None) -> list[dict]:
    """
    Runs the Cloudflare solver as a standalone process and returns the cookies.
    """
    try:
        browser_path = get_chrome_path()
    except Exception as e:
        st.error(f"Could not determine Chrome path: {e}")
        return []

    async def _solve() -> list[dict]:
        user_agent = get_chrome_user_agent()
        all_cookies: list[dict] = []
        try:
            async with CloudflareSolver(
                cdp_url=None,
                user_agent=user_agent,
                timeout=45,
                proxy=proxy,
                browser_executable_path=browser_path,
            ) as solver:
                await solver.driver.get(url)
                
                current_cookies = await solver.get_cookies()
                clearance_cookie = solver.extract_clearance_cookie(current_cookies)

                if clearance_cookie is None:
                    await solver.set_user_agent_metadata(await solver.get_user_agent())
                    
                    challenge_platform = await solver.detect_challenge()
                    if challenge_platform:
                        st.info(f"Detected Cloudflare {challenge_platform.value} challenge. Solving...")
                        await solver.solve_challenge()
                        all_cookies = await solver.get_cookies()
                    else:
                        st.warning("No Cloudflare challenge detected by solver.")
                        all_cookies = current_cookies
                else:
                    st.info("Cloudflare clearance cookie already present.")
                    all_cookies = current_cookies
        except Exception as e:
            st.error(f"An exception occurred during Cloudflare solving: {e}", icon="🔥")
            return []

        if not solver.extract_clearance_cookie(all_cookies):
             st.warning("Solver finished, but cf_clearance cookie was not found.", icon="⚠️")
        
        return all_cookies

    # This logic attempts to run the async solver in Streamlit's environment.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_solve(), loop)
        return future.result()
    else:
        return asyncio.run(_solve())



def sanitize_cookies(cookies: list[dict]) -> list[dict]:
    """
    Sanitizes the 'sameSite' attribute of cookies to be compatible with Playwright.
    Playwright's `add_cookies` is strict and only accepts "Strict", "Lax", or "None".
    """
    sanitized = []
    for cookie in cookies:
        if "sameSite" in cookie:
            # Convert to title case, as Playwright expects "Strict", "Lax", or "None"
            val = cookie["sameSite"].title()
            if val in ("Strict", "Lax", "None"):
                cookie["sameSite"] = val
            else:
                # If the value is invalid, it's safer to remove it
                del cookie["sameSite"]
        sanitized.append(cookie)
    return sanitized


def fetch_page(
    url: str,
    *,
    take_screenshot: bool = False,
    get_html: bool = False,
    proxy: str | None = None,
    cookies: list[dict] | None = None,
    user_agent: str | None = None,
    timeout: int = 30_000,
) -> dict:
    """Use Playwright to launch a browser, get page data, and detect CF challenges."""
    chrome_path = get_chrome_path()

    context_options = {}
    if proxy:
        proxy_parts = urlparse(proxy)
        server = f"{proxy_parts.scheme}://{proxy_parts.hostname}"
        if proxy_parts.port:
            server += f":{proxy_parts.port}"
        
        proxy_config = {"server": server}
        if proxy_parts.username:
            proxy_config["username"] = proxy_parts.username
        if proxy_parts.password:
            proxy_config["password"] = proxy_parts.password
        context_options["proxy"] = proxy_config
    
    if user_agent:
        context_options["user_agent"] = user_agent

    with sync_playwright() as playwright:
        with playwright.chromium.launch(
            executable_path=chrome_path,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        ) as browser:
            context = browser.new_context(**context_options)
            if cookies:
                sanitized_cookies = sanitize_cookies(cookies)
                context.add_cookies(sanitized_cookies)
            
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                
                if "Just a moment..." in page.title():
                    return {"status": "cloudflare_challenge"}

                result: dict[str, object] = {"status": "ok", "title": page.title()}
                if take_screenshot:
                    result["screenshot"] = page.screenshot(full_page=True)
                if get_html:
                    result["html"] = page.content()
                
                return result

            except PlaywrightError as e:
                return {"status": "error", "message": str(e)}

# --- App ---
st.set_page_config(page_title="Playwright URL Reader", layout="centered")

# Initialize session state
if "proxy_address" not in st.session_state:
    st.session_state.proxy_address = ""
if "proxy_country" not in st.session_state:
    st.session_state.proxy_country = ""
if "browser_path" not in st.session_state:
    st.session_state.browser_path = None
if "cookie_text" not in st.session_state:
    st.session_state.cookie_text = ""

st.title("Ambil Data dari URL dengan Playwright")
st.caption("Tekan tombol 'Go' untuk mengambil data dari URL.")

# --- Sidebar ---
st.sidebar.header("Opsi")
take_screenshot = st.sidebar.checkbox("Ambil screenshot", value=False)
get_html = st.sidebar.checkbox("Get HTML", value=False)
use_solver = st.sidebar.checkbox("Gunakan solver Cloudflare jika perlu", value=True)

st.sidebar.header("Proxy")
proxy_input = st.sidebar.text_input("Proxy Address", value=st.session_state.proxy_address)

if st.sidebar.button("Cari proxy otomatis"):
    with st.spinner("Mencari & menguji proxy..."):
        best_proxy = find_best_proxy()
        if best_proxy:
            st.session_state.proxy_address = best_proxy["proxy"]
            st.session_state.proxy_country = best_proxy["country"]
            st.rerun()
        else:
            st.sidebar.error("Tidak ada proxy yang berfungsi ditemukan.")
            st.session_state.proxy_address = ""
            st.session_state.proxy_country = ""

if st.session_state.proxy_country:
    st.sidebar.info(f"Negara Proxy: {st.session_state.proxy_country}")

st.sidebar.header("Overrides")
user_agent_input = st.sidebar.text_input("User Agent")
cookie_json_text_input = st.sidebar.text_area("Cookies (JSON Array)", value=st.session_state.cookie_text)
cookie_file = st.sidebar.file_uploader("Upload cookies.json", type=["json"])

# --- Main Page ---
url_input = st.text_input("Masukkan URL yang ingin diambil datanya", value="")

if st.button("Go"):
    normalized_url = _ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
    else:
        # --- Data Extraction from UI ---
        loaded_cookies = None
        raw_json_data = None
        # Give file uploader precedence
        if cookie_file:
            try:
                raw_json_data = json.load(cookie_file)
            except Exception as e:
                st.error(f"Gagal membaca file cookie: {e}")
                st.stop()
        elif cookie_json_text_input:
            try:
                raw_json_data = json.loads(cookie_json_text_input)
            except json.JSONDecodeError:
                st.error("JSON cookie di text area tidak valid.")
                st.stop()

        if raw_json_data:
            if isinstance(raw_json_data, list):
                loaded_cookies = raw_json_data
            else:
                st.error("Format cookie JSON tidak valid. Harus berupa array (daftar) objek cookie.")
                st.stop()
            
            st.session_state.cookie_text = json.dumps(raw_json_data, indent=2)

        # --- Determine Final Settings ---
        final_proxy = proxy_input if proxy_input else None
        final_user_agent = user_agent_input if user_agent_input else None

        # --- Main Orchestration Logic ---
        with st.spinner("Mengambil halaman..."):
            result = fetch_page(
                normalized_url,
                take_screenshot=take_screenshot,
                get_html=get_html,
                proxy=final_proxy,
                cookies=loaded_cookies,
                user_agent=final_user_agent,
            )

        if use_solver and result.get("status") == "cloudflare_challenge":
            solver_cookies = run_solver(normalized_url, final_proxy)
            if not solver_cookies:
                st.error("Cloudflare solver gagal mendapatkan cookies.")
                st.stop()
            
            sanitized_cookies = sanitize_cookies(solver_cookies)
            st.session_state.cookie_text = json.dumps(sanitized_cookies, indent=2)
            st.success("Solver berhasil mendapatkan cookies. Mengambil ulang halaman...")
            
            # Rerun to update the cookie text area and use the new cookies
            st.rerun()

        # --- Display Results ---
        if result.get("status") == "ok":
            st.success("Operasi Selesai!")
            st.subheader("Title")
            st.code(result.get("title", "-"))

            if "screenshot" in result:
                st.subheader("Screenshot")
                st.image(result["screenshot"])
                st.download_button("Download screenshot", data=result["screenshot"], file_name="screenshot.png", mime="image/png")

            if "html" in result:
                st.subheader("HTML Content")
                st.code(result["html"], language="html")
                st.download_button("Download HTML", data=result["html"], file_name="page.html", mime="text/html")
        
        elif result.get("status") == "cloudflare_challenge":
            st.error("Gagal melewati Cloudflare. Coba aktifkan solver jika belum aktif.")
        
        else:
            st.error(f"Gagal mengambil halaman: {result.get('message', 'Unknown error')}")
