import asyncio
import shutil

import streamlit as st
from playwright.async_api import Error, async_playwright

from src.setup import install_google_chrome

# Pastikan Google Chrome tersedia (khususnya saat jalan di Streamlit Cloud/Linux)
install_google_chrome()


@st.cache_resource
def get_chrome_executable_path() -> str | None:
    """
    Lokasi binary Google Chrome di mesin (jika tersedia).
    """
    return shutil.which("google-chrome") or shutil.which("chrome")


def _normalize_url(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


async def scrape_with_playwright(
    url: str, *, take_screenshot: bool, get_html: bool
) -> dict:
    """
    Buka URL memakai Playwright + Google Chrome, lalu ambil title dan opsi tambahan.
    """
    results: dict = {}
    launch_kwargs = {"headless": True}
    chrome_path = get_chrome_executable_path()

    if chrome_path:
        launch_kwargs["executable_path"] = chrome_path
    else:
        # Fallback ke channel Chrome bawaan Playwright (butuh `playwright install chrome`)
        launch_kwargs["channel"] = "chrome"

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
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
    "Masukkan URL, ambil title memakai Playwright + Google Chrome, "
    "dengan opsi screenshot dan HTML."
)

url_input = st.text_input("URL yang ingin di-scrape", placeholder="https://example.com")
take_screenshot = st.checkbox("Ambil screenshot (full page)")
get_html = st.checkbox("Ambil HTML")

if st.button("Scrape"):
    if not url_input:
        st.warning("Mohon masukkan URL.")
    else:
        target_url = _normalize_url(url_input.strip())
        with st.spinner("Memproses dengan Playwright + Google Chrome..."):
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
                    "Gagal menjalankan Playwright. "
                    "Pastikan browser Playwright ter-install (`python -m playwright install chrome`). "
                    f"Detail: {exc}"
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Gagal scrape: {exc}")
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
