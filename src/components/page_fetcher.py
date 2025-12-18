from typing import Dict, Optional
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from .browser_manager import get_chrome_path
from .cookies import sanitize_cookies


def _build_proxy_config(proxy: str) -> Dict[str, str]:
    proxy_parts = urlparse(proxy)
    server = f"{proxy_parts.scheme}://{proxy_parts.hostname}"
    if proxy_parts.port:
        server += f":{proxy_parts.port}"

    proxy_config: Dict[str, str] = {"server": server}
    if proxy_parts.username:
        proxy_config["username"] = proxy_parts.username
    if proxy_parts.password:
        proxy_config["password"] = proxy_parts.password
    return proxy_config


def fetch_page(
    url: str,
    *,
    take_screenshot: bool = False,
    get_html: bool = False,
    proxy: Optional[str] = None,
    cookies: Optional[list[dict]] = None,
    user_agent: Optional[str] = None,
    timeout: int = 30_000,
) -> Dict[str, object]:
    """Use Playwright to launch a browser, get page data, and detect CF challenges."""
    chrome_path = get_chrome_path()
    context_options = {}
    if proxy:
        context_options["proxy"] = _build_proxy_config(proxy)

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

                page_title = page.title().strip()
                lower_title = page_title.lower()
                if "just a moment" in lower_title or lower_title.startswith("challenge"):
                    return {"status": "cloudflare_challenge"}

                result: Dict[str, object] = {"status": "ok", "title": page_title}
                if take_screenshot:
                    result["screenshot"] = page.screenshot(full_page=True)
                if get_html:
                    result["html"] = page.content()

                return result

            except PlaywrightError as err:
                return {"status": "error", "message": str(err)}
