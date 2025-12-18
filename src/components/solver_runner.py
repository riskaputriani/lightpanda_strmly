import asyncio
from typing import Dict, List, Optional

import streamlit as st

from cf_solver.solver_zendriver import CloudflareSolver, get_chrome_user_agent

from .browser_manager import get_chrome_path


def run_solver(url: str, proxy: Optional[str]) -> Dict[str, object]:
    """
    Run the Cloudflare solver as a standalone process and return cookies plus the user agent.
    """
    try:
        browser_path = get_chrome_path()
    except Exception as err:
        st.error(f"Could not determine Chrome path: {err}")
        return {"cookies": [], "user_agent": None}

    async def _solve() -> Dict[str, object]:
        user_agent = get_chrome_user_agent()
        solver_user_agent: Optional[str] = user_agent
        all_cookies: List[dict] = []
        solver: Optional[CloudflareSolver] = None

        try:
            async with CloudflareSolver(
                cdp_url=None,
                user_agent=user_agent,
                timeout=45,
                proxy=proxy,
                browser_executable_path=browser_path,
            ) as solver_instance:
                solver = solver_instance
                await solver.driver.get(url)

                current_cookies = await solver.get_cookies()
                clearance_cookie = solver.extract_clearance_cookie(current_cookies)

                if clearance_cookie is None:
                    await solver.set_user_agent_metadata(await solver.get_user_agent())

                    challenge_platform = await solver.detect_challenge()
                    if challenge_platform:
                        st.info(
                            f"Detected Cloudflare {challenge_platform.value} challenge. Solving..."
                        )
                        await solver.solve_challenge()
                        all_cookies = await solver.get_cookies()
                    else:
                        st.warning("No Cloudflare challenge detected by solver.")
                        all_cookies = current_cookies
                else:
                    st.info("Cloudflare clearance cookie already present.")
                    all_cookies = current_cookies
        except Exception as err:
            st.error(f"An exception occurred during Cloudflare solving: {err}")
            return {"cookies": [], "user_agent": None}

        if solver:
            try:
                solver_user_agent = await solver.get_user_agent()
            except Exception:
                pass

        if solver and not solver.extract_clearance_cookie(all_cookies):
            st.warning("Solver finished, but cf_clearance cookie was not found.")

        return {"cookies": all_cookies, "user_agent": solver_user_agent}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_solve(), loop)
        return future.result()
    return asyncio.run(_solve())
