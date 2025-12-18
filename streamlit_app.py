import asyncio
import os
import platform
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, sync_playwright

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except RuntimeError:
        pass


_BROWSER_INSTALL_MARKER = Path(tempfile.gettempdir()) / "playwright-chromium-installed.marker"


def ensure_playwright_browsers_installed() -> None:
    """Run a one-time Playwright install so future launches find the Chromium executable."""
    if _BROWSER_INSTALL_MARKER.exists():
        return
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise PlaywrightError(
            "Unable to install Chromium automatically. "
            "Run `python -m playwright install chromium` and retry."
        ) from exc
    _BROWSER_INSTALL_MARKER.write_text("installed")


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


def fetch_page(
    url: str,
    *,
    take_screenshot: bool = False,
    get_html: bool = False,
    proxy: str | None = None,
    timeout: int = 30_000,
) -> dict:
    """Use Playwright to launch a local Chromium browser, return title and optional screenshot/HTML."""
    ensure_playwright_browsers_installed()

    launch_options = {"headless": True}
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
        
        launch_options["proxy"] = proxy_config

    with sync_playwright() as playwright:
        with playwright.chromium.launch(**launch_options) as browser:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            result = {"title": page.title()}

            if take_screenshot:
                result["screenshot"] = page.screenshot(full_page=True)
            
            if get_html:
                result["html"] = page.content()

            return result


def _system_info_text() -> str:
    """Return a text summary similar to the provided console script."""
    parts = [
        "\n=== SYSTEM INFO ===",
        f"OS          : {platform.system()} {platform.release()}",
        f"Kernel      : {platform.version()}",
        f"Machine     : {platform.machine()}",
        f"Platform    : {platform.platform()}",
        "",
        "=== PYTHON INFO ===",
        f"Python      : {sys.version.replace('\n', ' ')}",
        f"Build       : {platform.python_build()}",
        f"Compiler    : {platform.python_compiler()}",
        "",
        "=== ENVIRONMENT ===",
        f"os.name     : {os.name}",
        f"USER        : {os.environ.get('USER')}",
        f"HOME        : {os.environ.get('HOME')}",
        "",
        "=== SPECIAL CHECKS ===",
        f"Docker?     : {os.path.exists('/.dockerenv')}",
        f"WSL?        : {'microsoft' in platform.release().lower()}",
        f"Alpine?     : {'alpine' in platform.platform().lower()}",
    ]
    return "\n".join(parts)

# --- App ---

st.set_page_config(page_title="Playwright URL Reader", layout="centered")

# Initialize session state
if "proxy_address" not in st.session_state:
    st.session_state.proxy_address = ""
if "proxy_country" not in st.session_state:
    st.session_state.proxy_country = ""

st.title("Ambil Data dari URL dengan Playwright")
st.caption("Tekan tombol 'Go' untuk mengambil data dari URL.")

st.sidebar.header("Opsi")
take_screenshot = st.sidebar.checkbox("Ambil screenshot", value=False)
get_html = st.sidebar.checkbox("Get HTML", value=False)

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


st.subheader("Playwright Local Browser")
st.caption(
    "Playwright akan mencoba menjalankan `python -m playwright install chromium` sekali "
    "per runtime, tapi jalankan manual selama pengembangan agar startup lebih cepat."
)
st.markdown("---")

with st.expander("Info Sistem"):
    st.code(_system_info_text(), language="text")
st.markdown("---")

url_input = st.text_input("Masukkan URL yang ingin diambil datanya", value="")

if st.button("Go"):
    normalized_url = _ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
    else:
        final_proxy = proxy_input if proxy_input else None

        with st.spinner("Memuat dan memproses halaman..."):
            try:
                result = fetch_page(
                    normalized_url, 
                    take_screenshot=take_screenshot, 
                    get_html=get_html,
                    proxy=final_proxy
                )

                st.success("Operasi Selesai!")
                
                st.subheader("Title")
                st.code(result.get("title", "-"))

                if take_screenshot and "screenshot" in result:
                    st.subheader("Screenshot")
                    st.image(result["screenshot"])
                    st.download_button(
                        "Download screenshot",
                        data=result["screenshot"],
                        file_name="screenshot.png",
                        mime="image/png",
                    )

                if get_html and "html" in result:
                    st.subheader("HTML Content")
                    st.code(result["html"], language="html")
                    st.download_button(
                        "Download HTML",
                        data=result["html"],
                        file_name="page.html",
                        mime="text/html",
                    )

            except PlaywrightError as exc:
                st.error(f"Gagal memproses halaman: {exc}")