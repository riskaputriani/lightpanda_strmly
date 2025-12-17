from __future__ import annotations

import os
from urllib.parse import urlparse

import streamlit as st
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from lightpanda_local.lightpanda_service import ensure_lightpanda_server, parse_cdp_target


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://{url}"
    return url


def fetch_title(url: str, cdp_endpoint: str, timeout_ms: int = 60_000) -> str:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint)
        owns_context = True
        try:
            context = browser.new_context()
        except PlaywrightError:
            owns_context = False
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context()

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        title = page.title()
        page.close()
        if owns_context:
            context.close()
        browser.close()
        return title


def main() -> None:
    st.set_page_config(page_title="Lightpanda CDP Scraper", layout="centered")
    st.title("Lightpanda + Playwright (CDP) — Streamlit Scraper")

    default_cdp = os.environ.get("LIGHTPANDA_CDP_WS", "ws://127.0.0.1:9222")

    with st.sidebar:
        st.subheader("Connection")
        cdp_endpoint = st.text_input("CDP endpoint", value=default_cdp)
        autostart = st.toggle("Autostart Lightpanda (Linux)", value=True)

    url_input = st.text_input("Website URL", placeholder="https://example.com")
    go = st.button("Go", type="primary")

    if not go:
        return

    url = normalize_url(url_input)
    if not url:
        st.error("Masukkan URL dulu.")
        st.stop()

    try:
        parse_cdp_target(cdp_endpoint)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    if autostart:
        with st.status("Starting Lightpanda (if needed)...", expanded=False):
            try:
                process = ensure_lightpanda_server(cdp_endpoint)
                if process is not None:
                    st.session_state["lightpanda_process"] = process
            except Exception as e:
                st.error(f"Gagal start Lightpanda: {e}")
                st.stop()

    with st.spinner("Scraping..."):
        try:
            title = fetch_title(url, cdp_endpoint)
        except PlaywrightTimeoutError:
            st.error("Timeout saat membuka halaman.")
            st.stop()
        except PlaywrightError as e:
            st.error(f"Playwright error: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            st.stop()

    st.success("Selesai.")
    st.write({"url": url, "title": title})


if __name__ == "__main__":
    main()
