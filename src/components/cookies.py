from typing import Dict, List


def sanitize_cookies(cookies: List[Dict]) -> List[Dict]:
    """
    Sanitize cookie attributes to be compatible with Playwright.
    Playwright's `add_cookies` is strict and only accepts "Strict", "Lax", or "None".
    """
    sanitized: List[Dict] = []
    for cookie in cookies:
        if "partitionKey" in cookie:
            if isinstance(cookie["partitionKey"], str):
                pass
            elif isinstance(cookie["partitionKey"], dict):
                cookie.pop("partitionKey")
            else:
                cookie.pop("partitionKey")

        if "sameSite" in cookie:
            val = cookie["sameSite"].title()
            if val in ("Strict", "Lax", "None"):
                cookie["sameSite"] = val
            else:
                del cookie["sameSite"]
        sanitized.append(cookie)
    return sanitized

