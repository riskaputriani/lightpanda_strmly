from __future__ import annotations
import streamlit as st
import asyncio
import json
from urllib.parse import urlparse

import argparse
import logging
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Final, Iterable, List, Optional

import latest_user_agents
import user_agents
import zendriver
from selenium_authenticated_proxy import SeleniumAuthenticatedProxy
from zendriver import cdp
from zendriver.cdp.emulation import UserAgentBrandVersion, UserAgentMetadata
from zendriver.cdp.network import T_JSON_DICT, Cookie
from zendriver.core.element import Element

import os
from pathlib import Path

def _iter_playwright_browser_roots() -> List[Path]:
    """
    Return likely locations where Playwright stores downloaded browsers.
    """
    roots: List[Path] = []
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        roots.append(Path(env_path))

    home = Path.home()
    roots.extend(
        [
            home / ".cache" / "ms-playwright",
            Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright",
            home / "Library" / "Caches" / "ms-playwright",
        ]
    )
    return [p for p in roots if p]


def find_playwright_chromium_executable() -> Optional[str]:
    """
    Try to locate a Playwright-managed Chromium executable.
    """
    platform_paths = [
        ("chrome-linux", "chrome"),
        ("chrome-win", "chrome.exe"),
        ("chrome-mac", "Chromium.app/Contents/MacOS/Chromium"),
    ]

    for root in _iter_playwright_browser_roots():
        if not root.exists():
            continue
        for chromium_dir in sorted(root.glob("chromium-*"), reverse=True):
            for platform_dir, exe_name in platform_paths:
                candidate = chromium_dir / platform_dir / exe_name
                if candidate.exists():
                    return str(candidate)
    return None

def get_chrome_user_agent() -> str:
    """
    Get a random up-to-date Chrome user agent string.

    Returns
    -------
    str
        The user agent string.
    """
    chrome_user_agents = [
        user_agent
        for user_agent in latest_user_agents.get_latest_user_agents()
        if "Chrome" in user_agent and "Edg" not in user_agent
    ]

    return random.choice(chrome_user_agents)


class ChallengePlatform(Enum):
    """Cloudflare challenge platform types."""

    JAVASCRIPT = "non-interactive"
    MANAGED = "managed"
    INTERACTIVE = "interactive"


class CloudflareSolver:
    """
    A class for solving Cloudflare challenges with Zendriver.

    Parameters
    ----------
    cdp_url : Optional[str]
        The CDP WebSocket URL to connect to. If None, launches a new browser instance.
    user_agent : Optional[str]
        The user agent string to use for the browser requests.
    timeout : float
        The timeout in seconds to use for browser actions and solving challenges.
    http2 : bool
        Enable or disable the usage of HTTP/2 for the browser requests (standalone mode only).
    http3 : bool
        Enable or disable the usage of HTTP/3 for the browser requests (standalone mode only).
    headless : bool
        Enable or disable headless mode for the browser (standalone mode only).
    proxy : Optional[str]
        The proxy server URL to use for the browser requests (standalone mode only).
    """

    def __init__(
        self,
        *,
        cdp_url: Optional[str],
        user_agent: Optional[str],
        timeout: float,
        http2: bool = True,
        http3: bool = True,
        headless: bool = True,
        proxy: Optional[str] = None,
    ) -> None:
        self.cdp_url = cdp_url
        self.user_agent = user_agent
        self._timeout = timeout
        self.http2 = http2
        self.http3 = http3
        self.headless = headless
        self.proxy = proxy
        self.driver = None
        self._standalone_mode = cdp_url is None

    async def __aenter__(self) -> CloudflareSolver:
        if self._standalone_mode:
            # Standalone mode: launch new browser
            browser_executable_path = find_playwright_chromium_executable()
            config = zendriver.Config(headless=self.headless, browser_executable_path=browser_executable_path)

            if self.user_agent is not None:
                config.add_argument(f"--user-agent={self.user_agent}")

            if not self.http2:
                config.add_argument("--disable-http2")

            if not self.http3:
                config.add_argument("--disable-quic")

            auth_proxy = SeleniumAuthenticatedProxy(self.proxy)
            auth_proxy.enrich_chrome_options(config)

            self.driver = zendriver.Browser(config)
            await self.driver.start()
        else:
            # CDP mode: connect to existing browser
            self.driver = await zendriver.Browser.connect(self.cdp_url)
            
            # Set user agent if provided
            if self.user_agent:
                await self.driver.main_tab.evaluate(
                    f'Object.defineProperty(navigator, "userAgent", {{get: () => "{self.user_agent}"}})'
                )
        
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self.driver:
            await self.driver.stop()

    @staticmethod
    def _format_cookies(cookies: Iterable[Cookie]) -> List[T_JSON_DICT]:
        """
        Format cookies into a list of JSON cookies.

        Parameters
        ----------
        cookies : Iterable[Cookie]
            List of cookies.

        Returns
        -------
        List[T_JSON_DICT]
            List of JSON cookies.
        """
        return [cookie.to_json() for cookie in cookies]

    @staticmethod
    def extract_clearance_cookie(
        cookies: Iterable[T_JSON_DICT],
    ) -> Optional[T_JSON_DICT]:
        """
        Extract the Cloudflare clearance cookie from a list of cookies.

        Parameters
        ----------
        cookies : Iterable[T_JSON_DICT]
            List of cookies.

        Returns
        -------
        Optional[T_JSON_DICT]
            The Cloudflare clearance cookie. Returns None if the cookie is not found.
        """
        for cookie in cookies:
            if cookie["name"] == "cf_clearance":
                return cookie

        return None

    async def get_user_agent(self) -> str:
        """
        Get the current user agent string.

        Returns
        -------
        str
            The user agent string.
        """
        return await self.driver.main_tab.evaluate("navigator.userAgent")

    async def get_cookies(self) -> List[T_JSON_DICT]:
        """
        Get all cookies from the current page.

        Returns
        -------
        List[T_JSON_DICT]
            List of cookies.
        """
        return self._format_cookies(await self.driver.cookies.get_all())

    async def set_user_agent_metadata(self, user_agent: str) -> None:
        """
        Set the user agent metadata for the browser.

        Parameters
        ----------
        user_agent : str
            The user agent string to parse information from.
        """
        device = user_agents.parse(user_agent)

        metadata = UserAgentMetadata(
            architecture="x86",
            bitness="64",
            brands=[
                UserAgentBrandVersion(brand="Not)A;Brand", version="8"),
                UserAgentBrandVersion(
                    brand="Chromium", version=str(device.browser.version[0])
                ),
                UserAgentBrandVersion(
                    brand="Google Chrome",
                    version=str(device.browser.version[0]),
                ),
            ],
            full_version_list=[
                UserAgentBrandVersion(brand="Not)A;Brand", version="8"),
                UserAgentBrandVersion(
                    brand="Chromium", version=str(device.browser.version[0])
                ),
                UserAgentBrandVersion(
                    brand="Google Chrome",
                    version=str(device.browser.version[0]),
                ),
            ],
            mobile=device.is_mobile,
            model=device.device.model or "",
            platform=device.os.family,
            platform_version=device.os.version_string,
            full_version=device.browser.version_string,
            wow64=False,
        )

        self.driver.main_tab.feed_cdp(
            cdp.network.set_user_agent_override(
                user_agent, user_agent_metadata=metadata
            )
        )

    async def detect_challenge(self) -> Optional[ChallengePlatform]:
        """
        Detect the Cloudflare challenge platform on the current page.

        Returns
        -------
        Optional[ChallengePlatform]
            The Cloudflare challenge platform.
        """
        html = await self.driver.main_tab.get_content()

        for platform in ChallengePlatform:
            if f"cType: '{platform.value}'" in html:
                return platform

        return None

    async def solve_challenge(self) -> None:
        """Solve the Cloudflare challenge on the current page."""
        start_timestamp = datetime.now()

        while (
            self.extract_clearance_cookie(await self.get_cookies()) is None
            and await self.detect_challenge() is not None
            and (datetime.now() - start_timestamp).seconds < self._timeout
        ):
            try:
                widget_input = await self.driver.main_tab.find("input")

                if widget_input.parent is None or not widget_input.parent.shadow_roots:
                    await asyncio.sleep(0.25)
                    continue

                challenge = Element(
                    widget_input.parent.shadow_roots[0],
                    self.driver.main_tab,
                    widget_input.parent.tree,
                )

                challenge = challenge.children[0]

                if (
                    isinstance(challenge, Element)
                    and "display: none;" not in challenge.attrs["style"]
                ):
                    await asyncio.sleep(1)

                    try:
                        await challenge.get_position()
                    except Exception:
                        continue

                    await challenge.mouse_click()
            except asyncio.TimeoutError:
                pass


async def solve_cloudflare_challenge(url: str, proxy: str | None = None):
    user_agent = get_chrome_user_agent()
    async with CloudflareSolver(
        cdp_url=None,
        user_agent=user_agent,
        timeout=30,
        proxy=proxy,
    ) as solver:
        await solver.driver.get(url)
        all_cookies = await solver.get_cookies()
        clearance_cookie = solver.extract_clearance_cookie(all_cookies)
        if clearance_cookie is None:
            await solver.set_user_agent_metadata(await solver.get_user_agent())
            challenge_platform = await solver.detect_challenge()
            if challenge_platform is None:
                return {"error": "No Cloudflare challenge detected."}
            
            await solver.solve_challenge()
            all_cookies = await solver.get_cookies()
            clearance_cookie = solver.extract_clearance_cookie(all_cookies)

        user_agent = await solver.get_user_agent()

        if clearance_cookie is None:
            return {"error": "Failed to retrieve a Cloudflare clearance cookie."}

        domain = clearance_cookie["domain"]
        json_data = {
            domain: [
                {
                    "unix_timestamp": int(clearance_cookie["expires"] - timedelta(days=365).total_seconds()),
                    "timestamp": datetime.fromtimestamp(clearance_cookie["expires"] - timedelta(days=365).total_seconds(), tz=timezone.utc).isoformat(),
                    "cf_clearance": clearance_cookie["value"],
                    "cookies": all_cookies,
                    "user_agent": user_agent,
                    "proxy": proxy,
                }
            ]
        }
        return json_data


st.title("Cloudflare Solver")

url = st.text_input("Enter the URL to solve")
proxy = st.text_input("Enter proxy (optional)")

if st.button("Solve"):
    if url:
        with st.spinner("Solving Cloudflare challenge..."):
            try:
                # Run the async solver in the Streamlit event loop
                loop = asyncio.get_running_loop()
                result = loop.run_until_complete(solve_cloudflare_challenge(url, proxy if proxy else None))
                st.json(result)
            except RuntimeError:
                # If there is no running event loop, create a new one
                result = asyncio.run(solve_cloudflare_challenge(url, proxy if proxy else None))
                st.json(result)
    else:
        st.error("Please enter a URL")