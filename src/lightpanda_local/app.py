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


def fetch_title(
    url: str,
    cdp_endpoint: str,
    *,
    wait_full_render: bool = False,
    capture_screenshot: bool = False,
    full_page_screenshot: bool = False,
    timeout_ms: int = 60_000,
) -> tuple[str, bytes | None]:
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
        wait_until = "load" if wait_full_render else "domcontentloaded"
        page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        if wait_full_render:
            try:
                page.wait_for_load_state("networkidle", timeout=min(10_000, timeout_ms))
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_function(
                    "typeof document !== 'undefined' && !!document.title && document.title.length > 0",
                    timeout=min(5_000, timeout_ms),
                )
            except PlaywrightTimeoutError:
                pass

        title = page.title()
        screenshot_bytes: bytes | None = None
        if capture_screenshot:
            screenshot_bytes = page.screenshot(type="png", full_page=full_page_screenshot)
        page.close()
        if owns_context:
            context.close()
        browser.close()
        return title, screenshot_bytes


def main() -> None:
    st.set_page_config(page_title="Lightpanda CDP Scraper", layout="centered")
    st.title("Lightpanda + Playwright (CDP) — Streamlit Scraper")

    default_cdp = os.environ.get("LIGHTPANDA_CDP_WS", "ws://127.0.0.1:9222")

    with st.sidebar:
        st.subheader("Connection")
        cdp_endpoint = st.text_input("CDP endpoint", value=default_cdp)
        autostart = st.toggle("Autostart Lightpanda (Linux)", value=True)
        st.divider()
        st.subheader("Navigation")
        wait_full_render = st.toggle(
            "Wait for full render (JS)",
            value=False,
            help="If enabled: waits longer (load/network idle) and waits for document.title to be non-empty.",
        )
        st.divider()
        st.subheader("Output")
        show_screenshot = st.toggle(
            "Show screenshot",
            value=False,
            help="Captures a screenshot in-memory and shows it in the app (not saved on the server).",
        )
        full_page_screenshot = st.toggle(
            "Full page screenshot",
            value=False,
            disabled=not show_screenshot,
            help="If enabled, captures the full scrollable page (may be slower/larger).",
        )

    url_input = st.text_input("Website URL", placeholder="https://example.com")
    go = st.button("Go", type="primary")

    if not go:
        return

    url = normalize_url(url_input)
    if not url:
        st.error("Please enter a URL first.")
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
                st.error(f"Failed to start Lightpanda: {e}")
                st.stop()

    with st.spinner("Scraping..."):
        try:
            title, screenshot_bytes = fetch_title(
                url,
                cdp_endpoint,
                wait_full_render=wait_full_render,
                capture_screenshot=show_screenshot,
                full_page_screenshot=full_page_screenshot,
                timeout_ms=60_000,
            )
        except PlaywrightTimeoutError:
            st.error("Timeout while loading the page.")
            st.stop()
        except PlaywrightError as e:
            st.error(f"Playwright error: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            st.stop()

    if not title:
        st.warning(
            "The page title is empty. Try enabling 'Wait for full render (JS)' in the sidebar."
        )
    else:
        st.success("Done.")
    st.write({"url": url, "title": title})
    if screenshot_bytes is not None:
        with st.expander("Screenshot", expanded=True):
            st.image(screenshot_bytes)


if __name__ == "__main__":
    main()
