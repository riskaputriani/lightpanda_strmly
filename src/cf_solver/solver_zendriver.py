from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
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

COMMAND: Final[str] = (
    '{name}: {binary} --header "Cookie: {cookies}" --header "User-Agent: {user_agent}" {url}'
)


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
        browser_executable_path: Optional[str] = None,
    ) -> None:
        self.cdp_url = cdp_url
        self.user_agent = user_agent
        self._timeout = timeout
        self.http2 = http2
        self.http3 = http3
        self.headless = headless
        self.proxy = proxy
        self.browser_executable_path = browser_executable_path
        self.driver = None
        self._standalone_mode = cdp_url is None

    async def __aenter__(self) -> CloudflareSolver:
        if self._standalone_mode:
            # Standalone mode: launch new browser
            config = zendriver.Config(
                headless=self.headless,
                browser_executable_path=self.browser_executable_path,
            )

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
                    brand="Google Chrome",
                    version=str(device.browser.version[0]),
                ),
            ],
            full_version_list=[
                UserAgentBrandVersion(brand="Not)A;Brand", version="8"),
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


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="A simple program for scraping Cloudflare clearance (cf_clearance) cookies. "
                    "Supports both standalone mode (launches own browser) and CDP mode (connects to existing browser)."
    )

    parser.add_argument(
        "url",
        metavar="URL",
        help="The URL to scrape the Cloudflare clearance cookie from",
        type=str,
    )

    parser.add_argument(
        "-cdp",
        "--cdp-url",
        default=None,
        help="The CDP WebSocket URL to connect to (e.g., ws://localhost:9222/devtools/browser/xxx). "
             "If not provided, will launch a standalone browser instance.",
        type=str,
    )

    parser.add_argument(
        "-f",
        "--file",
        default=None,
        help="The file to write the Cloudflare clearance cookie information to, in JSON format",
        type=str,
    )

    parser.add_argument(
        "-t",
        "--timeout",
        default=30,
        help="The timeout in seconds to use for solving challenges",
        type=float,
    )

    parser.add_argument(
        "-p",
        "--proxy",
        default=None,
        help="The proxy server URL to use for the browser requests (standalone mode only)",
        type=str,
    )

    parser.add_argument(
        "-bep",
        "--browser-executable-path",
        default=None,
        help="The path to the browser executable (e.g., /usr/bin/google-chrome)",
        type=str,
    )

    parser.add_argument(
        "-ua",
        "--user-agent",
        default=None,
        help="The user agent to use for the browser requests",
        type=str,
    )

    parser.add_argument(
        "--disable-http2",
        action="store_true",
        help="Disable the usage of HTTP/2 for the browser requests (standalone mode only)",
    )

    parser.add_argument(
        "--disable-http3",
        action="store_true",
        help="Disable the usage of HTTP/3 for the browser requests (standalone mode only)",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run the browser in headed mode (standalone mode only)",
    )

    parser.add_argument(
        "-ac",
        "--all-cookies",
        action="store_true",
        help="Retrieve all cookies from the page, not just the Cloudflare clearance cookie",
    )

    parser.add_argument(
        "-c",
        "--curl",
        action="store_true",
        help="Get the cURL command for the request with the cookies and user agent",
    )

    parser.add_argument(
        "-w",
        "--wget",
        action="store_true",
        help="Get the Wget command for the request with the cookies and user agent",
    )

    parser.add_argument(
        "-a",
        "--aria2",
        action="store_true",
        help="Get the aria2 command for the request with the cookies and user agent",
    )

    args = parser.parse_args()

    logging.basicConfig(
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )

    logging.getLogger("zendriver").setLevel(logging.WARNING)
    
    if args.cdp_url:
        logging.info("Connecting to browser via CDP at %s...", args.cdp_url)
        mode = "CDP"
    else:
        logging.info("Launching %s browser...", "headed" if args.headed else "headless")
        mode = "standalone"

    challenge_messages = {
        ChallengePlatform.JAVASCRIPT: "Solving Cloudflare challenge [JavaScript]...",
        ChallengePlatform.MANAGED: "Solving Cloudflare challenge [Managed]...",
        ChallengePlatform.INTERACTIVE: "Solving Cloudflare challenge [Interactive]...",
    }

    user_agent = get_chrome_user_agent() if args.user_agent is None else args.user_agent

    try:
        async with CloudflareSolver(
            cdp_url=args.cdp_url,
            user_agent=user_agent,
            timeout=args.timeout,
            http2=not args.disable_http2,
            http3=not args.disable_http3,
            headless=not args.headed,
            proxy=args.proxy,
            browser_executable_path=args.browser_executable_path,
        ) as solver:
            logging.info("Going to %s...", args.url)

            try:
                await solver.driver.get(args.url)
            except asyncio.TimeoutError as err:
                logging.error(err)
                return

            all_cookies = await solver.get_cookies()
            clearance_cookie = solver.extract_clearance_cookie(all_cookies)

            if clearance_cookie is None:
                await solver.set_user_agent_metadata(await solver.get_user_agent())
                challenge_platform = await solver.detect_challenge()

                if challenge_platform is None:
                    logging.error("No Cloudflare challenge detected.")
                    return

                logging.info(challenge_messages[challenge_platform])

                try:
                    await solver.solve_challenge()
                except asyncio.TimeoutError:
                    pass

                all_cookies = await solver.get_cookies()
                clearance_cookie = solver.extract_clearance_cookie(all_cookies)

            user_agent = await solver.get_user_agent()

    except Exception as e:
        if args.cdp_url:
            logging.error(f"Failed to connect via CDP: {e}")
            logging.info("Make sure the browser is running with CDP enabled")
            logging.info("Example for Chrome: chromium --remote-debugging-port=9222 --headless=new")
        else:
            logging.error(f"Failed to launch browser: {e}")
        return

    if clearance_cookie is None:
        logging.error("Failed to retrieve a Cloudflare clearance cookie.")
        return

    cookie_string = "; ".join(
        f'{cookie["name"]}={cookie["value"]}' for cookie in all_cookies
    )

    if args.all_cookies:
        logging.info("All cookies: %s", cookie_string)
    else:
        logging.info("Cookie: cf_clearance=%s", clearance_cookie["value"])

    logging.info("User agent: %s", user_agent)

    if args.curl:
        logging.info(
            COMMAND.format(
                name="cURL",
                binary="curl",
                cookies=(
                    cookie_string
                    if args.all_cookies
                    else f'cf_clearance={clearance_cookie["value"]}'
                ),
                user_agent=user_agent,
                url=(
                    f"--proxy {args.proxy} {args.url}"
                    if args.proxy is not None and mode == "standalone"
                    else args.url
                ),
            )
        )

    if args.wget:
        if args.proxy is not None and mode == "standalone":
            logging.warning(
                "Proxies must be set in an environment variable or config file for Wget."
            )

        logging.info(
            COMMAND.format(
                name="Wget",
                binary="wget",
                cookies=(
                    cookie_string
                    if args.all_cookies
                    else f'cf_clearance={clearance_cookie["value"]}'
                ),
                user_agent=user_agent,
                url=args.url,
            )
        )

    if args.aria2:
        if args.proxy is not None and args.proxy.casefold().startswith("socks") and mode == "standalone":
            logging.warning("SOCKS proxies are not supported by aria2.")

        logging.info(
            COMMAND.format(
                name="aria2",
                binary="aria2c",
                cookies=(
                    cookie_string
                    if args.all_cookies
                    else f'cf_clearance={clearance_cookie["value"]}'
                ),
                user_agent=user_agent,
                url=(
                    f"--all-proxy {args.proxy} {args.url}"
                    if args.proxy is not None and mode == "standalone"
                    else args.url
                ),
            )
        )

    if args.file is None:
        return

    logging.info("Writing Cloudflare clearance cookie information to %s...", args.file)

    try:
        with open(args.file, encoding="utf-8") as file:
            json_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        json_data: Dict[str, List[Dict[str, Any]]] = {}

    local_timezone = datetime.now(timezone.utc).astimezone().tzinfo
    unix_timestamp = clearance_cookie["expires"] - timedelta(days=365).total_seconds()
    timestamp = datetime.fromtimestamp(unix_timestamp, tz=local_timezone).isoformat()

    json_data.setdefault(clearance_cookie["domain"], []).append(
        {
            "unix_timestamp": int(unix_timestamp),
            "timestamp": timestamp,
            "cf_clearance": clearance_cookie["value"],
            "cookies": all_cookies,
            "user_agent": user_agent,
            "proxy": args.proxy if mode == "standalone" else None,
        }
    )

    with open(args.file, "w", encoding="utf-8") as file:
        json.dump(json_data, file, indent=4)


if __name__ == "__main__":
    asyncio.run(main())