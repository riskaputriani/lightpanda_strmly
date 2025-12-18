import asyncio
import shutil
import subprocess
import sys

import streamlit as st
from playwright.async_api import Error, async_playwright

from src.setup import install_google_chrome

# Ensure Google Chrome is present (especially on Streamlit Cloud/Linux).
install_google_chrome()


@st.cache_resource
def get_chrome_executable_path() -> str | None:
    """
    Return the path to a Chrome binary if available.
    """
    return shutil.which("google-chrome") or shutil.which("chrome")


@st.cache_resource
def ensure_playwright_chrome_installed() -> None:
    """
    Install Playwright's Chrome channel if it is missing.
    """
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chrome"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="ignore").strip()
        message = stderr or str(exc)
        raise RuntimeError(f"Failed to install Playwright Chrome: {message}") from exc


def _normalize_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


async def scrape_with_playwright(
    url: str, *, take_screenshot: bool, get_html: bool
) -> dict:
    """
    Open the URL with Playwright + Chrome, then return the title plus optional assets.
    """
    results: dict = {}
    launch_kwargs = {"headless": True}
    chrome_path = get_chrome_executable_path()

    if chrome_path:
        launch_kwargs["executable_path"] = chrome_path
    else:
        ensure_playwright_chrome_installed()
        launch_kwargs["channel"] = "chrome"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**launch_kwargs)
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


st.title("Playwright Chrome Scraper")
st.caption(
    "Enter a URL to fetch the page title with Playwright + Google Chrome, "
    "optionally including a full-page screenshot and HTML."
)

url_input = st.text_input("URL to scrape", placeholder="https://example.com")
take_screenshot = st.checkbox("Capture screenshot (full page)")
get_html = st.checkbox("Fetch HTML")

if st.button("Scrape"):
    if not url_input:
        st.warning("Please enter a URL.")
    else:
        target_url = _normalize_url(url_input.strip())
        with st.spinner("Working with Playwright + Google Chrome..."):
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
                    "Playwright failed to launch Chrome. "
                    "We tried to auto-install the Playwright Chrome channel. "
                    "If it persists, run `python -m playwright install chrome` manually. "
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
