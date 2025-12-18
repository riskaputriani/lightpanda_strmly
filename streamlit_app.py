import asyncio
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st
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


def fetch_page(
    url: str, *, take_screenshot: bool = False, timeout: int = 30_000
) -> dict:
    """Use Playwright to launch a local Chromium browser, return title and optional screenshot bytes."""
    ensure_playwright_browsers_installed()
    with sync_playwright() as playwright:
        with playwright.chromium.launch(headless=True) as browser:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            result = {"title": page.title()}

            if take_screenshot:
                result["screenshot"] = page.screenshot(full_page=True)

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
        f"Python      : {sys.version.replace('\\n', ' ')}",
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


st.set_page_config(page_title="Playwright Title Reader", layout="centered")
st.title("Ambil Title dari URL dengan Playwright")
st.caption("Tekan tombol agar Playwright meluncurkan Chromium lokal dan membaca judul.")

st.sidebar.header("Opsi")
screenshot_button = st.sidebar.button("Ambil screenshot (full page)")

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

if st.button("Dapatkan Title"):
    normalized_url = _ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
    else:
        with st.spinner("Memuat dan membaca title..."):
            try:
                result = fetch_page(normalized_url, take_screenshot=False)
                st.success("Title ditemukan:")
                st.code(result.get("title", "-"))
            except PlaywrightError as exc:
                st.error(f"Gagal mengambil title: {exc}")

if screenshot_button:
    normalized_url = _ensure_scheme(url_input)
    if not normalized_url:
        st.error("Silakan masukkan URL terlebih dahulu.")
    else:
        with st.spinner("Memuat dan mengambil screenshot..."):
            try:
                result = fetch_page(normalized_url, take_screenshot=True)
                st.success("Screenshot berhasil diambil:")
                st.code(f"URL: {normalized_url}\nTitle: {result.get('title', '-')}")

                if "screenshot" in result:
                    st.subheader("Screenshot (tidak disimpan ke disk)")
                    st.image(result["screenshot"])
                    st.download_button(
                        "Download screenshot",
                        data=result["screenshot"],
                        file_name="screenshot.png",
                        mime="image/png",
                    )
            except PlaywrightError as exc:
                st.error(f"Gagal mengambil screenshot: {exc}")
