import asyncio
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import streamlit as st
from playwright.async_api import Error, async_playwright

from src.setup import install_google_chrome

# Prefer system Chrome if available; otherwise fall back to Playwright's Chromium (user install).
install_google_chrome()

# Use a local, user-writable cache for Playwright browsers to avoid sudo/apt.
PLAYWRIGHT_BROWSERS_DIR = Path(".pw-browsers").resolve()
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PLAYWRIGHT_BROWSERS_DIR))
LOCAL_LIB_DIR = Path(".pw-libs").resolve()


@st.cache_resource
def get_chrome_executable_path() -> str | None:
    """
    Return the path to a Chrome binary if available.
    """
    return shutil.which("google-chrome") or shutil.which("chrome")


@st.cache_resource
def ensure_playwright_chromium_installed() -> None:
    """
    Install Playwright's bundled Chromium into a local folder (no sudo required).
    """
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)

    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="ignore").strip()
        message = stderr or str(exc)
        raise RuntimeError(
            "Failed to install Playwright Chromium without sudo. "
            "Try running: PLAYWRIGHT_BROWSERS_PATH=.pw-browsers python -m playwright install chromium\n"
            f"Details: {message}"
        ) from exc


def _normalize_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def _ensure_local_nspr_nss() -> Path | None:
    """
    On minimal Linux images, Playwright's Chromium may miss libnspr4/libnss3.
    Download and extract those libs into a local directory (no sudo) and return the lib path.
    """
    if platform.system() != "Linux":
        return None

    target_lib = LOCAL_LIB_DIR / "usr" / "lib" / "x86_64-linux-gnu"
    if (target_lib / "libnspr4.so").exists():
        return target_lib

    LOCAL_LIB_DIR.mkdir(parents=True, exist_ok=True)

    deb_urls = [
        # Versions compatible with Debian/Ubuntu-like images; adjust if URLs break.
        "https://deb.debian.org/debian/pool/main/n/nspr/libnspr4_4.35-1_amd64.deb",
        "https://deb.debian.org/debian/pool/main/n/nss/libnss3_3.101-1_amd64.deb",
    ]

    for url in deb_urls:
        deb_path = LOCAL_LIB_DIR / Path(url).name
        try:
            if not deb_path.exists():
                urllib.request.urlretrieve(url, deb_path)
            subprocess.run(
                ["dpkg-deb", "-x", str(deb_path), str(LOCAL_LIB_DIR)],
                check=True,
                capture_output=True,
            )
        except Exception:
            # If we cannot fetch/extract, leave and rely on higher-level error handling.
            return None

    if (target_lib / "libnspr4.so").exists():
        return target_lib

    return None


async def scrape_with_playwright(
    url: str, *, take_screenshot: bool, get_html: bool
) -> dict:
    """
    Open the URL with Playwright (system Chrome if present, otherwise bundled Chromium),
    then return the title plus optional assets.
    """
    results: dict = {}
    launch_kwargs = {"headless": True}
    chrome_path = get_chrome_executable_path()

    if chrome_path:
        launch_kwargs["executable_path"] = chrome_path
    else:
        ensure_playwright_chromium_installed()

    browser_env = os.environ.copy()
    extra_lib_path = _ensure_local_nspr_nss()
    if extra_lib_path:
        current_ld = browser_env.get("LD_LIBRARY_PATH", "")
        browser_env["LD_LIBRARY_PATH"] = (
            f"{extra_lib_path}:{current_ld}" if current_ld else f"{extra_lib_path}"
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**launch_kwargs, env=browser_env)
        page = await browser.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded")
            results["title"] = await page.title()

            if take_screenshot:
                results["screenshot"] = await page.screenshot(full_page=True)

            if get_html:
                results["html"] = await page.content()
        finally:
            await browser.close()

    return results


st.title("Playwright Chrome/Chromium Scraper")
st.caption(
    "Enter a URL to fetch the page title with Playwright using system Chrome if available, "
    "otherwise a bundled Chromium; optional full-page screenshot and HTML."
)

url_input = st.text_input("URL to scrape", placeholder="https://example.com")
take_screenshot = st.checkbox("Capture screenshot (full page)")
get_html = st.checkbox("Fetch HTML")

if st.button("Scrape"):
    if not url_input:
        st.warning("Please enter a URL.")
    else:
        target_url = _normalize_url(url_input.strip())
        with st.spinner("Working with Playwright (Chrome/Chromium)..."):
            try:
                results = asyncio.run(
                    scrape_with_playwright(
                        target_url,
                        take_screenshot=take_screenshot,
                        get_html=get_html,
                    )
                )
            except Error as exc:
                st.error(
                    "Playwright failed to launch Chromium/Chrome. "
                    "We tried to auto-install Playwright's bundled Chromium without sudo. "
                    "If it persists, run "
                    "`PLAYWRIGHT_BROWSERS_PATH=.pw-browsers python -m playwright install chromium` manually. "
                    f"Details: {exc}"
                )
            except RuntimeError as exc:
                st.error(str(exc))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Scrape failed: {exc}")
            else:
                st.subheader("Title")
                st.write(results.get("title", "-"))

                if take_screenshot and "screenshot" in results:
                    st.subheader("Screenshot")
                    st.image(results["screenshot"])
                    st.download_button(
                        "Download screenshot",
                        data=results["screenshot"],
                        file_name="screenshot.png",
                        mime="image/png",
                    )

                if get_html and "html" in results:
                    st.subheader("HTML")
                    st.code(results["html"], language="html")
                    st.download_button(
                        "Download HTML",
                        data=results["html"],
                        file_name="page.html",
                        mime="text/html",
                    )
